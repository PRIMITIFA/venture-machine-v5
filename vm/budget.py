"""Hard money caps. Every paid call asks check() first, with an estimate, and is refused if it could pass the cap."""
from . import store
from .config import DEPTHS, S, cap_usd

PHASE1 = ["01", "02", "03", "04", "05"]

# Which venture/block is running now (set by the pipeline), so the ledger knows who spent what.
CURRENT = {"slug": None, "block": None}


class BudgetExceeded(Exception):
    pass


def _day_file(update=None):
    """Read (and optionally change) the shared spend record under a file lock, so parallel runs cannot lose each other's numbers."""
    import datetime as dt
    import fcntl
    import json
    f = S.spend_file
    f.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    with open(f, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            data = json.loads(fh.read() or "{}")
        except ValueError:
            data = {}
        day = data.setdefault(today, {"usd": 0.0, "calls": 0, "start_balance": None})
        if update:
            update(day)
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data, indent=1))
        return dict(day)


def day():
    """Today's recorded data spend: {'usd', 'calls', 'start_balance'}."""
    return _day_file()


def note_start_balance(balance):
    def up(d):
        if d.get("start_balance") is None:
            d["start_balance"] = float(balance)
    _day_file(up)


def day_check(est_usd):
    """The daily cap. It covers every paid call: any idea, any data folder, and lookups run by hand outside an idea."""
    spent = day()["usd"]
    if spent + est_usd > S.day_max_usd + 1e-9:
        raise BudgetExceeded(f"daily data cap ${S.day_max_usd:.2f}: ${spent:.2f} already spent today, next call needs ~${est_usd:.3f}. "
                             "Raise VM_DAY_MAX_USD to continue (the owner decides).")


def check(est_usd):
    day_check(est_usd)
    slug, blk = CURRENT["slug"], CURRENT["block"]
    if not slug:
        return
    total = store.spent(slug)
    v = store.venture(slug) or {}
    depth = (v.get("data") or {}).get("depth", "full")
    cap = cap_usd(depth)
    if total + est_usd > cap + 1e-9:
        raise BudgetExceeded(
            f"cap ${cap:.2f} for a {DEPTHS[depth]['label'].lower()}: spent ${total:.3f}, next call needs ~${est_usd:.3f}. "
            f"Raise {DEPTHS[depth]['cap_env']} to continue.")
    if blk in PHASE1:
        p1 = store.spent(slug, PHASE1)
        if p1 + est_usd > S.phase1_max_usd + 1e-9:
            raise BudgetExceeded(
                f"phase 1 cap ${S.phase1_max_usd:.2f}: spent ${p1:.3f}, next call needs ~${est_usd:.3f}. "
                f"Raise VM_PHASE1_MAX_USD to continue.")


def record(provider, endpoint, usd, counted=True, cached=False):
    store.ledger_add(CURRENT["slug"], CURRENT["block"], provider, endpoint, usd, counted, cached)
    if provider == "dataforseo" and not cached and usd:
        def up(d):
            d["usd"] = round(d["usd"] + float(usd), 4)
            d["calls"] += 1
        _day_file(up)

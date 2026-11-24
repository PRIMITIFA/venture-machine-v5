"""Hard money caps. Every paid call asks check() first, with an estimate, and is refused if it could pass the cap."""
from . import store
from .config import DEPTHS, S, cap_usd

PHASE1 = ["01", "02", "03", "04", "05"]

# Which venture/block is running now (set by the pipeline), so the ledger knows who spent what.
CURRENT = {"slug": None, "block": None}


class BudgetExceeded(Exception):
    pass


def check(est_usd):
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

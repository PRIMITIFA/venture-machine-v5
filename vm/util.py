import csv
import io
import json
import re
import statistics


def slugify(t, n=40):
    return re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-")[:n].strip("-") or "idea"


def extract_json(text):
    """Pull the largest JSON object out of a model reply (handles ```json fences and chatter)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    best = None
    for m in re.finditer(r"\{", text):
        try:
            v, end = dec.raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(v, dict) and (best is None or end > best[1]):
            best = (v, end)
    if best is None:
        raise ValueError("no JSON object found in the reply")
    return best[0]


def write_csv(path, rows, cols=None):
    rows = list(rows)
    cols = cols or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("; ".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def median(xs, default=0.0):
    xs = [x for x in xs if x]
    return statistics.median(xs) if xs else default


def domain_of(url):
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", str(url).strip().lower())
    return m.group(1) if m else ""


def pct_change(new, old):
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def md_table(rows, cols):
    if not rows:
        return "_none_\n"
    out = io.StringIO()
    out.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
    for r in rows:
        out.write("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |\n")
    return out.getvalue()


def has_number_or_source(line):
    return bool(re.search(r"\d", line) or re.search(r"https?://", line))


# ---------- buying demand (one definition, used by every block and the report) ----------
BUY_INTENTS = ("buy", "competitor", "brand-model")
# how much of a search counts as OUR buying demand: someone typing only a rival's name wants that rival's site
INTENT_VOLUME_W = {"buy": 1.0, "competitor": 1.0, "brand-model": 1.0, "brand": 0.1, "info": 0.0}


def is_buy(k):
    return k.get("intent") in BUY_INTENTS


def unique_searches(kws):
    """One row per real search. Google reports the SAME monthly volume and click price for close wordings of one search
    ('concrete calculator', 'calculator for concrete'): those are the same people, so they are counted once, not once per wording.
    Rows with the same volume and the same non-zero click price are one search; rows with no click price are only merged
    when they use the same words. The row kept is the shortest wording, with the lowest measured difficulty seen in the group."""
    groups = {}
    for k in kws:
        vol, cpc = num(k.get("volume")), num(k.get("cpc"))
        words = tuple(sorted(set(str(k.get("keyword", "")).lower().split())))
        key = (vol, cpc, k.get("intent")) if cpc > 0 else (vol, 0.0, k.get("intent"), words)
        groups.setdefault(key, []).append(k)
    out = []
    for g in groups.values():
        best = dict(min(g, key=lambda k: len(str(k.get("keyword", "")))))
        kds = [num(k.get("kd")) for k in g if k.get("kd") not in ("", None)]
        if kds:  # a 0 usually means "not measured": prefer a measured difficulty when the group has one
            best["kd"] = min([x for x in kds if x > 0] or kds)
        best["wordings"] = len(g)
        out.append(best)
    return out


def buy_volume(kws):
    """Searches a month that count as buying demand: commercial searches in full, a rival's bare brand name at 10%.
    Close wordings of one search are counted once (see unique_searches)."""
    return sum(num(k.get("volume")) * INTENT_VOLUME_W.get(k.get("intent"), 0.0) for k in unique_searches(kws))


def volume_split(kws):
    out = {"commercial": 0, "brand": 0, "info": 0}
    for k in unique_searches(kws):
        out["commercial" if is_buy(k) else "brand" if k.get("intent") == "brand" else "info"] += num(k.get("volume"))
    return {k: int(v) for k, v in out.items()}


def weighted_cpc(kws):
    """Ad click price averaged by search volume over the commercial searches (a keyword with no price counts as $0)."""
    buy = [k for k in unique_searches(kws) if is_buy(k)]
    vol = sum(num(k.get("volume")) for k in buy)
    return round(sum(num(k.get("cpc")) * num(k.get("volume")) for k in buy) / vol, 2) if vol else 0.0

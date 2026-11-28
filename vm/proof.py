"""Revenue proof: real businesses with payment-verified revenue, used to price and size an idea.

Why this exists: a keyword count measures ONE channel (free search). A niche with almost no search volume can still
carry a business that sells at a high price through ads or social (an exam course that keyword tools rate at
"about 90 visits a month" made $42k in 30 days). So before anything is scored, the machine looks for real businesses
in the niche and uses what THEY earn, charge and get per visitor.

Source: TrustMRR (https://trustmrr.com), where revenue is read from the startup's payment provider. Needs
TRUSTMRR_API_KEY. The pulled rows are kept in <data folder>/trustmrr/ and never leave the machine.
"""
import json
import re
import statistics
import subprocess
import time

import httpx
from pydantic import BaseModel, Field

from . import ai, store
from .config import S

API = "https://trustmrr.com/api/v1/startups"
BANDS = [("under 2,000", 0, 2000), ("2,000 to 35,000", 2000, 35000), ("35,000 to 130,000", 35000, 130000), ("over 130,000", 130000, 10 ** 12)]
STOP = set("a an and the for of to in on with your you our we is are be it that this from by at as or how what best free online app apps tool tools "
           "website site platform service business people who want would pay get make help helps their them can using use into more all any new one".split())


def folder():
    d = S.data_dir / "trustmrr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def available():
    return bool(S.trustmrr_key)


def _get(url, params=None):
    for _ in range(5):
        r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {S.trustmrr_key}"}, timeout=40)
        if r.status_code == 429:
            time.sleep(min(int(r.headers.get("retry-after", "30")), 90))
            continue
        r.raise_for_status()
        left = r.headers.get("x-ratelimit-remaining")
        return r.json(), (int(left) if left and left.isdigit() else None)
    raise RuntimeError("TrustMRR kept answering 'too many requests'")


def sync(min_usd=500, max_usd=5_000_000, say=print, max_pages=2000):
    """Pull every startup with last-30-day revenue in the range (10 a page, 10 requests a minute on a standard key)."""
    out, page = [], 1
    name = folder() / f"band{int(min_usd)}-{int(max_usd)}.json"
    while page <= max_pages:
        j, left = _get(API, {"minRevenue": int(min_usd), "maxRevenue": int(max_usd), "sort": "revenue-desc", "limit": 10, "page": page})
        out += j["data"]
        if page == 1:
            say(f"{j['meta']['total']} startups earn ${min_usd:,.0f} to ${max_usd:,.0f} in 30 days")
        name.write_text(json.dumps(out), encoding="utf-8")
        if not j["meta"]["hasMore"]:
            break
        time.sleep(6.5 if (left is None or left > 1) else 30)
        page += 1
    say(f"saved {len(out)} rows to {name}")
    return len(out)


def rows():
    """Every pulled startup, one row per slug (the newest file wins)."""
    seen = {}
    for f in sorted(folder().glob("band*.json"), key=lambda p: p.stat().st_mtime):
        try:
            for x in json.loads(f.read_text(encoding="utf-8")):
                if x.get("slug"):
                    seen[x["slug"]] = x
        except (ValueError, OSError):
            continue
    return list(seen.values())


def rev30(x):
    return float(((x.get("revenue") or {}).get("last30Days")) or 0)


def detail(slug):
    """Full profile of one startup (price, domain strength, channels), cached for 30 days."""
    key = f"trustmrr:detail:{slug}"
    hit = store.cache_get(key, 30)
    if hit is not None:
        return hit
    j, left = _get(f"{API}/{slug}")
    d = j.get("data", j)
    store.cache_put(key, d)
    time.sleep(6.5 if (left is None or left > 1) else 30)
    return d


# ---------------- how far off the tools are (back-tested 2026-11-27) ----------------
# Measured against businesses with payment-verified revenue and their own connected Google data (TrustMRR).
# Re-measure with the back-test scripts when the data is refreshed; these are the numbers every estimate must carry.
BACKTEST = {
    "date": "2026-11-27",
    "businesses": 2268,
    # a keyword tool's "estimated Google visits" for a small site, against that site's real Google clicks (134 sites)
    "tool_traffic_times_too_low": {"typical": 21, "low": 8, "high": 34},
    # share of the search demand a site really gets on the searches it ranks for in the top 30 (25 sites)
    "share_of_ranked_demand": {"typical": 0.12, "low": 0.05, "high": 0.18},
    # hiding each business and predicting its revenue from everything knowable (tool numbers, age, buyer type, model)
    "typical_miss_factor": 2.3,
    # of businesses that earn $500+ in 30 days
    "base": {"typical_usd": 2212, "upper_quarter_usd": 6894, "top_tenth_usd": 23918, "share_at_10k": 0.20,
             "under_6_months": {"typical_usd": 1495, "share_at_10k": 0.15}, "over_4_years": {"typical_usd": 4227, "share_at_10k": 0.33},
             "b2b": {"typical_usd": 2532, "share_at_10k": 0.21}, "b2c": {"typical_usd": 1601, "share_at_10k": 0.14}},
}


# share of a year's buyers that one site captures. Leader: Tree Nerd Academy took about 22% of a year's ISA applicants in its
# first year and runs near 39% (one back-test, 2026-11-27). Newcomer against established rivals: an assumption, not measured.
SHARES = {"newcomer": (0.02, 0.05, 0.08), "leader": (0.20, 0.30, 0.40)}


def people_estimate(buyers_per_year, price_usd):
    """Size a niche by counting the buyers: people who face the exam (or need the thing) each year x share captured x price.
    The only estimate that matched a real business in back-testing, and it needs no keyword or ad data. None when a number is missing."""
    try:
        n, p = float(buyers_per_year or 0), float(price_usd or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0 or p <= 0:
        return None
    out = {"buyers_per_year": int(n), "price_usd": p}
    for who, (lo, mid, hi) in SHARES.items():
        out[who] = {"share": (lo, mid, hi), "month_usd": (round(n * lo * p / 12), round(n * mid * p / 12), round(n * hi * p / 12))}
    return out


def honest_range(mid):
    """A revenue figure is never one number: with everything knowable, the typical miss is about 2.3 times either way."""
    f = BACKTEST["typical_miss_factor"]
    return round(mid / f), round(mid), round(mid * f)


# ---------------- what real sites earn per visitor ----------------
def calibration(rs=None):
    """Earnings per visitor of real businesses, by traffic size. Small narrow sites earn dollars a visitor, big free tools cents."""
    rs = rows() if rs is None else rs
    v = [x for x in rs if (x.get("visitorsLast30Days") or 0) >= 30 and (x.get("revenuePerVisitor") or 0) > 0 and rev30(x) >= 500]
    out = []
    for name, lo, hi in BANDS:
        g = sorted(float(x["revenuePerVisitor"]) for x in v if lo <= x["visitorsLast30Days"] < hi)
        if len(g) < 4:
            out.append({"visitors_month": name, "lo": lo, "hi": hi, "n": len(g)})
            continue
        q = lambda p: g[min(len(g) - 1, int(p * len(g)))]  # noqa: E731
        out.append({"visitors_month": name, "lo": lo, "hi": hi, "n": len(g), "low": round(q(.25), 2), "median": round(statistics.median(g), 2), "high": round(q(.75), 2)})
    return out


def per_visitor(visitors, cal=None):
    """(low, median, high) dollars a visitor for a site of this size, or None when there is not enough data."""
    for b in (calibration() if cal is None else cal):
        if b["lo"] <= visitors < b["hi"] and "median" in b:
            return b["low"], b["median"], b["high"]
    return None


def predict(visitors, cal=None):
    """Monthly revenue range for a site with this many visitors, from what real sites of that size earn per visitor."""
    pv = per_visitor(visitors, cal)
    if not pv:
        return None
    return {"visitors": int(visitors), "per_visitor": pv, "low": round(visitors * pv[0]), "mid": round(visitors * pv[1]), "high": round(visitors * pv[2])}


# ---------------- real businesses in the same niche ----------------
def words(t):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()) if w not in STOP}


def shortlist(text, rs=None, n=40):
    """Cheap first pass: startups whose name, description or category share words with the idea. The AI then picks the real matches."""
    rs = rows() if rs is None else rs
    want = words(text)
    scored = []
    for x in rs:
        if not x.get("website") or "trustmrr.com" in (x.get("website") or ""):
            continue
        have = words(f"{x.get('name')} {x.get('description')} {x.get('category')}")
        hit = want & have
        if hit:
            scored.append((len(hit) + min(rev30(x), 50000) / 500000, x))
    scored.sort(key=lambda t: -t[0])
    return [x for _s, x in scored[:n]]


class Pick(BaseModel):
    slug: str
    why: str = Field(description="one short plain sentence: same buyer, or the same kind of product for a similar buyer")
    closeness: int = Field(ge=1, le=3, description="3 = same niche and buyer; 2 = same kind of product, other niche; 1 = only loosely alike")


class Picks(BaseModel):
    picks: list[Pick] = Field(default=[], description="only startups that are a real comparison for this idea; an empty list is a fine answer")


def brief(x):
    return {"slug": x["slug"], "name": x.get("name"), "website": x.get("website"), "category": x.get("category"), "audience": x.get("targetAudience"),
            "revenue_30d_usd": round(rev30(x)), "what": (x.get("description") or "")[:220]}


def card(x, d=None):
    """The facts about one real business that matter for sizing an idea."""
    d = d or {}
    si = d.get("startupInsights") or {}
    r = x.get("revenue") or {}
    return {"name": x.get("name"), "slug": x["slug"], "website": x.get("website"), "page": f"https://trustmrr.com/startup/{x['slug']}",
            "revenue_30d_usd": round(rev30(x)), "mrr_usd": round(float(r.get("mrr") or 0)), "revenue_total_usd": round(float(r.get("total") or 0)),
            "founded": (x.get("foundedDate") or "")[:7], "visitors_30d": x.get("visitorsLast30Days"), "revenue_per_visitor": x.get("revenuePerVisitor"),
            "growth_30d_pct": round(float(x.get("growth30d") or 0)), "price": si.get("pricingModel") or "", "buyers": si.get("targetPersona") or "",
            "users": si.get("estimatedUserCount"), "domain_rating": d.get("domainRating"),
            "channels": [c.get("slug") for c in (d.get("marketingChannels") or [])], "paid_channels": [c.get("slug") for c in (d.get("marketingChannels") or []) if c.get("category") == "paid"]}


def comparables(idea, extra_terms=(), max_n=6):
    """Real businesses with verified revenue that compare to this idea. Returns [] when nothing compares (which is also a finding)."""
    rs = rows()
    sl = shortlist(idea + " " + " ".join(extra_terms), rs)
    if not sl:
        return []
    out = ai.ask_json(
        "Pick the startups below that are a REAL comparison for this idea: the same buyer, or the same kind of product sold to a similar buyer. "
        "Be strict: sharing a word is not enough. An empty list is a fine answer.\n\nIdea:\n" + idea,
        Picks, smart=False, context=[brief(x) for x in sl])
    by = {x["slug"]: x for x in sl}
    got = []
    for p in sorted(out.picks, key=lambda p: -p.closeness):
        x = by.get(p.slug)
        if not x or len(got) >= max_n:
            continue
        try:
            d = detail(x["slug"])
        except Exception:  # the list row alone is still useful
            d = {}
        got.append(card(x, d) | {"why": p.why, "closeness": p.closeness})
    return got


# ---------------- do the rivals buy ads? ----------------
SHARED_HOSTS = {"apps.apple.com", "play.google.com", "chromewebstore.google.com", "udemy.com", "amazon.com", "etsy.com", "gumroad.com", "youtube.com",
                "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com", "github.com", "fiverr.com", "tiktok.com", "substack.com", "trustmrr.com"}


def read_page(url, max_chars=6000):
    """Read a page through the owner's browser command (VM_BROWSER_CMD), for pages that need a real browser. '' when not set or blocked."""
    cmd = S.browser_cmd
    if not cmd:
        return ""
    try:
        p = subprocess.run(cmd.split() + [url, "--max", str(max_chars)], capture_output=True, text=True, timeout=120)
        j = json.loads(p.stdout)
        return j.get("text", "") if j.get("status") == "ok" else ""
    except Exception:
        return ""


def ads(name, domain):
    """How many ads a rival runs, from the two public ad libraries. None = could not be checked (never read that as zero)."""
    if domain in SHARED_HOSTS:   # an app-store or marketplace page is not the rival's own domain: many rivals share it
        domain = ""
    out = {"name": name, "domain": domain, "meta_ads": None, "google_ads": None}
    if not S.browser_cmd:
        return out
    key = f"proof:ads:{domain}" if domain else f"proof:ads:name:{name.lower()}"
    hit = store.cache_get(key, 14)
    if hit is not None:
        return hit
    from urllib.parse import quote
    t = read_page("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&search_type=keyword_exact_phrase&q=" + quote(f'"{name}"'))
    m = re.search(r"~?([\d,]+)\s+results?", t)
    if m:
        out["meta_ads"] = int(m.group(1).replace(",", ""))
    elif "No ads match" in t or "0 results" in t:
        out["meta_ads"] = 0
    if domain:
        t = read_page(f"https://adstransparency.google.com/?region=US&hl=en&domain={domain}")
        m = re.search(r"([\d,]+)\+?\s+ads?\b", t)
        if m:
            out["google_ads"] = int(m.group(1).replace(",", ""))
        elif "No ads found" in t:
            out["google_ads"] = 0
    store.cache_put(key, out)
    return out


def _read_raw(url, max_chars=30000):
    """Page text through the owner's browser command whatever the status ('' when the command is not set or failed)."""
    if not S.browser_cmd:
        return ""
    try:
        p = subprocess.run(S.browser_cmd.split() + [url, "--max", str(max_chars)], capture_output=True, text=True, timeout=120)
        return json.loads(p.stdout).get("text", "") or ""
    except Exception:
        return ""


def reviews(domain):
    """Public buyer reviews of a rival on Trustpilot: how many, the rating, how many in the last 12 months, and what the
    1 and 2 star reviewers complain about. Every review is a real past customer, so the count is a floor on buyers.
    checked False = could not be read (never read that as 'no reviews'); found False = the rival has no profile."""
    out = {"domain": domain, "source": "trustpilot", "url": f"https://www.trustpilot.com/review/{domain}", "checked": False, "found": False,
           "count": None, "rating": None, "last_12_months": None, "low_star_pct": None, "summary": "", "low_star_text": ""}
    if not S.browser_cmd or not domain or domain in SHARED_HOSTS:
        return out
    key = f"proof:reviews:{domain}"
    hit = store.cache_get(key, 14)
    if hit is not None:
        return hit
    t = _read_raw(out["url"] + "?stars=1&stars=2")
    if not t:
        return out
    out["checked"] = True
    m = re.search(r"All reviews\s*\(([\d,]+)\)", t) or re.search(r"Reviews\s+([\d,]+)", t)
    if "could not be found" in t or not m:
        store.cache_put(key, out)
        return out
    out["found"] = True
    out["count"] = int(m.group(1).replace(",", ""))
    m = re.search(r"\n\s*([1-5]\.\d)\s*\n", t)
    out["rating"] = float(m.group(1)) if (m and out["count"]) else None   # a profile with no reviews shows a placeholder rating
    m = re.search(r"([\d,]+) reviews? in the last 12 months", t)
    out["last_12_months"] = int(m.group(1).replace(",", "")) if m else None
    low = [int(x) for x in re.findall(r"[12]-star\s*(\d+)%", t)[:2]]
    out["low_star_pct"] = sum(low) if low else None
    m = re.search(r"(Evaluating [\d,]+ reviews?,.*?)(?:See more|\n\n)", t, re.S)
    out["summary"] = re.sub(r"\s+", " ", m.group(1)).strip()[:600] if m else ""
    i = t.find("Reset\n")
    if i > 0 and out["low_star_pct"]:
        body = re.sub(r"Reply from .*?(?=\nAdvertisement|\n[A-Z]{2}\n|$)", "", t[i + 6:], flags=re.S)   # the rival's own replies are not buyer words
        out["low_star_text"] = re.sub(r"\n{2,}", "\n", body).strip()[:3000]
    store.cache_put(key, out)
    return out


def summary(pr):
    """One plain line for the step result."""
    comps = pr.get("comparables") or []
    if not pr.get("checked"):
        return "revenue proof not checked (no TRUSTMRR_API_KEY or no data pulled: run 'vm proof sync')"
    if not comps:
        return "no real business with verified revenue found in this niche"
    best = max(comps, key=lambda x: x["revenue_30d_usd"])
    line = f"{len(comps)} real businesses with verified revenue (best: {best['name']} ${best['revenue_30d_usd']:,} in 30 days" + (f", price {best['price'][:60]}" if best.get("price") else "") + ")"
    paid = [a for a in pr.get("ads") or [] if (a.get("meta_ads") or 0) + (a.get("google_ads") or 0) > 0]
    if paid:
        line += "; rivals buying ads: " + ", ".join(f"{a['name']} ({(a.get('meta_ads') or 0) + (a.get('google_ads') or 0)})" for a in paid[:3])
    return line


def best_revenue(pr):
    """Highest verified 30-day revenue among close comparables (closeness 2 or 3). 0 when none."""
    return max([x["revenue_30d_usd"] for x in (pr or {}).get("comparables") or [] if x.get("closeness", 1) >= 2] or [0])


# ---------------- find niches from the revenue data ----------------
CROWDED = {"Artificial Intelligence", "Marketing", "Developer Tools", "Social Media", "Analytics", "Content Creation", "Crypto & Web3", "No-Code", "Design Tools", "Sales", "Customer Support"}


def discover(min_usd=5000, max_usd=150000, since="2024-01", include_crowded=False):
    """Named startups in the revenue range, youngest money first: places where a small new site already earns."""
    out = []
    for x in rows():
        if not (min_usd <= rev30(x) <= max_usd) or not x.get("website") or "Anonymous" in (x.get("name") or "") or "trustmrr.com" in x["website"]:
            continue
        if not include_crowded and x.get("category") in CROWDED:
            continue
        if since and (x.get("foundedDate") or "0000")[:7] < since:
            continue
        out.append(card(x))
    out.sort(key=lambda c: -c["revenue_30d_usd"])
    return out

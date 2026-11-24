"""PHASE 2: DEMAND + SEO (blocks 06-09). Real search demand, live SERPs, clusters (1 cluster = 1 page),
and the real top-5 competitors for phase 3. All raw API data is cached 30 days; spend is capped."""
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from .. import ai, seo
from ..config import K, S
from ..pipeline import Result
from ..util import domain_of, num, pct_change, read_csv, write_csv

INTENT_W = {"buy": 1.5, "competitor": 1.3, "brand-model": 1.2, "info": 0.6}


# ---------------- 06 Seeds ----------------
class Seed(BaseModel):
    keyword: str
    category: Literal["buy", "product", "brand-model", "competitor", "synonym", "modifier", "info"]
    source: str = Field(description="where it came from: forum quote, competitor site, synonym, modifier...")


class Seeds(BaseModel):
    seeds: list[Seed]


def b06_seeds(c):
    how, pulse = c.read("02_how_analysis.json"), c.read("04_niche_pulse.json")
    out = ai.ask_json(
        f"""Block 06. Build 30-60 seed keywords (lowercase, how buyers type them, plain ASCII letters/digits only) for:
{c.v['one_liner']}
Expand the key terms {c.v['data'].get('key_terms')} with synonyms, slang, brand/model names, modifiers
("free", "cost", "price", "near me", "alternative", "vs", "online", "check", "report") and competitor names.
Cover buying words, product names, brands and competitors. Language: {c.lang}. Country: {c.v['country']}.{c.note()}""",
        Seeds, smart=False, context={"competitors": [x["name"] for x in how["competitors"]],
                                     "rising_synonyms": pulse.get("rising_synonyms"), "key_terms": c.v["data"].get("key_terms")})
    seen, rows = set(), []
    for s in out.seeds:
        k = seo.clean_kw(s.keyword)
        if k and k not in seen:
            seen.add(k)
            rows.append({"seed_keyword": k, "category": s.category, "source": s.source})
    write_csv(c.path("06_seeds.csv"), rows, ["seed_keyword", "category", "source"])
    n, buy = len(rows), sum(r["category"] in ("buy", "competitor", "product", "brand-model") for r in rows)
    if n < 30 or n > 60:
        return Result("redo", f"{n} seeds; need 30-60")
    if buy < 8:
        return Result("redo", f"only {buy} buying/product/competitor seeds; need more buying words")
    return Result("pass", f"{n} seeds ({buy} buying/product/competitor)")


# ---------------- 07 Volume, CPC, cleaning ----------------
class Label(BaseModel):
    keyword: str
    intent: Literal["buy", "competitor", "brand-model", "info"]
    junk: bool = Field(description="true if unrelated to the business, wrong meaning, or a navigational query for a giant")


class Labels(BaseModel):
    labels: list[Label]


def _trend12(monthly):
    if not monthly or len(monthly) < 6:
        return None
    m = sorted(monthly, key=lambda x: (x.get("year", 0), x.get("month", 0)))
    first = sum(num(x.get("search_volume")) for x in m[:3]) / 3
    last = sum(num(x.get("search_volume")) for x in m[-3:]) / 3
    return pct_change(last, first)


def b07_volumes(c):
    seeds = read_csv(c.path("06_seeds.csv"))
    kws = [s["seed_keyword"] for s in seeds]
    srcmap = {s["seed_keyword"]: "seed:" + s["category"] for s in seeds}
    rows = {}
    for r in seo.search_volume(kws, c.loc, c.lang):
        rows[r["keyword"]] = {"keyword": r["keyword"], "volume": r.get("search_volume") or 0, "cpc": r.get("cpc") or 0,
                              "cpc_low": r.get("low_top_of_page_bid") or 0, "cpc_high": r.get("high_top_of_page_bid") or 0,
                              "competition": r.get("competition") or "", "trend12": _trend12(r.get("monthly_searches")),
                              "source": "google_ads " + srcmap.get(r["keyword"], "seed")}
    # real long-tail from the 3 strongest buying seeds
    buy_seeds = sorted([s for s in seeds if s["category"] in ("buy", "product")],
                       key=lambda s: -num(rows.get(s["seed_keyword"], {}).get("volume")))[:K("suggest_seeds")]
    for s in buy_seeds:
        for it in seo.suggestions(s["seed_keyword"], c.loc, c.lang, limit=K("suggest_limit")):
            k = it.get("keyword")
            ki = it.get("keyword_info") or {}
            if k and k not in rows:
                rows[k] = {"keyword": k, "volume": ki.get("search_volume") or 0, "cpc": ki.get("cpc") or 0,
                           "cpc_low": ki.get("low_top_of_page_bid") or 0, "cpc_high": ki.get("high_top_of_page_bid") or 0,
                           "competition": ki.get("competition_level") or "", "trend12": _trend12(ki.get("monthly_searches")),
                           "source": f"dataforseo_labs suggestions of '{s['seed_keyword']}'"}
    kept = [r for r in rows.values() if num(r["volume"]) >= 20 or num(r["cpc"]) > 3.0]
    dropped = len(rows) - len(kept)
    labels = {}
    for i in range(0, len(kept), 150):
        chunk = [r["keyword"] for r in kept[i:i + 150]]
        out = ai.ask_json(
            f"""Block 07. Label each keyword for this business: {c.v['one_liner']}
intent: buy (wants to pay/use a product now), competitor (names a competitor or 'X alternative'),
brand-model (a brand/model/specific item), info (wants to learn). junk=true if unrelated or wrong meaning.
Return one label per keyword, same spelling.{c.note()}""",
            Labels, smart=False, context={"keywords": chunk})
        labels.update({l.keyword.strip().lower(): l for l in out.labels})
    fetched = __import__("datetime").date.today().isoformat()
    clean = []
    for r in kept:
        lab = labels.get(r["keyword"].lower())
        if lab and lab.junk:
            continue
        r["intent"] = lab.intent if lab else "info"
        r["fetched_at"] = fetched
        clean.append(r)
    clean.sort(key=lambda r: -num(r["volume"]))
    write_csv(c.path("08_keywords_clean.csv"), clean,
              ["keyword", "volume", "cpc", "cpc_low", "cpc_high", "competition", "trend12", "intent", "source", "fetched_at"])
    buy = [r for r in clean if r["intent"] in ("buy", "competitor", "brand-model")]
    buy_vol = sum(num(r["volume"]) for r in buy)
    max_cpc = max([num(r["cpc"]) for r in buy] or [0])
    summary = f"{len(clean)} clean keywords ({dropped} dropped <20/mo); buying volume {int(buy_vol)}/mo; top buying CPC ${max_cpc:.2f}"
    if not clean:
        return Result("redo", "no keyword has volume >= 20; seeds are too narrow or wrong language")
    if buy_vol >= 1000 or max_cpc >= 2.0:
        lowcpc = buy_vol >= 10000 and max_cpc < 0.30
        return Result("warn" if lowcpc else "pass", summary + ("; WARNING high volume with CPC < $0.30 rarely converts" if lowcpc else ""))
    return Result("warn", summary + "; below the bar (buying volume >= 1,000/mo OR CPC >= $2)")


# ---------------- 08 SERP + clusters ----------------
FORUMS = ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com", "forum", "community.", "boards.", "facebook.com/groups")


def page_format(domain, url, title):
    u, t = (url or "").lower(), (title or "").lower()
    if any(f in domain or f in u for f in FORUMS):
        return "forum"
    if any(w in t for w in ("calculator", "checker", "lookup", "generator", "tool", "converter", "decoder", "search", "finder", "estimator")):
        return "tool"
    if domain in ("amazon.com", "ebay.com", "etsy.com", "walmart.com") or any(w in u for w in ("/product", "/shop", "/pricing", "/buy", "/plans")):
        return "product"
    if any(w in domain or w in t for w in ("directory", "yelp", "list of", "top 10", "best ")):
        return "directory"
    return "guide"


def cluster(serps, min_shared=4):
    """Greedy: biggest keyword starts a cluster; a keyword joins when its top-10 shares >= 4 URLs with the cluster head."""
    out = []
    for s in sorted(serps, key=lambda s: -num(s.get("volume"))):
        urls = {o.get("key") or o["url"] for o in s["organic"] if o["rank"] and o["rank"] <= 10}
        for cl in out:
            if len(urls & cl["head_urls"]) >= min_shared:
                cl["keywords"].append(s["keyword"])
                cl["volume"] += num(s.get("volume"))
                break
        else:
            out.append({"head": s["keyword"], "head_urls": urls, "keywords": [s["keyword"]], "volume": num(s.get("volume")), "serp": s})
    return out


def b08_serp_clusters(c):
    kws = read_csv(c.path("08_keywords_clean.csv"))
    for k in kws:
        k["prio"] = num(k["volume"]) * max(num(k["cpc"]), 0.30) * INTENT_W.get(k["intent"], 0.6)
    top = sorted(kws, key=lambda k: -k["prio"])[:K("max_serps")]
    raw = seo.serps([k["keyword"] for k in top], c.loc, c.lang)
    meta = {k["keyword"]: k for k in top}
    for s in raw:
        m = meta.get(s["keyword"], {})
        s["volume"], s["intent"], s["cpc"] = num(m.get("volume")), m.get("intent", "info"), num(m.get("cpc"))
    c.write("09_serp_raw.json", raw)
    ok = [s for s in raw if not s.get("error") and s["organic"]]
    top10_domains = {o["domain"] for s in ok for o in s["organic"] if o["rank"] and o["rank"] <= 10}
    ranks = seo.domain_ranks(top10_domains) if top10_domains else {}
    clusters = []
    for i, cl in enumerate(cluster(ok), 1):
        s = cl["serp"]
        top5 = [o for o in s["organic"] if o["rank"] and o["rank"] <= 5]
        top10 = [o for o in s["organic"] if o["rank"] and o["rank"] <= 10]
        fmts = Counter(page_format(o["domain"], o["url"], o["title"]) for o in top5)
        weak = []
        if any(page_format(o["domain"], o["url"], o["title"]) == "forum" for o in top10):
            weak.append("forum/Reddit in top 10")
        low = [o["domain"] for o in top10 if ranks.get(o["domain"]) and ranks[o["domain"]] < 20]  # 0 = no data
        if low:
            weak.append(f"DR<20 in top 10 ({', '.join(sorted(set(low))[:3])})")
        if s["features"].get("paid", 0) >= 3:
            weak.append("ads on top")
        better_format = fmts.get("tool", 0) == 0 and s["intent"] in ("buy", "brand-model")
        top5_dr = [ranks.get(o["domain"]) for o in top5 if ranks.get(o["domain"])]
        clusters.append({
            "id": i, "head": cl["head"], "keywords": cl["keywords"], "volume": cl["volume"], "intent": s["intent"],
            "cpc": s["cpc"], "features": s["features"], "winning_format": fmts.most_common(1)[0][0] if fmts else "unknown",
            "formats_top5": dict(fmts), "weak_spots": weak, "better_format_possible": better_format,
            "top5_min_dr": min(top5_dr) if top5_dr else None, "top5_all_dr60": bool(top5_dr) and min(top5_dr) >= 60,
            "top10": [{"rank": o["rank"], "domain": o["domain"], "url": o["url"], "title": o["title"], "dr": ranks.get(o["domain"])} for o in top10],
        })
    c.write("10_clusters_serp.json", clusters)
    fetched = len(ok) / max(len(raw), 1)
    opp = sum(1 for cl in clusters if cl["weak_spots"] or cl["better_format_possible"]) / max(len(clusters), 1)
    hard = sum(1 for cl in clusters if cl["top5_all_dr60"]) / max(len(clusters), 1)
    summary = (f"{len(ok)}/{len(raw)} SERPs; {len(clusters)} clusters; {opp:.0%} with a weak spot or better-format chance; "
               f"{hard:.0%} have all top-5 DR 60+")
    if fetched < 0.9:
        return Result("redo", summary + "; too many SERPs failed")
    if hard > 0.8:
        return Result("warn", summary + "; start with B2B/API/long-tail")
    return Result("pass" if opp >= 0.30 else "warn", summary)


# ---------------- 09 KD, shortlist, top-5 competitors ----------------
def score(volume, cpc, intent, kd, trend12=None):
    s = num(volume) * max(num(cpc), 0.30) * INTENT_W.get(intent, 0.6) / (num(kd) + 5)
    if trend12 is not None and trend12 != "" and num(trend12) > 10:
        s *= 1.15
    return round(s, 2)


def b09_shortlist(c):
    clusters = c.read("10_clusters_serp.json")
    kws = {k["keyword"]: k for k in read_csv(c.path("08_keywords_clean.csv"))}
    kd = seo.keyword_difficulty(list(kws), c.loc, c.lang)
    rows = []
    for k, r in kws.items():
        d = kd.get(k)
        r["kd"] = d if d is not None else ""
        r["kd_band"] = ("0-10 content only" if d is not None and d <= 10 else "10-30 a few links" if d is not None and d <= 30
                        else "30-50 serious links" if d is not None and d <= 50 else "50+ skip for new site" if d is not None else "unknown")
        r["score"] = score(r["volume"], r["cpc"], r["intent"], d if d is not None else 30, r.get("trend12"))
        rows.append(r)
    for cl in clusters:
        h = kws.get(cl["head"], {})
        cl["kd"] = h.get("kd", "")
        cl["score"] = round(sum(kws[k]["score"] for k in cl["keywords"] if k in kws), 2)
    clusters.sort(key=lambda cl: -cl["score"])
    c.write("10_clusters_serp.json", clusters)
    rows.sort(key=lambda r: -r["score"])
    main_heads = [cl["head"] for cl in clusters[:5]]
    long_tail = [r for r in rows if r["keyword"] not in main_heads and r["kd"] != "" and num(r["kd"]) <= 20][:40]
    short = [dict(r, role="main") for r in rows if r["keyword"] in main_heads] + [dict(r, role="long-tail") for r in long_tail]
    write_csv(c.path("11_shortlist.csv"), short, ["role", "keyword", "volume", "cpc", "intent", "kd", "kd_band", "trend12", "score", "source"])
    write_csv(c.path("11_keywords_scored.csv"), rows, ["keyword", "volume", "cpc", "intent", "kd", "kd_band", "trend12", "score", "source"])
    # real competitors: position weight across all SERPs, giants/platforms excluded
    weight, dr, seen_in = defaultdict(float), {}, defaultdict(int)
    for cl in clusters:
        for o in cl["top10"]:
            if seo.not_competitor(o["domain"]):
                continue
            weight[o["domain"]] += (11 - o["rank"]) * (1 + num(cl["volume"]) / 1000)
            seen_in[o["domain"]] += 1
            dr[o["domain"]] = o.get("dr")
    how = c.read("02_how_analysis.json")
    known = {domain_of(x["url"]) for x in how["competitors"]}
    comps = [{"domain": d, "weight": round(w, 1), "serps": seen_in[d], "dr": dr.get(d), "known_in_02": d in known}
             for d, w in sorted(weight.items(), key=lambda x: -x[1])[:5]]
    c.write("11_top_competitors.json", comps)
    top20 = clusters[:20]
    buy_clusters = sum(1 for cl in top20 if cl["intent"] in ("buy", "competitor", "brand-model"))
    buy_easy = sum(1 for r in rows if r["intent"] in ("buy", "competitor", "brand-model") and r["kd"] != "" and num(r["kd"]) <= 20)
    hard_all = all(num(r["kd"]) >= 50 for r in rows if r["kd"] != "")
    summary = (f"{buy_clusters} buying clusters in top 20; {buy_easy} buying keywords KD<=20; "
               f"top competitors: {', '.join(x['domain'] for x in comps)}")
    if not comps:
        return Result("redo", "no real competitor domain found in the SERPs")
    if all(r["intent"] == "info" for r in rows):
        return Result("warn", summary + "; only info keywords: go back to 06 with buying seeds (vm rerun <slug> 06)")
    if hard_all:
        return Result("warn", summary + "; everything KD 50+: plan a non-SEO first channel")
    if buy_clusters >= 10 and buy_easy >= 10:
        return Result("pass", summary)
    return Result("warn", summary + "; below the bar (>=10 buying clusters AND >=10 buying keywords KD<=20)")

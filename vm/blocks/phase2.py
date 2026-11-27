"""PHASE 2: DEMAND + SEO (blocks 06-09). Real search demand, live SERPs, clusters (1 cluster = 1 page),
and the real top-5 competitors for phase 3. All raw API data is cached 30 days; spend is capped."""
import re
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from .. import ai, seo
from ..config import K, S
from ..pipeline import Result
from .. import store
from ..util import BUY_INTENTS, buy_volume, domain_of, is_buy, num, pct_change, read_csv, volume_split, write_csv, unique_searches

INTENT_W = {"buy": 1.5, "competitor": 1.3, "brand-model": 1.2, "brand": 0.4, "info": 0.6}
INTENTS = Literal["buy", "competitor", "brand", "brand-model", "info"]
INTENT_HELP = """intent: buy (wants to pay for or use a product like ours now); competitor (a rival's name PLUS a comparing word:
"X alternative", "X vs Y", "X review", "X pricing"); brand (ONLY a rival's brand or product name, nothing else: the searcher
wants to go to that rival's site); brand-model (a specific item or model the buyer wants from us); info (wants to learn, wants
a course or a guide, or is a seller/freelancer looking for tips)."""
KW_COLS = ["keyword", "volume", "cpc", "cpc_low", "cpc_high", "competition", "trend12", "intent", "source", "fetched_at"]


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
    intent: INTENTS
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
{INTENT_HELP}
junk=true if unrelated or wrong meaning.
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
    write_csv(c.path("08_keywords_clean.csv"), clean, KW_COLS)
    buy = [r for r in clean if is_buy(r)]
    buy_vol = buy_volume(clean)
    sp = volume_split(clean)
    max_cpc = max([num(r["cpc"]) for r in buy] or [0])
    summary = (f"{len(clean)} clean keywords ({dropped} dropped <20/mo); buying volume {int(buy_vol)}/mo "
               f"(commercial {sp['commercial']}, rival brand names {sp['brand']} counted at 10%, info {sp['info']} not counted); top buying CPC ${max_cpc:.2f}")
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


class SerpCheck(BaseModel):
    keyword: str
    on_topic: bool = Field(description="true only if the pages Google shows for this search are about the same thing as this business. "
                                       "false if the word means something else there (another field, an acronym, a school or government programme), "
                                       "or the searchers are clearly a different group (sellers, students) that would never buy this")
    intent: INTENTS
    reason: str = Field(description="one short sentence, naming what the results are really about when off-topic")


class SerpChecks(BaseModel):
    checks: list[SerpCheck]


def check_relevance(c, serps):
    """Read what Google really shows for each search and drop the ones that mean something else. Returns {keyword: SerpCheck}."""
    out = {}
    for i in range(0, len(serps), 40):
        ctx = [{"keyword": s["keyword"], "labelled_intent": s.get("intent"),
                "page1": ["%s | %s" % (o["domain"], (o.get("title") or "")[:90]) for o in s["organic"][:10]],
                "people_also_ask": (s.get("questions") or [])[:4]} for s in serps[i:i + 40]]
        res = ai.ask_json(
            f"""Block 08 relevance check for this business: {c.v['one_liner']}
For each search, look at the real page-1 results and the questions people ask. Decide if the search is on-topic for THIS
business, and fix the intent label if the results show it is wrong.
{INTENT_HELP}
Return one check per keyword, same spelling.{c.note()}""", SerpChecks, smart=False, context={"searches": ctx})
        out.update({x.keyword.strip().lower(): x for x in res.checks})
    return out


def sync_kw_summary(c):
    """Step 07's result line must show the numbers every later step uses (after the step-08 topic check), not the ones before it."""
    st07 = store.block(c.slug, "07")
    if not st07.get("summary") or not c.has("08_keywords_dropped.csv"):
        return
    kept = read_csv(c.path("08_keywords_clean.csv"))
    sp_ = volume_split(kept)
    new = re.sub(
        r"\d+ clean keywords(.*?)buying volume \d+/mo \(commercial \d+, rival brand names \d+ counted at 10%, info \d+ not counted\)( \[after the step-08 topic check\])?",
        lambda m: (f"{len(kept)} clean keywords{m.group(1)}buying volume {int(buy_volume(kept))}/mo (commercial {sp_['commercial']}, "
                   f"rival brand names {sp_['brand']} counted at 10%, info {sp_['info']} not counted) [after the step-08 topic check]"), st07["summary"])
    if new != st07["summary"]:
        store.set_block(c.slug, "07", summary=new)


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
    fetched_ok = [s for s in raw if not s.get("error") and s["organic"]]
    checks = check_relevance(c, fetched_ok) if fetched_ok else {}
    dropped = []
    for s in fetched_ok:
        ck = checks.get(s["keyword"].lower())
        if not ck:
            continue
        if not ck.on_topic:
            s["off_topic"], s["off_topic_reason"] = True, ck.reason
            dropped.append({"keyword": s["keyword"], "volume": int(s["volume"]), "reason": ck.reason})
        elif ck.intent != s["intent"]:
            s["intent"] = ck.intent
    c.write("09_serp_raw.json", raw)
    # the keyword list every later block reads: off-topic searches out, intents corrected from the real results
    off = {d["keyword"] for d in dropped}
    fixed = {s["keyword"]: s["intent"] for s in fetched_ok}
    kept = [dict({k_: v_ for k_, v_ in k.items() if k_ != "prio"}, intent=fixed.get(k["keyword"], k["intent"])) for k in kws if k["keyword"] not in off]
    write_csv(c.path("08_keywords_clean.csv"), kept, KW_COLS)
    write_csv(c.path("08_keywords_dropped.csv"), dropped, ["keyword", "volume", "reason"])
    sync_kw_summary(c)
    ok = [s for s in fetched_ok if not s.get("off_topic")]
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
    fetched = len(fetched_ok) / max(len(raw), 1)
    opp = sum(1 for cl in clusters if cl["weak_spots"] or cl["better_format_possible"]) / max(len(clusters), 1)
    hard = sum(1 for cl in clusters if cl["top5_all_dr60"]) / max(len(clusters), 1)
    summary = (f"{len(fetched_ok)}/{len(raw)} SERPs; {len(clusters)} clusters; {opp:.0%} with a weak spot or better-format chance; "
               f"{hard:.0%} have all top-5 DR 60+")
    if dropped:
        summary += "; %d off-topic searches removed (%s)" % (len(dropped), ", ".join("%s %d/mo" % (d["keyword"], d["volume"]) for d in dropped[:4]))
    if not ok:
        return Result("redo", summary + "; every search was off-topic: the seeds mean something else on Google")
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


class RivalKind(BaseModel):
    domain: str
    kind: Literal["direct", "generalist", "off-target"] = Field(description="direct = sells or gives away the same kind of thing to the same buyer; "
                                                                "generalist = a big general tool or media site that only touches this topic; "
                                                                "off-target = about something else")
    reason: str


class RivalKinds(BaseModel):
    rivals: list[RivalKind]


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
    known = {}
    for x in how["competitors"]:
        d_ = domain_of(x["url"])
        if d_ and seo.VALID_DOMAIN.match(d_) and not seo.not_competitor(d_):
            known.setdefault(d_, x)
    cand = [d for d, _w in sorted(weight.items(), key=lambda x: -x[1])[:10]]
    titles = defaultdict(list)
    for cl in clusters:
        for o in cl["top10"]:
            if o["domain"] in cand and len(titles[o["domain"]]) < 3:
                titles[o["domain"]].append("%s -> %s" % (cl["head"], (o.get("title") or "")[:80]))
    kinds = {}
    if cand:
        res = ai.ask_json(
            f"""Block 09. Which of these sites are real rivals of this business: {c.v['one_liner']}
They rank on Google for our searches. Classify each one; judge by what the site sells, not by where it ranks.{c.note()}""",
            RivalKinds, smart=False, context={"sites": [{"domain": d, "ranks_for": titles[d]} for d in cand],
                                              "rivals_already_known_to_charge_money": list(known)})
        kinds = {x.domain.strip().lower(): x for x in res.rivals}
    row = lambda d, src: {"domain": d, "weight": round(weight.get(d, 0), 1), "serps": seen_in.get(d, 0), "dr": dr.get(d),
                          "known_in_02": d in known, "source": src, "kind": (kinds[d].kind if d in kinds else "direct"),
                          "why": (kinds[d].reason if d in kinds else ("charges money for this (block 02): " + known[d]["price"])[:160] if d in known else "")}
    direct = [row(d, "google page 1") for d in cand if (kinds.get(d) is None or kinds[d].kind == "direct")]
    general = [row(d, "google page 1") for d in cand if kinds.get(d) is not None and kinds[d].kind == "generalist"]
    removed = [{"domain": d, "why": kinds[d].reason} for d in cand if kinds.get(d) is not None and kinds[d].kind == "off-target"]
    # rivals known to charge money (block 02) are real rivals even when they do not rank: keep room for at least 2 of them
    extra = [d for d in known if d not in {x["domain"] for x in direct}]
    comps = direct[:5 - min(2, len(extra))]
    comps += [row(d, "block 02") for d in extra[:5 - len(comps)]]
    if len(comps) < 3:
        comps += general[:3 - len(comps)]
    missing_dr = [x["domain"] for x in comps if x["dr"] is None]
    if missing_dr:
        got = seo.domain_ranks(missing_dr)
        for x in comps:
            x["dr"] = got.get(x["domain"], x["dr"])
    c.write("11_top_competitors.json", comps)
    c.write("11_competitors_removed.json", {"off_target": removed, "generalist_not_used": [x["domain"] for x in general if x["domain"] not in {y["domain"] for y in comps}]})
    # trend from the real keywords (12 months, weighted by volume): the fallback when Google Trends had no data
    tk = [(num(r["trend12"]), num(r["volume"])) for r in rows if r.get("trend12") not in ("", None) and r["intent"] != "info"]
    kw_trend = round(sum(t * v for t, v in tk) / sum(v for _t, v in tk), 1) if tk and sum(v for _t, v in tk) else None
    store.set_data(c.slug, kw_trend_12m_pct=kw_trend)
    pulse = c.read("04_niche_pulse.json", default=None)
    if pulse is not None:
        pulse["kw_trend_12m_pct"] = kw_trend
        if pulse.get("status") == "unknown" and kw_trend is not None:
            pulse["status"] = "alive" if kw_trend >= -10 else "flat" if kw_trend >= -30 else "dying"
            pulse["status_source"] = "our own keywords' searches over 12 months (Google Ads numbers)"
            pulse["status_source"] = "12-month search volume of our own keywords (Google Trends had no data)"
        c.write("04_niche_pulse.json", pulse)
    top20 = clusters[:20]
    buy_clusters = sum(1 for cl in top20 if cl["intent"] in BUY_INTENTS)
    buy_easy = sum(1 for r in unique_searches(rows) if is_buy(r) and r["kd"] != "" and 0 < num(r["kd"]) <= 20)  # close wordings count once; 0 = not measured
    hard_all = all(num(r["kd"]) >= 50 for r in rows if r["kd"] != "")
    summary = (f"{buy_clusters} buying clusters in top 20; {buy_easy} buying keywords KD<=20; "
               f"top competitors: {', '.join(x['domain'] for x in comps)}"
               + ("; removed as off-target: " + ", ".join(x["domain"] for x in removed) if removed else ""))
    if not comps:
        return Result("redo", "no real competitor domain found in the SERPs")
    if all(r["intent"] == "info" for r in rows):
        return Result("warn", summary + "; only info keywords: go back to 06 with buying seeds (vm rerun <slug> 06)")
    if hard_all:
        return Result("warn", summary + "; everything KD 50+: plan a non-SEO first channel")
    if buy_clusters >= 10 and buy_easy >= 10:
        return Result("pass", summary)
    return Result("warn", summary + "; below the bar (>=10 buying clusters AND >=10 buying keywords KD<=20)")

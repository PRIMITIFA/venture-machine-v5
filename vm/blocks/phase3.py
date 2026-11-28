"""PHASE 3: COMPETITORS + MARKET (blocks 10-13). Facts about the real top-5 only."""
import re
from collections import defaultdict
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import ai, seo, store, web
from ..config import K, S
from ..pipeline import Result
from ..util import buy_volume, is_buy, md_table, median, num, read_csv, volume_split, write_csv


# ---------------- 10 Top-5 UX audit ----------------
# words that describe OUR failure to load a page, not something wrong with the rival
FETCH_FAIL = re.compile(r"\b(404|403|5\d\d|not found|no page content|returns? (a |an )?(error|404)|redirect stub|could not be (opened|loaded|fetched)|failed to load|timed? ?out|blocked|captcha|no title and no text|page (is )?(empty|blank))\b", re.I)


class UxOne(BaseModel):
    domain: str
    steps_to_checkout_estimate: Optional[int] = Field(default=None, description="estimate from the pages seen; null if unknown")
    weaknesses: list[str] = Field(description="concrete, e.g. '6 steps to pay, no sample report'")
    strengths: list[str]
    look: Literal["modern", "average", "dated", "not seen"] = Field(default="not seen", description="how the site LOOKS in its screenshot: modern = clean current design, one clear action; dated = old-style layout, clutter, many menus, stock badges; 'not seen' when there is no screenshot or it shows an error or block page")
    look_evidence: str = Field(default="", description="what the screenshot shows that led to the look rating, in one or two plain sentences; empty when not seen")


class Ux(BaseModel):
    competitors: list[UxOne]


def b10_ux(c):
    comps = c.read("11_top_competitors.json")
    shots_dir = c.path("shots")
    shots_dir.mkdir(exist_ok=True)
    facts, images, more, manual = [], [], [], []
    try:
        ages = seo.domain_ages([x["domain"] for x in comps])
    except seo.DFSError:
        ages = {}
    for x in comps:
        d = x["domain"]
        p = web.fetch(d)
        read_with = "plain fetch"
        if p["status"] != 200 or web.blocked(p):
            # the rival may only refuse plain fetching: read it the way a visitor does before calling it "could not open"
            from .. import proof
            btext = proof.read_page(p["url"] if p["status"] else "https://" + d, 6000)
            if len(btext) > 400:
                p = dict(p, status=200, html=btext, bytes=len(btext), error="")
                read_with = "real browser"
        # a page the owner (or the boss) opened by hand: shots/<domain>-manual.png and/or shots/<domain>-manual.txt beat a failed fetch
        m_png, m_txt = shots_dir / (d.replace(".", "_") + "-manual.png"), shots_dir / (d.replace(".", "_") + "-manual.txt")
        if (p["status"] != 200 or web.blocked(p)) and m_txt.exists():
            mt = m_txt.read_text(encoding="utf-8")
            p = dict(p, status=200, html=mt, bytes=len(mt), error="")
            read_with = "by hand"
        sig = web.signals(p["html"])
        pricing = next((u for u, label in web.links_of(p["html"], p["url"]) if "pric" in u.lower() or "plan" in u.lower()), "")
        sm = web.sitemap(d)
        from .. import proof as _proof
        rv = _proof.reviews(d)
        shots = [str(m_png)] if (m_png.exists() and read_with != "plain fetch") else web.screenshots(p["url"], str(shots_dir / d.replace(".", "_"))) if p["status"] == 200 else []
        images += shots[:1]
        more += shots[1:2]
        if web.blocked(p) and read_with == "plain fetch":
            manual.append(d)
        try:
            speed = seo.speed_score(p["url"] if p["status"] == 200 else d)
        except seo.DFSError:
            speed = None
        facts.append({"domain": d, "mobile_speed_score": speed, "domain_created": ages.get(d, ""), "status": p["status"], "load_ms": p["ms"], "kb": p["bytes"] // 1024, "title": web.title_of(p["html"]),
                      "trust": sig["trust"], "checkout_provider": sig["checkout"], "mobile_viewport": sig["mobile_viewport"],
                      "pricing_page": pricing, "sitemap_urls": sm["urls"], "sitemap_oldest": sm["oldest"], "sitemap_newest": sm["newest"],
                      "blocked_or_captcha": d in manual, "screenshots": shots, "read_with": read_with, "reviews": rv,
                      "text": web.text_of(p["html"], 2500) if read_with == "plain fetch" else p["html"][:4000]})
    out = ai.ask_json(
        f"""Block 10. UX + trust audit of the top-5 competitors of: {c.v['one_liner']}
For each: estimate steps from landing to payment (from the pages and screenshots; null if unknown), list concrete
weaknesses (missing sample, no reviews, slow, no prices, many steps, weak mobile, old site...) and strengths.
Rate how each site LOOKS from its screenshot (modern / average / dated) and say what you see; a rival with no screenshot,
or whose screenshot shows an error or block page, is "not seen". A page read with "real browser" or "by hand" has no checkout or
mobile data: treat those two as unknown, not as missing.
'reviews' is the rival's public Trustpilot profile. Many reviews with a high rating is a strength (name the count and rating).
Turn what the 1 and 2 star reviewers complain about (low_star_text) into weaknesses, in the buyers' own words, short.
checked false or found false means there are no public reviews to read: that is unknown, never a weakness.
Use only what the data and screenshots show.{c.note()}""",
        Ux, smart=False, images=(images + more)[:10], context={"measured": [{k: v for k, v in f.items() if k != "screenshots"} for f in facts]})
    by = {u.domain: u.model_dump() for u in out.competitors}
    rows = [dict(f, **{k: v for k, v in by.get(f["domain"], {}).items() if k != "domain"}) for f in facts]
    for r in rows:
        r.pop("text", None)
        if isinstance(r.get("reviews"), dict):
            r["reviews"] = {k: v for k, v in r["reviews"].items() if k != "low_star_text"}
        # a page we could not open says nothing about the rival: it is "not checked", never a weakness and never proof the rival is gone
        failed = num(r.get("status")) >= 400 or r.get("blocked_or_captcha")
        kept = [w for w in (r.get("weaknesses") or []) if not FETCH_FAIL.search(w)]
        if failed or len(kept) < len(r.get("weaknesses") or []):
            r["could_not_open"] = bool(failed)
            r["weaknesses"] = [] if failed else kept
            if failed and r["domain"] not in manual:
                manual.append(r["domain"])
    c.write("12_competitor_ux.json", {"competitors": rows, "manual_review_at_gate2": manual})
    n_weak = sum(len(r.get("weaknesses") or []) for r in rows)
    summary = f"{n_weak} concrete weaknesses across {len(rows)} competitors" + (f"; could not be opened, so NOT judged (check by hand at gate 2, they may be alive): {', '.join(manual)}" if manual else "")
    if n_weak >= 2:
        return Result("pass", summary)
    return Result("warn", summary + "; they are strong: the edge must come from price, data or B2B (block 11)")


# ---------------- 11 Prices, models, ads ----------------
class Plan(BaseModel):
    name: str
    price: str
    billing: Literal["one-time", "monthly", "yearly", "usage", "free", "custom", "unknown"]


class Biz(BaseModel):
    domain: str
    plans: list[Plan]
    free_tier: str
    upsells: list[str]
    b2b_or_api: str
    checkout_provider: str
    trial_refunds: str
    affiliate_or_ads_networks: str
    source_urls: list[str]


class Quote(BaseModel):
    quote: str
    url: str


class Business(BaseModel):
    competitors: list[Biz]
    long_running_ads: list[str] = Field(description="ads seen running 30+ days (Meta Ad Library / Google Ads Transparency): advertiser, angle, offer, URL. Empty if not verifiable")
    audience_quotes: list[Quote] = Field(description="real buyer quotes with the URL where they were said")
    identified_gap: str = Field(description="ONE line: the gap we can own (price, product, subscription/B2B/API, ignored audience, UX)")
    competitors_cheaper_than_our_data_cost_and_better_data: bool
    reason: str


def b11_business(c):
    comps = c.read("11_top_competitors.json")
    ux = c.read("12_competitor_ux.json")
    how = c.read("02_how_analysis.json")
    raw = c.read("09_serp_raw.json")
    paid = defaultdict(list)
    for s in raw:
        for p in s.get("paid") or []:
            paid[p["domain"]].append({"keyword": s["keyword"], "title": p["title"], "description": p["description"]})
    pages = {}
    for x in ux["competitors"]:
        if x.get("pricing_page"):
            p = web.fetch(x["pricing_page"])
            pages[x["domain"]] = {"url": p["url"], "text": web.text_of(p["html"], 4000)} if p["status"] == 200 else {"url": x["pricing_page"], "text": f"status {p['status']}"}
    out = ai.ask_json(
        f"""Block 11. For each top-5 competitor of "{c.v['one_liner']}": all products, prices, plans, free tier, upsells,
B2B/API, checkout provider, trial/refunds, affiliate or ad networks. Use the pricing pages given and web search; cite URLs.
Then look for ads that have run 30+ days (Meta Ad Library, Google Ads Transparency Center) - only list what you verified.
Collect real buyer quotes (Reddit, reviews, forums) with URLs and write ONE identified_gap line.
A rival whose page could not be opened ("could_not_open", or any 404 / blocked page) may be perfectly alive: sites move and block bots.
Open its main domain and its pricing page yourself before saying anything about it. NEVER base the gap on a rival being offline,
gone or "returning 404", and never count a failed page load as a weakness. If you cannot confirm, say "not checked".
Check each rival's guarantee and refund terms on its own site before claiming nobody offers one.
Our data sources and their cost are in 'how'. Say if competitors sell cheaper than our data cost AND have better data.{c.note()}""",
        Business, web=True, smart=True,
        context={"competitors": comps, "pricing_pages": pages, "how": {"data_sources": how["data_sources"], "competitors_02": how["competitors"]},
                 "google_ads_seen_in_our_serps": dict(paid), "ux": [{k: x.get(k) for k in ("domain", "checkout_provider", "weaknesses")} for x in ux["competitors"]]})
    d = out.model_dump() | {"google_ads_in_serps": dict(paid)}
    c.write("13_competitor_business.json", d)
    md = ["# 13 Competitor ads\n", "## Google search ads seen in our SERPs (DataForSEO, real)\n"]
    for dom, ads in paid.items():
        md.append(f"### {dom} ({len(ads)} ads)\n" + md_table(ads[:10], ["keyword", "title", "description"]))
    md.append("\n## Long-running ads (30+ days, from ad libraries)\n" + ("\n".join(f"- {a}" for a in out.long_running_ads) or "_none verified_"))
    c.write("13_competitor_ads.md", "\n".join(md))
    summary = f"gap: {out.identified_gap}; {sum(len(x.plans) for x in out.competitors)} plans priced; {len(paid)} advertisers on our keywords"
    if out.competitors_cheaper_than_our_data_cost_and_better_data:
        return Result("kill", summary + f"; competitors sell below our data cost with better data: {out.reason}")
    if not out.identified_gap.strip():
        return Result("redo", "no clear gap written")
    return Result("pass", summary)


# ---------------- 12 Market size + buyers ----------------
CTR_TOP5 = 0.28 + 0.15 + 0.10 + 0.07 + 0.05  # typical organic CTR of positions 1-5
AIO_CLICK_FACTOR = 0.6  # a search with a Google AI answer sends roughly 60% of the usual clicks (rule of thumb)


def parse_prices(text):
    """'$29 one-time', '£6.99', 'from €4.99' -> [29.0, 6.99*1.27, 4.99*1.08] in USD (rough FX)."""
    import re
    fx = {"$": 1.0, "£": 1.27, "€": 1.08}
    out = []
    for cur, val in re.findall(r"([$£€])\s?(\d+(?:[.,]\d{1,2})?)", str(text)):
        out.append(round(float(val.replace(",", ".")) * fx[cur], 2))
    return out

class Segment(BaseModel):
    name: str
    size_note: str
    pain_quotes: list[Quote]
    underserved: bool


class Market(BaseModel):
    top_down_usd_year: float = Field(description="buyers x price per year, from cited sources; 0 if unknown")
    top_down_method: str
    top_down_sources: list[str]
    typical_price_usd: float = Field(description="typical price per sale/month from block 11 data")
    segments: list[Segment]
    underserved_countries_or_segments: list[str]
    growth_direction: Literal["growing", "flat", "shrinking", "unknown"]
    growth_evidence: str


def b12_market(c):
    comps = c.read("11_top_competitors.json")
    biz = c.read("13_competitor_business.json")
    short = read_csv(c.path("11_shortlist.csv"))
    tr = seo.traffic([x["domain"] for x in comps], c.loc, c.lang)
    rival_traffic = {}
    for x in comps:
        try:
            rival_traffic[x["domain"]] = seo.rank_overview(x["domain"], c.loc, c.lang)
        except seo.DFSError as ex:
            rival_traffic[x["domain"]] = {"error": str(ex)[:150]}
    history, trends = {}, []
    by_visits = sorted([x for x in comps if x.get("kind", "direct") == "direct"], key=lambda x: -num((rival_traffic.get(x["domain"]) or {}).get("visits")))
    for x in by_visits[:K("history_rivals")]:
        try:
            h = seo.traffic_history(x["domain"], c.loc, c.lang)
        except seo.DFSError:
            continue
        history[x["domain"]] = h
        if len(h) >= 6:
            first = sum(r["visits"] for r in h[:3]) / 3
            last = sum(r["visits"] for r in h[-3:]) / 3
            if first:
                trends.append(round((last - first) / first * 100, 1))
                rival_traffic[x["domain"]]["trend_12m_pct"] = trends[-1]
    rivals_trend = round(sum(trends) / len(trends), 1) if trends else None  # direct rivals only (see by_visits)
    heads = [r["keyword"] for r in short if r["role"] == "main"][:5]
    by_country = {}
    for cc in list(dict.fromkeys(S.market_countries + K("extra_countries"))):
        if cc == c.v["country"]:
            continue
        try:
            from ..config import location_code, COUNTRY_LANG
            vols = seo.search_volume(heads, location_code(cc), COUNTRY_LANG.get(cc, "en"))
            by_country[cc] = int(sum(num(v.get("search_volume")) for v in vols))
        except seo.DFSError as e:
            by_country[cc] = "no data (API error)"
            store.log(c.slug, "error", f"12 search volume {cc}: {e}")
    by_country[c.v["country"]] = int(sum(num(r["volume"]) for r in short if r["role"] == "main"))
    out = ai.ask_json(
        f"""Block 12. Market size and buyers for: {c.v['one_liner']}
1) TOP-DOWN: number of buyers x price per year, each number with a source URL (web search).
2) Typical price from the competitor pricing data.
3) Buyer segments with real pain quotes (Trustpilot, app stores, Reddit, forums) and URLs; mark underserved ones.
4) Countries/segments that are underserved; growth direction with evidence.{c.note()}""",
        Market, web=True, smart=True, context={"competitor_pricing": biz["competitors"], "search_volume_by_country_main_keywords": by_country,
                                               "rivals_google_traffic_now_and_12m_trend": rival_traffic})
    conv = S.assumed_conversion
    # niche clicks: what the top-5 results get from OUR buying keywords (volume x organic CTR of positions 1-5)
    kws = read_csv(c.path("08_keywords_clean.csv"))
    serps_ = [s for s in c.read("09_serp_raw.json", default=[]) if not s.get("error") and not s.get("off_topic")]
    aio_share = sum(1 for s in serps_ if (s.get("features") or {}).get("ai_overview")) / max(len(serps_), 1)
    aio_factor = round(1 - (1 - AIO_CLICK_FACTOR) * aio_share, 2)  # searches with a Google AI answer send fewer clicks
    bv = buy_volume(kws)
    clicks = bv * CTR_TOP5 * aio_factor
    price, price_src = out.typical_price_usd, "AI from block 11 pricing"
    if not price:
        seen = [p for x in biz["competitors"] for pl in x["plans"] for p in parse_prices(pl["price"])]
        seen += [p for x in c.read("02_how_analysis.json")["competitors"] for p in parse_prices(x["price"])]
        price, price_src = median(seen), f"median of {len(seen)} competitor prices seen in blocks 02/11"
    bottom_up = clicks * conv * price * 12
    goal = S.min_market_usd  # size bar, not a sales goal
    d = {"bottom_up_usd_year": round(bottom_up),
         "buying_searches_month": int(bv), "clicks_month": round(clicks, 1), "ctr_top5": CTR_TOP5, "conversion_used": conv, "volume_split": volume_split(kws), "aio_share": round(aio_share, 2), "aio_click_factor": aio_factor,
         "price_used_usd": price, "price_source": price_src,
         "competitor_domain_traffic": tr, "rival_traffic": rival_traffic, "rival_traffic_history": history,
         "rivals_traffic_trend_12m_pct": rivals_trend,
         "search_volume_by_country": by_country, "min_market_usd": goal, **out.model_dump()}
    d["typical_price_usd"] = price
    d["bottom_up_method"] = market_method(d, price, price_src)
    big, small = max(bottom_up, out.top_down_usd_year), min(bottom_up, out.top_down_usd_year)
    d["methods_differ_10x"] = bool(small and big / small > 10)
    d["no_price_found"] = not price
    c.write("14_market_analysis.json", d)
    return market_result(d, bottom_up)


def market_result(d, bottom_up, at=""):
    """Block 12's verdict and one-line result, from the stored numbers. Called again by block 16 once the price is chosen,
    so the line always shows the same market number as the rest of the report."""
    top_down, goal, target = num(d.get("top_down_usd_year")), S.min_market_usd, S.target_market_month * 12
    rivals_trend, under = d.get("rivals_traffic_trend_12m_pct"), d.get("underserved_countries_or_segments") or []
    summary = (f"search market ${bottom_up / 12:,.0f}/mo (${bottom_up:,.0f}/yr){at}, whole-industry guess {('$%s/yr' % format(round(top_down), ',')) if top_down else 'unknown (no sourced number found)'} "
               f"(smallest worth building: ${S.min_market_month:,.0f}/mo; we want ${S.target_market_month:,.0f}+/mo); underserved: {', '.join(under[:3])[:300] or 'none'}")
    if d.get("no_price_found"):
        return Result("warn", summary + "; no competitor price found, market size unknown: check prices by hand at gate 2")
    if top_down and max(bottom_up, top_down) < goal and not at:   # an unknown industry size (0) is not proof of a small one
        return Result("kill", summary + "; the whole market is too small to build for")
    if bottom_up < goal:
        return Result("warn", summary + "; the money reachable through Google search is too small to build for: "
                                        "as a search business this is a KILL at gate 3 unless another channel carries it")
    if rivals_trend is not None and rivals_trend < -30:
        summary += f"; direct rivals' Google visits fell {abs(rivals_trend):.0f}% in 12 months (shrinking)"
    if bottom_up >= target and under:
        return Result("warn" if d.get("methods_differ_10x") else "pass", summary + ("; the two methods differ more than 10x (flagged in the SWOT)" if d.get("methods_differ_10x") else ""))
    return Result("warn", summary + "; below the bar (search market of the size we want AND an underserved segment): TEST FIRST at most")


def market_method(d, price, price_src):
    """The formula in words, built from the same numbers the result is computed from (so text and number cannot differ)."""
    bv, clicks, conv = num(d["buying_searches_month"]), num(d["clicks_month"]), num(d["conversion_used"])
    return (f"{int(bv)} buying searches/mo (a rival's bare brand name counts 10%) x top-5 CTR {num(d['ctr_top5']):.0%} x {d['aio_click_factor']} "
            f"(Google shows its own AI answer on {num(d['aio_share']):.0%} of these searches) = {int(clicks)} clicks/mo x {conv:.1%} conversion (ASSUMPTION) "
            f"x ${price:,.2f} ({price_src}) x 12 = ${clicks * conv * price * 12:,.0f} a year. This is the money reachable through Google search only, not other channels")


# ---------------- 13 SEO + link gap + AI visibility ----------------
MIN_LINK_DR, MIN_LINK_VISITS = 15, 100
SPAM_WORDS = ("casino", "poker", "gambl", "betting", "slot", "porn", "adult", "escort", "viagra", "pharma", "crypto", "bitcoin", "loan", "payday", "thc", "cbd", "mirror")
SPAM_TOKENS = {"bet", "bets", "sex", "xxx", "vape"}


def link_reject_reason(t):
    """Why a site is not worth asking for a link ('' = keep it)."""
    d = t["domain"].lower()
    name = d.rsplit(".", 1)[0]
    if any(w in name for w in SPAM_WORDS) or SPAM_TOKENS & set(re.split(r"[^a-z]+", name)) or re.match(r"bet(?!ter|a|h|ty|ween)[a-z]{3,}", name):
        return "spam or gambling style name"
    if num(t["dr"]) < MIN_LINK_DR:
        return f"strength under {MIN_LINK_DR} (or no data)"
    return ""


def b13_links(c):
    comps = c.read("11_top_competitors.json")
    seo_rows, refs = [], {}
    for x in comps:
        d = x["domain"]
        s = seo.backlinks_summary(d)
        s["kind"] = x.get("kind", "direct")
        s["top_pages"] = seo.top_pages(d, c.loc, c.lang, limit=10)
        s["free_tool_pages"] = [p["url"] for p in s["top_pages"] if any(w in (p["url"] or "").lower() for w in ("tool", "calculator", "checker", "free", "generator", "lookup"))]
        seo_rows.append(s)
        if s["kind"] == "direct":  # a general giant's links say nothing about who links to sites like ours
            refs[d] = seo.referring_domains(d, limit=K("ref_limit"))
    links = defaultdict(lambda: {"dr": 0, "competitors": []})
    comp_set = {x["domain"] for x in comps}
    for d, lst in refs.items():
        for r in lst:
            rd = r["domain"]
            if not rd or rd in comp_set:
                continue
            links[rd]["dr"] = max(links[rd]["dr"], num(r["dr"]))
            links[rd]["competitors"].append(d)
    found = [{"domain": k, "dr": int(v["dr"]), "links_to_n": len(v["competitors"]), "competitors": v["competitors"]}
             for k, v in links.items() if len(v["competitors"]) >= 2]
    found.sort(key=lambda t: (-t["links_to_n"], -t["dr"]))
    targets, rejected = [], []
    for t in found:
        why = link_reject_reason(t)
        (rejected.append(dict(t, why=why)) if why else targets.append(t))
    if targets:  # a site worth asking must also get real Google visitors
        try:
            tv = seo.traffic([t["domain"] for t in targets[:200]], c.loc, c.lang)
        except seo.DFSError:
            tv = {}
        keep = []
        for t in targets:
            visits = (tv.get(t["domain"]) or {}).get("etv")
            t["visits"] = int(visits) if visits is not None else ""
            if t["domain"] in tv and num(visits) < MIN_LINK_VISITS:
                rejected.append(dict(t, why=f"under {MIN_LINK_VISITS} Google visits a month"))
            else:
                keep.append(t)
        targets = keep
    write_csv(c.path("15_link_targets.csv"), targets, ["domain", "dr", "visits", "links_to_n", "competitors"])
    write_csv(c.path("15_link_targets_rejected.csv"), rejected, ["domain", "dr", "links_to_n", "why"])
    c.write("15_competitor_seo.json", {"competitors": seo_rows})
    gap = keyword_gap(c, [x for x in comps if x.get("kind", "direct") == "direct"])
    write_csv(c.path("15_keyword_gap.csv"), gap, ["keyword", "volume", "cpc", "kd", "best_rival", "rival_rank"])
    questions = people_ask(c)
    c.write("15_questions.json", questions)
    ai_vis = ai_visibility(c, comps)
    c.write("15_ai_visibility.json", ai_vis)
    drs = [num(s["dr"]) for s in seo_rows if s["dr"] is not None and s["kind"] == "direct"]
    dr_txt = ", ".join("%s %s" % (s["domain"], s["dr"]) for s in seo_rows)
    summary = (f"{len(targets)} good link targets (link to >=2 rivals, strength 15+, real visitors, not spam; {len(rejected)} rejected); competitor DR {dr_txt}; "
               f"median referring domains {int(median([num(s['referring_domains']) for s in seo_rows]))}")
    summary += "; %d searches rivals get that we had not planned; %d questions people ask; AI: %s" % (len(gap), len(questions), ai_vis["headline"])
    if drs and min(drs) >= 70:
        return Result("warn", summary + "; all DR 70+: SEO is a 12+ month game")
    if len(targets) >= 20 and drs and min(drs) < 40:  # counted after the quality filter
        return Result("pass", summary)
    if len(targets) < 20:
        return Result("fail", summary + f"; only {len(targets)} good link targets (the bar is 20): links will not come from asking rivals' linkers, "
                                        "plan another way (a data asset people cite, directories, PR)")
    return Result("warn", summary + "; no top competitor with DR < 40")


# ---------------- 13b AI visibility (part of block 13) ----------------
ISO = {"uk": "GB"}


def _mentioned(domain, text_low, cited):
    """A rival counts as mentioned if its site is cited, its domain is written out, or its brand word appears
    (brand word only when it is distinctive: no hyphen, 5+ letters, e.g. 'photoaid' but not 'passport-photo')."""
    from ..seo import _sld
    if domain in cited or domain in text_low:
        return True
    b = _sld(domain)
    return "-" not in b and len(b) >= 5 and re.search(r"%s" % re.escape(b), text_low) is not None


def ai_visibility(c, comps, n_prompts=None):
    """Do ChatGPT, Perplexity and Google's AI Overviews recommend the rivals, and which sites do they quote?"""
    n_prompts = n_prompts or K("ai_prompts")
    clusters = c.read("10_clusters_serp.json")
    heads = [cl["head"] for cl in clusters if cl["intent"] in ("buy", "brand-model")][:max(n_prompts - 1, 1)]
    product = (c.v["data"].get("product") or c.v["one_liner"] or "").strip().rstrip(".")
    payer = (c.v["data"].get("payer") or "").strip().rstrip(".")
    # the first question is the buyer's own need in plain words, so the answer is about products like ours
    first = ("I need this: %s. " % product) + (("The people who need it: %s. " % payer) if payer else "") + "Which specific websites or tools do you recommend?"
    prompts = [first]
    prompts += [f"What is the best website or tool for {h}? Recommend specific sites." for h in heads]
    direct = [x for x in comps if x.get("kind", "direct") == "direct"]
    if direct:
        prompts.append(f"What are the best alternatives to {direct[0]['domain']}?")
    iso = ISO.get(c.v["country"], c.v["country"].upper()) if not str(c.v["country"]).isdigit() else "US"
    answers = []
    for p in prompts:
        for eng in ("chatgpt", "perplexity"):
            try:
                answers.append(seo.ai_answer(eng, p, iso))
            except seo.DFSError as ex:
                answers.append({"engine": eng, "prompt": p, "text": "", "cited": [], "error": str(ex)[:200]})
    comp_domains = [x["domain"] for x in comps]
    share = {d: 0 for d in comp_domains}
    recommended = defaultdict(int)
    for a in answers:
        low = a["text"].lower()
        for d in comp_domains:
            if _mentioned(d, low, a["cited"]):
                share[d] += 1
        for d in a["cited"]:
            recommended[d] += 1
    # Google AI Overviews: re-read our SERPs (from cache, free) for the sites they cite
    aio_total, aio_count, aio_sources = 0, 0, defaultdict(int)
    for raw in c.read("09_serp_raw.json"):
        if raw.get("error") or raw.get("off_topic"):
            continue
        sr = seo.serp(raw["keyword"], c.loc, c.lang)
        aio_total += 1
        if sr["features"].get("ai_overview"):
            aio_count += 1
            for d in sr.get("ai_overview_sources") or []:
                aio_sources[d] += 1
    try:
        mentions = seo.ai_sources(heads[0], c.loc, c.lang) if heads else {"sources": [], "brands": [], "answers": 0}
    except seo.DFSError as ex:
        mentions = {"sources": [], "brands": [], "answers": 0, "error": str(ex)[:200]}
    ok = [a for a in answers if not a.get("error")]
    top_rec = sorted(recommended.items(), key=lambda x: -x[1])[:15]
    best = max(share.items(), key=lambda x: x[1]) if share else ("-", 0)
    headline = (f"in {len(ok)} AI answers the top Google rival {best[0]} shows up {best[1]} times; AI recommends most: "
                f"{', '.join(d for d, _ in top_rec[:3]) or 'nobody'}; Google AI answer on {aio_count}/{aio_total} searches")
    return {"headline": headline, "prompts": prompts, "answers": [dict(a, text=a["text"][:1500]) for a in answers],
            "rival_share": share, "answers_ok": len(ok), "ai_recommends": [{"site": d, "times": n} for d, n in top_rec],
            "google_ai_overview": {"searches": aio_total, "with_ai_answer": aio_count,
                                   "cited_sites": [{"site": d, "times": n} for d, n in sorted(aio_sources.items(), key=lambda x: -x[1])[:15]]},
                                   "ai_trusted_sources": mentions}


def _topic_phrases(c):
    """Each key term as a set of its real words, e.g. 'uk passport photo' -> {'passport', 'photo'}."""
    out = []
    for t in (c.v["data"].get("key_terms") or []):
        ws = {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in ("for", "the", "and", "online", "free")}
        if ws:
            out.append(ws)
    return out


def on_topic(keyword, phrases):
    """On topic = contains every word of at least one key term (so 'renew british passport' is not a 'passport photo' search)."""
    ws = set(re.findall(r"[a-z0-9]+", keyword.lower()))
    return any(p <= ws for p in phrases) if phrases else True


def keyword_gap(c, comps, n_rivals=None):
    """Searches the top rivals rank for (page 1-2) that are on our topic but not in our keyword list."""
    ours = {k["keyword"] for k in read_csv(c.path("08_keywords_clean.csv"))}
    phrases = _topic_phrases(c)
    best = {}
    for x in comps[:n_rivals or K("gap_rivals")]:
        try:
            rows = seo.ranked_keywords(x["domain"], c.loc, c.lang, limit=100)
        except seo.DFSError:
            continue
        for r in rows:
            k = (r["keyword"] or "").lower()
            if not k or k in ours or not on_topic(k, phrases):
                continue
            if k not in best or (r["rank"] or 99) < best[k]["rival_rank"]:
                best[k] = {"keyword": k, "volume": r["volume"] or 0, "cpc": r["cpc"] or 0, "kd": r["kd"] if r["kd"] is not None else "",
                           "best_rival": x["domain"], "rival_rank": r["rank"] or 99}
    return sorted(best.values(), key=lambda r: -num(r["volume"]))[:40]


def people_ask(c):
    """'People also ask' questions from our Google results (re-read from cache: free)."""
    seen, out = set(), []
    for raw in c.read("09_serp_raw.json"):
        if raw.get("error") or raw.get("off_topic"):
            continue
        for q in seo.serp(raw["keyword"], c.loc, c.lang).get("questions") or []:
            k = q.strip().lower()
            if k not in seen:
                seen.add(k)
                out.append({"question": q.strip(), "from_search": raw["keyword"]})
    return questions_on_topic(c, out[:60])


class OnTopic(BaseModel):
    keep: list[int] = Field(description="numbers of the questions a buyer of THIS product could plausibly ask")


def questions_on_topic(c, qs):
    """Google's 'people also ask' boxes drift off-topic; keep only questions about this product or its buyers' problem."""
    if not qs:
        return qs
    try:
        out = ai.ask_json(f"""Product: {c.v['one_liner']}
Below are numbered questions from Google's "People also ask" boxes. Return the numbers of the questions that a likely buyer of this
product could ask about this product or the problem it solves. Drop trivia, questions about who made a rival, and other topics.""",
                          OnTopic, smart=False, context={"questions": {i: q["question"] for i, q in enumerate(qs)}})
    except Exception:
        return qs
    keep = [qs[i] for i in out.keep if 0 <= i < len(qs)]
    return keep if keep else qs

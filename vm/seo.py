"""DataForSEO client: every call is cached 30 days, priced before it runs, and written to the ledger with its real cost."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import budget, store
from .config import K, S

BASE = "https://api.dataforseo.com/v3/"

# Upper-bound estimates (USD) used only to refuse a call before it could break the cap.
# The real price comes back in each response ("cost") and is what the ledger records.
EST = {
    "keywords_data/google_ads/search_volume/live": 0.08,
    "keywords_data/google_trends/explore/live": 0.01,
    "serp/google/organic/live/advanced": 0.006,
    "serp/google/ai_mode/live/advanced": 0.01,
    "dataforseo_labs/google/keyword_suggestions/live": 0.02,
    "dataforseo_labs/google/bulk_keyword_difficulty/live": 0.03,
    "dataforseo_labs/google/bulk_traffic_estimation/live": 0.02,
    "dataforseo_labs/google/relevant_pages/live": 0.02,
    "backlinks/summary/live": 0.03,
    "backlinks/referring_domains/live": 0.04,
    "backlinks/bulk_ranks/live": 0.04,
    "ai_optimization/chat_gpt/llm_responses/live": 0.05,
    "ai_optimization/perplexity/llm_responses/live": 0.02,
    "ai_optimization/llm_mentions/aggregated_metrics/live": 0.12,
    "dataforseo_labs/google/domain_rank_overview/live": 0.02,
    "dataforseo_labs/google/historical_rank_overview/live": 0.16,
    "dataforseo_labs/google/ranked_keywords/live": 0.03,
    "domain_analytics/whois/overview/live": 0.15,
    "on_page/lighthouse/live/json": 0.01,
    "dataforseo_labs/google/historical_serps/live": 0.005,
}

GENERIC = {"reddit.com", "youtube.com", "wikipedia.org", "en.wikipedia.org", "amazon.com", "quora.com", "facebook.com",
           "linkedin.com", "pinterest.com", "medium.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
           "google.com", "support.google.com", "play.google.com", "apps.apple.com", "ebay.com", "yelp.com", "github.com"}


# second-level names of directories, app stores, stock sites, media and review sites (any TLD)
GENERIC_NAMES = {"yelp", "yell", "mapquest", "tripadvisor", "trustpilot", "softonic", "apkpure", "appbrain", "aptoide", "filehippo",
                 "alamy", "gettyimages", "istockphoto", "shutterstock", "adobe", "tumblr", "spotify", "mumsnet", "moneysavingexpert",
                 "techradar", "sourceforge", "slashdot", "f6s", "webcatalog", "yahoo", "bing", "msn", "bbc", "theguardian", "nytimes",
                 "forbes", "wikihow", "fandom", "imdb", "craigslist", "indeed", "glassdoor", "g2", "capterra", "softwareadvice",
                 "producthunt", "crunchbase", "ekomi", "yellowpages", "bbb", "nextdoor", "foursquare", "groupon", "apple", "microsoft"}


def _sld(d):
    parts = d.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else d


def not_competitor(domain):
    """Big platforms and government/edu sites rank everywhere but are not business competitors."""
    d = (domain or "").lower()
    if not VALID_DOMAIN.match(d):
        return True
    if d in GENERIC or any(d.endswith("." + g) for g in GENERIC) or _sld(d) in GENERIC_NAMES:
        return True
    return bool(re.search(r"(\.|^)(gov|gouv|gob|edu|ac|mil|europa)(\.[a-z]{2,3})?$", d) or d.endswith(".gov.uk") or d.endswith(".europa.eu"))


class DFSError(Exception):
    pass


def available():
    return bool(S.dfs_login and S.dfs_password)


def _key(endpoint, task):
    return hashlib.sha256((endpoint + json.dumps(task, sort_keys=True)).encode()).hexdigest()


def post(endpoint, task):
    """One task to a live endpoint. Returns the task 'result' list."""
    key = _key(endpoint, task)
    hit = store.cache_get(key, S.cache_days)
    if hit is not None:
        budget.record("dataforseo", endpoint, 0, counted=False, cached=True)
        return hit
    if not available():
        raise DFSError("DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD are not set (see .env.example)")
    budget.check(EST.get(endpoint, 0.05))
    if budget.day().get("start_balance") is None:   # first paid call of the day: remember the real balance, to check the count against it
        try:
            budget.note_start_balance(balance())
        except Exception:
            pass
    r = httpx.post(BASE + endpoint, json=[task], auth=(S.dfs_login, S.dfs_password), timeout=180)
    try:
        d = r.json()
    except ValueError:
        raise DFSError(f"{endpoint}: HTTP {r.status_code}")
    if d.get("status_code") != 20000:
        raise DFSError(f"{endpoint}: {d.get('status_code')} {d.get('status_message')}")
    t = d["tasks"][0]
    budget.record("dataforseo", endpoint, t.get("cost") or 0)
    if t.get("status_code") != 20000:
        raise DFSError(f"{endpoint}: {t.get('status_code')} {t.get('status_message')}")
    res = t.get("result") or []
    store.cache_put(key, res)
    return res


def balance():
    r = httpx.get(BASE + "appendix/user_data", auth=(S.dfs_login, S.dfs_password), timeout=30).json()
    return r["tasks"][0]["result"][0]["money"]["balance"]


def clean_kw(k):
    """Google Ads rejects symbols, >80 chars and >10 words."""
    k = re.sub(r"[^\w\s\-'&.]", " ", str(k).lower(), flags=re.UNICODE)
    k = re.sub(r"\s+", " ", k).strip()
    return " ".join(k.split()[:10])[:80]


def _uniq(kws):
    seen, out = set(), []
    for k in kws:
        c = clean_kw(k)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def search_volume(keywords, loc, lang):
    """Google Ads volume, CPC low/high, competition, 12-month trend. 1 call per 1000 keywords."""
    kws, out = _uniq(keywords), []
    for i in range(0, len(kws), 1000):
        res = post("keywords_data/google_ads/search_volume/live",
                   {"keywords": kws[i:i + 1000], "location_code": loc, "language_code": lang})
        out += [r for r in res if r]
    return out


def suggestions(seed, loc, lang, limit=40):
    res = post("dataforseo_labs/google/keyword_suggestions/live",
               {"keyword": clean_kw(seed), "location_code": loc, "language_code": lang, "limit": limit,
                "include_seed_keyword": True, "order_by": ["keyword_info.search_volume,desc"]})
    return (res[0].get("items") or []) if res else []


def keyword_difficulty(keywords, loc, lang):
    kws, out = _uniq(keywords), {}
    for i in range(0, len(kws), 1000):
        res = post("dataforseo_labs/google/bulk_keyword_difficulty/live",
                   {"keywords": kws[i:i + 1000], "location_code": loc, "language_code": lang})
        for it in (res[0].get("items") or []) if res else []:
            out[it["keyword"]] = it.get("keyword_difficulty")
    return out


def trends(keywords, loc):
    """Google Trends, 5 years, up to 5 terms. Returns {term: [(date, value), ...]}."""
    kws = _uniq(keywords)[:5]
    res = post("keywords_data/google_trends/explore/live",
               {"keywords": kws, "location_code": loc, "time_range": "past_5_years", "type": "web"})
    out = {k: [] for k in kws}
    for it in (res[0].get("items") or []) if res else []:
        if it.get("type") != "google_trends_graph":
            continue
        terms = it.get("keywords") or kws
        for pt in it.get("data") or []:
            if pt.get("missing_data"):
                continue
            for k, v in zip(terms, pt.get("values") or []):
                if v is not None:
                    out.setdefault(k, []).append((pt.get("date_from"), v))
    return out


VALID_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,24}$")


def _real(it):
    """Google sometimes hides result links behind google.com/goto?url=<encrypted>. Recover the site from the breadcrumb.
    Returns (domain, url, key) where key identifies the page for SERP-overlap clustering."""
    dom = (it.get("domain") or "").lower().removeprefix("www.")
    url = it.get("url") or ""
    if dom in ("google.com", "www.google.com") and "/goto" in url:
        bc = (it.get("breadcrumb") or "").strip()
        m = re.match(r"^(?:https?://)?(?:www\.)?([^\s/›»>]+)", bc)
        cand = m.group(1).lower() if m else ""
        if not VALID_DOMAIN.match(cand):  # breadcrumb is not a site, e.g. "10+ comments" on forum results
            name = (it.get("website_name") or "").lower().replace(" ", "")
            cand = name if VALID_DOMAIN.match(name) else (f"{name}.com" if name in ("reddit", "quora", "youtube", "facebook") else "unknown")
        dom = cand
        path = re.sub(r"\s*[›»>]\s*", "/", bc.split("://", 1)[-1]).replace("...", "")
        path = re.sub(r"/+", "/", path).strip("/ ")
        url = "https://" + path if path else "https://" + dom
        return dom, url, f"{dom}|{(it.get('title') or '').strip().lower()}"
    return dom, url, url


def _parse_serp_items(items):
    organic, features = [], {"ai_overview": False, "paid": 0, "people_also_ask": False, "video": False,
                             "local_pack": False, "featured_snippet": False}
    paid, aio_refs, questions = [], [], []
    aio = {"text": "", "refs": [], "loaded": False}
    for it in items:
        t = it.get("type")
        if t == "organic":
            dom, url, key = _real(it)
            organic.append({"rank": it.get("rank_group"), "url": url, "key": key, "domain": dom,
                            "title": it.get("title") or "", "description": (it.get("description") or "")[:200]})
        elif t == "paid":
            features["paid"] += 1
            dom, url, _ = _real(it)
            paid.append({"domain": dom, "title": it.get("title") or "", "description": (it.get("description") or "")[:200], "url": url})
        elif t == "people_also_ask":
            features["people_also_ask"] = True
            questions += [q.get("title") for q in (it.get("items") or []) if q.get("title")]
        elif t == "ai_overview":
            features["ai_overview"] = True
            aio_refs += _domains_in(it)
            aio = _aio_of(it)
        elif t in features:
            features[t] = True
    return organic, paid, features, aio_refs, questions, aio


def degraded(items):
    """Google now often serves scrapers a reduced page: links hidden behind google.com/goto, no ads, odd sites.
    Such a page does not show what real people see."""
    org = [i for i in items if i.get("type") == "organic"]
    hidden = sum(1 for i in org if "google.com/goto" in (i.get("url") or ""))
    return bool(org) and hidden / len(org) >= 0.5


def serp_snapshot(keyword, loc, lang):
    """Newest real page-1 snapshot from DataForSEO's database (historical SERPs, about $0.0005)."""
    res = post("dataforseo_labs/google/historical_serps/live", {"keyword": clean_kw(keyword), "location_code": loc, "language_code": lang})
    snaps = (res[0].get("items") or []) if res else []
    snaps = [x for x in snaps if any(i.get("type") == "organic" for i in (x.get("items") or []))]
    if not snaps:
        return None
    return max(snaps, key=lambda x: x.get("datetime") or "")


def serp(keyword, loc, lang, depth=None):
    """Google page 1. Uses the live page; if Google served a reduced (degraded) page, the organic results come from the
    newest real database snapshot instead, and only the AI Overview check is taken from the live page."""
    ep = "serp/google/organic/live/advanced"
    task = {"keyword": clean_kw(keyword), "location_code": loc, "language_code": lang, "depth": depth or K("serp_depth"), "device": "desktop"}
    full = dict(task, load_async_ai_overview=True)   # also loads an AI answer that Google fills in after the page (so we can read what it says)
    res = store.cache_get(_key(ep, full), S.cache_days)
    if res is None:
        res = store.cache_get(_key(ep, task), S.cache_days)   # a page bought before the AI text was read
        if res is None or any(i.get("type") == "ai_overview" and not (i.get("markdown") or i.get("items")) for i in ((res[0].get("items") or []) if res else [])):
            try:
                res = post(ep, full)
            except (DFSError, budget.BudgetExceeded):
                if res is None:
                    raise
        else:
            budget.record("dataforseo", ep, 0, counted=False, cached=True)
    else:
        budget.record("dataforseo", ep, 0, counted=False, cached=True)
    items = (res[0].get("items") or []) if res else []
    organic, paid, features, aio_refs, questions, aio = _parse_serp_items(items)
    source = "live"
    if degraded(items):
        snap = serp_snapshot(keyword, loc, lang)
        if snap:
            o2, p2, f2, _a, q2, _x = _parse_serp_items(snap.get("items") or [])
            live_aio = features["ai_overview"]
            organic, paid, questions = o2, p2, (q2 or questions)
            features = dict(f2, ai_overview=live_aio or f2["ai_overview"])
            source = "database snapshot %s" % (snap.get("datetime") or "")[:10]
        else:
            source = "live (reduced page, no snapshot)"
    return {"keyword": keyword, "organic": organic, "paid": paid, "features": features, "ai_overview_sources": sorted(set(aio_refs)),
            "ai_overview": aio, "questions": questions, "source": source}


def _aio_of(it):
    """What a Google AI Overview says and which pages it links: {'text', 'refs': [{'domain', 'title'}], 'loaded'}.
    loaded False = Google showed an AI answer but its text was not delivered (never read that as 'says nothing')."""
    parts = [it.get("markdown") or ""] + [(x.get("markdown") or x.get("text") or "") for x in (it.get("items") or [])]
    text = "\n".join(p for p in parts if p)
    text = re.sub(r"\[\[\d+\]\]\([^)]*\)", "", text)                       # footnote marks
    text = re.sub(r"\[([^\]]*)\]\((?:https?://)[^)]*\)", r"\1", text)      # keep the link words, drop the address
    text = re.sub(r"\[Highlight (start|end)\]|Loading AI-generated quiz\.\.\.", " ", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    refs, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            d = (o.get("domain") or "").lower().removeprefix("www.")
            if d and d != "google.com" and o.get("type") in ("ai_overview_reference", "ai_overview_link", None) and (d, o.get("title")) not in seen and (o.get("title") or o.get("url")):
                seen.add((d, o.get("title")))
                refs.append({"domain": d, "title": (o.get("title") or "")[:120]})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(it)
    return {"text": text[:2500], "refs": refs[:12], "loaded": bool(text)}


def ai_mode(question, loc=2840, lang="en"):
    """Ask Google's AI Mode one question (about $0.004). Returns {'text', 'refs': [{'domain', 'title'}]}; text '' when it gave no answer."""
    res = post("serp/google/ai_mode/live/advanced", {"keyword": question[:700], "location_code": loc, "language_code": lang})
    for it in ((res[0].get("items") or []) if res else []):
        if it.get("type") == "ai_overview":
            a = _aio_of(it)
            a["text"] = re.sub(r"\[\[\d+\]\]|\u2060", "", a["text"])
            return a
    return {"text": "", "refs": [], "loaded": False}


def _domains_in(obj):
    """Every 'domain' inside an AI Overview block (its cited references and links)."""
    out = []
    if isinstance(obj, dict):
        d = obj.get("domain")
        if isinstance(d, str) and d and d.lower().removeprefix("www.") != "google.com":  # google.com = hidden redirect links
            out.append(d.lower().removeprefix("www."))
        for v in obj.values():
            out += _domains_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _domains_in(v)
    return out


def ai_answer(engine, prompt, country_iso="US"):
    """Ask ChatGPT (with web search) or Perplexity a buyer question. Returns text + the sites it cited."""
    if engine == "chatgpt":
        res = post("ai_optimization/chat_gpt/llm_responses/live",
                   {"user_prompt": prompt[:500], "model_name": "gpt-4.1-mini", "web_search": True, "max_output_tokens": 700,
                    "web_search_country_iso_code": country_iso.upper()})
    else:
        res = post("ai_optimization/perplexity/llm_responses/live",
                   {"user_prompt": prompt[:500], "model_name": "sonar", "max_output_tokens": 700, "web_search_country_iso_code": country_iso.upper()})
    r = res[0] if res else {}
    text, urls = "", []
    for it in r.get("items") or []:
        for sec in it.get("sections") or []:
            text += (sec.get("text") or "") + "\n"
            urls += [a.get("url") for a in (sec.get("annotations") or []) if a.get("url")]
    urls += [x.get("url") for x in (r.get("search_results") or []) if x.get("url")]
    doms = []
    for u in urls:
        m = re.match(r"^https?://(?:www\.)?([^/:?#]+)", u or "")
        if m and m.group(1).lower() not in doms:
            doms.append(m.group(1).lower())
    return {"engine": engine, "prompt": prompt, "text": text.strip(), "cited": doms}


def ai_sources(keyword, loc, lang):
    """Which sites Google's AI Overviews cite most on this topic (DataForSEO LLM Mentions)."""
    res = post("ai_optimization/llm_mentions/aggregated_metrics/live",
               {"location_code": loc, "language_code": lang, "platform": "google",
                "target": [{"keyword": clean_kw(keyword), "search_scope": ["any"]}], "internal_list_limit": 20})
    tot = (res[0].get("total") or {}) if res else {}
    pick = lambda k: [{"site": (g.get("key") or "").removeprefix("www."), "mentions": g.get("mentions")} for g in (tot.get(k) or [])]
    return {"sources": pick("sources_domain"), "brands": pick("brand_entities_title"),
            "answers": sum((g.get("mentions") or 0) for g in (tot.get("platform") or []))}


def serps(keywords, loc, lang, workers=10):
    with ThreadPoolExecutor(workers) as ex:
        ctx = dict(budget.CURRENT)

        def one(k):
            budget.CURRENT.update(ctx)
            try:
                return serp(k, loc, lang)
            except budget.BudgetExceeded:
                raise
            except Exception as e:
                return {"keyword": k, "error": str(e)[:200], "organic": [], "paid": [], "features": {}}
        return list(ex.map(one, keywords))


def domain_ranks(domains):
    """0-100 domain rank (DataForSEO's DR-like score)."""
    ds = sorted({d for d in domains if d and VALID_DOMAIN.match(d)})
    out = {}
    for i in range(0, len(ds), 1000):
        res = post("backlinks/bulk_ranks/live", {"targets": ds[i:i + 1000], "rank_scale": "one_hundred"})
        for it in (res[0].get("items") or []) if res else []:
            out[it["target"]] = it.get("rank")
    return out


def backlinks_summary(domain):
    res = post("backlinks/summary/live", {"target": domain, "include_subdomains": True, "rank_scale": "one_hundred",
                                          "internal_list_limit": 1, "backlinks_status_type": "live"})
    r = res[0] if res else {}
    return {"domain": domain, "dr": r.get("rank"), "backlinks": r.get("backlinks"),
            "referring_domains": r.get("referring_domains"), "first_seen": r.get("first_seen")}


def referring_domains(domain, limit=300):
    res = post("backlinks/referring_domains/live", {"target": domain, "limit": limit, "rank_scale": "one_hundred",
                                                     "order_by": ["rank,desc"], "backlinks_status_type": "live",
                                                     "exclude_internal_backlinks": True})
    return [{"domain": it.get("domain"), "dr": it.get("rank"), "backlinks": it.get("backlinks")}
            for it in ((res[0].get("items") or []) if res else [])]


def traffic(domains, loc, lang):
    res = post("dataforseo_labs/google/bulk_traffic_estimation/live",
               {"targets": list(domains)[:1000], "location_code": loc, "language_code": lang, "item_types": ["organic"]})
    out = {}
    for it in (res[0].get("items") or []) if res else []:
        org = (it.get("metrics") or {}).get("organic") or {}
        out[it.get("target")] = {"etv": org.get("etv"), "keywords": org.get("count")}
    return out


def top_pages(domain, loc, lang, limit=10):
    res = post("dataforseo_labs/google/relevant_pages/live",
               {"target": domain, "location_code": loc, "language_code": lang, "limit": limit,
                "order_by": ["metrics.organic.etv,desc"]})
    out = []
    for it in (res[0].get("items") or []) if res else []:
        org = (it.get("metrics") or {}).get("organic") or {}
        out.append({"url": it.get("page_address"), "etv": org.get("etv"), "keywords": org.get("count")})
    return out


def rank_overview(domain, loc, lang):
    """Google traffic a site gets: visits/month (estimate), keywords it ranks for, and what that traffic would cost in ads."""
    res = post("dataforseo_labs/google/domain_rank_overview/live", {"target": domain, "location_code": loc, "language_code": lang})
    it = ((res[0].get("items") or [{}])[0] if res else {}) or {}
    o = (it.get("metrics") or {}).get("organic") or {}
    return {"visits": o.get("etv"), "keywords": o.get("count"), "ads_value": o.get("estimated_paid_traffic_cost"),
            "top3": (o.get("pos_1") or 0) + (o.get("pos_2_3") or 0), "new_keywords": o.get("is_new"), "lost_keywords": o.get("is_lost")}


def traffic_history(domain, loc, lang, months=12):
    """Monthly Google visits (estimate) for the last ~12 months, oldest first."""
    import datetime as _dt
    start = (_dt.date.today().replace(day=1) - _dt.timedelta(days=31 * months)).replace(day=1).isoformat()
    res = post("dataforseo_labs/google/historical_rank_overview/live",
               {"target": domain, "location_code": loc, "language_code": lang, "date_from": start})
    rows = []
    for it in (res[0].get("items") or []) if res else []:
        o = (it.get("metrics") or {}).get("organic") or {}
        rows.append({"month": "%04d-%02d" % (it.get("year") or 0, it.get("month") or 0), "visits": round(o.get("etv") or 0)})
    return sorted(rows, key=lambda r: r["month"])


def ranked_keywords(domain, loc, lang, limit=100, max_rank=20):
    """Searches a site ranks for on page 1-2, biggest first."""
    res = post("dataforseo_labs/google/ranked_keywords/live",
               {"target": domain, "location_code": loc, "language_code": lang, "limit": limit,
                "filters": [["ranked_serp_element.serp_item.rank_group", "<=", max_rank]],
                "order_by": ["keyword_data.keyword_info.search_volume,desc"]})
    out = []
    for it in (res[0].get("items") or []) if res else []:
        kd = it.get("keyword_data") or {}
        ki = kd.get("keyword_info") or {}
        out.append({"keyword": kd.get("keyword"), "volume": ki.get("search_volume"), "cpc": ki.get("cpc"),
                    "kd": (kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                    "rank": ((it.get("ranked_serp_element") or {}).get("serp_item") or {}).get("rank_group")})
    return out


def domain_ages(domains):
    """WHOIS creation date per domain (one call for all)."""
    ds = [d for d in domains if VALID_DOMAIN.match(d or "")][:100]
    if not ds:
        return {}
    res = post("domain_analytics/whois/overview/live", {"limit": len(ds), "filters": [["domain", "in", ds]]})
    return {it.get("domain"): (it.get("created_datetime") or "")[:10] for it in ((res[0].get("items") or []) if res else [])}


def _lighthouse_local(url, mobile=True):
    """Performance score 0-100 from a local Lighthouse run, cached 30 days. None when Lighthouse is not installed or the run failed."""
    import shutil
    import subprocess
    import os
    exe = shutil.which("lighthouse") if os.environ.get("VM_LIGHTHOUSE", "").lower() == "local" else None
    if not exe:
        return None
    key = _key("local/lighthouse", {"url": url, "mobile": mobile})
    hit = store.cache_get(key, S.cache_days)
    if hit is not None:
        return hit.get("score")
    cmd = [exe, url, "--only-categories=performance", "--output=json", "--quiet", "--chrome-flags=--headless=new --no-first-run", "--max-wait-for-load=45000"]
    if not mobile:
        cmd.append("--preset=desktop")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        j = json.loads(r.stdout)
        sc = j["categories"]["performance"]["score"]
        if j.get("runtimeError") or not isinstance(sc, (int, float)):
            return None
    except Exception:
        return None
    store.cache_put(key, {"score": round(sc * 100)})
    return round(sc * 100)


def speed_score(url, mobile=True):
    """Google Lighthouse performance score 0-100 (mobile by default)."""
    if not url.startswith("http"):
        url = "https://" + url
    local = _lighthouse_local(url, mobile)   # free, when VM_LIGHTHOUSE=local and Google's own Lighthouse tool is installed (npm install -g lighthouse)
    if local is not None:
        return local
    res = post("on_page/lighthouse/live/json", {"url": url, "for_mobile": mobile, "categories": ["performance"]})
    sc = ((res[0].get("categories") or {}).get("performance") or {}).get("score") if res else None
    return round(sc * 100) if isinstance(sc, (int, float)) else None

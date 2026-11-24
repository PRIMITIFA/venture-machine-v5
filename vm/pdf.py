"""Findings PDF: everything the machine found out about one idea, written to be read (not a status page).

Built as print-ready HTML, then turned into a PDF with Playwright if installed, otherwise with Chrome / Edge /
Chromium in headless mode (already on most computers). Output: ventures/<slug>/<slug>-findings.pdf
"""
import html
import json
import os
import pathlib
import re
import shutil
import subprocess

from . import store
from .config import S
from .pipeline import registry
from .report import status_label
from .util import num, read_csv

CSS = """
@page{size:A4;margin:16mm 14mm 18mm}
*{box-sizing:border-box}html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font:10pt/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c1917;margin:0}
h1{font-size:22pt;line-height:1.2;margin:0 0 6pt}h2{font-size:14pt;margin:0 0 8pt;padding-bottom:4pt;border-bottom:2px solid #1c1917;break-before:page}
h3{font-size:11pt;margin:14pt 0 5pt}p{margin:0 0 6pt}ul{margin:0 0 6pt;padding-left:16pt}li{margin:0 0 2pt}
.mute{color:#78716c}.small{font-size:8.5pt}a{color:#1d4ed8;text-decoration:none;word-break:break-all}
table{border-collapse:collapse;width:100%;margin:4pt 0 10pt;font-size:8.5pt}th,td{text-align:left;padding:3pt 5pt;border-bottom:1px solid #e7e5e4;vertical-align:top}
th{background:#f5f5f4;font-weight:600}tr{break-inside:avoid}
.cover{min-height:240mm;display:flex;flex-direction:column}.tag{font-size:9pt;letter-spacing:.04em;color:#78716c;margin-bottom:28pt}
.verdict{border:2px solid #1c1917;border-radius:8pt;padding:12pt 14pt;margin:18pt 0}.verdict .big{font-size:18pt;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8pt;margin:8pt 0 12pt}.kpi{border:1px solid #e7e5e4;border-radius:6pt;padding:7pt 9pt}
.kpi .v{font-size:13pt;font-weight:700}.kpi .l{font-size:8pt;color:#78716c}
.pass{color:#15803d;font-weight:600}.warn{color:#b45309;font-weight:600}.kill,.redo{color:#b91c1c;font-weight:600}
.box{background:#fafaf9;border:1px solid #e7e5e4;border-radius:6pt;padding:8pt 10pt;margin:6pt 0 10pt}
pre{white-space:pre-wrap;font:8.5pt/1.45 Consolas,ui-monospace,monospace;margin:0}
"""


def e(x):
    return html.escape(str(x if x is not None else ""))


def link(u, text=None):
    u = str(u or "")
    return f'<a href="{e(u)}">{e(text or u)}</a>' if u.startswith("http") else e(text or u)


def money(x):
    return f"${num(x):,.0f}" if num(x) >= 100 else f"${num(x):,.2f}"


def table(rows, cols, heads=None, limit=None):
    rows = rows[:limit] if limit else rows
    if not rows:
        return "<p class=mute>none</p>"
    h = "<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in (heads or cols)) + "</tr>"
    for r in rows:
        h += "<tr>" + "".join(f"<td>{r.get(c, '') if str(r.get(c, '')).startswith('<a ') else e(r.get(c, ''))}</td>" for c in cols) + "</tr>"
    return h + "</table>"


def bullets(xs):
    xs = [x for x in (xs or []) if x]
    return "<ul>" + "".join(f"<li>{link(x) if str(x).startswith('http') else e(x)}</li>" for x in xs) + "</ul>" if xs else "<p class=mute>none</p>"


def md(text):
    """Tiny markdown -> HTML for the plan/SWOT files (headings, bullets, tables, bold)."""
    out, rows, lst = [], [], []

    def flush():
        nonlocal rows, lst
        if rows:
            hdr, body = rows[0], [r for r in rows[1:] if not re.match(r"^\|?[\s:-]+\|", "|".join(r))]
            out.append("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in hdr) + "</tr>" +
                       "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")
            rows = []
        if lst:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in lst) + "</ul>")
            lst = []
    for line in (text or "").splitlines():
        s = line.strip()
        inline = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(s))
        if s.startswith("|"):
            if lst:
                flush()
            rows.append([c.strip() for c in s.strip("|").split("|")])
            continue
        if rows:
            flush()
        if s.startswith("#"):
            flush()
            if not s.startswith("# "):
                out.append(f"<h3>{e(s.lstrip('#').strip())}</h3>")
        elif re.match(r"^(-|\d+\.)\s", s):
            lst.append(re.sub(r"^(-|\d+\.)\s+", "", inline))
        elif s:
            flush()
            out.append(f"<p>{inline}</p>")
    flush()
    return "\n".join(out)


def urls_in(obj, acc):
    if isinstance(obj, dict):
        for v in obj.values():
            urls_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            urls_in(v, acc)
    elif isinstance(obj, str):
        for u in re.findall(r"https?://[^\s\"'<>)\]]+", obj):
            if "google.com/goto" not in u:
                acc.setdefault(u.rstrip(".,;"), None)


def build_html(slug):
    v = store.venture(slug)
    d = S.ventures_dir / slug

    def jf(name):
        p = d / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def cf(name):
        p = d / name
        return read_csv(p) if p.exists() else None

    def tf(name):
        p = d / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    bl = store.blocks(slug)
    sc, how, eeat, pulse = jf("05_scorecard.json"), jf("02_how_analysis.json"), jf("03_eeat_quality.json"), jf("04_niche_pulse.json")
    kws, short, clusters, comps = cf("08_keywords_clean.csv"), cf("11_shortlist.csv"), jf("10_clusters_serp.json"), jf("11_top_competitors.json")
    ux, biz, mk, seo_, links = jf("12_competitor_ux.json"), jf("13_competitor_business.json"), jf("14_market_analysis.json"), jf("15_competitor_seo.json"), cf("15_link_targets.csv")
    costs, ue = jf("15_costs.json"), jf("16_unit_economics.json")
    data = v["data"]
    H = []

    # ---------- cover ----------
    rec = data.get("gate3_recommendation")
    decisions = store.gates(slug)
    last = decisions[-1] if decisions else None
    verdict = (f"Gate 3 score {data.get('gate3_score')}/5: <b>{e(rec)}</b>" if rec else
               "Research stopped before gate 3" if v["status"] in ("killed", "kill_recommended", "alert") else "Research in progress")
    buy = [k for k in (kws or []) if k["intent"] in ("buy", "competitor", "brand-model")]
    kpis = []
    if buy:
        kpis += [(f"{int(sum(num(k['volume']) for k in buy)):,}/mo", "buying-intent searches"), (money(max(num(k['cpc']) for k in buy)), "top buying CPC")]
    if mk:
        kpis += [(money(mk["bottom_up_usd_year"]) + "/yr", "market, bottom-up"), (money(mk["top_down_usd_year"]) + "/yr", "market, top-down")]
    if seo_:
        drs = [num(s["dr"], 100) for s in seo_["competitors"] if s.get("dr") is not None]
        if drs:
            kpis.append((f"DR {min(drs):.0f}", "weakest top-5 competitor"))
    if links is not None:
        kpis.append((str(len(links)), "link targets"))
    if sc:
        kpis += [(str(sc["ice_avg"]), "ICE score (of 10)"), (f"{sc['effort']['days_to_mvp']} days", "to an MVP")]
    if data.get("unit_economics"):
        kpis.append((money(data["unit_economics"].get("net_per_sale")), "net per sale"))
    kpi_html = "".join("<div class=kpi><div class=v>%s</div><div class=l>%s</div></div>" % (e(a), e(b)) for a, b in kpis)
    last_html = ("<p class=small>Last owner decision: gate %s %s %s</p>" % (e(last["gate"]), e(last["decision"].upper()), e(last["note"]))) if last else ""
    pivot_html = ("<p class=small><b>Pivot:</b> %s</p>" % e(v["pivot_note"])) if v.get("pivot_note") else ""
    three = ("<h3>In three lines</h3>" + bullets(sc["summary_3_lines"])) if sc else ""
    H.append("<section class=cover><div class=tag>THE VENTURE MACHINE &middot; FINDINGS REPORT</div>"
             + "<h1>%s</h1>" % e(v["one_liner"] or v["idea"])
             + "<p class=mute>Idea: %s<br>Market: %s / %s &middot; Started %s &middot; Report %s</p>" % (e(v["idea"]), e(v["country"].upper()), e(v["lang"]), e(v["created"][:10]), e(store.now()[:16]))
             + "<div class=verdict><div class=mute>Where it stands</div><div class=big>%s</div><p style='margin:4pt 0 0'>%s</p>%s%s</div>" % (e(status_label(v["status"])), verdict, last_html, pivot_html)
             + "<div class=grid>%s</div>%s" % (kpi_html, three)
             + "<p class='small mute' style='margin-top:auto'>Every number comes from DataForSEO or a page the AI opened (sources at the end). "
             + "Figures marked ASSUMPTION are not measured. Paid data spent on this idea: %s.</p></section>" % money(store.spent(slug)))

    # ---------- checks ----------
    rows = []
    for b in registry():
        st = bl.get(b.id)
        if not st:
            continue
        verd = st.get("verdict") or st["status"].lower()
        rows.append(f"<tr><td>{b.id}</td><td>{e(b.name)}</td><td class='{e(verd)}'>{e(verd.upper())}</td><td>{e((st.get('summary') or st.get('error') or '')[:400])}</td></tr>")
    H.append("<h2>1. The checks, block by block</h2><table><tr><th>#</th><th>Block</th><th>Result</th><th>What it found</th></tr>" + "".join(rows) + "</table>")

    # ---------- idea ----------
    if how:
        cp = [{"name": c["name"], "price": c["price"], "model": c["pricing_model"], "source": link(c["source_url"], "source")} for c in how["competitors"]]
        H.append("<h2>2. The business</h2><h3>Who already charges money</h3>" + table(cp, ["name", "price", "model", "source"]) +
                 f"<h3>How it makes money</h3>{bullets(how['revenue_models'])}<h3>Where the data comes from</h3>" +
                 table([{"name": s["name"], "type": s["type"], "url": link(s.get("url"), "link") if s.get("url") else "", "cost": s.get("cost_note", "")} for s in how["data_sources"]], ["name", "type", "url", "cost"]) +
                 f"<div class=box><b>The one question that decides it:</b> {e(how['validation_question'])}</div>")
        if eeat:
            er = [{"check": k.replace("_", " "), "ok": "yes" if eeat[k]["ok"] else "NO", "answer": eeat[k]["answer"]}
                  for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example")]
            H.append(f"<h3>Google quality (E-E-A-T)</h3>{table(er, ['check', 'ok', 'answer'])}<p>YMYL risk: <b>{e(eeat['ymyl_level'])}</b>. Never claim:</p>{bullets(eeat.get('ymyl_banned_claims'))}")
    if pulse:
        tr = [{"term": t, "change_24m": f"{x['change_24m_pct']}%" if x["change_24m_pct"] is not None else "n/a"} for t, x in pulse.get("trend", {}).items()]
        H.append(f"<h3>Is the niche alive? <span class='{'kill' if pulse['status'] == 'dying' else 'pass' if pulse['status'] == 'alive' else 'warn'}'>{e(pulse['status'].upper())}</span></h3>"
                 f"{table(tr, ['term', 'change_24m'], ['search term', '24-month change (Google Trends)'])}"
                 f"<p>Ads on the top term: {e(pulse.get('ads_on_top_term'))} {e(', '.join(pulse.get('advertisers') or []))}</p>"
                 f"<p><b>Rising synonyms:</b> {e(', '.join(pulse.get('rising_synonyms') or []) or 'none')}</p>"
                 f"<p><b>New players (12 months):</b></p>{bullets(pulse.get('new_competitors_12m'))}<p><b>Fresh discussions (90 days):</b></p>{bullets(pulse.get('fresh_discussions_90d'))}")
    if sc:
        H.append(f"<h3>For and against</h3><table><tr><th>For</th><th>Against</th></tr>" +
                 "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td></tr>" for a, b in zip(sc["pros"], sc["cons"])) + "</table>"
                 f"<p><b>Biggest unknown:</b> {e(sc['biggest_unknown'])}</p>"
                 f"<p><b>Effort:</b> {sc['effort']['days_to_mvp']} days to MVP, about {money(sc['effort']['monthly_cost_usd'])}/month, {sc['effort']['owner_hours_per_week']} owner hours/week. "
                 f"APIs: {e(', '.join(sc['effort']['api_dependencies']))}</p><p><b>ICE:</b> impact {sc['ice']['impact']}, confidence {sc['ice']['confidence']}, ease {sc['ice']['ease']} = {sc['ice_avg']}</p>"
                 f"<p><b>Synergy:</b> {e(sc['synergy'])}</p>" + (f"<p><b>Risks:</b></p>{bullets(sc.get('risks'))}" if sc.get("risks") else ""))

    # ---------- demand ----------
    if short:
        H.append("<h2>3. Demand: what people search for</h2>"
                 f"<p>{len(kws or [])} real keywords after cleaning (Google Ads data, {e(v['country'].upper())}). "
                 "Score = volume x max(CPC, 0.30) x intent weight / (KD + 5).</p><h3>Shortlist</h3>" +
                 table(short, ["role", "keyword", "volume", "cpc", "intent", "kd", "trend12", "score"],
                       ["role", "keyword", "searches/mo", "CPC $", "intent", "KD", "12-mo trend %", "score"], 45))
    if clusters:
        cr = [{"head": c["head"], "kws": len(c["keywords"]), "volume": int(c["volume"]), "intent": c["intent"], "kd": c.get("kd", ""),
               "format": c["winning_format"], "weak": "; ".join(c["weak_spots"]) or ("better format possible" if c.get("better_format_possible") else "")} for c in clusters]
        H.append("<h3>Topic clusters (1 cluster = 1 page)</h3>" + table(cr, ["head", "kws", "volume", "intent", "kd", "format", "weak"],
                                                                     ["main keyword", "keywords", "searches/mo", "intent", "KD", "what ranks", "weak spots"], 25))

    # ---------- competitors ----------
    if comps:
        dr = {s["domain"]: s for s in (seo_ or {}).get("competitors", [])}
        uxd = {x["domain"]: x for x in (ux or {}).get("competitors", [])}
        rows = [{"domain": c["domain"], "dr": dr.get(c["domain"], {}).get("dr", c.get("dr")), "rd": dr.get(c["domain"], {}).get("referring_domains", ""),
                 "serps": c["serps"], "checkout": ", ".join(uxd.get(c["domain"], {}).get("checkout_provider") or []),
                 "sitemap": uxd.get(c["domain"], {}).get("sitemap_urls") or "-"} for c in comps]
        H.append("<h2>4. Competitors</h2><p>The real top 5, picked by how often and how high they rank across all our searches (big platforms and government sites left out).</p>" +
                 table(rows, ["domain", "dr", "rd", "serps", "checkout", "sitemap"], ["site", "DR", "linking sites", "in # SERPs", "checkout", "pages"]))
        for x in (ux or {}).get("competitors", []):
            H.append(f"<h3>{e(x['domain'])}</h3><table><tr><th>Weak spots</th><th>Strong spots</th></tr><tr><td>{bullets(x.get('weaknesses'))}</td><td>{bullets(x.get('strengths'))}</td></tr></table>")
    if biz:
        plans = [{"site": x["domain"], "plan": p["name"], "price": p["price"], "billing": p["billing"]} for x in biz["competitors"] for p in x["plans"]]
        H.append("<h3>Their prices</h3>" + table(plans, ["site", "plan", "price", "billing"]) +
                 f"<div class=box><b>The gap we can own:</b> {e(biz['identified_gap'])}</div>")
        ads = [{"site": dom, "keyword": a["keyword"], "ad": f"{a['title']} - {a['description']}"} for dom, lst in (biz.get("google_ads_in_serps") or {}).items() for a in lst[:4]]
        if ads:
            H.append("<h3>Google ads running on our keywords</h3>" + table(ads, ["site", "keyword", "ad"], limit=20))
        if biz.get("long_running_ads"):
            H.append("<h3>Ads running 30+ days</h3>" + bullets(biz["long_running_ads"]))
        if biz.get("audience_quotes"):
            H.append("<h3>What buyers say</h3><ul>" + "".join(f"<li>&ldquo;{e(q['quote'])}&rdquo; {link(q['url'], 'source')}</li>" for q in biz["audience_quotes"]) + "</ul>")

    # ---------- market ----------
    if mk:
        country_rows = [{"country": k.upper(), "searches": val} for k, val in mk.get("search_volume_by_country", {}).items()]
        differ = "<p class=warn>The two methods differ by more than 10x.</p>" if mk.get("methods_differ_10x") else ""
        H.append("<h2>5. Market size</h2><div class=grid>"
                 + "<div class=kpi><div class=v>%s/yr</div><div class=l>bottom-up</div></div>" % money(mk["bottom_up_usd_year"])
                 + "<div class=kpi><div class=v>%s/yr</div><div class=l>top-down</div></div>" % money(mk["top_down_usd_year"])
                 + "<div class=kpi><div class=v>%s</div><div class=l>year-1 goal</div></div></div>" % money(mk["year1_goal_usd"])
                 + "<p><b>Bottom-up:</b> %s</p><p><b>Top-down:</b> %s</p>" % (e(mk["bottom_up_method"]), e(mk["top_down_method"]))
                 + bullets(mk.get("top_down_sources")) + differ
                 + "<h3>Searches by country (main keywords)</h3>" + table(country_rows, ["country", "searches"])
                 + "<h3>Buyer segments</h3>" + "".join(f"<p><b>{e(s['name'])}</b>{' (underserved)' if s['underserved'] else ''}: {e(s['size_note'])}</p>" +
                                    ("<ul>" + "".join(f"<li>&ldquo;{e(q['quote'])}&rdquo; {link(q['url'], 'source')}</li>" for q in s["pain_quotes"]) + "</ul>" if s["pain_quotes"] else "")
                                    for s in mk.get("segments", [])) +
                 f"<h3>Underserved</h3>{bullets(mk.get('underserved_countries_or_segments'))}<p><b>Growth:</b> {e(mk.get('growth_direction'))}: {e(mk.get('growth_evidence'))}</p>")
    if seo_:
        H.append("<h2>6. SEO strength and links</h2>" + table(
            [{"site": s["domain"], "dr": s["dr"], "rd": s["referring_domains"], "bl": s["backlinks"], "tools": ", ".join(s.get("free_tool_pages") or [])[:200]} for s in seo_["competitors"]],
            ["site", "dr", "rd", "bl", "tools"], ["site", "DR", "linking sites", "backlinks", "free-tool pages"]))
        for s in seo_["competitors"]:
            if s.get("top_pages"):
                H.append(f"<h3>{e(s['domain'])}: pages with the most traffic</h3>" + table(
                    [{"page": link(p["url"]), "traffic": int(num(p["etv"])), "keywords": p["keywords"]} for p in s["top_pages"][:6]], ["page", "traffic", "keywords"], ["page", "visits/mo (est.)", "keywords"]))
        if links:
            H.append(f"<h3>Link targets: sites that link to 2+ competitors but not to us ({len(links)})</h3>" +
                     table(links, ["domain", "dr", "links_to_n", "competitors"], ["site", "DR", "links to # competitors", "which"], 30))

    # ---------- plan ----------
    if costs:
        H.append("<h2>7. Costs, guardrails, to-do</h2>" + table([t for t in costs["tools"]], ["name", "purpose", "cost_start_usd_month", "cost_10x_usd_month", "limit", "account_owner"],
                                                               ["tool", "for", "$/mo now", "$/mo at 10x", "limit", "owner"]) +
                 f"<p>Data cost per sale: <b>{money(costs['data_cost_per_sale_usd'])}</b></p><h3>Marketing channels (thresholds fixed now)</h3>" +
                 table(costs["marketing"], ["channel", "cost", "cap", "pass_threshold", "kill_threshold"], ["channel", "cost", "cap", "pass if", "kill if"]) +
                 f"<h3>Guardrails for this business</h3>{bullets(costs['guardrails'])}<h3>Your manual to-do (block 19)</h3>" +
                 table(costs["owner_todo"], ["task", "why", "minutes"]) + f"<h3>Open questions for you</h3>{bullets(costs['owner_questions'])}")
    if ue:
        H.append("<h2>8. Money: unit economics</h2>" + table(ue["options"], ["model", "price_usd", "conversion_pct", "retention_months", "net_per_sale", "max_cac", "breakeven_cpc", "paid_search_cac"],
                                                            ["model", "price $", "conversion %", "months kept", "net/sale $", "max CAC $", "break-even CPC $", "paid-search CAC $"]) +
                 f"<p><b>Chosen:</b> {e(ue['chosen']['model'])}: the most profit per owner hour.</p><h3>Goal ladder</h3>" + table(ue["ladder"], ["goal", "by"]))
    if (t := tf("18_swot.md")):
        H.append("<h3>SWOT</h3>" + md(t))
    if (t := tf("19_business_plan.md")):
        H.append("<h2>9. The plan</h2>" + md(t))
    if (cal := cf("19_seo_calendar_90d.csv")):
        H.append("<h3>90-day calendar</h3>" + table(cal, ["week", "date", "type", "item", "keyword", "kd"], limit=60))
    if (t := tf("18_gate3_memo.md")):
        H.append("<h2>10. Gate 3 decision memo</h2><pre>" + e(t.replace("# Gate 3 memo", "").strip()) + "</pre>")
    if (t := tf("20_quick_test.md")):
        H.append("<h3>Quick test</h3>" + md(t))
    if decisions:
        H.append("<h3>Owner decisions</h3>" + table(decisions, ["ts", "gate", "decision", "note"], ["when", "gate", "decision", "note"]))

    # ---------- sources + spend ----------
    acc = {}
    for name in ("02_how_analysis.json", "04_niche_pulse.json", "13_competitor_business.json", "14_market_analysis.json"):
        if (x := jf(name)):
            urls_in(x, acc)
    led = store.ledger(slug)
    by = {}
    for r in led:
        a = by.setdefault(r["provider"], {"provider": r["provider"], "calls": 0, "cached": 0, "usd": 0.0})
        a["calls"] += 1
        a["cached"] += r["cached"]
        a["usd"] = round(a["usd"] + r["usd"], 3)
    H.append("<h2>Sources and spend</h2><p class=small>Pages the research used (opened by the AI or returned by DataForSEO):</p><ol class=small>" +
             "".join(f"<li>{link(u)}</li>" for u in list(acc)[:200]) + "</ol>" +
             table(list(by.values()), ["provider", "calls", "cached", "usd"], ["provider", "calls", "from cache", "USD"]) +
             f"<p class=small>Counted against the cap: {money(store.spent(slug))} of {money(S.max_usd_per_idea)}. Claude Code CLI runs on a subscription and is not counted unless VM_COUNT_CLI_COST=1.</p>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{e(slug)} findings</title><style>{CSS}</style></head>"
            f"<body>{''.join(H)}</body></html>")


BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_browser():
    if os.environ.get("VM_BROWSER"):
        return os.environ["VM_BROWSER"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        if (p := shutil.which(name)):
            return p
    return next((b for b in BROWSERS if os.path.exists(b)), None)


def html_to_pdf(html_path, pdf_path):
    """Returns (ok, how)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page()
            pg.goto(pathlib.Path(html_path).resolve().as_uri())
            pg.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True,
                   display_header_footer=True, header_template="<span></span>",
                   footer_template="<div style='font-size:7pt;color:#999;width:100%;text-align:center'><span class=pageNumber></span> / <span class=totalPages></span></div>",
                   margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
            b.close()
        return True, "playwright"
    except Exception:
        pass
    br = find_browser()
    if not br:
        return False, "no Chrome/Edge/Chromium found (install one, or: pip install playwright && playwright install chromium)"
    pdf_path = pathlib.Path(pdf_path).resolve()
    if pdf_path.exists():
        pdf_path.unlink()
    cmd = [br, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run", f"--print-to-pdf={pdf_path}",
           pathlib.Path(html_path).resolve().as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as ex:
        return False, f"browser failed: {ex}"
    return pdf_path.exists() and pdf_path.stat().st_size > 1000, pathlib.Path(br).name


def write(slug):
    """Writes ventures/<slug>/findings.html and <slug>-findings.pdf. Returns (pdf_path or None, message)."""
    d = S.ventures_dir / slug
    d.mkdir(parents=True, exist_ok=True)
    h = d / "findings.html"
    h.write_text(build_html(slug), encoding="utf-8")
    pdf = d / f"{slug}-findings.pdf"
    ok, how = html_to_pdf(h, pdf)
    return (pdf if ok else None), (f"PDF made with {how}" if ok else f"PDF not made: {how}. Open {h} and print it to PDF.")

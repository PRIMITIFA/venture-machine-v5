"""Findings PDF: what the machine found out about one idea, written so anyone can follow it.

Order: the answer first (build / test / don't), then one plain question per section, each opening with an
"In plain words" box, then the proof. Heavy tables go to the appendix. A glossary explains every term.

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
from .util import num, read_csv

INK, MUTE, LINE, SOFT = "#18181b", "#71717a", "#e4e4e7", "#f4f4f5"
GOOD, CARE, BAD, INFO = "#16a34a", "#d97706", "#dc2626", "#2563eb"

CSS = """
@page{size:A4;margin:14mm 14mm 16mm}
*{box-sizing:border-box}html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font:10.5pt/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:%(INK)s;margin:0}
h1{font-size:20pt;line-height:1.15;margin:0 0 8pt;letter-spacing:-.01em}
h2{font-size:17pt;line-height:1.2;margin:0 0 4pt;letter-spacing:-.01em}
.sec{break-before:page}.sec .num{display:inline-block;font-size:9pt;font-weight:700;color:#fff;background:%(INK)s;border-radius:99px;padding:1pt 8pt;margin-bottom:6pt}
h3{font-size:11.5pt;margin:14pt 0 5pt}p{margin:0 0 6pt}ul{margin:0 0 6pt;padding-left:15pt}li{margin:0 0 3pt}
.mute{color:%(MUTE)s}.small{font-size:8.5pt}a{color:%(INFO)s;text-decoration:none;word-break:break-all}
table{border-collapse:collapse;width:100%%;margin:4pt 0 10pt;font-size:9pt}th,td{text-align:left;padding:4pt 6pt;border-bottom:1px solid %(LINE)s;vertical-align:top}
th{font-weight:600;color:%(MUTE)s;font-size:8pt;text-transform:none}tr{break-inside:avoid}td.n{text-align:right;white-space:nowrap}
.plain{background:#eff6ff;border-left:4px solid %(INFO)s;border-radius:4pt;padding:9pt 12pt;margin:8pt 0 12pt;font-size:11pt}
.plain b.t{display:block;font-size:8pt;letter-spacing:.06em;color:%(INFO)s;margin-bottom:2pt}
.gap{background:#f0fdf4;border-left:4px solid %(GOOD)s;border-radius:4pt;padding:9pt 12pt;margin:8pt 0 12pt}
.worry{background:#fffbeb;border-left:4px solid %(CARE)s;border-radius:4pt;padding:9pt 12pt;margin:8pt 0 12pt}
.hero{border-radius:10pt;padding:16pt 18pt;margin:10pt 0 14pt;color:#fff}
.hero .lbl{font-size:9pt;letter-spacing:.08em;opacity:.85}.hero .ans{font-size:26pt;font-weight:800;line-height:1.1;margin:2pt 0 6pt}
.hero p{margin:0;font-size:11pt;opacity:.95}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8pt;margin:8pt 0 12pt}
.kpi{border:1px solid %(LINE)s;border-radius:8pt;padding:9pt 10pt;break-inside:avoid}.kpi .v{font-size:15pt;font-weight:800}
.kpi .l{font-size:9pt;font-weight:600;margin-top:1pt}.kpi .x{font-size:8pt;color:%(MUTE)s;margin-top:2pt;line-height:1.35}
.pill{display:inline-block;border-radius:99px;padding:0 7pt;font-size:8pt;font-weight:700;color:#fff;white-space:nowrap}
.score{display:grid;grid-template-columns:150pt 1fr 44pt;gap:8pt;align-items:center;padding:4pt 0;border-bottom:1px solid %(LINE)s;break-inside:avoid}
.score .q{font-weight:600;font-size:10pt}.score .why{font-size:8.5pt;color:%(MUTE)s;grid-column:1/4;margin-top:-3pt}
.bar{height:8pt;background:%(SOFT)s;border-radius:99px;overflow:hidden}.bar i{display:block;height:100%%;border-radius:99px}
.steps{counter-reset:s;list-style:none;padding:0}.steps li{counter-increment:s;padding-left:22pt;position:relative;margin-bottom:6pt}
.steps li:before{content:counter(s);position:absolute;left:0;top:0;width:15pt;height:15pt;border-radius:99px;background:%(INK)s;color:#fff;font-size:8pt;font-weight:700;text-align:center;line-height:15pt}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12pt}.two>div{break-inside:avoid}
.card{border:1px solid %(LINE)s;border-radius:8pt;padding:9pt 11pt;margin:0 0 8pt;break-inside:avoid}
.card h4{margin:0 0 3pt;font-size:10.5pt}
.tl{display:grid;grid-template-columns:repeat(6,1fr);gap:4pt;margin:6pt 0 12pt}.tl div{border-top:3px solid %(INK)s;padding-top:4pt;font-size:8.5pt}
.tl b{display:block;font-size:9pt}
pre{white-space:pre-wrap;font:8.5pt/1.45 Consolas,ui-monospace,monospace;margin:0}
.foot{font-size:8pt;color:%(MUTE)s;margin-top:14pt}
.herogrid{display:grid;grid-template-columns:96pt 1fr;gap:16pt;align-items:center}
.ring{width:92pt;height:92pt;border-radius:50%%;display:grid;place-items:center}
.ring>div{width:74pt;height:74pt;border-radius:50%%;display:flex;align-items:center;justify-content:center;color:#fff}
.ring b{font-size:26pt;line-height:1}.ring span{font-size:9pt;opacity:.85;margin-left:1pt}
.mini{display:grid;grid-template-columns:1fr 1fr;gap:4pt 18pt;margin:4pt 0 4pt}
.mini>div{display:grid;grid-template-columns:118pt 1fr 18pt;gap:6pt;align-items:center;font-size:9pt;break-inside:avoid}
.mini .bar{height:7pt;background:%(SOFT)s;border-radius:99px;overflow:hidden;display:block}.mini .bar i{display:block;height:100%%;border-radius:99px}
.mini b{text-align:right}
table.glance td{padding:5pt 6pt;font-size:9.5pt}table.glance td.t{font-weight:700;width:105pt;white-space:nowrap}
.divider{background:%(INK)s;color:#fff;border-radius:10pt;padding:16pt 18pt;margin-bottom:14pt}.divider .lbl{font-size:9pt;letter-spacing:.1em;opacity:.7}
.divider .big{font-size:18pt;font-weight:800}
""" % dict(INK=INK, MUTE=MUTE, LINE=LINE, SOFT=SOFT, GOOD=GOOD, CARE=CARE, BAD=BAD, INFO=INFO)

STEP_NAMES = {
    "01": "Is the idea clear?", "02": "Does anyone already pay for this?", "03": "Is the market alive?",
    "04": "Is it worth the effort?", "05": "Your decision #1", "06": "Brainstorm search words",
    "07": "How many people search?", "08": "What does Google show?", "09": "Pick the best keywords and rivals",
    "10": "How good are the rival websites?", "11": "What do rivals charge?", "12": "How big is the market?",
    "13": "How strong are the rivals, and does AI recommend them?", "14": "Your decision #2", "15": "Costs and safety rules",
    "16": "Does the money work?", "17": "The build plan", "18": "Your decision #3",
}

GLOSSARY = [
    ("CPC (cost per click)", "What advertisers pay Google each time someone clicks their ad. A high CPC means buyers for this are worth money."),
    ("KD (keyword difficulty, 0-100)", "How hard it is to get on Google's first page for a search. Under 20 is easy for a new site; over 50 is very hard."),
    ("DR (domain rating, 0-100)", "How strong a website is in Google's eyes, mostly from how many sites link to it. Under 30 is beatable."),
    ("SERP", "The Google results page for a search."),
    ("Cluster", "A group of searches that Google answers with the same pages. One cluster = one page to build."),
    ("Buying intent", "A search from someone ready to pay (\"passport photo online\"), not just curious (\"what size is a passport photo\")."),
    ("ICE score (1-10)", "Impact x Confidence x Ease, averaged. A quick gut-check of how worth it an idea is. 6+ is good."),
    ("MVP", "Minimum viable product: the simplest version people can pay for."),
    ("CAC (customer acquisition cost)", "What it costs to win one paying customer (ads, emails, time)."),
    ("Max CAC", "The most you can spend to win a customer and still not lose money."),
    ("Net per sale", "What you keep from one sale after data costs and payment fees."),
    ("Bottom-up market", "Estimate built from real search numbers: clicks the top sites get x a share who buy x price."),
    ("Top-down market", "Estimate built from the size of the whole industry. Always bigger; you will not get all of it."),
    ("E-E-A-T", "Experience, Expertise, Authority, Trust: what Google checks before it trusts a site with a topic."),
    ("YMYL", "\"Your money or your life\": topics like health, money or law where Google is extra strict."),
    ("Link target", "A website that links to your competitors and might link to you too. Links make your site stronger."),
    ("Gate", "A point where the machine stops and you decide: go on, change direction, or stop."),
    ("AI Overview", "The AI-written answer Google shows above the normal results for some searches. It quotes a few websites."),
    ("AI visibility", "Whether ChatGPT, Perplexity or Google's AI mention or quote your site when people ask them for help."),
    ("Indexed", "Google has stored your page and can show it. Pages that are not indexed get no Google visitors."),
    ("Worth in ads", "What a site's free Google visitors would cost if it had to buy them as ads. A quick way to see how valuable its Google traffic is."),
    ("People also ask", "The box of related questions Google shows for many searches. Great page and FAQ ideas."),
    ("Lighthouse speed score", "Google's 0-100 test of how fast a page loads on a phone. Under 50 is slow."),
]


def e(x):
    return html.escape(str(x if x is not None else ""))


def link(u, text=None):
    u = str(u or "")
    return '<a href="%s">%s</a>' % (e(u), e(text or u)) if u.startswith("http") else e(text or u)


def money(x):
    x = num(x)
    if x >= 1e9:
        return "$%.1fB" % (x / 1e9)
    if x >= 1e6:
        return "$%.1fM" % (x / 1e6)
    return "$%s" % format(round(x), ",") if x >= 100 else "$%.2f" % x


def pill(text, color):
    return '<span class=pill style="background:%s">%s</span>' % (color, e(text))


def kd_word(kd):
    if kd in ("", None):
        return pill("unknown", MUTE)
    k = num(kd)
    return pill("very easy", GOOD) if k <= 10 else pill("easy", GOOD) if k <= 30 else pill("medium", CARE) if k <= 50 else pill("hard", BAD)


def dr_word(dr):
    if dr in ("", None):
        return pill("unknown", MUTE)
    d = num(dr)
    return pill("weak", GOOD) if d < 20 else pill("beatable", GOOD) if d < 40 else pill("strong", CARE) if d < 60 else pill("very strong", BAD)


def table(rows, cols, heads=None, limit=None, raw=(), right=()):
    rows = rows[:limit] if limit else rows
    if not rows:
        return "<p class=mute>Nothing found.</p>"
    h = "<table><tr>" + "".join("<th>%s</th>" % e(c) for c in (heads or cols)) + "</tr>"
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            txt = str(v) if c in raw else e(v)
            cells.append(("<td class=n>%s</td>" if c in right else "<td>%s</td>") % txt)
        h += "<tr>" + "".join(cells) + "</tr>"
    return h + "</table>"


def bullets(xs, cls=""):
    xs = [x for x in (xs or []) if x]
    if not xs:
        return "<p class=mute>Nothing found.</p>"
    return "<ul%s>" % (' class="%s"' % cls if cls else "") + "".join(
        "<li>%s</li>" % (link(x) if str(x).startswith("http") else e(x)) for x in xs) + "</ul>"


def plain(text):
    return "<div class=plain><b class=t>IN PLAIN WORDS</b>%s</div>" % text


def first_sentence(t, n=220):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    m = re.match(r"(.+?[.;])(\s|$)", t)
    t = m.group(1) if m and len(m.group(1)) > 40 else t
    t = t.rstrip(";, ")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "..."


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


QUESTIONS = {
    "demand": "Do people search for it?", "value": "Are buyers worth money?", "market": "Is the market big enough?",
    "kd_dr": "Can a new site get onto Google?", "weak_spots": "Are the rivals weak anywhere?", "advantage": "Do we have an edge?",
    "costs": "Is it cheap to run?",
}


LEVELS = [
    ("Easy", GOOD, "1-3 months", "0-5 links"),
    ("Doable", GOOD, "3-6 months", "5-20 links"),
    ("Hard", CARE, "6-12 months", "20-50 links"),
    ("Very hard", BAD, "12+ months", "50+ links"),
]
LEVEL_MEANING = ["A good, useful page is usually enough.", "Good page plus a handful of links.",
                 "Needs real link building; start with easier searches first.", "Skip at the start; come back when the site is strong."]


def rank_level(cl):
    """How hard one search is to rank for, from 3 signals:
    1) keyword difficulty (KD, 0-100), 2) the weakest site already on page 1, 3) weak spots (forums, thin pages).
    Rule of thumb, not a promise."""
    kd = cl.get("kd")
    known = kd not in ("", None)
    k = num(kd, 35) if known else 35
    lvl = 0 if k <= 10 else 1 if k <= 30 else 2 if k <= 50 else 3
    drs = [num(o["dr"]) for o in cl.get("top10", []) if o.get("dr")]  # 0 = no data, not "weak"
    weakest = min(drs) if drs else None
    reasons = ["difficulty %s/100" % (int(k) if known else "unknown")]
    if weakest is not None:
        reasons.append("weakest site on page 1 has strength %d" % weakest)
    easier = (weakest is not None and weakest < 20) or any("forum" in w.lower() for w in cl.get("weak_spots", []))
    if easier and lvl > 0:
        lvl -= 1
        reasons.append("a weak site or a forum already ranks, so a better page can get in")
    if drs and min(drs) >= 60 and lvl < 3:
        lvl += 1
        reasons.append("every site on page 1 is strong (60+)")
    return lvl, reasons


def answer_of(v, data, n_done):
    st, rec = v["status"], data.get("gate3_recommendation") or ""
    if st == "killed":
        return "DON'T BUILD IT", BAD, "You stopped this idea. It stays in the archive so it is never suggested again."
    if st == "kill_recommended":
        return "STOP: A DEAL-BREAKER", BAD, "One of the checks found a problem big enough to stop. See 'Things to worry about'."
    if st == "alert":
        return "STUCK", CARE, "A step could not finish (for example the money cap was reached). See the step list at the back."
    if st == "approved_build":
        return "BUILD IT", GOOD, "You approved this idea for building."
    if st == "quick_test":
        return "TEST IT CHEAPLY FIRST", CARE, "You chose a small, capped test before building. The test plan is below."
    if rec.startswith("FULL"):
        return "LOOKS GOOD: BUILD IT", GOOD, "It scored %d out of 100 on the 7 checks that matter most." % round(num(data.get("gate3_score")) * 20)
    if rec.startswith("QUICK"):
        why = data.get("gate3_cap_note") or "Not clear enough to build; run a small capped test first."
        return "MAYBE: TEST IT CHEAPLY FIRST", CARE, "It scored %d out of 100. %s" % (round(num(data.get("gate3_score")) * 20), why)
    if rec.startswith("KILL"):
        return "DON'T BUILD IT", BAD, "It scored only %d out of 100 on the 7 checks that matter most." % round(num(data.get("gate3_score")) * 20)
    return "NOT FINISHED YET", "#52525b", "The machine has done %d of 18 steps so far. Run it again to continue." % n_done


def build_html(slug):
    from .blocks.gates import gate3_scores
    from .pipeline import Ctx
    v = store.venture(slug)
    d = S.ventures_dir / slug
    data = v["data"]

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
    costs, ue, plan = jf("15_costs.json"), jf("16_unit_economics.json"), jf("19_sitemap.json")
    n_done = sum(1 for b in bl.values() if b["status"] == "VALIDATED")
    decisions = store.gates(slug)
    H = []
    sec = [0]

    def section(title, sub=""):
        sec[0] += 1
        H.append("<div class=sec><span class=num>PART %d</span><h2>%s</h2>%s" % (sec[0], e(title), "<p class=mute>%s</p>" % e(sub) if sub else ""))

    def end():
        H.append("</div>")

    # ================= WORK OUT EVERYTHING FIRST =================
    ans, color, why = answer_of(v, data, n_done)
    # an override only counts while the step it overrode still carries it (re-running the step clears it)
    overridden = [g for g in decisions if g["decision"] == "override"
                  and any("OWNER OVERRIDE" in (bl.get(b_, {}).get("summary") or "") for b_ in g["gate"].split(","))]
    if color == GOOD and overridden:
        ans, color = "GOOD NUMBERS, BUT ONE CHECK SAID NO", CARE
        said = [first_sentence(re.sub(r"\s*\|\s*OWNER OVERRIDE:.*$", "", bl.get(b_, {}).get("summary") or ""), 160) for g in overridden for b_ in g["gate"].split(",")]
        why += " Step %s said stop (%s) and you chose to continue anyway." % (", ".join(sorted({g["gate"] for g in overridden})), "; ".join(said))
    buy = [k for k in (kws or []) if k["intent"] in ("buy", "competitor", "brand-model")]
    buy_vol = int(sum(num(k["volume"]) for k in buy))
    try:
        scores, avg = gate3_scores(Ctx(slug)) if comps and mk and seo_ and clusters else (None, None)
    except Exception:
        scores, avg = None, None
    score100 = int(round(avg / 5 * 100)) if avg else None
    aiv = jf("15_ai_visibility.json")
    uec = (ue or {}).get("chosen") or {}

    worries = ["Step %s (%s) said stop, and you chose to continue. Your reason: \"%s\"" % (g["gate"], STEP_NAMES.get(g["gate"], ""), g["note"]) for g in overridden]
    for bid in sorted(bl):
        st_ = bl[bid]
        if st_.get("verdict") not in ("warn", "kill") or bid in ("05", "14", "18"):
            continue
        summ = re.sub(r"\s*\|\s*OWNER OVERRIDE:.*$", "", st_.get("summary") or "")
        if bid == "04" and sc:
            w = "The quick gut-check score is only %s out of 10 (6 or more is good)." % sc["ice_avg"]
        elif bid == "12" and mk:
            w = "The careful market guess (%s a year) is only %.1f times your first-year goal; we want 10 times or more." % (money(mk["bottom_up_usd_year"]), mk["bottom_up_usd_year"] / max(mk["year1_goal_usd"], 1))
        elif bid == "16" and uec.get("paid_search_cac") and uec["paid_search_cac"] > uec.get("max_cac", 0):
            w = "Paid ads would lose money: one customer from Google ads costs about %s, but you keep only %s per sale. Use free channels (Google search results, email)." % (money(uec["paid_search_cac"]), money(uec["net_per_sale"]))
        else:
            w = "%s %s" % (STEP_NAMES.get(bid, bid) + ":", first_sentence(summ))
        worries.append(w)
    if sc and sc.get("risks"):
        worries += [first_sentence(r) for r in sc["risks"][:3]]

    st = v["status"]
    nxt = []
    if st.startswith("gate_"):
        g = {"gate_05": ("#1", "GO starts the paid keyword research (about $0.50-1.50). KILL archives the idea."),
             "gate_14": ("#2", "GO goes on to costs and the plan. PIVOT narrows the idea (one country, businesses only, a smaller group) and redoes the research. KILL archives it."),
             "gate_18": ("#3", "GO approves building it. TEST runs a small capped test first. KILL archives it.")}[st]
        nxt += ["Read the worries.", "Make decision %s in the app or with: vm gate %s go | kill%s" % (g[0], slug, " | pivot \"...\"" if st == "gate_14" else " | test" if st == "gate_18" else ""), g[1]]
        if st == "gate_18" and costs and costs.get("owner_questions"):
            nxt += ["Answer this first: " + first_sentence(q, 200) for q in costs["owner_questions"][:3]]
    elif st == "approved_build" and costs:
        nxt += ["%s (about %s min): %s" % (t["task"], t["minutes"], t["why"]) for t in costs["owner_todo"][:6]]
    elif st == "quick_test" and tf("20_quick_test.md"):
        nxt.append("Run the quick test described in 'The plan'. Stop the moment the kill line is hit.")
    elif st in ("kill_recommended", "alert"):
        nxt += ["Read the worries.", "Agree and stop: vm gate %s kill" % slug, "Or continue anyway with a reason: vm gate %s override \"why\"" % slug]
    elif st == "killed":
        nxt.append("Nothing. Try the next idea.")
    else:
        nxt.append("Run it again to continue: vm run %s" % slug)

    # one line per topic for the simple report: (topic, what we found, verdict word, colour)
    glance = []

    def verdict(ok, care):
        return ("good", GOOD) if ok else ("careful", CARE) if care else ("problem", BAD)
    if buy:
        top_cpc = max(num(k["cpc"]) for k in buy)
        glance.append(("Demand", "{:,} searches a month from people ready to buy".format(buy_vol), *verdict(buy_vol >= 1000, buy_vol >= 300)))
        glance.append(("Buyer value", "advertisers pay up to %s per click" % money(top_cpc), *verdict(top_cpc >= 2, top_cpc >= 1)))
    if pulse:
        ch = pulse.get("change_24m_pct_best")
        if pulse["status"] == "dying":
            txt = "interest is shrinking"
        elif ch is not None and ch < -10:
            txt = "searches are down %d%% in 2 years, but people still buy (ads, new sites, questions)" % abs(ch)
        elif ch is not None and ch > 10:
            txt = "searches are up %d%% in 2 years" % ch
        else:
            txt = "interest is steady"
        rt = (mk or {}).get("rivals_traffic_trend_12m_pct")
        if rt is not None:
            txt += "; the top rivals' Google visits are %s %d%% over 12 months" % ("up" if rt >= 0 else "down", abs(rt))
        good_trend = pulse["status"] == "alive" and ((ch is None or ch >= -10) or (rt is not None and rt > 5))
        glance.append(("Trend", txt, *verdict(good_trend, pulse["status"] != "dying")))
    if clusters:
        lv = [rank_level(cl)[0] for cl in clusters[:15]]
        ez = sum(1 for x in lv if x <= 1)
        glance.append(("Getting onto Google", "%d of the %d most valuable searches are Easy or Doable" % (ez, len(lv)), *verdict(ez >= len(lv) / 2, ez >= len(lv) / 4)))
    if aiv:
        g_ = aiv.get("google_ai_overview") or {}
        share = aiv.get("rival_share") or {}
        rec_ = aiv.get("ai_recommends") or []
        glance.append(("AI assistants", "Google answers %s of %s searches with its own AI (fewer clicks); ChatGPT/Perplexity recommend %s most"
                       % (g_.get("with_ai_answer", 0), g_.get("searches", 0), ", ".join(r["site"] for r in rec_[:2]) or "nobody"),
                       *verdict(g_.get("with_ai_answer", 0) <= g_.get("searches", 0) / 2, True)))
    if seo_:
        drs = [num(s_["dr"]) for s_ in seo_["competitors"] if s_.get("dr")]
        if drs:
            rtr = (mk or {}).get("rival_traffic") or {}
            top_r = max(rtr.items(), key=lambda kv: num(kv[1].get("visits")), default=(None, {}))
            extra = ("; biggest gets ~%s Google visits a month" % "{:,}".format(int(num(top_r[1].get("visits"))))) if top_r[0] else ""
            glance.append(("Rivals", "the weakest of the top 5 has strength %d/100%s%s" % (min(drs), extra, ("; gap: " + first_sentence(biz["identified_gap"], 100)) if biz else ""),
                           *verdict(min(drs) < 40, min(drs) < 60)))
    if mk:
        x_ = mk["bottom_up_usd_year"] / max(mk["year1_goal_usd"], 1)
        glance.append(("Market size", "careful guess %s a year, %.1fx your first-year goal" % (money(mk["bottom_up_usd_year"]), x_), *verdict(x_ >= 10, x_ >= 3)))
    if uec:
        ads_ok = uec.get("paid_search_cac") is not None and uec["paid_search_cac"] <= uec.get("max_cac", 0)
        glance.append(("Money", "you keep %s per sale; Google ads %s" % (money(uec["net_per_sale"]), "can pay off" if ads_ok else "would lose money"),
                       *verdict(uec["net_per_sale"] > 0 and ads_ok, uec["net_per_sale"] > 0)))
    fc = data.get("forecast_12m_usd") or {}
    if fc.get("mid") is not None:
        goal_ = S.year1_goal_usd
        glance.append(("First-year sales", "likely %s (bad case %s, good case %s); your goal is %s" % (money(fc.get("mid")), money(fc.get("low")), money(fc.get("high")), money(goal_)),
                       *verdict(fc["mid"] >= goal_, fc.get("high", 0) >= goal_)))
    if eeat:
        oks = sum(1 for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example") if eeat[k]["ok"])
        glance.append(("Google trust", "%d of 4 trust checks can be met by launch" % oks, *verdict(oks == 4, oks == 3)))
    if sc:
        fixed = (costs or {}).get("budget_caps", {}).get("fixed_cost_usd_month")
        glance.append(("Effort", "%s days to a first version%s" % (sc["effort"]["days_to_mvp"], ("; about %s a month to run" % money(fixed)) if fixed is not None else ""),
                       *verdict(sc["effort"]["days_to_mvp"] <= 14, sc["effort"]["days_to_mvp"] <= 30)))

    # ================= THE SIMPLE REPORT (page 1-2) =================
    H.append("<div class=mute style='font-size:8.5pt;letter-spacing:.08em'>THE VENTURE MACHINE &middot; FINDINGS REPORT &middot; %s</div>" % e(store.now()[:10]))
    H.append("<h1>%s</h1>" % e(v["one_liner"] or v["idea"]))
    H.append("<p class=mute>Checked for: %s &middot; Steps done: %d of 18 &middot; Data bought: %s</p>"
             % (e(v["country"].upper()), n_done, money(store.spent(slug))))
    ring = ("<div class=ring style='background:conic-gradient(#fff %d%%, rgba(255,255,255,.3) 0)'><div style='background:%s'><b>%d</b><span>/100</span></div></div>"
            % (score100, color, score100) if score100 is not None else
            "<div class=ring style='background:rgba(255,255,255,.3)'><div style='background:%s'><b>?</b><span>/100</span></div></div>" % color)
    H.append("<div class=hero style='background:%s'><div class=herogrid>%s<div><div class=lbl>THE ANSWER</div><div class=ans>%s</div><p>%s</p></div></div></div>"
             % (color, ring, e(ans), e(why)))
    if scores:
        H.append("<h3>The 7 scores (out of 10)</h3><div class=mini>" + "".join(
            "<div><span class=q>%s</span><span class=bar><i style='width:%d%%;background:%s'></i></span><b>%d</b></div>"
            % (e(QUESTIONS.get(k, k)), val * 20, GOOD if val >= 4 else CARE if val == 3 else BAD, val * 2) for k, (val, _w) in scores.items()) + "</div>"
            + "<p class='small mute'>Overall score = the average of the 7, out of 100. Under 60: don't build. 60-69: test it cheaply first. 70 or more: build, unless the likely first-year sales are below your goal (then: test first).</p>")
    if glance:
        H.append("<h3>Everything at a glance</h3><table class=glance>" + "".join(
            "<tr><td class=t>%s</td><td>%s</td><td class=n>%s</td></tr>" % (e(t), e(f), pill(w, c)) for t, f, w, c in glance) + "</table>")
    if sc:
        H.append("<h3>In three sentences</h3>" + bullets(sc["summary_3_lines"]))
    H.append("<div class=two><div><h3>Top worries</h3>%s</div><div><h3>What to do next</h3><ol class=steps>%s</ol></div></div>"
             % ("<div class=worry>%s</div>" % bullets(worries[:4]) if worries else "<p>Nothing serious was flagged.</p>",
                "".join("<li>%s</li>" % e(x) for x in nxt[:4])))
    H.append("<p class=foot>That is the whole story in short. Everything below is the detail and the proof: each part answers one plain question and "
             "starts with a blue \"in plain words\" box. Numbers come from Google data (via DataForSEO) or web pages the AI opened; sources are at the back, "
             "and words like CPC or KD are explained in the glossary.</p>")

    # ================= THE DETAILS =================
    H.append("<div class=sec><div class=divider><div class=lbl>THE DETAILS</div><div class=big>Everything we found, step by step</div></div>")
    section_open = True  # the first part shares the divider page

    # ================= PART 1: SCORECARD IN DETAIL =================
    sec[0] += 1
    H.append("<span class=num>PART 1</span><h2>The scorecard in detail</h2><p class=mute>The 7 things that decide if this idea is worth building, each out of 10.</p>")
    if scores:
        H.append(plain("Overall <b>%d out of 100</b>. Under 60 means don't build. 60 to 69 means run a cheap test first. 70 or more means build." % score100))
        for k, (val, why_) in scores.items():
            col = GOOD if val >= 4 else CARE if val == 3 else BAD
            H.append("<div class=score><div class=q>%s</div><div class=bar><i style='width:%d%%;background:%s'></i></div><div><b>%d</b>/10</div><div class=why>%s</div></div>"
                     % (e(QUESTIONS.get(k, k)), val * 20, col, val * 2, e(why_)))
    else:
        H.append(plain("The scores appear once all research steps are done (step 18). So far %d of 18 steps are done." % n_done))
    H.append("<h3>All the worries</h3>")
    H.append("<div class=worry>%s</div>" % bullets(worries) if worries else "<p>Nothing serious was flagged.</p>")
    H.append("<h3>All next steps</h3><ol class=steps>" + "".join("<li>%s</li>" % e(x) for x in nxt) + "</ol>")
    if section_open:
        end()

    # ================= PART 2: DEMAND =================
    if short or pulse:
        section("Is there demand?", "Do enough people search Google for this, and is that growing or shrinking?")
        if short:
            top = max(short, key=lambda r: num(r["volume"]))
            easy = sum(1 for r in short if r["kd"] != "" and num(r["kd"]) <= 20)
            H.append(plain("About <b>{:,}</b> searches a month come from people who look ready to buy. The biggest single search is "
                           "<b>\"{}\"</b> ({:,} a month). <b>{} of the {}</b> best searches are easy for a brand-new site to rank for."
                           .format(buy_vol, e(top["keyword"]), int(num(top["volume"])), easy, len(short))))
            rows = [{"kw": r["keyword"], "vol": "{:,}".format(int(num(r["volume"]))), "cpc": money(r["cpc"]), "kd": kd_word(r["kd"]),
                     "who": {"buy": "ready to buy", "competitor": "looking at a rival", "brand-model": "wants a specific thing", "info": "just learning"}.get(r["intent"], r["intent"])}
                    for r in sorted(short, key=lambda r: -num(r["score"]))[:15]]
            H.append("<h3>The best searches to go after</h3>" + table(rows, ["kw", "vol", "cpc", "kd", "who"],
                                                                      ["What people type into Google", "Searches a month", "Ad click price", "How hard to rank", "Who is searching"],
                                                                      raw=("kd",), right=("vol", "cpc")))
        if pulse:
            word = {"alive": ("alive", GOOD, "People still search for this and new sites keep appearing."),
                    "flat": ("flat", CARE, "Interest is not growing, but it is not dying either."),
                    "dying": ("dying", BAD, "Fewer people search for this every year.")}[pulse["status"]]
            H.append("<h3>Is it growing? %s</h3><p>%s</p>" % (pill(word[0], word[1]), e(word[2])))
            tr = [{"t": t, "c": ("%+.0f%%" % x["change_24m_pct"]) if x["change_24m_pct"] is not None else "not enough data"} for t, x in pulse.get("trend", {}).items()]
            H.append(table(tr, ["t", "c"], ["Search term", "Change over the last 2 years (Google Trends)"], right=("c",)))
            if pulse.get("rising_synonyms"):
                H.append("<p><b>Newer words people now use:</b> %s</p>" % e(", ".join(pulse["rising_synonyms"])))
        qs = jf("15_questions.json") or []
        if qs:
            H.append("<h3>Questions people ask Google</h3><p class=small>From the \"People also ask\" boxes on these searches. Each one is a ready-made FAQ or page idea.</p>"
                     + "<div class=two><div>%s</div><div>%s</div></div>" % (bullets([q["question"] for q in qs[:10]]), bullets([q["question"] for q in qs[10:20]])))
        end()

    # ================= RANK: HOW HARD + HOW TO =================
    if clusters:
        section("How hard is it to get onto Google, and how do you do it?",
                "How we judge difficulty, how hard each important search is, and the step-by-step way to rank.")
        H.append(plain("We look at <b>3 things</b> for every search: <b>1)</b> keyword difficulty, a 0-100 score of how many strong links the pages "
                       "on Google's first page have; <b>2)</b> how strong the <b>weakest</b> site on page 1 is (if a weak site is there, you can get in too); "
                       "<b>3)</b> weak spots, like forum posts or thin pages ranking, which show Google is short of good answers. "
                       "Together they give a rough time and how many websites need to link to you."))
        lv_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (pill(n, col), t, l, w)
                          for (n, col, t, l), w in zip(LEVELS, LEVEL_MEANING))
        H.append("<table><tr><th>Level</th><th>Time to page 1</th><th>Sites linking to you</th><th>What it means</th></tr>" + lv_rows
                 + "</table><p class='small mute'>Rule of thumb from how SEO usually goes for a new site, not a promise.</p>")
        ranked = [(rank_level(cl)[0], cl, rank_level(cl)[1]) for cl in clusters[:20]]
        rows = [{"s": cl["head"], "v": "{:,}".format(int(cl["volume"])), "lvl": pill(LEVELS[lvl][0], LEVELS[lvl][1]),
                 "t": LEVELS[lvl][2], "l": LEVELS[lvl][3], "w": "; ".join(why_)} for lvl, cl, why_ in ranked[:15]]
        H.append("<h3>Your most valuable searches, rated</h3>" + table(rows, ["s", "v", "lvl", "t", "l", "w"],
                 ["Search", "Searches a month", "How hard", "Time", "Links needed", "Why"], raw=("lvl",), right=("v",)))
        easy = [cl for lvl, cl, _ in sorted(ranked, key=lambda x: (x[0], -x[1]["volume"])) if lvl <= 1]
        n_links = len(links or [])
        aiv0 = jf("15_ai_visibility.json") or {}
        g0 = aiv0.get("google_ai_overview") or {}
        aio_n, aio_of = (g0.get("with_ai_answer", 0), g0.get("searches", 0)) if g0 else (sum(1 for cl in clusters if (cl.get("features") or {}).get("ai_overview")), len(clusters))
        steps = [
            "Start with the easy ones. Build these pages first: %s." % (", ".join('"%s"' % cl["head"] for cl in easy[:5]) or "the lowest-difficulty searches in the plan"),
            "One page per search topic, and make each one better than what ranks now: real data, a tool or a clear answer, not a copy of the others.",
            "Beat the forum posts: where Reddit or forums rank, people still have questions. Answer them fully on your page.",
            "Get links. %d sites already link to 2 or more of your rivals (appendix C). Ask them, starting with the strongest." % n_links,
            "Link your own pages to each other, and point the strongest pages at your money page.",
            "Go slowly with Google: about 10 pages in the first 1-2 months, then more. Bing can take more pages from the start.",
            "Check at 4-6 weeks: if fewer than half your pages are indexed, stop adding pages and improve or merge the weak ones.",
        ]
        if aio_n:
            steps.append("Google shows its own AI answer on %d of %d searches we checked. That takes clicks, so aim to be one of the sites that AI answer quotes (part on AI assistants)." % (aio_n, aio_of))
        gap = cf("15_keyword_gap.csv") or []
        if gap:
            rows = [{"k": g_["keyword"], "v": "{:,}".format(int(num(g_["volume"]))), "kd": kd_word(g_["kd"]), "r": "%s (#%s)" % (g_["best_rival"], g_["rival_rank"])} for g_ in gap[:15]]
            H.append("<h3>Searches your rivals already get that you had not planned</h3><p class=small>Real searches where a top rival is on page 1 or 2. Add the easy ones to your plan.</p>"
                     + table(rows, ["k", "v", "kd", "r"], ["Search", "Searches a month", "How hard", "Rival ranking (position)"], raw=("kd",), right=("v",)))
        H.append("<h3>How to rank: the plan</h3><ol class=steps>" + "".join("<li>%s</li>" % e(x) for x in steps) + "</ol>")
        end()

    # ================= PART 3: RIVALS =================
    if comps or how:
        section("Who are you up against?", "The sites that already sell this, what they charge, and where they are weak.")
        dr = {s["domain"]: s for s in (seo_ or {}).get("competitors", [])}
        uxd = {x["domain"]: x for x in (ux or {}).get("competitors", [])}
        plans = {x["domain"]: [p for p in x["plans"] if p["price"] and "unknown" not in p["price"].lower()] for x in (biz or {}).get("competitors", [])}
        if comps:
            drs = [num(dr[c["domain"]]["dr"]) for c in comps if c["domain"] in dr and dr[c["domain"]].get("dr") is not None]
            weakest = min(drs) if drs else None
            H.append(plain("These <b>%d sites</b> show up most often on Google for these searches. %s Below: what each one charges and where it is weak."
                           % (len(comps), ("The weakest has a strength of <b>%d out of 100</b>, which a new site can beat." % weakest) if weakest is not None and weakest < 40
                              else ("Even the weakest has a strength of <b>%d out of 100</b>, so getting onto Google will take time." % weakest) if weakest is not None else "")))
            for c in comps:
                s = dr.get(c["domain"], {})
                u = uxd.get(c["domain"], {})
                pr = ", ".join("%s %s" % (p["name"][:40], p["price"]) for p in plans.get(c["domain"], [])[:2]) or "price not found"
                H.append("<div class=card><h4>%s &nbsp;%s <span class=mute style='font-weight:400;font-size:8.5pt'>strength %s/100 &middot; %s sites link to it</span></h4>"
                         "<p class=small><b>Charges:</b> %s</p><div class=two><div><b class=small>Weak at</b>%s</div><div><b class=small>Good at</b>%s</div></div></div>"
                         % (e(c["domain"]), dr_word(s.get("dr", c.get("dr"))), e(s.get("dr", c.get("dr"))), e(s.get("referring_domains", "?")), e(pr),
                            bullets([first_sentence(w, 160) for w in (u.get("weaknesses") or [])[:3]]), bullets([first_sentence(w, 160) for w in (u.get("strengths") or [])[:2]])))
        rtr = (mk or {}).get("rival_traffic") or {}
        if comps and (rtr or ux):
            rows = []
            for c_ in comps:
                t_ = rtr.get(c_["domain"]) or {}
                u_ = uxd.get(c_["domain"], {})
                tr_ = t_.get("trend_12m_pct")
                age = u_.get("domain_created") or ""
                rows.append({"s": c_["domain"],
                             "v": "{:,}".format(int(num(t_.get("visits")))) if t_.get("visits") is not None else "?",
                             "a": money(t_.get("ads_value")) if t_.get("ads_value") is not None else "?",
                             "t": ("%+d%%" % tr_) if tr_ is not None else "-",
                             "y": ("%s (%d yrs)" % (age[:4], max(0, int(store.now()[:4]) - int(age[:4])))) if age[:4].isdigit() else "?",
                             "sp": ("%s/100" % u_["mobile_speed_score"]) if u_.get("mobile_speed_score") is not None else "?"})
            H.append("<h3>How big each rival is</h3>" + table(rows, ["s", "v", "a", "t", "y", "sp"],
                     ["Site", "Google visits a month", "Worth in ads a month*", "Visits, last 12 months", "Started (age)", "Phone speed"], right=("v", "a", "t")) +
                     "<p class='small mute'>* What those visitors would cost if bought as Google ads. Visits are DataForSEO estimates. Phone speed is Google's Lighthouse score; under 50 is slow, 90+ is fast.</p>")
            young = [r_ for r_ in rows if "(0 yrs)" in r_["y"] or "(1 yrs)" in r_["y"]]
            if young:
                H.append("<p><b>Good sign:</b> %s %s less than 2 years old and already on page 1, so new sites can get in.</p>"
                         % (e(", ".join(r_["s"] for r_ in young)), "is" if len(young) == 1 else "are"))
        if biz:
            H.append("<div class=gap><b>THE GAP YOU CAN OWN</b><br>%s</div>" % e(biz["identified_gap"]))
        if how:
            cp = [{"n": c["name"], "p": c["price"], "s": link(c["source_url"], "link")} for c in how["competitors"]]
            H.append("<h3>Others already charging for this</h3>" + table(cp, ["n", "p", "s"], ["Who", "What they charge", "Proof"], raw=("s",)))
        if biz and biz.get("audience_quotes"):
            H.append("<h3>What buyers say (real quotes)</h3><ul>" + "".join("<li>&ldquo;%s&rdquo; %s</li>" % (e(q["quote"]), link(q["url"], "source")) for q in biz["audience_quotes"][:8]) + "</ul>")
        end()

    # ================= AI: DO AI ASSISTANTS RECOMMEND YOU? =================
    aiv = jf("15_ai_visibility.json")
    if aiv:
        section("Do AI assistants recommend you?",
                "More people now ask ChatGPT, Perplexity or Google's AI instead of clicking links. Who do they recommend?")
        rec = aiv.get("ai_recommends") or []
        aio = aiv.get("google_ai_overview") or {}
        share = aiv.get("rival_share") or {}
        rivals_in = sum(1 for x in share.values() if x)
        first_q = (aiv.get("prompts") or [""])[0]
        H.append(plain("We asked ChatGPT and Perplexity <b>%d buyer questions</b> (like &ldquo;%s&rdquo;). They recommended <b>%s</b> most. "
                       "Of the %d sites that rank best on Google, <b>%d</b> got mentioned by the AI at all. Google showed its own AI answer on "
                       "<b>%s of %s</b> searches. <b>What this means:</b> ranking on Google is not enough any more; you also need to be one of the sites AI quotes."
                       % (len(aiv.get("prompts") or []), e(first_q), e(", ".join(r["site"] for r in rec[:3]) or "nobody in particular"),
                          len(share), rivals_in, aio.get("with_ai_answer", 0), aio.get("searches", 0))))
        t1 = table([{"s": r["site"], "n": r["times"]} for r in rec[:12]], ["s", "n"], ["Site", "Times quoted"], right=("n",))
        t2 = table([{"s": d_, "n": n_} for d_, n_ in sorted(share.items(), key=lambda x: -x[1])], ["s", "n"], ["Rival", "AI answers that mention it"], right=("n",))
        H.append("<div class=two><div><h3>Sites AI recommends</h3>%s</div><div><h3>Google's top rivals in AI answers</h3>%s</div></div>" % (t1, t2))
        trusted = (aiv.get("ai_trusted_sources") or {}).get("sources") or []
        cited = [t for t in (aio.get("cited_sites") or []) if t["site"] not in ("google.com", "www.google.com")]
        trusted = [t for t in trusted if t["site"] not in ("google.com", "www.google.com")]
        if trusted or cited:
            t3 = table([{"s": t["site"], "n": "{:,}".format(t["mentions"] or 0)} for t in trusted[:12]], ["s", "n"], ["Google AI cites most on this topic", "Times"], right=("n",))
            t4 = table([{"s": t["site"], "n": t["times"]} for t in cited[:12]], ["s", "n"], ["Quoted in AI answers on our searches", "Times"], right=("n",))
            H.append("<h3>Sources AI trusts</h3><p>Get mentioned on these (a listing, a review, a helpful answer, a video), because AI pulls its answers from them.</p>"
                     + "<div class=two><div>%s</div><div>%s</div></div>" % (t3, t4))
        tips = [
            "Be listed where AI looks: the 'best X' articles, Reddit threads, YouTube videos and review sites in the tables above.",
            "Put clear facts on your site: prices, specs, how it works, FAQs and a comparison with each rival, in plain text (not only images).",
            "Add an llms.txt file and clean structured data so AI tools can read your site easily.",
            "Get indexed by Bing as well as Google: ChatGPT's search leans on Bing.",
            "Collect real reviews (Trustpilot and similar). AI repeats what reviews say.",
            "Re-check every month: ask the same questions and see if you show up.",
        ]
        H.append("<h3>How to get into AI answers</h3><ol class=steps>" + "".join("<li>%s</li>" % e(x) for x in tips) + "</ol>")
        with_text = [a for a in aiv.get("answers") or [] if a.get("text")]
        if with_text:
            a = with_text[0]
            clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", a["text"])
            clean = re.sub(r"[*#]+", "", clean)
            H.append("<h3>Example: what %s said</h3><div class=card><p class=small><b>Question:</b> %s</p><p class=small>%s</p></div>"
                     % ("ChatGPT" if a["engine"] == "chatgpt" else "Perplexity", e(a["prompt"]), e(clean[:900] + ("..." if len(clean) > 900 else ""))))
        end()

    # ================= PART 4: MARKET =================
    if mk:
        section("How big is the money?", "Two different ways to guess how much money is in this market.")
        goal = mk["year1_goal_usd"]
        x = mk["bottom_up_usd_year"] / max(goal, 1)
        H.append(plain("<b>Careful guess: %s a year.</b> That is roughly what the top sites can earn from these Google searches if about 1 in 100 visitors buys. "
                       "<b>Big-picture guess: %s a year</b> for the whole industry; you will only ever get a small slice of that. "
                       "Your first-year goal is %s, and the careful guess is <b>%.1f times</b> that (we want at least 10 times)."
                       % (money(mk["bottom_up_usd_year"]), money(mk["top_down_usd_year"]), money(goal), x)))
        H.append("<div class=two><div class=card><h4>How the careful guess works</h4><p class=small>%s</p></div><div class=card><h4>How the big-picture guess works</h4><p class=small>%s</p></div></div>"
                 % (e(mk["bottom_up_method"]), e(first_sentence(mk["top_down_method"], 400))))
        rows = [{"c": k.upper(), "s": ("{:,}".format(val) if isinstance(val, int) else val)} for k, val in mk.get("search_volume_by_country", {}).items()]
        H.append("<h3>Where people search for it</h3>" + table(sorted(rows, key=lambda r: -num(str(r["s"]).replace(",", ""))), ["c", "s"], ["Country", "Searches a month (main words)"], right=("s",)))
        hist = mk.get("rival_traffic_history") or {}
        if hist:
            rt = mk.get("rivals_traffic_trend_12m_pct")
            H.append("<h3>Are the rivals growing?</h3><p>%s</p>" % (
                ("The biggest rivals' Google visits went <b>%s %d%%</b> over the last 12 months (average of the top %d). %s"
                 % ("up" if rt >= 0 else "down", abs(rt), len(hist), "A growing market." if rt > 5 else "A flat market." if rt > -5 else "A shrinking market."))
                if rt is not None else "Not enough history to tell."))
            months = sorted({r_["month"] for h_ in hist.values() for r_ in h_})[-12:]
            rows = [dict({"site": dom}, **{m_: "{:,}".format(next((r_["visits"] for r_ in h_ if r_["month"] == m_), 0)) for m_ in months[::3]}) for dom, h_ in hist.items()]
            H.append(table(rows, ["site"] + months[::3], ["Site"] + ["Visits %s" % m_ for m_ in months[::3]], right=tuple(months[::3])))
        if mk.get("underserved_countries_or_segments"):
            H.append("<h3>Groups nobody serves well yet</h3>" + bullets([first_sentence(u, 260) for u in mk["underserved_countries_or_segments"]]))
        if mk.get("segments"):
            H.append("<h3>Who buys</h3>" + "".join("<div class=card><h4>%s %s</h4><p class=small>%s</p></div>" % (e(s["name"]), pill("underserved", GOOD) if s["underserved"] else "", e(s["size_note"])) for s in mk["segments"]))
        end()

    # ================= PART 5: MONEY =================
    if ue:
        section("Will it make money?", "What you keep from each sale, and how much you can spend to win a customer.")
        c = ue["chosen"]
        ads_ok = c["paid_search_cac"] is not None and c["paid_search_cac"] <= c["max_cac"]
        H.append(plain("Sell <b>%s</b> for <b>%s</b>. After costs and fees you keep <b>%s</b> per sale. You can spend up to <b>%s</b> to win one customer and still break even. "
                       "Google ads would cost about <b>%s</b> per customer, so ads %s."
                       % (e(c["model"]), money(c["price_usd"]), money(c["net_per_sale"]), money(c["max_cac"]), money(c["paid_search_cac"]),
                          "<b>can work</b>" if ads_ok else "<b>would lose money</b>: get customers from Google search results (free) and email instead")))
        rows = [{"m": o["model"], "p": money(o["price_usd"]), "k": money(o["net_per_sale"]), "c": money(o["max_cac"]), "h": money(o["profit_per_hour_at_1000_visits"])} for o in ue["options"]]
        H.append("<h3>The ways to charge that were compared</h3>" + table(rows, ["m", "p", "k", "c", "h"],
                                                                         ["How you charge", "Price", "You keep per sale", "Max to spend per customer", "Profit per hour of your time*"],
                                                                         right=("p", "k", "c", "h")) + "<p class=small mute>* at 1,000 visitors a month, after fixed costs. The best one was picked.</p>")
        if costs:
            H.append("<p><b>Running costs:</b> about %s a month at the start, %s a month at 10 times the size.</p>"
                     % (money(costs["budget_caps"]["fixed_cost_usd_month"]), money(costs["budget_caps"]["fixed_cost_10x_usd_month"])))
        H.append("<h3>Goals and dates to aim for</h3><div class=tl>" + "".join("<div><b>%s</b>%s</div>" % (e(g["goal"]), e(g["by"])) for g in ue["ladder"]) + "</div>")
        end()

    # ================= PART 6: TRUST + FOR/AGAINST =================
    if eeat or sc:
        section("Can it work at all?", "Will Google trust the site, and the honest arguments for and against.")
        if eeat:
            names = {"real_person_or_company": "A real person or company behind it", "expertise_proof": "Proof you know the topic",
                     "unique_data_per_page": "Something unique on every page", "contacts_policies_real_example": "Contact details, policies, a real example"}
            oks = sum(1 for k in names if eeat[k]["ok"])
            H.append(plain("Google only shows sites it trusts. <b>%d of 4</b> trust checks can be met by launch. Risk level for this topic: <b>%s</b>." % (oks, e(eeat["ymyl_level"]))))
            rows = [{"c": names[k], "ok": pill("yes", GOOD) if eeat[k]["ok"] else pill("no", BAD), "a": first_sentence(eeat[k]["answer"], 260)} for k in names]
            H.append(table(rows, ["c", "ok", "a"], ["Trust check", "Can we?", "Why"], raw=("ok",)))
            if eeat.get("ymyl_banned_claims"):
                H.append("<h3>Never say this on the site</h3>" + bullets(eeat["ymyl_banned_claims"]))
        if sc:
            H.append("<h3>For and against</h3><div class=two><div class=card><h4 style='color:%s'>For</h4>%s</div><div class=card><h4 style='color:%s'>Against</h4>%s</div></div>"
                     % (GOOD, bullets(sc["pros"]), BAD, bullets(sc["cons"])))
            H.append("<div class=worry><b>The biggest unknown:</b> %s</div>" % e(sc["biggest_unknown"]))
        end()

    # ================= PART 7: THE PLAN =================
    bp = tf("19_business_plan.md")
    if plan or costs or tf("20_quick_test.md"):
        section("The plan", "What to build first, what to do by hand, and the rules to follow.")
        if bp:
            m = re.search(r"\*\*Why us \(5 seconds\):\*\*\s*(.+)", bp)
            if m:
                H.append(plain("<b>Why customers would pick you:</b> %s" % e(m.group(1).strip())))
            prod = re.search(r"## Product line\n(.*?)\n\n##", bp, re.S)
            if prod:
                H.append("<h3>What to sell</h3>" + md(prod.group(1)))
            fc = re.search(r"Low \$([\d,]+) \| Mid \$([\d,]+) \| High \$([\d,]+)", bp)
            if fc:
                H.append("<p><b>First-year sales forecast:</b> bad case $%s &middot; likely $%s &middot; good case $%s</p>" % fc.groups())
        if plan:
            rows = [{"p": p["title"], "t": p["page_type"], "s": "{:,}".format(int(num(p.get("volume")))), "kd": kd_word(p.get("kd")), "u": first_sentence(p["unique_data_source"], 140)}
                    for p in plan["pages"][:12]]
            H.append("<h3>The first pages to build (%d planned)</h3>" % len(plan["pages"]) +
                     table(rows, ["p", "t", "s", "kd", "u"], ["Page", "Type", "Searches a month", "How hard", "What makes it unique"], raw=("kd",), right=("s",)))
        if costs:
            H.append("<h3>Do these by hand before building</h3>" + table(costs["owner_todo"], ["task", "minutes"], ["Task", "Minutes"], right=("minutes",)))
            H.append("<h3>Rules for this business</h3>" + bullets(costs["guardrails"][:10]))
        if (t := tf("20_quick_test.md")):
            H.append("<h3>The quick test</h3>" + md(t))
        end()

    # ================= APPENDIX =================
    H.append("<div class=sec><span class=num>APPENDIX</span><h2>The details</h2><p class=mute>For checking the work. You can skip this.</p>")
    rows = []
    for bid in sorted(bl):
        st = bl[bid]
        vd = st.get("verdict") or st["status"].lower()
        word = {"pass": pill("good", GOOD), "warn": pill("careful", CARE), "kill": pill("problem", BAD), "redo": pill("problem", BAD)}.get(vd, pill(vd, MUTE))
        rows.append({"n": bid, "q": STEP_NAMES.get(bid, bid), "r": word, "f": first_sentence(st.get("summary") or st.get("error"), 300)})
    H.append("<h3>A. Every step and what it found</h3>" + table(rows, ["n", "q", "r", "f"], ["#", "Step", "Result", "What it found"], raw=("r",)))
    if clusters:
        rows = [{"h": c["head"], "v": "{:,}".format(int(c["volume"])), "k": kd_word(c.get("kd")), "n": len(c["keywords"]), "w": "; ".join(c["weak_spots"]) or "-"} for c in clusters[:30]]
        H.append("<h3>B. Page topics (each one = one page)</h3>" + table(rows, ["h", "v", "k", "n", "w"], ["Main search", "Searches a month", "How hard", "Searches covered", "Rivals' weak spots"], raw=("k",), right=("v", "n")))
    if links:
        rows = [{"d": l["domain"], "s": l["dr"], "n": l["links_to_n"]} for l in links[:30]]
        H.append("<h3>C. Sites to ask for a link (%d found)</h3><p class=small>They already link to 2 or more rivals, so they are likely to link to you.</p>" % len(links) +
                 table(rows, ["d", "s", "n"], ["Site", "Strength (0-100)", "Links to how many rivals"], right=("s", "n")))
    if (cal := cf("19_seo_calendar_90d.csv")):
        H.append("<h3>D. 90-day calendar</h3>" + table(cal, ["week", "type", "item", "keyword"], ["Week", "What", "Item", "Search"], limit=60))
    if (t := tf("18_swot.md")):
        H.append("<h3>E. Strengths, weaknesses, opportunities, threats</h3>" + md(t))
    if decisions:
        H.append("<h3>F. Your decisions</h3>" + table(decisions, ["ts", "gate", "decision", "note"], ["When", "Step", "Decision", "Note"]))
    H.append("<h3>G. Glossary</h3>" + table([{"t": a, "m": b} for a, b in GLOSSARY], ["t", "m"], ["Word", "What it means"]))
    acc = {}
    for name in ("02_how_analysis.json", "04_niche_pulse.json", "13_competitor_business.json", "14_market_analysis.json"):
        if (x := jf(name)):
            urls_in(x, acc)
    led = store.ledger(slug)
    paid = sum(r["usd"] for r in led if r["provider"] == "dataforseo")
    H.append("<h3>H. Sources</h3><ol class=small>" + "".join("<li>%s</li>" % link(u) for u in list(acc)[:200]) + "</ol>")
    H.append("<p class=small>Money spent on data for this idea: <b>%s</b> (DataForSEO %s, %d calls, %d free from cache). Limit: %s per idea.</p></div>"
             % (money(store.spent(slug)), money(paid), len(led), sum(r["cached"] for r in led), money(S.max_usd_per_idea)))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><title>%s findings</title><style>%s</style></head><body>%s</body></html>"
            % (e(slug), CSS, "".join(H)))


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

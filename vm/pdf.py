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
.stages{display:flex;gap:8pt;margin:8pt 0 2pt}.stages>div{flex:1;border:1px solid #e4e4e7;border-radius:8pt;padding:7pt 10pt}
.stages span{display:block;font-size:8pt;letter-spacing:.06em;text-transform:uppercase;color:#71717a}.stages b{font-size:15pt}
.stages i{display:block;font-style:normal;font-size:8.5pt;color:#71717a}.stages .off b{color:#a1a1aa}
.angle{border:1.5px solid #16a34a;background:#f0fdf4;border-radius:8pt;padding:9pt 12pt;margin:8pt 0}.angle .lbl{font-size:8pt;letter-spacing:.08em;color:#15803d;font-weight:700}
.angle p{margin:3pt 0}
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
    ("First-look score", "The phase 1 score: how big the win could be and how sure we are, each out of 10, averaged and shown out of 100. 60+ is good. How long it takes to build is shown but does not count."),
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
    return "$%s" % format(round(x), ",") if x >= 10 else "$%.2f" % x


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
            if "google.com/goto" not in u and not re.search(r"oauth2\.|googleapis\.com|/token\b|api\.dataforseo|`", u):
                acc.setdefault(u.rstrip(".,;`"), None)


QUESTIONS = {
    "demand": "Are there enough buyers?", "value": "Are buyers worth money?", "market": "Is the market big enough?",
    "kd_dr": "Can a new site get onto Google?", "weak_spots": "Are the rivals weak anywhere?", "advantage": "Do we have an edge?", "proof": "Do real businesses earn here?",
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
    if cl.get("intent") == "brand":
        return 2, ["this is a rival's own name: that rival holds the top spot, so only a comparison page can rank under it (difficulty %s/100 says little here)" % (kd if kd not in ("", None) else "unknown")]
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
    if st == "light_done":
        q, sc_ = data.get("quick_recommendation") or "", data.get("quick_score100")
        if q.startswith("WORTH"):
            return "WORTH A FULL CHECK", GOOD, "Quick check score %s out of 100. The basics look good; a full check will look at rivals, AI, market and money." % sc_
        if q.startswith("MAYBE"):
            return "MAYBE: FULL CHECK IF YOU LIKE IT", CARE, "Quick check score %s out of 100. Some basics are weak; only dig deeper if you really like the idea." % sc_
        return "SKIP IT", BAD, "Quick check score %s out of 100. The basics are weak." % sc_
    fs = data.get("first_score100")
    if st == "gate_05" and fs is not None:
        if fs >= 60:
            return "GOOD FIRST LOOK: RESEARCH IT", GOOD, "First-look score %d out of 100. Good enough to spend on real keyword research. The main score comes after that research." % fs
        if (data.get("other_angle") or {}).get("idea"):
            return "WEAK AS IT IS: TRY THE OTHER ANGLE", CARE, "First-look score %d out of 100 (60 or more is good). The idea as written is weak, but another angle could work. See the green box." % fs
        return "WEAK: PROBABLY SKIP IT", BAD, "First-look score %d out of 100 (60 or more is good), and no better angle was found." % fs
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
        return "LOOKS GOOD: BUILD IT", GOOD, "It scored %d out of 100 on the checks that matter most." % round(num(data.get("gate3_score")) * 20)
    if rec.startswith("QUICK"):
        why = re.sub(r"^Capped at TEST:\s*", "", data.get("gate3_cap_note") or "Not clear enough to build; run a small capped test first.")
        why = why[:1].upper() + why[1:]
        s100 = round(num(data.get("gate3_score")) * 20)
        if s100 >= 70:
            return "STRONG IDEA: PROVE IT WITH A SMALL TEST", GOOD, "It scored %d out of 100, which is in the build range. One thing holds it at a test first. %s" % (s100, why)
        return "MAYBE: TEST IT CHEAPLY FIRST", CARE, "It scored %d out of 100. %s" % (s100, why)
    if rec.startswith("KILL"):
        if (data.get("gate3_cap_note") or "").startswith("Knock-out"):
            return "DON'T BUILD IT", BAD, "It scored %d out of 100, but one rule decides on its own. %s" % (round(num(data.get("gate3_score")) * 20), data["gate3_cap_note"])
        return "DON'T BUILD IT", BAD, "It scored only %d out of 100 on the checks that matter most." % round(num(data.get("gate3_score")) * 20)
    if fs is not None:
        return "NOT FINISHED YET", "#52525b", "First-look score %d out of 100. The machine has done %d of 18 steps; the main score comes when the research is done." % (fs, n_done)
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
    from .util import buy_volume, is_buy, volume_split
    buy = [k for k in (kws or []) if is_buy(k)]
    buy_vol = int(buy_volume(kws or []))
    split = volume_split(kws or [])
    dropped_kw = cf("08_keywords_dropped.csv") or []
    depth = data.get("depth", "full")
    quick = depth == "light"
    QMAP = QUESTIONS
    try:
        if quick:
            from .blocks.gates import light_scores, LIGHT_QUESTIONS
            scores, avg = light_scores(Ctx(slug)) if kws else (None, None)
            QMAP = LIGHT_QUESTIONS
        else:
            main_ready = comps and mk and seo_ and clusters and bl.get("17", {}).get("status") == "VALIDATED"
            scores, avg = gate3_scores(Ctx(slug)) if main_ready else (None, None)
    except Exception:
        scores, avg = None, None
    first = False  # True = only the first-look (phase 1) score exists so far
    if not scores and not quick and sc:
        from .blocks.gates import first_scores, first_questions
        scores, avg = first_scores(Ctx(slug))
        QMAP, first = first_questions(), bool(scores)
    angle = data.get("other_angle") if (data.get("other_angle") or {}).get("idea") else None
    kid = None
    first100 = data.get("first_score100")
    score100 = int(round(avg / 5 * 100)) if avg else None
    aiv = jf("15_ai_visibility.json")
    uec = (ue or {}).get("chosen") or {}
    mk_up = ((mk or {}).get("bottom_up_at_chosen_price_usd_year") or (mk or {}).get("bottom_up_usd_year") or 0)

    from . import pipeline as _pl
    old_steps = _pl.stale(slug)
    problems_ = data.get("consistency_problems") or []
    offer = data.get("offer") or {}
    spin = data.get("spin_off") or {}
    worries = ["Step %s (%s) said stop, and you chose to continue. Your reason: \"%s\"" % (g["gate"], STEP_NAMES.get(g["gate"], ""), g["note"]) for g in overridden]
    went_against = [g for g in decisions if (g.get("note") or "").startswith("OVERRIDE:")]
    if went_against:
        worries.append("You continued past decision %s although some checks were weak. Those checks are in this list." % " and ".join(sorted({{"05": "1", "14": "2", "18": "3"}.get(g["gate"], g["gate"]) for g in went_against})))
    main_done = bool(scores) and not first and not quick
    for bid in sorted(bl):
        st_ = bl[bid]
        if st_.get("verdict") not in ("warn", "fail", "kill") or bid in ("05", "14", "18"):
            continue
        summ = re.sub(r"\s*\|\s*OWNER OVERRIDE:.*$", "", st_.get("summary") or "")
        if bid == "04" and sc and main_done:
            continue  # the main score has replaced the first look; it stays in the scorecard part as history
        elif bid == "04" and sc:
            w = "The first-look score is only %d out of 100 (60 or more is good)." % round(sc["ice_avg"] * 10)
        elif bid == "12" and mk:
            w = "Google search alone reaches about %s a month; the target is %s a month or more%s." % (
                money(round(mk_up / 12)), money(S.target_market_month), ", so the rest has to come from other channels (groups, email, partners)" if data.get("people_newcomer_month") else "")
        elif bid == "09" and re.search(r"(\d+) buying clusters in top 20", summ):
            w = "Only %s of the 20 best search topics come from people ready to buy; the rest are people still reading up." % re.search(r"(\d+) buying clusters in top 20", summ).group(1)
        elif bid == "13" and re.search(r"^0 good link targets", summ):
            w = "No good sites to get links from were found%s. Links will have to be earned another way (free tools, state pages others cite)." % (
                (" (%s were checked and rejected)" % re.search(r"(\d+) rejected", summ).group(1)) if re.search(r"(\d+) rejected", summ) else "")
        elif bid == "16" and uec.get("paid_search_cac") and uec["paid_search_cac"] > uec.get("max_cac", 0):
            w = "Paid ads would lose money: one customer from Google ads costs about %s, but you keep only %s per sale. Use free channels (Google search results, email)." % (money(uec["paid_search_cac"]), money(uec["net_per_sale"]))
        else:
            w = "%s %s" % (STEP_NAMES.get(bid, bid) + ":", first_sentence(summ))
        worries.append(w)
    if data.get("gate3_cap_note") and main_done and not (data.get("gate3_recommendation") or "").startswith("QUICK"):
        worries.insert(0, data["gate3_cap_note"])   # for a test verdict the same words already stand in the answer box
    if dropped_kw:
        worries.append("%d searches were thrown out because Google shows something else for them (for example \"%s\": %s)."
                       % (len(dropped_kw), dropped_kw[0]["keyword"], first_sentence(dropped_kw[0]["reason"], 120)))
    if sc and sc.get("risks"):
        worries += [first_sentence(r) for r in sc["risks"][:3]]

    worries = list(dict.fromkeys(worries))   # the same worry never twice
    st = v["status"]
    nxt = []
    if st.startswith("gate_"):
        g = {"gate_05": ("#1", "GO starts the paid keyword research (about $0.50-1.50). KILL archives the idea."),
             "gate_14": ("#2", "GO goes on to costs and the plan. PIVOT narrows the idea (one country, businesses only, a smaller group) and redoes the research. KILL archives it."),
             "gate_18": ("#3", "GO approves building it. TEST runs a small capped test first. KILL archives it.")}[st]
        kid = store.venture(data["angle_slug"]) if data.get("angle_slug") else None
        if st == "gate_05" and kid and (first100 or 100) < 60:
            ks = kid["data"].get("first_score100")
            nxt += [("The other angle was tested as its own idea (%s): it scored %d out of 100 on its first look. Read its report next." % (kid["slug"], ks)) if ks is not None
                    else "The other angle is saved as its own idea (%s). Run it: vm run %s" % (kid["slug"], kid["slug"]),
                    "Stop this version: vm gate %s kill (it stays archived so it is never suggested again)." % slug,
                    "Still believe in the idea as written? vm gate %s go starts the paid keyword research (about $0.50-1.50)." % slug]
        elif st == "gate_05" and angle and (first100 or 100) < 60:
            nxt += ["Test the other angle (about 1 cent, a few minutes): press 'Test the other angle' in the app, or: vm gate %s angle" % slug,
                    "Or stop here: vm gate %s kill (it stays archived so it is never suggested again)." % slug,
                    "Still believe in the idea as written? vm gate %s go starts the paid keyword research (about $0.50-1.50)." % slug]
        else:
            nxt += ["Read the worries.", "Make decision %s in the app or with: vm gate %s go | kill%s" % (g[0], slug, " | pivot \"...\"" if st == "gate_14" else " | test" if st == "gate_18" else ""), g[1]]
            if st == "gate_05" and angle:
                nxt.append("There is also another angle you can test for about 1 cent: vm gate %s angle" % slug)
        if st == "gate_18" and costs and costs.get("owner_questions"):
            nxt += ["Answer this first: " + first_sentence(q, 200) for q in costs["owner_questions"][:3]]
    elif st == "approved_build" and costs:
        nxt += ["%s (about %s min): %s" % (t["task"], t["minutes"], t["why"]) for t in costs["owner_todo"][:6]]
    elif st == "quick_test" and tf("20_quick_test.md"):
        nxt.append("Run the quick test described in 'The plan'. Stop the moment the kill line is hit.")
    elif st == "light_done":
        if angle and num(data.get("quick_score100"), 100) < 55:
            nxt.append("Weak as written, but another angle could work. Test it (about 20 cents): vm gate %s angle" % slug)
        nxt += ["If the quick score is good, run the full check: vm deepen %s full (about $2-3 more), or in the app press 'Run full check'." % slug,
                "Want everything bigger (more searches, countries, AI questions)? vm deepen %s deep (about $4-7)." % slug,
                "Not convinced? vm gate %s kill (it stays archived so it is never suggested again)." % slug]
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
    pr0 = jf("02_proof.json") or {}
    bc0, pp0 = pr0.get("buyer_count") or {}, pr0.get("people") or {}
    if bc0.get("figure"):
        n0 = num(bc0["figure"])
        glance.append(("Buyers counted", "{:,} people a year face this need ({}){}".format(int(n0), (bc0.get("source_name") or "source in the report")[:70],
                       "" if bc0.get("official") else "; not an official figure"), *verdict(n0 >= 5000, n0 >= 1000)))
    if buy:
        top_cpc = max(num(k["cpc"]) for k in buy)
        glance.append(("Search demand", "{:,} buying searches a month ({:,} commercial + 10% of {:,} for a rival's name)".format(buy_vol, split["commercial"], split["brand"])
                       if split["brand"] else "{:,} searches a month from people ready to buy".format(buy_vol), *verdict(buy_vol >= 1000, buy_vol >= 300)))
        from .util import weighted_cpc
        wc_ = weighted_cpc(kws or [])
        glance.append(("Ad click price", "advertisers pay about %s per click on average across the buying searches (highest single one %s)" % (money(wc_), money(top_cpc)), *verdict(wc_ >= 2, wc_ >= 1)))
    if pp0.get("price_usd"):
        glance.append(("What a buyer pays", "one customer pays the leading rival about %s" % money(pp0["price_usd"]), *verdict(pp0["price_usd"] >= 150, pp0["price_usd"] >= 50)))
    pr_ = jf("02_proof.json")
    if pr_ and pr_.get("checked"):
        from . import proof as _proof
        best30 = _proof.best_revenue(pr_)
        same_ = any(x_.get("closeness") == 3 and x_.get("revenue_30d_usd") == best30 for x_ in pr_.get("comparables") or [])
        glance.append(("Proven revenue", (("a real business in this niche made %s in the last 30 days (payment-verified)" if same_ else
                                           "a business selling the same kind of product in a neighbouring niche made %s in the last 30 days (payment-verified); none found in this exact niche") % money(best30)) if best30
                       else "no business with verified revenue found in this niche", *verdict(best30 >= S.proof_min_usd, best30 >= 1000)))
    if how and not biz:
        priced = [x_ for x_ in how.get("competitors", []) if x_.get("price") and "unknown" not in x_["price"].lower()]
        free_ = sum(1 for x_ in priced if "free" in x_["price"].lower())
        glance.append(("People already pay", "%d sites already sell this%s" % (len(priced), ("; %d of them also give a lot away free" % free_) if free_ else ""),
                       *verdict(len(priced) >= 3 and free_ < len(priced) / 2, len(priced) >= 1)))
    if pulse:
        ch = pulse.get("change_24m_pct_best")
        kwt = pulse.get("kw_trend_12m_pct")
        if pulse["status"] == "unknown" or (ch is None and kwt is None):
            txt = "not enough data to tell if interest is growing or shrinking"
        elif ch is None and kwt is not None:
            txt = "our own keywords' searches are %s %d%% in 12 months (source: Google Ads monthly search numbers; Google Trends had no data)" % ("up" if kwt >= 0 else "down", abs(kwt))
        elif pulse["status"] == "dying":
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
        known = ch is not None or kwt is not None
        up = (ch is not None and ch >= -10) or (ch is None and kwt is not None and kwt >= -10)
        shrinking_rivals = rt is not None and rt < -30
        good_trend = pulse["status"] == "alive" and known and up and not shrinking_rivals
        glance.append(("Trend", txt, *verdict(good_trend, pulse["status"] != "dying")))
    if clusters:
        lv = [rank_level(cl)[0] for cl in clusters if cl.get("intent") != "brand"][:15]
        ez = sum(1 for x in lv if x <= 1)
        glance.append(("Getting onto Google", "%d of the %d most valuable searches are Easy or Doable (searches for a rival's name are left out)" % (ez, len(lv)), *verdict(ez >= len(lv) / 2, ez >= len(lv) / 4)))
    if aiv:
        g_ = aiv.get("google_ai_overview") or {}
        share = aiv.get("rival_share") or {}
        rec_ = aiv.get("ai_recommends") or []
        glance.append(("AI assistants", "Google answers %s of %s searches with its own AI (fewer clicks); ChatGPT/Perplexity recommend %s most"
                       % (g_.get("with_ai_answer", 0), g_.get("searches", 0), ", ".join(r["site"] for r in rec_[:2]) or "nobody"),
                       *verdict(g_.get("with_ai_answer", 0) <= g_.get("searches", 0) / 2, True)))
    if seo_:
        drs = [num(s_["dr"]) for s_ in seo_["competitors"] if s_.get("dr") and s_.get("kind", "direct") == "direct"]
        if drs:
            rtr = (mk or {}).get("rival_traffic") or {}
            top_r = max(rtr.items(), key=lambda kv: num(kv[1].get("visits")), default=(None, {}))
            extra = ("; biggest gets ~%s Google visits a month" % "{:,}".format(int(num(top_r[1].get("visits"))))) if top_r[0] else ""
            glance.append(("Rivals", "the weakest direct rival has strength %d/100%s%s" % (min(drs), extra, ("; gap: " + first_sentence(biz["identified_gap"], 100)) if biz else ""),
                           *verdict(min(drs) < 40, min(drs) < 60)))
    if mk:
        if pp0.get("newcomer"):
            lo_, mid_, hi_ = pp0["newcomer"]["month_usd"]
            glance.append(("Market size, counted buyers", "about %s a month for a newcomer (%s to %s); the share is an assumption" % (money(mid_), money(lo_), money(hi_)),
                           *verdict(lo_ >= S.target_market_month, mid_ >= S.min_market_month)))
        glance.append(("Market size, Google search alone", "about %s a month (%s a year) reachable through Google search" % (money(round(mk_up / 12)), money(mk_up)),
                       *verdict(mk_up / 12 >= S.target_market_month, mk_up / 12 >= S.min_market_month)))
    if uec:
        ads_ok = uec.get("paid_search_cac") is not None and uec["paid_search_cac"] <= uec.get("max_cac", 0)
        glance.append(("Money", "you keep %s per sale; Google ads %s" % (money(uec["net_per_sale"]), "can pay off" if ads_ok else "would lose money"),
                       *verdict(uec["net_per_sale"] > 0 and ads_ok, uec["net_per_sale"] > 0)))
    fc = data.get("forecast_12m_usd") or {}
    if fc.get("mid") is not None:
        goal_ = S.min_market_usd
        glance.append(("First-year sales, Google search alone", "likely %s, about %s a month (bad case %s, good case %s)" % (money(fc.get("mid")), money(round(fc["mid"] / 12)), money(fc.get("low")), money(fc.get("high"))),
                       *verdict(fc["mid"] >= goal_, fc.get("high", 0) >= goal_)))
    fcp = data.get("forecast_people_12m_usd") or {}
    if fcp:
        glance.append(("First-year sales, counted buyers", "likely %s (bad case %s, good case %s) if a newcomer's share is reached by month 12. An assumption, not a measurement" % (money(fcp.get("mid")), money(fcp.get("low")), money(fcp.get("high"))),
                       *verdict(fcp.get("low", 0) >= S.min_market_usd, fcp.get("mid", 0) >= S.min_market_usd)))
    if eeat:
        oks = sum(1 for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example") if eeat[k]["ok"])
        n_if = sum(1 for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example")
                   if eeat[k]["ok"] and re.search(r"\b(if|unless|only when|provided|depends|as long as)\b", eeat[k]["answer"], re.I))
        glance.append(("Google trust", "%d of 4 trust checks can be met by launch%s" % (oks, (" (%d only under a condition)" % n_if) if n_if else ""), *verdict(oks == 4 and not n_if, oks >= 3)))
    if sc:
        fixed = offer.get("fixed_cost_usd_month") if offer else (costs or {}).get("budget_caps", {}).get("fixed_cost_usd_month")
        days_ = offer.get("build_days") or sc["effort"]["days_to_mvp"]
        glance.append(("Effort", "%s days to a first version%s%s" % (days_, " of the chosen offer" if offer else "", ("; about %s a month to run" % money(fixed)) if fixed is not None else ""),
                       *verdict(days_ <= 14, days_ <= 30)))

    fc_mid = (data.get("forecast_12m_usd") or {}).get("mid")
    # ================= THE SIMPLE REPORT (page 1-2) =================
    level = {"light": "QUICK CHECK", "full": "FULL CHECK", "deep": "DEEP CHECK"}.get(depth, "FULL CHECK")
    H.append("<div class=mute style='font-size:8.5pt;letter-spacing:.08em'>THE VENTURE MACHINE &middot; %s REPORT &middot; %s</div>" % (level, e(store.now()[:10])))
    H.append("<h1>%s</h1>" % e(v["one_liner"] or v["idea"]))
    H.append("<p class=mute>Checked for: %s &middot; Steps done: %d of 18 &middot; Data bought: %s</p>"
             % (e(v["country"].upper()), n_done, money(store.spent(slug))))
    if re.search(r"€|\bEUR\b", v["one_liner"] or v["idea"] or ""):
        H.append("<p class=small>The idea was written in euros. The machine works in US dollars: every price, cost and market number it worked out is in dollars%s. "
                 "Euro amounts further down are quotes from the idea or from rivals' own price pages.</p>"
                 % ((", and the chosen price is %s" % money((data.get("offer") or {}).get("price_usd"))) if (data.get("offer") or {}).get("price_usd") else ""))
    if data.get("angle_of"):
        H.append("<p class=small><b>This is the other angle</b> of the idea \"%s\", which scored %s out of 100 on its first look.</p>"
                 % (e(first_sentence(data.get("parent_idea") or data["angle_of"], 200)), e(data.get("parent_score100", "?"))))
    ring = ("<div class=ring style='background:conic-gradient(#fff %d%%, rgba(255,255,255,.3) 0)'><div style='background:%s'><b>%d</b><span>/100</span></div></div>"
            % (score100, color, score100) if score100 is not None else
            "<div class=ring style='background:rgba(255,255,255,.3)'><div style='background:%s'><b>?</b><span>/100</span></div></div>" % color)
    H.append("<div class=hero style='background:%s'><div class=herogrid>%s<div><div class=lbl>THE ANSWER</div><div class=ans>%s</div><p>%s</p></div></div></div>"
             % (color, ring, e(ans), e(why)))
    stage = [("First look", "3 checks, about 1 cent", first100 is not None, first100),
             ("Main score", "7 or 8 checks, after the full research", bool(scores) and not first and not quick, score100 if (scores and not first and not quick) else None)]
    if old_steps:
        H.append("<div class=worry><b>OUT OF DATE: do not decide on this report.</b> Steps %s ran under older rules or older results. "
                 "Refresh it (no new data is bought for searches already fetched): <b>vm run %s</b></div>" % (e(", ".join(old_steps)), e(slug)))
    if problems_:
        H.append("<div class=worry><b>NOT CONSISTENT: %d places in this report disagree with each other.</b> GO and TEST are switched off until it is fixed "
                 "(vm rerun %s 16, then vm run %s). KILL still works.%s</div>" % (len(problems_), e(slug), e(slug), bullets(problems_[:8])))
    if not quick and first100 is not None:
        H.append("<div class=stages>" + "".join(
            "<div class='%s'><span>%s</span><b>%s</b><i>%s</i></div>" % ("on" if done_ else "off", e(n_), ("%d/100" % val_) if val_ is not None else "not yet", e(sub_))
            for n_, sub_, done_, val_ in stage) + "</div>")
    if angle and (first or quick) and st in ("gate_05", "light_done", "kill_recommended"):
        H.append("<div class=angle><div class=lbl>ANOTHER ANGLE THAT COULD WORK</div><p><b>%s</b></p><p>%s</p><p class=small><b>Cheapest test:</b> %s</p>"
                 "<p class=small>%s</p></div>"
                 % (e(angle["idea"]), e(angle.get("why", "")), e(angle.get("cheapest_test", "")),
                    ("This angle was tested as its own idea (<b>%s</b>)%s." % (e(data["angle_slug"]),
                     (": it scored <b>%d out of 100</b> on its first look" % kid["data"]["first_score100"]) if kid and kid["data"].get("first_score100") is not None else "")) if data.get("angle_slug") else
                    ("The machine can run a first look on this angle as its own idea. In the app press <b>Test the other angle</b>, or type: <b>vm gate %s angle</b>" % e(slug))))
    if scores:
        H.append("<h3>The %d scores (out of 10)</h3><div class=mini>" % len(scores) + "".join(
            "<div><span class=q>%s</span><span class=bar><i style='width:%d%%;background:%s'></i></span><b>%d</b></div>"
            % (e(QMAP.get(k, k)), val * 20, GOOD if val >= 4 else CARE if val >= 3 else BAD, val * 2) for k, (val, _w) in scores.items()) + "</div>"
            + ("<p class='small mute'>First-look score = the average of the 3, out of 100. Under 60: weak as written. 60 or more: worth the paid research. "
               "This is an early judgement from what the AI found on the web, before any Google numbers. The main score (7 or 8 checks) replaces it after the full research.</p>" if first else
               "<p class='small mute'>Quick score = the average of the 6, out of 100. Under 55: skip it. 55-69: maybe. 70 or more: worth a full check. "
               "A quick check does not look at rivals, AI assistants, market size or money yet.</p>" if quick else
               "<p class='small mute'>Overall score = all the checks combined so that one very low score pulls the whole result down, out of 100. Under 60: don't build. 60-69: test it cheaply first. 70 or more: build. "
               "Rules that decide on their own: under %s a month reachable through Google search = don't build as a search business; between %s and %s a month = a cheap test first at most; "
               "likely first-year sales under %s a month = a cheap test first at most. Market score: under %s a month 2/10, %s 4/10, %s 6/10, %s 8/10, %s or more 10/10.</p>"
               % (money(S.min_market_month), money(S.min_market_month), money(S.target_market_month), money(S.min_market_month),
                  money(0.3 * S.target_market_month), money(0.3 * S.target_market_month), money(S.target_market_month), money(2 * S.target_market_month), money(5 * S.target_market_month))))
    if glance:
        H.append("<h3>Everything at a glance</h3><table class=glance>" + "".join(
            "<tr><td class=t>%s</td><td>%s</td><td class=n>%s</td></tr>" % (e(t), e(f), pill(w, c)) for t, f, w, c in glance) + "</table>")
    if main_done:
        best_k, worst_k = max(scores, key=lambda k_: scores[k_][0]), min(scores, key=lambda k_: scores[k_][0])
        three = [why if why.startswith("It scored") else "Main score %d out of 100. %s" % (score100, why),
                 "Strongest point: %s %s. Weakest point: %s %s." % (QMAP.get(best_k, best_k), first_sentence(scores[best_k][1], 140).rstrip("."), QMAP.get(worst_k, worst_k), first_sentence(scores[worst_k][1], 140).rstrip("."))]
        if fc_mid is not None:
            three.append("Likely first-year sales from Google search alone: %s, about %s a month." % (money(fc_mid), money(round(fc_mid / 12))) +
                         ((" Counting the buyers gives %s to %s (an assumption about the share a newcomer wins); search tools undercount small niches, so the two differ this much." % (money(fcp.get("low")), money(fcp.get("high")))) if fcp else ""))
        H.append("<h3>In three sentences</h3>" + bullets(three))
    elif sc:
        H.append("<h3>In three sentences%s</h3>" % (" (from the first look)" if kws else "") + bullets(sc["summary_3_lines"]))
    if main_done:
        proven, unproven = [], []
        if bc0.get("figure"):
            proven.append("%s people a year face this need (%s)" % ("{:,}".format(int(num(bc0["figure"]))), "official figure" if bc0.get("official") else "not an official figure"))
        if buy:
            proven.append("%s searches a month from people ready to buy (Google's own numbers; these tools tend to undercount small niches)" % "{:,}".format(buy_vol))
        if pp0.get("price_usd"):
            proven.append("buyers pay the leading rival about %s" % money(pp0["price_usd"]))
        if seo_:
            drs_ = [num(s_["dr"]) for s_ in seo_["competitors"] if s_.get("kind", "direct") == "direct" and s_.get("dr") is not None]
            if drs_:
                proven.append("the weakest direct rival's site has strength %d of 100" % min(drs_))
        cands_ = [x_ for x_ in pr0.get("comparables") or [] if x_.get("closeness", 1) >= 2] if pr0.get("checked") else []
        best_ = max(cands_, key=lambda x_: x_["revenue_30d_usd"]) if cands_ else None
        if best_:
            same2 = best_.get("closeness") == 3
            proven.append("%s made %s in the last 30 days (payment-verified)%s" % (best_["name"], money(best_["revenue_30d_usd"]), "" if same2 else ", in a neighbouring niche"))
            if not same2:
                unproven.append("nobody with verified revenue was found in this exact niche")
        if pp0.get("newcomer"):
            unproven.append("the share of buyers a new site wins (2% to 8% is an assumption; one real case backs the leader's share, none backs the newcomer's)")
        if offer.get("channel"):
            unproven.append("that buyers can be reached without paid ads (the test below checks this)")
        unproven.append("that buyers pick a new name over the known rival at %s" % money(offer.get("price_usd"))) if offer.get("price_usd") else None
        if proven and unproven:
            H.append("<div class=two><div><h3>What is measured</h3>%s</div><div><h3>What is still a guess</h3>%s</div></div>" % (bullets(proven), bullets(unproven)))
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
    H.append("<span class=num>PART 1</span><h2>The scorecard in detail</h2><p class=mute>The %s things that decide if this idea is worth %s, each out of 10.</p>"
             % (str(len(scores)) if (first and scores) else "3" if first else "6" if quick else str(len(scores)) if scores else "7", "paying for real research" if first else "a deeper look" if quick else "building"))
    if scores:
        H.append(plain(("First-look score <b>%d out of 100</b>. Under 60 means the idea is weak as written. 60 or more means it is worth the paid research. The main score comes later." if first else
                        "Quick score <b>%d out of 100</b>. Under 55 means skip it. 55 to 69 means maybe. 70 or more means it is worth a full check." if quick else
                        "Overall <b>%d out of 100</b>. Under 60 means don't build. 60 to 69 means run a cheap test first. 70 or more means build.") % score100))
        for k, (val, why_) in scores.items():
            col = GOOD if val >= 4 else CARE if val >= 3 else BAD
            H.append("<div class=score><div class=q>%s</div><div class=bar><i style='width:%d%%;background:%s'></i></div><div><b>%d</b>/10</div><div class=why>%s</div></div>"
                     % (e(QMAP.get(k, k)), val * 20, col, val * 2, e(why_)))
    else:
        H.append(plain("The scores appear once all research steps are done (step 18). So far %d of 18 steps are done." % n_done))
    if scores and not first and not quick and first100 is not None:
        H.append("<p class=small>For comparison: the first-look score, before any research, was <b>%d out of 100</b>.</p>" % first100)
    H.append("<h3>All the worries</h3>")
    H.append("<div class=worry>%s</div>" % bullets(worries) if worries else "<p>Nothing serious was flagged.</p>")
    H.append("<h3>All next steps</h3><ol class=steps>" + "".join("<li>%s</li>" % e(x) for x in nxt) + "</ol>")
    if section_open:
        end()

    # ================= REVENUE PROOF: DO REAL BUSINESSES MAKE MONEY HERE? =================
    pr = jf("02_proof.json")
    if pr:
        section("Do real businesses make money here?", "Businesses in this niche whose revenue is read from their payment provider, what they charge, and how they find buyers.")
        comps_ = pr.get("comparables") or []
        if not pr.get("checked"):
            H.append("<p><b>Not checked.</b> %s. Until it is checked, the money estimates in this report rest on search numbers alone, which measure one channel only.</p>"
                     % e(pr.get("note") or "No revenue data was available"))
        elif not comps_:
            H.append("<p><b>No real business with verified revenue was found in this niche.</b> That is not proof nobody earns here: the database only holds founders who chose to list. "
                     "It does mean there is no revenue proof yet.</p>")
        else:
            best_ = max(comps_, key=lambda x_: x_["revenue_30d_usd"])
            H.append("<p><b>%d real businesses compare to this idea.</b> The best earner, %s, made <b>%s in the last 30 days</b>%s. Revenue is read from the payment provider, not claimed.</p>"
                     % (len(comps_), e(best_["name"]), money(best_["revenue_30d_usd"]), (" selling at " + e(first_sentence(best_["price"], 90))) if best_.get("price") else ""))
            rw = [{"n": link(x_["page"], x_["name"]), "w": {3: "same niche", 2: "same kind of product", 1: "loosely alike"}.get(x_.get("closeness"), ""),
                   "r": money(x_["revenue_30d_usd"]), "t": money(x_["revenue_total_usd"]), "f": x_.get("founded") or "?", "p": first_sentence(x_.get("price") or "not listed", 70),
                   "v": ("{:,}".format(x_["visitors_30d"]) if x_.get("visitors_30d") else "not shared"),
                   "pv": (money(x_["revenue_per_visitor"]) if x_.get("revenue_per_visitor") else "-"), "d": x_.get("domain_rating") if x_.get("domain_rating") is not None else "?"} for x_ in comps_]
            H.append(table(rw, ["n", "w", "r", "t", "f", "p", "v", "pv", "d"],
                           ["Business", "How close", "Last 30 days", "All time", "Founded", "Price", "Visitors a month", "Earned per visitor", "Site strength (0-100)"], raw=("n",), right=("r", "t", "v", "pv", "d")))
            said = [x_ for x_ in comps_ if x_.get("channels")]
            if said:
                H.append("<p><b>Where they say buyers come from:</b> " + "; ".join("%s: %s%s" % (e(x_["name"]), e(", ".join(x_["channels"][:6]).replace("-", " ")),
                         " (<b>pays for ads</b>)" if x_.get("paid_channels") else "") for x_ in said) + ".</p>")
        ads_ = [a_ for a_ in pr.get("ads") or [] if a_.get("meta_ads") is not None or a_.get("google_ads") is not None]
        if ads_:
            show = lambda v_: "not checked" if v_ is None else "none found" if v_ == 0 else "{:,}".format(v_)  # noqa: E731
            H.append("<h3>Do rivals buy ads?</h3><p class=small>From the two public ad libraries. A rival that keeps paying for ads is earning from them, and its buyers do not come from free search alone.</p>" +
                     table([{"n": a_["name"], "m": show(a_.get("meta_ads")), "g": show(a_.get("google_ads"))} for a_ in ads_], ["n", "m", "g"],
                           ["Rival", "Facebook / Instagram ads running", "Google ads"], right=("m", "g")))
        ppl_, bc_ = pr.get("people"), pr.get("buyer_count") or {}
        if ppl_:
            H.append("<h3>Counting the buyers</h3><p><b>%s people a year</b> (%s%s; source: %s%s). At %s a customer, a newcomer taking %d%% to %d%% of them earns <b>%s to %s a month</b>, "
                     "and the leader of the niche, taking %d%% to %d%%, earns %s to %s a month.</p><p class=small>This is the estimate to trust most: in back-testing it was the only method that matched a real "
                     "business (an exam course that takes about 22%% to 39%% of a year's applicants), while search-based estimates were 12 to 48 times too low. The shares are still assumptions: "
                     "the leader's comes from that one case, the newcomer's is not measured.%s</p>"
                     % ("{:,}".format(ppl_["buyers_per_year"]), e(bc_.get("counts_what") or "yearly figure"), (", " + e(bc_["year"])) if bc_.get("year") else "",
                        link(bc_["source_url"], bc_.get("source_name") or "source") if bc_.get("source_url") else e(bc_.get("source_name") or "not named"),
                        "" if bc_.get("official") else ", not an official source", money(ppl_["price_usd"]),
                        round(ppl_["newcomer"]["share"][0] * 100), round(ppl_["newcomer"]["share"][2] * 100), money(ppl_["newcomer"]["month_usd"][0]), money(ppl_["newcomer"]["month_usd"][2]),
                        round(ppl_["leader"]["share"][0] * 100), round(ppl_["leader"]["share"][2] * 100), money(ppl_["leader"]["month_usd"][0]), money(ppl_["leader"]["month_usd"][2]),
                        (" " + e(bc_["notes"])) if bc_.get("notes") else ""))
        elif pr.get("buyer_count") is not None:
            H.append("<h3>Counting the buyers</h3><p class=small><b>Not counted.</b> No reliable yearly figure for the number of buyers was found%s. Without it the money estimates rest on search numbers, which undercount small niches.</p>"
                     % ((" (total holders: %s)" % "{:,}".format(bc_["total_holders"])) if bc_.get("total_holders") else ""))
        from . import proof as _pf
        bt_ = _pf.BACKTEST
        H.append("<h3>How far to trust the numbers in this report</h3><p class=small>Back-tested on %s businesses with payment-verified revenue (%s). "
                 "<b>A keyword tool's traffic estimate for a small site is typically %d times too low</b> against the site's real Google clicks (middle half %d to %d times). "
                 "A site that ranks gets about %d%% of the search demand it ranks for, not all of it. "
                 "Even using everything that can be known in advance, a revenue prediction is typically off by about %.1f times either way. "
                 "Of businesses that earn at all, the typical one makes %s a month and %d%% reach $10,000 a month. So read every money figure here as a range, and trust the real businesses above over any formula.</p>"
                 % ("{:,}".format(bt_["businesses"]), bt_["date"], bt_["tool_traffic_times_too_low"]["typical"], bt_["tool_traffic_times_too_low"]["low"], bt_["tool_traffic_times_too_low"]["high"],
                    round(bt_["share_of_ranked_demand"]["typical"] * 100), bt_["typical_miss_factor"], money(bt_["base"]["typical_usd"]), round(bt_["base"]["share_at_10k"] * 100)))
        cal_ = [b_ for b_ in pr.get("calibration") or [] if "median" in b_]
        if cal_:
            H.append("<h3>What real sites earn per visitor</h3><p class=small>From %d businesses with verified revenue and visitor counts. Small sites with a narrow buyer and a real price earn dollars per visitor; "
                     "big free tools earn cents. These are businesses that already earn, so read them as what a working site gets, not an average.</p>" % sum(b_["n"] for b_ in cal_) +
                     table([{"v": b_["visitors_month"], "n": b_["n"], "l": money(b_["low"]), "m": money(b_["median"]), "h": money(b_["high"])} for b_ in cal_], ["v", "n", "l", "m", "h"],
                           ["Visitors a month", "Businesses", "Lower quarter", "Typical", "Upper quarter"], right=("n", "l", "m", "h")))
        end()

    # ================= PART 2: DEMAND =================
    if short or pulse:
        section("Is there demand?", "Do enough people search Google for this, and is that growing or shrinking?")
        if short:
            top = max(short, key=lambda r: num(r["volume"]))
            best_ = [r for r in sorted(short, key=lambda r: -num(r["score"])) if r.get("intent") != "brand"][:15]
            easy = sum(1 for r in best_ if r["kd"] != "" and num(r["kd"]) <= 30)
            if split["brand"] or dropped_kw:
                H.append("<p class=small><b>How the buying searches are counted:</b> %s commercial searches count in full; %s searches for a rival's name alone count 10%% "
                         "(those people want that rival's site); %s learning searches are not counted.%s</p>"
                         % ("{:,}".format(split["commercial"]), "{:,}".format(split["brand"]), "{:,}".format(split["info"]),
                            (" <b>%d searches were thrown out</b> because Google shows something else for them: %s."
                             % (len(dropped_kw), "; ".join("\"%s\" (%s a month): %s" % (e(x_["keyword"]), e(x_["volume"]), e(first_sentence(x_["reason"], 110))) for x_ in dropped_kw[:4]))) if dropped_kw else ""))
            H.append(plain("About <b>{:,}</b> searches a month come from people who look ready to buy. The biggest single search is "
                           "<b>\"{}\"</b> ({:,} a month). <b>{} of the {}</b> best searches below have an easy or very easy difficulty score (a rival's own name is never counted as easy)."
                           .format(buy_vol, e(top["keyword"]), int(num(top["volume"])), easy, len(best_))))
            rows = [{"kw": r["keyword"], "vol": "{:,}".format(int(num(r["volume"]))), "cpc": money(r["cpc"]), "kd": pill("rival's name", CARE) if r.get("intent") == "brand" else kd_word(r["kd"]),
                     "who": {"buy": "ready to buy", "competitor": "comparing rivals", "brand": "wants a rival's own site", "brand-model": "wants a specific thing", "info": "just learning"}.get(r["intent"], r["intent"])}
                    for r in sorted(short, key=lambda r: (r.get("intent") == "brand", -num(r["score"])))[:15]]
            H.append("<h3>The best searches to go after</h3>" + table(rows, ["kw", "vol", "cpc", "kd", "who"],
                                                                      ["What people type into Google", "Searches a month", "Ad click price", "Difficulty score", "Who is searching"],
                                                                      raw=("kd",), right=("vol", "cpc")))
        if pulse:
            word = {"alive": ("alive", GOOD, "People still search for this and new sites keep appearing."),
                    "flat": ("flat", CARE, "Interest is not growing, but it is not dying either."),
                    "dying": ("dying", BAD, "Fewer people search for this every year."),
                    "unknown": ("unknown", CARE, "There was not enough data to tell: no trend history, no advertisers and no fresh discussions. That is not proof of demand.")}[pulse["status"]]
            H.append("<h3>Is it growing? %s</h3><p>%s%s</p>" % (pill(word[0], word[1]), e(word[2]),
                     (" This verdict rests on one measured signal: %s (%+.0f%%). Google Trends itself had no data." % (e(pulse["status_source"]), num(pulse.get("kw_trend_12m_pct")))) if pulse.get("status_source") else ""))
            tr = [{"t": t, "c": ("%+.0f%%" % x["change_24m_pct"]) if x["change_24m_pct"] is not None else "not enough data"} for t, x in pulse.get("trend", {}).items()]
            H.append(table(tr, ["t", "c"], ["Search term", "Change over the last 2 years (Google Trends)"], right=("c",)))
            gone = {x_["keyword"].lower() for x_ in dropped_kw}
            newer = [w_ for w_ in pulse.get("rising_synonyms") or [] if w_.lower() not in gone]
            if newer:
                H.append("<p><b>Newer words people now use</b> (found by the AI on the web, not measured): %s</p>" % e(", ".join(newer)))
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
("Get links. %d sites already link to 2 or more of your rivals (appendix C). Ask them, starting with the strongest." % n_links) if n_links else
            "Get links another way: no site worth asking links to 2 or more of your rivals. Publish one data asset people cite, list the site in the real directories of this niche, and pitch the numbers to writers who cover it.",
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
            hist_ = (mk or {}).get("rival_traffic_history") or {}
            for c_ in comps:
                t_ = rtr.get(c_["domain"]) or {}
                u_ = uxd.get(c_["domain"], {})
                tr_ = t_.get("trend_12m_pct")
                age = u_.get("domain_created") or ""
                rows.append({"s": c_["domain"],
                             "v": ("{:,}".format(int(num(hist_[c_["domain"]][-1]["visits"]))) if hist_.get(c_["domain"]) else
                                   "{:,}".format(int(num(t_.get("visits")))) if t_.get("visits") is not None else "?"),
                             "vn": num(hist_[c_["domain"]][-1]["visits"]) if hist_.get(c_["domain"]) else num(t_.get("visits")),
                             "a": money(t_.get("ads_value")) if t_.get("ads_value") is not None else "?",
                             "t": ("%+d%%" % tr_) if tr_ is not None else "-",
                             "y": ("%s (%d yrs)" % (age[:4], max(0, int(store.now()[:4]) - int(age[:4])))) if age[:4].isdigit() else "?",
                             "sp": ("%s/100" % u_["mobile_speed_score"]) if u_.get("mobile_speed_score") is not None else "?"})
            H.append("<h3>How big each rival is</h3>" + table(rows, ["s", "v", "a", "t", "y", "sp"],
                     ["Site", "Google visits a month", "Worth in ads a month*", "Visits, last 12 months**", "Domain registered***", "Phone speed"], right=("v", "a", "t")) +
                     "<p class='small mute'>* What those visitors would cost if bought as Google ads. Visits are DataForSEO estimates (the latest month of the same history shown in the market part). "
                     "** Average of the last 3 months against the average of the first 3 of the 12, so it differs from comparing two single months. "
                     "*** When the web address was first registered; the business on it can be much younger. Phone speed is Google's Lighthouse score; under 50 is slow, 90+ is fast.</p>")
            young = [r_ for r_ in rows if ("(0 yrs)" in r_["y"] or "(1 yrs)" in r_["y"]) and r_["vn"] >= 100]
            if young:
                H.append("<p><b>Good sign:</b> %s %s on a web address less than 2 years old and already gets 100+ Google visits a month, so new sites can get in.</p>"
                         % (e(", ".join(r_["s"] for r_ in young)), "is" if len(young) == 1 else "are"))
        if biz:
            H.append("<div class=gap><b>THE GAP YOU CAN OWN</b><br>%s</div>" % e(biz["identified_gap"]))
        if how:
            cp = [{"n": c["name"], "p": c["price"], "s": link(c["source_url"], "link")} for c in how["competitors"]]
            H.append("<h3>Others already charging for this</h3><p class=small>This is a different list from the %s sites above: these %d were found in the first web check as "
                     "businesses that charge for something similar, whether or not they rank on Google for our searches.</p>" % (len(comps) if comps else "ranking", len(how["competitors"])) + table(cp, ["n", "p", "s"], ["Who", "What they charge", "Proof"], raw=("s",)))
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
        with_text = [a for a in aiv.get("answers") or [] if a.get("text") and (a.get("cited") or re.search(r"\b[a-z0-9-]+\.(com|io|co|ai|app|net|org)\b", a["text"], re.I))]
        if not with_text and aiv.get("answers"):
            H.append("<p class=small>None of the AI answers named a specific site, so there is no example to show: nobody owns this question yet.</p>")
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
        goal = S.min_market_usd
        H.append(plain("<b>Reachable through Google search: %s a year.</b> That is roughly what the top sites can earn from these searches if about 1 in 100 visitors buys%s. "
                       "It covers Google search only; other channels (cold email, communities) are not in it. "
                       "<b>Big-picture guess: %s</b> for the whole industry; you will only ever get a small slice of that. "
                       "The search number is about <b>%s a month</b>. We want %s a month or more; under %s a month is too small to build as a search business, and in between the most an idea gets is a cheap test first."
                       % (money(mk_up), (" at the chosen price of %s" % money(mk["chosen_price_usd"])) if mk.get("chosen_price_usd") else "", (money(mk["top_down_usd_year"]) + " a year") if num(mk.get("top_down_usd_year")) else "unknown (no sourced number was found)", money(round(mk_up / 12)), money(S.target_market_month), money(S.min_market_month))))
        H.append("<div class=two><div class=card><h4>How the search number works</h4><p class=small>%s</p></div><div class=card><h4>How the big-picture guess works</h4><p class=small>%s</p></div></div>"
                 % (e(mk.get("bottom_up_method_at_chosen_price") or mk["bottom_up_method"]), e(first_sentence(mk["top_down_method"], 400))))
        rows = [{"c": k.upper(), "s": ("{:,}".format(val) if isinstance(val, int) else "no data (API error)")} for k, val in mk.get("search_volume_by_country", {}).items()]
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
                       "Google ads would cost about <b>%s</b> per customer (the average ad click price divided by the share of visitors who buy), so ads %s."
                       % (e(c["model"]), money(c["price_usd"]), money(c["net_per_sale"]), money(c["max_cac"]), money(c["paid_search_cac"]),
                          "<b>can work</b>" if ads_ok else "<b>would lose money</b>: get customers from Google search results (free) and email instead")))
        ph = lambda o: o.get("profit_per_hour", o.get("profit_per_hour_at_1000_visits"))
        rows = [{"m": o["model"] + ("" if o.get("same_buyer_and_channel", True) else " (different buyer or channel: not chosen here)"), "p": money(o["price_usd"]) + (" a month" if o.get("payment") == "subscription" else ""),
                 "k": money(o["net_per_sale"]), "c": money(o["max_cac"]), "h": ("-%s" % money(-ph(o))) if num(ph(o)) < 0 else money(ph(o))} for o in ue["options"]]
        H.append("<h3>The ways to charge that were compared</h3>" + table(rows, ["m", "p", "k", "c", "h"],
                                                                         ["How you charge", "Price", "You keep per sale", "Max to spend per customer", "Profit per hour of your time*"],
                                                                         right=("p", "k", "c", "h")) + "<p class='small mute'>* after fixed costs, at %s visitors a month: what Google can really send for these searches (never more than 1,000). "
                 "The best option for this idea's own buyer through Google search was picked.%s</p>"
                 % ("{:,}".format(int(num(c.get("visits_used"), 1000))), (" Max to spend per customer = what you keep per sale x %s months a customer stays (an assumption)." % ("%g" % c["retention_months"])) if num(c.get("retention_months")) > 1 else "")
                 + (("<h3>What the chosen numbers rest on</h3>" + bullets(c["assumptions"])) if c.get("assumptions") else "")
                 + (("<div class=angle><div class=lbl>A DIFFERENT BUSINESS, SET ASIDE</div><p><b>%s</b></p><p>%s</p><p class=small>Run it as its own idea: <b>vm new \"%s\"</b></p></div>"
                     % (e(spin["idea"]), e(spin["why"]), e(spin["idea"]))) if spin else ""))
        if costs:
            H.append("<p><b>Running costs for the chosen offer:</b> about %s a month at the start (the tools: %s a month at 10 times the size). Delivering one sale costs about %s in data.</p>"
                     % (money(c.get("fixed_cost_usd_month", costs["budget_caps"]["fixed_cost_usd_month"])), money(costs["budget_caps"]["fixed_cost_10x_usd_month"]),
                        money(c.get("delivery_cost_per_sale_usd", costs["budget_caps"].get("data_cost_per_sale_usd")))))
        if ue.get("ladder"):
            H.append("<h3>Steps and dates</h3><p class=small>Worked out from the validation test and the forecast, not typed by hand.</p>"
                     + table(ue["ladder"], ["goal", "by"], ["Step", "When"]))
        end()

    # ================= PART 6: TRUST + FOR/AGAINST =================
    if eeat or sc:
        section("Can it work at all?", "Will Google trust the site, and the honest arguments for and against.")
        if eeat:
            names = {"real_person_or_company": "A real person or company behind it", "expertise_proof": "Proof you know the topic",
                     "unique_data_per_page": "Something unique on every page", "contacts_policies_real_example": "Contact details, policies, a real example"}
            oks = sum(1 for k in names if eeat[k]["ok"])
            cond = lambda k: eeat[k]["ok"] and re.search(r"\b(if|unless|only when|provided|depends|as long as)\b", eeat[k]["answer"], re.I)
            n_cond = sum(1 for k in names if cond(k))
            H.append(plain("Google only shows sites it trusts. <b>%d of 4</b> trust checks can be met by launch%s. Risk level for this topic: <b>%s</b>."
                           % (oks, (", but <b>%d of them only under a condition</b> (see the table)" % n_cond) if n_cond else "", e(eeat["ymyl_level"]))))
            rows = [{"c": names[k], "ok": pill("only if", CARE) if cond(k) else pill("yes", GOOD) if eeat[k]["ok"] else pill("no", BAD), "a": first_sentence(eeat[k]["answer"], 260)} for k in names]
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
            fcd = data.get("forecast_12m_usd") or {}
            if fcd:
                H.append("<p><b>First-year sales forecast (Google search alone):</b> bad case %s &middot; likely %s &middot; good case %s. %s</p>"
                         % (money(fcd.get("low")), money(fcd.get("mid")), money(fcd.get("high")), e(data.get("forecast_note") or "")))
                if fcp:
                    H.append("<p><b>First-year sales from counted buyers:</b> bad case %s &middot; likely %s &middot; good case %s. This takes the official yearly number of buyers, the share a newcomer wins (2%%, 5%%, 8%%, reached by month 12) and the leading rival's price. "
                             "The share is an ASSUMPTION; it fits small niches with few rivals and is too high for crowded ones. The dates below use the bad case.</p>"
                             % (money(fcp.get("low")), money(fcp.get("mid")), money(fcp.get("high"))))
        tst = offer.get("test")
        if tst:
            H.append("<div class=card><h4>The one validation test%s</h4><p class=small><b>%s</b>: %s. %s days%s, budget %s, at the price of %s.</p>"
                     "<p class=small><b>Pass if:</b> %s<br><b>Stop if:</b> %s</p></div>"
                     % (" (first: nothing is built before it ends)" if (data.get("timeline") or {}).get("test_first") else "", e(tst["test"]), e(tst["sample"]), e(tst["days"]),
                        (" after %s days of warm-up" % e(tst["warmup_days"])) if tst.get("warmup_days") else "", money(tst["budget_usd"]), money(tst["price_usd"]),
                        e(tst["pass_threshold"]), e(tst["kill_threshold"])))
        if plan:
            lvl_of = {cl["head"]: rank_level(cl)[0] for cl in (clusters or [])}
            hard = lambda p: pill(LEVELS[lvl_of[p["head"]]][0], LEVELS[lvl_of[p["head"]]][1]) if p.get("head") in lvl_of else pill("support page", MUTE)
            rows = [{"p": p["title"], "t": p["page_type"], "s": "{:,}".format(int(num(p.get("volume")))), "kd": hard(p), "u": first_sentence(p["unique_data_source"], 140)}
                    for p in plan["pages"]]
            H.append("<h3>The pages to build (%d planned, all shown)</h3>" % len(plan["pages"]) +
                     table(rows, ["p", "t", "s", "kd", "u"], ["Page", "Type", "Searches a month", "How hard", "What makes it unique"], raw=("kd",), right=("s",)))
        if costs:
            H.append("<h3>Do these by hand before building</h3>" + table(costs["owner_todo"], ["task", "minutes"], ["Task", "Minutes"], right=("minutes",)))
            H.append("<h3>Rules for this business%s</h3>" % (" (written for the chosen offer)" if offer else "") + bullets(costs["guardrails"][:10]))
        if (t := tf("20_quick_test.md")):
            H.append("<h3>The quick test</h3>" + md(t))
        end()

    # ================= APPENDIX =================
    H.append("<div class=sec><span class=num>APPENDIX</span><h2>The details</h2><p class=mute>For checking the work. You can skip this.</p>")
    rows = []
    for bid in sorted(bl):
        st = bl[bid]
        vd = st.get("verdict") or st["status"].lower()
        word = {"pass": pill("good", GOOD), "warn": pill("careful", CARE), "fail": pill("failed its bar", BAD), "kill": pill("problem", BAD), "redo": pill("problem", BAD)}.get(vd, pill(vd, MUTE))
        rows.append({"n": bid, "q": STEP_NAMES.get(bid, bid), "r": word, "f": first_sentence(st.get("summary") or st.get("error"), 300)})
    H.append("<h3>A. Every step and what it found</h3>" + table(rows, ["n", "q", "r", "f"], ["#", "Step", "Result", "What it found"], raw=("r",)))
    if clusters:
        rows = [{"h": c["head"], "v": "{:,}".format(int(c["volume"])), "k": pill(LEVELS[rank_level(c)[0]][0], LEVELS[rank_level(c)[0]][1]), "n": len(c["keywords"]), "w": "; ".join(c["weak_spots"]) or "-"} for c in clusters[:30]]
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

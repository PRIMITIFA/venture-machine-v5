"""One HTML report per venture: status of every block, gate memos, key tables, money spent."""
import html
import json

from . import store
from .config import S
from .pipeline import registry
from .util import read_csv

CSS = """
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--acc:#1d4ed8}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:32px 20px 80px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 10px}
.mute{color:var(--mute)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600}.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid}
.VALIDATED.pass{color:var(--ok)}.VALIDATED.warn{color:var(--warn)}.ALERT{color:var(--bad)}.WAITING{color:var(--acc)}.PENDING,.RUNNING,.RETRY{color:var(--mute)}
pre{white-space:pre-wrap;margin:0;font:13px/1.5 ui-monospace,Consolas,monospace}a{color:var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.big{font-size:22px;font-weight:700}
form.inline{display:inline}button{font:inherit;padding:7px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer}
button.primary{background:var(--ink);color:#fff;border-color:var(--ink)}button.danger{color:var(--bad)}
input,textarea,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;width:100%}
"""


STATUS = {"gate_05": "Waiting: Gate 1", "gate_14": "Waiting: Gate 2", "gate_18": "Waiting: Gate 3", "active": "Ready to run",
          "running": "Running", "alert": "Stopped (see red block)", "kill_recommended": "Kill recommended", "killed": "Killed",
          "approved_build": "Approved to build", "quick_test": "Quick test", "phase4_done": "Phase 4 done"}


def status_label(st):
    return STATUS.get(st, st)


def e(x):
    return html.escape(str(x if x is not None else ""))


def table(rows, cols, limit=25):
    if not rows:
        return "<p class=mute>none</p>"
    h = "<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>"
    for r in rows[:limit]:
        h += "<tr>" + "".join(f"<td>{e(r.get(c, ''))}</td>" for c in cols) + "</tr>"
    return h + "</table>" + (f"<p class=mute>{len(rows) - limit} more in the file</p>" if len(rows) > limit else "")


def body(slug, actions=""):
    v = store.venture(slug)
    d = S.ventures_dir / slug
    bl = store.blocks(slug)
    spent = store.spent(slug)
    allc = sum(r["usd"] for r in store.ledger(slug))
    h = [f"<h1>{e(v['one_liner'] or v['idea'])}</h1><p class=mute>{e(slug)} | {e(v['country'])}/{e(v['lang'])} | created {e(v['created'])}</p>",
         "<div class=grid>",
         f"<div class=card><div class=mute>Status</div><div class=big>{e(status_label(v['status']))}</div></div>",
         f"<div class=card><div class=mute>Counted spend</div><div class=big>${spent:.2f}</div><div class=mute>cap ${S.max_usd_per_idea:.2f}; all incl. subscription ${allc:.2f}</div></div>",
         f"<div class=card><div class=mute>Score</div><div class=big>{e(v['data'].get('gate3_score100', '-'))}<span class=mute style='font-size:14px'>/100</span></div><div class=mute>{e(v['data'].get('gate3_recommendation', ''))}</div></div>",
         "</div>", actions]
    if v.get("pivot_note"):
        h.append(f"<div class=card><b>Pivot:</b> {e(v['pivot_note'])}</div>")
    h.append("<h2>Blocks</h2><div class=card><table><tr><th>#</th><th>Block</th><th>State</th><th>Result</th></tr>")
    for b in registry():
        st = bl.get(b.id, {"status": "PENDING", "verdict": "", "summary": "", "error": ""})
        res = st.get("summary") or ""
        if st.get("error"):
            res += f" | {st['error']}"
        label = st["status"] + (f" / {st['verdict']}" if st.get("verdict") else "")
        cell = f"<pre>{e(res)}</pre>" if b.kind == "gate" else e(res)
        h.append(f"<tr><td>{b.id}</td><td>{e(b.name)}</td><td class='{e(st['status'])} {e(st.get('verdict', ''))}'><b>{e(label)}</b></td><td>{cell}</td></tr>")
    h.append("</table></div>")

    def jf(name):
        p = d / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def cf(name):
        p = d / name
        return read_csv(p) if p.exists() else None

    if (x := cf("11_shortlist.csv")):
        h.append("<h2>Keyword shortlist</h2><div class=card>" + table(x, ["role", "keyword", "volume", "cpc", "intent", "kd", "score"], 45) + "</div>")
    if (x := jf("11_top_competitors.json")):
        h.append("<h2>Top-5 competitors (from SERPs)</h2><div class=card>" + table(x, ["domain", "weight", "serps", "dr", "known_in_02"]) + "</div>")
    if (x := jf("10_clusters_serp.json")):
        rows = [{"id": c["id"], "head": c["head"], "kws": len(c["keywords"]), "volume": int(c["volume"]), "intent": c["intent"], "kd": c.get("kd", ""),
                 "score": c.get("score", ""), "format": c["winning_format"], "weak spots": "; ".join(c["weak_spots"])} for c in x]
        h.append("<h2>Clusters (1 cluster = 1 page)</h2><div class=card>" + table(rows, list(rows[0]) if rows else [], 30) + "</div>")
    if (x := jf("13_competitor_business.json")):
        h.append(f"<h2>Gap</h2><div class=card><b>{e(x.get('identified_gap'))}</b></div>")
    if (x := jf("14_market_analysis.json")):
        h.append(f"<h2>Market</h2><div class=card>Bottom-up <b>${x['bottom_up_usd_year']:,.0f}</b>/yr ({e(x['bottom_up_method'])})<br>"
                 f"Top-down <b>${x['top_down_usd_year']:,.0f}</b>/yr ({e(x['top_down_method'])})</div>")
    if (x := cf("15_link_targets.csv")):
        h.append("<h2>Link targets</h2><div class=card>" + table(x, ["domain", "dr", "links_to_n", "competitors"], 20) + "</div>")
    if (x := jf("16_unit_economics.json")):
        h.append("<h2>Unit economics</h2><div class=card>" + table(x["options"], ["model", "price_usd", "conversion_pct", "net_per_sale", "max_cac", "breakeven_cpc", "paid_search_cac", "profit_per_hour_at_1000_visits"]) + "</div>")
    files = sorted(p.name for p in d.glob("*") if p.is_file()) if d.exists() else []
    h.append("<h2>Files</h2><div class=card>" + " &middot; ".join(e(f) for f in files) + f"<p class=mute>Folder: {e(d)}</p></div>")
    led = store.ledger(slug)
    if led:
        agg = {}
        for r in led:
            k = (r["block"], r["provider"])
            a = agg.setdefault(k, {"block": r["block"], "provider": r["provider"], "calls": 0, "cached": 0, "usd": 0.0})
            a["calls"] += 1
            a["cached"] += r["cached"]
            a["usd"] = round(a["usd"] + r["usd"], 4)
        h.append("<h2>Spend by block</h2><div class=card>" + table(list(agg.values()), ["block", "provider", "calls", "cached", "usd"], 80) + "</div>")
    return "\n".join(h)


def page(title, inner, refresh=False):
    meta = '<meta http-equiv="refresh" content="4">' if refresh else ""
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"{meta}<title>{e(title)}</title><style>{CSS}</style></head><body><main>{inner}</main></body></html>")


def write(slug):
    p = S.ventures_dir / slug / "report.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page(slug, body(slug)), encoding="utf-8")
    return p

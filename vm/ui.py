"""Local web app (no extra installs): add ideas, run them, decide gates. http://127.0.0.1:8765"""
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import pdf, pipeline, report, store
from .config import LOCATIONS, S
from .report import e

RUNNING = {}  # slug -> list of log lines
LOCK = threading.Lock()


def _bg_run(slug):
    lines = RUNNING[slug]
    try:
        pipeline.run(slug, say=lambda m: lines.append(m))
    except Exception as ex:
        lines.append(f"crashed: {ex}\n{traceback.format_exc()[-800:]}")
        store.update_venture(slug, status="alert")
    finally:
        report.write(slug)
        try:
            pdf.write(slug)
        except Exception as ex:
            lines.append(f"PDF failed: {ex}")
        with LOCK:
            RUNNING.pop(slug, None)


def start(slug):
    with LOCK:
        if slug in RUNNING:
            return
        RUNNING[slug] = []
    threading.Thread(target=_bg_run, args=(slug,), daemon=True).start()


def home():
    rows = ""
    for v in store.ventures():
        done = sum(1 for b in store.blocks(v["slug"]).values() if b["status"] == "VALIDATED")
        st = "running..." if v["slug"] in RUNNING else report.status_label(v["status"])
        rows += (f"<tr><td><a href='/v/{e(v['slug'])}'>{e(v['one_liner'] or v['idea'])}</a><div class=mute>{e(v['slug'])} &middot; {e(v['data'].get('depth', 'full'))}</div></td>"
                 f"<td>{e(st)}</td><td>{done}/18</td><td>${store.spent(v['slug']):.2f}</td></tr>")
    opts = "".join(f"<option value='{c}'{' selected' if c == 'us' else ''}>{c.upper()}</option>" for c in LOCATIONS if c != "uk")
    return report.page("Venture Machine", f"""
<h1>Venture Machine</h1><p class=mute>Check any business idea with real Google data. Pick a quick check (minutes, cents) or a full / deep check (rivals, AI assistants, market, money, plan).</p>
<div class=card><form method=post action=/new>
<label>Idea (who wants what, and what would they pay for?)</label>
<textarea name=idea rows=3 required placeholder="People who buy used cars want the original window sticker and would pay $15 for it"></textarea>
<div class=grid style="margin-top:10px"><div><label>Source link (optional)</label><input name=source></div>
<div><label>Country</label><select name=country>{opts}</select></div>
<div><label>How deep</label><select name=depth><option value=light>Quick check: ~5 min, ~$0.20</option>
<option value=full selected>Full check: ~30 min, ~$2-3</option><option value=deep>Deep check: ~45 min, ~$4-7</option></select></div></div>
<p><button class=primary>Add and run</button></p></form></div>
<h2>Ideas</h2><div class=card><table><tr><th>Idea</th><th>Status</th><th>Blocks</th><th>Spent</th></tr>{rows or '<tr><td colspan=4 class=mute>none yet</td></tr>'}</table></div>""",
                       refresh=bool(RUNNING))


def venture_page(slug):
    v = store.venture(slug)
    if not v:
        return None
    acts = (f"<p><a href='/'>&larr; all ideas</a> &nbsp; <a href='/pdf/{e(slug)}'><button>Download findings PDF</button></a></p>")
    if slug in RUNNING:
        acts += "<div class=card><b>Running...</b><pre>" + e("\n".join(RUNNING[slug][-30:])) + "</pre></div>"
    else:
        st = v["status"]
        btn = lambda d, cls="": (f"<form class=inline method=post action='/gate/{e(slug)}'><input type=hidden name=decision value={d}>"
                                 f"<button class='{cls}'>{d.upper()}</button></form> ")
        ang = v["data"].get("other_angle") or {}
        angle_btn = ""
        if v["data"].get("angle_slug") and store.venture(v["data"]["angle_slug"]):
            angle_btn = f"<a href='/v/{e(v['data']['angle_slug'])}'><button>Open the other angle</button></a> "
        elif ang.get("idea"):
            angle_btn = (f"<form class=inline method=post action='/gate/{e(slug)}'><input type=hidden name=decision value=angle>"
                         f"<button class='{'primary' if (v['data'].get('first_score100') or 100) < 60 else ''}'>Test the other angle (about 1 cent)</button></form> ")
        if v["data"].get("angle_of"):
            acts += (f"<div class=card>This is the <b>other angle</b> of <a href='/v/{e(v['data']['angle_of'])}'>{e(v['data'].get('parent_idea') or v['data']['angle_of'])}</a>"
                     f" (that idea scored {e(v['data'].get('parent_score100', '?'))}/100).</div>")
        if ang.get("idea") and st in ("gate_05", "light_done", "kill_recommended"):
            acts += (f"<div class=card><b>Another angle that could work</b><p>{e(ang['idea'])}</p><p class=mute>{e(ang.get('why', ''))}</p>"
                     f"<p class=mute>Cheapest test: {e(ang.get('cheapest_test', ''))}</p><p>{angle_btn}</p></div>")
        if st.startswith("gate_"):
            b = pipeline.by_id()[st.removeprefix("gate_")]
            memo = store.block(slug, b.id).get("summary", "")
            acts += f"<div class=card><b>{e(b.name)}</b><pre>{e(memo)}</pre><p>"
            for d in b.decisions:
                if d == "angle":
                    continue  # shown in its own card above
                if d == "pivot":
                    acts += (f"<form method=post action='/gate/{e(slug)}' style='margin:8px 0'><input type=hidden name=decision value=pivot>"
                             f"<input name=note placeholder='Pivot to... (e.g. UK only, B2B dealers)' required style='width:60%'> <button>PIVOT</button></form>")
                else:
                    acts += btn(d, "primary" if d == "go" else "danger" if d == "kill" else "")
            acts += "</p></div>"
        elif st in ("kill_recommended", "alert"):
            acts += (f"<div class=card><b>Stopped: {e(st)}</b> - see the red block below.<p>{btn('kill', 'danger')}"
                     f"<form class=inline method=post action='/gate/{e(slug)}'><input type=hidden name=decision value=override>"
                     f"<input name=note placeholder='why continue anyway' required style='width:40%'> <button>OVERRIDE</button></form></p></div>")
        elif st == "light_done":
            memo = store.block(slug, "09").get("summary", "")
            qm = (S.ventures_dir / slug / "09_quick_memo.md")
            acts += ("<div class=card><b>Quick check done</b><pre>%s</pre><p>"
                     "<form class=inline method=post action='/deepen/%s'><input type=hidden name=depth value=full><button class=primary>Run full check (~$2-3)</button></form> "
                     "<form class=inline method=post action='/deepen/%s'><input type=hidden name=depth value=deep><button>Run deep check (~$4-7)</button></form> %s</p></div>"
                     % (e(qm.read_text(encoding="utf-8") if qm.exists() else memo), e(slug), e(slug), btn("kill", "danger")))
        elif st not in ("killed", "approved_build", "phase4_done", "quick_test"):
            acts += f"<form method=post action='/run/{e(slug)}'><button class=primary>Run next blocks</button></form>"
    return report.page(slug, report.body(slug, acts), refresh=slug in RUNNING)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8", loc=None):
        self.send_response(code)
        if loc:
            self.send_header("Location", loc)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if body:
            self.wfile.write(body.encode("utf-8"))

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")).items()}

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path == "/":
            return self.send(200, home())
        if path.startswith("/v/"):
            pg = venture_page(path[3:])
            return self.send(200, pg) if pg else self.send(404, "not found")
        if path.startswith("/pdf/"):
            slug = path[5:]
            if not store.venture(slug):
                return self.send(404, "not found")
            f, msg = pdf.write(slug)
            if not f:
                return self.send(500, report.page("PDF", f"<div class=card>{e(msg)}</div>"))
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{slug}-findings.pdf"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/files/"):
            slug, _, name = path[7:].partition("/")
            f = (S.ventures_dir / slug / name).resolve()
            if f.is_file() and (S.ventures_dir.resolve() in f.parents):
                return self.send(200, f.read_text(encoding="utf-8", errors="replace"), "text/plain; charset=utf-8")
            return self.send(404, "not found")
        self.send(404, "not found")

    def do_POST(self):
        path = urllib.parse.unquote(self.path)
        f = self.form()
        try:
            if path == "/new":
                slug = pipeline.new(f.get("idea", "").strip(), f.get("source", "").strip(), f.get("country", "us"), depth=f.get("depth", "full"))
                start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
            if path.startswith("/run/"):
                slug = path[5:]
                start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
            if path.startswith("/deepen/"):
                slug = path[8:]
                pipeline.deepen(slug, f.get("depth", "full"))
                start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
            if path.startswith("/gate/"):
                slug = path[6:]
                pipeline.gate(slug, f.get("decision", ""), f.get("note", ""))
                report.write(slug)
                if f.get("decision") == "angle":
                    child = store.venture(slug)["data"]["angle_slug"]
                    start(child)
                    return self.send(303, "", loc=f"/v/{child}")
                if f.get("decision") in ("go", "pivot", "override"):
                    start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
        except SystemExit as ex:
            return self.send(400, report.page("error", f"<p><a href='/'>&larr; back</a></p><div class=card>{e(ex)}</div>"))
        self.send(404, "not found")


def serve(port=8765):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}"
    print(f"Venture Machine running at {url}  (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

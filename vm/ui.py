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
        rows += (f"<tr><td><a href='/v/{e(v['slug'])}'>{e(v['one_liner'] or v['idea'])}</a><div class=mute>{e(v['slug'])}</div></td>"
                 f"<td>{e(st)}</td><td>{done}/18</td><td>${store.spent(v['slug']):.2f}</td></tr>")
    opts = "".join(f"<option value='{c}'{' selected' if c == 'us' else ''}>{c.upper()}</option>" for c in LOCATIONS if c != "uk")
    return report.page("Venture Machine", f"""
<h1>Venture Machine</h1><p class=mute>Phases 1-4: idea filter, demand + SEO, competitors + market, plan + costs. Cap ${S.max_usd_per_idea:.2f} per idea.</p>
<div class=card><form method=post action=/new>
<label>Idea (who wants what, and what would they pay for?)</label>
<textarea name=idea rows=3 required placeholder="People who buy used cars want the original window sticker and would pay $15 for it"></textarea>
<div class=grid style="margin-top:10px"><div><label>Source link (optional)</label><input name=source></div>
<div><label>Country</label><select name=country>{opts}</select></div></div>
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
        if st.startswith("gate_"):
            b = pipeline.by_id()[st.removeprefix("gate_")]
            memo = store.block(slug, b.id).get("summary", "")
            acts += f"<div class=card><b>{e(b.name)}</b><pre>{e(memo)}</pre><p>"
            for d in b.decisions:
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
                slug = pipeline.new(f.get("idea", "").strip(), f.get("source", "").strip(), f.get("country", "us"))
                start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
            if path.startswith("/run/"):
                slug = path[5:]
                start(slug)
                return self.send(303, "", loc=f"/v/{slug}")
            if path.startswith("/gate/"):
                slug = path[6:]
                pipeline.gate(slug, f.get("decision", ""), f.get("note", ""))
                report.write(slug)
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

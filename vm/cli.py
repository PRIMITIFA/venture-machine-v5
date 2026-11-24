"""Command line: python vm.py <command> ...  (run `python vm.py help`)"""
import argparse
import sys

from . import ai, pdf, pipeline, report, seo, store
from .config import ROOT, S, load_env


def cmd_new(a):
    slug = pipeline.new(a.idea, a.source or "", a.country, a.lang, a.slug)
    print(f"created '{slug}'. Next: python vm.py run {slug}")
    if a.run:
        cmd_run(argparse.Namespace(slug=slug))


def cmd_run(a):
    st = pipeline.run(a.slug)
    p = report.write(a.slug)
    print(f"\nstatus: {st} | spent ${store.spent(a.slug):.2f} | report: {p}")


def cmd_gate(a):
    print(pipeline.gate(a.slug, a.decision, " ".join(a.note)))
    report.write(a.slug)


def cmd_list(a):
    vs = store.ventures()
    if not vs:
        print("no ventures yet. python vm.py new \"people who ... want ... and would pay for ...\"")
    for v in vs:
        done = sum(1 for b in store.blocks(v["slug"]).values() if b["status"] == "VALIDATED")
        print(f"{v['slug']:40} {v['status']:18} {done:2}/18  ${store.spent(v['slug']):.2f}  {v['one_liner'] or v['idea']}"[:180])


def cmd_show(a):
    v = store.venture(a.slug)
    if not v:
        sys.exit(f"no venture '{a.slug}'")
    print(f"{v['slug']} | {v['status']} | {v['country']}/{v['lang']} | spent ${store.spent(a.slug):.2f}\n{v['one_liner'] or v['idea']}\n")
    bl = store.blocks(a.slug)
    for b in pipeline.registry():
        st = bl.get(b.id, {"status": "PENDING", "verdict": "", "summary": "", "error": ""})
        tail = (st.get("summary") or "").split("\n")[0] + (f" | {st['error']}" if st.get("error") else "")
        print(f" {b.id} {b.name[:32]:32} {st['status']:9} {st.get('verdict') or '':5} {tail}"[:200])


def cmd_rerun(a):
    pipeline.rerun(a.slug, a.block)
    print(f"block {a.block} and later blocks reset. Run: python vm.py run {a.slug}")


def cmd_report(a):
    print(report.write(a.slug))


def cmd_pdf(a):
    f, msg = pdf.write(a.slug)
    print(f if f else msg)


def cmd_doctor(a):
    print(f"data folder : {S.data_dir}")
    print(f"AI provider : {ai.provider()}  (smart={S.model_smart}, fast={S.model_fast})")
    if seo.available():
        try:
            print(f"DataForSEO  : ok, balance ${seo.balance():.2f}")
        except Exception as e:
            print(f"DataForSEO  : ERROR {e}")
    else:
        print("DataForSEO  : not set (DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD). Phases 2-3 need it.")
    print(f"caps        : ${S.max_usd_per_idea:.2f} per idea, ${S.phase1_max_usd:.2f} for phase 1")
    try:
        import playwright  # noqa: F401
        print("screenshots : playwright installed")
    except ImportError:
        print("screenshots : off (optional: pip install playwright && playwright install chromium)")
    print(f"PDF         : {'playwright' if 'playwright' in sys.modules else (pdf.find_browser() or 'no browser found: open findings.html and print to PDF')}")
    print(f"house rules : {'house_rules.md' if (ROOT / 'house_rules.md').exists() else 'house_rules.example.md (copy it to house_rules.md and edit)'}")


def cmd_ui(a):
    from .ui import serve
    serve(a.port)


def main(argv=None):
    load_env()
    p = argparse.ArgumentParser(prog="vm", description="The Venture Machine v5, phases 1-4 (blocks 01-18).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new", help="add an idea")
    s.add_argument("idea")
    s.add_argument("--source", help="link the idea came from")
    s.add_argument("--country", default="us", help="target country code (us, gb, de, lt...) or a Google location code")
    s.add_argument("--lang", help="language code (default: from country)")
    s.add_argument("--slug")
    s.add_argument("--run", action="store_true", help="start running right away")
    s.set_defaults(f=cmd_new)
    s = sub.add_parser("run", help="run blocks until the next owner gate")
    s.add_argument("slug")
    s.set_defaults(f=cmd_run)
    s = sub.add_parser("gate", help="owner decision: go | kill | pivot | test | override")
    s.add_argument("slug")
    s.add_argument("decision", choices=["go", "kill", "pivot", "test", "override"])
    s.add_argument("note", nargs="*")
    s.set_defaults(f=cmd_gate)
    sub.add_parser("list", help="all ventures").set_defaults(f=cmd_list)
    s = sub.add_parser("show", help="block-by-block status")
    s.add_argument("slug")
    s.set_defaults(f=cmd_show)
    s = sub.add_parser("rerun", help="reset a block and everything after it")
    s.add_argument("slug")
    s.add_argument("block")
    s.set_defaults(f=cmd_rerun)
    s = sub.add_parser("report", help="write ventures/<slug>/report.html")
    s.add_argument("slug")
    s.set_defaults(f=cmd_report)
    s = sub.add_parser("pdf", help="write ventures/<slug>/<slug>-findings.pdf (everything it found out)")
    s.add_argument("slug")
    s.set_defaults(f=cmd_pdf)
    sub.add_parser("doctor", help="check keys, balance and setup").set_defaults(f=cmd_doctor)
    s = sub.add_parser("ui", help="local web app on http://127.0.0.1:8765")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(f=cmd_ui)
    a = p.parse_args(argv)
    a.f(a)

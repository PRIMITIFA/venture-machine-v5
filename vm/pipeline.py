"""The 28-block chain (this repo runs phases 1-4 = blocks 01-18), its state machine and the owner gates.

Block states: PENDING -> RUNNING -> VALIDATED | RETRY -> ALERT
Block verdicts: pass | warn (continue, noted) | redo (retry, max 2) | kill (stop; owner must confirm or override)
"""
import json
import traceback
from dataclasses import dataclass, field

from . import budget, store
from .config import S, location_code


@dataclass
class Result:
    verdict: str  # pass | warn | redo | kill
    summary: str
    data: dict = field(default_factory=dict)


@dataclass
class Block:
    id: str
    name: str
    phase: int
    kind: str  # auto | gate
    run: object = None
    decisions: tuple = ()


class Ctx:
    """What a block gets: the venture, its folder, file helpers, codes and the last retry feedback."""

    def __init__(self, slug, feedback=""):
        self.slug = slug
        self.v = store.venture(slug)
        self.dir = S.ventures_dir / slug
        self.dir.mkdir(parents=True, exist_ok=True)
        self.feedback = feedback
        self.loc = location_code(self.v["country"])
        self.lang = self.v["lang"]
        self.pivot = self.v.get("pivot_note") or ""

    def path(self, name):
        return self.dir / name

    def write(self, name, content):
        p = self.path(name)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, indent=1)
        p.write_text(content, encoding="utf-8")
        return p

    def read(self, name, default=None):
        p = self.path(name)
        if not p.exists():
            if default is not None:
                return default
            raise FileNotFoundError(f"{name} missing: run the earlier block first")
        t = p.read_text(encoding="utf-8")
        return json.loads(t) if name.endswith(".json") else t

    def has(self, name):
        return self.path(name).exists()

    def note(self):
        """Extra instructions for the AI: the pivot decision and the last retry feedback."""
        out = ""
        if self.pivot:
            out += f"\n\nOWNER PIVOT DECISION (narrow everything to this): {self.pivot}"
        if self.feedback:
            out += f"\n\nYOUR PREVIOUS ATTEMPT FAILED THE TEST: {self.feedback}. Fix exactly that."
        return out


def registry():
    from .blocks import phase1, phase2, phase3, phase4, gates
    return [
        Block("01", "Idea + duplicate check", 1, "auto", phase1.b01_intake),
        Block("02", "Business, data and E-E-A-T", 1, "auto", phase1.b02_how_eeat),
        Block("03", "Niche alive or dead", 1, "auto", phase1.b03_niche_pulse),
        Block("04", "ICE score + MVP effort", 1, "auto", phase1.b04_ice),
        Block("05", "GATE 1: Go / Kill", 1, "gate", gates.memo1, ("go", "kill")),
        Block("06", "Seeds (30-60 keywords)", 2, "auto", phase2.b06_seeds),
        Block("07", "Volume, CPC, cleaning", 2, "auto", phase2.b07_volumes),
        Block("08", "Top-20 SERP + clusters", 2, "auto", phase2.b08_serp_clusters),
        Block("09", "KD, shortlist, top-5 competitors", 2, "auto", phase2.b09_shortlist),
        Block("10", "Top-5 UX audit", 3, "auto", phase3.b10_ux),
        Block("11", "Prices, models, ads", 3, "auto", phase3.b11_business),
        Block("12", "Market size + buyers", 3, "auto", phase3.b12_market),
        Block("13", "SEO + link gap", 3, "auto", phase3.b13_links),
        Block("14", "GATE 2: Market gap?", 3, "gate", gates.memo2, ("go", "pivot", "kill")),
        Block("15", "Tools, costs, guardrails", 4, "auto", phase4.b15_costs),
        Block("16", "Unit economics + SWOT", 4, "auto", phase4.b16_economics),
        Block("17", "Product, sitemap, 90-day SEO", 4, "auto", phase4.b17_plan),
        Block("18", "GATE 3: Kill / Test / Go", 4, "gate", gates.memo3, ("kill", "test", "go")),
    ]


def by_id():
    return {b.id: b for b in registry()}


def new(idea, source="", country="us", lang=None, slug=None):
    from .util import slugify
    from .config import COUNTRY_LANG
    location_code(country)  # validates
    slug = slug or slugify(idea)
    base, i = slug, 2
    while store.venture(slug):
        slug, i = f"{base}-{i}", i + 1
    store.create_venture(slug, idea, source, country.lower(), (lang or COUNTRY_LANG.get(country.lower(), "en")))
    store.log(slug, "new", idea)
    return slug


def _run_block(b, slug, say):
    st = store.block(slug, b.id)
    attempts = st.get("attempts", 0)
    feedback = ""
    while True:
        attempts += 1
        store.set_block(slug, b.id, status="RUNNING", attempts=attempts, started=store.now(), error="")
        budget.CURRENT.update(slug=slug, block=b.id)
        say(f"[{b.id}] {b.name} ...")
        try:
            res = b.run(Ctx(slug, feedback))
        except budget.BudgetExceeded as e:
            store.set_block(slug, b.id, status="ALERT", error=str(e), finished=store.now())
            store.update_venture(slug, status="alert")
            store.log(slug, "alert", f"{b.id}: {e}")
            say(f"[{b.id}] STOPPED (budget): {e}")
            return False
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            store.log(slug, "error", f"{b.id}: {err}\n{traceback.format_exc()[-1500:]}")
            if attempts < 2:
                store.set_block(slug, b.id, status="RETRY", error=err)
                say(f"[{b.id}] error, retrying: {err}")
                feedback = ""
                continue
            store.set_block(slug, b.id, status="ALERT", error=err, finished=store.now())
            store.update_venture(slug, status="alert")
            say(f"[{b.id}] ALERT: {err}")
            return False
        finally:
            budget.CURRENT.update(slug=None, block=None)
        store.log(slug, res.verdict, f"{b.id}: {res.summary}")
        if res.verdict in ("pass", "warn"):
            store.set_block(slug, b.id, status="VALIDATED", verdict=res.verdict, summary=res.summary, finished=store.now())
            say(f"[{b.id}] {res.verdict.upper()}: {res.summary}")
            return True
        if res.verdict == "redo":
            if attempts < 3:
                store.set_block(slug, b.id, status="RETRY", verdict="redo", summary=res.summary)
                say(f"[{b.id}] REDO: {res.summary}")
                feedback = res.summary
                continue
            store.set_block(slug, b.id, status="ALERT", verdict="redo", summary=res.summary, error="failed its test 3 times", finished=store.now())
            store.update_venture(slug, status="alert")
            say(f"[{b.id}] ALERT: failed its test 3 times: {res.summary}")
            return False
        # kill
        store.set_block(slug, b.id, status="ALERT", verdict="kill", summary=res.summary, finished=store.now())
        store.update_venture(slug, status="kill_recommended")
        say(f"[{b.id}] KILL recommended: {res.summary}\n  -> confirm: vm gate {slug} kill   |   continue anyway: vm gate {slug} override \"why\"")
        return False


def run(slug, say=print, stop_at_gate=True):
    """Run blocks in order until a gate needs the owner, a block stops, or phase 4 is done."""
    v = store.venture(slug)
    if not v:
        raise SystemExit(f"no venture '{slug}'")
    if v["status"] in ("killed",):
        say(f"{slug} is killed.")
        return v["status"]
    if v["status"] in ("kill_recommended",):
        say(f"{slug} waits for you: a block recommends KILL. vm gate {slug} kill | vm gate {slug} override \"why\"")
        return v["status"]
    store.update_venture(slug, status="running")
    for b in registry():
        st = store.block(slug, b.id)
        if st["status"] == "VALIDATED":
            continue
        if b.kind == "gate":
            memo = b.run(Ctx(slug))
            store.set_block(slug, b.id, status="WAITING", summary=memo.summary)
            store.update_venture(slug, status=f"gate_{b.id}")
            say(f"\n=== {b.name} ===\n{memo.summary}\n\nDecide: " + " | ".join(f"vm gate {slug} {d}" for d in b.decisions))
            return f"gate_{b.id}"
        if not _run_block(b, slug, say):
            return store.venture(slug)["status"]
    store.update_venture(slug, status="phase4_done")
    return "phase4_done"


PIVOT_RESET = ["06", "07", "08", "09", "10", "11", "12", "13", "14"]


def gate(slug, decision, note=""):
    """Owner decision. Works on the gate that is waiting, or 'kill'/'override' at any time."""
    v = store.venture(slug)
    if not v:
        raise SystemExit(f"no venture '{slug}'")
    decision = decision.lower()
    if decision == "kill":
        g = v["status"].removeprefix("gate_") if v["status"].startswith("gate_") else "any"
        store.add_gate(slug, g, "kill", note)
        store.update_venture(slug, status="killed")
        store.log(slug, "gate", f"KILL {note}")
        return "killed (kept in the archive so it is never re-pitched)"
    if decision == "override":
        if v["status"] not in ("kill_recommended", "alert"):
            raise SystemExit("override only works when a block stopped (kill_recommended or alert)")
        stopped = [b for b, st in store.blocks(slug).items() if st["status"] == "ALERT"]
        for b in stopped:
            st = store.block(slug, b)
            if st.get("verdict") == "kill":
                store.set_block(slug, b, status="VALIDATED", verdict="warn", summary=st["summary"] + f" | OWNER OVERRIDE: {note}")
            else:
                store.set_block(slug, b, status="PENDING", attempts=0, error="")
        store.add_gate(slug, ",".join(stopped), "override", note)
        store.update_venture(slug, status="active")
        return f"override noted; blocks {', '.join(stopped)} cleared. Run: vm run {slug}"
    if not v["status"].startswith("gate_"):
        raise SystemExit(f"{slug} is not waiting at a gate (status: {v['status']})")
    gid = v["status"].removeprefix("gate_")
    b = by_id()[gid]
    if decision not in b.decisions:
        raise SystemExit(f"gate {gid} takes: {', '.join(b.decisions)}")
    store.add_gate(slug, gid, decision, note)
    store.log(slug, "gate", f"{gid} {decision.upper()} {note}")
    if decision == "pivot":
        store.update_venture(slug, pivot_note=(note or "narrow to one country / B2B / a smaller segment"), status="active")
        store.reset_blocks(slug, PIVOT_RESET)
        return "pivot saved; phases 2-3 will re-run on the narrower target. Run: vm run " + slug
    if decision == "test":
        from .blocks.gates import plan_quick_test
        path = plan_quick_test(Ctx(slug))
        store.set_block(slug, gid, status="VALIDATED", verdict="warn", summary="QUICK TEST chosen")
        store.update_venture(slug, status="quick_test")
        return f"quick test planned ({path.name}). Thresholds are fixed; come back to gate 3 when it ends."
    store.set_block(slug, gid, status="VALIDATED", verdict="pass", summary=f"owner: {decision.upper()} {note}".strip())
    if gid == "18":
        store.update_venture(slug, status="approved_build")
        return "GO: approved for phase 5 (build). Your manual list is in OWNER-TODO.json."
    store.update_venture(slug, status="active")
    return f"{decision.upper()} saved. Run: vm run {slug}"


def rerun(slug, block_id):
    """Reset one block and everything after it (gates included)."""
    ids = [b.id for b in registry()]
    if block_id not in ids:
        raise SystemExit(f"unknown block {block_id}")
    store.reset_blocks(slug, ids[ids.index(block_id):])
    store.update_venture(slug, status="active")

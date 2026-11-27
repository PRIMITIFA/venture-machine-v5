"""The 28-block chain (this repo runs phases 1-4 = blocks 01-18), its state machine and the owner gates.

Block states: PENDING -> RUNNING -> VALIDATED | RETRY -> ALERT
Block verdicts: pass | warn (continue, noted) | fail (the block's own bar was missed: continue, shown in red and counted
against the idea) | redo (retry, max 2) | kill (stop; owner must confirm or override)

Every block has a version and a list of the blocks it reads from. When a rule changes (version bump or a changed setting),
the blocks that used the old rule and everything that reads from them are out of date: `vm run` re-runs them, and no
decision can be made on an out-of-date report.
"""
import json
import traceback
from dataclasses import dataclass, field

from . import budget, store
from .config import S, location_code


@dataclass
class Result:
    verdict: str  # pass | warn | fail | redo | kill
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

    def __init__(self, slug, feedback="", attempt=1):
        self.slug = slug
        self.attempt = attempt
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
        Block("05", "GATE 1: Go / Kill", 1, "gate", gates.memo1, ("go", "angle", "kill")),
        Block("06", "Seeds (30-60 keywords)", 2, "auto", phase2.b06_seeds),
        Block("07", "Volume, CPC, cleaning", 2, "auto", phase2.b07_volumes),
        Block("08", "Top-20 SERP + clusters", 2, "auto", phase2.b08_serp_clusters),
        Block("09", "KD, shortlist, top-5 competitors", 2, "auto", phase2.b09_shortlist),
        Block("10", "Top-5 UX audit", 3, "auto", phase3.b10_ux),
        Block("11", "Prices, models, ads", 3, "auto", phase3.b11_business),
        Block("12", "Market size + buyers", 3, "auto", phase3.b12_market),
        Block("13", "SEO, links + AI visibility", 3, "auto", phase3.b13_links),
        Block("14", "GATE 2: Market gap?", 3, "gate", gates.memo2, ("go", "pivot", "kill")),
        Block("15", "Tools, costs, guardrails", 4, "auto", phase4.b15_costs),
        Block("16", "Unit economics + SWOT", 4, "auto", phase4.b16_economics),
        Block("17", "Product, sitemap, 90-day SEO", 4, "auto", phase4.b17_plan),
        Block("18", "GATE 3: Kill / Test / Go", 4, "gate", gates.memo3, ("kill", "test", "go")),
    ]


def by_id():
    return {b.id: b for b in registry()}


def new(idea, source="", country="us", lang=None, slug=None, depth="full"):
    from .util import slugify
    from .config import COUNTRY_LANG, DEPTHS
    if depth not in DEPTHS:
        raise SystemExit(f"depth must be one of: {', '.join(DEPTHS)}")
    location_code(country)  # validates
    slug = slug or slugify(idea)
    base, i = slug, 2
    while store.venture(slug):
        slug, i = f"{base}-{i}", i + 1
    store.create_venture(slug, idea, source, country.lower(), (lang or COUNTRY_LANG.get(country.lower(), "en")))
    store.set_data(slug, depth=depth)
    store.log(slug, "new", f"[{depth}] {idea}")
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
            res = b.run(Ctx(slug, feedback, attempts))
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
        if res.verdict in ("pass", "warn", "fail"):
            store.set_block(slug, b.id, status="VALIDATED", verdict=res.verdict, summary=res.summary, finished=store.now())
            sigs = dict(store.venture(slug)["data"].get("block_sig") or {})
            sigs[b.id] = block_sig(b.id)
            store.set_data(slug, block_sig=sigs)
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
    from .config import ACTIVE, LIGHT_BLOCKS
    depth = v["data"].get("depth", "full")
    ACTIVE["depth"] = depth
    resync(slug)
    old = refresh(slug)
    if old:
        say("out of date (a rule or an earlier step changed), running again: " + ", ".join(old))
    store.update_venture(slug, status="running")
    for b in registry():
        st = store.block(slug, b.id)
        if st["status"] == "VALIDATED":
            continue
        if depth == "light" and b.id not in LIGHT_BLOCKS:
            if b.id == "05":  # no stop in a quick check
                store.set_block(slug, b.id, status="VALIDATED", verdict="pass", summary="skipped: quick check runs straight through")
                continue
            from .blocks.gates import light_memo
            memo = light_memo(Ctx(slug))
            store.update_venture(slug, status="light_done")
            say(f"\n=== Quick check result ===\n{memo.summary}\n\nNext: vm deepen {slug} full   (or: deep)   |   vm gate {slug} kill")
            return "light_done"
        if b.kind == "gate":
            memo = b.run(Ctx(slug))
            store.set_block(slug, b.id, status="WAITING", summary=memo.summary)
            store.update_venture(slug, status=f"gate_{b.id}")
            has_angle = bool(store.venture(slug)["data"].get("other_angle"))
            say(f"\n=== {b.name} ===\n{memo.summary}\n\nDecide: " + " | ".join(f"vm gate {slug} {d}" for d in b.decisions if d != "angle" or has_angle))
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
    if decision == "angle":
        return try_angle(slug, note)
    if not v["status"].startswith("gate_"):
        raise SystemExit(f"{slug} is not waiting at a gate (status: {v['status']})")
    if stale(slug):
        raise SystemExit(f"{slug}: steps {', '.join(stale(slug))} are out of date (a rule changed since they ran). "
                         f"Refresh first: vm run {slug}   (or stop the idea: vm gate {slug} kill)")
    problems = v["data"].get("consistency_problems") or []
    if v["status"] == "gate_18" and problems and decision in ("go", "test"):
        raise SystemExit(f"{slug}: the report is NOT CONSISTENT ({len(problems)} problems, first: {problems[0]}). "
                         f"Fix by re-running the plan: vm rerun {slug} 16 && vm run {slug}   (or stop the idea: vm gate {slug} kill)")
    gid = v["status"].removeprefix("gate_")
    b = by_id()[gid]
    if decision not in b.decisions:
        raise SystemExit(f"gate {gid} takes: {', '.join(b.decisions)}")
    against = _against(slug, v, gid, decision)
    if against:
        note = ("OVERRIDE: " + against + (" | owner: " + note if note else "")).strip()
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


def _against(slug, v, gid, decision):
    """If the owner's GO goes against what the machine recommended, say what was overridden ('' if nothing)."""
    if decision != "go":
        return ""
    d, bl = v["data"], store.blocks(slug)
    warned = lambda ids: [b for b in ids if bl.get(b, {}).get("verdict") in ("warn", "fail")]
    if gid == "05" and d.get("first_score100") is not None and d["first_score100"] < 60:
        return f"GO although the first-look score was WEAK ({d['first_score100']}/100)"
    if gid == "14" and warned(("07", "08", "09", "10", "11", "12", "13")):
        return "GO although these steps were below their bar: " + ", ".join(warned(("07", "08", "09", "10", "11", "12", "13")))
    rec = d.get("gate3_recommendation") or ""
    if gid == "18" and rec and not rec.startswith("FULL"):
        return f"GO although the recommendation was {rec.split(' (')[0]}"
    return ""


# ---------------- out-of-date steps ----------------
# bump a number when a block's rules change: every idea that ran the older version is then out of date from that block on
BLOCK_VERSIONS = {"03": 2, "10": 2, "11": 2, "12": 5, "13": 3, "16": 3, "17": 3}
# what each block reads from (a block is out of date when one of these was re-run or is itself out of date)
DEPS = {"02": ["01"], "03": ["01", "02"], "04": ["01", "02", "03"], "05": ["04"], "06": ["01", "02"], "07": ["06"], "08": ["07"],
        "09": ["08"], "10": ["09"], "11": ["09", "02"], "12": ["08", "09", "11"], "13": ["08", "09"], "14": ["10", "11", "12", "13"],
        "15": ["02", "11", "12", "13"], "16": ["15", "12", "08", "09", "04"], "17": ["16", "13", "12", "08"], "18": ["15", "16", "17"]}
GATES = ("05", "14", "18")


def block_sig(bid):
    """Version of a block's rules plus the settings its numbers depend on."""
    s = str(BLOCK_VERSIONS.get(bid, 1))
    if bid in ("12", "16", "17"):
        s += f"|{S.min_market_month:g}|{S.target_market_month:g}|{S.assumed_conversion:g}|{S.good_case_share:g}"
    return s


def stale(slug):
    """Blocks that are done but out of date: they ran under older rules, or read from a block that is out of date."""
    v = store.venture(slug)
    if not v or v["status"] == "killed":
        return []
    sigs, bl = v["data"].get("block_sig") or {}, store.blocks(slug)
    done = lambda b: bl.get(b, {}).get("status") == "VALIDATED" and not (bl[b].get("summary") or "").startswith("skipped")
    out = set()
    for b in registry():
        if b.kind == "gate" or not done(b.id):
            continue
        have = sigs.get(b.id) or "1"      # blocks from before signatures existed count as version 1
        want = block_sig(b.id)
        if (have != want and (b.id in sigs or BLOCK_VERSIONS.get(b.id, 1) > 1)) or any(d in out for d in DEPS.get(b.id, [])):
            out.add(b.id)
    return sorted(out)


def refresh(slug):
    """Reset the out-of-date blocks so the next run redoes them. Decisions already made at gates 1 and 2 stay; gate 3 is asked again."""
    old = stale(slug)
    if not old:
        return []
    ids = list(old)
    if store.block(slug, "18")["status"] != "PENDING":
        ids.append("18")
    store.reset_blocks(slug, ids)
    store.set_data(slug, consistency_problems=[])
    store.log(slug, "refresh", "out of date, reset: " + ", ".join(ids))
    return old


def resync(slug):
    """Rebuild the one-line results that are pure arithmetic on stored files (steps 03, 04 and 07), so they cannot lag behind the data or the rules."""
    import re
    from .blocks import phase1, phase2
    c = Ctx(slug)
    if store.block(slug, "08")["status"] == "VALIDATED":
        phase2.sync_kw_summary(c)
    st = store.block(slug, "03")
    if st["status"] == "VALIDATED" and c.has("04_niche_pulse.json"):
        new = re.sub(r"^(alive|flat|dying|unknown); 24-month trend [^;]*", lambda m: phase1.pulse_line(c.read("04_niche_pulse.json")), st.get("summary") or "")
        if new != st.get("summary"):
            store.set_block(slug, "03", summary=new)
    st = store.block(slug, "04")
    if st["status"] == "VALIDATED" and c.has("05_scorecard.json"):
        sc = c.read("05_scorecard.json")
        avg = phase1.first_avg(sc["ice"])
        verdict, summary = phase1.first_result(sc)
        if avg != sc.get("ice_avg"):
            c.write("05_scorecard.json", sc | {"ice_avg": avg})
            store.set_data(slug, ice_avg=avg, first_score100=round(avg * 10))
        if verdict != "kill" and (summary != st.get("summary") or verdict != st.get("verdict")):
            store.set_block(slug, "04", summary=summary, verdict=verdict)


def try_angle(slug, note=""):
    """Test the other angle from block 04 (or the owner's own words) as its own idea. The main idea is left as it is."""
    v = store.venture(slug)
    a = v["data"].get("other_angle") or {}
    idea = (note or a.get("idea") or "").strip()
    if not idea:
        raise SystemExit(f"no other angle found for {slug} yet (it appears after step 04). Or write your own: vm gate {slug} angle \"...\"")
    child = v["data"].get("angle_slug")
    if child and store.venture(child) and store.venture(child)["idea"] == idea:
        return f"the other angle is already saved as '{child}'. Run: vm run {child}"
    child = new(idea, v["source"], v["country"], v["lang"], f"{slug}-angle", depth=v["data"].get("depth", "full"))
    store.set_data(child, angle_of=slug, parent_score100=v["data"].get("first_score100"), parent_idea=v["one_liner"] or v["idea"])
    store.set_data(slug, angle_slug=child)
    store.add_gate(slug, v["status"].removeprefix("gate_") if v["status"].startswith("gate_") else "any", "angle", idea)
    store.log(slug, "gate", f"ANGLE -> {child}: {idea}")
    return f"other angle saved as its own idea '{child}'. Run: vm run {child}"


def deepen(slug, depth="full"):
    """Upgrade a quick check to a full or deep check (or a full check to deep). Data already fetched is re-used."""
    from .config import DEPTHS
    v = store.venture(slug)
    if not v:
        raise SystemExit(f"no venture '{slug}'")
    if depth not in ("full", "deep"):
        raise SystemExit("deepen to: full | deep")
    order = list(DEPTHS)
    cur = v["data"].get("depth", "full")
    if order.index(depth) <= order.index(cur):
        raise SystemExit(f"{slug} is already a {DEPTHS[cur]['label'].lower()}")
    store.set_data(slug, depth=depth)
    store.add_gate(slug, "05", "go", f"deepen to {depth}")
    store.set_block(slug, "05", status="VALIDATED", verdict="pass", summary=f"owner: GO (deepened to a {DEPTHS[depth]['label'].lower()})")
    ids = [b.id for b in registry()]
    store.reset_blocks(slug, ids[ids.index("06"):])
    store.update_venture(slug, status="active", pivot_note=v.get("pivot_note") or "")
    return f"{slug} is now a {DEPTHS[depth]['label'].lower()} ({DEPTHS[depth]['about']}). Run: vm run {slug}"


def rerun(slug, block_id):
    """Reset one block and everything after it (gates included)."""
    ids = [b.id for b in registry()]
    if block_id not in ids:
        raise SystemExit(f"unknown block {block_id}")
    store.reset_blocks(slug, ids[ids.index(block_id):])
    store.update_venture(slug, status="active")

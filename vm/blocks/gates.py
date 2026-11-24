"""Owner gates 1-3: a short memo, then the owner decides (CLI `vm gate` or the local UI)."""
from typing import Literal

from pydantic import BaseModel, Field

from .. import ai, store
from ..config import S
from ..pipeline import Result
from ..util import num, read_csv


def _spent(c):
    return f"spent so far ${store.spent(c.slug):.2f} of ${S.max_usd_per_idea:.2f}"


def memo1(c):
    sc = c.read("05_scorecard.json")
    e = c.read("03_eeat_quality.json")
    n = c.read("04_niche_pulse.json")
    eeat_ok = sum(1 for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example") if e[k]["ok"])
    lines = sc["summary_3_lines"] + [
        f"ICE {sc['ice_avg']} | MVP {sc['effort']['days_to_mvp']} days | ~${sc['effort']['monthly_cost_usd']}/mo | blockers: {', '.join(sc['blockers']) or 'none'}",
        f"E-E-A-T {eeat_ok}/4 ok, YMYL {e['ymyl_level']} | niche {n['status']} (24-mo trend {n.get('change_24m_pct_best')}%)",
        f"Biggest unknown: {sc['biggest_unknown']}", _spent(c)]
    return Result("pass", "\n".join(lines))


def memo2(c):
    biz = c.read("13_competitor_business.json")
    mk = c.read("14_market_analysis.json")
    seo_ = c.read("15_competitor_seo.json")
    ux = c.read("12_competitor_ux.json")
    prices = []
    for x in biz["competitors"]:
        known = [p for p in x["plans"] if p["price"] and "unknown" not in p["price"].lower()]
        prices.append(f"{x['domain']}: " + (", ".join(f"{p['name'][:60]} {p['price']}" for p in known[:3]) or "no price found (check by hand)"))
    lines = ["Competitor prices:"] + [f"  - {p}" for p in prices] + [
        f"Gap: {biz['identified_gap']}",
        f"Market: bottom-up ${mk['bottom_up_usd_year']:,.0f}/yr, top-down ${mk['top_down_usd_year']:,.0f}/yr (goal ${mk['year1_goal_usd']:,.0f})",
        "SEO strength: " + ", ".join(f"{s['domain']} DR {s['dr']} / {s['referring_domains']} RD" for s in seo_["competitors"]),
        "Underserved:"] + [f"  - {u[:220]}" for u in mk["underserved_countries_or_segments"][:4]]
    if ux.get("manual_review_at_gate2"):
        lines.append(f"Check by hand (blocked bots, ~2 min): {', '.join(ux['manual_review_at_gate2'])}")
    lines += ["Optional: one cheap test purchase from the #1 competitor.", _spent(c),
              "PIVOT = narrow to one country / B2B / smaller segment: vm gate <slug> pivot \"UK landlords only\""]
    return Result("pass", "\n".join(lines))


def gate3_scores(c):
    kws = read_csv(c.path("08_keywords_clean.csv"))
    buy = [k for k in kws if k["intent"] in ("buy", "competitor", "brand-model")]
    buy_vol = sum(num(k["volume"]) for k in buy)
    max_cpc = max([num(k["cpc"]) for k in buy] or [0])
    mk = c.read("14_market_analysis.json")
    ratio = mk["bottom_up_usd_year"] / max(mk["year1_goal_usd"], 1)
    short = read_csv(c.path("11_shortlist.csv"))
    easy = sum(1 for r in short if r["kd"] != "" and num(r["kd"]) <= 20) / max(len(short), 1)
    seo_ = c.read("15_competitor_seo.json")
    min_dr = min([num(s["dr"], 100) for s in seo_["competitors"]] or [100])
    clusters = c.read("10_clusters_serp.json")
    weak = sum(1 for cl in clusters if cl["weak_spots"]) / max(len(clusters), 1)
    fixed = c.v["data"].get("budget_caps", {}).get("fixed_cost_usd_month", 0)
    cost_share = fixed / max(mk["year1_goal_usd"] / 12, 1)

    def band(v, cuts):  # cuts for 5,4,3,2
        for s, cut in zip((5, 4, 3, 2), cuts):
            if v >= cut:
                return s
        return 1
    kd_dr = round((band(easy, (0.6, 0.4, 0.25, 0.1)) + (5 if min_dr < 20 else 4 if min_dr < 40 else 3 if min_dr < 60 else 2 if min_dr < 75 else 1)) / 2)
    s = {
        "demand": (band(buy_vol, (5000, 2000, 1000, 300)), f"buying volume {int(buy_vol)}/mo"),
        "value": (band(max_cpc, (5, 3, 2, 1)), f"top buying CPC ${max_cpc:.2f}"),
        "market": (band(ratio, (50, 20, 10, 3)), f"bottom-up = {ratio:.1f}x year-1 goal"),
        "kd_dr": (kd_dr, f"{easy:.0%} of shortlist KD<=20; weakest competitor DR {min_dr:.0f}"),
        "weak_spots": (band(weak, (0.5, 0.3, 0.2, 0.1)), f"{weak:.0%} of clusters have a weak spot"),
        "advantage": (int(c.v["data"].get("advantage_score") or 3), "block 17 edge score"),
        "costs": (5 if cost_share <= 0.05 else 4 if cost_share <= 0.10 else 3 if cost_share <= 0.20 else 2 if cost_share <= 0.40 else 1,
                  f"fixed ${fixed:.0f}/mo = {cost_share:.0%} of goal/month"),
    }
    avg = round(sum(v[0] for v in s.values()) / len(s), 2)
    return s, avg


def memo3(c):
    s, avg = gate3_scores(c)
    rec = "KILL" if avg < 3.0 else "QUICK TEST (7 days, capped)" if avg < 3.5 else "FULL BUILD"
    store.set_data(c.slug, gate3_score=avg, gate3_recommendation=rec)
    ue = c.v["data"].get("unit_economics", {})
    qs = c.read("16_owner_questions.md", default="")
    lines = [f"Score {avg}/5 -> recommendation: {rec}"] + [f"  {k:11} {v[0]}/5  {v[1]}" for k, v in s.items()] + [
        f"Model: {ue.get('model')} at ${ue.get('price_usd')} | net ${ue.get('net_per_sale')}/sale | max CAC ${ue.get('max_cac')}",
        "Answer the open questions in 16_owner_questions.md before GO." if "Answer: \n" in qs or qs.rstrip().endswith("Answer:") else "",
        _spent(c)]
    flags = []
    for bid, st in sorted(store.blocks(c.slug).items()):
        if st.get("verdict") == "warn" and bid not in ("05", "14", "18"):
            flags.append(f"  {bid} WARN: {(st.get('summary') or '')[:200]}")
    overrides = [g for g in store.gates(c.slug) if g["decision"] == "override"]
    if flags or overrides:
        extra = [f"  OVERRIDDEN kill at block {g['gate']}: {g['note']}" for g in overrides] + flags
        lines[1:1] = ["Read before deciding:"] + extra
    c.write("18_gate3_memo.md", "# Gate 3 memo\n\n" + "\n".join(lines))
    return Result("pass", "\n".join(l for l in lines if l))


# ---------------- Quick test (gate 3 'test' branch, Appendix A) ----------------
class QuickTest(BaseModel):
    test: Literal["search-demand", "smoke-page", "fake-door", "pre-sale", "ads-test", "cold-email", "price-test", "seo-test", "channel-test"]
    why: str
    setup_steps: list[str]
    budget_usd: float = Field(le=150)
    days: int = Field(le=14)
    pass_threshold: str
    kill_threshold: str


MENU = """search-demand: keyword API only (~$1, 10 min) - pass >= 1,000 buying searches/mo or CPC >= $2
smoke-page: 1 page, 1 promise, 1 button, collect emails ($70-140, 5-7 d) - pass 5-15% sign-up from paid search
fake-door: 'Buy for $X' -> honest 'coming soon, get notified' ($100-300, 7 d) - pass 1-3% clicks
pre-sale: real refundable payment for early access ($100-300) - pass >= 5 paying customers
ads-test: exact buying keywords, 3 ad groups, capped ($300, 14 d) - pass CPA <= max CAC
cold-email: 100-300 emails to a public B2B list (~$0, 7 d) - pass >= 3% positive replies
price-test: two prices 50/50 on live traffic - pass = higher profit per visitor
seo-test: 10-20 unique pages on low-KD keywords (time, 4-6 weeks) - pass indexed + impressions growing
channel-test: any new channel, 14 d, capped (max $100) - pass matches block 16 economics"""


def plan_quick_test(c):
    how = c.read("02_how_analysis.json")
    ue = c.v["data"].get("unit_economics", {})
    out = ai.ask_json(
        f"""Gate 3 chose QUICK TEST for: {c.v['one_liner']}
Pick the cheapest test from the menu that answers the validation question: "{how['validation_question']}".
Budget <= $150, <= 14 days. Write pass and kill thresholds NOW; they will not change after results.
Menu:
{MENU}""",
        QuickTest, smart=False, context={"unit_economics": ue})
    p = c.write("20_quick_test.md", f"""# Quick test: {out.test}
Written {store.now()}. Thresholds are fixed and must not change after results.

- Why: {out.why}
- Budget: ${out.budget_usd} | Days: {out.days}
- PASS if: {out.pass_threshold}
- KILL if: {out.kill_threshold} (stop spending at once)

## Setup
{chr(10).join(f'{i}. {s}' for i, s in enumerate(out.setup_steps, 1))}

When it ends: `vm rerun {c.slug} 18` and decide again.
""")
    return p

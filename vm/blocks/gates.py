"""Owner gates 1-3: a short memo, then the owner decides (CLI `vm gate` or the local UI)."""
from typing import Literal

from pydantic import BaseModel, Field

from .. import ai, store
from ..config import S
from ..pipeline import Result
from ..util import buy_volume, is_buy, num, read_csv, volume_split, weighted_cpc


def _spent(c):
    from ..config import cap_usd
    return f"spent so far ${store.spent(c.slug):.2f} of ${cap_usd(c.v['data'].get('depth', 'full')):.2f}"


_FIRST_ALL = {"impact": "How much money could it make?", "confidence": "How sure are we it will work?", "ease": "How easy is it to build and sell?"}


def first_questions():
    """The first-look questions that count. Build effort is left out unless VM_COUNT_BUILD_EFFORT=1."""
    from .phase1 import first_keys
    return {k: _FIRST_ALL[k] for k in first_keys()}
FIRST_PASS = 60  # first-look score out of 100; under this the idea is weak as written


def first_scores(c):
    """The phase 1 (first look) score: 3 checks. Values are on the same 1-5 scale as the other scorecards (shown x2 = out of 10)."""
    sc = c.read("05_scorecard.json", default=None)
    if not sc:
        return None, None
    ice = sc["ice"]
    fallback = {"impact": "how big the win could be (AI judgement from what phase 1 found)",
                "confidence": "how sure the evidence makes us (AI judgement)", "ease": "how easy it is to build and to sell (AI judgement)"}
    s = {k: (ice[k] / 2, (ice.get(k + "_why") or fallback[k])[:220]) for k in first_questions()}
    return s, round(sum(v[0] for v in s.values()) / len(s), 2)


def other_angle(c_or_v):
    """The other angle from block 04, or None."""
    v = c_or_v.v if hasattr(c_or_v, "v") else c_or_v
    a = v["data"].get("other_angle")
    return a if a and a.get("idea") else None


def memo1(c):
    sc = c.read("05_scorecard.json")
    e = c.read("03_eeat_quality.json")
    n = c.read("04_niche_pulse.json")
    eeat_ok = sum(1 for k in ("real_person_or_company", "expertise_proof", "unique_data_per_page", "contacts_policies_real_example") if e[k]["ok"])
    score = round(sc["ice_avg"] * 10)
    ang = sc.get("other_angle")
    head = [f"First-look score {score}/100 -> " + ("GOOD ENOUGH: worth the paid research" if score >= FIRST_PASS else
                                                    "WEAK as written" + (": test the other angle" if ang else ""))]
    fq = first_questions()
    head += [f"  {fq[k]:34} {sc['ice'][k]:>2}/10  {sc['ice'].get(k + '_why', '')}".rstrip() for k in fq]
    if ang:
        head += ["Other angle that could work: " + ang["idea"], "  Why: " + ang["why"], "  Cheapest test: " + ang["cheapest_test"],
                 f"  Check it (about 1 cent): vm gate {c.slug} angle"]
    if c.v["data"].get("angle_of"):
        head.append(f"This idea is the other angle of '{c.v['data']['angle_of']}' (that one scored {c.v['data'].get('parent_score100', '?')}/100).")
    lines = head + sc["summary_3_lines"] + [
        f"First look {sc['ice_avg']} of 10 | build about {sc['effort']['days_to_mvp']} days{'' if S.count_build_effort else ' (not counted)'} | ~${sc['effort']['monthly_cost_usd']}/mo | blockers: {', '.join(sc['blockers']) or 'none'}",
        f"E-E-A-T {eeat_ok}/4 ok, YMYL {e['ymyl_level']} | niche {n['status']} (" + (f"24-mo trend {n['change_24m_pct_best']}%" if n.get('change_24m_pct_best') is not None else "not enough search history for a trend") + ")",
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
        f"Market: bottom-up ${mk['bottom_up_usd_year']:,.0f}/yr, top-down ${mk['top_down_usd_year']:,.0f}/yr (smallest worth building: ${S.min_market_month:,.0f}/mo; we want ${S.target_market_month:,.0f}+/mo)",
        "SEO strength: " + ", ".join(f"{s['domain']} DR {s['dr']} / {s['referring_domains']} RD" for s in seo_["competitors"]),
        "Underserved:"] + [f"  - {u[:220]}" for u in mk["underserved_countries_or_segments"][:4]]
    if ux.get("manual_review_at_gate2"):
        lines.append(f"Check by hand (blocked bots, ~2 min): {', '.join(ux['manual_review_at_gate2'])}")
    lines += ["Optional: one cheap test purchase from the #1 competitor.", _spent(c),
              "PIVOT = narrow to one country / B2B / smaller segment: vm gate <slug> pivot \"UK landlords only\""]
    return Result("pass", "\n".join(lines))


def gate3_scores(c):
    kws = read_csv(c.path("08_keywords_clean.csv"))
    buy = [k for k in kws if is_buy(k)]
    buy_vol = buy_volume(kws)          # commercial searches in full, a rival's bare brand name at 10%
    sp = volume_split(kws)
    w_cpc = weighted_cpc(kws)          # averaged by volume, so one tiny expensive keyword cannot carry the score
    max_cpc = max([num(k["cpc"]) for k in buy] or [0])
    mk = c.read("14_market_analysis.json")
    bottom_up = market_at_chosen_price(c, mk)
    month, target = bottom_up / 12, S.target_market_month
    # a rival's own name is not an easy search for us (that rival holds the top spot), so it is left out of the ranking score
    short = [r for r in read_csv(c.path("11_shortlist.csv")) if r.get("intent") != "brand"]
    easy = sum(1 for r in short if r["kd"] != "" and 0 < num(r["kd"]) <= 20) / max(len(short), 1)   # 0 = not measured, never "easy"
    seo_ = c.read("15_competitor_seo.json")
    direct = [s for s in seo_["competitors"] if s.get("kind", "direct") == "direct" and s.get("dr") is not None]
    min_dr = min([num(s["dr"], 100) for s in direct] or [100])
    clusters = c.read("10_clusters_serp.json")
    weak = sum(1 for cl in clusters if cl["weak_spots"]) / max(len(clusters), 1)
    ads_seen = sum(num((cl.get("features") or {}).get("paid")) for cl in clusters) + num((c.read("04_niche_pulse.json", default={}) or {}).get("ads_on_top_term"))
    caps = c.v["data"].get("budget_caps", {})
    fixed = (c.v["data"].get("offer") or {}).get("fixed_cost_usd_month") or caps.get("fixed_cost_usd_month", 0)  # for the chosen offer
    cost_share = fixed / max(S.min_market_month, 1)  # fixed dollar bands: $50 / $100 / $200 / $400 a month at the default

    def band(v, cuts):  # cuts for 5,4,3,2
        for s, cut in zip((5, 4, 3, 2), cuts):
            if v >= cut:
                return s
        return 1
    kd_dr = round((band(easy, (0.6, 0.4, 0.25, 0.1)) + (5 if min_dr < 20 else 4 if min_dr < 40 else 3 if min_dr < 60 else 2 if min_dr < 75 else 1)) / 2)
    # easy rankings are only worth something if people search: a small niche cannot score top marks for being empty
    small = buy_vol < 300
    rank_cap = 3 if small else 4 if buy_vol < 1000 else 5
    kd_note = "" if kd_dr <= rank_cap else " Capped: easy to rank, but only %s buying searches a month, so the prize is small." % "{:,}".format(int(buy_vol))
    value = band(w_cpc, (5, 3, 2, 1))
    value_note = f"advertisers pay about ${w_cpc:.2f} per click on average across the buying searches (want $2+; the single highest is ${max_cpc:.2f})"
    if value > 3 and not ads_seen:
        value, value_note = 3, value_note + ". Capped: no advertiser was seen on any of these searches, so the click price is not proven."
    adv_reason = (c.v["data"].get("advantage_reason") or "").strip()
    weak_s = min(band(weak, (0.5, 0.3, 0.2, 0.1)), 4 if small else 5)
    s = {
        "demand": (band(buy_vol, (5000, 2000, 1000, 300)),
                   f"{int(buy_vol):,} buying searches a month (want 1,000+): {sp['commercial']:,} commercial, plus 10% of {sp['brand']:,} searches for a rival's name; {sp['info']:,} learning searches not counted"),
        "value": (value, value_note),
        "market": (market_score(month), f"about ${month:,.0f} a month is reachable through Google search. We want ${target:,.0f}+ a month, and under ${S.min_market_month:,.0f} is too small"),
        "kd_dr": (min(kd_dr, rank_cap), f"{easy:.0%} of the best searches are easy to rank for; weakest direct rival has strength {min_dr:.0f}/100.{kd_note}"),
        "weak_spots": (weak_s, f"rivals are weak on {weak:.0%} of the page topics"),
        "advantage": (int(c.v["data"].get("advantage_score") or 3), adv_reason[:200] or "how much better we can be than the rivals (AI judgement)"),
        "costs": (5 if cost_share <= 0.05 else 4 if cost_share <= 0.10 else 3 if cost_share <= 0.20 else 2 if cost_share <= 0.40 else 1,
                  f"about ${fixed:.0f} a month to run the chosen offer (want under ${S.min_market_month * 0.05:,.0f} a month)"),
    }
    ps = proof_score(c)
    if ps:
        s["proof"] = ps
    # geometric mean: one very low score pulls the whole result down instead of hiding behind the high ones
    prod = 1.0
    for v in s.values():
        prod *= max(v[0], 1)
    avg = round(prod ** (1 / len(s)), 2)
    return s, avg


def proof_score(c):
    """Do real businesses earn here? Scored from payment-verified revenue of comparable businesses (02_proof.json).
    The other checks measure free Google search; this one is the evidence that the niche pays through ANY channel.
    Returns None when the proof was not checked, so an unchecked idea is neither helped nor hurt."""
    pr = c.read("02_proof.json", default=None)
    if not pr or not pr.get("checked"):
        return None
    comps = [x for x in pr.get("comparables") or [] if x.get("closeness", 1) >= 2]
    if not comps:
        return 2, "no business with payment-verified revenue was found in this niche (the database only holds founders who chose to list)"
    best = max(comps, key=lambda x: x["revenue_30d_usd"])
    rev = best["revenue_30d_usd"]
    sc = 5 if rev >= 30000 else 4 if rev >= 10000 else 3 if rev >= 5000 else 2 if rev >= 1000 else 1
    same = best.get("closeness") == 3
    if not same:   # the same kind of product in another niche is weaker proof than a business in this exact niche
        sc = max(1, sc - 1)
    return sc, (f"{best['name']} made ${rev:,.0f} in the last 30 days (payment-verified)" +
                (", in this same niche" if same else ", selling the same kind of product in a neighbouring niche, so it counts one step lower") +
                (f"; it charges {best['price'][:70]}" if best.get("price") else ""))


def market_score(month):
    """Score 1-5 (shown x2) for the money reachable through Google search a month. One scale, written in docs/BLOCKS.md:
    under 0.3x the target = 1 | 0.3x = 2 | the target = 3 | 2x = 4 | 5x or more = 5   (target default $10,000 a month)."""
    t = S.target_market_month
    return 5 if month >= 5 * t else 4 if month >= 2 * t else 3 if month >= t else 2 if month >= 0.3 * t else 1


def market_at_chosen_price(c, mk):
    """The search market at the price the business case actually chose (one price for market, economics and plan)."""
    from ..checks import market_year
    return market_year(c, mk)


def knockouts(c):
    """Rules that decide on their own, whatever the average says. Returns (forced recommendation or None, note)."""
    mk = c.read("14_market_analysis.json")
    market = market_at_chosen_price(c, mk)
    month, floor, target = market / 12, S.min_market_month, S.target_market_month
    best = c.v["data"].get("proof_best_30d") or 0
    if month < target and best >= S.proof_min_usd:
        return "QUICK TEST (7 days, capped)", (f"Capped at TEST: only about ${month:,.0f} a month is reachable through Google search, but a real business in this niche "
                                               f"made ${best:,.0f} in the last 30 days (payment-verified). The niche pays; search alone does not carry it. "
                                               "Test the channel that business uses (see the revenue proof) before building.")
    if month < floor:
        return "KILL", (f"Knock-out: only about ${month:,.0f} a month (${market:,.0f} a year) is reachable through Google search, even if you took all of it. "
                        f"Under ${floor:,.0f} a month is too small to build for. As a search business this is a KILL. "
                        "Only another channel (for example cold email) could carry it; test that as its own idea.")
    if month < target:
        return "QUICK TEST (7 days, capped)", (f"Capped at TEST: about ${month:,.0f} a month is reachable through Google search. "
                                               f"Between ${floor:,.0f} and ${target:,.0f} a month the most an idea can get is a cheap test first.")
    return None, ""


def memo3(c):
    s, avg = gate3_scores(c)
    rec = "KILL" if avg < 3.0 else "QUICK TEST (7 days, capped)" if avg < 3.5 else "FULL BUILD"
    # safety rule: good scores but a forecast below the smallest size worth building is not a full build
    fc = (c.v["data"].get("forecast_12m_usd") or {}).get("mid")
    cap_note = ""
    if rec == "FULL BUILD" and fc is not None and fc < S.min_market_usd:
        rec = "QUICK TEST (7 days, capped)"
        cap_note = f"Capped at TEST: the likely first-year sales (${fc:,.0f}) are about ${fc / 12:,.0f} a month, under the ${S.min_market_usd / 12:,.0f} a month that makes a full build worth it."
    forced, ko = knockouts(c)
    if forced == "KILL" or (forced and rec == "FULL BUILD"):
        rec, cap_note = forced, ko
    from .. import checks, pipeline
    pipeline.resync(c.slug)
    problems = checks.consistency(c)
    store.set_data(c.slug, gate3_score=avg, gate3_score100=round(avg * 20), gate3_recommendation=rec, gate3_cap_note=cap_note, consistency_problems=problems)
    ue = c.v["data"].get("unit_economics", {})
    qs = c.read("16_owner_questions.md", default="")
    lines = [f"Score {round(avg * 20)}/100 -> recommendation: {rec}" + (f" ({cap_note})" if cap_note else "")] + [f"  {k:11} {v[0] * 2:>2}/10  {v[1]}" for k, v in s.items()] + [
        f"Model: {ue.get('model')} at ${ue.get('price_usd')} | net ${ue.get('net_per_sale')}/sale | max CAC ${ue.get('max_cac')}",
        "Answer the open questions in 16_owner_questions.md before GO." if "Answer: \n" in qs or qs.rstrip().endswith("Answer:") else "",
        _spent(c)]
    flags = []
    for bid, st in sorted(store.blocks(c.slug).items()):
        if st.get("verdict") in ("warn", "fail") and bid not in ("05", "14", "18"):
            flags.append(f"  {bid} {'FAILED ITS BAR' if st['verdict'] == 'fail' else 'WARN'}: {(st.get('summary') or '')[:200]}")
    bl = store.blocks(c.slug)
    overrides = [g for g in store.gates(c.slug) if g["decision"] == "override"
                 and any("OWNER OVERRIDE" in (bl.get(b, {}).get("summary") or "") for b in g["gate"].split(","))]
    if flags or overrides:
        extra = [f"  OVERRIDDEN kill at block {g['gate']}: {g['note']}" for g in overrides] + flags
        lines[1:1] = ["Read before deciding:"] + extra
    if problems:
        lines[0:0] = [f"NOT CONSISTENT: {len(problems)} places in this report disagree with each other. GO and TEST are switched off until it is fixed "
                      f"(vm rerun {c.slug} 16, then vm run {c.slug}). KILL still works."] + [f"  ! {p}" for p in problems[:12]]
    spin = c.v["data"].get("spin_off")
    if spin:
        lines.append(f"A different business was set aside (not researched here): {spin['idea']}. Run it as its own idea: vm new \"{spin['idea']}\"")
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
    t = (c.v["data"].get("offer") or {}).get("test")
    if t:  # the one validation test written with the business case: same numbers in every part of the report
        return c.write("20_quick_test.md", f"""# Quick test: {t['test']}
Written {store.now()}. Thresholds are fixed and must not change after results.

- Why: {t['why']}
- Who and how many: {t['sample']}
- Budget: ${t['budget_usd']:g} | Days: {t['days']}{f" (after {t['warmup_days']} days of warm-up)" if t.get('warmup_days') else ''} | Price shown: ${t['price_usd']:g}
- PASS if: {t['pass_threshold']}
- KILL if: {t['kill_threshold']} (stop spending at once)

## Setup
{chr(10).join(f'{i}. {s}' for i, s in enumerate(t['setup_steps'], 1))}

When it ends: `vm rerun {c.slug} 18` and decide again.
""")
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


# ---------------- Quick check (light depth) ----------------
LIGHT_QUESTIONS = {
    "demand": "Do people search for it?", "value": "Are buyers worth money?", "paying": "Do people already pay for this?",
    "rank": "Can a new site get onto Google?", "alive": "Is the market alive?", "effort": "Is it worth the effort?",
}


def light_scores(c):
    """6 checks, each 1-5, from what a quick check knows (no rival deep-dive yet)."""
    def band(v, cuts):
        for s_, cut in zip((5, 4, 3, 2), cuts):
            if v >= cut:
                return s_
        return 1
    kws = read_csv(c.path("08_keywords_clean.csv")) if c.has("08_keywords_clean.csv") else []
    buy = [k for k in kws if is_buy(k)]
    buy_vol = buy_volume(kws)
    max_cpc = max([num(k["cpc"]) for k in buy] or [0])
    how = c.read("02_how_analysis.json", default={}) or {}
    priced = [x for x in how.get("competitors", []) if x.get("price") and "unknown" not in x["price"].lower()]
    pulse = c.read("04_niche_pulse.json", default={}) or {}
    ch = pulse.get("change_24m_pct_best")
    st_ = pulse.get("status")
    if st_ == "dying":
        alive = 1
    elif ch is not None and ch < -30:
        alive = 2
    elif ch is not None and ch < -10:
        alive = 3
    else:
        alive = 5 if st_ == "alive" else 2 if st_ == "unknown" else 3
    clusters = c.read("10_clusters_serp.json", default=[]) or []
    easy = sum(1 for cl in clusters[:15] if cl.get("kd") not in ("", None) and 0 < num(cl["kd"]) <= 30) / max(min(len(clusters), 15), 1)
    sc = c.read("05_scorecard.json", default={}) or {}
    ice = num(sc.get("ice_avg"), 5)
    s = {
        "demand": (band(buy_vol, (5000, 2000, 1000, 300)), f"{int(buy_vol):,} searches a month from people ready to buy (want 1,000+)"),
        "value": (band(max_cpc, (5, 3, 2, 1)), f"advertisers pay up to ${max_cpc:.2f} per click (want $2+)"),
        "paying": (5 if len(priced) >= 5 else 4 if len(priced) >= 3 else 3 if len(priced) == 2 else 2 if priced else 1,
                   f"{len(priced)} sites already charge money for this"),
        "rank": (band(easy, (0.6, 0.4, 0.25, 0.1)), f"{easy:.0%} of the top searches have easy or medium difficulty (30 or less)"),
        "alive": (alive, f"niche is {pulse.get('status', 'unknown')}" + (f", searches {ch:+.0f}% in 2 years" if ch is not None else "")),
        "effort": (max(1, min(5, round(ice / 2))), f"first-look score {ice}/10" + (f", first version in {(sc.get('effort') or {}).get('days_to_mvp', '?')} days" if S.count_build_effort else " (build time not counted)")),
    }
    avg = round(sum(v[0] for v in s.values()) / len(s), 2)
    return s, avg


def light_memo(c):
    s, avg = light_scores(c)
    score = round(avg * 20)
    rec = "WORTH A FULL CHECK" if score >= 70 else "MAYBE: FULL CHECK IF YOU LIKE IT" if score >= 55 else "SKIP IT"
    store.set_data(c.slug, quick_score100=score, quick_recommendation=rec)
    lines = [f"Quick score {score}/100 -> {rec}"] + [f"  {LIGHT_QUESTIONS[k]:34} {v[0] * 2:>2}/10  {v[1]}" for k, v in s.items()] + [
        _spent(c), "A full check adds rivals, AI assistants, market size, money and a plan (about $2-3); a deep check goes bigger (about $4-7)."]
    c.write("09_quick_memo.md", "# Quick check\n\n" + "\n".join(lines))
    return Result("pass", "\n".join(lines))

"""PHASE 1: IDEA FILTER (blocks 01-04). Goal: in about an hour and under $0.50, drop dead, duplicate
or no-unique-data ideas before any paid keyword research."""
import difflib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import ai, seo, store, web
from ..pipeline import Result
from ..util import pct_change


# ---------------- 01 Idea + duplicates ----------------
class Intake(BaseModel):
    one_liner: str = Field(description="Exactly: 'People [who] want X and would pay for Y'")
    payer: str = Field(description="who pays, concrete")
    product: str = Field(description="what they pay for, concrete, digital")
    clear: bool = Field(description="true only if payer and product are concrete")
    why_unclear: str = ""
    key_terms: list[str] = Field(description="3-5 short search terms buyers would type", min_length=3, max_length=5)
    duplicate_of: Optional[str] = Field(default=None, description="slug of an archived idea that is the same business, else null")


def b01_intake(c):
    v = c.v
    src_text = ""
    if v["source"].startswith("http"):
        p = web.fetch(v["source"])
        src_text = web.text_of(p["html"], 6000) if p["status"] == 200 else f"(could not open: {p['status']} {p['error']})"
    # an "other angle" idea is never a duplicate of the idea it came from
    family = {c.slug, v["data"].get("angle_of"), v["data"].get("angle_slug")}
    archive = [{"slug": o["slug"], "one_liner": o["one_liner"] or o["idea"], "status": o["status"]}
               for o in store.ventures() if o["slug"] not in family]
    # cheap local duplicate check first
    for o in archive:
        r = difflib.SequenceMatcher(None, v["idea"].lower(), o["one_liner"].lower()).ratio()
        if r > 0.85:
            return Result("kill", f"duplicate of '{o['slug']}' ({o['status']}), text match {r:.0%}")
    out = ai.ask_json(
        f"""Block 01. Turn this raw idea into one sentence: "People [who] want X and would pay for Y".
Then check if it duplicates an idea in the archive (same buyer AND same product = duplicate; killed ideas count too).
Raw idea: {v['idea']}
Source: {v['source'] or '-'}
Source text: {src_text or '-'}
Target country: {v['country']}{c.note()}""",
        Intake, smart=False, context={"archive": archive})
    c.write("01_intake.md", f"""# 01 Intake: {c.slug}
- Date: {store.now()}
- Raw idea: {v['idea']}
- Source: {v['source'] or '-'}
- Country / language: {v['country']} / {v['lang']}
- **One sentence:** {out.one_liner}
- Payer: {out.payer}
- Product: {out.product}
- Key terms: {', '.join(out.key_terms)}
- Duplicate: {out.duplicate_of or 'none'}
""")
    store.update_venture(c.slug, one_liner=out.one_liner)
    store.set_data(c.slug, key_terms=out.key_terms, payer=out.payer, product=out.product)
    if out.duplicate_of and store.venture(out.duplicate_of):
        return Result("kill", f"duplicate of '{out.duplicate_of}'")
    if not out.clear:
        return Result("redo", f"payer/product unclear: {out.why_unclear or out.one_liner}")
    return Result("pass", out.one_liner)


# ---------------- 02 Business, data, E-E-A-T ----------------
class Competitor(BaseModel):
    name: str
    url: str
    price: str = Field(description="real price seen on their site, e.g. '$29 one-time' or '$49/mo'; 'unknown' if not found")
    pricing_model: Literal["one-time", "subscription", "b2b", "api", "ads", "affiliate", "freemium", "unknown"]
    source_url: str = Field(description="page where the price was seen")


class DataSource(BaseModel):
    name: str
    type: Literal["api", "public-register", "scraping", "own-data", "ai-generated", "manual", "other"]
    url: str = ""
    cost_note: str = ""


class EeatItem(BaseModel):
    answer: str
    ok: bool = Field(description="true if the owner can REALISTICALLY have this by launch (it does not need to exist today); false only if it is impossible or very hard")


class Eeat(BaseModel):
    real_person_or_company: EeatItem
    expertise_proof: EeatItem
    unique_data_per_page: EeatItem
    contacts_policies_real_example: EeatItem
    ymyl_level: Literal["none", "low", "medium", "high"]
    ymyl_banned_claims: list[str] = []


class How(BaseModel):
    competitors: list[Competitor] = Field(description="paying competitors you actually found, best first (aim for 3-8)")
    revenue_models: list[str]
    data_sources: list[DataSource]
    validation_question: str = Field(description="the ONE question that decides if this works")
    delivered_digitally: bool
    legal: bool
    needs_physical_logistics: bool
    breaks_house_rules: list[str] = Field(default=[], description="ONLY the house rules this idea actually breaks, one line each. Empty list if none. Never list rules that are not broken")
    eeat: Eeat
    notes: str = ""


def b02_how_eeat(c):
    i = c.read("01_intake.md")
    out = ai.ask_json(
        f"""Block 02. Research HOW this business makes money, using web search. Open competitor sites and pricing pages.
A) Find paying competitors (links + real prices), the revenue model, where the data comes from (API, public register,
scraping...) and the one validation question.
B) Google quality (E-E-A-T) check for OUR future site (judge what the owner can realistically have by launch, not what exists today): 1) real person/company behind it (no AI faces) 2) proof of
expertise 3) unique data for every page 4) contacts, policies, a real example 5) YMYL risk (money/health/law) and claims
we must never make.
Intake:
{i}{c.note()}""",
        How, web=True, smart=True)
    d = out.model_dump()
    c.write("02_how_analysis.json", {k: v for k, v in d.items() if k != "eeat"})
    c.write("03_eeat_quality.json", d["eeat"])
    priced = [x for x in out.competitors if x.price and x.price.lower() != "unknown"]
    e = out.eeat
    kills = []
    if not priced:
        kills.append("nobody is charging money today (no priced competitor found)")
    if not out.legal:
        kills.append("not legal")
    if out.needs_physical_logistics or not out.delivered_digitally:
        kills.append("needs physical delivery/logistics")
    if not e.real_person_or_company.ok:
        kills.append("no real person/company can stand behind it")
    if not e.unique_data_per_page.ok:
        kills.append("no unique data per page")
    broken = [r for r in out.breaks_house_rules if "not broken" not in r.lower()]
    if broken:
        kills.append("breaks house rules: " + "; ".join(broken))
    if kills:
        return Result("kill", "; ".join(kills))
    weak = [k for k in ("expertise_proof", "contacts_policies_real_example") if not getattr(e, k).ok]
    summary = f"{len(priced)} paying competitors (e.g. {priced[0].name} {priced[0].price}); data: {', '.join(s.name for s in out.data_sources[:3])}; YMYL {e.ymyl_level}"
    if len(priced) < 3 or weak:
        return Result("warn", summary + (f"; weak E-E-A-T: {', '.join(weak)}" if weak else "") + ("; fewer than 3 paying competitors" if len(priced) < 3 else ""))
    return Result("pass", summary)


# ---------------- 03 Niche alive or dead ----------------
class Pulse(BaseModel):
    rising_synonyms: list[str] = Field(description="newer terms people now use for the same thing (may be empty)")
    new_competitors_12m: list[str] = Field(description="URLs of competitors launched in the last 12 months")
    fresh_discussions_90d: list[str] = Field(description="URLs of Reddit/forum questions from the last 90 days")
    notes: str = ""


def _trend_change(series, months=24):
    """% change: average of the last 3 points vs the same 3 points `months` earlier (weekly or monthly data)."""
    if len(series) < 8:
        return None
    per_year = 52 if len(series) > 80 else 12
    back = int(per_year * months / 12)
    if len(series) <= back + 3:
        back = len(series) - 4
    vals = [v for _, v in series]
    new = sum(vals[-3:]) / 3
    old = sum(vals[-back - 3:-back]) / 3
    return pct_change(new, old)


def b03_niche_pulse(c):
    terms = (c.v["data"].get("key_terms") or [])[:5]
    how = c.read("02_how_analysis.json")
    trend, err = {}, ""
    if seo.available():
        try:
            series = seo.trends(terms, c.loc)
            trend = {t: {"change_24m_pct": _trend_change(s), "points": len(s)} for t, s in series.items()}
        except seo.DFSError as e:
            err = str(e)
        try:
            s = seo.serp(terms[0], c.loc, c.lang, depth=10)
            ads = s["features"].get("paid", 0)
            ads_domains = sorted({p["domain"] for p in s["paid"]})
        except seo.DFSError as e:
            ads, ads_domains, err = None, [], err + " " + str(e)
    else:
        ads, ads_domains, err = None, [], "no DataForSEO keys: trend and ads not measured"
    out = ai.ask_json(
        f"""Block 03. Is this niche alive? Use web search. Find: newer synonyms people use now, competitors launched in the
last 12 months (URLs), and Reddit/forum questions from the last 90 days (URLs). Only list URLs you actually saw.
Idea: {c.v['one_liner']}
Key terms: {terms}
Competitors already known: {[x['url'] for x in how['competitors']]}{c.note()}""",
        Pulse, web=True, smart=False)
    changes = [t["change_24m_pct"] for t in trend.values() if t["change_24m_pct"] is not None]
    best = max(changes) if changes else None
    quiet = len(out.fresh_discussions_90d) == 0
    if best is not None and best < -30 and not out.rising_synonyms and not ads and quiet:
        status = "dying"
    elif best is None or best >= -10 or out.rising_synonyms:
        status = "alive"
    else:
        status = "flat"
    pulse = {"status": status, "change_24m_pct_best": best, "trend": trend, "ads_on_top_term": ads,
             "advertisers": ads_domains, **out.model_dump(), "measure_errors": err.strip()}
    c.write("04_niche_pulse.json", pulse)
    summary = (f"{status}; 24-month trend {best if best is not None else 'n/a'}%; ads on '{terms[0]}': {ads}; "
               f"{len(out.fresh_discussions_90d)} fresh discussions; {len(out.new_competitors_12m)} new players")
    if status == "dying":
        return Result("kill", summary)
    return Result("pass" if status == "alive" else "warn", summary)


# ---------------- 04 ICE + MVP ----------------
class Effort(BaseModel):
    days_to_mvp: int
    monthly_cost_usd: float
    api_dependencies: list[str]
    owner_hours_per_week: float


class Ice(BaseModel):
    impact: int = Field(ge=1, le=10)
    confidence: int = Field(ge=1, le=10)
    ease: int = Field(ge=1, le=10)
    impact_why: str = Field(default="", description="one short plain sentence: why this impact score")
    confidence_why: str = Field(default="", description="one short plain sentence: why this confidence score")
    ease_why: str = Field(default="", description="one short plain sentence: why this ease score")


class OtherAngle(BaseModel):
    idea: str = Field(description="One full sentence that stands alone as a NEW idea: who pays, what they get, how it is charged. "
                                  "A clearly different customer or offer (B2B instead of consumers, a narrower group, another way to charge), not a small tweak")
    why: str = Field(description="one or two plain sentences: why this could work where the idea as written is weak")
    cheapest_test: str = Field(description="the cheapest way to check it before building, one sentence")


class Scorecard(BaseModel):
    pros: list[str] = Field(min_length=5, max_length=5)
    cons: list[str] = Field(min_length=5, max_length=5)
    biggest_unknown: str
    effort: Effort
    ice: Ice
    synergy: str = Field(description="what existing assets (sites, data, outreach system) from the house rules help")
    blockers: list[str] = Field(description="HARD blockers only: things that make the business impossible (illegal, no way to get the data, needs a licence we cannot get). Empty if none. Prerequisites and risks go in 'risks'")
    risks: list[str] = Field(default=[], description="soft risks and prerequisites (privacy policy, unproven conversion, low price...)")
    summary_3_lines: list[str] = Field(min_length=3, max_length=3)
    other_angle: Optional[OtherAngle] = Field(default=None, description="the ONE best different angle on this idea that could work better than the idea as written. "
                                              "Always give one when the ICE average is under 6; null only if there truly is none")


def b04_ice(c):
    ctx = {"intake": c.read("01_intake.md"), "how": c.read("02_how_analysis.json"),
           "eeat": c.read("03_eeat_quality.json"), "niche": c.read("04_niche_pulse.json")}
    out = ai.ask_json(
        f"""Block 04. Score this idea. Give exactly 5 arguments FOR and 5 AGAINST, the single biggest unknown, the effort
(days to a working MVP built with an AI coding agent, monthly running cost, API dependencies, owner hours/week),
ICE 1-10 (Impact, Confidence, Ease) with one short plain reason each, synergy with the owner's existing assets, hard blockers,
and a 3-line summary. Also name the ONE other angle that could work better (a different customer, B2B, a narrower group or another
way to charge), written as a full new idea sentence, so it can be tested on its own if this idea scores under 6.
In the summary and reasons use plain words; never write "ICE" or score shorthand like "3/2/4".{c.note()}""",
        Scorecard, smart=True, context=ctx)
    avg = round((out.ice.impact + out.ice.confidence + out.ice.ease) / 3, 2)
    d = out.model_dump() | {"ice_avg": avg}
    c.write("05_scorecard.json", d)
    store.set_data(c.slug, ice_avg=avg, mvp_days=out.effort.days_to_mvp, first_score100=round(avg * 10),
                   other_angle=out.other_angle.model_dump() if out.other_angle else None)
    summary = f"ICE {avg} (I{out.ice.impact} C{out.ice.confidence} E{out.ice.ease}); MVP {out.effort.days_to_mvp} d; blockers: {', '.join(out.blockers) or 'none'}"
    if out.blockers or out.effort.days_to_mvp > 30:
        return Result("kill", summary)
    if avg >= 6.0 and out.effort.days_to_mvp <= 14:
        return Result("pass", summary)
    return Result("warn", summary + " (below the pass bar: ICE >= 6 and MVP <= 14 d)"
                  + ("; another angle could work, see gate 1" if out.other_angle else ""))

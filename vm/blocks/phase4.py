"""PHASE 4: PLAN, COSTS, GUARDRAILS (blocks 15-17). Numbers before building."""
import datetime as dt
import json
import pathlib
import re
from typing import Literal

from pydantic import BaseModel, Field

from .. import ai, store
from ..config import S
from ..pipeline import Result
from ..util import has_number_or_source, md_table, num, read_csv, write_csv
from .gates import MENU

PRICES = json.loads((pathlib.Path(__file__).resolve().parent.parent / "prices.json").read_text(encoding="utf-8"))
BAD = re.compile(r"\b(tbd|todo|unknown|n/?a|\?\?)\b", re.I)

ABSOLUTE_BANS = [
    "No impersonating government bodies, no 'official', no OEM logos or state look-alike design.",
    "No fake reviews, fake testimonials, fake timers, fake scarcity or arbitrage pages.",
    "No loan/financing wording unless licensed.",
    "One honest account per platform per business; no proxies to dodge bans; never reuse a banned account.",
    "No invented numbers on the site or in ads: every stat has a source and a date.",
    "Money never moves without the owner: agents propose budgets with caps, the owner approves.",
    "Hard daily and monthly caps on ads, pages, emails and API calls.",
    "Pass/kill thresholds are written before a test and never changed after seeing results.",
]


# ---------------- 15 Tools, costs, guardrails ----------------
class Tool(BaseModel):
    name: str
    purpose: str
    cost_start_usd_month: float
    cost_10x_usd_month: float
    limit: str
    account_owner: str


class Channel(BaseModel):
    channel: str
    cost: str
    cap: str
    pass_threshold: str
    kill_threshold: str


class Todo(BaseModel):
    task: str
    why: str
    minutes: int


class Costs(BaseModel):
    tools: list[Tool]
    data_cost_per_sale_usd: float = Field(description="API/data cost to deliver ONE sale (from block 02 data sources)")
    marketing: list[Channel]
    guardrails: list[str] = Field(description="business-specific bans and caps (the absolute bans are added automatically)")
    access: list[str] = Field(description="every API key / login the build needs, and who holds it")
    owner_todo: list[Todo] = Field(description="manual steps for block 19: domain, DNS SPF/DKIM/DMARC, payment KYC, one honest account per platform, API keys")
    owner_questions: list[str] = Field(description="open questions only the owner can answer")


def b15_costs(c):
    ctx = {"stack_price_list": PRICES, "how": c.read("02_how_analysis.json"), "business": c.read("13_competitor_business.json"),
           "market": {k: v for k, v in c.read("14_market_analysis.json").items() if k in ("typical_price_usd", "bottom_up_usd_year", "segments")},
           "seo": c.read("15_competitor_seo.json")}
    out = ai.ask_json(
        f"""Block 15. Costs and the autonomy contract for: {c.v['one_liner']}
1) Technical costs at start and at 10x: hosting, DB, payments, API price per call, proxies, email, analytics - with
limits and the account owner. Start from the stack price list; add the business's own data APIs with real prices.
2) Marketing costs and caps: cold email from warmed domains, directories, partners (20-35% of sales only), ads
(5-20/day caps), and pass/kill thresholds per channel test.
3) Guardrails (business-specific bans and caps), access list, the owner's manual to-do (block 19), open questions.
No field may be 'TBD' or 'unknown': give a number or a concrete answer.{c.note()}""",
        Costs, smart=True, context=ctx)
    bad = [f"{t.name}: {t.limit}" for t in out.tools if BAD.search(t.limit) or BAD.search(t.account_owner) or not t.account_owner.strip()]
    bad += [ch.channel for ch in out.marketing if any(BAD.search(x) for x in (ch.cap, ch.pass_threshold, ch.kill_threshold))]
    fixed = sum(t.cost_start_usd_month for t in out.tools)
    caps = {"fixed_cost_usd_month": round(fixed, 2), "fixed_cost_10x_usd_month": round(sum(t.cost_10x_usd_month for t in out.tools), 2),
            "data_cost_per_sale_usd": out.data_cost_per_sale_usd, "channel_test_max_loss_usd": 100, "ads_daily_cap_usd": 20}
    store.set_data(c.slug, budget_caps=caps)
    c.write("15_costs.json", out.model_dump() | {"budget_caps": caps})
    g = [f"# GUARDRAILS: {c.slug}\n", "## Absolute bans (every business)"] + [f"- {x}" for x in ABSOLUTE_BANS]
    g += ["\n## This business"] + [f"- {x}" for x in out.guardrails]
    g += ["\n## Budget caps", md_table([caps], list(caps)), "\n## Channel tests (thresholds fixed now)",
          md_table([ch.model_dump() for ch in out.marketing], ["channel", "cost", "cap", "pass_threshold", "kill_threshold"])]
    c.write("GUARDRAILS.md", "\n".join(g))
    c.write("ACCESS.md", "# ACCESS\n\n" + "\n".join(f"- {a}" for a in out.access) + "\n\n## Tools\n" +
            md_table([t.model_dump() for t in out.tools], ["name", "purpose", "cost_start_usd_month", "cost_10x_usd_month", "limit", "account_owner"]))
    c.write("OWNER-TODO.json", {"block": 19, "done": False, "tasks": [t.model_dump() | {"done": False} for t in out.owner_todo]})
    c.write("16_owner_questions.md", "# Open questions for the owner\n\n" + "\n".join(f"{i}. {q}\n   - Answer: " for i, q in enumerate(out.owner_questions, 1)))
    summary = f"fixed ${fixed:.0f}/mo at start; data cost ${out.data_cost_per_sale_usd:.2f}/sale; {len(out.owner_todo)} owner to-dos; {len(out.owner_questions)} questions"
    if bad:
        return Result("redo", "these have no price/limit/owner (TBD): " + "; ".join(bad[:8]))
    return Result("pass", summary)


# ---------------- 16 Unit economics + SWOT ----------------
CHANNEL = Literal["google search", "cold email", "marketplace", "community", "partners", "paid ads"]


class ModelOption(BaseModel):
    model: str = Field(description="e.g. one-time report, monthly subscription, B2B plan, API, own data vs reseller")
    price_usd: float
    payment: Literal["one-time", "subscription"]
    payer: str = Field(description="who pays, in a few words")
    channel: CHANNEL = Field(description="the MAIN way customers are won for this option")
    same_buyer_and_channel: bool = Field(description="true ONLY if the payer is the idea's own payer AND customers come mainly from Google search "
                                                     "(the buyer and channel that phases 2-3 measured). A different buyer or channel = false")
    conversion_pct: float = Field(description="visitor -> buyer %, with reasoning in 'assumptions'")
    retention_months: float = Field(description="1 for one-time")
    sales_per_month_at_1000_visits: float
    owner_hours_per_month: float
    delivery_cost_per_sale_usd: float = Field(description="data/API cost to deliver ONE sale (for a subscription: one customer for one month)")
    extra_fixed_cost_usd_month: float = Field(description="monthly cost THIS option needs on top of the block 15 tools (API hosting, scheduled data pulls...); 0 if none")
    build_days: int = Field(description="days to a first sellable version of THIS option")
    assumptions: list[str] = Field(description="each number above that is not measured: say where it comes from (URL) or write ASSUMPTION")
    sources: list[str]


class Options(BaseModel):
    options: list[ModelOption] = Field(min_length=3)


class ValidationTest(BaseModel):
    test: Literal["search-demand", "smoke-page", "fake-door", "pre-sale", "ads-test", "cold-email", "price-test", "seo-test", "channel-test"]
    why: str
    sample: str = Field(description="who and how many, e.g. '300 emails to SEO agencies' or '500 visitors from the 3 easiest pages'")
    warmup_days: int = Field(ge=0, le=21, description="days needed before the test can start (14 for a new cold-email domain, 0 otherwise)")
    days: int = Field(ge=1, le=14)
    budget_usd: float = Field(le=150)
    pass_threshold: str
    kill_threshold: str
    setup_steps: list[str]


class Case(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]
    conclusions: list[str] = Field(min_length=3, max_length=3)
    guardrails: list[str] = Field(description="bans and caps for THE CHOSEN OFFER only")
    owner_todo: list[Todo] = Field(description="manual steps for THE CHOSEN OFFER only")
    owner_questions: list[str] = Field(description="open questions only the owner can answer, about THE CHOSEN OFFER and this decision")
    validation_test: ValidationTest


def economics(price, data_cost, fee_pct, fee_fixed, conversion_pct, retention_months, cpc):
    net = price - data_cost - price * fee_pct / 100 - fee_fixed
    max_cac = net * retention_months
    breakeven_cpc = net * retention_months * conversion_pct / 100
    paid_cac = cpc / (conversion_pct / 100) if conversion_pct else None
    return {"net_per_sale": round(net, 2), "max_cac": round(max_cac, 2), "breakeven_cpc": round(breakeven_cpc, 2),
            "paid_search_cac": round(paid_cac, 2) if paid_cac else None}


def offer_line(o):
    return (f"{o['model']} for {o['payer']}, ${o['price_usd']:g} USD {'a month (subscription)' if o['payment'] == 'subscription' else 'one-time'}, "
            f"customers won through {o['channel']}")


def timeline(offer, forecast_mid, market_year_usd, today=None):
    """Dates worked out from the validation test and the forecast (never typed by hand).
    Money steps get a date only if the forecast reaches them inside 12 months (straight ramp: month m earns m/78 of the year)."""
    t = today or dt.date.today()
    test = offer.get("test") or {}
    test_first = market_year_usd < S.target_market_month * 12 and bool(test)
    steps = []
    start = t
    if test_first:
        if test.get("warmup_days"):
            start = t + dt.timedelta(days=int(test["warmup_days"]))
            steps.append(("warm-up done, validation test starts", start.isoformat()))
        begin = start
        end = begin + dt.timedelta(days=int(test["days"]))
        hol_a, hol_b = dt.date(begin.year, 12, 18), dt.date(begin.year + 1, 1, 4)
        if begin <= hol_b and end >= hol_a:   # nobody answers a test sent over Christmas and New Year: start after it
            begin = hol_b + dt.timedelta(days=(7 - hol_b.weekday()) % 7 or 0)
            steps.append(("validation test starts (moved past the year-end holidays, when buyers do not answer)", begin.isoformat()))
            end = begin + dt.timedelta(days=int(test["days"]))
        start = end
        steps.append(("validation test ends: decide (first paid pre-orders, or stop)", start.isoformat()))
    live = start + dt.timedelta(days=int(offer.get("build_days") or 14))
    steps += [("first version live", live.isoformat()), ("pages indexed by Google", (live + dt.timedelta(days=14)).isoformat())]
    for x in (100, 1000):
        m = -(-78 * x // max(forecast_mid, 0.01)) if forecast_mid else 99
        steps.append((f"${x:,} a month", (live + dt.timedelta(days=30 * int(m))).isoformat() if m <= 12 else
                      f"not reached in the first 12 months (the forecast ends at about ${forecast_mid * 12 / 78:,.0f} a month)"))
    return {"test_first": test_first, "build_from": start.isoformat(), "live": live.isoformat(),
            "steps": [{"goal": g, "by": by} for g, by in steps]}


def write_guardrails(c, costs, offer):
    caps = costs["budget_caps"]
    g = [f"# GUARDRAILS: {c.slug}\n", f"Offer: {offer_line(offer)}\n" if offer else "", "## Absolute bans (every business)"] + [f"- {x}" for x in ABSOLUTE_BANS]
    g += ["\n## This business"] + [f"- {x}" for x in costs["guardrails"]]
    g += ["\n## Budget caps", md_table([caps], list(caps)), "\n## Later channel tests (after the validation test; thresholds fixed now)",
          md_table(costs["marketing"], ["channel", "cost", "cap", "pass_threshold", "kill_threshold"])]
    c.write("GUARDRAILS.md", "\n".join(g))
    c.write("OWNER-TODO.json", {"block": 19, "done": False, "tasks": [t | {"done": False} for t in costs["owner_todo"]]})
    c.write("16_owner_questions.md", "# Open questions for the owner\n\n" + "\n".join(f"{i}. {q}\n   - Answer: " for i, q in enumerate(costs["owner_questions"], 1)))


def b16_economics(c):
    from .. import checks
    from ..util import is_buy
    from .phase3 import market_method
    costs = c.read("15_costs.json")
    caps = costs["budget_caps"]
    pay = next((s for s in PRICES["stack"] if "fee_pct" in s), {"fee_pct": 5.0, "fee_fixed_usd": 0.4})
    kws = read_csv(c.path("08_keywords_clean.csv"))
    priced = [k for k in kws if is_buy(k) and num(k["cpc"]) > 0]
    vol = sum(num(k["volume"]) for k in priced)
    # click price averaged by volume over the buying searches that have a price (what a real ad budget would pay)
    avg_cpc = round(sum(num(k["cpc"]) * num(k["volume"]) for k in priced) / vol, 2) if vol else 1.0
    mkt = c.read("14_market_analysis.json")
    clicks = checks.reachable_clicks(mkt)
    payer = (c.v["data"].get("payer") or "").strip() or "the buyer named in the idea"
    out = ai.ask_json(
        f"""Block 16a. Ways to charge for: {c.v['one_liner']}
The idea's own payer: {payer}. Phases 2-3 measured this payer through GOOGLE SEARCH only.
Give at least 3 model options (one-time vs subscription vs B2B vs API; own data vs reseller). For each: price in USD, payment type,
who pays, the main channel, conversion %, retention months, sales per 1,000 visits, owner hours/month, the delivery cost per sale,
any extra monthly cost this option needs, days to build it, and where each unmeasured number comes from (URL or the word ASSUMPTION).
At least ONE option must be for the idea's own payer through Google search (same_buyer_and_channel = true).
An option for a different buyer or a different main channel is allowed, but mark it false: it will be shown as a separate idea, not chosen here.
Python computes the money. All amounts in USD.{c.note()}""",
        Options, smart=True, context={"costs": {k: costs[k] for k in ("tools", "data_cost_per_sale_usd", "marketing", "budget_caps")},
                                      "scorecard": c.read("05_scorecard.json"), "competitor_business": c.read("13_competitor_business.json"),
                                      "shortlist": read_csv(c.path("11_shortlist.csv"))[:25], "avg_buying_cpc_usd": avg_cpc, "payment_fees": pay,
                                      "reachable_clicks_a_month_from_google": round(clicks)})
    opts = []
    for o in out.options:
        same = o.same_buyer_and_channel and o.channel == "google search"
        e = economics(o.price_usd, o.delivery_cost_per_sale_usd, pay["fee_pct"], pay["fee_fixed_usd"], o.conversion_pct, o.retention_months, avg_cpc)
        visits = min(1000.0, max(clicks, 1.0)) if same else 1000.0   # a search option cannot assume more visitors than Google can send
        fixed = caps["fixed_cost_usd_month"] + o.extra_fixed_cost_usd_month
        profit_month = e["net_per_sale"] * o.sales_per_month_at_1000_visits * visits / 1000 - fixed
        e |= {"visits_used": round(visits), "fixed_cost_usd_month": round(fixed, 2), "profit_per_hour": round(profit_month / max(o.owner_hours_per_month, 1), 2)}
        opts.append(o.model_dump() | e | {"same_buyer_and_channel": same})
    own = [o for o in opts if o["same_buyer_and_channel"]]
    if not own:
        return Result("redo", "no option is for the idea's own payer through Google search; give at least one (same_buyer_and_channel = true)")
    best = max(own, key=lambda o: o["profit_per_hour"])
    other = max([o for o in opts if not o["same_buyer_and_channel"]], key=lambda o: o["profit_per_hour"], default=None)
    spin = None
    if other and other["profit_per_hour"] > best["profit_per_hour"]:
        # block 16 may not move the idea to another buyer or channel: that would be a business nobody researched
        spin = {"idea": f"{other['payer']} want {other['model']} and would pay ${other['price_usd']:g} {'a month' if other['payment'] == 'subscription' else 'one-time'}; sold through {other['channel']}",
                "why": (f"On paper it earns more per hour (${other['profit_per_hour']:,.0f} against ${best['profit_per_hour']:,.0f}), but it is a different buyer or channel: "
                        "none of this report's demand, rival or market research is about it. Run it as its own idea."),
                "option": other}
    offer = {"model": best["model"], "price_usd": best["price_usd"], "currency": "USD", "payment": best["payment"], "payer": best["payer"],
             "channel": best["channel"], "retention_months": best["retention_months"], "conversion_pct": best["conversion_pct"],
             "build_days": best["build_days"], "fixed_cost_usd_month": best["fixed_cost_usd_month"], "delivery_cost_per_sale_usd": best["delivery_cost_per_sale_usd"]}
    # one price everywhere: restate the search market at the price that was chosen, formula text included
    used = num(mkt.get("price_used_usd") or mkt.get("typical_price_usd"))
    market = mkt["bottom_up_usd_year"] * best["price_usd"] / used if used else mkt["bottom_up_usd_year"]
    if used:
        mkt["bottom_up_at_chosen_price_usd_year"] = round(market)
        mkt["chosen_price_usd"] = best["price_usd"]
        mkt["bottom_up_method_at_chosen_price"] = market_method(mkt, best["price_usd"], "the chosen price from step 16")
        c.write("14_market_analysis.json", mkt)
        from .phase3 import market_result
        r12 = market_result(mkt, market, f" at the chosen price ${best['price_usd']:g}")
        store.set_block(c.slug, "12", verdict=r12.verdict, summary=r12.summary)
    facts = {"THE_OFFER": offer_line(offer), "price_usd": best["price_usd"], "payment": best["payment"],
             "net_per_sale_usd": best["net_per_sale"], "max_spend_per_customer_usd": best["max_cac"], "paid_search_cost_per_customer_usd": best["paid_search_cac"],
             "money_reachable_through_google_search_usd_year": round(market), "that_is_usd_a_month": round(market / 12),
             "smallest_market_worth_building_usd_month": S.min_market_month, "market_we_want_usd_month": S.target_market_month,
             "buying_searches_a_month": mkt.get("buying_searches_month"), "reachable_clicks_a_month": round(clicks),
             "rivals_google_visits_trend_12m_pct": mkt.get("rivals_traffic_trend_12m_pct"), "fixed_cost_usd_month": best["fixed_cost_usd_month"],
             "other_options_compared": [f"{o['model']} at ${o['price_usd']:g}" for o in opts if o is not best]}
    case = ai.ask_json(
        f"""Block 16b. Business case for: {c.v['one_liner']}
THE CHOSEN OFFER (fixed, do not change it): {offer_line(offer)}
Write everything for THIS offer only. The facts sheet in the context holds the only numbers you may use for price, market and money.
1) SWOT: EVERY line must contain a number or a source URL. 2) Exactly 3 conclusions.
3) Guardrails, the owner's manual to-do list and the open owner questions: for this offer only (its payment type, its buyer, its channel).
4) ONE validation test, the cheapest from the menu that answers "{c.read('02_how_analysis.json').get('validation_question', 'will they pay?')}":
budget <= $150, <= 14 days, pass and kill thresholds written now. Its price is the chosen price.
RULES: USD only (never euros). Do not describe other options as if they were the plan. Do not write about a sales goal or target revenue:
the only size rule is the market bar in the facts sheet. Do not give two different tests or thresholds.
Menu:
{MENU}{c.note()}""",
        Case, smart=True, context={"facts_sheet": facts, "tools_and_marketing": {k: costs[k] for k in ("tools", "marketing", "access")},
                                   "market": {k: mkt.get(k) for k in ("segments", "underserved_countries_or_segments", "growth_direction", "growth_evidence", "top_down_usd_year", "top_down_method", "rival_traffic")},
                                   "competitor_business": c.read("13_competitor_business.json"), "scorecard": c.read("05_scorecard.json")})
    offer["test"] = case.validation_test.model_dump() | {"price_usd": best["price_usd"]}
    costs_before = {k: costs[k] for k in ("guardrails", "owner_todo", "owner_questions")} if "before_offer" not in costs else costs["before_offer"]
    costs |= {"guardrails": case.guardrails, "owner_todo": [t.model_dump() for t in case.owner_todo], "owner_questions": case.owner_questions,
              "before_offer": costs_before}
    c.write("15_costs.json", costs)
    write_guardrails(c, costs, offer)
    c.write("offer.json", offer)
    ue = {"chosen": best, "options": opts, "avg_buying_cpc_usd": avg_cpc, "ladder": [], "spin_off": spin,
          "formulas": {"net_per_sale": "price - delivery cost - payment fees", "max_cac": "net x retention months",
                       "breakeven_cpc": "net x retention x conversion", "paid_search_cac": f"average buying click price ${avg_cpc} / conversion {best['conversion_pct']}%",
                       "profit_per_hour": "(net x sales at the visitors Google can really send - fixed costs) / owner hours"}}
    store.set_data(c.slug, unit_economics={k: best[k] for k in ("model", "price_usd", "net_per_sale", "max_cac", "breakeven_cpc", "paid_search_cac")},
                   chosen_price_usd=best["price_usd"], offer=offer, spin_off=spin,
                   budget_caps=caps | {"fixed_cost_usd_month": best["fixed_cost_usd_month"], "data_cost_per_sale_usd": best["delivery_cost_per_sale_usd"]})
    c.write("16_unit_economics.json", ue)
    lines = case.strengths + case.weaknesses + case.opportunities + case.threats
    missing = [l for l in lines if not has_number_or_source(l)]
    mk = lambda xs: "\n".join(f"- {x}" for x in xs)
    swot = (f"# SWOT: {c.slug}\nOffer: {offer_line(offer)}\n\n## Strengths\n{mk(case.strengths)}\n\n## Weaknesses\n{mk(case.weaknesses)}\n\n"
            f"## Opportunities\n{mk(case.opportunities)}\n\n## Threats\n{mk(case.threats)}\n\n## 3 conclusions\n{mk(case.conclusions)}\n")
    c.write("18_swot.md", swot)
    t = offer["test"]
    c.write("18_business_case.md", f"""# Business case: {c.slug}
{c.v['one_liner']}

## Chosen offer: {offer_line(offer)}
- Price ${best['price_usd']:g} | net per sale ${best['net_per_sale']} | max spend per customer ${best['max_cac']} | break-even click price ${best['breakeven_cpc']}
- Paid search cost per customer at the average buying click price ${avg_cpc}: ${best['paid_search_cac']}
- Profit per owner hour at {best['visits_used']} visitors a month (what Google can really send, at most 1,000): ${best['profit_per_hour']}
- Money reachable through Google search at this price: ${market:,.0f} a year (${market / 12:,.0f} a month)

## The one validation test
{t['test']}: {t['sample']}; {t['days']} days{f" after {t['warmup_days']} days of warm-up" if t['warmup_days'] else ''}; budget ${t['budget_usd']:g}.
PASS if: {t['pass_threshold']}. KILL if: {t['kill_threshold']}.

## All options
{md_table(opts, ['model', 'payer', 'channel', 'price_usd', 'payment', 'conversion_pct', 'retention_months', 'net_per_sale', 'max_cac', 'profit_per_hour', 'visits_used', 'same_buyer_and_channel'])}
## Assumptions behind the chosen offer
{mk(best['assumptions']) or '- none given'}
""")
    summary = (f"{best['model']} at ${best['price_usd']:g} ({best['payment']}): net ${best['net_per_sale']}/sale, max spend per customer ${best['max_cac']}, "
               f"paid search ${best['paid_search_cac']} per customer" + ("; a stronger option for a different buyer or channel was set aside as its own idea" if spin else ""))
    bad = checks.text_problems({"SWOT": swot, "rules": "\n".join(case.guardrails), "to-do list": json.dumps(costs["owner_todo"], ensure_ascii=False),
                                "owner questions": "\n".join(case.owner_questions)}, offer, market, mkt["bottom_up_usd_year"])
    if missing:
        bad.append(f"{len(missing)} SWOT lines have no number or source, e.g. '{missing[0][:80]}'")
    if bad and c.attempt < 3:
        return Result("redo", "; ".join(bad[:6]))
    if best["net_per_sale"] <= 0:
        return Result("kill", summary + "; loses money on every sale")
    if bad:
        return Result("fail", summary + "; the text still has problems after 3 tries: " + "; ".join(bad[:3]))
    if best["paid_search_cac"] and best["paid_search_cac"] > best["max_cac"]:
        return Result("warn", summary + "; paid search is not profitable: needs SEO/cold email first")
    return Result("pass", summary)


# ---------------- 17 Product, sitemap, 90-day SEO ----------------
class PagePlan(BaseModel):
    cluster_id: int
    url_slug: str
    title: str
    page_type: Literal["home", "money", "tool", "data", "guide", "comparison", "directory"]
    unique_data_source: str = Field(description="the specific data that makes THIS page different from the others")


class Plan(BaseModel):
    product_line: list[str]
    free_hook: str
    upsell: str
    why_us_5_seconds: str
    forecast_12m_usd: dict[str, float] = Field(description="keys: low, mid, high")
    forecast_assumptions: str
    pages: list[PagePlan]
    link_bait_asset: str
    ai_search_plan: list[str] = Field(description="llms.txt, Bing/IndexNow, MCP/OpenAPI, etc.")
    advantage_score: int = Field(ge=1, le=5, description="1-5: how strong our edge is vs the top-5, from blocks 10-13")
    advantage_reason: str


def _template_title(t, head):
    return re.sub(r"\s+", " ", t.lower().replace(head.lower(), "{kw}")).strip()


BUYING = ("buy", "competitor", "brand-model")


def b17_plan(c):
    from .. import checks
    clusters = c.read("10_clusters_serp.json")
    links = read_csv(c.path("15_link_targets.csv"))
    offer = c.v["data"].get("offer") or {}
    mkt = c.read("14_market_analysis.json")
    market = checks.market_year(c, mkt)
    test = offer.get("test") or {}
    test_first = market < S.target_market_month * 12
    cl_info = [{"id": cl["id"], "head": cl["head"], "keywords": cl["keywords"][:8], "volume": cl["volume"], "intent": cl["intent"],
                "kd": cl.get("kd"), "winning_format": cl["winning_format"], "weak_spots": cl["weak_spots"]} for cl in clusters[:60]]
    cap = market * S.good_case_share
    out = ai.ask_json(
        f"""Block 17. Product and SEO plan for: {c.v['one_liner']}
THE CHOSEN OFFER (fixed): {offer_line(offer) if offer else 'see the business case'}
1) Product line that fills the gaps from block 11 (not a copy), a free hook, an upsell, a 5-second 'why us', and a
12-month revenue forecast low/mid/high with assumptions.
2) Sitemap: home page on the strongest BUYING search, 1 page = 1 cluster (use cluster_id), money page on the strongest buying
intent. Plan at least 20 pages (or one per cluster if fewer). EVERY page needs its own unique data source - pages that only
swap the keyword in a template are not allowed.
3) One link-bait asset and the AI-search plan. 4) Rate our edge 1-5 and give the reason as facts (price, data, speed, channel), not opinion.
RULES: sell only the chosen offer at its price, in USD (never euros). One main keyword belongs to ONE page only; a page
without its own cluster must say "support page, no target keyword" as its data source and does not count toward the 20.
The home page and the money page must target clusters with intent buy / competitor / brand-model, never an 'info' or 'brand' cluster.
A cluster with intent 'brand' is a rival's own name: that rival holds the top spot, so use it only for a comparison page.
FORECAST: about ${market:,.0f} a year is reachable through Google search in total. A new site cannot take more than {S.good_case_share:.0%} of that
in year one, so the high case must be at most ${cap:,.0f}; low <= mid <= high.
{'The search market is under the size we want, so the plan is TEST FIRST: the first product-line item is "Run the validation test" and no page is built before it ends. ' if test_first else ''}The validation test is fixed (see context): refer to it as "the validation test" and do NOT restate or invent other test sizes, day counts or thresholds.
Do not write about a sales goal or target revenue. Never give away free the same data the paid product sells.{c.note()}""",
        Plan, smart=True, context={"clusters": cl_info, "business_case": c.read("18_business_case.md"),
                                   "validation_test": test, "money_reachable_through_google_search_usd_year": round(market),
                                   "chosen_price_usd": offer.get("price_usd") or c.v["data"].get("chosen_price_usd"),
                                   "eeat": c.read("03_eeat_quality.json"), "gap": c.read("13_competitor_business.json").get("identified_gap"),
                                   "ux_weaknesses": [x.get("weaknesses") for x in c.read("12_competitor_ux.json")["competitors"]],
                                   "questions_people_ask": [q["question"] for q in c.read("15_questions.json", default=[])][:30],
                                   "searches_rivals_get_we_missed": read_csv(c.path("15_keyword_gap.csv"))[:20] if c.has("15_keyword_gap.csv") else []})
    cmap = {cl["id"]: cl for cl in clusters}
    pages = []
    used_clusters = set()
    for p in out.pages:
        cl = cmap.get(p.cluster_id, {})
        if p.cluster_id in used_clusters:
            cl = {}  # a second page on the same search would compete with the first: it is a support page with no target keyword
        elif cl:
            used_clusters.add(p.cluster_id)
        pages.append(p.model_dump() | {"head": cl.get("head", ""), "volume": cl.get("volume", 0), "kd": cl.get("kd", ""), "intent": cl.get("intent", "")})
    c.write("19_sitemap.json", {"pages": pages})
    # forecast: kept inside what Google can send (good case <= a set share of the reachable market), cases in order
    fc = {k: float(out.forecast_12m_usd.get(k, 0)) for k in ("low", "mid", "high")}
    fc_note = ""
    if fc["high"] > cap:
        fc_note = f"The good case was cut from ${fc['high']:,.0f} to ${cap:,.0f}: a new site is assumed to take at most {S.good_case_share:.0%} of the money reachable through Google search in year one (ASSUMPTION)."
        fc["high"] = round(cap)
    fc["mid"] = min(fc["mid"], fc["high"])
    fc["low"] = min(fc["low"], fc["mid"])
    tl = timeline(offer, fc["mid"], market)
    ue = c.read("16_unit_economics.json")
    ue["ladder"] = tl["steps"]
    c.write("16_unit_economics.json", ue)
    # 90-day calendar from the day building may start (after the validation test when the plan is test-first):
    # easiest (lowest KD) first, home + money page in week 1, ~2-3 pages a week, link outreach alongside
    order = sorted(pages, key=lambda p: (p["page_type"] not in ("home", "money"), num(p["kd"], 50)))
    cal, start = [], dt.date.fromisoformat(tl["live"])
    for i, p in enumerate(order):
        week = 1 if p["page_type"] in ("home", "money") else min(1 + (i // 3) + 1, 13)
        cal.append({"week": week, "date": (start + dt.timedelta(weeks=week - 1)).isoformat(), "type": "page", "item": p["url_slug"],
                    "keyword": p["head"], "kd": p["kd"], "data_source": p["unique_data_source"]})
    for i, l in enumerate(links[:52]):
        week = 3 + i // 4
        if week > 13:
            break
        cal.append({"week": week, "date": (start + dt.timedelta(weeks=week - 1)).isoformat(), "type": "link outreach",
                    "item": l["domain"], "keyword": "", "kd": "", "data_source": f"DR {l['dr']}, links to {l['links_to_n']} competitors"})
    cal.append({"week": 4, "date": (start + dt.timedelta(weeks=3)).isoformat(), "type": "link bait", "item": out.link_bait_asset, "keyword": "", "kd": "", "data_source": ""})
    for i, a in enumerate(out.ai_search_plan):
        cal.append({"week": 2, "date": (start + dt.timedelta(weeks=1)).isoformat(), "type": "ai search", "item": a, "keyword": "", "kd": "", "data_source": ""})
    cal.sort(key=lambda r: (r["week"], r["type"]))
    write_csv(c.path("19_seo_calendar_90d.csv"), cal, ["week", "date", "type", "item", "keyword", "kd", "data_source"])
    store.set_data(c.slug, advantage_score=out.advantage_score, advantage_reason=out.advantage_reason, forecast_12m_usd=fc, forecast_note=fc_note, timeline=tl)
    test_md = (f"{test['test']}: {test['sample']}; {test['days']} days{' after ' + str(test['warmup_days']) + ' days of warm-up' if test.get('warmup_days') else ''}; "
               f"budget ${test['budget_usd']:g}. PASS if: {test['pass_threshold']}. KILL if: {test['kill_threshold']}.") if test else "none planned"
    plan_md = f"""# Business plan: {c.slug}
**Why us (5 seconds):** {out.why_us_5_seconds}

## Product line
{chr(10).join('- ' + x for x in out.product_line)}
- Free hook: {out.free_hook}
- Upsell: {out.upsell}

## The validation test{' (comes first: nothing is built before it ends)' if tl['test_first'] else ''}
{test_md}

## 12-month forecast
Low ${fc['low']:,.0f} | Mid ${fc['mid']:,.0f} | High ${fc['high']:,.0f}
Assumptions: {out.forecast_assumptions}
{fc_note}

## Steps and dates (worked out from the test and the forecast)
{md_table(tl['steps'], ['goal', 'by'])}
## Edge: {out.advantage_score}/5
{out.advantage_reason}

## Pages ({len(pages)})
{md_table(pages, ['page_type', 'url_slug', 'title', 'head', 'volume', 'kd', 'unique_data_source'])}
## Link bait
{out.link_bait_asset}

## AI search plan
{chr(10).join('- ' + x for x in out.ai_search_plan)}
"""
    c.write("19_business_plan.md", plan_md)
    need = min(20, len(clusters))
    sources = [p["unique_data_source"].strip().lower() for p in pages]
    dup_src = len(sources) - len(set(sources))
    templ = [_template_title(p["title"], p["head"]) for p in pages if p["head"]]
    dup_tpl = len(templ) - len(set(templ))
    targeted = sum(1 for p in pages if p["head"])
    summary = (f"{len(pages)} pages planned ({targeted} with their own search, {len(pages) - targeted} support pages); "
               f"edge {out.advantage_score}/5; forecast mid ${fc['mid']:,.0f}/yr")
    bad = []
    if len(pages) < need:
        bad.append(f"only {len(pages)} pages; plan at least {need}")
    if dup_src > len(pages) * 0.2 or dup_tpl > len(pages) * 0.3:
        bad.append(f"pages differ only by keyword ({dup_src} repeated data sources, {dup_tpl} template titles)")
    if any(cl["intent"] in BUYING for cl in clusters):
        for p in pages:
            if p["page_type"] in ("home", "money") and p["head"] and p["intent"] not in BUYING:
                bad.append(f"the {p['page_type']} page targets \"{p['head']}\" (intent {p['intent']}); it must target a buying search")
    bad += checks.text_problems({"plan": "\n".join([out.why_us_5_seconds, out.free_hook, out.upsell, out.forecast_assumptions, out.link_bait_asset, out.advantage_reason]
                                                    + out.product_line + out.ai_search_plan + [p.unique_data_source + " " + p.title for p in out.pages])},
                                offer, market, mkt["bottom_up_usd_year"])
    if bad and c.attempt < 3:
        return Result("redo", "; ".join(bad[:6]))
    if bad:
        return Result("fail", summary + "; still wrong after 3 tries: " + "; ".join(bad[:3]))
    if targeted < 20:
        return Result("fail", summary + f"; only {targeted} pages have their own search (the bar is 20): the topic is too narrow for a 20-page site")
    return Result("pass", summary)

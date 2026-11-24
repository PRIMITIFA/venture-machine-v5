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
class ModelOption(BaseModel):
    model: str = Field(description="e.g. one-time report, monthly subscription, B2B plan, API, own data vs reseller")
    price_usd: float
    conversion_pct: float = Field(description="visitor -> buyer %, with reasoning in 'sources'")
    retention_months: float = Field(description="1 for one-time")
    sales_per_month_at_1000_visits: float
    owner_hours_per_month: float
    sources: list[str]


class Swot(BaseModel):
    options: list[ModelOption] = Field(min_length=3)
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]
    conclusions: list[str] = Field(min_length=3, max_length=3)


def economics(price, data_cost, fee_pct, fee_fixed, conversion_pct, retention_months, cpc):
    net = price - data_cost - price * fee_pct / 100 - fee_fixed
    max_cac = net * retention_months
    breakeven_cpc = net * retention_months * conversion_pct / 100
    paid_cac = cpc / (conversion_pct / 100) if conversion_pct else None
    return {"net_per_sale": round(net, 2), "max_cac": round(max_cac, 2), "breakeven_cpc": round(breakeven_cpc, 2),
            "paid_search_cac": round(paid_cac, 2) if paid_cac else None}


def ladder(mvp_days):
    t = dt.date.today()
    steps = [("launched", mvp_days), ("indexed", mvp_days + 14), ("100 organic visits/mo", mvp_days + 60),
             ("first $1", mvp_days + 30), ("$100/mo", mvp_days + 90), ("$1,000/mo", mvp_days + 180)]
    return [{"goal": g, "by": (t + dt.timedelta(days=d)).isoformat()} for g, d in steps]


def b16_economics(c):
    costs = c.read("15_costs.json")
    caps = costs["budget_caps"]
    pay = next((s for s in PRICES["stack"] if "fee_pct" in s), {"fee_pct": 5.0, "fee_fixed_usd": 0.4})
    kws = read_csv(c.path("08_keywords_clean.csv"))
    buy_cpcs = [num(k["cpc"]) for k in kws if k["intent"] in ("buy", "competitor", "brand-model") and num(k["cpc"]) > 0]
    avg_cpc = round(sum(buy_cpcs) / len(buy_cpcs), 2) if buy_cpcs else 1.0
    ctx = {"costs": costs, "scorecard": c.read("05_scorecard.json"), "market": c.read("14_market_analysis.json"),
           "shortlist": read_csv(c.path("11_shortlist.csv"))[:25], "competitor_business": c.read("13_competitor_business.json"),
           "avg_buying_cpc_usd": avg_cpc, "payment_fees": pay}
    out = ai.ask_json(
        f"""Block 16. Business case for: {c.v['one_liner']}
1) Give at least 3 model options (one-time vs subscription vs B2B vs API; own data vs reseller) with price, conversion %,
retention months, sales per 1,000 visits, owner hours/month and sources. Python computes the money.
2) SWOT: EVERY line must contain a number or a source URL. 3) Exactly 3 conclusions.{c.note()}""",
        Swot, smart=True, context=ctx)
    opts = []
    for o in out.options:
        e = economics(o.price_usd, caps["data_cost_per_sale_usd"], pay["fee_pct"], pay["fee_fixed_usd"], o.conversion_pct, o.retention_months, avg_cpc)
        profit_month = e["net_per_sale"] * o.sales_per_month_at_1000_visits - caps["fixed_cost_usd_month"]
        e["profit_per_hour_at_1000_visits"] = round(profit_month / max(o.owner_hours_per_month, 1), 2)
        opts.append(o.model_dump() | e)
    best = max(opts, key=lambda o: o["profit_per_hour_at_1000_visits"])
    mvp = c.v["data"].get("mvp_days") or 14
    ue = {"chosen": best, "options": opts, "avg_buying_cpc_usd": avg_cpc, "ladder": ladder(int(mvp)),
          "formulas": {"net_per_sale": "price - data cost - fees", "max_cac": "net x retention months",
                       "breakeven_cpc": "net x retention x conversion", "paid_search_cac": "avg buying CPC / conversion"}}
    store.set_data(c.slug, unit_economics={k: best[k] for k in ("model", "price_usd", "net_per_sale", "max_cac", "breakeven_cpc", "paid_search_cac")})
    c.write("16_unit_economics.json", ue)
    lines = out.strengths + out.weaknesses + out.opportunities + out.threats
    missing = [l for l in lines if not has_number_or_source(l)]
    mk = lambda xs: "\n".join(f"- {x}" for x in xs)
    c.write("18_swot.md", f"# SWOT: {c.slug}\n\n## Strengths\n{mk(out.strengths)}\n\n## Weaknesses\n{mk(out.weaknesses)}\n\n"
                          f"## Opportunities\n{mk(out.opportunities)}\n\n## Threats\n{mk(out.threats)}\n\n## 3 conclusions\n{mk(out.conclusions)}\n")
    c.write("18_business_case.md", f"""# Business case: {c.slug}
{c.v['one_liner']}

## Chosen model: {best['model']}
- Price ${best['price_usd']} | net per sale ${best['net_per_sale']} | max CAC ${best['max_cac']} | break-even CPC ${best['breakeven_cpc']}
- Paid search CAC at avg buying CPC ${avg_cpc}: ${best['paid_search_cac']}
- Profit per owner hour at 1,000 visits/mo: ${best['profit_per_hour_at_1000_visits']}

## All options
{md_table(opts, ['model', 'price_usd', 'conversion_pct', 'retention_months', 'net_per_sale', 'max_cac', 'breakeven_cpc', 'profit_per_hour_at_1000_visits'])}
## Goal ladder
{md_table(ue['ladder'], ['goal', 'by'])}
""")
    summary = f"{best['model']} at ${best['price_usd']}: net ${best['net_per_sale']}/sale, max CAC ${best['max_cac']}, paid CAC ${best['paid_search_cac']}"
    if missing:
        return Result("redo", f"{len(missing)} SWOT lines have no number or source, e.g. '{missing[0][:80]}'")
    if best["net_per_sale"] <= 0:
        return Result("kill", summary + "; loses money on every sale")
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


def b17_plan(c):
    clusters = c.read("10_clusters_serp.json")
    links = read_csv(c.path("15_link_targets.csv"))
    cl_info = [{"id": cl["id"], "head": cl["head"], "keywords": cl["keywords"][:8], "volume": cl["volume"], "intent": cl["intent"],
                "kd": cl.get("kd"), "winning_format": cl["winning_format"], "weak_spots": cl["weak_spots"]} for cl in clusters[:60]]
    out = ai.ask_json(
        f"""Block 17. Product and SEO plan for: {c.v['one_liner']}
1) Product line that fills the gaps from block 11 (not a copy), a free hook, an upsell, a 5-second 'why us', and a
12-month revenue forecast low/mid/high with assumptions.
2) Sitemap: home page on the strongest keyword, 1 page = 1 cluster (use cluster_id), money page on the strongest buying
intent. Plan at least 20 pages (or one per cluster if fewer). EVERY page needs its own unique data source - pages that only
swap the keyword in a template are not allowed.
3) One link-bait asset and the AI-search plan. 4) Rate our edge 1-5.{c.note()}""",
        Plan, smart=True, context={"clusters": cl_info, "business_case": c.read("18_business_case.md"),
                                   "eeat": c.read("03_eeat_quality.json"), "gap": c.read("13_competitor_business.json").get("identified_gap"),
                                   "ux_weaknesses": [x.get("weaknesses") for x in c.read("12_competitor_ux.json")["competitors"]]})
    cmap = {cl["id"]: cl for cl in clusters}
    pages = []
    for p in out.pages:
        cl = cmap.get(p.cluster_id, {})
        pages.append(p.model_dump() | {"head": cl.get("head", ""), "volume": cl.get("volume", 0), "kd": cl.get("kd", ""), "intent": cl.get("intent", "")})
    c.write("19_sitemap.json", {"pages": pages})
    # 90-day calendar: easiest (lowest KD) first, home + money page in week 1, ~2-3 pages a week, link outreach alongside
    order = sorted(pages, key=lambda p: (p["page_type"] not in ("home", "money"), num(p["kd"], 50)))
    cal, start = [], dt.date.today()
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
    store.set_data(c.slug, advantage_score=out.advantage_score)
    c.write("19_business_plan.md", f"""# Business plan: {c.slug}
**Why us (5 seconds):** {out.why_us_5_seconds}

## Product line
{chr(10).join('- ' + x for x in out.product_line)}
- Free hook: {out.free_hook}
- Upsell: {out.upsell}

## 12-month forecast
Low ${out.forecast_12m_usd.get('low', 0):,.0f} | Mid ${out.forecast_12m_usd.get('mid', 0):,.0f} | High ${out.forecast_12m_usd.get('high', 0):,.0f}
Assumptions: {out.forecast_assumptions}

## Edge: {out.advantage_score}/5
{out.advantage_reason}

## Pages ({len(pages)})
{md_table(pages, ['page_type', 'url_slug', 'title', 'head', 'volume', 'kd', 'unique_data_source'])}
## Link bait
{out.link_bait_asset}

## AI search plan
{chr(10).join('- ' + x for x in out.ai_search_plan)}
""")
    need = min(20, len(clusters))
    sources = [p["unique_data_source"].strip().lower() for p in pages]
    dup_src = len(sources) - len(set(sources))
    templ = [_template_title(p["title"], p["head"]) for p in pages if p["head"]]
    dup_tpl = len(templ) - len(set(templ))
    summary = f"{len(pages)} pages planned; edge {out.advantage_score}/5; forecast mid ${out.forecast_12m_usd.get('mid', 0):,.0f}/yr"
    if len(pages) < need:
        return Result("redo", f"only {len(pages)} pages; plan at least {need}")
    if dup_src > len(pages) * 0.2 or dup_tpl > len(pages) * 0.3:
        return Result("redo", f"pages differ only by keyword ({dup_src} repeated data sources, {dup_tpl} template titles)")
    if len(clusters) < 20:
        return Result("warn", summary + f"; only {len(clusters)} clusters exist (want >= 20)")
    return Result("pass", summary)

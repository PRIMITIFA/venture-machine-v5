"""Consistency checks: the report must say one thing in every part.

`text_problems` looks at words the AI wrote (plan, SWOT, rules, to-dos, questions). `consistency` runs before gate 3 and
also checks the numbers against each other. Any problem = the report is NOT CONSISTENT and GO / TEST are refused.
"""
import datetime as dt
import json
import re

from . import store
from .config import S
from .util import num, read_csv

OLD_RULE = re.compile(r"(first[- ]year|year[- ]?1|year[- ]one|annual|revenue|sales) goal|goal of \$|\$[\d,.]+k? (a year |year-1 )?goal|% of the (\$[\d,]+ )?(year-1 )?goal", re.I)
RAW_ERROR = re.compile(r"Traceback|Service Unavailable|oauth2\.|\b50[0-9]{1,3} Server error|DFSError|`POST |internal_failure", re.I)
EURO = re.compile(r"€|\bEUR\b")
TEST_DAYS = re.compile(r"(\d+)[- ]days?[- ](?:pre-?sale|test|gate|validation|trial run)", re.I)
BUY_PAGE_TYPES = ("home", "money")


def reachable_clicks(mk):
    """Clicks a month the top results get from our buying searches (the most a search business can win)."""
    if mk.get("clicks_month") is not None:
        return num(mk["clicks_month"])
    return num(mk.get("buying_searches_month")) * 0.65 * num(mk.get("aio_click_factor"), 1)


def market_year(c, mk=None):
    """THE search market number: money reachable through Google search a year, at the chosen price when there is one."""
    mk = mk or c.read("14_market_analysis.json")
    price = num((c.v["data"].get("offer") or {}).get("price_usd") or (c.v["data"].get("unit_economics") or {}).get("price_usd"))
    used = num(mk.get("price_used_usd") or mk.get("typical_price_usd"))
    return mk["bottom_up_usd_year"] * price / used if used and price else mk["bottom_up_usd_year"]


def _fmt(n):
    return {format(int(round(n)), ","), str(int(round(n)))}


def text_problems(texts, offer=None, market=None, market_raw=None):
    """texts = {name: text the AI wrote}. Returns plain sentences, each naming the place and the problem."""
    out = []
    test = (offer or {}).get("test") or {}
    for name, t in texts.items():
        t = t or ""
        if (m := OLD_RULE.search(t)):
            out.append(f"{name} measures against a sales goal (\"{m.group(0)}\"); the machine has no sales goals, only the market size bar")
        if (m := RAW_ERROR.search(t)):
            out.append(f"{name} contains raw error text (\"{m.group(0)}\")")
        if (m := EURO.search(t)):
            out.append(f"{name} uses euros near \"{t[max(0, m.start() - 30):m.start() + 12].strip()}\"; every amount must be in USD")
        if market is not None and market_raw is not None and abs(market - market_raw) > 1:
            for f in _fmt(market_raw):
                if re.search(r"\$%s\b" % re.escape(f), t):
                    out.append(f"{name} gives the search market as ${f} a year; the one number is ${market:,.0f} a year (at the chosen price)")
                    break
        if offer:
            if offer.get("payment") == "subscription" and (m := re.search(r"one-time (payments? )?only|no subscriptions?\b|never (a )?subscription", t, re.I)):
                out.append(f"{name} says \"{m.group(0)}\" but the chosen offer is a subscription")
            if offer.get("payment") == "one-time" and (m := re.search(r"subscriptions? only|no one-time", t, re.I)):
                out.append(f"{name} says \"{m.group(0)}\" but the chosen offer is a one-time payment")
        if test.get("days"):
            for m in TEST_DAYS.finditer(t):
                if int(m.group(1)) not in (int(test["days"]), int(test.get("warmup_days") or 0), int(test["days"]) + int(test.get("warmup_days") or 0)):
                    out.append(f"{name} mentions a \"{m.group(0)}\" but the one validation test runs {test['days']} days")
                    break
    return out


def consistency(c):
    """Everything checked before gate 3. Returns a list of problems (empty = consistent)."""
    d, out = c.v["data"], []
    mk = c.read("14_market_analysis.json", default=None)
    ue = c.read("16_unit_economics.json", default=None)
    offer = d.get("offer") or {}
    if not (mk and ue and offer):
        return ["the offer, the market or the money step is missing: run the steps again"]
    market, raw = market_year(c, mk), mk["bottom_up_usd_year"]
    # one price in every part
    prices = {"offer": offer.get("price_usd"), "money step": (ue.get("chosen") or {}).get("price_usd"), "decision data": d.get("chosen_price_usd"),
              "market step": mk.get("chosen_price_usd")}
    if len({round(num(p), 2) for p in prices.values()}) > 1:
        out.append("the price is not the same in every part: " + ", ".join(f"{k} ${v}" for k, v in prices.items()))
    if abs(num(mk.get("bottom_up_at_chosen_price_usd_year")) - market) > 2:
        out.append(f"the market step stores ${num(mk.get('bottom_up_at_chosen_price_usd_year')):,.0f} a year but the chosen price gives ${market:,.0f}")
    # forecast inside the reachable market
    fc = d.get("forecast_12m_usd") or {}
    if fc:
        if not (num(fc.get("low")) <= num(fc.get("mid")) <= num(fc.get("high"))):
            out.append(f"forecast cases are out of order: bad {fc.get('low')}, likely {fc.get('mid')}, good {fc.get('high')}")
        if offer.get("channel") == "google search" and num(fc.get("high")) > market * S.good_case_share + 1:
            out.append(f"the good case (${num(fc.get('high')):,.0f}) is more than {S.good_case_share:.0%} of the money reachable through Google search (${market:,.0f})")
    # profit per hour must not assume more visitors than exist
    ch = ue.get("chosen") or {}
    if num(ch.get("visits_used")) > max(reachable_clicks(mk), 1) + 1 and offer.get("channel") == "google search":
        out.append(f"profit per hour assumes {num(ch.get('visits_used')):,.0f} visitors a month; only {reachable_clicks(mk):,.0f} clicks are reachable")
    # dates: nothing before the test ends; money steps only where the forecast gets there
    tl = d.get("timeline") or {}
    cal = read_csv(c.path("19_seo_calendar_90d.csv")) if c.has("19_seo_calendar_90d.csv") else []
    if tl.get("test_first") and tl.get("build_from"):
        early = [r for r in cal if r["date"] < tl["build_from"]]
        if early:
            out.append(f"{len(early)} calendar items are dated before the validation test ends ({tl['build_from']})")
    month12 = num(d.get("forecast_basis_usd") or fc.get("mid")) * 12 / 78 if fc else 0  # month-12 run rate of a straight ramp
    for st in ue.get("ladder") or []:
        m = re.match(r"\$([\d,]+)\s*a month", st.get("goal", ""))
        if m and re.match(r"\d{4}-\d\d-\d\d", st.get("by", "")) and num(m.group(1).replace(",", "")) > month12 + 1:
            out.append(f"the step \"{st['goal']}\" has a date, but the forecast only reaches about ${month12:,.0f} a month by month 12")
    # pages: same list in the plan and the calendar; main pages on buying searches; no thrown-out search as a target
    sm = c.read("19_sitemap.json", default={"pages": []})["pages"]
    cal_pages = {r["item"] for r in cal if r["type"] == "page"}
    if cal and cal_pages != {p["url_slug"] for p in sm}:
        out.append(f"the calendar has {len(cal_pages)} pages but the plan has {len(sm)}")
    dropped = {r["keyword"].lower() for r in (read_csv(c.path("08_keywords_dropped.csv")) if c.has("08_keywords_dropped.csv") else [])}
    for p in sm:
        if p.get("head", "").lower() in dropped:
            out.append(f"page {p['url_slug']} targets \"{p['head']}\", a search that was thrown out as off-topic")
    clusters = c.read("10_clusters_serp.json", default=[])
    if any(cl["intent"] in ("buy", "competitor", "brand-model") for cl in clusters):
        for p in sm:
            if p["page_type"] in BUY_PAGE_TYPES and p.get("head") and p.get("intent") in ("info", "brand"):
                kind = "a rival's name" if p["intent"] == "brand" else "a learning search"
                out.append(f"the {p['page_type']} page targets \"{p['head']}\" ({kind}), not a buying search")
    # words: every text the AI wrote, and every step's one-line result
    texts = {"SWOT": c.read("18_swot.md", default=""), "plan": c.read("19_business_plan.md", default=""),
             "rules": "\n".join((c.read("15_costs.json", default={}) or {}).get("guardrails") or []),
             "to-do list": json.dumps((c.read("15_costs.json", default={}) or {}).get("owner_todo") or [], ensure_ascii=False),
             "owner questions": "\n".join((c.read("15_costs.json", default={}) or {}).get("owner_questions") or [])}
    out += text_problems(texts, offer, market, raw)
    for bid, st in sorted(store.blocks(c.slug).items()):
        s = st.get("summary") or ""
        if bid != "18" and (OLD_RULE.search(s) or RAW_ERROR.search(s)):
            out.append(f"step {bid}'s result line still carries an old rule or raw error text")
    seen = []
    return [x for x in out if not (x in seen or seen.append(x))]

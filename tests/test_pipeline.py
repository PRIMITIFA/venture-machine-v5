"""Offline end-to-end test: fake AI + fake DataForSEO + fake web, all 18 blocks, gates, caps.

Run: python -m unittest discover -s tests -v
"""
import os
import pathlib
import random
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = pathlib.Path(tempfile.mkdtemp(prefix="vm-test-"))
import atexit  # noqa: E402
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))  # every test class shares the folder
os.environ.update(VM_SPEND_FILE=str(TMP / "spend.json"), VM_DAY_MAX_USD="1000")
os.environ.update(VM_DATA_DIR=str(TMP / "data"), VM_VENTURES_DIR=str(TMP / "ventures"), VM_AI_PROVIDER="fake",
                  DATAFORSEO_LOGIN="x", DATAFORSEO_PASSWORD="y", VM_MAX_USD_PER_IDEA="5", VM_PHASE1_MAX_USD="0.5")

from vm import ai, budget, pipeline, seo, store, web  # noqa: E402
from vm.blocks import phase2, phase4  # noqa: E402

rnd = random.Random(7)
WORDS = ["window sticker", "vin decoder", "car history", "build sheet", "monroney label", "original msrp", "options list",
         "factory options", "sticker lookup", "dealer invoice", "trim lookup", "spec sheet"]
KWS = [f"{w} {m}".strip() for w in WORDS for m in ("", "free", "by vin", "online", "price")]
DOMAINS = [f"comp{i}.com" for i in range(1, 9)] + ["reddit.com", "smallblog.net"]


def fake_post(endpoint, task):
    budget.check(seo.EST.get(endpoint, 0.05))
    budget.record("dataforseo", endpoint, seo.EST.get(endpoint, 0.05) / 2)
    if endpoint.endswith("search_volume/live"):
        return [{"keyword": k, "search_volume": rnd.randint(30, 5000), "cpc": round(rnd.uniform(0.5, 6), 2), "competition": "HIGH",
                 "low_top_of_page_bid": 0.5, "high_top_of_page_bid": 4.0,
                 "monthly_searches": [{"year": 2026, "month": m, "search_volume": 100 + m * 5} for m in range(1, 13)]} for k in task["keywords"]]
    if endpoint.endswith("keyword_suggestions/live"):
        return [{"items": [{"keyword": f"{task['keyword']} {s}", "keyword_info": {"search_volume": 200, "cpc": 2.5}} for s in ("near me", "cost", "report")]}]
    if endpoint.endswith("google_trends/explore/live"):
        return [{"items": [{"type": "google_trends_graph", "keywords": task["keywords"],
                            "data": [{"date_from": f"d{i}", "values": [50 + i // 10 for _ in task["keywords"]]} for i in range(260)]}]}]
    if endpoint.endswith("organic/live/advanced"):
        k = task["keyword"]
        base = sorted(DOMAINS, key=lambda d: hash((d, k[:6])) % 97)
        items = [{"type": "organic", "rank_group": i + 1, "domain": d, "url": f"https://{d}/{k[:10].replace(' ', '-')}" if i > 3 else f"https://{d}/",
                  "title": f"{k} tool" if i == 2 else f"{k} guide"} for i, d in enumerate(base)]
        items += [{"type": "paid", "domain": "comp1.com", "title": "Get your sticker", "description": "From $9"}, {"type": "people_also_ask", "items": [{"title": "How do I find my window sticker?"}, {"title": "Is a window sticker free?"}]},
                  {"type": "ai_overview", "items": [{"type": "ai_overview_element", "references": [{"domain": "www.comp2.com", "url": "https://comp2.com"}]}]}]
        return [{"items": items}]
    if endpoint.endswith("bulk_keyword_difficulty/live"):
        return [{"items": [{"keyword": k, "keyword_difficulty": rnd.randint(0, 45)} for k in task["keywords"]]}]
    if endpoint.endswith("bulk_ranks/live"):
        return [{"items": [{"target": d, "rank": 15 if d == "smallblog.net" else rnd.randint(25, 70)} for d in task["targets"]]}]
    if endpoint.endswith("bulk_traffic_estimation/live"):
        return [{"items": [{"target": d, "metrics": {"organic": {"etv": 40000, "count": 900}}} for d in task["targets"]]}]
    if endpoint.endswith("relevant_pages/live"):
        return [{"items": [{"page_address": f"https://{task['target']}/free-tool", "metrics": {"organic": {"etv": 900, "count": 40}}}]}]
    if endpoint.endswith("backlinks/summary/live"):
        return [{"rank": 35, "backlinks": 5000, "referring_domains": 400}]
    if endpoint.endswith("referring_domains/live"):
        return [{"items": [{"domain": f"ref{i}.org", "rank": 60 - i, "backlinks": 3} for i in range(40)]}]
    if endpoint.endswith("domain_rank_overview/live"):
        return [{"items": [{"metrics": {"organic": {"etv": 12000, "count": 800, "estimated_paid_traffic_cost": 9000, "pos_1": 5, "pos_2_3": 9}}}]}]
    if endpoint.endswith("historical_rank_overview/live"):
        return [{"items": [{"year": 2026, "month": m, "metrics": {"organic": {"etv": 1000 + m * 50}}} for m in range(1, 13)]}]
    if endpoint.endswith("ranked_keywords/live"):
        return [{"items": [{"keyword_data": {"keyword": f"window sticker {w}", "keyword_info": {"search_volume": 300, "cpc": 2}, "keyword_properties": {"keyword_difficulty": 12}},
                            "ranked_serp_element": {"serp_item": {"rank_group": 4}}} for w in ("pdf", "lookup ford", "unrelated")]
                 + [{"keyword_data": {"keyword": "pizza near me", "keyword_info": {"search_volume": 9000}}, "ranked_serp_element": {"serp_item": {"rank_group": 2}}}]}]
    if endpoint.endswith("whois/overview/live"):
        return [{"items": [{"domain": d, "created_datetime": "2020-01-01 00:00:00 +00:00"} for d in task["filters"][0][2]]}]
    if endpoint.endswith("lighthouse/live/json"):
        return [{"categories": {"performance": {"score": 0.42}}}]
    if endpoint.endswith("llm_responses/live"):
        return [{"items": [{"type": "message", "sections": [{"type": "text", "text": "Try comp1.com or BestSnap.",
                                                            "annotations": [{"url": "https://comp1.com/x"}, {"url": "https://bestsnap.io/"}]}]}],
                 "search_results": [{"url": "https://reddit.com/r/x"}]}]
    if endpoint.endswith("aggregated_metrics/live"):
        return [{"total": {"sources_domain": [{"key": "www.reddit.com", "mentions": 40}], "brand_entities_title": [], "platform": [{"key": "google", "mentions": 40}]}}]
    raise AssertionError(endpoint)


def fake_fetch(url, timeout=20):
    html = "<html><head><title>Comp</title><meta name=\"viewport\"></head><body><a href='/pricing'>Pricing</a> $19 per month refund contact us</body></html>"
    return {"url": url if url.startswith("http") else "https://" + url, "status": 200, "ms": 300, "bytes": len(html), "html": html, "error": ""}


OPTIONS = [("one-time", 15, "one-time", "used car buyers", "google search", True, 1), ("sub", 29, "subscription", "used car buyers", "google search", True, 4),
           ("b2b", 199, "subscription", "car dealers", "cold email", False, 8)]
CASE_RULES = ["no OEM logos"]


def fake_ai(task, cls, web_, model):
    n = cls.__name__
    comp = lambda i: {"name": f"Comp{i}", "url": f"https://comp{i}.com", "price": "$19", "pricing_model": "one-time", "source_url": f"https://comp{i}.com/pricing"}
    ok = {"answer": "yes", "ok": True}
    data = {
        "Intake": {"one_liner": "People buying used cars want the window sticker and would pay $15", "payer": "used car buyers",
                   "product": "window sticker PDF", "clear": True, "key_terms": ["window sticker", "vin decoder", "build sheet"]},
        "How": {"competitors": [comp(i) for i in range(1, 4)], "revenue_models": ["one-time"],
                "data_sources": [{"name": "OEM API", "type": "api"}], "validation_question": "Will buyers pay $15?",
                "delivered_digitally": True, "legal": True, "needs_physical_logistics": False,
                "eeat": {"real_person_or_company": ok, "expertise_proof": ok, "unique_data_per_page": ok,
                         "contacts_policies_real_example": ok, "ymyl_level": "low"}},
        "Pulse": {"rising_synonyms": ["monroney label"], "new_competitors_12m": ["https://new.com"], "fresh_discussions_90d": ["https://reddit.com/r/x/1"]},
        "Scorecard": {"pros": ["a"] * 5, "cons": ["b"] * 5, "biggest_unknown": "conversion", "summary_3_lines": ["1", "2", "3"],
                      "effort": {"days_to_mvp": 7, "monthly_cost_usd": 30, "api_dependencies": ["x"], "owner_hours_per_week": 5},
                      "ice": {"impact": 7, "confidence": 6, "ease": 8, "impact_why": "many buyers"}, "synergy": "cold email", "blockers": [],
                      "other_angle": {"idea": "Car dealers want bulk window sticker PDFs for their listings and would pay $49 a month",
                                      "why": "dealers buy many at once", "cheapest_test": "cold email 100 dealers"}},
        "Seeds": {"seeds": [{"keyword": k, "category": "buy" if i % 2 else "product", "source": "t"} for i, k in enumerate(KWS[:45])]},
        "Ux": {"competitors": [{"domain": d, "steps_to_checkout_estimate": 5, "weaknesses": ["no sample"], "strengths": ["fast"]} for d in DOMAINS]},
        "Business": {"competitors": [{"domain": "comp1.com", "plans": [{"name": "Basic", "price": "$19", "billing": "one-time"}], "free_tier": "no",
                                      "upsells": [], "b2b_or_api": "no", "checkout_provider": "stripe", "trial_refunds": "30d",
                                      "affiliate_or_ads_networks": "none", "source_urls": ["https://comp1.com/pricing"]}],
                     "long_running_ads": [], "audience_quotes": [{"quote": "too expensive", "url": "https://reddit.com/x"}],
                     "identified_gap": "nobody offers a free preview", "competitors_cheaper_than_our_data_cost_and_better_data": False, "reason": "-"},
        "Market": {"top_down_usd_year": 3_000_000, "top_down_method": "buyers x price", "top_down_sources": ["https://x"], "typical_price_usd": 19,
                   "segments": [{"name": "dealers", "size_note": "40k", "pain_quotes": [], "underserved": True}],
                   "underserved_countries_or_segments": ["UK"], "growth_direction": "growing", "growth_evidence": "x"},
        "Costs": {"tools": [{"name": "Workers", "purpose": "host", "cost_start_usd_month": 5, "cost_10x_usd_month": 20, "limit": "100k/day", "account_owner": "owner"}],
                  "data_cost_per_sale_usd": 2.0, "marketing": [{"channel": "cold email", "cost": "$50/mo", "cap": "300/day", "pass_threshold": ">=3% replies", "kill_threshold": "<1%"}],
                  "guardrails": ["no OEM logos"], "access": ["DataForSEO: owner"], "owner_todo": [{"task": "buy domain", "why": "site", "minutes": 5}],
                  "owner_questions": ["Which country first?"]},
        "Options": {"options": [{"model": m, "price_usd": p, "payment": pay, "payer": who, "channel": ch, "same_buyer_and_channel": same,
                                 "conversion_pct": 2, "retention_months": r, "sales_per_month_at_1000_visits": 20, "owner_hours_per_month": 20,
                                 "delivery_cost_per_sale_usd": 2.0, "extra_fixed_cost_usd_month": 0, "build_days": 7, "assumptions": ["conversion 2%: ASSUMPTION"],
                                 "sources": ["https://x"]}
                                for m, p, pay, who, ch, same, r in OPTIONS]},
        "Case": {"strengths": ["3 competitors at $19"], "weaknesses": ["DR 0 today"], "opportunities": ["UK 12k searches"], "threats": ["https://x.com new player"],
                 "conclusions": ["a", "b", "c"], "guardrails": CASE_RULES, "owner_todo": [{"task": "buy domain", "why": "site", "minutes": 5}],
                 "owner_questions": ["Which country first?"],
                 "validation_test": {"test": "pre-sale", "why": "cheapest proof", "sample": "200 visitors from the 3 easiest pages", "warmup_days": 0, "days": 14,
                                     "budget_usd": 100, "pass_threshold": ">= 5 paid pre-orders", "kill_threshold": "0 paid pre-orders", "setup_steps": ["page", "button"]}},
        "OnTopic": {"keep": list(range(60))},
        "Picks": {"picks": [{"slug": "sticker-pro", "why": "sells window stickers to the same car buyers", "closeness": 3}]},
        "Plan": {"product_line": ["sticker PDF"], "free_hook": "free preview", "upsell": "dealer plan", "why_us_5_seconds": "instant",
                 "forecast_12m_usd": {"low": 5000, "mid": 20000, "high": 60000}, "forecast_assumptions": "x",
                 "pages": [{"cluster_id": i, "url_slug": f"p{i}", "title": f"Page {i} unique angle {i * 7}", "page_type": "data",
                            "unique_data_source": f"dataset {i}"} for i in range(1, 25)],
                 "link_bait_asset": "MSRP index", "ai_search_plan": ["llms.txt"], "advantage_score": 4, "advantage_reason": "price"},
        "QuickTest": {"test": "cold-email", "why": "cheap", "setup_steps": ["list", "send"], "budget_usd": 0, "days": 7,
                      "pass_threshold": ">=3%", "kill_threshold": "<1%"},
    }
    if n == "Labels":
        import json, re
        m = re.search(r'"keywords": (\[.*?\])', task, re.S)
        kws = json.loads(m.group(1)) if m else []
        return {"labels": [{"keyword": k, "intent": "buy" if i % 3 else "competitor", "junk": False} for i, k in enumerate(kws)]}
    if n == "SerpChecks":
        import json, re
        kws = re.findall(r'"keyword": "([^"]+)"', task)
        return {"checks": [{"keyword": k, "on_topic": k not in OFF_TOPIC, "intent": "brand" if k in BRAND_ONLY else "buy", "reason": "means something else on Google"} for k in kws]}
    if n == "RivalKinds":
        import re
        doms = re.findall(r'"domain": "([^"]+)"', task)
        return {"rivals": [{"domain": d, "kind": RIVAL_KIND.get(d, "direct"), "reason": "test"} for d in doms]}
    return data[n]


OFF_TOPIC, BRAND_ONLY, RIVAL_KIND = set(), set(), {}


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seo.post = fake_post
        web.fetch = fake_fetch
        web.sitemap = lambda d, max_children=5: {"found": True, "urls": 120, "oldest": "2019-01-01", "newest": "2026-01-01", "source": "", "note": ""}
        web.screenshots = lambda url, prefix: []
        ai.FAKE = fake_ai


    def test_full_run_with_gates(self):
        slug = pipeline.new("window sticker reports for used car buyers", country="us")
        self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_05")
        pipeline.gate(slug, "go")
        self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_14")
        pipeline.gate(slug, "go")
        self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_18")
        v = store.venture(slug)
        self.assertIn("gate3_score", v["data"])
        for f in ("01_intake.md", "02_how_analysis.json", "03_eeat_quality.json", "04_niche_pulse.json", "05_scorecard.json",
                  "06_seeds.csv", "08_keywords_clean.csv", "09_serp_raw.json", "10_clusters_serp.json", "11_shortlist.csv",
                  "11_top_competitors.json", "12_competitor_ux.json", "13_competitor_business.json", "13_competitor_ads.md",
                  "14_market_analysis.json", "15_competitor_seo.json", "15_ai_visibility.json", "15_keyword_gap.csv", "15_questions.json", "15_link_targets.csv", "GUARDRAILS.md", "ACCESS.md",
                  "OWNER-TODO.json", "16_owner_questions.md", "18_business_case.md", "18_swot.md", "19_business_plan.md",
                  "19_sitemap.json", "19_seo_calendar_90d.csv"):
            self.assertTrue((TMP / "ventures" / slug / f).exists(), f)
        self.assertLessEqual(store.spent(slug), 5)
        pipeline.gate(slug, "go")
        self.assertEqual(store.venture(slug)["status"], "approved_build")
        from vm import report, pdf
        self.assertTrue(report.write(slug).exists())
        h = pdf.build_html(slug)
        for part in ("FULL CHECK REPORT", "THE ANSWER", "The scorecard", "Is there demand?", "Who are you up against?",
                     "How big is the money?", "Will it make money?", "The plan", "Glossary", "Sources", "IN PLAIN WORDS",
                     "How hard is it to get onto Google", "How to rank: the plan", "Do AI assistants recommend you?"):
            self.assertIn(part, h)
        f, msg = pdf.write(slug)  # a real PDF if a browser is installed, else a clear message
        self.assertTrue(f is None or f.stat().st_size > 1000, msg)

    def test_quick_check_then_deepen(self):
        slug = pipeline.new("light check idea about window stickers", country="us", depth="light")
        self.assertEqual(pipeline.run(slug, say=lambda m: None), "light_done")
        v = store.venture(slug)
        self.assertIn("quick_score100", v["data"])
        self.assertEqual(store.block(slug, "10")["status"], "PENDING")  # no rival deep-dive in a quick check
        from vm import pdf
        h = pdf.build_html(slug)
        self.assertIn("QUICK CHECK REPORT", h)
        self.assertIn("vm deepen", h)
        before = store.spent(slug)
        self.assertLess(before, 0.5)
        pipeline.deepen(slug, "full")
        self.assertEqual(store.venture(slug)["data"]["depth"], "full")
        self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_14")  # gate 1 already passed by deepening

    def test_first_look_score_and_other_angle(self):
        weak = lambda task, cls, web_, model: (fake_ai(task, cls, web_, model) | {"ice": {"impact": 3, "confidence": 3, "ease": 4}}
                                               if cls.__name__ == "Scorecard" else fake_ai(task, cls, web_, model))
        ai.FAKE = weak
        try:
            slug = pipeline.new("weak consumer idea about sticker subscriptions", country="us")
            said = []
            self.assertEqual(pipeline.run(slug, say=said.append), "gate_05")
        finally:
            ai.FAKE = fake_ai
        v = store.venture(slug)
        self.assertEqual(v["data"]["first_score100"], 30)
        self.assertIn("First-look score 30/100", said[-1])
        self.assertIn(f"vm gate {slug} angle", said[-1])
        from vm import pdf
        h = pdf.build_html(slug)
        for part in ("WEAK AS IT IS: TRY THE OTHER ANGLE", "ANOTHER ANGLE THAT COULD WORK", "Car dealers want bulk", "First look", "30/100", "not yet"):
            self.assertIn(part, h)
        msg = pipeline.gate(slug, "angle")
        child = store.venture(slug)["data"]["angle_slug"]
        self.assertIn(child, msg)
        self.assertEqual(store.venture(slug)["status"], "gate_05")  # the main idea is left as it is
        self.assertEqual(store.venture(child)["data"]["angle_of"], slug)
        self.assertIn("Car dealers", store.venture(child)["idea"])
        self.assertEqual(pipeline.run(child, say=lambda m: None), "gate_05")  # not killed as a duplicate of its parent
        self.assertEqual(store.venture(child)["data"]["first_score100"], 65)
        h2 = pdf.build_html(child)
        self.assertIn("This is the other angle", h2)
        self.assertIn("GOOD FIRST LOOK", h2)
        self.assertIn("already saved", pipeline.gate(slug, "angle"))  # asking twice does not make a second copy

    def test_off_topic_searches_and_rival_brand_names(self):
        from vm.util import read_csv, buy_volume
        slug = pipeline.new("relevance filter idea about build sheets", country="us")
        pipeline.run(slug, say=lambda m: None)
        pipeline.gate(slug, "go")
        OFF_TOPIC.update({KWS[0]}); BRAND_ONLY.update({KWS[1]}); RIVAL_KIND["comp5.com"] = "off-target"
        try:
            self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_14")
        finally:
            OFF_TOPIC.clear(); BRAND_ONLY.clear(); RIVAL_KIND.clear()
        d = TMP / "ventures" / slug
        clean = read_csv(d / "08_keywords_clean.csv")
        dropped = read_csv(d / "08_keywords_dropped.csv")
        self.assertIn(KWS[0], [r["keyword"] for r in dropped])          # Google shows something else: thrown out
        self.assertNotIn(KWS[0], [r["keyword"] for r in clean])
        brand = [r for r in clean if r["keyword"] == KWS[1]][0]
        self.assertEqual(brand["intent"], "brand")                         # a rival's bare name: counted at 10%
        from vm.util import unique_searches
        from vm.util import is_buy
        full = sum(float(r["volume"]) for r in unique_searches(clean) if is_buy(r))   # "free ..." searches are not buying searches
        self.assertAlmostEqual(buy_volume(clean), full + 0.1 * float(brand["volume"]), places=3)
        import json
        comps = json.loads((d / "11_top_competitors.json").read_text())
        self.assertNotIn("comp5.com", [x["domain"] for x in comps])      # off-target site is not a rival
        self.assertIn("comp5.com", [x["domain"] for x in json.loads((d / "11_competitors_removed.json").read_text())["off_target"]])
        self.assertNotIn(KWS[0], [cl["head"] for cl in json.loads((d / "10_clusters_serp.json").read_text())])

    def test_go_against_the_recommendation_is_an_override(self):
        weak = lambda task, cls, web_, model: (fake_ai(task, cls, web_, model) | {"ice": {"impact": 3, "confidence": 3, "ease": 4}}
                                               if cls.__name__ == "Scorecard" else fake_ai(task, cls, web_, model))
        ai.FAKE = weak
        try:
            slug = pipeline.new("override marking idea about trim levels", country="us")
            pipeline.run(slug, say=lambda m: None)
        finally:
            ai.FAKE = fake_ai
        pipeline.gate(slug, "go", "I want the numbers anyway")
        g = store.gates(slug)[-1]
        self.assertTrue(g["note"].startswith("OVERRIDE: GO although the first-look score was WEAK (30/100)"), g["note"])
        self.assertIn("I want the numbers anyway", g["note"])
        from vm import pdf
        self.assertIn("GO although the first-look score was WEAK", pdf.build_html(slug))

    def test_pivot_resets_phase2_3(self):
        slug = pipeline.new("pivot test idea about stickers", country="gb")
        pipeline.run(slug, say=lambda m: None)
        pipeline.gate(slug, "go")
        pipeline.run(slug, say=lambda m: None)
        pipeline.gate(slug, "pivot", "UK dealers only")
        self.assertEqual(store.block(slug, "06")["status"], "PENDING")
        self.assertEqual(store.venture(slug)["pivot_note"], "UK dealers only")

    def test_quick_test_branch(self):
        slug = pipeline.new("quick test branch idea about trims", country="us")
        for _ in range(3):
            pipeline.run(slug, say=lambda m: None)
            if store.venture(slug)["status"] == "gate_18":
                break
            pipeline.gate(slug, "go")
        pipeline.gate(slug, "test")
        self.assertEqual(store.venture(slug)["status"], "quick_test")
        self.assertTrue((TMP / "ventures" / slug / "20_quick_test.md").exists())

    def _to_gate3(self, idea):
        slug = pipeline.new(idea, country="us")
        for _ in range(3):
            pipeline.run(slug, say=lambda m: None)
            if store.venture(slug)["status"] == "gate_18":
                break
            pipeline.gate(slug, "go")
        return slug

    def test_one_offer_everywhere(self):
        """The offer is chosen first; price, market, test and dates all come from it, and a different buyer is set aside, not chosen."""
        import json
        slug = self._to_gate3("one offer idea about build sheets")
        d = store.venture(slug)["data"]
        offer, folder = d["offer"], TMP / "ventures" / slug
        self.assertEqual(offer["channel"], "google search")           # the b2b / cold-email option earns more on paper but is another business
        self.assertIn("car dealers", d["spin_off"]["idea"])
        mk = json.loads((folder / "14_market_analysis.json").read_text())
        self.assertEqual(mk["chosen_price_usd"], offer["price_usd"])
        self.assertIn("$%.2f" % offer["price_usd"], mk["bottom_up_method_at_chosen_price"])   # the formula text uses the chosen price
        self.assertIn("at the chosen price", store.block(slug, "12")["summary"])              # so does step 12's own result line
        fc = d["forecast_12m_usd"]                                                              # good case kept inside what Google can send
        self.assertLessEqual(fc["high"], mk["bottom_up_at_chosen_price_usd_year"] * 0.35 + 1)
        self.assertTrue(fc["low"] <= fc["mid"] <= fc["high"])
        self.assertEqual(d["consistency_problems"], [])
        self.assertIn("pre-sale", (folder / "19_business_plan.md").read_text())               # the one test is in the plan
        pipeline.gate(slug, "test")
        self.assertIn(offer["test"]["pass_threshold"], (folder / "20_quick_test.md").read_text())  # and the quick test is that same test

    def test_not_consistent_blocks_go(self):
        slug = self._to_gate3("inconsistent idea about option lists")
        try:
            CASE_RULES[:] = ["One-time payments only. No subscriptions.", "The first-year goal is $12,000", "Pre-pay 49 EUR"]
            pipeline.rerun(slug, "16")
            st = pipeline.run(slug, say=lambda m: None)
        finally:
            CASE_RULES[:] = ["no OEM logos"]
        self.assertEqual(st, "gate_18")
        self.assertEqual(store.block(slug, "16")["verdict"], "fail")       # the text stayed wrong after 3 tries
        probs = " | ".join(store.venture(slug)["data"]["consistency_problems"])
        for word in ("subscription", "sales goal", "euros"):
            self.assertIn(word, probs)
        for decision in ("go", "test"):
            with self.assertRaises(SystemExit):
                pipeline.gate(slug, decision)
        from vm import pdf
        self.assertIn("NOT CONSISTENT", pdf.build_html(slug))
        self.assertIn("killed", pipeline.gate(slug, "kill"))                # stopping the idea still works

    def test_rule_change_makes_steps_out_of_date(self):
        slug = self._to_gate3("out of date idea about spec sheets")
        self.assertEqual(pipeline.stale(slug), [])
        old = dict(pipeline.BLOCK_VERSIONS)
        try:
            pipeline.BLOCK_VERSIONS["12"] = old.get("12", 1) + 1
            self.assertEqual(pipeline.stale(slug), ["12", "15", "16", "17"])   # step 12 and everything that reads from it
            with self.assertRaises(SystemExit):
                pipeline.gate(slug, "go")
            from vm import pdf
            self.assertIn("OUT OF DATE", pdf.build_html(slug))
            said = []
            self.assertEqual(pipeline.run(slug, say=said.append), "gate_18")   # one run refreshes them; gates 1 and 2 are not asked again
            self.assertIn("out of date", said[0])
            self.assertEqual(pipeline.stale(slug), [])
        finally:
            pipeline.BLOCK_VERSIONS.clear()
            pipeline.BLOCK_VERSIONS.update(old)


    def test_budget_cap_stops(self):
        os.environ["VM_MAX_USD_PER_IDEA"] = "0.05"
        try:
            slug = pipeline.new("cap test idea about vin numbers", country="us")
            self.assertEqual(pipeline.run(slug, say=lambda m: None), "gate_05")
            pipeline.gate(slug, "go")
            st = pipeline.run(slug, say=lambda m: None)
            self.assertEqual(st, "alert")
            self.assertIn("cap", store.block(slug, "07")["error"])
            self.assertLessEqual(store.spent(slug), 0.05 + 1e-9)
        finally:
            os.environ["VM_MAX_USD_PER_IDEA"] = "5"

    def test_duplicate_killed(self):
        a = pipeline.new("dup idea people want window stickers", country="us")
        pipeline.run(a, say=lambda m: None)
        b = pipeline.new("dup idea people want window stickers", country="us")
        store.update_venture(a, one_liner="dup idea people want window stickers")
        self.assertEqual(pipeline.run(b, say=lambda m: None), "kill_recommended")
        pipeline.gate(b, "kill")
        self.assertEqual(store.venture(b)["status"], "killed")


    def test_stored_idea_is_rescored(self):
        slug = pipeline.new("Aquarium water test log app for reef tank hobbyists who pay monthly", country="us")
        pipeline.run(slug, say=lambda m: None)
        c = pipeline.Ctx(slug)
        sc = c.read("05_scorecard.json")
        c.write("05_scorecard.json", sc | {"ice_avg": 7.0})
        store.set_data(slug, ice_avg=7.0, first_score100=70)
        store.set_block(slug, "04", summary="ICE 7.0 (I7 C6 E8); MVP 7 d; blockers: none")
        pipeline.resync(slug)
        self.assertEqual(store.venture(slug)["data"]["first_score100"], 65)
        self.assertIn("not counted", store.block(slug, "04")["summary"])


class Pure(unittest.TestCase):

    def test_close_wordings_count_once(self):
        """Google gives close wordings of one search the same volume and click price: they are the same people."""
        from vm.util import buy_volume, unique_searches, volume_split
        kws = [{"keyword": "concrete calculator", "volume": 450000, "cpc": 2.67, "intent": "buy", "kd": 42},
               {"keyword": "calculator for concrete", "volume": 450000, "cpc": 2.67, "intent": "buy", "kd": 27},
               {"keyword": "concrete measuring calculator", "volume": 450000, "cpc": 2.67, "intent": "buy", "kd": 0},
               {"keyword": "gravel calculator", "volume": 60500, "cpc": 2.04, "intent": "buy", "kd": 11},
               {"keyword": "rebar calculator", "volume": 90, "cpc": 0, "intent": "buy", "kd": 3},
               {"keyword": "deck screw calculator", "volume": 90, "cpc": 0, "intent": "buy", "kd": 5},   # same volume, no price, other words: kept
               {"keyword": "calculator rebar", "volume": 90, "cpc": 0, "intent": "buy", "kd": 9}]         # same words: merged
        u = unique_searches(kws)
        self.assertEqual(len(u), 4)
        self.assertEqual(buy_volume(kws), 450000 + 60500 + 90 + 90)
        self.assertEqual(volume_split(kws)["commercial"], 510680)
        big = [k for k in u if k["volume"] == 450000][0]
        self.assertEqual((big["keyword"], big["kd"], big["wordings"]), ("concrete calculator", 27, 3))

    def test_market_knockout_boundaries(self):
        from vm.blocks import gates

        class C:  # the smallest context knockouts() needs
            def __init__(self, bottom_up):
                self.v = {"data": {}}
                self.mk = {"bottom_up_usd_year": bottom_up, "min_market_usd": 12000}

            def read(self, name, default=None):
                return self.mk
        self.assertEqual(gates.knockouts(C(11999))[0], "KILL")                    # under the smallest size: don't build
        self.assertTrue(gates.knockouts(C(12001))[0].startswith("QUICK TEST"))   # 1x-3x: test at most
        self.assertTrue(gates.knockouts(C(119999))[0].startswith("QUICK TEST"))  # between the smallest size and the size we want: test at most
        self.assertIsNone(gates.knockouts(C(120001))[0])

    def test_text_checks(self):
        from vm import checks
        offer = {"payment": "subscription", "test": {"days": 14, "warmup_days": 14}}
        bad = checks.text_problems({"plan": "One-time payments only. Google reaches $2,209 a year, 18% of the $12,000 goal. Run a 21-day pre-sale at 49 EUR.",
                                    "note": "CA error: `POST https://oauth2.googleapis.com/token` resulted in a 503 Service Unavailable"},
                                   offer, market=1695, market_raw=2209)
        text = " | ".join(bad)
        for word in ("sales goal", "euros", "$2,209", "subscription", "21-day pre-sale", "raw error"):
            self.assertIn(word, text)
        good = "Sell the feed at $99 a month. About $1,695 a year is reachable through Google search. The 14-day test comes first."
        self.assertEqual(checks.text_problems({"plan": good}, offer, market=1695, market_raw=2209), [])

    def test_dates_come_from_test_and_forecast(self):
        import datetime as dt
        day = dt.date(2026, 9, 1)                                             # away from the year-end holidays
        offer = {"build_days": 10, "test": {"days": 14, "warmup_days": 14}}
        tl = phase4.timeline(offer, forecast_mid=565, market_year_usd=1695, today=day)
        by = {s["goal"]: s["by"] for s in tl["steps"]}
        self.assertTrue(tl["test_first"])
        self.assertEqual(tl["build_from"], "2026-09-29")                     # 14 days warm-up + 14 days test: nothing is built before
        self.assertEqual(by["first version live"], "2026-10-09")
        self.assertIn("not reached", by["$1,000 a month"])                   # $565 a year never gets to $1,000 a month
        self.assertIn("not reached", by["$100 a month"])
        big = phase4.timeline(offer, forecast_mid=60000, market_year_usd=400000, today=day)
        self.assertFalse(big["test_first"])                                  # a market of the size we want: build right away
        self.assertRegex({s["goal"]: s["by"] for s in big["steps"]}["$1,000 a month"], r"^202[67]-")

    def test_rival_name_is_never_easy(self):
        from vm import pdf
        self.assertGreaterEqual(pdf.rank_level({"kd": 5, "intent": "brand", "top10": [{"dr": 3}], "weak_spots": ["forum"]})[0], 2)
        self.assertLessEqual(pdf.rank_level({"kd": 5, "intent": "buy", "top10": [{"dr": 3}], "weak_spots": []})[0], 1)

    def test_market_scale(self):
        from vm.blocks import gates
        self.assertEqual([gates.market_score(m) for m in (141, 2999, 3000, 9999, 10000, 20000, 50000)], [1, 1, 2, 2, 3, 4, 5])

    def test_link_targets_filter(self):
        from vm.blocks.phase3 import link_reject_reason as r
        for bad in ("bestnz-poker-casinoslot.com", "betwinnermirror.com", "betulcrime.com", "thcradar.com", "merrigoldfinance-loan.com"):
            self.assertTrue(r({"domain": bad, "dr": 50}), bad)
        self.assertTrue(r({"domain": "uncledspizza.com", "dr": 0}))             # no strength data: not worth an email
        self.assertEqual(r({"domain": "indiehackers.com", "dr": 70}), "")
        self.assertEqual(r({"domain": "betterprogramming.pub", "dr": 60}), "")   # 'bet' inside a normal word is fine

    def test_weighted_click_price(self):
        from vm.util import weighted_cpc
        kws = [{"keyword": "a", "volume": 90, "cpc": 0, "intent": "buy"}, {"keyword": "b", "volume": 10, "cpc": 23.14, "intent": "buy"},
               {"keyword": "c", "volume": 5000, "cpc": 30, "intent": "info"}]
        self.assertEqual(weighted_cpc(kws), 2.31)   # not $23.14: one tiny expensive keyword cannot carry the score


    def test_score_formula(self):
        # (1000 x 2 x 1.5) / (10 + 5) = 200, rising +15% = 230
        self.assertEqual(phase2.score(1000, 2, "buy", 10), 200)
        self.assertEqual(phase2.score(1000, 2, "buy", 10, 20), 230)
        self.assertEqual(phase2.score(1000, 0.1, "info", 0), round(1000 * 0.3 * 0.6 / 5, 2))

    def test_cluster_overlap(self):
        u = lambda *n: [{"rank": i + 1, "url": f"u{x}"} for i, x in enumerate(n)]
        s = [{"keyword": "a", "volume": 100, "organic": u(1, 2, 3, 4, 5, 6)}, {"keyword": "b", "volume": 50, "organic": u(1, 2, 3, 4, 9, 10)},
             {"keyword": "c", "volume": 40, "organic": u(1, 2, 3, 11, 12, 13)}]
        cl = phase2.cluster(s)
        self.assertEqual([c["keywords"] for c in cl], [["a", "b"], ["c"]])

    def test_hidden_google_links(self):
        d, u, k = seo._real({"domain": "google.com", "url": "https://google.com/goto?url=XYZ",
                             "breadcrumb": "https://www.photoaid.com › ... › UK", "title": "UK photo"})
        self.assertEqual(d, "photoaid.com")
        self.assertEqual(k, "photoaid.com|uk photo")
        self.assertTrue(seo.not_competitor("passport.service.gov.uk"))
        self.assertFalse(seo.not_competitor("photoaid.com"))

    def test_on_topic(self):
        from vm.blocks.phase3 import on_topic
        ph = [{"passport", "photo"}, {"visa", "photo"}]
        self.assertTrue(on_topic("uk passport photo app", ph))
        self.assertFalse(on_topic("renew british passport", ph))

    def test_degraded_serp_uses_snapshot(self):
        real_post = seo.post
        def fake(ep, task):
            if ep.endswith("organic/live/advanced"):
                return [{"items": [{"type": "organic", "rank_group": i, "domain": "google.com", "url": "https://google.com/goto?url=x",
                                    "breadcrumb": "https://junk%d.com" % i, "title": "t"} for i in range(1, 6)] + [{"type": "ai_overview"}]}]
            if ep.endswith("historical_serps/live"):
                return [{"items": [{"datetime": "2026-01-01", "items": [{"type": "organic", "rank_group": 1, "domain": "old.com", "url": "https://old.com"}]},
                                   {"datetime": "2026-11-01", "items": [{"type": "organic", "rank_group": 1, "domain": "www.clio.com", "url": "https://www.clio.com/"},
                                                                        {"type": "paid", "domain": "ad.com", "url": "https://ad.com"}]}]}]
            return real_post(ep, task)
        seo.post = fake
        try:
            s = seo.serp("law practice management software", 2840, "en")
        finally:
            seo.post = real_post
        self.assertEqual(s["organic"][0]["domain"], "clio.com")
        self.assertTrue(s["source"].startswith("database snapshot 2026-11-01"))
        self.assertTrue(s["features"]["ai_overview"])
        self.assertEqual(s["features"]["paid"], 1)

    def test_economics(self):
        e = phase4.economics(price=20, data_cost=2, fee_pct=5, fee_fixed=0.4, conversion_pct=2, retention_months=3, cpc=1.0)
        self.assertEqual(e["net_per_sale"], 16.6)
        self.assertEqual(e["max_cac"], 49.8)
        self.assertEqual(e["breakeven_cpc"], 1.0)
        self.assertEqual(e["paid_search_cac"], 50.0)


class BuildEffortNotCounted(unittest.TestCase):
    """Owner rule 2026-11-27: how long an idea takes to build never counts against it."""

    def test_first_look_ignores_build_effort(self):
        from vm.blocks import phase1
        sc = {"ice": {"impact": 8, "confidence": 6, "ease": 1}, "effort": {"days_to_mvp": 90}, "blockers": [], "other_angle": None}
        self.assertEqual(phase1.first_avg(sc["ice"]), 7.0)
        verdict, line = phase1.first_result(sc)
        self.assertEqual(verdict, "pass")  # 90 days to build and ease 1 do not stop it
        self.assertIn("not counted", line)
        self.assertEqual(phase1.first_result(sc | {"blockers": ["illegal"]})[0], "kill")  # hard blockers still stop it
        os.environ["VM_COUNT_BUILD_EFFORT"] = "1"
        try:
            self.assertEqual(phase1.first_avg(sc["ice"]), 5.0)
            self.assertEqual(phase1.first_result(sc)[0], "kill")  # old rule: over 30 days
        finally:
            del os.environ["VM_COUNT_BUILD_EFFORT"]


class RevenueProof(unittest.TestCase):
    """A keyword count measures one channel. Real businesses with verified revenue decide what a niche can pay."""
    ROWS = [{"slug": "sticker-pro", "name": "Sticker Pro", "website": "https://stickerpro.com", "category": "Utilities", "targetAudience": "B2C",
             "description": "Window sticker PDF by VIN for used car buyers", "foundedDate": "2025-12-04T00:00:00.000Z",
             "revenue": {"last30Days": 42327.15, "mrr": 0, "total": 282010.2}, "visitorsLast30Days": 11093, "revenuePerVisitor": 3.91, "growth30d": 28.5},
            {"slug": "cat-facts", "name": "Cat Facts", "website": "https://catfacts.com", "category": "Entertainment", "description": "Daily cat facts by email",
             "revenue": {"last30Days": 900, "mrr": 900, "total": 5000}, "visitorsLast30Days": 400000, "revenuePerVisitor": 0.002}]

    @classmethod
    def setUpClass(cls):
        from vm import proof
        cls.proof = proof
        seo.post = fake_post
        web.fetch = fake_fetch
        web.sitemap = lambda d, max_children=5: {"found": True, "urls": 120, "oldest": "2019-01-01", "newest": "2026-01-01", "source": "", "note": ""}
        web.screenshots = lambda url, prefix: []
        ai.FAKE = fake_ai
        many = list(cls.ROWS)
        for i in range(12):  # enough rows per traffic band for a calibration
            many.append({"slug": f"small{i}", "name": f"Small {i}", "website": f"https://small{i}.com", "revenue": {"last30Days": 12000 + i, "mrr": 0, "total": 1},
                         "visitorsLast30Days": 500 + i, "revenuePerVisitor": 20 + i, "description": "niche b2b tool"})
            many.append({"slug": f"mid{i}", "name": f"Mid {i}", "website": f"https://mid{i}.com", "revenue": {"last30Days": 15000 + i, "mrr": 0, "total": 1},
                         "visitorsLast30Days": 9000 + i, "revenuePerVisitor": 1 + i / 10, "description": "consumer tool"})
        (proof.folder() / "band-test.json").write_text(__import__("json").dumps(many))
        cls._detail, cls._ads = proof.detail, proof.ads
        proof.detail = lambda slug: {"domainRating": 6, "startupInsights": {"pricingModel": "Starter: $60, Self-Study: $199", "targetPersona": "car buyers", "estimatedUserCount": 753},
                                     "marketingChannels": [{"slug": "meta-ads", "category": "paid"}, {"slug": "seo", "category": "organic"}]}
        proof.ads = lambda name, domain: {"name": name, "domain": domain, "meta_ads": 41 if "sticker" in name.lower() else None, "google_ads": 2 if "sticker" in name.lower() else None}
        os.environ["TRUSTMRR_API_KEY"] = "test"

    @classmethod
    def tearDownClass(cls):
        cls.proof.detail, cls.proof.ads = cls._detail, cls._ads
        os.environ.pop("TRUSTMRR_API_KEY", None)
        for f in cls.proof.folder().glob("band*.json"):
            f.unlink()

    def test_per_visitor_bands_and_prediction(self):
        cal = self.proof.calibration()
        small, mid = [b for b in cal if b["visitors_month"] == "under 2,000"][0], [b for b in cal if b["visitors_month"] == "2,000 to 35,000"][0]
        self.assertGreater(small["median"], 10 * mid["median"])        # few visitors at a real price earn far more per visitor
        p = self.proof.predict(11000, cal)
        self.assertEqual(p["mid"], round(11000 * mid["median"]))
        self.assertIsNone(self.proof.predict(10 ** 7, cal))            # no data for that size: no made-up number

    def test_shortlist_matches_on_meaning_words(self):
        got = [x["slug"] for x in self.proof.shortlist("window sticker lookup for people who buy a used car")]
        self.assertEqual(got[0], "sticker-pro")
        self.assertNotIn("cat-facts", got)

    def test_proof_reaches_the_report_and_the_score_inputs(self):
        slug = pipeline.new("Paid window sticker report by VIN for buyers of used cars in the United States", country="us")
        pipeline.run(slug, say=lambda m: None)
        pr = pipeline.Ctx(slug).read("02_proof.json")
        self.assertTrue(pr["checked"])
        self.assertEqual(pr["comparables"][0]["revenue_30d_usd"], 42327)
        self.assertEqual(pr["comparables"][0]["paid_channels"], ["meta-ads"])
        self.assertEqual(store.venture(slug)["data"]["proof_best_30d"], 42327)
        self.assertIn("real businesses with verified revenue (best: Sticker Pro $42,327", store.block(slug, "02")["summary"])
        from vm import pdf
        h = pdf.build_html(slug)
        for part in ("Do real businesses make money here?", "$42,327", "Starter: $60, Self-Study: $199", "pays for ads", "What real sites earn per visitor", "Proven revenue"):
            self.assertIn(part, h)

    def test_small_search_does_not_kill_a_proven_niche(self):
        from vm.blocks import gates

        class C:  # the knock-out only needs the market size and the stored proof
            v = {"data": {"proof_best_30d": 42327}}
            read = staticmethod(lambda name, default=None: {})
        old = gates.market_at_chosen_price
        gates.market_at_chosen_price = lambda c, mk: 14 * 12          # $14 a month through search: far under the floor
        try:
            rec, note = gates.knockouts(C)
            self.assertTrue(rec.startswith("QUICK TEST"))
            self.assertIn("made $42,327 in the last 30 days", note)
            C.v = {"data": {"proof_best_30d": 0}}
            self.assertEqual(gates.knockouts(C)[0], "KILL")            # no proof: the old rule stands
        finally:
            gates.market_at_chosen_price = old

    def test_app_store_rivals_do_not_share_an_ad_count(self):
        proof, real = self.proof, type(self).__dict__["_ads"]
        seen = []
        old_read, old_cmd = proof.read_page, os.environ.get("VM_BROWSER_CMD")
        os.environ["VM_BROWSER_CMD"] = "x"
        proof.read_page = lambda url, max_chars=6000: (seen.append(url) or ("~7 results" if "Alpha" in url else "~1 results"))
        try:
            a = real("Alpha App", "apps.apple.com")
            b = real("Beta App", "apps.apple.com")
        finally:
            proof.read_page = old_read
            os.environ.pop("VM_BROWSER_CMD") if old_cmd is None else os.environ.__setitem__("VM_BROWSER_CMD", old_cmd)
        self.assertEqual((a["meta_ads"], b["meta_ads"]), (7, 1))       # each rival has its own count
        self.assertEqual((a["domain"], a["google_ads"]), ("", None))   # no own domain: Google ads are 'not checked', never zero
        self.assertFalse(any("adstransparency" in u for u in seen))

    def test_proof_is_part_of_the_final_score(self):
        from vm.blocks import gates
        mk = lambda pr: type("C", (), {"read": staticmethod(lambda name, default=None: pr)})  # noqa: E731
        comp = {"name": "Sticker Pro", "revenue_30d_usd": 42327, "closeness": 3, "price": "$199"}
        self.assertIsNone(gates.proof_score(mk({"checked": False})))                        # not checked: no effect at all
        self.assertEqual(gates.proof_score(mk({"checked": True, "comparables": []}))[0], 2)
        self.assertEqual(gates.proof_score(mk({"checked": True, "comparables": [comp]}))[0], 5)
        near = gates.proof_score(mk({"checked": True, "comparables": [comp | {"closeness": 2}]}))
        self.assertEqual(near[0], 4)                                                          # a neighbouring niche counts one step lower
        self.assertIn("neighbouring niche", near[1])
        self.assertEqual(gates.proof_score(mk({"checked": True, "comparables": [comp | {"closeness": 1}]}))[0], 2)  # loosely alike is not proof

    def test_unchecked_is_never_reported_as_nothing_found(self):
        self.assertIn("not checked", self.proof.summary({"checked": False}))
        self.assertIn("no real business", self.proof.summary({"checked": True, "comparables": []}))


class FourthAudit(unittest.TestCase):
    """Faults a reviewer found in the welding-inspector report (2026-11-27)."""

    def test_free_searches_are_not_buying_searches(self):
        from vm.util import buy_volume, is_buy, volume_split
        kws = [{"keyword": "free cwi practice test", "volume": 480, "cpc": 2.1, "intent": "buy", "kd": 5},
               {"keyword": "cwi practice test", "volume": 320, "cpc": 2.6, "intent": "buy", "kd": 7}]
        self.assertFalse(is_buy(kws[0]))
        self.assertEqual(buy_volume(kws), 320)
        self.assertEqual(volume_split(kws), {"commercial": 320, "brand": 0, "info": 480})

    def test_a_failed_page_load_is_not_a_rival_weakness(self):
        from vm.blocks.phase3 import FETCH_FAIL
        for w in ("Returns 404 with no page content, no title and no text", "Page is a redirect stub", "Site blocked our request", "Could not be opened"):
            self.assertTrue(FETCH_FAIL.search(w), w)
        for w in ("6 steps to pay, no sample report", "No money-back terms published", "Slow on mobile (4.2 s)"):
            self.assertFalse(FETCH_FAIL.search(w), w)

    def test_no_validation_test_over_the_year_end_holidays(self):
        import datetime as dt
        offer = {"test": {"days": 14}, "build_days": 10}
        tl = phase4.timeline(offer, 800, 7000, today=dt.date(2026, 12, 11))
        ends = [s_["by"] for s_ in tl["steps"] if s_["goal"].startswith("validation test ends")][0]
        starts = [s_["by"] for s_ in tl["steps"] if "moved past the year-end holidays" in s_["goal"]]
        self.assertTrue(starts and starts[0] >= "2027-01-04")
        self.assertGreaterEqual(ends, "2027-01-18")
        tl2 = phase4.timeline(offer, 800, 7000, today=dt.date(2026, 9, 1))     # far from the holidays: unchanged
        self.assertEqual([s_["by"] for s_ in tl2["steps"] if s_["goal"].startswith("validation test ends")][0], "2026-09-15")


class DailySpend(unittest.TestCase):
    """2026-11-27: $20 was spent against a $10 limit, across four data folders and hand-run lookups, with only a running tally."""

    def test_one_daily_cap_over_every_folder_and_hand_run_lookup(self):
        os.environ["VM_SPEND_FILE"] = str(TMP / "spend-day.json")
        os.environ["VM_DAY_MAX_USD"] = "1"
        old = dict(budget.CURRENT)
        try:
            budget.CURRENT.update(slug=None, block=None)          # a lookup run by hand, outside any idea
            budget.day_check(0.4)
            budget.record("dataforseo", "serp", 0.6)
            budget.record("dataforseo", "serp", 0.0, counted=False, cached=True)   # a cached answer costs nothing
            budget.record("claude-cli", "ask", 3.0)                               # AI usage is not data money
            self.assertEqual(budget.day()["usd"], 0.6)
            os.environ["VM_DATA_DIR"], keep = str(TMP / "other-folder"), os.environ["VM_DATA_DIR"]
            try:
                self.assertEqual(budget.day()["usd"], 0.6)        # another data folder sees the same total
                with self.assertRaises(budget.BudgetExceeded):
                    budget.check(0.5)                            # 0.6 + 0.5 is over the $1 day cap, even with no idea running
            finally:
                os.environ["VM_DATA_DIR"] = keep
            budget.note_start_balance(25.34)
            budget.note_start_balance(9.99)                       # only the first balance of the day is kept
            self.assertEqual(budget.day()["start_balance"], 25.34)
        finally:
            budget.CURRENT.update(old)
            os.environ["VM_SPEND_FILE"] = str(TMP / "spend.json")
            os.environ["VM_DAY_MAX_USD"] = "1000"


if __name__ == "__main__":
    unittest.main()

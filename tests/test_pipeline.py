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
        items += [{"type": "paid", "domain": "comp1.com", "title": "Get your sticker", "description": "From $9"}, {"type": "people_also_ask"},
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
                      "ice": {"impact": 7, "confidence": 6, "ease": 8}, "synergy": "cold email", "blockers": []},
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
        "Swot": {"options": [{"model": m, "price_usd": p, "conversion_pct": 2, "retention_months": r, "sales_per_month_at_1000_visits": 20,
                              "owner_hours_per_month": 20, "sources": ["https://x"]} for m, p, r in (("one-time", 15, 1), ("sub", 29, 4), ("b2b", 199, 8))],
                 "strengths": ["3 competitors at $19"], "weaknesses": ["DR 0 today"], "opportunities": ["UK 12k searches"], "threats": ["https://x.com new player"],
                 "conclusions": ["a", "b", "c"]},
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
    return data[n]


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seo.post = fake_post
        web.fetch = fake_fetch
        web.sitemap = lambda d, max_children=5: {"found": True, "urls": 120, "oldest": "2019-01-01", "newest": "2026-01-01", "source": "", "note": ""}
        web.screenshots = lambda url, prefix: []
        ai.FAKE = fake_ai

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

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
                  "14_market_analysis.json", "15_competitor_seo.json", "15_ai_visibility.json", "15_link_targets.csv", "GUARDRAILS.md", "ACCESS.md",
                  "OWNER-TODO.json", "16_owner_questions.md", "18_business_case.md", "18_swot.md", "19_business_plan.md",
                  "19_sitemap.json", "19_seo_calendar_90d.csv"):
            self.assertTrue((TMP / "ventures" / slug / f).exists(), f)
        self.assertLessEqual(store.spent(slug), 5)
        pipeline.gate(slug, "go")
        self.assertEqual(store.venture(slug)["status"], "approved_build")
        from vm import report, pdf
        self.assertTrue(report.write(slug).exists())
        h = pdf.build_html(slug)
        for part in ("FINDINGS REPORT", "THE ANSWER", "The scorecard", "Is there demand?", "Who are you up against?",
                     "How big is the money?", "Will it make money?", "The plan", "Glossary", "Sources", "IN PLAIN WORDS",
                     "How hard is it to get onto Google", "How to rank: the plan", "Do AI assistants recommend you?"):
            self.assertIn(part, h)
        f, msg = pdf.write(slug)  # a real PDF if a browser is installed, else a clear message
        self.assertTrue(f is None or f.stat().st_size > 1000, msg)

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


class Pure(unittest.TestCase):
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

    def test_economics(self):
        e = phase4.economics(price=20, data_cost=2, fee_pct=5, fee_fixed=0.4, conversion_pct=2, retention_months=3, cpc=1.0)
        self.assertEqual(e["net_per_sale"], 16.6)
        self.assertEqual(e["max_cac"], 49.8)
        self.assertEqual(e["breakeven_cpc"], 1.0)
        self.assertEqual(e["paid_search_cac"], 50.0)


if __name__ == "__main__":
    unittest.main()

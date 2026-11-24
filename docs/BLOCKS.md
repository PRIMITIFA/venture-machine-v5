# Blocks 01-18: inputs, outputs, tests

Each block has a verdict:
- **pass**: continue.
- **warn**: continue, and the warning is noted.
- **redo**: retry with the failure as feedback; after 3 tries the block goes to ALERT.
- **kill**: the run stops until you confirm it (`gate kill`) or override it (`gate override "why"`).

Paid data comes from DataForSEO. The AI is Claude.

## Phase 1: Idea filter (about 1 hour, cap $0.50)

| # | Does | Data | Output | Test |
|---|---|---|---|---|
| 01 | Turns the idea into "People [who] want X and would pay for Y", checks it against every archived idea (killed ones too) and picks 3-5 key terms | AI (fast) + local text match | `01_intake.md` | **Redo** if the payer or product is unclear. **Kill** if it is a duplicate |
| 02 | Finds at least 3 paying competitors with prices, the revenue model, the data source and the one validation question. E-E-A-T: a real person, expertise, unique data per page, contacts and policies, YMYL risk and banned claims. Checks the house rules | AI + web search | `02_how_analysis.json`, `03_eeat_quality.json` | **Kill** if nobody pays today, it is illegal, it needs physical logistics, no real person can stand behind it, there is no unique data, or it breaks a house rule. **Warn** if fewer than 3 competitors charge money |
| 03 | 5-year Google Trends for the key terms (24-month change), ads on the top term, rising synonyms, new players in the last 12 months, forum questions in the last 90 days | DataForSEO Trends + 1 SERP, AI + web | `04_niche_pulse.json` | **Kill** if the trend is down more than 30% with no new terms, no ads and quiet forums |
| 04 | 5 points for, 5 against, the biggest unknown, the effort (days to MVP, cost per month, APIs, hours per week), ICE (1-10), synergy, blockers vs risks | AI | `05_scorecard.json` | **Pass** if the ICE average is ≥ 6, the MVP takes ≤ 14 days and there are no blockers. **Kill** if the MVP takes more than 30 days or there is a hard blocker |
| 05 | **GATE 1**: a short memo | - | - | GO / KILL |

## Phase 2: Demand + SEO (30-day cache)

| # | Does | Data | Output | Test |
|---|---|---|---|---|
| 06 | 30-60 seed keywords: synonyms, slang, brands, modifiers, competitors | AI | `06_seeds.csv` | **Redo** if there are fewer than 30 or more than 60 seeds, or fewer than 8 buying seeds |
| 07 | Volume, CPC low/high, competition and 12-month trend, plus real long-tail from the 3 strongest buying seeds. Drops keywords under 20/month unless CPC is above $3. The AI labels intent and removes junk | Google Ads volume + Labs suggestions | `08_keywords_clean.csv` | **Pass** if buying volume is ≥ 1,000/month or CPC is ≥ $2. **Warn** on high volume with CPC under $0.30 |
| 08 | Top-20 SERP for the strongest keywords (`VM_MAX_SERPS`). Google often serves scrapers a reduced page (links hidden behind google.com/goto, no ads, odd sites); when that happens the organic results come from DataForSEO's newest real page-1 snapshot (historical SERPs, dated in the data) and only the AI Overview flag comes from the live page. Two keywords form one cluster (= one page) when their top 10 share ≥ 4 URLs. Records the winning format and SERP features. Weak spots: forums in the top 10, DR under 20 in the top 10, ads on top | SERP live + bulk domain ranks | `09_serp_raw.json`, `10_clusters_serp.json` | **Pass** if ≥ 90% of SERPs were fetched AND ≥ 30% of clusters have a weak spot or room for a better format. **Warn** if every top-5 result is DR 60+ |
| 09 | KD for every keyword. Score = volume × max(CPC, 0.30) × intent weight / (KD + 5). Weights: buy 1.5, competitor 1.3, brand-model 1.2, info 0.6; a rising trend adds 15%. Shortlist: the top 5 + 30-40 long-tail keywords with KD ≤ 20. Top-5 competitor domains by position weight (big platforms left out) | Labs bulk KD | `11_shortlist.csv`, `11_keywords_scored.csv`, `11_top_competitors.json` | **Pass** if the top 20 has ≥ 10 buying clusters AND there are ≥ 10 buying keywords with KD ≤ 20. If there are only info keywords, go back to 06. If every keyword is KD 50+, use a non-SEO first channel |

## Phase 3: Competitors + market

| # | Does | Data | Output | Test |
|---|---|---|---|---|
| 10 | For each of the top 5: Google Lighthouse mobile speed score, domain age (WHOIS), home page speed and size, trust signals, checkout provider, pricing page, sitemap size and age, desktop and mobile screenshots. The AI lists concrete weaknesses. Sites that block bots are listed for a 2-minute check by hand at gate 2 | web + Playwright + AI vision | `12_competitor_ux.json`, `shots/` | **Pass** if there are ≥ 2 concrete weaknesses |
| 11 | All plans and prices, free tier, upsells, B2B/API, checkout, refunds, affiliates. Real Google ads from our SERPs, plus ad-library ads that have run 30+ days. Buyer quotes with URLs. One `identified_gap` line | pricing pages + AI + web | `13_competitor_business.json`, `13_competitor_ads.md` | **Kill** if competitors sell below our data cost and have better data |
| 12 | Rivals' Google visits per month, what those visits are worth in ads, and their 12-month traffic trend (top 3), which is real evidence of growth or decline. Bottom-up = buying searches × top-5 click share × an assumed conversion rate × the typical price × 12. Top-down = the AI's sourced estimate. Volume by country, buyer segments with pain quotes, growth direction | Labs traffic + volume by country + AI + web | `14_market_analysis.json` | **Pass** if bottom-up is ≥ 10× the year-1 goal AND there is an underserved segment. **Kill** if the whole market is smaller than the goal. Flags estimates that differ by more than 10× |
| 13 | DR, backlinks and referring domains for the top 5, their top pages (free tools), and referring domains that link to ≥ 2 competitors (link targets). **Keyword gap:** on-topic searches the top 3 rivals rank for that we had not planned. **Questions:** "People also ask" from our SERPs (free, from cache). **AI visibility:** 5 buyer questions are put to ChatGPT (with web search) and Perplexity. It records which sites they cite, how many of the top-5 Google rivals they mention, the sites Google AI Overviews quote on our searches, and the sites Google's AI cites most on the topic | backlinks summary, referring domains, relevant pages, LLM responses (ChatGPT, Perplexity), LLM mentions, AI Overview items from the SERPs | `15_competitor_seo.json`, `15_link_targets.csv`, `15_ai_visibility.json` | **Pass** if there are ≥ 20 link targets AND a top competitor has DR under 40. **Warn** if every competitor is DR 70+ |
| 14 | **GATE 2**: prices, gap, market, SEO strength, sites to check by hand | - | - | GO / PIVOT "narrower target" / KILL |

## Phase 4: Plan, costs, guardrails

| # | Does | Output | Test |
|---|---|---|---|
| 15 | Every tool with its cost at start and at 10×, its limit and its owner. Marketing channels with caps and pass/kill thresholds. Data cost per sale. Guardrails (the absolute bans are always included), the access list, the owner's to-dos and open questions | `GUARDRAILS.md`, `ACCESS.md`, `OWNER-TODO.json`, `16_owner_questions.md`, `15_costs.json` | **Redo** if any field is TBD |
| 16 | At least 3 business models. Python works out: net per sale = price − data cost − fees; max CAC = net × retention months; break-even CPC = net × retention × conversion; paid-search CAC = average buying CPC / conversion; profit per owner hour. Goal ladder with dates. SWOT: every line needs a number or a source | `16_unit_economics.json`, `18_business_case.md`, `18_swot.md` | **Redo** if a SWOT line has no number or source. **Kill** if every sale loses money. **Warn** if paid search costs more than the max CAC |
| 17 | Product line, free hook, upsell, a 5-second "why us", 12-month forecast. Sitemap: one cluster per page, home on the strongest keyword, money page on the strongest buying intent, each page with its own unique data source. 90-day calendar: lowest KD first, link outreach every week, a link-bait asset, the AI-search plan | `19_business_plan.md`, `19_sitemap.json`, `19_seo_calendar_90d.csv` | **Pass** if ≥ 20 pages are planned with distinct data sources. **Redo** if the pages only swap the keyword |
| 18 | **GATE 3**: 7 criteria scored 1-5 from the data: demand, value (CPC), market, KD/DR, weak spots, edge, costs | `18_gate3_memo.md` | below 3.0 = KILL; 3.0-3.5 = QUICK TEST (`20_quick_test.md`, max $150, 14 days, thresholds written first); 3.5 or more = GO, unless the likely first-year sales (block 17 forecast) are below the year-1 goal, in which case it is capped at QUICK TEST |

## Absolute bans

These are written into every `GUARDRAILS.md`:
- No pretending to be a government body.
- No "official" claims or OEM logos.
- No fake reviews, fake timers or fake scarcity.
- One honest account per platform.
- No invented numbers.
- No money moves without the owner.
- Caps everywhere.
- Thresholds are written before the test.

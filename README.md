# The Venture Machine v5: from idea to validated plan

The Venture Machine is an open-source tool that takes a business idea through **phases 1-4 (blocks 01-18)** of the 28-block Venture Machine process. Along the way it gathers real search data, finds the real competitors, sizes the market, checks costs and sets the guardrails. It stops at **3 owner gates**, where you decide GO, KILL, PIVOT or TEST.

```
PHASE 1  IDEA FILTER          01 idea + duplicates  02 business, data, E-E-A-T  03 niche alive?  04 ICE + MVP   05 GATE 1 go/kill
PHASE 2  DEMAND + SEO         06 seeds (30-60)  07 volume, CPC, cleaning  08 top-20 SERP + clusters  09 KD, shortlist, top-5 competitors
PHASE 3  COMPETITORS + MARKET 10 UX audit  11 prices, models, ads  12 market size + buyers  13 SEO + link gap   14 GATE 2 go/pivot/kill
PHASE 4  PLAN + GUARDRAILS    15 tools, costs, GUARDRAILS.md  16 unit economics + SWOT  17 product, sitemap, 90-day SEO   18 GATE 3 kill/test/go
```

**Rules the tool enforces:**
- **No invented numbers.** Every volume, CPC, keyword difficulty (KD), domain rating (DR), traffic figure and price comes from an API or from a web page, with its source.
- **The AI only sorts, labels and writes.** It does not supply the numbers.
- **Hard money caps.** The default is **$5 per idea** for all paid API calls in phases 1-4, and $0.50 for phase 1. If the next call could go over the cap, the tool refuses to make it.
- **30-day cache.** Raw API data is cached for 30 days, so re-running a step costs nothing.
- **Strict state machine.** Each block runs PENDING → RUNNING → VALIDATED, or goes to RETRY, then ALERT.
  - Each block's output is checked (pydantic) and must pass a written test.
  - A failed test is retried twice.
  - A KILL result stops the run until you confirm it or override it.
- **Fixed thresholds.** All pass/kill thresholds are written in the code before any results come in.

A real idea usually costs **$0.30-1.50** in DataForSEO calls. Phase 1 costs a few cents.

## Install (5 minutes)

You need **Python 3.10+**.

```bash
git clone https://github.com/<you>/venture-machine.git
cd venture-machine
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env
cp house_rules.example.md house_rules.md
```

Then fill in `.env`:

| What | Why | Where |
|---|---|---|
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | keyword volumes, CPC, SERPs, KD, backlinks, traffic | [dataforseo.com](https://dataforseo.com), pay as you go |
| **AI**: either `ANTHROPIC_API_KEY`... | research, labelling, plans | [console.anthropic.com](https://console.anthropic.com) |
| ...or install **Claude Code** (`claude` on PATH) | the same, run on your Claude subscription | [claude.com/claude-code](https://claude.com/claude-code) |

Next, edit `house_rules.md`: what you will and won't build, your price range and your assets. Every idea is checked against these rules.

Check the setup:

```bash
python vm.py doctor
```

Optional: competitor screenshots in block 10 need `pip install playwright && playwright install chromium`.
The findings PDF uses Playwright if it is installed. Otherwise it uses Chrome, Edge or Chromium, which are already on most computers.

## Use it

### The simple way: a local web app

```bash
python vm.py ui
```

This opens http://127.0.0.1:8765. Then:

1. Type the idea, pick a country and click **Add and run**.
2. The page refreshes while the blocks run.
3. At each gate, read the memo and click **GO**, **KILL**, **PIVOT** or **TEST**.

### The command line

```bash
python vm.py new "People who buy used cars want the original window sticker and would pay $15 for it" --country us
python vm.py run <slug>             # runs until the next gate
python vm.py gate <slug> go         # or: kill | pivot "UK dealers only" | test | override "why"
python vm.py show <slug>            # block-by-block status
python vm.py list                   # every idea (killed ones stay, so they are never re-pitched)
python vm.py rerun <slug> 07        # redo a block and everything after it
python vm.py report <slug>          # ventures/<slug>/report.html
python vm.py pdf <slug>             # ventures/<slug>/<slug>-findings.pdf: everything it found out
```

## What you get (in `ventures/<slug>/`)

| Block | Files |
|---|---|
| 01-04 | `01_intake.md`, `02_how_analysis.json`, `03_eeat_quality.json`, `04_niche_pulse.json`, `05_scorecard.json` |
| 06-09 | `06_seeds.csv`, `08_keywords_clean.csv`, `09_serp_raw.json`, `10_clusters_serp.json`, `11_shortlist.csv`, `11_top_competitors.json` |
| 10-13 | `12_competitor_ux.json` (+ `shots/`), `13_competitor_business.json`, `13_competitor_ads.md`, `14_market_analysis.json`, `15_competitor_seo.json`, `15_link_targets.csv` |
| 15-17 | `GUARDRAILS.md`, `ACCESS.md`, `OWNER-TODO.json`, `16_owner_questions.md`, `16_unit_economics.json`, `18_business_case.md`, `18_swot.md`, `19_business_plan.md`, `19_sitemap.json`, `19_seo_calendar_90d.csv` |
| gates | `18_gate3_memo.md`, `20_quick_test.md` (if you pick TEST) |
| all | **`<slug>-findings.pdf`**: the findings report to read or share (made after every run; also the **Download findings PDF** button in the app). It covers the verdict, key numbers, every check, competitors and their prices, the market, links, costs, unit economics, SWOT, the plan, the 90-day calendar and every source used |
| all | `report.html`: a live status page with spend per block |

The state (blocks, gate decisions, the money ledger and the cache) is kept in `data/vm.sqlite`.

## The gates

| Gate | When | Choices |
|---|---|---|
| **1** | after the idea filter | **GO** (start the paid keyword research) / **KILL** (archived, never re-pitched) |
| **2** | after the competitor and market research | **GO** / **PIVOT** (narrow to one country, B2B or a smaller segment; phases 2-3 re-run on it) / **KILL** |
| **3** | after the plan | 7-criteria score out of 5: below 3.0 is a KILL; 3.0-3.5 is a **QUICK TEST** (7 days, max $150, thresholds written first); 3.5 or more is **GO** to build |

Every block has its own pass/kill test from the spec, for example:
- 02: a competitor must already be charging money.
- 03: a trend down more than 30% in 24 months with no ads and quiet forums is a kill.
- 04: ICE must be ≥ 6 and the MVP ≤ 14 days.
- 07: buying-intent volume ≥ 1,000/mo or CPC ≥ $2.

The full list is in [docs/BLOCKS.md](docs/BLOCKS.md).

## Settings

All settings live in `.env` (see `.env.example`):
- caps
- models (default: `claude-sonnet-5-5` for research, `claude-haiku-5-5` for labelling)
- the number of SERPs (default 60), SERP depth (20)
- the year-1 revenue goal used by block 12 ($12,000)
- the assumed conversion rate (1%, labelled as an assumption in every output)
- the countries to compare

Prices for the standard stack used by block 15 are in `vm/prices.json`. Edit them to match your own stack.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests are offline. They run all 18 blocks, the gates, a pivot, a duplicate kill and the budget cap against fake APIs.

## Not in this repo (yet)

Phases 5-6 of the spec are not included:
- the build: Astro/Cloudflare starter, payments, E2E lock
- the growth loop: daily outreach, finance kill-switch, SEO tracking, 90-day gate 4

Phase 4 ends with `OWNER-TODO.json` and the plan files, which are the input for phase 5.

## License

MIT

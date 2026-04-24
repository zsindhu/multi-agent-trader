# Premium Trader — Backlog

Last updated: 2026-04-24

---

## Working rules

1. **Recon-first Claude Code**: Any prompt touching existing subsystems must be structured recon-first. Turn 1 reports findings + proposes a plan, no commits. Turn 2 executes after human review. Read-only is the default; commit permission is a separate explicit grant.
2. **Diagnostics before fixes**: Isolate a variable with an experiment before writing a fix. Failed fixes compound uncertainty; they don't reset it.
3. **Decision transparency everywhere**: Every selection, rejection, and tier transition records WHY in name_observations (selection_reason, selection_score, selection_signals, rejected_reason).
4. **Multi-window metrics**: Never store single-window measurements for things with meaningfully different values across timeframes. Capture short/medium/long; let analysis decide.
5. **Research sandbox over trading bot**: When "ships faster" conflicts with "generates better research data," choose better research data.
6. **Sanity-check inputs, not just outputs**: When a metric exists, verify the data feeding it has the expected shape (row count, distinct values, source distribution) before trusting the metric's value.
7. **Coverage floor on every ingestion service**: Any service that ingests data for the universe must include a daily sanity check that logs WARNING (not just INFO) if total coverage drops below a configurable threshold.
8. **Verify data source capabilities before wiring rules**: Test that an API actually returns the fields you need before building signal logic on top of it. Alpaca options snapshots lack daily_bar/volume; discovered only after rules 5/6 shipped with permanent zeros. Added 2026-04-22.

---

## Thesis

Premium Trader is a **research sandbox** for answering one question:

> Can an agentic LLM-driven system generate repeatable alpha in a market,
> and does the architecture transfer to other markets (Bitcoin perpetuals,
> prediction markets, event-driven equities)?

Options is the first market we're testing in. It has rich structured data,
clear entry and exit semantics, and enough inefficiency that there might be
alpha to capture. If the architecture works here, the same structure
transfers elsewhere with minimal changes to the broker abstraction.

**The core thesis about where alpha comes from:** the differentiator isn't
that the LLM is smarter than a human on any single trade. The LLM's edge is
**scale and breadth** — it can monitor 4,000 names instead of 5, process
every news headline, make consistent decisions across the full universe,
and never get tired or biased. AI removes the cognitive bottleneck that
limits how much capital a single human can intelligently deploy.

**The success metric isn't immediate PnL.** It's whether we can prove the
architecture works AND whether we can run a comprehensive research operation
for the cost of a Netflix subscription. A real hedge fund running this
strategy burns $50,000-100,000/month on data feeds and analyst salaries.
We're targeting under $150/month total. **Cost efficiency is a thesis pillar,
not a constraint.**

The North Star return target is beating the 9-10% passive benchmark, but
that's a long-term measurement. The near-term success criteria are:
1. The data layer captures enough signal to learn from every cycle
2. The intelligence layer (lead agent + research agents) demonstrates
   measurable learning over time via the playbook and skill documents
3. The system is self-documenting enough that walking away for a month and
   coming back, you can understand what it learned and where it's stuck

---

## Architecture overview

```
┌─────────────────────────────────────────────────────┐
│  Layer 4 — Research Interface                       │
│  Plain-HTML inspector at /research                  │
│  CLI tools for ad-hoc queries                       │
│  Eventually: real research dashboard                │
├─────────────────────────────────────────────────────┤
│  Layer 3 — Intelligence Agents                      │
│  Lead Agent (decisions + actions)         ← exists  │
│  Breadth Analyst (universe screening)     ← exists  │
│  Tier 2a Pre-filter (11/11 rules)        ← exists  │
│  Tier 2b LLM reasoning (Llama 3.3)       ← exists  │
│  Fundamentals Analyst (10-K/10-Q reading) ← exists  │
│  Research Analyst (strategy iteration)    ← exists  │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                      │
│  PostgreSQL + JSONB + pgvector            ← exists  │
│  Eight core tables + historical_bars      ← exists  │
│  macro_news_events + symbol_news_headlines← exists  │
│  Skill documents, embeddings, msg bus     ← exists  │
├─────────────────────────────────────────────────────┤
│  Layer 1 — Data Foundation                          │
│  Alpaca (market data, options, execution) ← exists  │
│  Yahoo/yfinance (options vol/OI, short %) ← exists  │
│  Finnhub (earnings, news)                 ← exists  │
│  Stooq + yfinance (historical bulk)       ← exists  │
│  FRED (macro indicators)                  ← exists  │
│  EDGAR (SEC filings)                      ← exists  │
│  Technical indicators (pure Python)       ← exists  │
│  StockTwits (social velocity)             ← exists  │
│  Together AI / Llama 3.3 (Tier 2b)        ← exists  │
└─────────────────────────────────────────────────────┘
```

---

## How to use this backlog

The work is organized into **phases**. Each phase has multiple **batches**.
Each batch is sized to fit one Claude Code prompt and is committed as
multiple separate commits so individual tasks can be reverted.

Status legend:
- `[ ]` not started
- `[~]` in progress
- `[x]` shipped
- `[?]` blocked or needs investigation

Discipline: **work from the top down.** Don't skip ahead to later phases
until earlier phases are complete. If you notice something not in this
file, add it under PARKING LOT and keep working on the current phase.

---

## BUILD NOW vs NEXT WEEK

### Build now (post-fix stabilization)

All Week 3 items shipped. Critical bugs fixed 2026-04-24. System is now
in observation mode.

**Priority 1 — Verify prompt caching effectiveness.** ✅ Cache logging
deployed. Check hit rates after 2:20 PM cycle with new logging. If
cache reads are >50% of input tokens, cost drops to ~$100/month.

**Priority 2 — Observe first funnel-driven trade execution.** Monday
2026-04-28 10:20 AM ET will be the first clean cycle with all fixes
live. Risk gate, scheduling, and CycleSnapshot all corrected.

**Priority 3 — Let the system run 2-4 weeks.** Accumulate funnel-driven
trades for signal attribution. No code changes unless bugs found.

### Shipped (Weeks 1-3 + hotfixes)

- ✅ Sleeve Orchestrator (parallel + consolidation, 4 sleeves)
- ✅ SleeveRiskGate (5 hard limits, now using real equity)
- ✅ Evaluation dashboard (`/research/experiment`)
- ✅ Prompt caching (`cache_control` on system prompt)
- ✅ Multi-leg order infrastructure (not activated)
- ✅ Edge estimate capture (`estimated_edge` on trade_outcomes)
- ✅ Research dashboard (Win95 UI, 3 screens, 7 API endpoints)
- ✅ CycleSnapshot writes restored in orchestrator
- ✅ Risk gate total_capital fixed (was $500K, now portfolio equity)
- ✅ Lead Agent scheduling (20-min interval → 3x daily cron)
- ✅ Legacy scanner disabled (redundant, caused rate limit hangs)
- ✅ Together AI key fix (was sending Anthropic key)
- ✅ Cache hit/miss logging for cost visibility

### On hold for 6-month experiment

- No new sleeves (4 only)
- No signal weight changes without backtester validation
- No Kelly sizing activation
- No Phase 3 architecture transfer
- Allowed: bug fixes, data quality, monitoring, prompt tuning

### Cost projections (updated 2026-04-24)

With cron scheduling (3 cycles/day × 4 sleeves):

| Service | Monthly estimate |
|---------|-----------------|
| Claude API (Lead Agent sleeves) | ~$187 (or ~$100 with cache hits) |
| Claude API (Fundamentals + Research) | ~$8 |
| Together AI (Tier 2b) | ~$2.80 |
| OpenAI (embeddings) | ~$2 |
| DigitalOcean | ~$18 |
| **Total** | **~$218** (or ~$131 with caching) |

April actual: $95.80 as of Apr 24. Apr 24 alone was $38.70 due to
20-min interval before cron fix deployed.

### Operator tasks

1. Rotate compromised credentials (Postgres password + Finnhub key)
2. Fill EXPERIMENT_CHARTER.md specifics

---

## PHASE 1 — Data Foundation

**Goal:** Build the substrate that all future research and intelligence
builds on. Capture every signal the system produces, expand the universe
to test the breadth thesis, wire up high-quality free data feeds, and
expose the data via a plain HTML inspector.

### Batch 1.1 — Research Data Layer Schema `[x]` SHIPPED

Six tables live with pgvector: cycle_snapshots, name_observations,
agent_messages, skill_documents, reasoning_embeddings, agent_capabilities.
Plus agent_actions (unified audit log) and historical_bars (persistent bar
cache). Embeddings service operational.

### Batch 1.2 — Tiered Scanning `[x]` SHIPPED

- `[x]` **1.2.1 Tier 1** — Universe definition. SHIPPED as rule-based Breadth
  Analyst. Daily 8 AM ET sweep of ~6,300 optionable US equities. Mechanical
  filters from config/breadth_analyst.yaml. Pass/reject/near-miss logged
  with full reasoning to name_observations.
- `[x]` **1.2.2-1.2.5** — Superseded by 1.4.0b-a (Tier 2a) and 1.4.0b-b
  (Tier 2b).

### Batch 1.2b — Multi-source historical_bars `[x]` SHIPPED

Stooq ZIP adapter, yfinance adapter, Alpaca adapter. Chunked bulk loader
(fixed OOM). 3.08M rows. Source-aware dedup with priority
`stooq > yfinance > alpaca`.

### Batch 1.3 — Additional Data Feeds `[x]` SHIPPED

- `[x]` **1.3.1** FRED macro — Treasury yields, yield curve, Fed funds, VIX,
  unemployment, inflation expectations. Free, cached 6 hours.
- `[x]` **1.3.2** EDGAR filings — 10-K, 10-Q, 8-K via SEC EDGAR API. Free.
- `[x]` **1.3.3** Technical indicators — RSI, MACD, Bollinger, ATR, SMA/EMA,
  OBV. Pure Python.
- `[x]` **1.3.4** Earnings calendar — Finnhub `/calendar/earnings` bulk
  endpoint with 7-day chunked fetching. ~2,300 events during earnings season.
- `[x]` **1.3.5** News architecture — `macro_news_events` (topic-tagged, 90d
  retention) + `symbol_news_headlines` (on-demand top 200, 35d retention).
- `[x]` **1.3.6** Social sentiment — StockTwits public API, on-demand top 50.
- `[x]` **1.3.7** yfinance options data — Real volume + OI via
  `Ticker.option_chain()`. Replaced Alpaca snapshots for rules 5/6.

### Batch 1.4.0b-a — Tier 2a Mechanical Pre-filter `[x]` SHIPPED (11/11 rules)

**Framing:** Tier 2a answers "Is something different about this name today
vs its own recent history?" Per-name baselines prevent large-cap bias.

**Combination logic:** Weighted sum of normalized scores (0-1), 2-rule
minimum gate, 1.5x earnings amplification.

**Pre-filters:** Liquidity floor (~25% culled), min-history guard (60 days).

**The 11 rules:**
1. `[x]` Volume z-score vs 60d mean/std (z >= 2.0)
2. `[x]` Range expansion vs 20d ATR (>= 1.5x)
3. `[x]` Gap z-score vs 60d overnight gap distribution
4. `[x]` IV rank delta over 5 days (>= 15 points)
5. `[x]` Put/call volume ratio (yfinance, P/C > 1.5 or < 0.5)
6. `[x]` Options volume / OI (yfinance, ratio > 0.30)
7. `[x]` Correlation breakdown vs SPY (20d vs 60d, drop >= 0.3)
8. `[x]` Earnings proximity (1-14 days, 1.5x amplification)
9. `[x]` Short interest level (yfinance, short% > 10% or ratio > 5.0)
10. `[x]` News density z-score (min_news_days=5, now firing)
11. `[x]` Social mention velocity (StockTwits, 10+ recent mentions)

**On-demand data fetch tiers:**

| Source | Top N | Pacing | Rules |
|---|---|---|---|
| historical_bars (DB) | All ~4,200 | None | 1-4, 7 |
| earnings_events (DB) | All ~4,200 | None | 8 |
| Finnhub company news | 200 | 60/min | 10 |
| yfinance (combined) | 100 | ~0.5s/call | 5, 6, 9 |
| StockTwits API | 50 | 1.8s/call | 11 |

**Cron:** 10 AM, 12 PM, 2 PM ET. Latest: ~525 promoted, ~186s runtime.

### Batch 1.4.0b-b — Tier 2b LLM Reasoning Layer `[x]` SHIPPED

Llama 3.3 70B on Together AI ($0.88/M tokens, ~$2.80/month actual). Reads
all promoted names, 25/batch, narrative reasoning stored in
`analysis.tier2b_reasoning`. Cron: 10:10/12:10/2:10 ET. Runtime: ~8 min.

### Batch 1.4.0c — Lead Agent Rewiring `[x]` SHIPPED

Lead Agent reads from Tier 2 promotions (top 50 by composite_score) with
signal profiles + Tier 2b reasoning. Open positions managed independently.
Cost: ~$1.50/cycle via Claude Sonnet 4.6. Daily cap: $15.

**Full pipeline closed end-to-end:**
```
Tier 1 (6,350 → 4,285 daily)
  → Tier 2a (4,285 → ~525, 11 rules, ~186s)
    → Tier 2b (~525 → reasoning strings, Llama 3.3, ~8 min)
      → Lead Agent (top 50 + reasoning, Claude Sonnet, ~$1.50/cycle)
        → Trade decisions + position management
```

### Batch 1.4.1 — Specialized Agents `[x]` SHIPPED

- `[x]` **1.4.1.1 Fundamentals Analyst** — On-demand via Lead Agent tool
  `get_fundamentals(symbol)`. EDGAR filing text + earnings + FRED macro +
  news → Llama 3.3 summary. Cached 24h in agent_messages. ~$0.30/month.
- `[x]` **1.4.1.2/1.4.2.3 Research Analyst** — Daily 5:30 PM ET. Reads
  cycle_snapshots + top 20 promotions + trade outcomes → narrative
  reflection. ~$0.05/month.
- `[x]` **1.4.1.3/1.4.2.4 Pre-market briefing** — Daily 7:30 AM ET. No
  LLM. Assembles Research Analyst reflection + playbook. $0/month.
- `[x]` **1.4.1.4 Prompt caching** — `cache_control: {"type": "ephemeral"}`
  on system prompt. Cache-aware cost tracking. Hit/miss logging added
  2026-04-24.

### Batch 1.4.2 — Learning Loop Activation `[x]` SHIPPED (core items)

- `[x]` **1.4.2.1 Outcome labeler** — Nightly 5 PM ET. Joins trades to
  observations, computes PnL (sell/buy guards), holding period, underlying
  return. 23 pre-funnel outcomes labeled.
- `[x]` **1.4.2.2 Signal-weight learner** — numpy logistic regression.
  L2 regularized, bounded drift (0.3x-3x), CI diagnostics. Min 50
  funnel-driven outcomes. Output: config/learned_weights.json (human-reviewed).
- `[x]` **1.4.2.3 Research Analyst** — See 1.4.1.2 above.
- `[x]` **1.4.2.4 Pre-market briefing** — See 1.4.1.3 above.
- `[ ]` **1.4.2.5 Citation tracking** — Deferred to post-experiment.
- `[ ]` **1.4.2.6 Decay and re-validation** — Deferred to post-experiment.
- `[ ]` **1.4.2.7 Adversarial review** — Deferred.
- `[ ]` **1.4.2.8 Skill document producer** — Deferred.
- `[x]` **1.4.2.9 Lead Agent rewiring** — SHIPPED as 1.4.0c.
- ~~**1.4.2.10 Control Lead Agent**~~ — REPLACED by 4-sleeve experiment.

### Batch 1.4.3 — Validation Pipeline `[x]` SHIPPED (v1)

- `[x]` **1.4.3.1** Config backtester — re-scores historical observations
  under two configs, compares promotion counts + win rates.
- `[ ]` **1.4.3.2** Shadow forward test — deferred until backtester
  produces meaningful candidates.
- `[ ]` **1.4.3.3** Paper trading promotion — deferred.
- `[x]` **1.4.3.4** Pending changes queue — `pending_changes` table.
- `[x]` **1.4.3.5** Manual review gate — implicit (human updates config).

### Batch 1.5 — Research Inspector `[x]` SHIPPED

- `[x]` PostgreSQL views (5 views via migration)
- `[x]` CLI tool (`scripts/research_inspect.py`, 6 subcommands)
- `[x]` `/research` HTML route (5 pages: dashboard, promotions, trades,
  signals, cycle drill-down)
- `[ ]` pgvector semantic search — deferred.

### Batch 1.6 — Robust Statistics Migration `[x]` SHIPPED

- `[x]` `_safe_median()` and `_safe_mad()` in signal_compute.py
- `[x]` Rules 1, 2, 3 migrated to median/MAD (backward-compatible, legacy
  z-scores preserved in analysis JSON)
- `[x]` Rule 4 converted from fixed 15-point threshold to per-name robust
  z-score of 5-day change vs 60-day distribution
- `[x]` Rule 7 enriched with corr_short/corr_long diagnostic fields
- `[x]` MAD=0 fallback to std for thinly-traded names

### Phase 1.5 — Multi-Sleeve Experiment `[~]` IN PROGRESS

- `[x]` **Week 1:** Robust statistics migration, sleeve_id migration,
  4 sleeve configs, SleeveConfig loader, EXPERIMENT_CHARTER.md template
- `[x]` **Week 2:** SleeveOrchestrator (parallel + consolidation),
  SleeveRiskGate (5 hard limits), per-sleeve Tier 2 filtering,
  per-sleeve system prompts, deterministic conflict resolution,
  scheduler wiring with graceful single-agent fallback
- `[x]` **Week 3:** Evaluation dashboard (`/research/experiment`),
  prompt caching, multi-leg infrastructure, edge estimate capture,
  Win95 research dashboard (3 screens, 7 API endpoints),
  CycleSnapshot fix, risk gate fix, scheduling fix, scanner disabled
- `[~]` **Launch:** ~$97K paper, 6 months, charter filled before Day 1.
  All critical bugs fixed 2026-04-24. First clean cycle: Mon 2026-04-28.

### Batch 1.7 — Cross-Database Context Retrieval `[ ]`

Build when Research Analyst needs cross-table queries. Deferred.

---

## PHASE 2 — Real Dashboard (deferred)

## PHASE 3 — Architecture Transferability (deferred)

## PHASE 4 — Model Diversification (partially realized)

- **4a — Ensemble**: second opinion on critical cycles.
- **4b — Specialized models**: ✅ PARTIALLY REALIZED — Tier 2b uses Llama
  3.3 ($2.80/month), Lead Agent uses Claude Sonnet (~$100/month).

---

## PARKING LOT

- ~~Prompt caching across agents (1.4.1.4)~~ ✅ SHIPPED 2026-04-24
- pgvector semantic search via CLI
- Consolidate HistoricalBar reads into single helper
- Credential rotation (Postgres password + Finnhub key)
- Rules 5/6 v2: per-name z-scores (needs options_snapshots history table)
- Rule 9 v2: short interest delta (needs bi-monthly FINRA snapshots)
- Rule 11 v2: social velocity z-score (needs social_mentions history table)
- Reddit ingestion for rule 11 (PRAW + parsing)
- Earnings proximity weight tuning (after outcome labeler)
- Coverage floor sanity checks on yfinance + StockTwits fetches
- Alpaca options chain pagination fix (100 contract cap, calls only)
- Sector Rotation sleeve: 0 candidates every cycle since launch — keep
  running for data but investigate scanner_filter criteria
- Legacy agents/scanner.py: disabled, not deleted. May reference later.
- Internal cost tracker underreports vs Anthropic console (counter resets
  on container restart). Anthropic console is ground truth.

### Bugs
- Two regime classifiers produce parallel outputs
- Legacy dead code: universe_loader.py, tier_writer.py, etc.

---

## OBSERVATIONS

- **O1**: UPDATED — Flywheel's first turn happening: Tier 2b reasoning
  written, Lead Agent reading it, playbook entries updated from funnel.
- **O2**: RESOLVED 2026-04-22 — Lead Agent rewired (1.4.0c).
- **O3**: Real learning requires outcome labeler + Research Analyst +
  pre-market briefing. These are the next builds.
- **O4-O7**: RESOLVED (source-scoping, data feeds, volume bug, earnings).
- **O8**: RESOLVED — min_news_days lowered to 5, now firing on 14 names.
- **O9**: RESOLVED — All 11 rules contributing to composite landscape.
- **O10**: Alpaca OptionsSnapshot lacks daily_bar/volume. Fixed via yfinance.
- **O11**: Lead Agent cost cap raised $5 → $10 → $15 for richer Tier 2 context.
- **O12**: SQLAlchemy json column needs flag_modified() for mutations.
- **O13**: First autonomous funnel cycle (2026-04-20): Lead Agent correctly
  held NXE on merit, declined earnings-contaminated scanner names.
- **O14**: RESOLVED — Lead Agent scheduling changed from 20-min interval
  (~19 cycles/day, $25+/day) to 3x daily cron at 10:20/12:20/14:20 ET.
- **O15**: Sector Rotation sleeve has had 0 candidates in every cycle
  since launch. Not disabled — keeping for data collection.
- **O16**: CRITICAL (RESOLVED) — Sleeve orchestrator was not writing
  CycleSnapshot records since launch. Entire learning flywheel (outcome
  labeler, Research Analyst, signal attribution) was blind to all trade
  decisions. Fixed 2026-04-24.
- **O17**: CRITICAL (RESOLVED) — SleeveRiskGate total_capital hardcoded at
  $500K while actual portfolio equity is ~$97K. Drawdown calculated as
  80.6%, silently blocking every single trade proposal. System spent ~$95
  on LLM calls in April with zero funnel-driven trades executing. Fixed
  2026-04-24.
- **O18**: Two parallel scanning systems were running — legacy
  agents/scanner.py (individual Alpaca bar fetches, rate limit prone)
  alongside the Tier 2a funnel (database reads, fast). Legacy scanner
  disabled 2026-04-24.
- **O19**: Anthropic billing shows $38.70 for Apr 24 vs internal tracker
  showing ~$16. Counter resets on container restart cause underreporting.
  Anthropic console is the ground truth for cost tracking.

---

## STRATEGIC OPEN QUESTIONS

1. **Q1**: Marginal contribution of LLM narrative vs statistical baseline?
   Falsifiable via control Lead Agent (1.4.2.10).
2. **Q2**: Does the validation pipeline catch overfitting?
3. **Q3**: At what trade count do signal weights stabilize? (200 is a guess)
4. **Q4**: Does $150/month hold with all agents? Current: ~$218/month
   (or ~$131 with effective prompt caching). Apr actual: $95.80 through
   Apr 24, but includes $38.70 from pre-cron-fix 20-min interval day.
5. **Q5**: Does the full 11-rule composite produce meaningfully different
   rankings than the old IV-rank-delta-dominated scores?
6. **Q6**: Lead Agent requesting n=10 despite default=50 — monitor.

---

## CHANGELOG

### 2026-04-24 — Critical fixes: risk gate, scheduling, scanner, CycleSnapshot

**Fixes shipped:**
- CycleSnapshot writes restored in sleeve_orchestrator.py — learning
  flywheel was completely disconnected since sleeve architecture launched
- Risk gate total_capital fixed: was hardcoded at $500K, actual equity
  ~$97K, drawdown computed at 80.6% → every trade blocked silently
- Lead Agent scheduling: 20-min interval → 3x daily cron (10:20/12:20/
  14:20 ET), saving ~$20/day in redundant LLM calls
- Legacy scanner disabled: agents/scanner.py hanging container 10+ min
  on startup via Alpaca 429s, output unused by sleeve orchestrator
- Together AI key fix: conflict resolver was sending Anthropic key → 401
- Markdown fence stripping on stored summaries
- Prompt cache hit/miss logging for cost visibility
- Daily LLM cost cap $10 → $15
- Research dashboard: 3 Win95 screens, 7 API endpoints, mobile responsive

**Key discoveries:**
- Zero funnel-driven trades executed since sleeve orchestrator launched
  (every proposal blocked by $500K risk gate bug)
- April Anthropic spend: $95.80 (console) vs ~$50 (internal tracker —
  resets on container restart, underreports)
- Apr 24 alone: $38.70 due to 20-min interval + 4 sleeves before fix
- Sector Rotation sleeve: 0 candidates every cycle (not disabled)

### 2026-04-22 — 11/11 rules + Tier 2b + Lead Agent rewiring + yfinance fix

- News density min_news_days 14 → 5
- Tier 2b shipped (Llama 3.3, $2.80/month, 633/633 reasoned)
- flag_modified() fix for json column persistence
- Lead Agent rewired to Tier 2 promotions (1.4.0c)
- Daily cost cap $5 → $10
- Rules 5/6 wired (Alpaca → discovered volume=0 → switched to yfinance)
- Rule 9 wired (yfinance short interest)
- Rule 11 wired (StockTwits social velocity)
- Combined yfinance fetch for rules 5/6/9
- Together AI integrated

### 2026-04-13 — Phase 1+2: liquidity floor + earnings + news rebuild

- Liquidity floor, history guard, earnings proximity rule
- News architecture split, earnings calendar bulk rebuild
- Chunked Finnhub fetch (1,500-event cap workaround)

### 2026-04-11 — Tier 2a + data feeds

- Tier 2a (6/11 rules), FRED, EDGAR, technical indicators
- Volume window source-hardcode bug fix

### 2026-04-10 — Multi-source historical_bars

3.08M rows, chunked loader, source-aware dedup.

### 2026-04-09 — Schema foundation + Breadth Analyst

### 2026-04-06 — Backlog rewritten under research thesis framing
# Premium Trader — Backlog

Last updated: 2026-04-11

---

## Working rules

1. **Recon-first Claude Code**: Any prompt touching existing subsystems must be structured recon-first. Turn 1 reports findings + proposes a plan, no commits. Turn 2 executes after human review. Read-only is the default; commit permission is a separate explicit grant.
2. **Diagnostics before fixes**: Isolate a variable with an experiment before writing a fix. Failed fixes compound uncertainty; they don't reset it.
3. **Decision transparency everywhere**: Every selection, rejection, and tier transition records WHY in name_observations (selection_reason, selection_score, selection_signals, rejected_reason).
4. **Multi-window metrics**: Never store single-window measurements for things with meaningfully different values across timeframes. Capture short/medium/long; let analysis decide.
5. **Research sandbox over trading bot**: When "ships faster" conflicts with "generates better research data," choose better research data.

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
│  Tier 2a Pre-filter (change detection)    ← exists  │
│  Fundamentals Analyst (10-K/10-Q reading) ← planned │
│  Research Analyst (strategy iteration)    ← planned │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                      │
│  PostgreSQL + JSONB + pgvector            ← exists  │
│  Eight core tables + historical_bars      ← exists  │
│  Skill documents, embeddings, msg bus     ← exists  │
├─────────────────────────────────────────────────────┤
│  Layer 1 — Data Foundation                          │
│  Alpaca (market data, options, execution) ← exists  │
│  Yahoo (spot VIX)                         ← exists  │
│  Finnhub (earnings, news)                 ← exists  │
│  Stooq + yfinance (historical bulk)       ← exists  │
│  FRED (macro indicators)                  ← exists  │
│  EDGAR (SEC filings)                      ← exists  │
│  Technical indicators (pure Python)       ← exists  │
│  Social sentiment (StockTwits/Reddit)     ← planned │
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

### Build now (this session / next 1-2 days)

Nothing. The system needs to **run and generate data** before more code
makes sense. The Tier 2a pre-filter and Breadth Analyst are deployed but
have not been observed against real market data yet.

**Operator tasks (not code):**
1. Run `scripts/run_breadth_analyst.py sweep` on the droplet. Verify AAPL
   `avg_volume_20d` ≈ 28M (source-scoping fix worked) not ≈ 84M (triple-counted).
2. Run `scripts/run_tier2a.py --dry-run` on the droplet. Spot-check:
   how many names promoted? What signal distributions look like? Are the
   6 live rules producing sane scores?
3. Let both crons run for 2-3 trading days. Accumulate name_observations
   data at both tiers.
4. Query the data: `SELECT tier, was_considered, COUNT(*) FROM name_observations
   WHERE timestamp >= NOW() - INTERVAL '3 days' GROUP BY tier, was_considered;`

**Why hold off on code:** Building more without observing the output of
what's deployed violates working rule #2 (diagnostics before fixes). The
Tier 2a signals are theoretical until we see them on real data. Building
1.4.0b-b (LLM reasoning) on top of unvalidated signals would compound
uncertainty.

### Build next week (after 3-5 trading days of observation)

**Priority 1 — Wire remaining Tier 2a rules (as data lands):**
- Rules 5/6 (put/call ratio, options volume/OI) — verify Alpaca provides
  this data in the options chain response, then wire
- Rule 8 (earnings proximity) — wire from existing `earnings_calendar.py`
- Rules 9/11 (short interest, social velocity) — blocked on data ingestion

**Priority 2 — 1.4.0b-b Tier 2b LLM reasoning layer:**
- Only after Tier 2a signal behavior is validated on real data
- Llama 3.3 on Together AI, ~$10/month
- Reads top ~600 from Tier 2a, produces reasoning strings for passes+rejects
- Every reasoning string logged to name_observations

**Priority 3 — 1.4.1.1 Fundamentals Analyst:**
- LLM agent reads EDGAR filings + earnings + FRED macro context
- Produces qualitative context for Tier 3 reasoning

**Priority 4 — 1.4.2.1 Outcome labeler service:**
- Joins name_observations to closed position outcomes
- Ground truth substrate for everything in the learning loop
- Needs enough closed trades to be meaningful (~30 minimum)

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
cache). Embeddings service operational. Consumers do not yet exist beyond
Tier 2a writes — substrate without flywheel.

### Batch 1.2 — Tiered Scanning (rescoped)

- `[x]` **1.2.1 Tier 1** — Universe definition. SHIPPED as rule-based Breadth
  Analyst. Daily 8 AM ET sweep of ~4,500 optionable US equities. Mechanical
  filters from config/breadth_analyst.yaml. Pass/reject/near-miss logged
  with full reasoning to name_observations. **Pending: Part B sanity run.**
- `[~]` **1.2.2-1.2.5** — Superseded. See 1.4.0b-a (Tier 2a) and 1.4.0b-b
  (Tier 2b) below for the actual tier 2/3 implementation.

### Batch 1.2b — Multi-source historical_bars `[x]` SHIPPED

Stooq ZIP adapter (local-file reader), yfinance adapter, Alpaca adapter.
Chunked bulk loader (fixed OOM). 3.08M rows landed. Bug fixes: source-aware
dedup, source-scoped metrics.

### Batch 1.3 — Additional Data Feeds `[x]` SHIPPED (partial)

- `[x]` **1.3.1** FRED macro — `services/fred_service.py`. Treasury yields,
  yield curve, Fed funds, VIX (CBOE official), unemployment, inflation
  expectations. Free, no API key. Cached 6 hours. Wired in bootstrap.
- `[x]` **1.3.2** EDGAR filings — `services/edgar_service.py`. 10-K, 10-Q,
  8-K filings via SEC EDGAR API. Free, no API key. Rate-limited per SEC
  policy. CIK lookup cached. Wired in bootstrap.
- `[x]` **1.3.3** Technical indicators — `services/technical_indicators.py`.
  RSI, MACD, Bollinger Bands, ATR, SMA/EMA, OBV. **Pure Python, no TA-Lib
  dependency.** All functions take OHLCV arrays, return computed values.
- `[x]` **1.3.4** Earnings calendar — `services/earnings_calendar.py`.
  Pre-existing (Finnhub). Gates rule #8 in 1.4.0b-a.
- `[x]` **1.3.5** News feed — `services/news_feed.py`. Pre-existing
  (Finnhub). Feeds rule #10 in 1.4.0b-a.
- `[ ]` **1.3.6** Social sentiment (NEW) — feeds rule #11 in 1.4.0b-a.
  - 1.3.6.1 StockTwits ingestion: symbol-level message volume + bullish/bearish
    ratios. Free API, rate-limited.
  - 1.3.6.2 Reddit ingestion: r/wallstreetbets, r/options, r/stocks via PRAW
    or Pushshift. Track mention velocity (spike vs baseline).
  - 1.3.6.3 Wire sentiment features into Tier 2a as rule #11.
  - 1.3.6.4 Capture in name_observations.selection_signals for counterfactual
    research.

### Batch 1.4.0b-a — Tier 2a Mechanical Pre-filter `[x]` SHIPPED (6/11 rules)

**Framing:** Tier 2a answers "Is something different about this name today
vs its own recent history?" Every rule is a change-detection rule measured
against the name's own distribution. Per-name baselines prevent the
large-cap bias every retail screener has.

**Combination logic:** Each rule produces a normalized signal score (0-1).
Selection score is a weighted sum, but at least 2 independent rules must
fire before promotion. Initial weights equal; tuned by statistical learner
in 1.4.2.2.

**The 11 rules:**
1. `[x]` Volume z-score vs name's 60d mean/std. Threshold: z >= 2.0
2. `[x]` Range expansion vs 20d ATR. Threshold: >= 1.5x
3. `[x]` Gap z-score vs name's 60d overnight gap distribution
4. `[x]` IV rank delta over 5 trading days, >= 15 points
5. `[ ]` Put/call volume ratio anomaly — needs verification (Alpaca options)
6. `[ ]` Options volume / prior-day OI — needs verification
7. `[x]` Correlation breakdown vs SPY (20d vs 60d, drop >= 0.3)
8. `[ ]` Earnings proximity (gating rule, 1-14 days) — needs wiring from 1.3.4
9. `[ ]` Short interest delta — needs FINRA data ingestion
10. `[x]` News density z-score vs 30d baseline
11. `[ ]` Social mention velocity — needs 1.3.6

**Ship phasing:** 6/11 rules live with existing data. Rules 5/6/8 wire
next as verification/wiring completes. Rules 9/11 blocked on data ingestion.

**Deployed:** `agents/tier2a_prefilter.py`, `services/signal_compute.py`,
`config/tier2a.yaml`, `scripts/run_tier2a.py`. Cron: 10 AM, 12 PM, 2 PM ET.

### Batch 1.4.0b-b — Tier 2b LLM Reasoning Layer `[ ]`

Cheap LLM (Llama 3.3 on Together AI, ~$0.20/M tokens) reads top ~600 from
Tier 2a with signals + playbook context + recent agent_messages. For each
name, produces a short reasoning string for both passes and rejects.
Promotes ~200-400 to Tier 3.

Cost envelope: ~$10/month. Pulls Phase 4 cheap-model thesis forward.

Logging: every reasoning string logged to name_observations alongside
mechanical signals. Ship order: after ~1 week of observed Tier 2a signal
behavior.

### Batch 1.4.1 — Specialized Agents `[ ]`

- **1.4.1.1 Fundamentals Analyst** — LLM agent, reads EDGAR filings (1.3.2)
  + earnings calendar (1.3.4) + FRED macro context (1.3.1). Produces
  qualitative context for Tier 3 reasoning. Not a rule generator.
- **1.4.1.2 Research Analyst** — promoted into 1.4.2.3 (depends on outcome
  labeler).
- **1.4.1.3 Pre-market briefing** — promoted into 1.4.2.4.
- **1.4.1.4 Prompt caching** — across Lead Agent + Tier 2b + Fundamentals to
  keep cost envelope intact as context grows.

### Batch 1.4.2 — Learning Loop Activation `[ ]`

**Framing:** Hybrid. Statistics handles quantitative signal-weight learning
where small models on small features are more trustworthy than LLMs. The
LLM handles narrative pattern recognition where qualitative + situational
reasoning is the actual edge. Neither alone is the thesis — the combination
is.

- **1.4.2.1 Outcome labeler** — joins name_observations to closed position
  outcomes. 30-sample minimum, confidence intervals, CIs crossing zero are
  flagged not promoted. Ground truth substrate.
- **1.4.2.2 Statistical signal-weight learner** — logistic regression over
  Tier 2a signal vector vs win/loss outcomes. Retrained monthly once >= ~200
  closed trades exist. Output: updated weights for the 11 rules.
- **1.4.2.3 Research Analyst (narrative-only)** — daily post-market
  reflection. Restricted to narrative reasoning patterns, not predictive
  rules. Writes to skill_documents and agent_messages.
- **1.4.2.4 Pre-market briefing** — reads yesterday's Research Analyst
  reflection + active playbook + pgvector semantic search. Injected into
  Lead Agent's context each cycle.
- **1.4.2.5 Citation tracking** — when Lead Agent cites a playbook entry,
  log the citation + eventual trade outcome. Measure which entries correlate
  with good outcomes.
- **1.4.2.6 Decay and re-validation** — every active playbook entry gets
  re-validated against fresh data on a schedule. Drops below threshold →
  retired.
- **1.4.2.7 Adversarial review (optional)** — second LLM reviews proposed
  playbook entries with adversarial prompt.
- **1.4.2.8 Skill document producer** — each agent writes/updates its own
  skill_doc on schedule. Versioned.
- **1.4.2.9 Lead Agent reads playbook + past reasoning** — the consumer
  side. Currently writes to cycle_snapshots but doesn't read from them.
- **1.4.2.10 Control Lead Agent (falsifiability)** — runs 3 months parallel
  on frozen baseline. If playbook-reading agent doesn't beat it, the
  document-based learning mechanism gets cut.

### Batch 1.4.3 — Validation Pipeline `[ ]`

- **1.4.3.1 Backtester** — replays historical_bars + name_observations,
  compares proposed changes vs current production.
- **1.4.3.2 Shadow forward test** — 20 trading days parallel with production.
- **1.4.3.3 Paper trading promotion** — 30 trading days real broker.
- **1.4.3.4 Pending changes queue** — surfaced in /research.
- **1.4.3.5 Manual review gate** — validated changes still require human
  approval before live capital.

### Batch 1.5 — Research Inspector `[ ]`

- PostgreSQL views for common queries
- CLI inspection tool (`scripts/inspect.py`)
- `/research` route (plain HTML, no JS)
- `/research/cycle/<id>` drill-down
- `/research/search?q=...` pgvector semantic search

---

## PHASE 2 — Real Dashboard (deferred)

UI for inspecting cycles, positions, decisions, rejected candidates. Risk
monitor fixes, timezone handling, sector rotation views. Deferred until
Phase 1 foundation is solid.

## PHASE 3 — Architecture Transferability (deferred)

Extract the four-tier funnel as reusable framework. Prove on BTC perpetuals.
Explore prediction markets as third asset class.

## PHASE 4 — Model Diversification (split)

- **4a — Ensemble for decision quality (near-term)**: Lead Agent's trade
  decisions get second opinion from different model on critical cycles.
- **4b — Specialized models per agent (longer-term)**: cheap models for
  high-volume agents, Claude reserved for Lead Agent + Research Analyst.
  Drives cost from $150 → ~$30/month. Note: 1.4.0b-b already pulls this
  forward as a Phase 1 dependency.

---

## PARKING LOT

- Claude Code scope discipline — recon-first rule in working rules
- Push discipline — "shipped vs pushed vs deployed" status convention
- Prompt caching across agents (1.4.1.4) when context pressures cost
- pgvector semantic search exposed via CLI for ad-hoc queries
- Social sentiment (1.3.6) — StockTwits/Reddit API setup

### UI fixes (deferred until Phase 2)
- Active Positions card unreadable / "Unassigned" badges
- Risk Monitor computation broken
- Time displayed in UTC instead of Eastern
- System Assessment shows JSON as giant code block
- Last Cycle Actions should move from Dashboard to Trade Desk
- Sector Rotation card empty
- Breadth stuck at 50%

### Bugs (small, addressed within batches as discovered)
- Two regime classifiers still produce parallel outputs
- Frontend `buildEquityData` is dead code
- Legacy dead code: universe_loader.py, tier_writer.py, universe_filters.py,
  run_universe_sweep.py (cleanup deferred to step 7)

---

## OBSERVATIONS

- **O1**: Eight tables exist; consumers don't yet exist beyond Tier 2a
  writes. Substrate is real, flywheel is not yet active.
- **O2**: Lead Agent reads from hardcoded list, not from Tier 2 promotions.
  1.4.2.9 is the wiring that connects the funnel end-to-end.
- **O3**: Playbook citation on April 6 was recency, not learning. Real
  learning requires 1.4.2.4 + 1.4.2.9.
- **O4**: Breadth Analyst deployed but sanity-check run still pending. AAPL
  avg_volume_20d ≈ 28M validates source-scoping; ≈ 84M means triple-counting.
- **O5**: RESOLVED — 9 commits pushed 2026-04-11. Tier 2a + Batch 1.3
  feeds now deployed.

---

## STRATEGIC OPEN QUESTIONS

1. **Q1 (sharpened)**: What's the marginal contribution of LLM narrative
   pattern matching over the statistical-only Tier 2a baseline? Falsifiable
   via 1.4.2.10 — control Lead Agent is the experiment.
2. **Q2**: Does the validation pipeline (1.4.3) actually catch overfitting?
   Answerable after 3-5 changes complete the full pipeline.
3. **Q3**: At what closed-trade count do statistical weight updates stabilize?
   The 200-trade floor in 1.4.2.2 is a guess.
4. **Q4**: Does the $150/month envelope hold once 1.4.0b-b, 1.4.1, and
   1.4.2 are all running simultaneously?

---

## CHANGELOG

### 2026-04-11 — Architectural rewrite + Tier 2a + data feeds shipped

**Shipped and pushed:**
- 1.4.0b-a Tier 2a Mechanical Pre-filter (6/11 rules): signal_compute.py,
  tier2a_prefilter.py, tier2a.yaml, run_tier2a.py, cron at 10/12/14 ET
- 1.3.1 FRED macro (fred_service.py)
- 1.3.2 EDGAR filings (edgar_service.py)
- 1.3.3 Technical indicators (technical_indicators.py, pure Python)
- Bootstrap wiring + preflight updates

**Architectural decisions locked in:**
- Hybrid learning loop: statistics for signal weights, LLM for narrative
- 11 change-detection rules with 2-rule-minimum gate
- Control Lead Agent (1.4.2.10) as falsifiability experiment
- Validation pipeline: backtest → 20d shadow → 30d paper
- Phase 4 split: ensemble (decision quality) vs specialized (cost)

### 2026-04-10 — Multi-source historical_bars + bug fixes

3.08M rows (Stooq + yfinance + Alpaca), chunked loader OOM fix,
source-aware dedup, source-scoped metrics fixes.

### 2026-04-09 — Schema foundation + Breadth Analyst

Step 1 schema (name_observations extensions, historical_bars, agent_actions).
Breadth Analyst agent with backfill + daily sweep. Scheduler wiring.

### 2026-04-06 — Backlog rewritten under research thesis framing

Old engineering-task backlog moved to git history. New structure organized
around phases and data layer foundation.

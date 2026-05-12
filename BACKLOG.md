# Premium Trader — Backlog

Last updated: 2026-05-12

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
│  Win95 dashboard (3 screens)               ← exists │
│  CLI tools for ad-hoc queries              ← exists │
│  RAG Chat Agent                            ← planned│
├─────────────────────────────────────────────────────┤
│  Layer 3 — Intelligence Agents                      │
│  Lead Agent (decisions + actions)         ← exists  │
│  Breadth Analyst (universe screening)     ← exists  │
│  Tier 2a Pre-filter (11/11 rules)        ← exists  │
│  Tier 2b LLM reasoning (Llama 3.3)       ← exists  │
│  Fundamentals Analyst (10-K/10-Q reading) ← exists  │
│  Research Analyst (strategy iteration)    ← exists  │
│  Position Sentinel (5-min price monitor)  ← exists  │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                      │
│  PostgreSQL + JSONB + pgvector            ← exists  │
│  Eight core tables + historical_bars      ← exists  │
│  macro_news_events + symbol_news_headlines← exists  │
│  Skill documents, embeddings, msg bus     ← exists  │
│  LLM usage log (persistent cost tracking) ← exists  │
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
│  Together AI / DeepSeek V4-Flash (Chat)    ← planned │
└─────────────────────────────────────────────────────┘
```

---

## System state (as of May 11, 2026)

**What's running:**
- Full pipeline: Tier 1 (6,346) → Tier 2a (514 promoted, 11 rules) → Tier 2b (Llama reasoning) → Lead Agent (4 sleeves, 3 cron cycles/day)
- Learning flywheel: outcome labeler → Research Analyst reflection → pre-market briefing → Lead Agent reads
- Position sentinel: 5-min price checks during market hours, Discord alerts
- Dashboard: Win95 aesthetic — Command Center + History + Rules & Logic

**Performance to date:**
- 44 labeled outcomes: 32 wins (86%), 5 losses (14%)
- 14 funnel-driven outcomes: 5 wins (71%), 2 losses (29%)
- Total PnL: +$3,752.70 (avg win +$128.62, avg loss -$72.60)
- Current positions: AMGN (2 CSPs, one at DANGER alert level)

**What's working well:**
- Funnel producing real, profitable trades
- Lead Agent learning from losses (CHTR lesson → proactive UNP close)
- Strategy rules being created and applied (DDOG post-earnings IV distinction)
- Signal attribution data accumulating (14 funnel-driven outcomes)

**What's broken or suboptimal:**
- Playbook bloat: 148K tokens of regime observations drowning 2.9K tokens of strategy
- Research Analyst reflections are formulaic/repetitive
- 21 ghost trades (March, pre-funnel) polluting the trades table
- Prompt caching showing minimal savings (~$0.01-0.09 per call)
- Cost tracking underreports due to container restart counter resets
- Monthly API cost: ~$200-220/month (over $150 target)

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

## ROADMAP — Current priorities

### Phase 0 — Critical Fixes `[x]` SHIPPED

*Unblocking issues that cost money or degrade system quality.*

- `[x]` **0.1** Remove `_periodic_scanner` from `api/main.py` — was blocking
  event loop and flooding Alpaca API. SHIPPED 2026-05-05.
- `[x]` **0.2** Smart playbook retrieval — `get_playbook()` returns all strategy
  entries + last 7 days regime (time-based, not count-based). Drops per-cycle
  tokens from 151K to ~28K. SHIPPED 2026-05-12.
- `[x]` **0.3** Clean 21 ghost trades — `scripts/clean_ghost_trades.py` marks
  pre-funnel submitted trades as `cancelled`. Dashboard `/trades/history`
  excludes cancelled by default. SHIPPED 2026-05-12.
- `[x]` **0.4** Playbook dedup — regime observations only written on material
  change. `_regime_materially_changed()` in `lead_agent.py:300-347`. SHIPPED 2026-05-04.
- `[x]` **0.5** Prompt caching — tools block now cached with `cache_control:
  {"type": "ephemeral"}` on last tool. System prompt + tools (~4,100 tokens)
  cached on turns 2-10 within each cycle. Estimated ~$32/month savings.
  SHIPPED 2026-05-12.

### Phase 1 — Tiered Memory & Context Retrieval `[x]` SHIPPED

*The Lead Agent reads smarter, not more. Build once, three agents consume.*

- `[x]` **1.9** Embed playbook entries on write (pgvector, OpenAI
  text-embedding-3-small). Embedded after creation in add_playbook_entry
  handler. SHIPPED 2026-05-12.
- `[x]` **1.10** Embed trade outcomes on label. Embedded after batch write
  in outcome labeler. SHIPPED 2026-05-12.
- `[x]` **1.11** `services/context_retrieval.py` — shared retrieval layer.
  Methods: `search_playbook()`, `search_outcomes()`, `search_cycles()`,
  `search_all()`, `get_context_for_symbol()`. Hydrates embedding hits with
  full entity data. SHIPPED 2026-05-12.
- `[x]` **1.12** `get_playbook(query="...")` — semantic search mode via
  ContextRetrievalService. Falls back to default if embeddings disabled.
  SHIPPED 2026-05-12.
- `[x]` **1.13** Weekly summarizer — `agents/weekly_summarizer.py`. Sunday
  6 PM ET. Reads reflections + regime + strategy rules + outcomes. Produces
  actionable digest with signal contradiction analysis. Llama 3.3 via
  Together AI. SHIPPED 2026-05-12.
- `[x]` **1.14** Monthly summarizer — `agents/monthly_summarizer.py`. 1st of
  month 6:30 PM ET. Reads weekly digests + trade aggregates + regime
  trajectory. Llama 3.3. SHIPPED 2026-05-12.
- `[x]` **1.15** Tiered playbook read — default `get_playbook()` now returns:
  all strategy content + 7d regime + last 4 weekly digests + last 12 monthly
  digests. Full temporal depth in ~28K tokens vs 151K. SHIPPED 2026-05-12.

### Phase 2 — RAG Chat Agent `[ ]`

*Natural language interface for querying system data and writing strategy.
DeepSeek V4-Flash on Together AI (~$0.50/month).*

- `[ ]` **2.1** `agents/chat_agent.py` — query router + SQL executor + context
  assembler + Together AI call. Does not exist yet.
- `[ ]` **2.2** `api/routes/chat.py` — POST `/api/chat` endpoint. Does not exist.
- `[ ]` **2.3** Dashboard chat panel — Win95 text input + message history.
  Currently 3 pages only (CommandCenter, History, Rules).
- `[ ]` **2.4** Write-back capability — chat agent can write playbook entries +
  pending_changes.
- `[ ]` **2.5** Claude Code prompt generation — chat agent generates prompts for
  code changes.

**Dependencies:** Phase 1 context retrieval layer (1.11) is shipped. Ready to build.

### Phase 3 — Research Analyst Upgrade `[ ]`

*Better reflections, less boilerplate.*

- `[ ]` **3.1** Tune Research Analyst prompt — require specific observations, not
  generic summaries. Current prompt at `research_analyst.py:32-42` is generic.
- `[ ]` **3.2** Add trade outcome awareness — reflection includes analysis of any
  trades that closed today.
- `[ ]` **3.3** Add week-over-week comparison — reflection compares today's
  promotions/signals to last week.
- `[ ]` **3.4** Add anomaly detection — flag when today's signal landscape differs
  significantly from recent baseline.

### Phase 4 — Execution Reliability `[ ]`

*The system decides correctly but fails to execute. Fix the plumbing.*

- `[ ]` **4.1** Investigate hard close execution failure pattern — CHTR (10
  cycles), AMGN (4 cycles).
- `[ ]` **4.2** Add order retry logic — if a limit order doesn't fill within 2
  minutes, resubmit at market or more aggressive limit. Currently only 429
  rate-limit retry exists (`alpaca_broker.py:758-780`).
- `[ ]` **4.3** Add order status dashboard panel.
- `[ ]` **4.4** Kill switch — emergency endpoint to close all positions. Does not
  exist.

### Phase 5 — Signal Learner Activation `[?]` BLOCKED

*Requires ~50 funnel-driven outcomes. Currently at 14.*

- `[x]` **5.1** Signal learner — `services/signal_learner.py`. Logistic regression,
  L2 regularized, MIN_SAMPLES=50, CONFIDENCE_THRESHOLD=200, bounded drift
  (0.3x-3x). Output: `config/learned_weights.json` (human-reviewed).
- `[x]` **5.2** Config backtester — `scripts/run_backtest_config.py` (238 lines).
  Replays historical observations under two configs, writes to pending_changes.
- `[ ]` **5.3** Review and apply first weight update — `config/learned_weights.json`
  does not exist yet (created on-demand when learner runs).
- `[ ]` **5.4** Control Lead Agent (1.4.2.10) — frozen baseline for comparison.

**Gating:** At ~2 funnel-driven trades/week, need ~18 more weeks to reach 50.
Estimated late June 2026.

### Phase 6 — Cost Optimization `[ ]`

*Stay within budget as the system scales.*

- `[x]` **6.1** Tools block caching — ~$32/month savings (shipped as 0.5).
- `[ ]` **6.2** Reduce sleeve count if Sector Rotation continues showing 0 candidates.
- `[ ]` **6.3** Move Fundamentals + Research Analyst to DeepSeek V4-Flash.
- `[x]` **6.4** Tiered playbook read — shipped as 1.15.
- `[ ]` **6.5** Evaluate Llama 4 Scout or DeepSeek V4-Flash for Tier 2b.

**Monthly cost targets:**
- Current: ~$220/month
- After Phase 0+1: ~$160/month
- After Phase 6: ~$120-140/month
- Target: under $150/month

### Phase 7 — Strategy Expansion (Q3 2026) `[ ]`

*Only after CSP strategy is validated with 100+ funnel-driven outcomes.*

- `[ ]` **7.1** Post-earnings momentum sleeve.
- `[ ]` **7.2** Iron condors / strangles for range-bound names.
- `[ ]` **7.3** Multi-leg order activation (infrastructure already built).
- `[ ]` **7.4** Architecture transferability test — BTC perpetuals or prediction markets.

**Gating:** Don't build until CSP strategy has 100+ funnel-driven outcomes and a
validated edge.

---

## Cost projections (updated 2026-05-11)

With cron scheduling (3 cycles/day x 4 sleeves):

| Service | Monthly estimate |
|---------|-----------------|
| Claude API (Lead Agent sleeves) | ~$187 (or ~$100 with cache hits) |
| Claude API (Fundamentals + Research) | ~$8 |
| Together AI (Tier 2b) | ~$2.80 |
| OpenAI (embeddings) | ~$2 |
| Together AI (Chat Agent, DeepSeek V4-Flash) | ~$0.50 (planned) |
| DigitalOcean | ~$18 |
| **Total** | **~$218** (or ~$131 with caching) |

April actual: $95.80 as of Apr 24. Apr 24 alone was $38.70 due to
20-min interval before cron fix deployed.

### Operator tasks

1. Rotate compromised credentials (Postgres password + Finnhub key)
2. Fill EXPERIMENT_CHARTER.md specifics (exists as template, no values filled)

---

## PHASE 1 — Data Foundation (SHIPPED)

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
Tier 1 (6,350 -> 4,285 daily)
  -> Tier 2a (4,285 -> ~525, 11 rules, ~186s)
    -> Tier 2b (~525 -> reasoning strings, Llama 3.3, ~8 min)
      -> Lead Agent (top 50 + reasoning, Claude Sonnet, ~$1.50/cycle)
        -> Trade decisions + position management
```

### Batch 1.4.1 — Specialized Agents `[x]` SHIPPED

- `[x]` **1.4.1.1 Fundamentals Analyst** — On-demand via Lead Agent tool
  `get_fundamentals(symbol)`. EDGAR filing text + earnings + FRED macro +
  news -> Llama 3.3 summary. Cached 24h in agent_messages. ~$0.30/month.
- `[x]` **1.4.1.2/1.4.2.3 Research Analyst** — Daily 5:30 PM ET. Reads
  cycle_snapshots + top 20 promotions + trade outcomes -> narrative
  reflection. ~$0.05/month.
- `[x]` **1.4.1.3/1.4.2.4 Pre-market briefing** — Daily 7:30 AM ET. No
  LLM. Assembles Research Analyst reflection + playbook. $0/month.
- `[x]` **1.4.1.4 Prompt caching** — `cache_control: {"type": "ephemeral"}`
  on system prompt. Cache-aware cost tracking. Hit/miss logging added
  2026-04-24.

### Batch 1.4.2 — Learning Loop Activation `[x]` SHIPPED (core items)

- `[x]` **1.4.2.1 Outcome labeler** — Nightly 5 PM ET. Joins trades to
  observations, computes PnL (sell/buy guards + round-trip matching),
  holding period, underlying return. 44 outcomes labeled (14 funnel-driven).
  Round-trip fix shipped 2026-05-04 — SQL JOIN for sell_to_open + buy_to_close.
- `[x]` **1.4.2.2 Signal-weight learner** — numpy logistic regression.
  L2 regularized, bounded drift (0.3x-3x), CI diagnostics. Min 50
  funnel-driven outcomes. Output: config/learned_weights.json (human-reviewed).
  EXISTS but WAITING — only 14 funnel-driven outcomes, needs 50.
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

### Batch 1.7 — RAG Chat Agent `[ ]`

**Purpose:** Natural language interface for querying all system data — cycle
history, trade outcomes, promotions, signal scores, agent reasoning, config,
and logs. Ask questions in plain English instead of writing SQL or CLI commands.

**Architecture:**
- **Dual retrieval:** SQL generation for structured queries (cycle_snapshots,
  name_observations, trade_outcomes) + pgvector semantic search for unstructured
  data (agent_messages, skill_documents, reasoning_embeddings)
- **Model:** DeepSeek V4-Flash on Together AI (~$0.20/M input, ~$0.60/M output).
  Fast, cheap, good at instruction-following and code generation (SQL).
- **UI:** Win95-themed chat panel in the research dashboard (matches existing
  design language)

**Example queries and retrieval strategies:**
1. "What were the top 5 promotions last cycle?" -> SQL on name_observations
2. "Why did the Lead Agent pass on AAPL yesterday?" -> semantic search on
   agent_messages filtered by symbol + date
3. "What's my total PnL this week?" -> SQL on trade_outcomes
4. "What did the Research Analyst learn about earnings plays?" -> semantic
   search on skill_documents
5. "Show me all trades where estimated_edge > 0.15" -> SQL on trade_outcomes
6. "Which rules fired most often this month?" -> SQL aggregate on
   name_observations analysis JSON
7. "Compare Momentum sleeve vs Mean Reversion sleeve win rates" -> SQL on
   trade_outcomes joined to cycle_snapshots

**Implementation (4 components, no new tables):**
1. `agents/chat_agent.py` — Query classifier (SQL vs semantic vs hybrid),
   SQL generator with schema context, pgvector search, response formatter.
   Uses DeepSeek V4-Flash via Together AI client (same pattern as Tier 2b).
2. `routes/chat.py` — POST `/api/chat` endpoint. Session history in
   memory (not persisted). Rate limit: 30 req/min.
3. Dashboard component — Chat panel in research dashboard. Collapsible sidebar
   or dedicated `/research/chat` page. Markdown rendering for responses.
4. Schema context — Static schema description injected into system prompt so
   DeepSeek can generate correct SQL without hallucinating column names.

**Cost:** ~$0.50/month assuming ~20 queries/day, avg 2K tokens/query.

**Dependencies:** PostgreSQL with pgvector (exists), Together AI client
(exists), research dashboard (exists), agent_messages table (exists),
context retrieval layer (exists, shipped as 1.11). Ready to build.

**Model choice rationale — three-model architecture:**
- **Claude Sonnet 4.6** — Lead Agent trade decisions. Needs maximum reasoning
  quality for capital allocation. ~$187/month (or ~$100 with caching).
- **Llama 3.3 70B (Together AI)** — Tier 2b reasoning, Fundamentals Analyst,
  Research Analyst. Bulk narrative generation where good-enough quality at
  1/50th the cost matters. ~$3/month.
- **DeepSeek V4-Flash (Together AI)** — RAG Chat Agent. Fast, cheap,
  instruction-following. Perfect for SQL generation and Q&A where latency
  and cost matter more than frontier reasoning. ~$0.50/month.

### Phase 1.5 — Multi-Sleeve Experiment `[x]` SHIPPED

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
- `[x]` **Launch:** ~$97K paper, running since 2026-04-28. All critical
  bugs fixed. 44 outcomes labeled, 14 funnel-driven.

### Batch 1.8 — Cross-Database Context Retrieval `[ ]`

Build when Research Analyst needs cross-table queries. Deferred.
Superseded by Phase 1 tiered memory roadmap (items 1.9-1.15).

---

## PHASE 2 — Real Dashboard `[x]` SHIPPED (v1)

Win95 aesthetic dashboard with 3 screens:
- **Command Center** — portfolio overview, positions, sentinel alerts
- **History** — trade history with status filters, per-filter summary stats
- **Rules & Logic** — daily schedule, system configuration

---

## PHASE 3 — Architecture Transferability (deferred)

## PHASE 4 — Model Diversification (partially realized)

- **4a — Ensemble**: second opinion on critical cycles.
- **4b — Three-model architecture:** PARTIALLY REALIZED
  - Claude Sonnet 4.6: Lead Agent trade decisions (~$187/month, ~$100 with caching)
  - Llama 3.3 70B (Together AI): Tier 2b + Fundamentals + Research Analyst (~$3/month)
  - DeepSeek V4-Flash (Together AI): RAG Chat Agent (~$0.50/month) — planned

---

## Shipped (post-Apr-24 through May 12)

- Position sentinel — 5-min price checks, 3 alert levels, Discord notifications (2026-05-02)
- Trade status filters in History page with toggle buttons + per-filter summary stats
- Daily Schedule panel in Rules page with collapsible cycle groups
- History page empty panel fix + filtering on all tables
- Market hours guard on startup cycle
- LLM persistent usage log table (survives container restarts)
- Outcome labeler round-trip fix — SQL JOIN for sell_to_open + buy_to_close matching (2026-05-04)
- Playbook regime observation dedup — only writes on material change (2026-05-04)
- Background scanner removed from API container (2026-05-05)
- Smart playbook retrieval — all strategy + 7d regime (2026-05-12)
- Ghost trade cleanup script + cancelled exclusion from dashboard (2026-05-12)
- Tools block caching for ~$32/month savings (2026-05-12)
- Playbook + trade outcome embeddings on write (2026-05-12)
- Weekly summarizer — Sunday 6 PM ET, actionable digest with signal contradictions (2026-05-12)
- Monthly summarizer — 1st of month 6:30 PM ET (2026-05-12)
- Context retrieval service — semantic search across playbook, outcomes, cycles (2026-05-12)
- Semantic playbook query + tiered read with weekly/monthly digests (2026-05-12)
- Vector search parameter binding fix for asyncpg (2026-05-12)

### On hold for 6-month experiment

- No new sleeves (4 only)
- No signal weight changes without backtester validation
- No Kelly sizing activation
- No Phase 3 architecture transfer
- Allowed: bug fixes, data quality, monitoring, prompt tuning

---

## PARKING LOT

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
  on container restart). Anthropic console is ground truth. Persistent
  llm_usage_log table added but verify dashboard reads from it.
- Discord webhook for notifications (notifier built, no webhook configured)
- Daily health check email/alert
- Annual summarizer (when system has 12+ months of data)

### Bugs
- Two regime classifiers produce parallel outputs
- Legacy dead code: universe_loader.py, tier_writer.py, etc.

---

## OBSERVATIONS

- **O1**: UPDATED — Flywheel running: Tier 2b reasoning written, Lead Agent
  reading it, playbook entries updated from funnel, outcome labeler closing
  the loop. 44 labeled outcomes, 14 funnel-driven.
- **O2**: RESOLVED 2026-04-22 — Lead Agent rewired (1.4.0c).
- **O3**: RESOLVED — Outcome labeler + Research Analyst + pre-market briefing
  all shipped and running.
- **O4-O7**: RESOLVED (source-scoping, data feeds, volume bug, earnings).
- **O8**: RESOLVED — min_news_days lowered to 5, now firing on 14 names.
- **O9**: RESOLVED — All 11 rules contributing to composite landscape.
- **O10**: Alpaca OptionsSnapshot lacks daily_bar/volume. Fixed via yfinance.
- **O11**: Lead Agent cost cap raised $5 -> $10 -> $15 for richer Tier 2 context.
- **O12**: SQLAlchemy json column needs flag_modified() for mutations.
- **O13**: First autonomous funnel cycle (2026-04-20): Lead Agent correctly
  held NXE on merit, declined earnings-contaminated scanner names.
- **O14**: RESOLVED — Lead Agent scheduling: 20-min interval -> 3x daily cron.
- **O15**: Sector Rotation sleeve: 0 candidates every cycle since launch.
- **O16**: RESOLVED — CycleSnapshot writes restored 2026-04-24.
- **O17**: RESOLVED — SleeveRiskGate total_capital fixed 2026-04-24.
- **O18**: RESOLVED — Legacy scanner disabled 2026-04-24, removed from API 2026-05-05.
- **O19**: Anthropic billing vs internal tracker discrepancy — persistent
  llm_usage_log table shipped to fix counter reset issue.
- **O20**: Playbook bloat — 148K tokens of regime observations drowning 2.9K
  tokens of strategy. get_playbook() returns flat 20 most recent entries
  regardless of category. Needs smart retrieval (Phase 0, item 0.2).
- **O21**: Research Analyst reflections are formulaic and repetitive. Same
  structure every day regardless of what happened. Needs prompt tuning
  (Phase 3).
- **O22**: 21 ghost trades from March (pre-funnel, status=submitted, no
  order_id) polluting trades table and dashboard. Need cancellation (Phase 0, item 0.3).
- **O23**: Prompt caching showing minimal savings ($0.01-0.09 per call) despite
  correct cache_control format. Expected $0.50+ savings. Needs investigation
  (Phase 0, item 0.5).
- **O24**: Lead Agent learning from losses: CHTR loss -> proactive UNP close.
  DDOG post-earnings IV distinction noted as strategy_rule. First evidence
  of genuine learning loop.
- **O25**: Hard close execution failures — CHTR took 10 cycles to close,
  AMGN taking 4+ cycles. Limit orders not filling. Needs order retry logic
  (Phase 4).

---

## STRATEGIC OPEN QUESTIONS

1. **Q1**: Marginal contribution of LLM narrative vs statistical baseline?
   Falsifiable via control Lead Agent (Phase 5, item 5.4).
2. **Q2**: Does the validation pipeline catch overfitting?
3. **Q3**: At what trade count do signal weights stabilize? (200 is a guess)
4. **Q4**: Does $150/month hold with all agents? Current: ~$220/month.
   Needs Phase 0 + Phase 6 optimizations.
5. **Q5**: Does the full 11-rule composite produce meaningfully different
   rankings than the old IV-rank-delta-dominated scores?
6. **Q6**: Lead Agent requesting n=10 despite default=50 — monitor.

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| Apr 22 | 11 rules, absolute thresholds (v1) | Ship and validate before z-score v2 |
| Apr 22 | Llama 3.3 for Tier 2b, Claude for Lead Agent | Cost tier matching: cheap model for bulk, expensive for decisions |
| Apr 24 | 3x daily cron instead of 20-min interval | Eliminate redundant cycles reading same Tier 2 data |
| Apr 24 | Dynamic risk gate capital from portfolio equity | Hardcoded $500K was blocking all trades |
| May 2 | Keep all 4 sleeves despite Sector Rotation 0 candidates | Accumulate data before disabling |
| May 4 | Keep CSP-only strategy, don't add directional trades yet | Validate premium selling with 100+ outcomes before expanding |
| May 11 | Tiered memory over raw playbook dump | 148K tokens of regime noise vs 2.9K of strategy |
| May 11 | DeepSeek V4-Flash for chat agent, not Claude | Data Q&A doesn't need frontier reasoning |
| May 11 | Preserve all regime observations in DB, compress for retrieval | Historical patterns have long-term value |

---

## Success Metrics

**Existence stage (now through June 2026):**
- [ ] 50 funnel-driven outcomes labeled (currently 14)
- [ ] Signal learner produces first weight proposal
- [ ] Win rate on funnel-driven trades > 60% (currently 71%)
- [ ] Profit factor > 2.0 (gross wins / gross losses)
- [ ] Monthly API cost under $150 (currently ~$220)
- [x] Lead Agent demonstrates learning (cites playbook lessons in trade decisions)

**Growth stage (July-September 2026):**
- [ ] 100+ funnel-driven outcomes
- [ ] Control Lead Agent comparison completed
- [ ] First weight update applied and validated
- [ ] Weekly and monthly summaries producing actionable insights
- [ ] Chat agent operational for system inspection

**Maturity stage (Q4 2026+):**
- [ ] Strategy expansion (directional trades) validated
- [ ] Architecture transfer to second market tested
- [ ] Annual cost under $1,800 ($150/month)
- [ ] System operates autonomously with weekly human review only

---

## CHANGELOG

### 2026-05-12 — Phase 0 complete + Phase 1 shipped

**Phase 0 (all 5 items shipped):**
- Smart playbook retrieval: all strategy + last 7 days regime (time-based)
- Ghost trade cleanup: scripts/clean_ghost_trades.py + dashboard exclusion
- Tools block caching: cache_control on last tool, ~$32/month savings

**Phase 1 Tiered Memory (all 7 items shipped):**
- Playbook entries + trade outcomes embedded on write (pgvector)
- Weekly summarizer (Sunday 6 PM ET): actionable digest with strategy rule
  evaluation, new patterns, signal contradictions, trade outcomes
- Monthly summarizer (1st of month 6:30 PM ET): long-horizon summary
- Context retrieval service: semantic search across playbook, outcomes, cycles
- Semantic get_playbook(query="..."): embedding similarity search
- Tiered playbook read: strategy + 7d regime + 4 weekly + 12 monthly digests
- Vector search CAST() fix for asyncpg parameter binding

### 2026-05-11 — Roadmap reconciliation + backlog rewrite

- Reconciled roadmap with codebase: verified built/not-built status of all items
- Added phased roadmap (Phases 0-7) with accurate implementation status
- Updated performance data: 44 outcomes, 14 funnel-driven, +$3,752.70 PnL
- Added system state section, decision log, success metrics
- Recorded 8 post-Apr-27 shipped items in changelog

### 2026-05-05 — Background scanner removed from API

- `_periodic_scanner` removed from api/main.py lifespan
- API container now only serves HTTP — no background Alpaca calls

### 2026-05-04 — Outcome labeler round-trip fix + playbook dedup

- Outcome labeler: SQL JOIN for sell_to_open + buy_to_close matching
  (was missing all actively-managed positions with status=filled)
- Playbook dedup: regime_observation only written on material change
  (regime shift, VIX threshold cross, SPY trend reversal)

### 2026-05-02 — Position sentinel + dashboard improvements

- Position sentinel: 5-min price checks, 3 alert levels (WARNING/DANGER/CRITICAL),
  Discord notifications for DANGER+
- Trade status filters in History page with toggle buttons
- Daily Schedule panel in Rules page with collapsible cycle groups
- History page filtering on all tables
- Market hours guard on startup cycle
- LLM persistent usage log table

### 2026-04-27 — RAG Chat Agent roadmap + three-model architecture

- Added RAG Chat Agent to roadmap (Batch 1.7)
- Three-model architecture finalized: Claude (trade decisions), Llama (bulk reasoning), DeepSeek (chat Q&A)

### 2026-04-24 — Critical fixes: risk gate, scheduling, scanner, CycleSnapshot

**Fixes shipped:**
- CycleSnapshot writes restored in sleeve_orchestrator.py — learning
  flywheel was completely disconnected since sleeve architecture launched
- Risk gate total_capital fixed: was hardcoded at $500K, actual equity
  ~$97K, drawdown computed at 80.6% -> every trade blocked silently
- Lead Agent scheduling: 20-min interval -> 3x daily cron (10:20/12:20/
  14:20 ET), saving ~$20/day in redundant LLM calls
- Legacy scanner disabled: agents/scanner.py hanging container 10+ min
  on startup via Alpaca 429s, output unused by sleeve orchestrator
- Together AI key fix: conflict resolver was sending Anthropic key -> 401
- Markdown fence stripping on stored summaries
- Prompt cache hit/miss logging for cost visibility
- Daily LLM cost cap $10 -> $15
- Research dashboard: 3 Win95 screens, 7 API endpoints, mobile responsive

**Key discoveries:**
- Zero funnel-driven trades executed since sleeve orchestrator launched
  (every proposal blocked by $500K risk gate bug)
- April Anthropic spend: $95.80 (console) vs ~$50 (internal tracker —
  resets on container restart, underreports)
- Apr 24 alone: $38.70 due to 20-min interval + 4 sleeves before fix
- Sector Rotation sleeve: 0 candidates every cycle (not disabled)

### 2026-04-22 — 11/11 rules + Tier 2b + Lead Agent rewiring + yfinance fix

- News density min_news_days 14 -> 5
- Tier 2b shipped (Llama 3.3, $2.80/month, 633/633 reasoned)
- flag_modified() fix for json column persistence
- Lead Agent rewired to Tier 2 promotions (1.4.0c)
- Daily cost cap $5 -> $10
- Rules 5/6 wired (Alpaca -> discovered volume=0 -> switched to yfinance)
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

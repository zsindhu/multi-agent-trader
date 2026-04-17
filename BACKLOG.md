# Premium Trader — Backlog

Last updated: 2026-04-13

---

## Working rules

1. **Recon-first Claude Code**: Any prompt touching existing subsystems must be structured recon-first. Turn 1 reports findings + proposes a plan, no commits. Turn 2 executes after human review. Read-only is the default; commit permission is a separate explicit grant.
2. **Diagnostics before fixes**: Isolate a variable with an experiment before writing a fix. Failed fixes compound uncertainty; they don't reset it.
3. **Decision transparency everywhere**: Every selection, rejection, and tier transition records WHY in name_observations (selection_reason, selection_score, selection_signals, rejected_reason).
4. **Multi-window metrics**: Never store single-window measurements for things with meaningfully different values across timeframes. Capture short/medium/long; let analysis decide.
5. **Research sandbox over trading bot**: When "ships faster" conflicts with "generates better research data," choose better research data.
6. **Sanity-check inputs, not just outputs**: When a metric exists, verify the data feeding it has the expected shape (row count, distinct values, source distribution) before trusting the metric's value. A plausible-looking output can hide a wrong input. Added 2026-04-11 after the volume-window bug; reinforced 2026-04-13 by the earnings-coverage and news-warm-up findings.
7. **Coverage floor on every ingestion service**: Any service that ingests data for the universe must include a daily sanity check that logs WARNING (not just INFO) if total coverage drops below a configurable threshold. Added 2026-04-13 — would have caught the 30-event earnings calendar issue on day one rather than during Tier 2a verification two weeks later.

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
│  Tier 2b LLM reasoning (narrative)        ← planned │
│  Fundamentals Analyst (10-K/10-Q reading) ← planned │
│  Research Analyst (strategy iteration)    ← planned │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                      │
│  PostgreSQL + JSONB + pgvector            ← exists  │
│  Eight core tables + historical_bars      ← exists  │
│  macro_news_events + symbol_news_headlines← exists  │
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

**Priority 1 — News density warm-up strategy decision.** Currently `news_density` returns `insufficient_news_history` for every promoted name because the new `symbol_news_headlines` table has <14 days of accumulated baseline. Two options:
- Lower `min_news_days` from 14 to ~5 (signal contributes weeks earlier, accept noisier baseline initially)
- Wait the full 14 days (statistically rigorous, but Tier 2a runs without news_density contribution for 2 weeks)

This is a 30-minute decision + small config change, not a build. Tabled per 2026-04-13 session — revisit when ready.

**Priority 2 — 1.4.0b-b Tier 2b LLM reasoning layer.** With Phase 1+2 wiring verified working and earnings calendar coverage now restored to universe scale, Tier 2a outputs are healthy enough to layer reasoning on top. This is the single highest-leverage build remaining.
- Llama 3.3 on Together AI, ~$10/month
- Reads top ~200-400 from Tier 2a (the actual passes, not 600 as previously specced — Tier 2a's gate is now meaningfully selective)
- Produces narrative reasoning strings for both passes and rejects
- Every reasoning string logged to name_observations alongside mechanical signals
- Pulls Phase 4 cheap-model thesis forward into Phase 1

**Priority 3 — Lead Agent rewiring (1.4.2.9).** Currently reads from hardcoded list, ignoring the funnel. After Tier 2b ships, wire Lead Agent to read top names from Tier 2 promotions ordered by composite score. This closes the funnel end-to-end — Tier 1 → Tier 2a → Tier 2b → Lead Agent decisions.

**Operator tasks (low-effort hygiene):**
1. Reconcile divergent BACKLOG.md from 2026-04-12 — ✅ this file is the reconciled merge.
2. Rotate compromised credentials: `POSTGRES_PASSWORD=multiagent2026!` and `FINNHUB_API_KEY` (both pasted in chat during 2026-04-11 and 2026-04-13 sessions).
3. Investigate the SQLAlchemy DBAPI error from 2026-04-11 Tier 2a dry-run logs. Caught silently with 0 errors in final stats — likely transient but worth confirming.

### Build next week (after Tier 2b + Lead Agent ship)

**Priority 1 — Wire remaining Tier 2a rules:**
- Rules 5/6 (put/call ratio, options volume/OI) — verify Alpaca provides this data in the options chain response, then wire
- Rules 9/11 (short interest, social velocity) — blocked on data ingestion (FINRA + 1.3.6)

**Priority 2 — 1.4.1.1 Fundamentals Analyst:**
- LLM agent reads EDGAR filings + earnings + FRED macro context
- Produces qualitative context for Tier 3 reasoning

**Priority 3 — 1.4.2.1 Outcome labeler service:**
- Joins name_observations to closed position outcomes
- Ground truth substrate for everything in the learning loop
- Needs enough closed trades to be meaningful (~30 minimum). Lead Agent must be wired (Priority 3 above) before any trades flow from the funnel.

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
  Analyst. Daily 8 AM ET sweep of ~6,300 optionable US equities. Mechanical
  filters from config/breadth_analyst.yaml. Pass/reject/near-miss logged
  with full reasoning to name_observations. Sanity-check verified 2026-04-11
  (AAPL avg_volume_20d/60d/252d show three distinct values after source-scoping
  bug fix).
- `[~]` **1.2.2-1.2.5** — Superseded. See 1.4.0b-a (Tier 2a) and 1.4.0b-b
  (Tier 2b) below for the actual tier 2/3 implementation.

### Batch 1.2b — Multi-source historical_bars `[x]` SHIPPED

Stooq ZIP adapter (local-file reader), yfinance adapter, Alpaca adapter.
Chunked bulk loader (fixed OOM). 3.08M rows landed. Bug fixes: source-aware
dedup, source-scoped metrics. Read pattern fix 2026-04-11 (consumers no
longer hardcode `source='alpaca'`; read from all sources with bar_date dedup
and priority `stooq > yfinance > alpaca`).

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
  Rebuilt 2026-04-13 for universe-scale coverage via Finnhub `/calendar/earnings`
  bulk endpoint. Daily refresh covers next 30 days. Coverage sanity check
  fires WARNING if next-30-days events drop below 200. Now provides ~1,500-2,500
  events per refresh during earnings season vs the pre-rebuild ~30. Gates
  rule #8 in 1.4.0b-a.
- `[x]` **1.3.5** News feed — Rebuilt 2026-04-13 into split architecture
  (see 1.3.5b below). Old `news_headlines` table renamed to
  `news_headlines_legacy`.
- `[x]` **1.3.5b** News architecture (NEW, 2026-04-13) — Split into two
  tables reflecting two distinct purposes:
  - `macro_news_events` — market-wide news from Finnhub general endpoint.
    Topic-tagged at ingestion (monetary_policy, inflation_data, geopolitical,
    macro_data, market_action, general). 90-day retention. Logged but does
    NOT affect Tier 2a scoring — exists for future agents to reference when
    constructing playbook entries or reasoning about why a name moved.
  - `symbol_news_headlines` — per-name company news fetched on-demand for
    the top 200 Tier 2a candidates per cycle. 35-day retention. Feeds
    news_density rule. Distinguishes four states in `analysis` JSON:
    `news_density_below_threshold`, `no_news` (real signal — absence is
    information), `not_evaluated` (not in top-200), `fetch_failed`.
- `[ ]` **1.3.6** Social sentiment — feeds rule #11 in 1.4.0b-a.
  - 1.3.6.1 StockTwits ingestion: symbol-level message volume + bullish/bearish
    ratios. Free API, rate-limited.
  - 1.3.6.2 Reddit ingestion: r/wallstreetbets, r/options, r/stocks via PRAW
    or Pushshift. Track mention velocity (spike vs baseline).
  - 1.3.6.3 Wire sentiment features into Tier 2a as rule #11.
  - 1.3.6.4 Capture in name_observations.selection_signals for counterfactual
    research.

### Batch 1.4.0b-a — Tier 2a Mechanical Pre-filter `[x]` SHIPPED (7/11 rules + structural improvements)

**Framing:** Tier 2a answers "Is something different about this name today
vs its own recent history?" Every rule is a change-detection rule measured
against the name's own distribution. Per-name baselines prevent the
large-cap bias every retail screener has.

**Combination logic:** Each rule produces a normalized signal score (0-1).
Selection score is a weighted sum, but at least 2 independent rules must
fire before promotion. Composite score multiplied by amplification multiplier
when earnings_proximity fires (default 1.5x, applied to final composite
including news_density). Initial weights equal; tuned by statistical learner
in 1.4.2.2.

**Pre-filters (run before any signal compute, added 2026-04-13):**
- **Liquidity floor:** symbols below `min_daily_dollar_volume` (default $10M)
  rejected with `rejection_reason="insufficient_liquidity"`. Rejected names
  still logged to name_observations for research. Verified 2026-04-13: 1,042
  of 4,241 Tier 1 passes filtered (~25%).
- **Min-history guard:** volume_zscore, range_expansion, gap_zscore, and
  correlation_breakdown skip with `reason="insufficient_history"` if input
  bar series has fewer than 60 distinct trading days (configurable per-rule).
  Prevents thin-history names from producing meaningless signals against
  artificially short baselines.

**The 11 rules:**
1. `[x]` Volume z-score vs name's 60d mean/std. Threshold: z >= 2.0
2. `[x]` Range expansion vs 20d ATR. Threshold: >= 1.5x
3. `[x]` Gap z-score vs name's 60d overnight gap distribution
4. `[x]` IV rank delta over 5 trading days, >= 15 points
5. `[ ]` Put/call volume ratio anomaly — needs verification (Alpaca options)
6. `[ ]` Options volume / prior-day OI — needs verification
7. `[x]` Correlation breakdown vs SPY (20d vs 60d, drop >= 0.3)
8. `[x]` Earnings proximity (NEW 2026-04-13) — fires standalone for symbols
   1-14 days from earnings (formula: `1.0 - (days-1)/14`); ALSO amplifies
   the final composite score by 1.5x when fired. Both effects independent
   and tunable. Reads from rebuilt earnings_calendar (universe-scale coverage).
9. `[ ]` Short interest delta — needs FINRA data ingestion
10. `[x]` News density z-score vs 30d baseline (NEW architecture 2026-04-13).
    Currently structurally dormant: `min_news_days=14` guard means rule
    won't fire until symbol_news_headlines has 14 days of accumulated history
    per symbol. Decision pending on whether to lower threshold for warm-up.
11. `[ ]` Social mention velocity — needs 1.3.6

**Ship phasing:** 7/11 rules live. Rule 5/6 wire next as Alpaca options data
verification completes. Rule 9 blocked on FINRA ingestion. Rule 11 blocked on
1.3.6.

**Deployed:** `agents/tier2a_prefilter.py`, `services/signal_compute.py`,
`config/tier2a.yaml`, `scripts/run_tier2a.py`. Cron: 10 AM, 12 PM, 2 PM ET.
Verified end-to-end 2026-04-13: 197 of 4,241 Tier 1 passes promoted, 1,042
liquidity-rejected, 30 near-misses, 0 errors, 113.5s runtime.

**Known data starvation as of 2026-04-13:**
- Earnings amplification: RESOLVED — earnings_calendar rebuild restored
  universe-scale coverage. Amplification now firing on the meaningful subset
  of names with upcoming earnings rather than the pre-rebuild ~1 name.
- News_density: structural warm-up. Rule cannot meaningfully fire for ~14 days
  due to min_news_days guard. Decision pending.

### Batch 1.4.0b-b — Tier 2b LLM Reasoning Layer `[ ]` NEXT BUILD

Cheap LLM (Llama 3.3 on Together AI, ~$0.20/M tokens) reads top ~200-400 from
Tier 2a (the actual passes, since Tier 2a's gate is now selective) with
signals + earnings amplification flags + news state + playbook context +
recent agent_messages. For each name, produces a short reasoning string for
both passes and rejects.

Cost envelope: ~$10/month. Pulls Phase 4 cheap-model thesis forward.

Logging: every reasoning string logged to name_observations alongside
mechanical signals. Becomes the input for Lead Agent rewiring (1.4.2.9).

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
  closed trades exist. Output: updated weights for the 11 rules. Critical
  data prerequisite: every name's `analysis` JSON must persist all per-signal
  raw values (not just the composite). Verified 2026-04-13 — current schema
  satisfies this requirement.
- **1.4.2.3 Research Analyst (narrative-only)** — daily post-market
  reflection. Restricted to narrative reasoning patterns, not predictive
  rules. Writes to skill_documents and agent_messages. Reads across
  name_observations + macro_news_events + symbol_news_headlines for
  full-context pattern recognition.
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
- **1.4.2.9 Lead Agent rewiring** — currently reads from hardcoded list, not
  from Tier 2 promotions. Wire to read top names from `name_observations
  WHERE tier=2 AND was_considered=true` ordered by composite_score. This
  closes the funnel end-to-end. Should ship immediately after 1.4.0b-b
  (Tier 2b) so Lead Agent receives names with narrative reasoning attached.
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

### Batch 1.6 — Cross-Database Context Retrieval Service `[ ]` (NEW 2026-04-13)

Unified `services/context_retrieval.py` with `context_for(date, symbol=None,
filters=None)` method that joins across `name_observations`,
`macro_news_events`, `symbol_news_headlines`, `cycle_snapshots`,
`agent_actions`, and trades. Agents need to reason fluidly across macro
context, symbol news, observation history, and trade outcomes without
learning separate query patterns for each table.

Deferred from 2026-04-13 ship — schemas were designed to be retrieval-friendly
(consistent date and symbol column naming) but the service itself was held
back to avoid speculative design without a consumer. Build when first agent
(probably Research Analyst, 1.4.2.3) needs cross-table context queries.

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
- **Consolidate `HistoricalBar` time-series reads into a single helper** —
  currently duplicated across `breadth_analyst.py` and `tier2a_prefilter.py`
  with identical dedup logic. Next consumer that gets added will either
  copy it again or get it wrong. Preventative refactor.
- **Credential rotation** — `POSTGRES_PASSWORD=multiagent2026!` and
  `FINNHUB_API_KEY` were both pasted into chat during 2026-04-11 and
  2026-04-13 sessions. Rotate both.
- **SQLAlchemy DBAPI error from Tier 2a dry-run logs** (2026-04-11) —
  caught silently with 0 errors in final stats. Likely transient but worth
  pulling stack trace and confirming.
- **News density warm-up strategy** (NEW 2026-04-13) — currently rule won't
  fire for ~14 days due to min_news_days guard. Decision: lower threshold
  to ~5 (signal sooner, noisier baseline) vs wait the 14 days (rigorous,
  longer dormancy). Tabled per session decision.
- **Earnings proximity weight tuning** — initial weight set to match
  news_density (~0.15) but actual contribution should be observed and
  retuned once labeled outcomes exist. The architectural intent is for
  earnings amplification to be a meaningful driver of the gate's
  composition.
- **Coverage floor sanity checks across all ingestion services** — earnings
  rebuild added one. News service should add one. Future ingestion services
  (FINRA short interest, social sentiment) must include one from day one.

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

- **O1**: Eight tables exist plus two new news tables (macro_news_events,
  symbol_news_headlines); consumers don't yet exist beyond Tier 2a writes.
  Substrate is real, flywheel is not yet active.
- **O2**: Lead Agent reads from hardcoded list, not from Tier 2 promotions.
  1.4.2.9 is the wiring that connects the funnel end-to-end. Should ship
  immediately after 1.4.0b-b (Tier 2b).
- **O3**: Playbook citation on April 6 was recency, not learning. Real
  learning requires 1.4.2.4 + 1.4.2.9.
- **O4**: RESOLVED 2026-04-11 — Breadth Analyst sanity check confirmed
  source-scoping fix took (AAPL three distinct values across windows).
- **O5**: RESOLVED 2026-04-11 — 9 commits pushed. Tier 2a + Batch 1.3 feeds
  deployed.
- **O6**: RESOLVED 2026-04-13 — Volume window source-hardcode bug
  (`tier2a_prefilter._get_bars` and `breadth_analyst._compute_metrics_for_symbol`
  both filtered to `source='alpaca'` despite Alpaca only carrying 2-bar
  freshness top-up). Fixed via all-sources read with bar_date dedup and
  source priority `stooq > yfinance > alpaca`.
- **O7** (NEW 2026-04-13): RESOLVED — Earnings calendar coverage rebuilt
  from ~30 names (watchlist-scale) to ~1,500-2,500 names (universe-scale)
  via Finnhub `/calendar/earnings` bulk endpoint. Daily refresh with
  coverage floor sanity check.
- **O8** (NEW 2026-04-13): News_density rule structurally dormant for ~14
  days post-deployment due to min_news_days warm-up guard. This is correct
  behavior but means news_density does not contribute to gate composition
  during the warm-up period. Decision tabled on whether to lower threshold.
- **O9** (NEW 2026-04-13): The first integrated Tier 2a run after Phase
  1+2 deployment showed top-15 promotions dominated by `insufficient_news_history`
  state — reflecting both the news warm-up and the (now-fixed) earnings
  coverage gap. Re-eyeball after one trading day with the fixed earnings
  calendar to assess whether earnings amplification meaningfully shifts
  the score landscape.

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
5. **Q5** (NEW 2026-04-13): With earnings amplification now firing at
   universe scale, does it dilute the IV rank delta dominance pattern
   observed during 2026-04-12 verification? If not, IV rank delta threshold
   may need retuning regardless of additional rules being added.

---

## CHANGELOG

### 2026-04-13 — Phase 1+2 ship: liquidity floor + history guard + earnings proximity + news architecture rebuild + earnings calendar bulk ingestion

**Shipped and pushed:**
- Liquidity floor in Tier 2a (`min_daily_dollar_volume=$10M`, configurable)
- Min-history guard on volume_zscore, range_expansion, gap_zscore,
  correlation_breakdown (default 60 distinct trading days, configurable per-rule)
- Earnings proximity rule wired (rule #8 in Tier 2a) — fires standalone for
  1-14 day window AND amplifies composite by 1.5x when fired
- News architecture split: `macro_news_events` (90-day retention, topic-tagged)
  + `symbol_news_headlines` (35-day retention, on-demand fetched for top 200
  Tier 2a candidates per cycle)
- Four distinguishable news states in `analysis` JSON: below_threshold, no_news,
  not_evaluated, fetch_failed
- Earnings calendar rebuilt for universe-scale coverage via Finnhub
  `/calendar/earnings` bulk endpoint. Daily refresh covering 30-day forward
  window. Coverage sanity check fires WARNING below 200 events. Coverage
  jumped from ~30 names to ~1,500-2,500 (during earnings season).
- Old `news_headlines` table renamed to `news_headlines_legacy`.

**Verification (Phase 1+2):**
- Tier 1 sweep: 4,241 passed of 6,340, 0 errors, 655s
- Tier 2a sweep: 197 promoted, 1,042 liquidity-rejected, 17 insufficient-history,
  30 near-misses, 0 errors, 113.5s
- News tables populated correctly: 100 macro events, 350 symbol headlines
  for 53 distinct names
- All four news states representable in JSON
- Earnings amplification arithmetic correct (verified on 1 name pre-rebuild;
  expected to fire on ~10-30 of 197 promotions post-rebuild)

**Architectural decisions locked in:**
- News split: macro = environmental context for future agents (logged, no
  scoring impact), symbol-specific = per-name change-detection (feeds
  news_density rule)
- Macro news topic-tagged at ingestion via static keyword map (monetary_policy,
  inflation_data, geopolitical, macro_data, market_action, general)
- On-demand news fetch for top 200 Tier 2a candidates accepts the trade-off
  that news-only stories on names not firing mechanical signals are invisible
  to the gate (Option A — news as confirming signal, not screening signal)
- Cross-database retrieval service (1.6) deferred — schemas designed
  retrieval-friendly but no consumer yet
- Working rule #6 added: sanity-check inputs, not just outputs
- Working rule #7 added: coverage floor on every ingestion service

**Lessons captured:**
- "Coverage" is a first-class architectural concern — services designed for
  watchlist-scale don't gracefully scale to universe-scale; explicit coverage
  floors with WARNING-level alerts catch this on day one
- The recon-first rule earned its keep again — earnings calendar rebuild
  surfaced the line-8 documentation comment that immediately revealed the
  watchlist-scale design intent without any code archaeology
- Dry-run mode skipping database writes is a verification trap — verification
  queries against `--dry-run` output return empty and look like failures.
  Run non-dry-run before checking persisted state.
- News-density warm-up is real and structural — guards that prevent firing
  on insufficient history do their job correctly but leave rules dormant
  until baselines accumulate. Worth designing for warm-up periods explicitly
  in future rule additions.

### 2026-04-11 — Architectural rewrite + Tier 2a + data feeds shipped

**Shipped and pushed:**
- 1.4.0b-a Tier 2a Mechanical Pre-filter (6/11 rules): signal_compute.py,
  tier2a_prefilter.py, tier2a.yaml, run_tier2a.py, cron at 10/12/14 ET
- 1.3.1 FRED macro (fred_service.py)
- 1.3.2 EDGAR filings (edgar_service.py)
- 1.3.3 Technical indicators (technical_indicators.py, pure Python)
- Bootstrap wiring + preflight updates
- Volume window source-hardcode bug fix (commit 25d65e1) — `breadth_analyst`
  and `tier2a_prefilter` both filtered to `source='alpaca'`, but Alpaca only
  has 2-bar freshness top-up. Fix: read all sources, dedup by bar_date with
  priority `stooq > yfinance > alpaca`.

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

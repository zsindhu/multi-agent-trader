# Premium Trader — Backlog

Last updated: 2026-04-06

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

Premium Trader has four conceptual layers. The current system has the
bottom two well-built. Phase 1 builds the middle two.

```
┌─────────────────────────────────────────────────────┐
│  Layer 4 — Research Interface                       │
│  Plain-HTML inspector at /research                  │
│  CLI tools for ad-hoc queries                       │
│  Eventually: real research dashboard                │
├─────────────────────────────────────────────────────┤
│  Layer 3 — Intelligence Agents                      │
│  Lead Agent (decisions + actions)         ← exists  │
│  Breadth Analyst (universe screening)     ← new     │
│  Fundamentals Analyst (10-K/10-Q reading) ← new     │
│  Research Analyst (strategy iteration)    ← new     │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                      │
│  PostgreSQL + JSONB + pgvector            ← new     │
│  Six core tables (see Phase 1)                      │
│  Skill documents, embeddings, msg bus               │
├─────────────────────────────────────────────────────┤
│  Layer 1 — Data Foundation                          │
│  Alpaca (market data, options, news)      ← exists  │
│  Yahoo (spot VIX)                         ← exists  │
│  FRED (macro indicators)                  ← new     │
│  EDGAR (SEC filings)                      ← new     │
│  TA-Lib (technical indicators)            ← new     │
│  Tiered scanning (4,000 name universe)    ← new     │
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

## PHASE 1 — Data Foundation

**Goal:** Build the substrate that all future research and intelligence
builds on. Capture every signal the system produces, expand the universe
to test the breadth thesis, wire up high-quality free data feeds, and
expose the data via a plain HTML inspector.

**Estimated effort:** 5 batches, ~2-3 weeks of work
**Estimated cost increase:** $80-120/month operational (mostly Anthropic API)

### Batch 1.1 — Research data layer schema

**Goal:** The six PostgreSQL tables + migrations + basic write paths from
existing code into the new tables. This is the foundation everything else
builds on.

**Tasks:**

- [ ] **1.1.1** Install pgvector extension on the droplet's PostgreSQL
- [ ] **1.1.2** Create `cycle_snapshots` table — one row per LLM cycle
  with structured columns (timestamp, regime, vix, breadth, etc.) plus a
  JSONB `full_context` column for everything else
- [ ] **1.1.3** Create `name_observations` table — one row per name per
  cycle for every name the system looked at, with tier (1/2/3/4),
  was_considered, was_traded, rejection_reason, plus JSONB for the full
  per-name analysis
- [ ] **1.1.4** Create `agent_messages` table — the inter-agent
  communication bus. Any agent can write a message, any agent can read.
  Loose coupling through shared database.
- [ ] **1.1.5** Create `skill_documents` table — versioned markdown
  documents per agent. Each agent maintains its own evolving description
  of its strategy and capabilities. Old versions preserved.
- [ ] **1.1.6** Create `reasoning_embeddings` table — vector embeddings
  for every reasoning trace, playbook entry, and skill document version.
  Powers semantic search via pgvector.
- [ ] **1.1.7** Create `agent_capabilities` table — registry of what
  each agent can do. Other agents query this to see what's available.
- [ ] **1.1.8** Wire the existing Lead Agent's `_store_cycle_reasoning`
  to ALSO write a row to `cycle_snapshots` with the full context as JSONB
- [ ] **1.1.9** Add a helper function `embed_and_store(text, source_table,
  source_id)` that calls OpenAI embeddings API and writes to
  `reasoning_embeddings`. Include cost tracking.
- [ ] **1.1.10** Migration scripts and Alembic versions for all of the above

**Deliverable:** After this batch ships, every cycle the Lead Agent runs
writes a complete snapshot to the new tables. We can query "what was the
full context of the cycle on April 5 at 2pm" and get back everything.

**Cost impact:** $0/month direct. Embedding API is $0.01/month at this scale.

---

### Batch 1.2 — Universe expansion + tiered scanning

**Goal:** Replace the current 16-name fixed scanner with a 4,000-name
universe and a tiered scanning architecture. This is what actually tests
the breadth thesis.

**Tasks:**

- [ ] **1.2.1** Build the universe loader: pull all US-listed equities and
  ETFs from Alpaca that have listed options, filter to those with stock
  price > $5 and average daily volume > 100K shares. Target: 3,500-4,500
  names. Cache the result for 24 hours.
- [ ] **1.2.2** Build Tier 1 (Universe Sweep) — runs once per day before
  market open. Pulls daily bars + market cap + average volume + basic
  options availability for ALL universe names. Cheap because daily bars
  are one API call per name and cached for the day. Stores results in
  `name_observations` with tier=1.
- [ ] **1.2.3** Build Tier 2 (Active Universe) — runs every 2 hours during
  market hours. Filters Tier 1 results to names with "interesting
  characteristics": unusual volume, large price moves, IV rank changes,
  earnings approaching. Narrows ~4000 to ~200-400 names. Fetches options
  chains and computes IV ranks. Stores results with tier=2.
- [ ] **1.2.4** Build Tier 3 (Deep Analysis) — runs every 15 minutes
  during market hours. From Tier 2 results, picks ~30-60 names that are
  actually candidates for trading. Runs full analysis (options chain
  scoring, liquidity, support/resistance, news sentiment). This is what
  the LLM reasons over. Stores results with tier=3.
- [ ] **1.2.5** Build Tier 4 (Position Management) — runs every 15
  minutes, only on currently-open positions. Refreshes position state
  near-real-time. Stores results with tier=4.
- [ ] **1.2.6** Add async batching where appropriate — fetch multiple
  symbols in parallel using `asyncio.gather` to stay under Alpaca rate
  limits while moving fast through the universe.
- [ ] **1.2.7** Add caching with appropriate TTLs — daily bars cached for
  24h, options chains cached for 1h, quotes cached for 1 minute.
- [ ] **1.2.8** Update the existing Scanner agent to use the new tier
  system. Lead Agent reads from Tier 3 results. Existing scanner
  functionality preserved but now operates on the broader universe.

**Deliverable:** After this batch ships, the system is monitoring 4,000
names with appropriate depth at each tier. The data layer captures every
name the system looked at, whether it was traded or not.

**Cost impact:** Marginal Alpaca API usage increase (still well within
free tier). LLM cost increase ~$20-40/month from richer Tier 3 context.

---

### Batch 1.3 — New data feeds

**Goal:** Wire up the additional data sources that make the LLM's reasoning
meaningfully richer than what Alpaca alone provides.

**Tasks:**

- [ ] **1.3.1** FRED integration — `services/fred_service.py` that fetches
  macro indicators (VIX, 10Y yield, 2Y yield, yield curve, HYG/LQD spread,
  unemployment, inflation expectations, Fed funds rate). Free, no API key
  needed for basic access. Cache for 6 hours. Expose as a tool the Lead
  Agent can call: `get_macro_indicators()`.
- [ ] **1.3.2** EDGAR integration — `services/edgar_service.py` that can
  fetch the most recent 10-K, 10-Q, or 8-K for any ticker symbol. Returns
  structured text. Free, no API key. Rate limited to 10 req/sec which is
  fine. Expose as a tool: `get_filing(symbol, filing_type)`.
- [ ] **1.3.3** Technical indicators — install TA-Lib in the Docker image,
  add `services/technical_indicators.py` that computes RSI, MACD, Bollinger
  Bands, ATR, multiple moving averages from price bars. No external data
  source needed — uses bars we already fetch. Add as fields in
  name_observations or expose as a tool.
- [ ] **1.3.4** Earnings calendar — Finnhub free tier provides earnings
  dates and estimates. Add `services/earnings_calendar.py` (if not already
  present) and a tool `get_earnings_upcoming(days_ahead)`.
- [ ] **1.3.5** News enrichment — Alpaca's built-in news feed is free and
  provides news with timestamps and ticker tags. Wire it more deeply into
  the Lead Agent's tools so news becomes a first-class input to decisions
  rather than an afterthought. Add a tool `get_news_for_symbol(symbol,
  hours_back)`.

**Deliverable:** After this batch ships, the Lead Agent has access to
macro context (FRED), fundamentals (EDGAR), technical indicators (TA-Lib),
earnings dates (Finnhub), and news (Alpaca enriched). Every cycle's
reasoning can pull from any of these sources via tool calls.

**Cost impact:** $0/month — all feeds are free.

---

### Batch 1.4 — New intelligence agents

**Goal:** Add the three new agents that operate on the data layer and the
new feeds. These are the agents that make the system feel like a research
desk instead of just a trader.

**Tasks:**

- [ ] **1.4.1** Build the Breadth Analyst agent (`agents/breadth_analyst.py`).
  Runs once per hour during market hours. Job: scan the Tier 1+2 universe
  for names that look "interesting" by criteria the LLM defines. Surfaces
  candidates to the Lead Agent via the `agent_messages` table. Maintains
  its own skill document describing its screening methodology. Cost: ~$5
  per day in LLM API.
- [ ] **1.4.2** Build the Fundamentals Analyst agent
  (`agents/fundamentals_analyst.py`). Runs on demand when triggered by
  upcoming earnings or by Lead Agent request. Job: read the most recent
  10-K/10-Q for a name via EDGAR, extract material information, benchmark
  against industry peers, identify forward guidance, write findings to
  `agent_messages`. Maintains its own skill document. Cost: ~$1.20 per day.
- [ ] **1.4.3** Build the Research Analyst agent
  (`agents/research_analyst.py`). Runs once per day after market close. Job:
  read the day's `cycle_snapshots`, identify patterns ("CSPs in risk-off
  underperformed CSPs in neutral by X%"), update its own skill document
  with findings, write summary to `agent_messages` for Lead Agent to read
  next morning. This is the "system that reads its own trade data" you
  asked about. Cost: ~$0.30 per day.
- [ ] **1.4.4** Update the Lead Agent's system prompt and tool list to:
  (a) read `agent_messages` at the start of every cycle, (b) read its own
  current skill document, (c) write to its skill document when it
  discovers something material. The skill document becomes the Lead
  Agent's evolving description of its own strategy.
- [ ] **1.4.5** Add prompt caching for the parts of context that don't
  change between cycles (system prompt, current skill documents, recent
  playbook). This cuts Anthropic API costs by 50-90% on cached content.

**Deliverable:** After this batch ships, the system has four agents
collaborating through the message bus. Each maintains its own skill
document. The Lead Agent is no longer making decisions in isolation — it's
reading the morning briefing from the Research Analyst, the latest screen
from the Breadth Analyst, and the latest deep dives from the Fundamentals
Analyst.

**Cost impact:** ~$80-120/month additional Anthropic API spend. Total
operating cost lands at the projected $100-150/month.

---

### Batch 1.5 — Research inspector (plain HTML at /research)

**Goal:** Build the brutalist Win95-style research interface so we can
actually see what the data layer is producing without writing SQL by hand.

**Tasks:**

- [ ] **1.5.1** Create PostgreSQL views that pre-aggregate the most useful
  data: `today_cycles_with_summary`, `tier3_active_names`,
  `latest_skill_documents`, `agent_message_feed`, `name_observation_history`.
  These are SQL queries saved as named views — the eventual real dashboard
  will read from these too.
- [ ] **1.5.2** Build CLI inspection tool (`scripts/inspect.py`) with
  subcommands: `cycles` (last N cycles), `names` (active tier 3),
  `messages` (recent agent messages), `skills` (current skill documents),
  `playbook` (recent playbook entries), `cost` (today's API spend).
  Output to terminal as pretty-formatted tables.
- [ ] **1.5.3** Build `make inspect` shortcut that runs the most useful
  inspection commands in sequence and dumps everything to terminal. One
  command, full system state.
- [ ] **1.5.4** Add `/research` route to FastAPI. Plain HTML, no
  JavaScript, no styling beyond minimal readable defaults. Renders the
  data from the SQL views as HTML tables. Sections: latest cycle,
  active universe, agent messages, skill documents, playbook. One page,
  scrollable, dense.
- [ ] **1.5.5** Add `/research/cycle/<id>` for drilling into a specific
  cycle's full context (including the JSONB blob rendered as readable
  text).
- [ ] **1.5.6** Add `/research/search?q=...` endpoint that uses pgvector
  semantic search across cycle reasonings, playbook entries, and skill
  documents. Plain text input, plain text results. This is the killer
  feature for research — ask "what did the system think about gold
  miners in March" in plain English and get back the relevant cycles.

**Deliverable:** After this batch ships, you have a URL to look at
(`/research`) that shows everything the data layer has captured, plus
a CLI tool for terminal-based inspection, plus semantic search across
all the system's accumulated knowledge.

**Cost impact:** $0/month. Pure read-only views over existing data.

---

## PHASE 2 — Real Dashboard (deferred)

**Goal:** Build the actual research-focused dashboard that becomes the
primary interface for studying the system. Designed around the research
workflow, not the operational workflow.

**Why deferred:** Don't design the UI until we know what data exists and
what research questions are most useful to answer. The plain-HTML
inspector from Batch 1.5 will reveal what we actually need.

**Estimated start:** 2-3 weeks after Phase 1 completes
**Batches not yet defined** — will be filled in based on what we learn
from operating Phase 1 for a few weeks.

---

## PHASE 3 — Architecture Transferability (later)

**Goal:** Refactor the codebase so the broker abstraction, market
abstraction, and strategy abstraction are clean enough that we can swap
in Bitcoin perpetuals or prediction markets without rewriting the core.

**Why deferred:** Premature. We don't yet know if the architecture works
in even one market. Prove it in options first, then think about transfer.

**Estimated start:** 1-2 months after Phase 1 completes (assuming Phase 1
proves out)

---

## PARKING LOT

Things that came up but aren't part of the current plan. Don't lose them,
but don't work on them either until they get formally pulled into a phase.

### UI fixes (deferred until Phase 2 redesign)
- Active Positions card unreadable / "Unassigned" badges everywhere
- Risk Monitor shows arbitrary numbers, computation broken
- Time displayed in UTC instead of Eastern
- System Assessment block shows JSON action list as giant code block
- Last Cycle Actions should move from Dashboard to Trade Desk
- Sector Rotation card empty (data never wired up)
- Breadth shows stuck at 50% — possibly cache issue, possibly real
- Equity chart Y-axis squashes data range

### Bugs (small, can be addressed within phase batches as discovered)
- Two regime classifiers (`core/strategy.py` and `services/market_regime.py`)
  still produce parallel outputs even after VIX consolidation
- Frontend `buildEquityData` is dead code now that the API serves
  `equity-history`
- 21 legacy submitted trades in DB will never reconcile (already marked
  as `unknown` via cleanup script)

### Future intelligence agents
- Strategy Backtest agent — replays historical decisions against actual
  outcomes to validate the playbook
- Risk Manager agent — separate from the Lead Agent, evaluates portfolio
  risk in real time and can override with risk veto
- Cross-Market Researcher — once Phase 3 ships, an agent that monitors
  multiple markets simultaneously and identifies regime correlations

### Ops improvements
- GitHub Actions Node.js 20 deprecation warnings (need to bump action
  versions before June 2026)
- Worker pause/resume button on dashboard (plumbing exists, needs UI)
- Mobile push notifications for risk events (Discord webhook exists,
  needs to be configured and tested)
- Daily Anthropic spend cap set to $5/day in console (safety net for
  runaway token usage)

---

## OBSERVATIONS — read but do not engineer against

Things to look at during observation blocks. Do NOT fix, just understand.

### O1 — The learning flywheel is showing first signs of life
On April 6, the LLM cited its own playbook entry in a trade decision:
*"4 DTE Profit Capture Rule: 89.6% profit with 4 DTE in elevated VIX
environment. Playbook rule confidence 0.9."* This is the first evidence
of institutional memory compounding. Worth pulling all playbook entries
and reading them end-to-end at some point this week.

### O2 — System concentrated heavily in GDX
8 of the original 8 positions were in gold miners or biotech, all bearish.
Why did the scanner repeatedly surface the same names? Is this a feature
(high IV in those names is real) or a bug (scanner bias)? Worth
understanding before scaling capital. The Phase 1.2 universe expansion
will probably resolve this naturally, but worth confirming.

### O3 — Cost discipline is real
Today's full LLM cycle (15970 in / 3673 out tokens, 9 actions) cost $0.10.
The cost controls from earlier batches are working. Phase 1 will increase
this but the architecture supports prompt caching to keep it bounded.

---

## STRATEGIC OPEN QUESTIONS

These don't have answers yet. They're the questions we're trying to answer
by running the experiment.

1. **Does the playbook actually compound knowledge, or does it accumulate
   noise?** We'll know after 4-6 weeks of operation with the new data
   layer capturing reasoning evolution.

2. **Does the LLM's regime classification correlate with forward returns?**
   Need ~3 months of data in `cycle_snapshots` to test this rigorously.

3. **Are CSPs the right primary strategy, or should we be running iron
   condors / wheels / 0DTE / something else?** Don't decide until we have
   real performance data on the primary strategy.

4. **What's the right balance between LLM autonomy and rule-based guardrails?**
   Currently the LLM has full position management authority. Should some
   things become hard rules (max position size, hard stop losses) or stay
   under LLM judgment?

5. **At what point do we start trading real money?** Set explicit criteria.
   E.g.: "Trade real after 3 months of paper, after the system has shown
   consistent positive returns in at least 2 different VIX regimes, and
   after a manual review of all major decision categories."

6. **What's the kill criteria for the project?** When do we say "the
   thesis is wrong, time to rethink"? Without one, we'll keep tinkering
   forever even if it's not working. Suggested: 6 months of operation
   with no consistent edge over the passive benchmark = thesis disconfirmed,
   time to rethink the architecture.

---

## CHANGELOG

- 2026-04-06: Backlog rewritten from scratch under research thesis framing.
  Old engineering-task backlog moved to git history. New structure
  organized around phases and the data layer foundation.

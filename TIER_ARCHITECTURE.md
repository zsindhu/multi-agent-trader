# Tier Architecture Roadmap (Updated 2026-04-09 evening)

**Status:** Working hypothesis, refined twice during the April 9 session.

**What changed in the second revision:** The original roadmap assumed `historical_bars` would be populated via an Alpaca-based backfill. Two architectural questions during the evening session pulled the design in a better direction:

1. *"Can the LLM just reference historical prices instead of us storing them?"* — answered no (LLMs know historical prices narratively, not precisely), but the question forced a re-examination of whether we needed deep history at all.

2. *"Can't we just download historical data and store it in a database?"* — answered yes, and this is the architectural unlock. Historical daily bars are a commodity that exists in many free public forms. The Alpaca rate limit problem we've been fighting was caused by treating bulk historical data as a streaming-API problem when it should have been treated as a file-download problem.

**The current working architecture for Tier 1 historical data:**

- One-time bulk load of daily OHLCV bars from **three free public sources** (Stooq, yfinance, and the Boris Marjanovic Kaggle dataset) into the `historical_bars` table via Postgres `COPY`. Each row is tagged with its source so we preserve provenance. This happens once, takes probably 1-2 hours total across all three sources, and is done.
- `historical_bars` gets a new `source` column and the unique constraint changes from `(symbol, bar_date)` to `(symbol, bar_date, source)`. This allows the same `(symbol, bar_date)` to appear multiple times, once per source, so we can cross-validate and detect discrepancies later if needed.
- After the bulk load, Alpaca handles all daily incremental updates. The Breadth Analyst's `run_daily_sweep` fetches one new bar per symbol from Alpaca each morning and appends to `historical_bars` (tagged with `source='alpaca'`). This is the only ongoing API dependency.
- For symbols not present in the bulk files (new IPOs, edge cases), the Breadth Analyst falls back to a targeted Alpaca fetch. The existing mini-backfill code path in `run_daily_sweep` handles this correctly.
- Tier 2 and Tier 3 agents query `historical_bars` on demand when they need historical context on specific names. The LLM never processes the full table — only thin per-name slices as part of per-symbol reasoning.
- `services/breadth_checkpoint.py` and the `backfill_history()` method on the Breadth Analyst become dead code under this design. They stay in place until step 6's cleanup pass.

**Why multi-source instead of single-source:** The `historical_bars` table is a reference repository that future agents will query on demand, not a streaming data pipeline. Having multiple sources provides better coverage (each source fills gaps the others have), supports future cross-validation research ("where do Stooq and yfinance disagree on volume?"), and reduces dependency risk (if yfinance breaks, Stooq and Kaggle still provide coverage). The LLM-based discrepancy resolution we considered is deferred — for now, the loader just stores all source values and lets consumers decide how to handle them.

This is cleaner than every previous version of the design. Less code fighting rate limits, more coverage, better optionality for the future.

---

## Relationship to BACKLOG.md

This document is a supplement, not a replacement. The backlog defines the phased build plan. This document defines the target structure for the universe scanning substrate and the execution sequence for getting there.

## Why this document exists

By April 9, 2026, the project had accumulated two parallel pipelines for universe scanning. The audit during the April 9 session revealed that the universe loader (`services/universe_loader.py` + `services/tier_writer.py`) was shipped as loose services rather than as an agent, hit Alpaca rate limits, and produced output nothing read. The roadmap formalizes the decision to build the Breadth Analyst as a real agent and restructure the scanning substrate around the three-layer decision model.

The evening session refined the design by recognizing that the historical data problem was a category error: bulk historical bars are a file-download problem, not a streaming-API problem.

## Guiding principles

**1. Scanning work belongs to agents, not loose services.**

**2. Every filtering decision is documented.** Silent filtering is forbidden.

**3. Every agent action is logged** to `agent_actions`.

**4. Historical data is loaded from bulk sources where possible, fetched incrementally where required.** (Updated from the previous "cached once and updated incrementally" — the new framing makes the source distinction explicit.)

**5. Schema supports queryability from day one.**

**6. The target state is additive, not destructive, for the live trading loop.**

## The three-layer decision model

Layer 1 (Eligibility / Breadth Analyst), Layer 2 (Signal / Scanner), Layer 3 (Judgment / Scanner final pass), Layer 4 (Action / Lead Agent).

## Target structure

### Agents

Eight files. The new file `agents/breadth_analyst.py` is shipped (Step 2 complete). Its `run_daily_sweep` method is the live tier 1 entry point. Its `backfill_history` method is now dead code that will be removed in step 7.

### Services

Two changes from the morning version:

**Stays in place but becomes dead code** (deleted in step 7):
- `services/breadth_checkpoint.py` — designed for Alpaca backfill checkpointing, not needed for bulk loads

**Still scheduled for deletion in step 7:**
- `services/universe_loader.py`, `services/universe_filters.py`, `services/tier_writer.py`, `scripts/run_universe_sweep.py`

**Still scheduled for shrinking in step 7:**
- `services/research_data.py`

### New files for the bulk historical data loader

To be created in the revised step 3:

- `scripts/bulk_load_historical_bars.py` — one-time loader. Downloads bulk archive from chosen source, normalizes to our schema, COPYs into `historical_bars`. Takes the source name as an argument so we can re-run with a different source if needed. Idempotent — re-running on already-loaded data should be a no-op.
- `services/bulk_data_sources/` — directory with one adapter per supported source. Initially just one (whichever we pick), but structured so we can add others later.

### Models and schema

All three migrations from step 1 are live on the droplet.

The `historical_bars` table is empty as of end-of-session April 9. It will be populated by the bulk loader in the revised step 3.

The `name_observations` table has its tier columns ready. It has one row from April 7 (the original orphaned universe loader test) plus whatever rows the Breadth Analyst writes once it runs.

The `agent_actions` table is empty. It will be populated by Breadth Analyst actions starting with the first sweep.

### Scheduling

The agents container runs `main.py` with APScheduler. The cron change (replacing `_run_universe_sweep` with the Breadth Analyst's daily sweep) is the original step 3a, which doesn't need to change.

The dual-scheduler concern from the morning version was a misread. The agents container and the app container are intentionally separate processes with intentionally separate responsibilities. No consolidation needed.

## Execution sequence (revised)

### Step 1 — Schema foundation ✅ SHIPPED

Three migrations applied to droplet at alembic revision `p0q1r2s3t4u5`. Schema is live.

### Step 2 — Breadth Analyst scaffold ✅ SHIPPED

Agent code committed and deployed. Smoke test passed on droplet. The `backfill_history()` method exists but will not be called — it's now dead code pending step 7 cleanup.

### Step 3 — Multi-source bulk load and wire daily sweep (revised)

This is the next step to execute. It splits into four phases:

**Phase 3.1 — Schema migration for source provenance.** Add a `source` column to `historical_bars`. Change the unique constraint from `(symbol, bar_date)` to `(symbol, bar_date, source)`. Small Claude Code prompt, single migration, no agent code changes.

**Phase 3.2 — Build the source adapters and bulk loader.** Create `services/bulk_data_sources/` directory with three adapter modules: `stooq_adapter.py`, `yfinance_adapter.py`, `kaggle_adapter.py`. Each adapter has the same interface: given a list of symbols, return bar records in a standard format. Then create `scripts/bulk_load_historical_bars.py` that orchestrates the adapters — runs each in turn, normalizes results, COPYs into `historical_bars` with appropriate source tags. Idempotent so re-runs don't create duplicates.

**Phase 3.3 — Run the bulk load.** Execute the loader on the droplet. Verify `historical_bars` is populated correctly: row count should be in the 4-6M range (multiple sources contributing for each symbol/date pair), distinct symbols should be in the 6,000+ range, date range should span ~252 days, no constraint violations.

**Phase 3.4 — Wire the daily sweep into the scheduler.** Small change to `main.py` to replace the `_run_universe_sweep` cron with a `_run_breadth_analyst_sweep` cron. After this lands, the daily sweep fires automatically each morning at 8 AM ET and appends `source='alpaca'` rows to `historical_bars`.

**Shipped when:** Multi-source bulk load completed, all three sources contributed data, daily sweep runs successfully on demand, scheduler is updated, the next scheduled run fires correctly.

### Step 4 — Scanner instrumentation pass

Refactor the scanner's filtering passes to write decision records to `name_observations` at tiers 2 and 3. Capture near-misses. Log scanner actions to `agent_actions`. Biggest change to existing working code in the whole roadmap.

### Step 5 — Lead Agent tier 4 writes

Augment Lead Agent cycle to write tier 4 observations for every position considered.

### Step 6 — Cleanup (renumbered from Step 7)

Delete dead code: `services/universe_loader.py`, `services/universe_filters.py`, `services/tier_writer.py`, `scripts/run_universe_sweep.py`, `services/breadth_checkpoint.py`, the `backfill_history()` method on the Breadth Analyst. Shrink `services/research_data.py` to only the methods actually called. Final audit.

(The original Step 6, scheduler consolidation, was removed because it was based on a misread of the architecture.)

## Open questions

**1. Initial source selection — DECIDED.** Stooq, yfinance, and Boris Marjanovic Kaggle dataset for the initial multi-source bulk load. Mboum and Google Finance investigated and rejected — Mboum is a transactional API not a bulk source, Google Finance API is dead. Paid alternatives (Tiingo, EODHD, Mboum, Polygon) are deferred until we have a specific need that the free sources don't cover.

**2. What's the right cadence for the scanner's tier 2/3 instrumentation?** Currently the scanner runs every 30 minutes via the API container's background loop and twice daily via the main container's cron. The two scanners are running the same code in two processes — wasted work but not harmful. Worth revisiting in step 4.

**3. When do we start populating `agent_messages`, `skill_documents`, `agent_capabilities` with real data?** These tables exist from Batch 1.1 but have no consumers. They'll gain consumers in Batch 1.4 when the Research Analyst is built. In the meantime, the Breadth Analyst could optionally post a sweep-complete message to `agent_messages` as a dry run of the mechanism. Worth deciding before the bulk loader work begins.

**4. How do we handle bulk source updates?** The bulk load is a one-time operation, but if we ever want to refresh the historical depth (add another year, switch sources, validate against a second source), the bulk loader needs to be re-runnable safely. The current design uses idempotent COPYs against a unique constraint, which handles this correctly. Worth confirming in Phase 3.2.

**5. Does Tier 2 need its own historical data layer or does it read from `historical_bars` directly?** The morning version of the roadmap assumed Tier 2 would maintain its own caches. The simpler answer might be that Tier 2 reads from `historical_bars` for any name-level historical lookup and only fetches from Alpaca for things `historical_bars` doesn't cover (intraday, options chains). Defer this to step 4.

## Architectural lessons from the April 9 session

These are observations that shape future decisions, written down so they're not lost.

**Bulk historical data is a commodity, not an API streaming problem.** Daily OHLCV for the US equity universe is freely available in many forms. Treating it as something we have to fetch through a transactional API was a category error that cost the previous session 12 hours of failed work. Any time we're tempted to fight a rate limit on bulk historical data, the right move is probably to find a file source instead.

**`name_observations` is the irreplaceable research substrate, not `historical_bars`.** Raw price data can be re-fetched from many sources at any time. The system's own decisions about names — what it considered, what it rejected, what it almost picked — only exist if we capture them as they happen. This is what the breadth thesis actually depends on. The historical bars are infrastructure; the observation records are the asset.

**The Breadth Analyst, the Scanner, and the Lead Agent are three different agents owning three different decision layers, not one pipeline with multiple stages.** The instinct to consolidate them into one agent (which I floated and then walked back during the conversation) was wrong. They're correctly separated by cadence, by what data they read, by what filters they apply, and by how they relate to the LLM. Future refactors should preserve this separation.

**Slow down before generating fixes.** This is the discipline the previous session's handoff demanded and the discipline that worked when I followed it tonight. Three times during the April 9 session, the operator's question pulled me out of a frame I had committed to too quickly. The pattern that worked was: pause, name the assumption, check whether the assumption was load-bearing, redesign if necessary. The pattern that didn't work was: generate confident output and hope it lands.

## Changelog

- **2026-04-09 (morning)** — Initial version. Written after the audit session that revealed the universe loader was shipped as loose services and that its output was consumed by nothing.
- **2026-04-09 (evening, first revision)** — Revised after architectural pivots during step 3 planning. Historical data architecture changed from "Alpaca rate-limited backfill" to "bulk file load from free public source plus Alpaca-only incremental updates." Step 6 (scheduler consolidation) removed as based on a misread. Lessons section added.
- **2026-04-09 (evening, second revision)** — Refined to multi-source bulk load (Stooq + yfinance + Kaggle Boris Marjanovic dataset) with source provenance tracking instead of single-source. The `historical_bars` table reframed as a reference repository for on-demand queries by Tier 2/3 agents, not a streaming pipeline. Schema adjustment added to step 3 (new `source` column, updated unique constraint). Mboum and Google Finance investigated as potential additions; Mboum deferred as paid commercial API, Google Finance rejected as deprecated.

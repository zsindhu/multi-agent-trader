# Premium Trader — Multi-Agent Options Trading System

A research sandbox for answering one question: **can an agentic LLM-driven system generate repeatable alpha, and does the architecture transfer to other markets?**

Options is the first test market — rich structured data, clear entry/exit semantics, enough inefficiency that there might be alpha to capture. The system monitors ~4,500 optionable names across a tiered scanning funnel, reasons over macro context via a GLM-5.2-powered Lead Agent orchestrated across four strategy sleeves, and executes income strategies (Covered Calls, Cash Secured Puts, The Wheel) through Alpaca's brokerage API — with a data-integrity layer that keeps every decision auditable and every training label honest.

The core thesis about where alpha comes from: the LLM's edge isn't being smarter on any single trade. It's **scale and breadth** — monitoring 4,500 names instead of 5, processing every headline, making consistent decisions across the full universe, never getting tired or biased. The goal is to run a comprehensive research operation for the cost of a Netflix subscription (~$150/month) vs the $50-100K/month a real desk would burn.

The formal experiment is registered in [`EXPERIMENT_CHARTER.md`](EXPERIMENT_CHARTER.md) (MSE-2026-01, 180 days from the 2026-04-20 funnel cutover), with all protocol amendments recorded.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 6 — Learning & Integrity                         │
│  Outcome Labeler (fill-based, freeze-at-decision) (live)│
│  Signal-Weight Learner (nightly, decisions not          │
│    contracts, 50-sample gate)                    (live) │
│  Broker Reconciliation (nightly DB↔Alpaca audit) (live) │
│  Judgment envelopes (structured verdicts beside         │
│    prose on every LLM decision)                  (live) │
├─────────────────────────────────────────────────────────┤
│  Layer 5 — Multi-Sleeve Orchestration                   │
│  SleeveOrchestrator (parallel + consolidation)   (live) │
│  4 sleeves: event-driven, vol-reversion,         (live) │
│    sector-rotation, yield-farming ($125K each)          │
│  SleeveRiskGate (hard limits)                    (live) │
│  Conflict resolution: deterministic → LLM judge →       │
│    load-balance, every verdict persisted         (live) │
├─────────────────────────────────────────────────────────┤
│  Layer 4 — Operator Interface                           │
│  React dashboard: Command Center / History /            │
│    Rules / Chat (Win95 style)                    (live) │
│  /research HTML inspector                        (live) │
│  RAG Chat Agent (DeepSeek-V3, SQL over the              │
│    research schema)                              (live) │
│  CLI: scripts/research_inspect.py                (live) │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — Intelligence Agents                          │
│  Lead Agent (GLM-5.2, per-sleeve decisions)      (live) │
│  Breadth Analyst (Tier 1 universe sweep)         (live) │
│  Tier 2a Pre-filter (11 rules, robust stats)     (live) │
│  Tier 2b LLM reasoning (Llama 3.3)               (live) │
│  Fundamentals Analyst (EDGAR + earnings)         (live) │
│  Research Analyst (daily reflection)             (live) │
│  Weekly + Monthly Summarizers (playbook digests) (live) │
│  Pre-market Briefing (daily assembly)            (live) │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer (append-only)            │
│  PostgreSQL + pgvector                           (live) │
│  name_observations — sweep_id append-only, every        │
│    pass/reject/near-miss with reasons            (live) │
│  trades — signal_snapshot + sleeve_id frozen at         │
│    decision time; broker fill_price/filled_at    (live) │
│  cycle_snapshots (+ envelopes), trade_outcomes,         │
│    agent_actions (incl. conflict verdicts)       (live) │
│  historical_bars (3M+ rows, 3 sources),                 │
│    playbook_entries, embeddings                  (live) │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — Data Foundation                              │
│  Alpaca (market data, options, execution)        (live) │
│  Together AI (GLM-5.2 lead + Llama 3.3 fleet)    (live) │
│  yfinance (options vol/OI, short interest)       (live) │
│  Finnhub (earnings bulk, news split)             (live) │
│  Stooq + yfinance (historical bulk)              (live) │
│  FRED (macro), EDGAR (SEC filings)               (live) │
│  StockTwits (social velocity)                    (live) │
│  OpenAI (embeddings only)                        (live) │
└─────────────────────────────────────────────────────────┘
```

## Model Stack

| Role | Model | Provider | Notes |
|------|-------|----------|-------|
| Lead Agent + 4 sleeves | `zai-org/GLM-5.2` | Together AI | Migrated from claude-sonnet-4-6 (2026-07-08, ADR-025). Multi-turn tool use, $15/day hard cap that survives restarts. Provider swap is config-only (`LLM_MODEL`/`LLM_BASE_URL`). |
| Tier 2b reasoning, Research Analyst, Fundamentals, Summarizers, conflict judge | Llama-3.3-70B-Instruct-Turbo | Together AI | Narrative reasoning + digests, ~$3/month |
| Chat Agent | DeepSeek-V3 (Llama fallback) | Together AI | RAG over the research schema |
| Embeddings | text-embedding-3-small | OpenAI | pgvector semantic search |

## What's Built

### Trading System

- **Sleeve Orchestrator** — Runs 4 independent Lead Agent calls (one per strategy sleeve) with per-sleeve system prompts and filtered Tier 2 candidates, then consolidates. Cross-sleeve conflicts resolve in three escalating modes — deterministic (ETF → sector-rotation), LLM judge (thesis-fit), load-balance fallback — and **every verdict is persisted** to `agent_actions` with competitors, model, and latency.
- **4 Strategy Sleeves** — Event-driven premium (pre-earnings IV), vol mean reversion (IV spikes without catalyst), sector rotation (ETF macro-driven IV), yield farming (far-OTM on stable large-caps). Per-sleeve config, scanner criteria, weight overrides, capital allocation ($125K each, $500K total paper).
- **Lead Agent** — GLM-5.2 per-sleeve decision maker, 15 tools (fundamentals, briefing, playbook, regime, positions, earnings, news...). Emits both prose reasoning and a **structured judgment envelope** (`verdict, one_liner, factors, confidence`) per cycle. Edge estimates captured per trade for future Kelly calibration.
- **Sleeve Risk Gate** — Hard limits the Lead Agent cannot override: per-sleeve position count, cross-sleeve single-name prevention, sector concentration (30%), capital utilization (80%), portfolio drawdown trigger (8%).
- **Worker Agents** — Covered Calls, Cash Secured Puts, The Wheel (full state machine). Close paths refuse to buy-to-close non-short positions and never stack duplicate close orders (post-incident guards, ADR-026).
- **Breadth Analyst** — Tier 1 daily sweep over ~6,300 optionable names. Robust statistics (median/MAD). Every decision written to `name_observations`.
- **Tier 2a Pre-filter** — 11 change-detection rules with per-name baselines, 2-rule minimum gate, earnings amplification. Runs 3×/day, **append-only** (each sweep stamped with a sortable `sweep_id`; history is never destroyed).
- **Tier 2b Reasoning** — Llama 3.3 narrative per promotion, written once to dedicated columns (never overwrites, never mutates the mechanical snapshot).

### Learning & Integrity Pipeline (the research product)

- **Freeze-at-decision** — Every entry trade snapshots its tier-2 observation (`signal_snapshot`) and sleeve at write time, so the nightly labeler sees exactly what the decision saw — immune to later sweeps.
- **Outcome Labeler** (nightly 5:00 PM ET) — Labels only *filled entry* trades, computes PnL from broker fills, distinguishes order-expired from option-expired, and reports `funnel_driven` as true/false/unknown (never silently false).
- **Signal-Weight Learner** (nightly 5:15 PM ET) — Logistic regression over funnel outcomes; counts **decisions, not contracts**; gated behind 50 clean samples; output is a proposal, never auto-applied.
- **Broker Reconciliation** (nightly 5:45 PM ET) — Cross-checks every DB trade against Alpaca order history (status, fills, positions, realized PnL drift) and publishes a report to the dashboard. Data drift surfaces in a day, not at the next manual audit.
- **Judgment envelopes** — `parse_envelope()` in `services/llm_service.py`; structured judgments ride the same ```json block as actions and degrade to prose-only without data loss.
- **Playbook** — LLM-written institutional memory with bounded retrieval, near-duplicate write guards, and daily caps on regime observations. Weekly/monthly digests compound it.

### Research Data Layer

- **`name_observations`** — One row per name per tier per sweep, **append-only** with sortable `sweep_id` ("latest sweep" = `MAX(sweep_id)`; helpers in `services/sweep_utils.py`). First-class columns for price, volume windows, asset type, selection/rejection reasons, tier2b reasoning.
- **`trades`** — Execution records with frozen decision context (`name_observation_id`, `signal_snapshot`, `sleeve_id`) and broker truth (`fill_price`, `filled_at`).
- **`trade_outcomes`** — Ground truth for learning: fill-based PnL, holding period, frozen signal profile, funnel/sleeve attribution.
- **`cycle_snapshots`** — One row per LLM cycle: regime context, portfolio state, reasoning, cost, model id, and structured envelopes in `full_context`.
- **`agent_actions`** — Unified audit log, including conflict-resolution verdicts.
- **`historical_bars`** — Multi-source persistent daily bars (Alpaca/Stooq/yfinance), unique per `(symbol, bar_date, source)`.
- **`reasoning_embeddings`** — pgvector semantic search (OpenAI embeddings) over reasoning, playbook, and outcomes.

### Intelligence Services

- **Market Regime** — VIX + direction, breadth, SPY trend, sector rotation, credit stress → `risk_on | neutral | risk_off | crisis`.
- **Earnings Calendar** — Finnhub dates; blocks selling puts into announcements.
- **Performance Analyst** — 7 analytical lenses, daily after close.
- **News Feed / VIX Service / FRED / EDGAR** — supporting context feeds.

### API + Dashboard

- **FastAPI Backend** — REST endpoints for dashboard, portfolio, trades, proposals, intelligence, research, diagnostics, chat; serves the production dashboard build.
- **React Dashboard** (Vite, Win95 styling) — 4 screens:
  - **Command Center** (`/`) — system status, funnel counts (latest sweep), learning progress (n/50), reconciliation status, positions, promotions with tier2b reasoning, signal fire rates, daily reflection
  - **History & Learning** (`/history`) — trade history with outcome labels and funnel attribution, cycle reasoning, playbook, daily PnL charts
  - **Rules** (`/rules`) — strategy/rule reference
  - **Chat** (`/chat`) — RAG chat agent over the research database

### CI/CD + Operations

- **GitHub Actions** — Every push to `main` runs preflight (imports + full migration chain against SQLite), then SSHes to the droplet, pulls, rebuilds containers, verifies health.
- **Preflight** (`scripts/preflight.py`) — catches missing deps and broken migrations in ~30 seconds.
- **Docker Compose** — Three containers: PostgreSQL 16 + pgvector, FastAPI app (auto-migrates on start), agents process (APScheduler).
- **Makefile** — `make preflight / deploy / logs / status`.

## Daily Schedule (ET)

| Time | Job |
|------|-----|
| 06:00 | Earnings calendar refresh |
| 08:00 | Tier 1 breadth sweep (append-only) |
| 10:00 / 12:00 / 14:00 | Tier 2a mechanical sweeps |
| 10:10 / 12:10 / 14:10 | Tier 2b LLM reasoning |
| 10:20 / 12:20 / 14:20 | Multi-sleeve Lead Agent cycles (trades) |
| 16:30 | Performance Analyst |
| 17:00 | Outcome Labeler |
| 17:15 | Signal-Weight Learner |
| 17:30 | Research Analyst reflection |
| 17:45 | Broker Reconciliation |
| Sun 18:00 / 1st 18:30 | Weekly / Monthly digests |

## Quick Start

### Docker Compose (production)

```bash
git clone https://github.com/zsindhu/multi-agent-trader.git
cd multi-agent-trader
cp .env.example .env   # Add your API keys
docker compose up -d --build
# Runs: alembic upgrade head → uvicorn (port 8000) + python main.py --mode paper
# Dashboard at http://localhost:8000
```

### Local Development

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
python main.py --mode paper                      # agents
uvicorn api.main:app --reload --port 8000        # API (separate terminal)
cd dashboard && npm install && npm run dev       # dashboard at :5173 (separate terminal)
```

## Configuration

### Environment Variables (`.env`)

```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/premium_trader
TOGETHER_API_KEY=                   # REQUIRED for all LLM agents (lead, tier2b, analysts, chat)
OPENAI_API_KEY=                     # Optional — semantic search embeddings
FINNHUB_API_KEY=                    # Optional — earnings + news (free tier)
DISCORD_WEBHOOK_URL=                # Optional — notifications
# LLM_MODEL / LLM_BASE_URL          # Optional — override the lead agent's model/endpoint
```

Sleeve configs live in `config/sleeves/*.yaml`; tier funnel configs in `config/tier2a.yaml` / `config/tier2b.yaml` / `config/breadth_analyst.yaml`; worker strategy params in `config/strategies.yaml`.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Broker Abstraction** | Abstract `Broker` ABC | Swap brokers without changing agents |
| **Lead Agent model** | GLM-5.2 via OpenAI-compatible endpoint | ~⅓ the cost of Sonnet at parity tool-use quality; rollback is two env vars (ADR-025) |
| **Freeze-at-decision** | Signal snapshot copied onto the trade at write time | Training labels must reflect what the decision saw, not what a later sweep left behind (ADR-026) |
| **Append-only sweeps** | `sweep_id` per sweep, no deletes | Destroying intraday history corrupted 6 of the first 10 training labels |
| **Order-status taxonomy** | `order_expired` ≠ option expired | An unfilled order labeled as a "worthless-expiry win" fabricated 91% of early PnL |
| **Nightly reconciliation** | DB↔broker cross-check with published drift | Data integrity is verified continuously, not discovered by audits |
| **Structured judgments** | Envelope beside prose, never instead of it | Queryable verdicts without losing the narrative the operator reads |
| **Learner gating** | 50 clean *decisions*, output is a proposal | No weight changes without statistical support and human review |
| **Decision Transparency** | Every pass AND reject recorded with reason | Silent filtering forbidden — research depends on "why not?" queries |
| **Cost Cap** | $15/day LLM hard cap, persisted across restarts | Safety net, not target |
| **CI/CD** | Preflight gates every deploy | Broken imports/migrations caught in 30 seconds |
| **Agent Communication** | Shared database (`agent_messages`) | Loose coupling — add agents without modifying existing ones |

## Current Status (2026-07)

- **Experiment MSE-2026-01** running: 4 sleeves, $500K paper, Day-90 checkpoint 2026-07-19, final evaluation 2026-10-17.
- Learning funnel: 17 labeled trades, **4 clean decisions** toward the 50-sample learner gate (6 pre-remediation labels excluded as contaminated — see `RECON_PRE_REMEDIATION_VERIFICATION.md`).
- Known constraint: ~55% of entry limit orders expire unfilled — fill-rate work is the biggest lever on the learning timeline.
- Next build items: frontend alignment batch (`RECON_FRONTEND_ARCHITECTURE_ALIGNMENT.md`), Integrity Sentinel agent (`BACKLOG.md`).

## Tech Stack

- **Python 3.9+** — async/await throughout
- **alpaca-py** — brokerage & market data
- **openai SDK** — all LLM calls (Together AI endpoints) + embeddings
- **FastAPI / SQLAlchemy 2.0 / Alembic** — API + async ORM + migrations
- **PostgreSQL 16 + pgvector** — production DB with vector search (SQLite for preflight)
- **APScheduler** — agent scheduling
- **Docker Compose + GitHub Actions** — 3-container deploy, preflight-gated CI/CD
- **React 19 + Vite** — dashboard frontend
- **Loguru** — structured logging

## Docs

- [`docs/ADR.md`](docs/ADR.md) — Architecture Decision Records (ADR-001 … ADR-026)
- [`EXPERIMENT_CHARTER.md`](EXPERIMENT_CHARTER.md) — registered experiment protocol + amendments
- [`BACKLOG.md`](BACKLOG.md) — working rules, thesis, roadmap
- [`TIER_ARCHITECTURE.md`](TIER_ARCHITECTURE.md) — scanning substrate design
- `RECON_*.md` — point-in-time architecture audits (multi-sleeve viability, structured data, pre-remediation verification, frontend alignment)

## License

Private — for personal use.

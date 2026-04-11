# Premium Trader — Multi-Agent Options Trading System

A research sandbox for answering one question: **can an agentic LLM-driven system generate repeatable alpha, and does the architecture transfer to other markets?**

Options is the first test market — rich structured data, clear entry/exit semantics, enough inefficiency that there might be alpha to capture. The system monitors ~4,500 optionable names across a tiered scanning architecture, reasons over macro context via a Claude-powered Lead Agent, and executes income strategies (Covered Calls, Cash Secured Puts, The Wheel) through Alpaca's brokerage API.

The core thesis about where alpha comes from: the LLM's edge isn't being smarter on any single trade. It's **scale and breadth** — monitoring 4,500 names instead of 5, processing every headline, making consistent decisions across the full universe, never getting tired or biased. The goal is to run a comprehensive research operation for the cost of a Netflix subscription (~$150/month) vs the $50-100K/month a real desk would burn.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4 — Research Interface                           │
│  Plain-HTML inspector at /research          (planned)   │
│  CLI tools: scripts/inspect.py              (planned)   │
│  React dashboard at /                       (live)      │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — Intelligence Agents                          │
│  Lead Agent (LLM decisions + actions)       (live)      │
│  Breadth Analyst (Tier 1 universe sweep)    (live)      │
│  Fundamentals Analyst (10-K/10-Q reading)   (planned)   │
│  Research Analyst (strategy iteration)      (planned)   │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — Research Data Layer                          │
│  PostgreSQL + pgvector                      (live)      │
│  cycle_snapshots, name_observations         (live)      │
│  historical_bars (Stooq + yfinance bulk)    (live)      │
│  agent_messages, skill_documents            (live)      │
│  reasoning_embeddings (OpenAI vectors)      (live)      │
│  agent_actions (unified audit log)          (live)      │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — Data Foundation                              │
│  Alpaca (market data, options, execution)   (live)      │
│  Yahoo Finance (spot VIX)                   (live)      │
│  Finnhub (earnings, news)                   (live)      │
│  Stooq + yfinance (historical bar bulk)     (live)      │
│  FRED (macro indicators)                    (planned)   │
│  EDGAR (SEC filings)                        (planned)   │
└─────────────────────────────────────────────────────────┘
```

## What's Built

### Trading System

- **Lead Agent** — Claude-powered orchestrator. Runs every 20 minutes during market hours. Calls 9 tools per cycle (regime, scanner, positions, performance, earnings, news, playbook). Produces structured JSON actions dispatched to workers. Falls back to emergency-only safe mode if LLM is unavailable. Full reasoning persisted to `cycle_snapshots` for research.
- **Worker Agents** — Covered Calls, Cash Secured Puts, and The Wheel (full state machine: `SELLING_PUTS → ASSIGNED → SELLING_CALLS → CALLED_AWAY`). Each worker handles targeted open/close/roll per LLM action.
- **Scanner Agent** — Dynamic universe discovery from Alpaca's asset list. Batch pre-filter (volume, price, options OI), ETF-aware composite scoring, smart caching (12h bars, 24h support levels). Runs 2x daily (9:35 ET + 12:30 ET).
- **Breadth Analyst** — Tier 1 of the new scanning pipeline. Daily 8 AM ET sweep over the full optionable universe (~4,500 names). Writes every decision (pass, reject, near-miss) to `name_observations` with full transparency. Owns the persistent `historical_bars` cache.
- **Order Reconciler** — Matches submitted orders to fills/rejections from Alpaca before every LLM cycle, keeping DB state in sync with broker reality.
- **Risk Manager** — Portfolio health checks, position sizing, drawdown limits, conservative mode.

### Research Data Layer

- **`cycle_snapshots`** — One row per LLM cycle with regime context, portfolio state, action counts, reasoning text, LLM cost tracking, and a JSONB blob of tool calls and actions.
- **`name_observations`** — One row per name per tier per cycle. First-class columns for price, volume averages (20d/60d/252d), dollar volume, asset type, selection reason, decision layer. JSONB analysis column for signals and diagnostics.
- **`historical_bars`** — Persistent daily bar cache. Multi-source (Alpaca, Stooq, yfinance) with composite unique on `(symbol, bar_date, source)`. Bulk-loaded from free public sources, incrementally updated by the Breadth Analyst.
- **`agent_messages`** — Inter-agent communication bus. Any agent writes, any agent reads. Loose coupling through shared database.
- **`skill_documents`** — Versioned markdown documents per agent. Each agent maintains its own evolving strategy description. Old versions preserved.
- **`reasoning_embeddings`** — Vector embeddings (OpenAI text-embedding-3-small, 1536d) for semantic search via pgvector HNSW index.
- **`agent_actions`** — Unified audit log for every decision any agent makes. Queryable timeline of system behavior.
- **`agent_capabilities`** — Registry of agents and their capabilities. Agents discover each other through this table.

### Intelligence Services

- **Market Regime** — Multi-signal classification (VIX + direction, market breadth, SPY trend, sector rotation, credit stress) → `risk_on | neutral | risk_off | crisis` with confidence score. Persisted to `regime_snapshots`.
- **Earnings Calendar** — Finnhub earnings dates. Flags high-risk symbols (≤7 days) and approaching (≤14 days). Prevents selling puts before announcements.
- **Performance Analyst** — 7 analytical lenses: overall summary, strategy breakdown, delta-bucket win rates, regime correlation, symbol scorecard, open position health, rule-based recommendations. Runs daily after market close.
- **News Feed** — Finnhub general + company news with deduplication, 48h auto-prune.
- **VIX Service** — Real spot VIX from Yahoo Finance (5-min cache). Falls back to VIXY proxy.
- **Embeddings Service** — OpenAI embeddings for semantic search across reasoning traces, playbook entries, and skill documents. Best-effort enrichment (never blocks trading).

### Bulk Historical Data Loading

- **Stooq Adapter** — Reads from a local ZIP archive of the full US daily bar dataset. Builds in-memory symbol index once, reads individual CSVs from ZIP without extraction. No network calls.
- **yfinance Adapter** — Batched `yf.download()` in thread executor (50 symbols/batch, 1s sleep). Handles single vs multi-ticker DataFrame shapes.
- **Orchestrator** (`scripts/bulk_load_historical_bars.py`) — Processes universe in 250-symbol chunks to stay under memory budget on 2 GiB droplets. `INSERT ... ON CONFLICT DO NOTHING` for idempotent re-runs. Logs to `agent_actions`.

### API + Dashboard

- **FastAPI Backend** — REST endpoints for portfolio, trades, agents, scanner, intelligence, executions, proposals, backtest, settings, diagnostics, account. WebSocket for live updates. Static file serving for production dashboard build.
- **React Dashboard** (Vite + Tailwind CSS) — 4 screens:
  - **Dashboard** (`/`) — portfolio stats, equity chart (auto-scaling Y-axis), risk gauge, active positions (with agent assignment badges and unassigned warnings), system thinking card, last cycle actions card, market intelligence
  - **Trade Desk** (`/trade-desk`) — scanner results, trade proposals with approve/reject/modify, execution feed
  - **Performance** (`/performance`) — trade history, journal, backtest engine with compare mode
  - **Diagnostics** (`/diagnostics`) — system health and logs
- **Content-hashed bundles** — Vite outputs `[name].[hash].js` filenames. `index.html` served with `no-cache` headers. Browser cache invalidation is automatic on deploy.

### CI/CD + Operations

- **GitHub Actions** — Every push to `main` runs preflight (imports + SQLite migration test), then SSHes to droplet, pulls, rebuilds containers, verifies health.
- **Preflight** (`scripts/preflight.py`) — Imports every module, runs Alembic migrations against in-memory SQLite. Catches missing deps and broken migrations in 30 seconds. Supports `--ci` flag for credential-free environments.
- **Makefile** — `make preflight`, `make deploy` (preflight → push → SSH rebuild), `make logs`, `make status`.
- **Docker Compose** — Three containers: PostgreSQL 16 with pgvector, FastAPI app (auto-migrates on start), agents process. Stooq ZIP mounted read-only.

## Project Structure

```
premium-trader/
├── agents/
│   ├── base_agent.py              # Abstract lifecycle: scan → evaluate → execute → manage
│   ├── lead_agent.py              # LLM-powered orchestrator (Claude tool use, 9 tools)
│   ├── breadth_analyst.py         # Tier 1 universe sweep + historical bars cache
│   ├── scanner.py                 # Dynamic universe discovery, pre-filter, scoring
│   ├── worker_cc.py               # Covered Calls Worker
│   ├── worker_csp.py              # Cash Secured Puts Worker
│   ├── worker_wheel.py            # The Wheel (CSP ↔ CC state machine)
│   └── trade_journal.py           # Trade context logging (observer)
│
├── api/
│   ├── main.py                    # FastAPI app, lifespan, CORS, WebSocket, static serving
│   ├── state.py                   # AppState — shared services singleton (uses bootstrap)
│   └── routes/                    # 11 route modules (portfolio, trades, agents, scanner,
│                                  #   backtest, settings, proposals, account, executions,
│                                  #   intelligence, diagnostics)
│
├── core/
│   ├── bootstrap.py               # Single source of truth for service initialization
│   ├── broker.py                  # Abstract Broker interface (ABC)
│   ├── database.py                # Async SQLAlchemy engine + session factory
│   ├── portfolio.py               # Portfolio state management + broker sync
│   ├── risk_manager.py            # Position sizing, drawdown limits, conservative mode
│   └── strategy.py                # VIX regime detection + parameter adjustment
│
├── models/                        # 24 SQLAlchemy models
│   ├── trade.py                   # Trade execution records
│   ├── position.py                # Active option positions
│   ├── execution_log.py           # Per-trade reasoning audit trail
│   ├── cycle_snapshot.py          # Full system state per LLM cycle
│   ├── name_observation.py        # Per-name tier decisions (pass/reject/near-miss)
│   ├── historical_bar.py          # Cached OHLCV (multi-source, unique per symbol+date+source)
│   ├── agent_action.py            # Unified agent audit log
│   ├── agent_message.py           # Inter-agent communication bus
│   ├── skill_document.py          # Versioned agent self-documentation
│   ├── reasoning_embedding.py     # pgvector embeddings for semantic search
│   ├── agent_capability.py        # Agent capability registry
│   ├── playbook_entry.py          # Learned trading rules
│   ├── equity_snapshot.py         # Portfolio equity history (for charting)
│   ├── worker_state.py            # Worker active/paused state persistence
│   ├── proposal.py                # Trade proposals (pending → approved/rejected)
│   ├── wheel_state.py             # Wheel strategy state machine persistence
│   ├── regime_snapshot.py         # Market regime classification records
│   ├── earnings_event.py          # Upcoming earnings dates
│   ├── performance_insight.py     # Analytics blobs from PerformanceAnalyst
│   ├── news_headline.py           # Finnhub headlines
│   ├── strategy_insight.py        # Strategy performance analysis
│   ├── opportunity.py             # Scanner-detected opportunities
│   ├── performance.py             # Aggregated performance metrics
│   └── journal_entry.py           # Detailed trade journal entries
│
├── services/
│   ├── alpaca_broker.py           # AlpacaBroker — Broker interface implementation
│   ├── llm_service.py             # Claude API — multi-turn tool use, cost tracking ($5/day cap)
│   ├── order_reconciler.py        # Syncs broker order state to DB before each cycle
│   ├── vix_service.py             # Real spot VIX from Yahoo Finance
│   ├── market_regime.py           # Multi-signal regime classification
│   ├── earnings_calendar.py       # Finnhub earnings dates
│   ├── performance_analyst.py     # 7-lens trade analytics
│   ├── news_feed.py               # Finnhub headlines with dedup + auto-prune
│   ├── embeddings.py              # OpenAI embeddings + pgvector search
│   ├── research_data.py           # High-level interface to research data layer
│   ├── notifier.py                # Discord webhook notifications
│   ├── logger_service.py          # Performance metrics logging
│   ├── backtester.py              # Historical replay engine
│   ├── breadth_checkpoint.py      # Backfill checkpoint file management
│   ├── universe_loader.py         # Legacy universe loader (being replaced by Breadth Analyst)
│   ├── tier_writer.py             # Legacy tier writer (being replaced by Breadth Analyst)
│   ├── universe_filters.py        # Legacy filter constants
│   └── bulk_data_sources/
│       ├── base.py                # Abstract adapter interface
│       ├── stooq_adapter.py       # Reads from local Stooq ZIP archive
│       └── yfinance_adapter.py    # Yahoo Finance batched download
│
├── config/
│   ├── settings.py                # Pydantic settings (loads from .env)
│   ├── strategies.yaml            # Strategy parameters (delta targets, DTE ranges, IV thresholds)
│   ├── scanner_universe.yaml      # Scanner config (pre-filter, weights, cache TTLs, overrides)
│   └── breadth_analyst.yaml       # Breadth Analyst config (filters, pacing, windows, overrides)
│
├── dashboard/                     # React frontend (Vite + Tailwind CSS 4)
│   └── src/
│       ├── api.js                 # API client — all backend endpoint functions
│       ├── App.jsx                # Layout, nav, trading mode toggle
│       ├── components/            # 18 components (ActivePositions, LastCycleActions,
│       │                          #   SystemThinking, MarketIntelligence, ProposalCard, etc.)
│       └── pages/                 # DashboardPage, TradeDeskPage, PerformancePage, DiagnosticsPage
│
├── data/
│   ├── market_feed.py             # Real-time quotes, IV rank, support/resistance
│   └── options_chain.py           # Options chain analysis, filtering & scoring
│
├── scripts/
│   ├── preflight.py               # Pre-deploy smoke test (imports + migrations)
│   ├── bulk_load_historical_bars.py  # Bulk ingest from Stooq + yfinance (chunked, idempotent)
│   ├── run_breadth_analyst.py     # Manual Breadth Analyst invocation (backfill / sweep)
│   ├── run_universe_sweep.py      # Legacy manual universe sweep
│   ├── backtest.py                # Backtest CLI (run, compare, export)
│   ├── backfill_agent_assignments.py  # One-shot: assign legacy trades to workers
│   ├── mark_legacy_submitted_unknown.py  # One-shot: clean up stuck submitted trades
│   ├── diagnose_bars.py           # Debug market data fetching
│   ├── diagnose_orders.py         # Debug order submission/fills
│   └── init_db.py                 # Database initialization
│
├── docs/
│   ├── ADR.md                     # Architecture Decision Records
│   ├── PRFAQ.md                   # Product FAQ
│   └── DEPLOY_SETUP.md            # GitHub Actions SSH key setup guide
│
├── .github/workflows/
│   └── deploy.yml                 # CI/CD: preflight → SSH deploy to droplet
│
├── main.py                        # Agent entrypoint + APScheduler (20min LLM cycles)
├── docker-compose.yml             # 3 containers: db (pgvector), app (FastAPI), agents
├── Makefile                       # make preflight / deploy / logs / status
├── alembic.ini                    # Alembic configuration
├── BACKLOG.md                     # Single source of truth for planned work
└── requirements.txt               # Python dependencies
```

## Quick Start

### Docker Compose (production)

```bash
# 1. Clone & configure
git clone https://github.com/zsindhu/multi-agent-trader.git
cd multi-agent-trader
cp .env.example .env   # Add your API keys

# 2. Start everything
docker compose up -d --build
# Runs: alembic upgrade head → uvicorn (port 8000) + python main.py --mode paper

# 3. Dashboard at http://localhost:8000
```

### Local Development

```bash
# 1. Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Initialize database
python scripts/init_db.py

# 3. Run the trading agents
python main.py --mode paper

# 4. Run the API server (separate terminal)
uvicorn api.main:app --reload --port 8000

# 5. Run the dashboard (separate terminal)
cd dashboard && npm install && npm run dev
# Dashboard at http://localhost:5173, API proxied to :8000
```

### Bulk Load Historical Data (one-time)

```bash
# Load from Stooq + yfinance (chunked, idempotent, ~30-60 min)
python scripts/bulk_load_historical_bars.py

# Test with a small set first
python scripts/bulk_load_historical_bars.py --symbols AAPL,MSFT,SPY --days 30

# Resume after interruption (ON CONFLICT DO NOTHING skips existing rows)
python scripts/bulk_load_historical_bars.py
```

## Configuration

### Environment Variables (`.env`)

```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/premium_trader
DISCORD_WEBHOOK_URL=                # Optional — Discord notifications
FINNHUB_API_KEY=                    # Optional — earnings + news (free tier)
ANTHROPIC_API_KEY=                  # Optional — enables LLM Lead Agent (Claude)
OPENAI_API_KEY=                     # Optional — enables semantic search embeddings
```

### Strategy Parameters (`config/strategies.yaml`)

```yaml
covered_calls:
  min_iv_rank: 30
  delta_target: 0.30
  dte_min: 20
  dte_max: 45

cash_secured_puts:
  min_iv_rank: 25
  delta_target: -0.25
  support_buffer: 0.05

wheel:
  min_iv_rank: 25
  cc_delta: 0.30
  csp_delta: -0.25
```

### Breadth Analyst (`config/breadth_analyst.yaml`)

```yaml
breadth_analyst:
  min_price: 5.0
  max_price: 1000.0
  min_avg_volume_20d: 100000
  max_universe_size: 4500
  near_miss_threshold_pct: 0.15
  backfill_days: 252
  batch_size: 50
  batch_sleep_seconds: 2.0
  always_include: [SPY, QQQ, IWM, DIA, XLF, XLE, XLK, XLV, SMH, GDX, TLT, HYG, EFA, EEM]
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Broker Abstraction** | Abstract `Broker` ABC | Swap brokers without changing agents |
| **Bootstrap Pattern** | `core/bootstrap.py` single source of truth | Eliminates entrypoint drift between `main.py` and `api/state.py` |
| **LLM Cycle** | Every 20 min, always LLM (no rules fallback) | Rules path was running 95% of the time, defeating the purpose |
| **Safe Mode** | Emergency-only (ITM expiring, >300% loss) | Fires only when LLM is truly unavailable, not as a parallel path |
| **Tier Architecture** | 4-tier funnel (universe → active → deep → positions) | Breadth thesis requires monitoring 4,500 names at appropriate depth |
| **Decision Transparency** | Every pass AND reject recorded with reason | Silent filtering forbidden — research depends on "why not?" queries |
| **Historical Bars** | Multi-source persistent cache | Compute metrics from DB, not fresh API calls. One fetch per symbol per day. |
| **Research Data Layer** | 8 new tables with JSONB + pgvector | Captures every signal for future analysis without schema rigidity |
| **Cost Cap** | $5/day LLM hard cap (~$100/month max) | Safety net, not target. Projected ~$2.60/day at 20-min cadence. |
| **CI/CD** | Preflight gates every deploy | pytz bug, httpx bug, migration bugs — all caught in 30 seconds |
| **Database** | PostgreSQL + pgvector (prod), SQLite (preflight) | pgvector for semantic search, SQLite for fast CI validation |
| **Agent Communication** | Shared database (agent_messages table) | Loose coupling — add new agents without modifying existing ones |

## Planned Work

| Phase | Scope | Status |
|-------|-------|--------|
| **1.1** | Research data layer schema (8 tables) | Shipped |
| **1.2** | Universe expansion + tiered scanning | In progress (Breadth Analyst live, Tier 2-4 planned) |
| **1.3** | New data feeds (FRED, EDGAR, TA-Lib) | Planned |
| **1.4** | New intelligence agents (Fundamentals, Research) | Planned |
| **1.5** | Research inspector (plain HTML at /research) | Planned |
| **2** | Real research dashboard | Deferred until Phase 1 proves what's useful |
| **3** | Architecture transferability (Bitcoin perps, prediction markets) | Deferred until architecture proven in options |

## Tech Stack

- **Python 3.9+** — async/await throughout
- **alpaca-py** — Brokerage & market data API
- **anthropic** — Claude API (LLM-powered Lead Agent, $5/day cap)
- **openai** — Embeddings API (text-embedding-3-small for semantic search)
- **FastAPI** — REST API + WebSocket backend
- **SQLAlchemy 2.0** — Async ORM with Alembic migrations
- **PostgreSQL 16 + pgvector** — Production database with vector similarity search
- **APScheduler** — Cron + interval scheduling for agents
- **Docker Compose** — 3-container deployment (db, app, agents)
- **GitHub Actions** — CI/CD with preflight gating
- **yfinance + Stooq** — Bulk historical data sources
- **Finnhub** — Earnings calendar + news headlines
- **httpx** — Async HTTP (Alpaca REST bypass, external feeds)
- **React 19 + Vite + Tailwind CSS 4** — Dashboard frontend
- **Recharts** — Equity curves & analytics charts
- **Loguru** — Structured logging
- **Discord webhooks** — Trade alerts & risk notifications

## License

Private — for personal use.

# Premium Trader — Multi-Agent Options Trading System

A multi-agent architecture for automated options income strategies (Covered Calls, Cash Secured Puts, The Wheel) built on Alpaca's brokerage API with a broker-agnostic abstraction layer, dynamic universe discovery, VIX regime adaptation, backtesting engine, and a full-stack React dashboard.

## Architecture

```
                         ┌──────────────────────────┐
                         │    Alpaca Brokerage API   │
                         │  Market Data · Trading    │
                         └────────────┬─────────────┘
                                      │
                         ┌────────────▼─────────────┐
                         │  Broker Abstraction Layer │
                         │    core/broker.py (ABC)   │
                         │    └─ AlpacaBroker impl   │
                         └────────────┬─────────────┘
                                      │
          ┌───────────────────────────▼───────────────────────────┐
          │                    Data Layer                          │
          │  MarketFeed (quotes, IV rank, support/resistance)     │
          │  OptionsChainAnalyzer (filter, score, rank contracts) │
          └──────┬────────────────────────────────────┬──────────┘
                 │                                    │
    ┌────────────▼───────────┐           ┌────────────▼───────────┐
    │     Scanner Agent      │           │   Lead Agent           │
    │  Dynamic Universe      │──────────▶│   (Orchestrator)       │
    │  Discovery · Pre-filter│  top N    │   Assignment · Risk    │
    │  Scoring · ETF-aware   │  opps     │   Performance Rotation │
    │  Smart Caching         │           └───┬──────┬──────┬─────┘
    │  Runs 2x daily         │               │      │      │
    └────────────────────────┘       ┌───────▼┐ ┌───▼───┐ ┌▼────────┐
                                     │Covered │ │ Cash   │ │  The    │
                                     │ Calls  │ │Secured │ │ Wheel   │
                                     │        │ │ Puts   │ │(CSP↔CC) │
                                     │        │ │        │ │         │
                                     └───┬────┘ └───┬────┘ └───┬─────┘
                                         │          │          │
                                      ┌──▼──────────▼──────────▼──┐
                                      │    Trade Journal Agent     │
                                      │  Entry/Exit · Context ·   │
                                      │  Asset Type Tracking       │
                                      └────────────┬──────────────┘
                                                   │
                                      ┌────────────▼──────────────┐
                                      │    Performance Logger      │
                                      │  Win Rate · P&L · Sharpe  │
                                      │  Drawdown · Premium Track  │
                                      └────────────┬──────────────┘
                                                   │
                              ┌─────────────────────┼────────────────────┐
                              │                     │                    │
                 ┌────────────▼──────────┐ ┌────────▼──────┐ ┌──────────▼─────┐
                 │    SQLite / Postgres   │ │  Discord      │ │  Backtester    │
                 │  Trades · Positions    │ │  Notifier     │ │  Historical    │
                 │  Journal · Perf        │ │  Webhooks     │ │  Replay Engine │
                 │  Wheel State · Opps    │ └───────────────┘ └────────────────┘
                 └───────────────────────┘
                              │
                 ┌────────────▼──────────────┐
                 │   FastAPI Backend          │
                 │   REST API · WebSocket     │
                 │   Portfolio · Trades ·     │
                 │   Agents · Scanner ·       │
                 │   Backtest · Settings      │
                 └────────────┬──────────────┘
                              │
                 ┌────────────▼──────────────┐
                 │   React Dashboard          │
                 │   Vite + Tailwind CSS      │
                 │   Portfolio · Positions ·  │
                 │   Trades · Agents ·        │
                 │   Scanner Workshop ·       │
                 │   Backtest · Mode Toggle   │
                 └───────────────────────────┘
```

## What's Built

### Phase 1 — Data Layer & Alpaca Integration ✅
- Full Alpaca API integration via `alpaca-py` (options chains, orders, historical data, quotes)
- Real-time market data streaming with WebSocket support
- IV rank calculation (current IV vs 52-week percentile using rolling realized vol)
- Options chain analyzer with filtering, scoring, and optimal strike selection
- Rate limiting and async API methods throughout

### Phase 2 — Broker Abstraction Layer ✅
- Abstract `Broker` interface (`core/broker.py`) decouples all trading logic from Alpaca
- `AlpacaBroker` implementation (`services/alpaca_broker.py`) with full API coverage
- All agents and data modules use dependency injection — swap brokers without touching agent code
- `get_tradable_assets()` for dynamic asset discovery with ETF classification
- `get_historical_bars_batch()` for cheap multi-symbol bar fetching (up to 200 per call)

### Phase 3 — Database & Trade Journal Agent ✅
- SQLAlchemy 2.0 async models: `Trade`, `ActivePosition`, `AgentPerformance`, `ScannerOpportunity`, `JournalEntry`
- Alembic migrations for schema management (auto-generated, versioned)
- `TradeJournalAgent` — records every trade with full market context (IV rank, VIX, support distances, strategy params, asset type)
- `PerformanceLogger` — async metrics engine (win rate, Sharpe ratio, max drawdown, premium tracking)
- Async SQLAlchemy session management via `core/database.py`

### Phase 4 — Worker Agents + Scanner Agent + Lead Agent Intelligence ✅
- **Covered Calls Worker**: scans held shares for CC opportunities, scores contracts, manages profit-taking and rolling
- **Cash Secured Puts Worker**: scans for high-IV stocks near support, filters chain, handles assignment and rolling
- **The Wheel Worker**: full state machine (`SELLING_PUTS → ASSIGNED → SELLING_CALLS → CALLED_AWAY`), tracks cumulative cost basis, logs full cycle metrics
- **Scanner Agent**: dynamic universe discovery from broker's asset list (no static watchlists), batch pre-filter (volume ≥ 1M, price $5–$500), ETF-aware composite scoring, smart caching (12h bars, 24h support levels), `always_include` / `always_exclude` lists, runs 2× daily (9:35 ET + 12:30 ET)
- **Lead Agent**: orchestrates workers, assigns symbols using Scanner results (falls back to static watchlist), syncs portfolio from broker, performance-based worker rotation, conservative mode on risk breach
- **Risk Manager**: portfolio health checks, position sizing, drawdown limits, conservative mode support
- **Portfolio**: tracks cash, buying power, equity, stock + option positions, `sync_from_broker()`

### Phase 7B — Supporting Services ✅
- **VIX Regime Detection** (`core/strategy.py`): fetches VIX proxy, classifies regime (high_vol / normal / low_vol), adjusts strategy params (delta targets, max positions) — refreshed each cycle
- **Discord Notifications** (`services/notifier.py`): webhook notifications for trade alerts, risk warnings, cycle summaries, daily summaries; graceful no-op if no webhook configured
- **Wheel State Persistence** (`models/wheel_state.py`): SQLAlchemy model for persisting Wheel state machine across restarts (phase, cost basis, cycle count)
- Removed legacy `alpaca_client.py` — all code uses `AlpacaBroker` via the `Broker` interface

### Phase 8 — Backtesting Engine ✅
- **BacktestBroker** (`services/backtester.py`): mock `Broker` implementation that serves cached historical bars and generates synthetic options chains with realistic Greeks
- **BacktestEngine**: historical replay loop stepping through trading days, running agent lifecycle (`scan → evaluate → execute → manage_positions`), handles option expiration, put assignment, and call assignment
- **BacktestResult**: comprehensive stats — equity curve, trade log, summary (Sharpe, Sortino, max drawdown, win rate, profit factor), per-symbol breakdown, monthly returns
- **CLI** (`scripts/backtest.py`): single runs, parameter overrides, `--compare` mode, JSON export
- Local data caching in `data/backtest_cache/` (pickle files) to avoid redundant API calls

### Phase 9 — FastAPI Backend + React Dashboard ✅
- **FastAPI Backend** (`api/main.py`):
  - `AppState` singleton (`api/state.py`) — wires broker, portfolio, scanner, strategy manager, and all services at startup
  - REST endpoints: `/api/portfolio`, `/api/trades`, `/api/agents`, `/api/scanner`, `/api/backtest`, `/api/settings`
  - Portfolio snapshot with account balances, positions, options, market regime
  - Trade history + journal queries with filtering
  - Agent status and strategy parameter CRUD
  - Scanner run/preview/config with live parameter tuning
  - Backtest run/status/results with job management and compare mode
  - Trading mode toggle (`POST /api/settings/mode`) — switches between paper and live, reinitializes broker and dependent services, persists to `.env`

- **React Dashboard** (`dashboard/`):
  - Vite + React 19 + Tailwind CSS 4 + React Router
  - **Portfolio Overview**: stat cards (equity, cash, buying power, P&L), Active Positions summary (collapsible, grouped by underlying, strategy badges), Market Regime display
  - **Positions Page**: stock + option positions with filtering
  - **Trade History**: filterable trade log and journal entries
  - **Agent Status**: per-agent metrics, strategy parameter editor
  - **Scanner Workshop**: live parameter tuning, preview runs, opportunity scoring
  - **Backtest**: run backtests, view results with equity curves, compare mode
  - **Trading Mode Toggle**: interactive header toggle (Paper ↔ Live), green/red pulsing indicator, 2-step confirmation modal for live mode, global visual cues (red top border, sidebar tints when live)
  - **Active Positions Summary**: collapsible section on Portfolio view — groups options by underlying, shows contract count, managing agent with color-coded badges (indigo=CC, emerald=CSP, pink=Wheel), premium collected, P&L; Wheel phase display (selling puts / selling calls)
  - API client (`api.js`) with all endpoint functions
  - Vite dev proxy to FastAPI backend on `:8000`

## Phased Build Plan

| Phase | Scope | Status |
|-------|-------|--------|
| **1** | Data Layer — Alpaca API, MarketFeed, OptionsChainAnalyzer | ✅ Complete |
| **2** | Broker Abstraction — `Broker` ABC, `AlpacaBroker`, dependency injection | ✅ Complete |
| **3** | Database — SQLAlchemy models, Alembic, TradeJournal, PerformanceLogger | ✅ Complete |
| **4** | Workers + Scanner + Lead Agent — CC, CSP, Wheel, dynamic universe, orchestration | ✅ Complete |
| **7B** | Supporting Services — VIX regime, Discord notifications, Wheel state persistence | ✅ Complete |
| **8** | Backtesting Engine — historical replay, synthetic chains, CLI, compare mode | ✅ Complete |
| **9** | Dashboard — FastAPI REST API, React + Tailwind, Scanner Workshop, Mode Toggle | ✅ Complete |

### Remaining Work
| Phase | Scope | Status |
|-------|-------|--------|
| **5** | Advanced Intelligence — earnings avoidance, sector diversification, correlation | 🔲 Planned |
| **10** | ML Layer — IV surface modeling, regime detection, entry timing | 🔲 Planned |
| **11** | Risk Hardening — Greeks monitoring, margin impact, circuit breakers | 🔲 Planned |

## Quick Start

```bash
# 1. Clone & setup
git clone https://github.com/zsindhu/multi-agent-trader.git
cd multi-agent-trader
cp .env.example .env   # Add your Alpaca API keys

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Initialize database (runs Alembic migrations)
python scripts/init_db.py

# 4. Run the trading system (paper mode)
python main.py --mode paper

# 5. Start the API server
uvicorn api.main:app --reload --port 8000

# 6. Start the dashboard (dev mode)
cd dashboard
npm install
npm run dev
# Dashboard at http://localhost:5173, API proxied to :8000
```

## Configuration

### Environment Variables (`.env`)
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets   # Paper trading
TRADING_MODE=paper                                  # paper | live
DISCORD_WEBHOOK_URL=                                # Optional — Discord notifications
```

### Strategy Parameters (`config/strategies.yaml`)
```yaml
covered_calls:
  min_iv_rank: 30       # Minimum IV rank to sell calls
  delta_target: 0.30    # Target delta for call selection
  dte_min: 20           # Minimum days to expiration
  dte_max: 45           # Maximum days to expiration

cash_secured_puts:
  min_iv_rank: 25
  delta_target: -0.25
  support_buffer: 0.05  # % buffer above support level

wheel:
  min_iv_rank: 25
  cc_delta: 0.30
  csp_delta: -0.25
```

### Scanner Configuration (`config/scanner_universe.yaml`)
```yaml
scanner:
  # Pre-filter thresholds (applied to broker's full asset list)
  min_daily_volume: 1000000     # Avg daily volume in shares
  min_price: 5.0
  max_price: 500.0
  min_options_oi: 100

  # Composite scoring weights (sum to 1.0)
  weights:
    iv_rank: 0.30
    momentum: 0.20
    liquidity: 0.25
    support_proximity: 0.15
    mean_reversion: 0.10

  # Smart caching — avoids redundant API calls
  cache:
    iv_history_ttl: 43200       # 12h — loads at market open
    historical_bars_ttl: 43200  # 12h — momentum/MA static intraday
    support_levels_ttl: 86400   # 24h — swing lows don't change
    prefilter_ttl: 43200        # 12h — discovery runs once

  # ETF scoring adjustments
  etf:
    iv_rank_discount: 10        # Lower IV threshold for ETFs
    support_weight_reduction: 0.5
    liquidity_bonus: 0.10
    broad_index_etfs: [SPY, QQQ, IWM, DIA]

  # Override lists
  always_include: [SPY, QQQ, IWM, DIA, XLF, XLE, XBI, SMH, ...]
  always_exclude: []
```

## Project Structure

```
premium-trader/
├── agents/                    # Multi-agent system
│   ├── base_agent.py          # Abstract lifecycle: scan → evaluate → execute → manage
│   ├── lead_agent.py          # Portfolio orchestrator & Scanner-powered assignment
│   ├── scanner.py             # Dynamic universe discovery, pre-filter, ETF-aware scoring
│   ├── worker_cc.py           # Covered Calls Worker
│   ├── worker_csp.py          # Cash Secured Puts Worker
│   ├── worker_wheel.py        # The Wheel (CSP ↔ CC state machine)
│   └── trade_journal.py       # Trade Journal Agent — context-rich trade logging
│
├── api/                       # FastAPI REST backend
│   ├── main.py                # FastAPI app, lifespan, CORS, static serving
│   ├── state.py               # AppState — shared services singleton
│   └── routes/
│       ├── portfolio.py       # Account snapshot, positions, options, refresh
│       ├── trades.py          # Trade history, journal queries, performance stats
│       ├── agents.py          # Agent status, regime, strategy CRUD
│       ├── scanner.py         # Run scanner, preview, config tuning
│       ├── backtest.py        # Run/status/results, compare mode, job list
│       └── settings.py        # Trading mode toggle (paper ↔ live)
│
├── core/                      # Core abstractions & business logic
│   ├── broker.py              # Abstract Broker interface (ABC)
│   ├── database.py            # Async SQLAlchemy session factory
│   ├── portfolio.py           # Portfolio state management + broker sync
│   ├── risk_manager.py        # Position sizing, drawdown limits, conservative mode
│   └── strategy.py            # VIX regime detection + parameter adjustment
│
├── dashboard/                 # React frontend (Vite + Tailwind CSS)
│   ├── src/
│   │   ├── api.js             # API client — all backend endpoint functions
│   │   ├── App.jsx            # Layout, nav, trading mode toggle, global styling
│   │   ├── components/
│   │   │   ├── ActivePositions.jsx  # Collapsible positions summary (grouped by underlying)
│   │   │   ├── Badge.jsx            # Color-coded badges (green, red, blue, indigo, pink…)
│   │   │   ├── Card.jsx             # Reusable card container
│   │   │   ├── ConfirmLiveModal.jsx # 2-step confirmation for live trading switch
│   │   │   ├── Spinner.jsx          # Loading spinner
│   │   │   ├── StatCard.jsx         # Metric display card with trend indicator
│   │   │   └── TradingModeToggle.jsx # Paper/Live dropdown with pulsing indicators
│   │   └── pages/
│   │       ├── Portfolio.jsx        # Account overview + active positions + regime
│   │       ├── Positions.jsx        # Stock & option position details
│   │       ├── TradeHistory.jsx     # Trade log & journal with filters
│   │       ├── AgentStatus.jsx      # Per-agent metrics & strategy editor
│   │       ├── ScannerWorkshop.jsx  # Live parameter tuning & preview
│   │       └── Backtest.jsx         # Run backtests, view results, compare
│   ├── vite.config.js         # Vite config with API proxy to :8000
│   └── package.json
│
├── data/                      # Market data layer
│   ├── market_feed.py         # Real-time quotes, IV rank, support/resistance
│   ├── options_chain.py       # Options chain analysis, filtering & scoring
│   ├── backtest_cache/        # Cached historical data for backtesting
│   └── backtest_results/      # Stored backtest result files
│
├── models/                    # SQLAlchemy ORM models
│   ├── trade.py               # Trade execution records
│   ├── position.py            # Active option positions
│   ├── performance.py         # Agent performance snapshots
│   ├── opportunity.py         # Scanner-detected opportunities (+ asset_type)
│   ├── journal_entry.py       # Detailed trade journal entries (+ asset_type)
│   └── wheel_state.py         # Wheel state machine persistence
│
├── services/                  # External service integrations
│   ├── alpaca_broker.py       # AlpacaBroker — Broker interface implementation
│   ├── backtester.py          # BacktestBroker, BacktestEngine, BacktestResult
│   ├── logger_service.py      # Performance logger (metrics, P&L, Sharpe)
│   └── notifier.py            # Discord webhook notifications
│
├── config/                    # Configuration
│   ├── settings.py            # Pydantic settings (loads from .env)
│   ├── strategies.yaml        # Strategy parameters & fallback watchlists
│   └── scanner_universe.yaml  # Scanner config (pre-filter, weights, cache, ETF, overrides)
│
├── alembic/                   # Database migrations
│   ├── env.py                 # Alembic environment config
│   └── versions/              # Migration scripts (auto-generated)
│
├── scripts/
│   ├── init_db.py             # Database initialization via Alembic
│   └── backtest.py            # Backtest CLI (run, compare, export)
│
├── docs/
│   ├── ADR.md                 # Architecture Decision Records
│   └── PRFAQ.md               # Product FAQ
│
├── tests/
│   └── test_alpaca.py         # Integration tests
│
├── main.py                    # Application entry point + APScheduler
├── alembic.ini                # Alembic configuration
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
└── README.md
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Broker SDK** | `alpaca-py` (not `alpaca-trade-api`) | Modern async SDK, active maintenance |
| **Broker Abstraction** | Abstract `Broker` ABC | Swap brokers without changing agents |
| **Dynamic Universe** | Broker asset discovery + batch pre-filter | New IPOs auto-discovered, delistings auto-dropped |
| **ETF Support** | Asset type classification + adjusted scoring | ETFs have different IV characteristics, always-liquid chains |
| **Smart Caching** | TTL-based per data type (12h bars, 24h support) | Avoids redundant API calls on midday scan |
| **VIX Regime** | `StrategyManager` classifies high/normal/low vol | Workers auto-adapt delta targets and position limits |
| **Wheel State** | SQLAlchemy model with DB persistence | State machine survives restarts; cost basis preserved |
| **Backtesting** | Mock `Broker` + synthetic options chains | Any agent backtestable without code changes |
| **Database** | SQLite (dev) / PostgreSQL (prod) | SQLite for zero-config dev, Postgres for production |
| **ORM** | SQLAlchemy 2.0 async | Full async support, Alembic migrations |
| **Agent Lifecycle** | `scan → evaluate → execute → manage` | Consistent pattern across all workers |
| **Scanner Schedule** | 2× daily (9:35 + 12:30 ET) | Universe changes slowly; workers run every 15 min |
| **Config** | Pydantic Settings + YAML | Type-safe env vars + human-readable strategy params |
| **Async** | `asyncio` throughout | Non-blocking API calls, streaming, DB queries |
| **API** | FastAPI with Pydantic models | Auto-docs, async, validation |
| **Dashboard** | React 19 + Vite + Tailwind CSS 4 | Fast HMR, modern CSS, component-based UI |
| **Trading Mode** | Runtime toggle with broker reinitialization | Switch paper ↔ live without restart; 2-step confirmation for safety |
| **Notifications** | Discord webhooks (graceful no-op) | Non-intrusive; no crash if not configured |

## Tech Stack

- **Python 3.9+** — async/await throughout
- **alpaca-py** — Brokerage & market data API
- **FastAPI** — REST API + WebSocket backend
- **SQLAlchemy 2.0** — Async ORM with Alembic migrations
- **APScheduler** — Cron + interval scheduling for agents
- **Pydantic v2** — Settings & data validation
- **Loguru** — Structured logging
- **React 19** — Component-based dashboard UI
- **Vite 7** — Frontend build tool with HMR
- **Tailwind CSS 4** — Utility-first styling
- **React Router 7** — Client-side routing
- **Recharts** — Charting library for equity curves & metrics
- **Lucide React** — Icon library

## License

Private — for personal use.

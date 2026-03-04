# Premium Trader — Multi-Agent Options Trading System

A multi-agent architecture for automated options income strategies (Covered Calls, Cash Secured Puts, The Wheel) built on Alpaca's brokerage API with a broker-agnostic abstraction layer, dynamic universe discovery, and comprehensive trade journaling.

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
                                     │Worker A│ │Worker B│ │Worker C │
                                     │Covered │ │ Cash   │ │  The    │
                                     │ Calls  │ │Secured │ │ Wheel   │
                                     │        │ │ Puts   │ │(CSP↔CC) │
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
                                      ┌────────────▼──────────────┐
                                      │    SQLite / PostgreSQL     │
                                      │  Trades · Positions · Perf │
                                      │  Journal · Opportunities   │
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
- **Worker A (Covered Calls)**: scans held shares for CC opportunities, scores contracts, manages profit-taking and rolling
- **Worker B (Cash Secured Puts)**: scans for high-IV stocks near support, filters chain, handles assignment and rolling
- **Worker C (The Wheel)**: full state machine (`SELLING_PUTS → ASSIGNED → SELLING_CALLS → CALLED_AWAY`), tracks cumulative cost basis, logs full cycle metrics
- **Scanner Agent**: dynamic universe discovery from broker's asset list (no static watchlists), batch pre-filter (volume ≥ 1M, price $5–$500), ETF-aware composite scoring, smart caching (12h bars, 24h support levels), `always_include` / `always_exclude` lists, runs 2× daily (9:35 ET + 12:30 ET)
- **Lead Agent**: orchestrates workers, assigns symbols using Scanner results (falls back to static watchlist), syncs portfolio from broker, performance-based worker rotation, conservative mode on risk breach
- **Risk Manager**: portfolio health checks, position sizing, drawdown limits, conservative mode support
- **Portfolio**: tracks cash, buying power, equity, stock + option positions, `sync_from_broker()`

### Phases 5–6 — Upcoming
- **Phase 5**: Advanced Lead Agent intelligence (earnings calendar avoidance, sector diversification, correlation-aware assignment)
- **Phase 6**: FastAPI backend + React dashboard with real-time WebSocket updates

## Phased Build Plan

| Phase | Scope | Status |
|-------|-------|--------|
| **1** | Data Layer — Alpaca API, MarketFeed, OptionsChainAnalyzer | ✅ Complete |
| **2** | Broker Abstraction — `Broker` ABC, `AlpacaBroker`, dependency injection | ✅ Complete |
| **3** | Database — SQLAlchemy models, Alembic, TradeJournal, PerformanceLogger | ✅ Complete |
| **4** | Workers + Scanner + Lead Agent — CC, CSP, Wheel, dynamic universe, orchestration | ✅ Complete |
| **5** | Advanced Intelligence — earnings avoidance, sector diversification, correlation | 🔲 Planned |
| **6** | Dashboard — FastAPI REST + WebSocket, React + Tailwind | 🔲 Planned |
| **7** | Risk Hardening — Greeks monitoring, margin impact, circuit breakers | 🔲 Planned |
| **8** | ML Layer — IV surface modeling, regime detection, entry timing | 🔲 Planned |
| **9** | Scanner Workshop — live weight tuning UI, backtesting, parameter optimization | 🔲 Planned |

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

# 4. Run tests
pytest tests/

# 5. Run in paper trading mode
python main.py --mode paper
```

## Configuration

### Environment Variables (`.env`)
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets   # Paper trading
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
│   ├── worker_cc.py           # Worker A: Covered Calls
│   ├── worker_csp.py          # Worker B: Cash Secured Puts
│   ├── worker_wheel.py        # Worker C: The Wheel (CSP ↔ CC state machine)
│   └── trade_journal.py       # Trade Journal Agent — context-rich trade logging
│
├── core/                      # Core abstractions & business logic
│   ├── broker.py              # Abstract Broker interface (ABC)
│   ├── database.py            # Async SQLAlchemy session factory
│   ├── portfolio.py           # Portfolio state management + broker sync
│   └── risk_manager.py        # Position sizing, drawdown limits, conservative mode
│
├── data/                      # Market data layer
│   ├── market_feed.py         # Real-time quotes, IV rank, support/resistance
│   └── options_chain.py       # Options chain analysis, filtering & scoring
│
├── models/                    # SQLAlchemy ORM models
│   ├── trade.py               # Trade execution records
│   ├── position.py            # Active option positions
│   ├── performance.py         # Agent performance snapshots
│   ├── opportunity.py         # Scanner-detected opportunities (+ asset_type)
│   └── journal_entry.py       # Detailed trade journal entries (+ asset_type)
│
├── services/                  # External service integrations
│   ├── alpaca_broker.py       # AlpacaBroker — Broker interface implementation
│   ├── alpaca_client.py       # Low-level Alpaca API wrapper (legacy)
│   └── logger_service.py      # Performance logger (metrics, P&L, Sharpe)
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
├── api/                       # FastAPI backend (Phase 6)
├── dashboard/                 # React frontend (Phase 6)
├── scripts/
│   └── init_db.py             # Database initialization via Alembic
├── tests/
│   └── test_alpaca.py         # Integration tests
├── notebooks/                 # Jupyter research notebooks
│
├── main.py                    # Application entry point + scheduler
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
| **Database** | SQLite (dev) / PostgreSQL (prod) | SQLite for zero-config dev, Postgres for production |
| **ORM** | SQLAlchemy 2.0 async | Full async support, Alembic migrations |
| **Agent Lifecycle** | `scan → evaluate → execute → manage` | Consistent pattern across all workers |
| **Scanner Schedule** | 2× daily (9:35 + 12:30 ET) | Universe changes slowly; workers run every 15 min |
| **Config** | Pydantic Settings + YAML | Type-safe env vars + human-readable strategy params |
| **Async** | `asyncio` throughout | Non-blocking API calls, streaming, DB queries |

## Tech Stack

- **Python 3.9+** — async/await throughout
- **alpaca-py** — Brokerage & market data API
- **SQLAlchemy 2.0** — Async ORM with Alembic migrations
- **APScheduler** — Cron + interval scheduling for agents
- **Pydantic v2** — Settings & data validation
- **Loguru** — Structured logging
- **FastAPI** — REST API + WebSocket (Phase 6)
- **React + Tailwind** — Dashboard (Phase 6)

## License

Private — for personal use.

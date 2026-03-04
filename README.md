# Premium Trader — Multi-Agent Options Trading System

A multi-agent architecture for automated options income strategies (Covered Calls, Cash Secured Puts, The Wheel) built on Alpaca's brokerage API with a broker-agnostic abstraction layer.

## Architecture

```
                    ┌─────────────────────────────┐
                    │      Market Data Layer       │
                    │  Alpaca · Options Chain · IV │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   Broker Abstraction Layer   │
                    │   (core/broker.py — ABC)     │
                    │   └─ AlpacaBroker impl       │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │          Lead Agent (Orchestrator)       │
              │  Assignment · Performance · Risk Mgmt   │
              └───┬────────────┬────────────┬──────────┘
                  │            │            │
         ┌───────▼──┐  ┌──────▼───┐  ┌─────▼──────┐
         │ Worker A  │  │ Worker B │  │  Worker C  │
         │ Covered   │  │  Cash    │  │   The      │
         │  Calls    │  │ Secured  │  │  Wheel     │
         │           │  │  Puts    │  │ (CSP→CC)   │
         └───────┬───┘  └────┬─────┘  └─────┬──────┘
                 │           │              │
              ┌──▼───────────▼──────────────▼──┐
              │       Trade Journal Agent       │
              │  Entry/Exit Logging · Context   │
              └──────────────┬─────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │     Performance Logger       │
              │  Metrics · P&L · Sharpe · DD │
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │     SQLite / PostgreSQL      │
              │  Trades · Positions · Perf   │
              │  Journal · Opportunities     │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │   Dashboard     │
                    │    (Phase 6)    │
                    └─────────────────┘
```

## What's Built

### Phase 1 — Data Layer & Alpaca Integration ✅
- Full Alpaca API integration via `alpaca-py` (options chains, orders, historical data, quotes)
- Real-time market data streaming with WebSocket support
- IV rank calculation (current IV vs 52-week percentile)
- Options chain analyzer with filtering, scoring, and optimal strike selection
- Rate limiting and async API methods throughout

### Phase 2 — Broker Abstraction Layer ✅
- Abstract `Broker` interface (`core/broker.py`) decouples all trading logic from Alpaca
- `AlpacaBroker` implementation (`services/alpaca_broker.py`) with full API coverage
- All agents and data modules use dependency injection — swap brokers without touching agent code

### Phase 3 — Database & Trade Journal Agent ✅
- SQLAlchemy 2.0 async models: `Trade`, `ActivePosition`, `AgentPerformance`, `ScannerOpportunity`, `JournalEntry`
- Alembic migrations for schema management
- `TradeJournalAgent` — records every trade with full market context (IV rank, VIX, support distances, strategy parameters)
- `PerformanceLogger` — async metrics engine (win rate, Sharpe ratio, max drawdown, premium tracking)
- Async SQLAlchemy session management via `core/database.py`

### Phases 4–6 — Upcoming
- **Phase 4**: Worker agents fully wired (CSP → CC → Wheel end-to-end on paper)
- **Phase 5**: Lead Agent intelligence (dynamic assignment, performance-based rotation, risk throttling)
- **Phase 6**: FastAPI backend + React dashboard with real-time WebSocket updates

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

watchlists:
  high_iv_stocks:
    - AAPL
    - MSFT
    - NVDA
    - AMD
    - TSLA
```

## Project Structure

```
premium-trader/
├── agents/                    # Multi-agent system
│   ├── base_agent.py          # Abstract lifecycle: scan → evaluate → execute → manage
│   ├── lead_agent.py          # Portfolio orchestrator & assignment engine
│   ├── worker_cc.py           # Worker A: Covered Calls
│   ├── worker_csp.py          # Worker B: Cash Secured Puts
│   ├── worker_wheel.py        # Worker C: The Wheel (CSP ↔ CC state machine)
│   └── trade_journal.py       # Trade Journal Agent — context-rich trade logging
│
├── core/                      # Core abstractions & business logic
│   ├── broker.py              # Abstract Broker interface (ABC)
│   ├── database.py            # Async SQLAlchemy session factory
│   ├── portfolio.py           # Portfolio state management
│   └── risk_manager.py        # Position sizing & drawdown limits
│
├── data/                      # Market data layer
│   ├── market_feed.py         # Real-time quotes, IV rank, support/resistance
│   └── options_chain.py       # Options chain analysis, filtering & scoring
│
├── models/                    # SQLAlchemy ORM models
│   ├── trade.py               # Trade execution records
│   ├── position.py            # Active option positions
│   ├── performance.py         # Agent performance snapshots
│   ├── opportunity.py         # Scanner-detected opportunities
│   └── journal_entry.py       # Detailed trade journal entries
│
├── services/                  # External service integrations
│   ├── alpaca_broker.py       # AlpacaBroker — Broker interface implementation
│   ├── alpaca_client.py       # Low-level Alpaca API wrapper
│   └── logger_service.py      # Performance logger (metrics, P&L, Sharpe)
│
├── config/                    # Configuration
│   ├── settings.py            # Pydantic settings (loads from .env)
│   └── strategies.yaml        # Strategy parameters & watchlists
│
├── alembic/                   # Database migrations
│   ├── env.py                 # Alembic environment config
│   └── versions/              # Migration scripts
│
├── api/                       # FastAPI backend (Phase 6)
├── dashboard/                 # React frontend (Phase 6)
├── scripts/
│   └── init_db.py             # Database initialization via Alembic
├── tests/
│   └── test_alpaca.py         # Integration tests
├── notebooks/                 # Jupyter research notebooks
│
├── main.py                    # Application entry point
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
| **Database** | SQLite (dev) / PostgreSQL (prod) | SQLite for zero-config dev, Postgres for production |
| **ORM** | SQLAlchemy 2.0 async | Full async support, Alembic migrations |
| **Agent Lifecycle** | `scan → evaluate → execute → manage` | Consistent pattern across all workers |
| **Config** | Pydantic Settings + YAML | Type-safe env vars + human-readable strategy params |
| **Async** | `asyncio` throughout | Non-blocking API calls, streaming, DB queries |

## Tech Stack

- **Python 3.9+** — async/await throughout
- **alpaca-py** — Brokerage & market data API
- **SQLAlchemy 2.0** — Async ORM with Alembic migrations
- **Pydantic v2** — Settings & data validation
- **FastAPI** — REST API + WebSocket (Phase 6)
- **Loguru** — Structured logging
- **React + Tailwind** — Dashboard (Phase 6)

## License

Private — for personal use.

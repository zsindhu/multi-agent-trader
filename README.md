# Premium Trader — Multi-Agent Options Trading System

A multi-agent architecture for automated options income strategies (Covered Calls, Cash Secured Puts, The Wheel) built on Alpaca's brokerage API.

## Architecture

```
Market Data (Alpaca / Options Chain / IV Feed)
        │
   Lead Agent (Portfolio Manager)
   ┌────┼────┐
   │    │    │
  W-A  W-B  W-C
  CC   CSP  Wheel
   │    │    │
   └────┼────┘
        │
  Performance Logger
        │
    Dashboard (You)
```

## Quick Start

```bash
# 1. Clone & setup
cp .env.example .env  # Add your Alpaca API keys
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Initialize database
python scripts/init_db.py

# 3. Run in paper trading mode
python main.py --mode paper

# 4. Launch dashboard
cd dashboard && npm install && npm run dev
```

## Project Structure

```
premium-trader/
├── agents/              # Agent implementations
│   ├── base_agent.py    # Abstract base for all agents
│   ├── lead_agent.py    # Portfolio manager / orchestrator
│   ├── worker_cc.py     # Worker A: Covered Calls
│   ├── worker_csp.py    # Worker B: Cash Secured Puts
│   └── worker_wheel.py  # Worker C: The Wheel (state machine)
├── core/                # Core business logic
│   ├── portfolio.py     # Portfolio state management
│   ├── risk_manager.py  # Position sizing, drawdown limits
│   └── strategy.py      # Strategy evaluation engine
├── data/                # Data layer
│   ├── market_feed.py   # Real-time market data client
│   ├── options_chain.py # Options chain & IV data
│   └── cache.py         # Redis/local caching layer
├── models/              # Database models (SQLAlchemy)
│   ├── trade.py         # Trade records
│   ├── position.py      # Open positions
│   └── performance.py   # Agent performance metrics
├── services/            # External integrations
│   ├── alpaca_client.py # Alpaca brokerage API wrapper
│   ├── logger_service.py# Performance logger
│   └── notifier.py      # Alerts (Discord/email)
├── api/                 # FastAPI backend
│   ├── main.py          # API entry point
│   └── routes/          # Route handlers
├── dashboard/           # React frontend
├── config/              # Config files
│   ├── settings.py      # Pydantic settings
│   └── strategies.yaml  # Strategy parameters
├── scripts/             # Utility scripts
├── tests/               # Test suite
├── notebooks/           # Jupyter research notebooks
├── main.py              # Application entry point
└── .env.example         # Env var template
```

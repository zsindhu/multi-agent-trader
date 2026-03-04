# Cursor AI Prompt — Premium Trader Build Guide

Copy and paste the relevant section into Cursor as you build each phase.

---

## PHASE 1: Data Layer & Alpaca Integration

```
I'm building a multi-agent options trading system called Premium Trader. The project scaffold is already set up — review the full project structure before making changes.

For Phase 1, I need you to fully implement the data layer:

1. **services/alpaca_client.py** — Complete the Alpaca integration:
   - Use alpaca-py (not the deprecated alpaca-trade-api) for all API calls
   - Implement get_options_chain() — fetch full options chain for a symbol using Alpaca's Options API, returning contracts with: symbol, strike, expiration, bid, ask, last, volume, open_interest, implied_volatility, delta, gamma, theta, vega
   - Implement submit_option_order() — submit limit orders for options (sell to open, buy to close)
   - Add get_historical_bars() for price history (used for support/resistance detection)
   - Add error handling and rate limiting
   - All methods that hit the API should be async

2. **data/market_feed.py** — Create a market data service:
   - Real-time quote streaming via Alpaca's websocket
   - IV rank calculation (current IV percentile vs 52-week range)
   - A method to get the current IV rank for a list of symbols
   - Cache recent data in memory (or Redis if available)

3. **data/options_chain.py** — Options chain analyzer:
   - Filter chains by DTE range, delta range, minimum open interest
   - Calculate annualized return on capital for each contract
   - Find optimal strikes based on strategy parameters from config/strategies.yaml
   - Support both calls and puts

Make sure everything works with paper trading. Use the .env.example structure for API keys. Write a quick test in tests/test_alpaca.py that verifies the connection and fetches a quote for AAPL.
```

---

## PHASE 2: Performance Logger & Database

```
Continuing Premium Trader build. Phase 1 (Alpaca data layer) is complete.

For Phase 2, implement the full performance tracking system:

1. **models/trade.py** — Already has the Trade model. Now add:
   - models/position.py — ActivePosition model tracking open option positions with fields: id, agent_name, symbol, option_symbol, contract_type (call/put), strike, expiration, quantity, entry_price, current_price, premium_collected, status (open/closed/assigned/expired), opened_at, closed_at, pnl
   - models/performance.py — AgentPerformance model for daily snapshots: agent_name, date, total_trades, wins, losses, total_premium, realized_pnl, win_rate, avg_return_per_trade

2. **Database setup with Alembic:**
   - Initialize Alembic in the project
   - Create initial migration with all three models
   - Update scripts/init_db.py to use Alembic

3. **services/logger_service.py** — Fully implement:
   - log_trade() — record every trade execution to DB
   - log_position_update() — track position status changes
   - log_cycle() — already stubbed, connect to DB
   - get_agent_metrics() — query DB and compute: win_rate, total_premium_collected, avg_days_held, avg_return_per_trade, sharpe_ratio, max_drawdown per agent
   - get_portfolio_summary() — aggregate across all agents
   - get_trade_history() — paginated trade history with filters

4. **services/notifier.py** — Simple notification service:
   - Discord webhook for trade alerts (trade executed, position closed, risk alert)
   - Format messages with trade details, P&L, and running totals

Use SQLAlchemy async sessions. The Lead Agent will call get_agent_metrics() to decide worker rotations, so make sure the return format is clean.
```

---

## PHASE 3: Worker Agent B (Cash Secured Puts) — First Working Agent

```
Continuing Premium Trader. Phases 1-2 (data layer + logging) are complete.

For Phase 3, fully implement Worker B (Cash Secured Puts) as the first working agent. This is the simplest strategy and will validate the entire pipeline.

Implement agents/worker_csp.py end-to-end:

**scan():**
- For each assigned security, fetch current price and IV rank from data/market_feed.py
- Only consider stocks where IV rank >= min_iv_rank from strategies.yaml
- Check if stock is near a support level (within support_buffer % of 20-day low or a recent swing low)
- Fetch options chain and filter for puts matching: delta near -0.25, DTE between 20-45

**evaluate():**
- For each candidate, calculate:
  - Annualized return on capital (premium / collateral * 365 / DTE)
  - Probability of profit (1 - abs(delta))
  - Distance from current price to strike (as %)
- Score and rank by a weighted composite
- Filter out any where risk_manager.can_sell_put() returns False

**execute():**
- Submit limit orders at the mid price (bid+ask)/2 via alpaca_client
- Log each trade via logger_service.log_trade()
- Return list of executed trades

**manage_positions():**
- Fetch all open CSP positions for this agent from DB
- If premium captured > 70% of max: buy to close (take profit)
- If DTE < 5 and ITM: roll down and out (close + reopen at lower strike, further expiry)
- If assigned: log the assignment event, update position status
- Log all actions via logger_service

Write tests in tests/test_worker_csp.py that mock the Alpaca API and verify:
- scan() filters correctly by IV rank and delta
- evaluate() ranks and scores properly
- manage_positions() triggers close/roll at the right thresholds

After this is working on paper, the same pattern extends to Worker A and C.
```

---

## PHASE 4: Worker A (Covered Calls) + Worker C (The Wheel)

```
Continuing Premium Trader. Worker B (CSPs) is working on paper.

Implement the remaining two workers:

**Worker A — Covered Calls (agents/worker_cc.py):**
- scan(): Check portfolio for positions with 100+ shares. For those, fetch options chain for OTM calls at target delta ~0.30, DTE 20-45, IV rank >= 30
- evaluate(): Rank by annualized premium yield, downside protection (distance OTM), and IV rank
- execute(): Sell to open call contracts at mid price
- manage_positions(): Buy to close if >80% profit captured. Roll up and out if stock approaches strike with >5 DTE remaining. Close if DTE < 3

**Worker C — The Wheel (agents/worker_wheel.py):**
This is a state machine combining Workers A and B. Each assigned symbol tracks its own state:
- SELLING_PUTS: Behave like Worker B (sell CSPs)
- ASSIGNED: Detected via Alpaca position check — shares appeared, transition to SELLING_CALLS
- SELLING_CALLS: Behave like Worker A (sell CCs against assigned shares)
- CALLED_AWAY: Detected when shares disappear — log full cycle metrics, transition to SELLING_PUTS

Key additions for the Wheel:
- Track cumulative cost basis reduction per symbol across the full cycle
- Log full wheel cycle return (total premium collected / original capital deployed)
- wheel_states and cost_basis should persist to DB (add a WheelState model)

Both workers should follow the exact same lifecycle pattern as Worker B: scan -> evaluate -> execute -> manage_positions -> report. Reuse the options chain analysis from data/options_chain.py.
```

---

## PHASE 5: Lead Agent Intelligence

```
Continuing Premium Trader. All three workers are operational on paper.

Fully implement the Lead Agent (agents/lead_agent.py) as the orchestrator:

**_update_assignments():**
- Fetch the watchlist from strategies.yaml
- For each symbol, get IV rank from market_feed
- Assignment rules:
  - IV rank > 40 + we hold shares → assign to Worker A (covered calls)
  - IV rank > 30 + stock near support + we have cash → assign to Worker B (CSPs)
  - IV rank > 25 + stock is a good wheel candidate (liquid, $20-$500 range) → assign to Worker C
  - A symbol can only be assigned to ONE worker at a time
- Log all assignment changes

**_evaluate_worker_performance():**
- Pull metrics from logger_service.get_agent_metrics() for each worker
- If a worker's win rate drops below 50% over last 20 trades: reduce its max_positions by 1
- If a worker's annualized return > 20%: increase max_positions by 1 (up to config max)
- If a worker has 3 consecutive losses: pause it for 1 cycle and alert via notifier

**run_cycle() enhancements:**
- Before running workers, sync portfolio state from Alpaca (cash, positions, buying power)
- After workers run, compute aggregate P&L and log to performance table
- If total portfolio drawdown > 5%: switch all workers to "conservative" mode (tighter delta targets, fewer positions)
- End of day: generate daily summary and send via notifier

Also implement core/strategy.py:
- Load strategy parameters from strategies.yaml
- Provide a method to get adjusted parameters based on market regime (high vol = tighter deltas, low vol = wider deltas)
- Simple regime detection: VIX > 25 = high vol, VIX < 15 = low vol
```

---

## PHASE 6: FastAPI Backend + Dashboard

```
Final phase of Premium Trader. All agents and orchestration working on paper.

Build the API and dashboard:

**api/main.py — FastAPI backend:**
- WebSocket endpoint /ws for real-time portfolio updates
- REST endpoints:
  - GET /portfolio — current portfolio state (positions, cash, P&L)
  - GET /agents — status of all agents (active, last_run, assigned securities)
  - GET /agents/{name}/metrics — detailed performance for one agent
  - GET /trades — paginated trade history with filters (agent, symbol, date range)
  - GET /performance/daily — daily P&L chart data
  - POST /agents/{name}/toggle — activate/deactivate a worker
  - POST /settings — update strategy parameters at runtime
- CORS enabled for localhost dev
- Serve at port 8000

**dashboard/ — React frontend:**
- Use Vite + React + Tailwind CSS
- Components:
  - PortfolioSummary: total equity, cash, P&L, premium collected
  - AgentCards: one card per worker showing status, assigned stocks, win rate, last trade
  - TradeLog: sortable/filterable table of recent trades
  - PerformanceChart: line chart of daily portfolio value over time (use Recharts)
  - RiskGauge: visual indicator of current drawdown vs limit
- Real-time updates via WebSocket connection to /ws
- Dark theme matching the architecture diagram style (dark navy #0a0f1e background, amber/indigo/emerald/pink accent colors for each agent)
- Responsive layout

The dashboard should feel like the architecture diagram I built — same color scheme, same typography (DM Mono + Syne), same dark aesthetic.
```

---

## Tips for Cursor

- **Always tell Cursor to review existing files first** before making changes — it needs the context of what's already built.
- **Reference specific files** by path (e.g., "look at agents/base_agent.py for the lifecycle pattern").
- **Build incrementally** — don't ask for everything at once. One phase at a time, test before moving on.
- **If Cursor hallucinates an API**: tell it to check Alpaca's latest docs at https://docs.alpaca.markets
- **For the dashboard**: reference the architecture React component you already built for the color scheme and fonts.

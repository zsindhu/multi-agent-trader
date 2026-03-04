# Architecture Decision Records (ADR)

## ADR-001: Broker Abstraction Layer

**Status:** Accepted  
**Date:** 2025-01

**Context:** The system initially used Alpaca directly throughout the codebase. To support future broker integrations and improve testability, we introduced an abstract `Broker` interface.

**Decision:** All agents and data modules depend on `core/broker.py` (ABC). The Alpaca implementation lives in `services/alpaca_broker.py`. No agent imports alpaca directly.

**Consequences:** Easy to add new brokers (e.g., IBKR, TD Ameritrade) by implementing the `Broker` interface. All existing code remains broker-agnostic.

---

## ADR-002: Dynamic Universe Discovery

**Status:** Accepted  
**Date:** 2025-02

**Context:** Static symbol lists don't adapt to market conditions and miss opportunities.

**Decision:** The Scanner Agent queries the broker for all tradable, optionable assets, applies fast pre-filters (volume, price, OI), and performs full analysis only on survivors. Config lives in `scanner_universe.yaml`.

**Consequences:** The system discovers opportunities dynamically. ETFs are handled alongside stocks with scoring adjustments.

---

## ADR-003: VIX Regime Detection

**Status:** Accepted  
**Date:** 2025-03

**Context:** Strategy parameters should adapt to market volatility conditions.

**Decision:** `core/strategy.py` fetches VIX proxy levels and classifies market regime (high_vol/normal/low_vol). The Lead Agent applies regime-adjusted parameters (delta targets, max positions) to workers each cycle.

**Consequences:** Workers automatically tighten positions in high-vol and loosen in low-vol without manual intervention.

---

## ADR-004: Wheel State Persistence

**Status:** Accepted  
**Date:** 2025-03

**Context:** The Wheel strategy maintains per-symbol state (selling_puts → assigned → selling_calls → called_away). This state was lost on restart.

**Decision:** Added `models/wheel_state.py` (WheelStateRecord) to persist wheel state to the database. The WheelWorker loads states from DB on first scan and saves on every state transition.

**Consequences:** Wheel state survives restarts. Cost basis tracking and cycle counts are preserved.

---

## ADR-005: Discord Notifications

**Status:** Accepted  
**Date:** 2025-03

**Context:** Operators need real-time awareness of trades, risk events, and daily performance.

**Decision:** `services/notifier.py` sends Discord webhook notifications for trade alerts, risk warnings, cycle summaries, and daily summaries. If no webhook URL is configured, it logs but doesn't crash.

**Consequences:** Non-intrusive notification system. Configurable via `DISCORD_WEBHOOK_URL` env var.

---

## ADR-006: Backtesting Engine Architecture

**Status:** Accepted  
**Date:** 2025-03

**Context:** Need to validate strategy parameters against historical data before deploying to live markets. Must support any agent type, parameter overrides, and comparison mode.

**Decision:** `services/backtester.py` implements a three-layer architecture:
1. **BacktestBroker** — A mock `Broker` implementation that serves cached historical bars and generates synthetic options chains with realistic greeks. Caches data locally in `data/backtest_cache/` as pickle files.
2. **BacktestEngine** — Replay loop that steps through trading days, running the agent's full lifecycle (`scan → evaluate → execute → manage_positions`) against reconstructed market data. Handles option expiration, assignment (ITM puts → shares), and covered call assignment.
3. **BacktestResult** — Comprehensive stats: equity curve, trade log, summary (Sharpe, Sortino, max drawdown, win rate, profit factor), per-symbol breakdown, and monthly returns.

CLI via `scripts/backtest.py` supports single runs, parameter overrides, `--compare` mode, and JSON export.

**Consequences:** Any agent can be backtested without modifying its code. The `Broker` abstraction makes this possible — agents don't know they're running against simulated data. Synthetic options chains approximate real greeks well enough for strategy validation but aren't suitable for precise P&L projection.

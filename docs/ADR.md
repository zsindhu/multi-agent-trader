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

---

## ADR-007: FastAPI Backend with AppState Singleton

**Status:** Accepted  
**Date:** 2025-06

**Context:** The dashboard needs a REST API to access portfolio data, trades, agent status, scanner config, and backtest results. Services like the broker, portfolio, scanner, and strategy manager must be initialized once and shared across all request handlers.

**Decision:** `api/state.py` defines an `AppState` class that holds all shared services (broker, portfolio, scanner, strategy manager, etc.). It's created once during FastAPI's lifespan startup and attached to `request.app.state.app`. Route handlers access it via a `_get_state(request)` helper. Routes are organized into modules under `api/routes/` (portfolio, trades, agents, scanner, backtest, settings) and mounted with prefix-based routing.

**Consequences:** Single initialization, no redundant broker/portfolio instances. Adding new routes is straightforward — create a new module, add it to `api/main.py`. AppState also supports `reinitialize_broker()` for runtime mode switching.

---

## ADR-008: React Dashboard with Vite + Tailwind

**Status:** Accepted  
**Date:** 2025-06

**Context:** Operators need a visual dashboard to monitor portfolio, positions, trades, agent status, and scanner opportunities without reading logs.

**Decision:** Built a React 19 SPA using Vite 7 as the build tool and Tailwind CSS 4 for styling. The dashboard uses React Router for client-side navigation across six pages: Portfolio, Positions, Trade History, Agent Status, Scanner Workshop, and Backtest. Vite's dev server proxies `/api` requests to the FastAPI backend on port 8000. Production builds are served as static files from FastAPI.

**Consequences:** Fast HMR during development. Zero-config proxy avoids CORS issues. The dashboard is a standalone SPA that can be deployed independently or served from the API. Tailwind's utility classes keep styling co-located with components.

---

## ADR-009: Runtime Trading Mode Toggle (Paper ↔ Live)

**Status:** Accepted  
**Date:** 2025-06

**Context:** Users need to switch between paper and live trading without restarting the application. Accidentally switching to live mode with real money must be prevented.

**Decision:** The dashboard header contains an interactive toggle showing the current mode with visual indicators (green pulsing dot for paper, red pulsing dot for live). Switching to live requires a 2-step confirmation modal (risk acknowledgment + typing "CONFIRM"). Switching to paper is immediate. The frontend calls `POST /api/settings/mode` which:
1. Updates `settings.trading_mode` and `settings.alpaca_base_url` in memory
2. Persists changes to the `.env` file
3. Calls `AppState.reinitialize_broker()` which creates a new `AlpacaBroker` and re-wires all dependent services (MarketFeed, OptionsChainAnalyzer, StrategyManager, ScannerAgent, Portfolio)

Global visual cues (red top border, sidebar tints, mode label in footer) reinforce which mode is active across all pages. A `trading-mode-changed` custom event triggers data refreshes in Portfolio and Positions pages.

**Consequences:** Safe mode switching at runtime. The 2-step confirmation prevents accidental live trading. The broker and all dependent services are fully reinitialized — no stale paper-mode references. The `.env` persistence ensures the mode survives API server restarts.

---

## ADR-010: Active Positions Summary Component

**Status:** Accepted  
**Date:** 2025-06

**Context:** The Portfolio page showed aggregate stats (total P&L, premium collected, position counts) but gave no visibility into *which* underlyings had open trades or which agent managed them. Users had to navigate to the Positions page for that detail.

**Decision:** Added a collapsible "Active Positions" section to the Portfolio view, placed between the stat cards and the Market Regime card. Options are grouped by underlying symbol (not per contract). Each row shows: symbol, contract count, managing agent (with color-coded badge — indigo for Covered Calls, emerald for CSP, pink for The Wheel), total premium collected, and unrealized P&L. The Wheel's current phase (selling puts / selling calls) is inferred from contract types and displayed in the badge. The section hides itself when no options are open.

The Portfolio page now fetches both `fetchPortfolioSummary()` and `fetchPortfolio()` in parallel to get the full options array alongside the aggregate stats.

**Consequences:** Glanceable at-a-glance visibility into active positions without leaving the Portfolio view. Compact enough to not clutter the dashboard. The collapse/expand state prevents visual overload when there are many positions.

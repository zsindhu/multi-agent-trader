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

**Decision:** Built a React 19 SPA using Vite 7 as the build tool and Tailwind CSS 4 for styling. The dashboard uses React Router for client-side navigation. Vite's dev server proxies `/api` requests to the FastAPI backend on port 8000. Production builds are served as static files from FastAPI.

The dashboard was initially structured across six pages (Portfolio, Positions, Trade History, Agent Status, Scanner Workshop, Backtest) and later restructured into three focused screens aligned with the human-in-the-loop workflow (see ADR-011):
- **Dashboard** (`/`) — portfolio monitor: stat cards, equity chart, risk gauge, active positions, agent status
- **Trade Desk** (`/trade-desk`) — action screen: scanner results, trade proposals, execution feed
- **Performance** (`/performance`) — review screen: trade history, journal analytics, backtest engine

**Consequences:** Fast HMR during development. Zero-config proxy avoids CORS issues. The three-screen structure maps directly to the operator workflow: monitor → decide → review.

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

## ADR-011: Human-in-the-Loop Trade Proposal System

**Status:** Accepted
**Date:** 2026-03

**Context:** The original Lead Agent ran full autonomous cycles — scanning, evaluating, and executing trades without any user approval step. This made it impossible to review trade logic before real orders were placed, and it created unnecessary risk in paper-to-live transitions.

**Decision:** Introduced a proposal layer between the Lead Agent's analysis and actual order execution. The system now operates in two explicit steps:

1. **Generate** — `POST /api/proposals/generate` triggers the Lead Agent to analyze scanner opportunities, build `TradeProposal` objects with all trade details (strike, expiry, delta, premium, collateral, rationale), and save them with `status="pending"`. No orders are placed.
2. **Approve/Reject/Modify** — The operator reviews proposals on the Trade Desk. Approving a proposal sends the order to the broker; rejecting discards it. Modifications re-fetch the options chain with new parameters before resubmission.

Key implementation details:
- `models/proposal.py` — `TradeProposal` SQLAlchemy model stored in a `proposals` table (indexed on `batch_id` and `status`)
- `api/routes/proposals.py` — 9 endpoints: `GET /pending`, `GET /history`, `GET /batch/{id}`, `POST /generate`, `POST /{id}/approve`, `POST /{id}/reject`, `POST /{id}/modify`, `POST /batch/{id}/approve`, `POST /batch/{id}/reject`
- `AppState.auto_approve = False` — hardcoded default; no code path sets it to `True` without explicit operator action
- Batch operations allow approving or rejecting an entire scan cycle in one click
- `ProposalCard` component surfaces all relevant details: strike, expiry, delta, premium, collateral, annualized return, PoP, max risk, IV rank, rationale string

**Consequences:** Operators have full visibility and control before any capital is deployed. The system can never auto-trade by default. The proposal history table provides a complete audit trail of every considered trade, whether approved, rejected, or modified.

---

## ADR-012: Alpaca SDK Bypass — Direct REST API for Historical Bars

**Status:** Accepted
**Date:** 2026-03

**Context:** `StockHistoricalDataClient.get_stock_bars()` from the `alpaca-py` SDK consistently returns an empty `BarSet` on the free-tier paper account despite valid API credentials. The SDK call returns HTTP 200 but deserializes to an empty result. The same credentials work correctly against the raw REST endpoint (`https://data.alpaca.markets/v2`).

Diagnosis was performed via `scripts/diagnose_bars.py` (5-test matrix: baseline SDK, IEX feed, TZ-aware datetime, IEX+TZ, raw httpx). Tests A–C2 all FAIL (empty BarSet); Test D (raw httpx) PASS — confirming the issue is SDK-level deserialization, not authentication or data availability.

**Decision:** Replace both `get_historical_bars()` and `get_historical_bars_batch()` in `services/alpaca_broker.py` with direct `httpx.AsyncClient` calls:

- Single-symbol: `GET /v2/stocks/{symbol}/bars?timeframe=1Day&start=...`
- Multi-symbol: `GET /v2/stocks/bars?symbols=SPY,QQQ,...&timeframe=1Day&start=...`
- Auth via `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers
- Pagination via `next_page_token` in response body
- Compact bar format (`c/h/l/o/t/v/vw`) normalized via shared `_parse_bar()` helper

The SDK is still used for order placement, account queries, and options chain data — only historical bar methods are bypassed.

**Consequences:** Historical bar fetching works on free-tier accounts. The bypass is isolated to two methods in `AlpacaBroker`. If the SDK is fixed in a future release, reverting is a two-method change. `scripts/diagnose_bars.py` is retained as a regression test for future SDK upgrades.

---

## ADR-010: Active Positions Summary Component

**Status:** Accepted  
**Date:** 2025-06

**Context:** The Portfolio page showed aggregate stats (total P&L, premium collected, position counts) but gave no visibility into *which* underlyings had open trades or which agent managed them. Users had to navigate to the Positions page for that detail.

**Decision:** Added a collapsible "Active Positions" section to the Portfolio view, placed between the stat cards and the Market Regime card. Options are grouped by underlying symbol (not per contract). Each row shows: symbol, contract count, managing agent (with color-coded badge — indigo for Covered Calls, emerald for CSP, pink for The Wheel), total premium collected, and unrealized P&L. The Wheel's current phase (selling puts / selling calls) is inferred from contract types and displayed in the badge. The section hides itself when no options are open.

The Portfolio page now fetches both `fetchPortfolioSummary()` and `fetchPortfolio()` in parallel to get the full options array alongside the aggregate stats.

**Consequences:** Glanceable at-a-glance visibility into active positions without leaving the Portfolio view. Compact enough to not clutter the dashboard. The collapse/expand state prevents visual overload when there are many positions.

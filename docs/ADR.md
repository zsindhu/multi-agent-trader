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

## ADR-013: Autonomous Execution Architecture (Agents Service)

**Status:** Accepted
**Date:** 2026-03

**Context:** The proposal system (ADR-011) was designed for human-in-the-loop review, but the intended production behavior is fully autonomous execution — agents should scan, evaluate, and trade without operator intervention every cycle.

**Decision:** Retained two separate services in `docker-compose.yml`:

1. **`agents` service** — runs `main.py` on a scheduler (APScheduler), calling `lead.run_cycle()` → workers → `broker.submit_option_order()` directly. This service is fully autonomous: no proposal layer, no approval gate.
2. **`app` service** — runs FastAPI + the React dashboard. Serves the proposal/approve workflow for manual overrides and provides the monitoring UI.

The `agents` service uses `buying_power` from the Alpaca account as its capital signal, falling back to `cash` when `buying_power` is zero (common when all cash is committed as options collateral). The risk manager gates every trade on collateral availability.

**Consequences:** The system executes trades automatically. The dashboard is a monitoring and override tool, not an execution gate. Operators who want human-in-the-loop control can use the `app`-side proposal API, but the `agents` service will continue executing in parallel.

---

## ADR-014: ExecutionLog — Trade Reasoning Audit Trail

**Status:** Accepted
**Date:** 2026-03

**Context:** Trades were executing autonomously but there was no record of *why* — what delta, DTE, IV rank, or annualized return triggered the decision. Post-hoc analysis was impossible. When the dashboard showed no positions, there was no way to diagnose whether the agents were reasoning correctly.

**Decision:** Added `models/execution_log.py` — a new `execution_logs` table that every worker writes to immediately after a successful order submission. Each row captures:

- **Decision inputs:** `delta`, `dte`, `iv_rank_at_entry`, `scanner_score`, `stock_price_at_entry`, `probability_of_profit`, `annualized_return`
- **Trade details:** `symbol`, `option_symbol`, `action`, `contract_type`, `strike`, `expiration`, `premium`, `collateral_required`, `break_even_price`
- **Plain-English rationale:** A human-readable `rationale` string built by static methods on `BaseAgent` (`build_csp_rationale`, `build_cc_rationale`, `build_wheel_rationale`) — e.g. *"Sold GDX $80P expiring Apr 10 — IV rank 72 (elevated), delta -0.28 gives 72% PoP, annualized return 41.3% on $8,000 collateral. Break-even $78.65 (1.7% below current $80.02)."*
- **Order outcome:** `order_id`, `order_status`, `fill_price`

The dashboard "Recent Activity" feed (`GET /api/executions/latest`) surfaces the last 15 entries with expandable detail panels.

**Consequences:** Every autonomous trade decision is auditable. Operators can review exactly what the agent saw and why it traded. The rationale strings are designed to be readable without domain expertise.

---

## ADR-015: Performance Metrics — Open vs Closed Trade Distinction

**Status:** Accepted
**Date:** 2026-03

**Context:** `get_agent_metrics()` in `services/logger_service.py` originally filtered on `Trade.closed_at IS NOT NULL`, meaning metrics were empty until positions expired or were closed. With 30–45 DTE options, the dashboard showed zero trades for weeks after the system started.

**Decision:** Split metrics into two tiers:

1. **Entry-based metrics** (all trades, open + closed): `total_trades`, `total_premium_collected` — available immediately when a trade is opened
2. **Realized metrics** (closed trades only): `wins`, `losses`, `win_rate`, `total_pnl`, `avg_days_held`, `sharpe_ratio`, `max_drawdown` — populated as positions close

`log_trade()` now sets `closed_at = datetime.utcnow()` automatically when `trade_type` is `buy_to_close`, `assignment`, `expired`, or `wheel_cycle_complete`, so close events are correctly timestamped without requiring changes to worker code.

**Consequences:** The dashboard shows meaningful data (trade count, premium) from day one. Win rate and P&L populate progressively as positions close. No schema change required — `closed_at` column already existed in the `trades` table.

---

## ADR-016: Intelligence Services — Data Producers for Contextual Decisions

**Status:** Accepted
**Date:** 2026-03

**Context:** The Lead Agent made assignment and position management decisions using only IV rank and VIX regime. It had no awareness of upcoming earnings events, sector rotation, macro breadth, credit stress, historical performance patterns, or qualitative news signals. These blind spots led to situations like selling puts before earnings (high gap risk) and opening new positions in clearly deteriorating market conditions.

**Decision:** Added four autonomous data-producer services that compute and persist context to the database on a schedule. No agent logic was put in these services — they are pure data producers:

1. **`MarketRegimeService`** (`services/market_regime.py`) — computes a multi-signal regime snapshot each cycle: VIX proxy level + direction, market breadth (% of scanner universe above 50-day MA), SPY trend (20/50-day MA cross), sector rotation (5-day returns across 11 SPDR ETFs), and credit stress (HYG vs TLT divergence). Classifies regime into: `risk_on`, `neutral`, `risk_off`, `crisis`. Stored in `regime_snapshots` table.

2. **`EarningsCalendarService`** (`services/earnings_calendar.py`) — fetches earnings dates from Finnhub for all symbols in the scanner universe. Flags symbols with earnings within 7 days as `high_risk`. Stored in `earnings_events` table. Used by `_apply_intelligence_checks()` to prevent selling puts before announcements.

3. **`PerformanceAnalystService`** (`services/performance_analyst.py`) — queries the `trades` and `journal_entries` tables and computes 7 analytical lenses: overall win rate, strategy breakdown, optimal delta range, regime correlation, symbol-level scorecard, open position health (flags deeply underwater or ITM near-expiry), and rule-based recommendations. Stores results as JSON blobs in `performance_insights` table.

4. **`NewsFeedService`** (`services/news_feed.py`) — fetches Finnhub general + company-specific headlines. Deduplicates by headline text. Auto-prunes entries older than 48 hours. Stored in `news_headlines` table.

All four services are initialized in `AppState` and `main.py`. Four new intelligence API routes were added under `/api/intelligence/`. The dashboard's DashboardPage shows the regime badge, earnings warnings, recommendations, and top headlines.

**Consequences:** The system has rich context before making decisions. Earnings avoidance is automatic. Regime awareness allows proactive position-size reduction before conditions deteriorate. Performance analytics surface optimal parameters from live trading data. News provides qualitative color for unexpected moves.

---

## ADR-017: LLM-Powered Lead Agent — Claude as the Reasoning Engine

**Status:** Accepted
**Date:** 2026-03

**Context:** The Lead Agent's decision logic was entirely rule-based: if IV rank > 30 and near support → assign to CSP worker. This worked for simple cases but couldn't reason about tradeoffs. It couldn't weigh an earnings event against an attractive IV rank, notice that a losing streak in one strategy should change position sizing, or synthesize regime + breadth + sector rotation + news into a coherent view. The intelligence services (ADR-016) produced rich context but nothing consumed it holistically.

**Decision:** Replaced the Lead Agent's core decision loop with Claude (`claude-sonnet-4-6`) via the Anthropic API's tool use (function calling). The original rule-based logic remains intact as `_rule_based_cycle()` and activates automatically when no API key is configured.

**Architecture:**

```
LLMService → Claude API (multi-turn tool-use loop, max 10 turns)
    ↑ tool results
LeadAgent._execute_tool() → regime_service, scanner, portfolio, earnings, news, perf_service
    ↓ JSON action list
LeadAgent._execute_action() → workers (targeted open/close/roll, or pause/resume)
```

**Tool definitions** (9 tools Claude can call per cycle):
- `get_regime` — current macro regime (VIX, breadth, SPY trend, sectors, credit stress)
- `get_regime_detail` — drill into a specific metric
- `get_scanner_top` — top N scored opportunities from the Scanner
- `get_open_positions` — all open options with P&L and DTE
- `get_position_detail` / `get_symbol_history` — trading history for a symbol
- `get_performance` — overall win rate, strategy breakdown, delta analysis
- `get_earnings_upcoming` — earnings within N days
- `get_news` — recent headlines (market-wide or symbol-specific)

**Action dispatch** — Claude outputs a structured JSON block at the end of its reasoning. `_execute_action()` validates and dispatches each action:
- `close` / `roll` — finds the owning worker via `_find_worker_for_position()` and calls the new public `close_position()` / `roll_position()` methods added to all three workers
- `open_csp` / `open_cc` / `open_wheel` — sets `worker.assigned_securities = [symbol]` then calls targeted `scan → evaluate → execute` (not `run_cycle()`, which would re-run position management)
- `pause_worker` / `resume_worker` — toggles `is_active` on the named worker
- `no_action` / `hold` — logs and returns

**Hard constraints** enforced in `_validate_new_position()` before any open action: buying power ≥ $5,000, worker below `max_positions`, drawdown within limit.

**Claude's reasoning** is persisted to `execution_logs` (agent="Lead-Agent", action="cycle_decision") after every cycle. The dashboard "Lead Agent Thinking" card surfaces the latest summary + expandable full reasoning text.

**Cost**: ~3,000 input + 800 output tokens per cycle ≈ $0.02/cycle. 26 cycles/market day ≈ $0.52/day at Sonnet 4.6 pricing.

**Consequences:** The Lead Agent can reason across all available context simultaneously — regime, open positions, performance history, earnings risk, news — and produce nuanced decisions that rule-based logic cannot. The rule-based fallback ensures the system never stops trading if the API is unavailable. Every reasoning step is auditable via the execution log.

---

## ADR-010: Active Positions Summary Component

**Status:** Accepted
**Date:** 2025-06

**Context:** The Portfolio page showed aggregate stats (total P&L, premium collected, position counts) but gave no visibility into *which* underlyings had open trades or which agent managed them. Users had to navigate to the Positions page for that detail.

**Decision:** Added a collapsible "Active Positions" section to the Portfolio view, placed between the stat cards and the Market Regime card. Options are grouped by underlying symbol (not per contract). Each row shows: symbol, contract count, managing agent (with color-coded badge — indigo for Covered Calls, emerald for CSP, pink for The Wheel), total premium collected, and unrealized P&L. The Wheel's current phase (selling puts / selling calls) is inferred from contract types and displayed in the badge. The section hides itself when no options are open.

The Portfolio page now fetches both `fetchPortfolioSummary()` and `fetchPortfolio()` in parallel to get the full options array alongside the aggregate stats.

**Consequences:** Glanceable at-a-glance visibility into active positions without leaving the Portfolio view. Compact enough to not clutter the dashboard. The collapse/expand state prevents visual overload when there are many positions.

---

## ADR-018: Phase C — Intelligence-First Dashboard Redesign

**Status:** Accepted
**Date:** 2026-03

**Context:** The dashboard surfaced portfolio and trade data but gave no visibility into the system's reasoning or market context. Operators could see *what* happened but not *why*. The intelligence services (ADR-016) and LLM Lead Agent (ADR-017) produced rich data — regime snapshots, earnings risk, performance analytics, Claude's cycle reasoning — but very little of it reached the UI. Breadth was also permanently showing 100% due to a NULL-handling bug in the regime service.

**Decision:** Redesigned all three dashboard screens to surface the system's intelligence as first-class information. Core changes:

**Bug fix:** `services/market_regime.py` `_get_breadth()` was counting `NULL` `distance_from_50ma` values as "above 50MA" via `(None or 0) >= 0`. Fixed by filtering to non-null records before computing the percentage.

**New components** (8 created, all in `dashboard/src/components/`):
- `SystemStatusBar` — sticky header bar showing connection, mode, market hours (ET), regime badge, VIX, breadth %, and last cycle time. Fetched at the App level and refreshed every 60 seconds.
- `SystemThinking` — AI reasoning card with purple/indigo accent (distinguishes AI-generated content from raw data). Shows latest Lead Agent summary prominently; full reasoning expandable. Empty state for rule-based mode.
- `PositionHealthBar` — 3-zone horizontal gauge showing where current price sits relative to strike and break-even. Green (safe OTM), amber (approaching strike), red (ITM). Uses proportional zones from strike ±10%.
- `ActivityFeed` — color-coded chronological event feed. Border colors encode event type: purple (Lead Agent decisions), emerald (new trades), red (closes/alerts), amber (regime changes). Polls every 15 seconds independently of the 30-second main poll.
- `MarketIntelligence` — two-column card: left = regime detail (breadth bar, SPY trend, credit stress), right = sector rotation ranked list with horizontal bar chart. Upcoming catalysts (earnings ≤7 days) highlight held symbols. Falls back to muted "Phase A services not configured" text.
- `RegimeCorrelationChart` — `React.memo`-wrapped Recharts bar chart of win rate by regime (color-coded: emerald/blue/amber/red). Lazy-loadable.
- `DeltaAnalysisChart` — `React.memo`-wrapped bar chart of win rate by delta bucket with avg return in tooltip. Lazy-loadable.
- `SymbolScorecard` — `React.memo`-wrapped sortable table of per-symbol P&L, win rate, trade count, avg premium. Click any column header to sort; P&L-tinted rows.

**Dashboard page** (`/`): Stat cards updated — "Day P&L" replaces cash, "Open Positions" shows count + mini strategy breakdown (e.g. "2 CSP · 1 CC"). `ActivePositions` enhanced with DTE display, earnings ⚠️ flag, and `PositionHealthBar` per position. Activity feed polls 15s separately. `IntelligenceSection` replaced with `MarketIntelligence`.

**Trade Desk** (`/trade-desk`): Added AI Decision Queue showing the last 3 Lead Agent reasoning entries as expandable cards above the scanner. Scanner table gained two columns: earnings flag (⚠️ if earnings within 14 days) and regime signal (green/red dot). Manual Trade Entry collapsible form added — symbol, strategy, delta slider, DTE slider — queues a note for the Lead Agent on next cycle.

**Performance** (`/performance`): New "Insights" tab (default tab) with lazy-loaded regime correlation + delta analysis charts, symbol scorecard, and What's Working recommendations. The existing Trades/Journal/Backtest tabs are unchanged.

**App-level intelligence**: `App.jsx` now fetches regime and last reasoning timestamp on mount and refreshes every 60 seconds, passing data to `SystemStatusBar` in the header.

**API additions** (`dashboard/src/api.js`): Added `fetchIntelligenceStrategyBreakdown`, `fetchIntelligenceDeltaAnalysis`, `fetchIntelligenceRegimeCorrelation`, `fetchIntelligenceSymbolScorecard`, `fetchIntelligenceRegimeHistory`. No new backend endpoints were needed — all are served by the existing `api/routes/intelligence.py`.

**Consequences:** Operators see regime, VIX, breadth, and last cycle time without navigating anywhere. The "System Assessment" card makes Claude's reasoning visible in plain English on the main screen. Active positions show safety at a glance via the health bar. The Performance Insights tab turns raw performance data into actionable analysis. Every intelligence section degrades gracefully when Phase A/B services aren't configured.

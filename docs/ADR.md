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

---

## ADR-019: Order Reconciliation Service

**Status:** Accepted
**Date:** 2026-04

**Context:** All 21 trades opened by the system showed `status="submitted"` in the database indefinitely. The system never checked whether orders actually filled, at what price, or whether Alpaca rejected them. The LLM was making position management decisions based on stale "submitted" state rather than confirmed fills.

**Decision:** Added `services/order_reconciler.py` — an `OrderReconciler` service that runs at the **start** of every Lead Agent cycle, before portfolio sync and before any LLM calls.

Behavior:
1. Queries `trades` table for all records where `status="submitted"`
2. Calls `broker.get_order(order_id)` for each to fetch real Alpaca status
3. Updates the record: `status` (filled/rejected/cancelled), `price` (fill price), and appends fill details to `notes`
4. Logs warnings on rejections with the reject reason
5. Returns a summary dict `{reconciled, filled, rejected, pending, errors}`

Also detects **position disappearances** via `detect_position_changes()`: compares the set of option symbols in the current portfolio against the previous cycle. Positions that vanished are inferred as expired (if expiry date has passed) or closed externally. Expirations are logged to the trade journal as `expired_worthless`.

Two new methods added to `AlpacaBroker`:
- `get_order(order_id)` — fetches a single order by ID with fill details, reject reason, and timestamps
- `close_option_position(option_symbol)` — calls Alpaca's `close_position` endpoint to submit a market-order close

**Wiring:** `OrderReconciler` initialized in `main.py` and injected into `LeadAgent`. `run_cycle()` calls `reconciler.reconcile()` before `portfolio.sync_from_broker()`.

**Consequences:** The LLM always sees confirmed fill status before making decisions. Rejected orders are surfaced immediately rather than silently persisting as "submitted" forever. Expiration detection closes the journal loop for positions that expire worthless between cycles.

---

## ADR-020: LLM-First Position Management with Emergency Safe Mode

**Status:** Accepted
**Date:** 2026-04

**Context:** Workers had hardcoded `manage_positions()` methods with fixed profit targets (50% for CSP, 80% for CC). These rules preempted the LLM — Claude might decide to let a 55%-profit position run because the regime was favorable, but the worker would close it anyway. "Take profit at 50%" is the wrong rule in many contexts.

**Decision:** The LLM manages all positions. Hardcoded rules are removed from the primary code path and replaced with an emergency-only safe mode.

**LLM path (normal operation):** Claude receives all open positions via `get_open_positions` with P&L, DTE, distance from break-even, and regime context. It decides for each position: hold, close, or roll. Its JSON action block is executed by `_execute_action()` which routes to the appropriate worker's `close_position()` or `roll_position()` method.

**Safe mode (`_safe_mode_cycle()`):** Activates only when the LLM is unavailable (credits depleted, API error, or `is_enabled=False`). Two conditions only:
1. DTE ≤ 2 AND position appears ITM → close to avoid assignment
2. P&L < -300% of premium → circuit breaker close

Safe mode **never opens new positions**. It logs its reasoning to `execution_logs` so operators can see it activated and why.

**Fallback chain in `run_cycle()`:**
1. Reconcile orders
2. Sync portfolio
3. Detect position changes
4. Try LLM → on success, execute actions
5. On LLM exception or credits depleted → safe mode
6. On no API key configured → original rule-based cycle

**Consequences:** Claude drives position management with full context. The 50%/80% profit rules are emergency parameters only. Safe mode prevents runaway losses and assignment risk when the LLM is offline, without pretending to make intelligent decisions.

---

## ADR-021: Comprehensive Trade Journal — Entry Context, Exit Tracking, and Worker Execution Logging

**Status:** Accepted
**Date:** 2026-04

**Context:** The trade journal had three critical gaps:
1. **Zero exits logged** — 21 trades opened, zero exit records. `log_exit()` existed but workers weren't calling it consistently, and when called, it didn't compute P&L or return % automatically.
2. **Missing entry context** — VIX level, 20MA distance, 50MA distance, scanner score, and sector were all NULL in every journal entry. Workers weren't passing this data to `log_entry()`.
3. **Workers not logging to execution_log** — all 548 execution log entries were from "Lead-Agent". The Activity Feed showed only Claude's thinking, not actual trade opens and closes.

**Decision:**

**`log_exit()` overhaul** (`agents/trade_journal.py`): Added `exit_price` parameter. When provided, computes:
- `realized_pnl = (entry_price - exit_price) * qty * 100` (for short options)
- `return_pct = realized_pnl / (strike * 100 * qty) * 100` (return as % of collateral)
- `days_held` — computed from `entry_at` when not provided
- Special case: `exit_reason="expired_worthless"` → full premium is profit

**Entry context enrichment** (all three workers): Before calling `trade_journal.log_entry()`, workers now gather:
- `vix_level` — from `strategy_manager.get_regime_summary()["vix_level"]`
- `scanner_composite_score`, `distance_from_20ma`, `distance_from_50ma` — from `scanner.get_opportunity_by_symbol(symbol)` (new method on `ScannerAgent`, DB-backed with in-memory cache)

`strategy_manager` and `scanner` added as optional constructor params on all three workers. `main.py` passes them.

**Worker execution logging on close**: `_close_position()` in all three workers now writes to `ExecutionLog` with `action="close_profit"` or `"close_stop_loss"`, the close price, exit stock price, exit IV rank, and a P&L rationale string.

**Exit context on close**: `_close_position()` fetches current stock price and IV rank at exit time and passes them to `log_exit()` alongside `exit_price`.

**Consequences:** The journal now captures a complete picture: entry conditions (what the market looked like when we entered) and exit conditions (what changed). Workers appear in the Activity Feed for every trade action. Return % is computed against collateral (correct denominator for options premium selling), not against premium received.

---

## ADR-022: Evolving Knowledge Base — Strategy Playbook and Strategy Insights

**Status:** Accepted
**Date:** 2026-04

**Context:** The LLM starts fresh every cycle. It has no memory of what it discovered in previous cycles beyond raw trade data it must re-query. If it notices "GDX puts lose money in high VIX" on Monday, it must rediscover that Tuesday by re-querying the same journal entries. There was no mechanism for the system to accumulate and act on its own learnings over time.

**Decision:** Two-layer persistent knowledge system, both queryable by the LLM via tools.

**Layer A: Strategy Playbook** (`models/playbook_entry.py`, table `playbook_entries`):
- Qualitative, narrative entries written by the LLM itself during cycles
- Fields: `category` (lesson_learned / parameter_adjustment / symbol_note / regime_observation / strategy_rule / market_insight), `content` (plain English), `source`, `confidence` (0–1), `validated` (confirmed by data), `trades_supporting`, `active`
- The LLM reads the full playbook at the start of every cycle via `get_playbook` tool
- The LLM writes new entries via `add_playbook_entry` tool when it discovers patterns

**Layer B: Strategy Insights** (`models/strategy_insight.py`, table `strategy_insights`):
- Structured, enforceable rules extracted from playbook + trade data
- Fields: `insight_type`, `rule` (human-readable), `parameters` (JSON), `confidence`, `supporting_trades`, `contradicting_trades`, `win_rate_with`, `win_rate_without`
- Intended to be populated and validated by the Performance Analyst (weekly run)
- Higher authority than playbook — validated by actual trade outcomes

**Three new LLM tools** added to `LeadAgent._build_tools()` and `_execute_tool()`:
- `get_playbook(category?, limit?)` — returns active entries, newest first
- `add_playbook_entry(category, content, confidence?)` — creates new entry with `source="lead_agent"`
- `get_strategy_insights(insight_type?, min_confidence?)` — returns validated rules above confidence threshold

**System prompt update**: Instructs Claude to call `get_playbook()` then `get_strategy_insights()` as its first two tool calls every cycle, before checking regime or positions. When closing a losing trade, always add a playbook entry. When discovering a pattern, add it with supporting data.

**Migration:** `alembic/versions/b1c2d3e4f5a6_add_knowledge_base_tables.py` — adds both tables with appropriate indexes.

**Learning flywheel:**
1. LLM writes observations to playbook during trading
2. Performance Analyst (weekly) validates observations against trade journal
3. Validated observations become `strategy_insights` with enforcement confidence
4. LLM reads both every cycle — each cycle builds on accumulated knowledge

**Consequences:** The system accumulates institutional memory across cycles. Early cycles start with an empty playbook; by week 2 the LLM is reading its own prior observations about symbols, regimes, and parameter choices. The Performance Analyst's validation step prevents confirmation bias — insights must be supported by trade data to gain confidence.

---

## ADR-023: Postgres-Compatible Boolean Server Defaults in Migrations

**Status:** Accepted  
**Date:** 2026-04

**Context:** `alembic/versions/b1c2d3e4f5a6_add_knowledge_base_tables.py` used `sa.text('0')` and `sa.text('1')` as `server_default` values for `Boolean` columns (`validated`, `active` in both `playbook_entries` and `strategy_insights`). SQLite accepts bare integer literals for booleans, but Postgres raises `DatatypeMismatch: column "validated" is of type boolean but default expression is of type integer`, causing the app container to crash-loop on `alembic upgrade head`.

**Decision:** Replace `server_default=sa.text('0')` with `server_default=sa.false()` and `server_default=sa.text('1')` with `server_default=sa.true()` on all Boolean columns in the affected migration. `sa.false()` / `sa.true()` emit `FALSE` / `TRUE` in Postgres and `0` / `1` in SQLite — the portable approach. Integer and Float columns with `sa.text('0')` defaults were left unchanged (correct for those types). The migration file was edited in place because it had never successfully run against Postgres, so there was no production state to preserve.

**Rule going forward:** All Boolean columns in Alembic migrations must use `sa.false()` / `sa.true()` for server defaults, never `sa.text('0')` / `sa.text('1')` or bare integer literals.

**Consequences:** Migration chain is intact (revision IDs unchanged). The app container can now run `alembic upgrade head` cleanly against Postgres.

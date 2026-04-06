"""
Lead Agent — Portfolio Manager & Orchestrator.

Monitors portfolio health, assigns securities to workers based on IV rank
and strategy fit, enforces risk limits, and coordinates run cycles.

Now powered by the Scanner Agent for dynamic symbol selection instead of
a static watchlist.  Falls back to strategies.yaml watchlist if no scan
results are available yet.

Integrates:
- StrategyManager for VIX-based regime detection and parameter adjustment
- Notifier for Discord webhook alerts on trades, risk events, daily summary

Assignment Rules:
- IV rank > 40 + we hold shares → Covered Calls
- IV rank > 30 + stock near support + we have cash → Cash Secured Puts
- IV rank > 25 + good wheel candidate (liquid, $20-$500 range) → The Wheel
- A symbol can only be assigned to ONE worker at a time
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

import yaml
from loguru import logger

from agents.base_agent import BaseAgent
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.strategy import StrategyManager
from core.database import AsyncSessionLocal
from data.market_feed import MarketFeed
from models.execution_log import ExecutionLog
from models.proposal import TradeProposal
from services.logger_service import PerformanceLogger
from services.notifier import Notifier
from config.settings import settings

if TYPE_CHECKING:
    from agents.scanner import ScannerAgent
    from agents.trade_journal import TradeJournalAgent
    from services.llm_service import LLMService
    from services.market_regime import MarketRegimeService
    from services.earnings_calendar import EarningsCalendarService
    from services.performance_analyst import PerformanceAnalystService
    from services.news_feed import NewsFeedService
    from services.order_reconciler import OrderReconciler


def _load_fallback_watchlist() -> list[str]:
    """Load the static watchlist from strategies.yaml (fallback only)."""
    try:
        with open("config/strategies.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("watchlists", {}).get("high_iv_stocks", [])
    except FileNotFoundError:
        return []


class LeadAgent:
    """
    Lead Agent — Orchestrates workers, assigns securities, monitors performance.

    Uses ScannerAgent.get_top_opportunities() for dynamic symbol selection.
    Falls back to the static watchlist in strategies.yaml if no scan data.

    Integrates StrategyManager for VIX regime detection and Notifier for
    Discord alerts.
    """

    def __init__(
        self,
        workers: list[BaseAgent],
        risk_manager: RiskManager = None,
        performance_logger: PerformanceLogger = None,
        broker: Broker = None,
        portfolio: Portfolio = None,
        market_feed: MarketFeed = None,
        scanner: Optional["ScannerAgent"] = None,
        strategy_manager: Optional[StrategyManager] = None,
        notifier: Optional[Notifier] = None,
        # Phase B — LLM + intelligence services
        llm_service: Optional["LLMService"] = None,
        regime_service: Optional["MarketRegimeService"] = None,
        earnings_service: Optional["EarningsCalendarService"] = None,
        performance_service: Optional["PerformanceAnalystService"] = None,
        news_service: Optional["NewsFeedService"] = None,
        trade_journal: Optional["TradeJournalAgent"] = None,
        # Phase C — Order reconciliation
        order_reconciler: Optional["OrderReconciler"] = None,
    ):
        self.workers = {w.name: w for w in workers}
        self.risk_manager = risk_manager
        self.performance_logger = performance_logger
        self.broker = broker
        self.portfolio = portfolio
        self.market_feed = market_feed
        self.scanner = scanner
        self.strategy_manager = strategy_manager
        self.notifier = notifier

        # Phase B services
        self.llm_service = llm_service
        self.regime_service = regime_service
        self.earnings_service = earnings_service
        self.performance_service = performance_service
        self.news_service = news_service
        self.trade_journal = trade_journal

        # Phase C — Order reconciler
        self.order_reconciler = order_reconciler

        # Fallback watchlist (used only when scanner hasn't produced results)
        self._fallback_watchlist = _load_fallback_watchlist()

        # Track per-worker performance for rotation
        self._consecutive_losses: dict[str, int] = {}
        self._paused_workers: set[str] = set()

    async def run_cycle(self):
        """
        Execute one full orchestration cycle.

        Order:
        1. Reconcile submitted orders (update fills/rejections)
        2. Sync portfolio from broker (now reflects real state)
        3. LLM path: full Claude analysis with playbook + knowledge base
        4. Safe mode fallback: only closes extreme positions if LLM unavailable
        5. Rule-based fallback: only when no LLM key configured at all
        """
        logger.info("[Lead] ═══════════════════════════════════════════")
        logger.info("[Lead] Starting orchestration cycle...")

        # Sync worker active state from DB before any decisions
        for worker in self.workers.values():
            try:
                await worker.refresh_active_state()
            except Exception:
                pass

        # Step 1: Reconcile orders FIRST — LLM needs actual fill status
        if self.order_reconciler:
            try:
                reconcile_summary = await self.order_reconciler.reconcile()
                logger.info(f"[Lead] Reconciler: {reconcile_summary}")
            except Exception as e:
                logger.warning(f"[Lead] Order reconciliation failed: {e}")

        # Step 2: Sync portfolio from broker (now reflects filled orders)
        if self.portfolio and self.broker:
            await self.portfolio.sync_from_broker(self.broker)

        # Step 3: Detect position changes (expirations, assignments)
        if self.order_reconciler and self.portfolio:
            try:
                current_syms = {opt.option_symbol for opt in self.portfolio.options}
                await self.order_reconciler.detect_position_changes(current_syms)
            except Exception as e:
                logger.warning(f"[Lead] Position change detection failed: {e}")

        # Step 4: LLM path
        if self.llm_service and self.llm_service.is_enabled:
            portfolio_summary = {
                "equity": self.portfolio.equity if self.portfolio else 0,
                "cash": self.portfolio.cash if self.portfolio else 0,
                "buying_power": self.portfolio.buying_power if self.portfolio else 0,
                "open_positions": len(self.portfolio.options) if self.portfolio else 0,
                "trading_mode": settings.trading_mode,
            }
            try:
                decision = await self.llm_service.get_cycle_decision(
                    tools=self._build_tools(),
                    tool_executor=self._execute_tool,
                    portfolio_summary=portfolio_summary,
                    system_prompt=self._build_system_prompt(),
                )
                logger.info(f"[Lead] LLM decision: {decision['summary']}")
                logger.info(f"[Lead] LLM actions: {len(decision['actions'])}")
                await self._store_cycle_reasoning(decision)
                for action in decision["actions"]:
                    try:
                        await self._execute_action(action)
                    except Exception as e:
                        logger.error(f"[Lead] Action failed: {action} — {e}")
                await self._evaluate_worker_performance()
                logger.info("[Lead] ═══════════════════════════════════════════")
                return {}
            except Exception as e:
                logger.error(f"[Lead] LLM cycle failed: {e} — falling back to safe mode")
                return await self._safe_mode_cycle()

        # LLM key configured but service returned is_enabled=False → safe mode
        if self.llm_service and not self.llm_service.is_enabled:
            logger.warning("[Lead] LLM credits depleted — entering safe mode")
            return await self._safe_mode_cycle()

        # Step 5: No LLM key at all → rule-based
        logger.info("[Lead] No LLM configured — using rule-based decisions")
        return await self._rule_based_cycle()

    async def _safe_mode_cycle(self):
        """
        Emergency fallback — ONLY runs when LLM is unavailable.

        Extremely conservative: only acts on 2 truly extreme situations.
        NEVER opens new positions.
        """
        logger.warning("[Lead] SAFE MODE — LLM unavailable, minimal position management only")

        if not self.portfolio:
            return {}

        actions_taken = []

        for opt in list(self.portfolio.options):
            try:
                dte = self._calculate_dte(opt.expiration)
                is_itm = self._is_itm(opt)

                # Condition 1: Expiring within 2 days AND in-the-money → close to avoid assignment
                if dte is not None and dte <= 2 and is_itm:
                    worker = await self._find_worker_for_position(opt.option_symbol)
                    if worker:
                        result = await worker.close_position(
                            opt.option_symbol,
                            reason="Safe mode: expiring ITM in 2 days",
                        )
                        actions_taken.append(result)
                        logger.warning(
                            f"[Lead] Safe mode close: {opt.option_symbol} "
                            f"(DTE={dte}, ITM)"
                        )
                    continue

                # Condition 2: Lost more than 300% of premium → circuit breaker
                if opt.pnl_pct is not None and opt.pnl_pct < -3.0:
                    worker = await self._find_worker_for_position(opt.option_symbol)
                    if worker:
                        result = await worker.close_position(
                            opt.option_symbol,
                            reason="Safe mode: catastrophic loss circuit breaker (>300%)",
                        )
                        actions_taken.append(result)
                        logger.warning(
                            f"[Lead] Safe mode close: {opt.option_symbol} "
                            f"(P&L {opt.pnl_pct:.0%})"
                        )

            except Exception as e:
                logger.error(f"[Lead] Safe mode error for {opt.option_symbol}: {e}")

        await self._store_cycle_reasoning({
            "reasoning": (
                "LLM unavailable — safe mode active. Only closing positions at extreme risk "
                "(expiring ITM within 2 days or catastrophic >300% loss). "
                "No new trades. Add Anthropic API credits to restore full intelligence."
            ),
            "actions": actions_taken,
            "summary": f"SAFE MODE: LLM credits depleted. {len(actions_taken)} emergency closes.",
        })
        return {"safe_mode": True, "actions": actions_taken}

    def _calculate_dte(self, expiration: str) -> Optional[int]:
        """Calculate days to expiration from date string."""
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            return (exp_date - datetime.now()).days
        except (ValueError, TypeError):
            return None

    def _is_itm(self, opt) -> bool:
        """
        Return True if the option appears to be in-the-money.
        For short puts: stock price < strike.
        For short calls: stock price > strike.
        """
        if not self.portfolio or opt.current_price is None:
            return False
        # Use P&L as a proxy: if position has lost significant value it's likely ITM
        # (exact price requires a market feed call — keep safe mode lightweight)
        if opt.pnl_pct is not None and opt.pnl_pct < -0.5:
            return True
        return False

    async def _rule_based_cycle(self):
        """Original rule-based orchestration cycle (fallback when no LLM key)."""

        # Step 1: Sync portfolio from broker
        if self.portfolio and self.broker:
            await self.portfolio.sync_from_broker(self.broker)

        # Step 2: Refresh VIX regime
        if self.strategy_manager:
            await self.strategy_manager.refresh_regime()
            regime_info = self.strategy_manager.get_regime_summary()
            logger.info(
                f"[Lead] Market regime: {regime_info['regime']} "
                f"(VIX≈{regime_info['vix_level']:.1f})"
            )

            # Push regime-adjusted params to workers
            self._apply_regime_params()

        # Step 3: Check portfolio health
        if self.risk_manager:
            risk_ok = await self.risk_manager.check_portfolio_health()
            if not risk_ok:
                logger.warning("[Lead] Risk limits breached — running in conservative mode")
                if self.notifier:
                    drawdown = self.risk_manager.get_current_drawdown()
                    await self.notifier.send_risk_warning(
                        f"Portfolio drawdown at {drawdown:.1%} — conservative mode engaged",
                        details={
                            "drawdown": drawdown,
                            "action": "Conservative mode enabled",
                        },
                    )

        # Step 3b: Intelligence checks (earnings risk, regime override, perf pause)
        await self._apply_intelligence_checks()

        # Step 4: Update assignments based on Scanner + IV + portfolio state
        await self._update_assignments()

        # Step 5: Run all active workers
        results = {}
        for name, worker in self.workers.items():
            if not worker.is_active:
                logger.info(f"[Lead] {name} is inactive — skipping")
                continue
            if name in self._paused_workers:
                logger.info(f"[Lead] {name} is paused — skipping")
                continue

            try:
                logger.info(f"[Lead] Running {name} ({len(worker.assigned_securities)} symbols)")
                results[name] = await worker.run_cycle()
            except Exception as e:
                logger.error(f"[Lead] Worker {name} failed: {e}")
                results[name] = {"error": str(e)}

        # Step 6: Log cycle results
        if self.performance_logger:
            await self.performance_logger.log_cycle(results)

        # Step 7: Send trade notifications
        if self.notifier:
            # Notify on individual trades
            for name, result in results.items():
                if not isinstance(result, dict):
                    continue
                for trade in result.get("new_trades", []):
                    await self.notifier.send_trade_alert({
                        "agent": name,
                        "symbol": trade.get("symbol", "?"),
                        "strategy": trade.get("contract_type", trade.get("wheel_state", "?")),
                        "side": trade.get("side", "sell"),
                        "strike": trade.get("strike", 0),
                        "premium": trade.get("limit_price", 0),
                        "dte": trade.get("dte", 0),
                        "delta": trade.get("delta", 0),
                        "contracts": trade.get("qty", 1),
                        "order_id": trade.get("order_id"),
                    })

            # Cycle summary (only if there was activity)
            await self.notifier.send_cycle_summary(results)

        # Step 8: Evaluate worker performance for rotation
        await self._evaluate_worker_performance()

        # Summary
        total_trades = sum(
            len(r.get("new_trades", [])) for r in results.values() if isinstance(r, dict)
        )
        total_actions = sum(
            len(r.get("position_actions", [])) for r in results.values() if isinstance(r, dict)
        )
        logger.info(
            f"[Lead] Cycle complete: {total_trades} trades, "
            f"{total_actions} position actions across {len(results)} workers"
        )
        logger.info("[Lead] ═══════════════════════════════════════════")

        return results

    # ── LLM MODE METHODS ──────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Return the Lead Agent system prompt for Claude."""
        max_pos = getattr(
            next(iter(self.workers.values()), None),
            "max_positions",
            5,
        )
        max_pct = int(settings.max_position_pct * 100)
        return f"""You are the Lead Agent for Premium Trader, an automated options premium selling system. You are the portfolio manager — you decide what trades to make and when.

## Your Role
You analyze market conditions, evaluate opportunities, manage existing positions, and produce specific trading instructions for your worker agents. You have three workers:
- Cash-Secured-Puts: Sells OTM puts to collect premium. Needs cash as collateral.
- Covered-Calls: Sells OTM calls against shares we hold. Needs 100+ shares.
- Wheel: Runs a full cycle — sells puts, gets assigned shares, sells calls, gets called away, repeats.

## Your Tools
You have access to market regime data, scanner opportunities, open positions, performance analytics, earnings calendar, and news. USE THEM. Always check the regime and open positions before making decisions.

## Hard Constraints (never violate these)
- NEVER sell puts on a symbol with earnings within 7 days
- NEVER deploy more than 80% of available buying power
- NEVER have more than {max_pos} positions open per worker
- NEVER exceed {max_pct}% of equity in a single position
- Paper trading mode — this is real-time simulation with real market data

## Knowledge Base

You have access to two knowledge tools that persist across cycles:

1. **Strategy Playbook** (get_playbook): Your institutional memory. READ THIS EVERY CYCLE before making decisions. It contains lessons from past trades, regime observations, symbol-specific notes, and parameter adjustments. Past you wrote these entries to help future you make better decisions.

2. **Add to Playbook** (add_playbook_entry): When you discover something important — a pattern in the data, a lesson from a losing trade, an observation about a symbol or regime — WRITE IT DOWN. Be specific. Include numbers and trade references. Future cycles will read this.

3. **Strategy Insights** (get_strategy_insights): Validated rules confirmed by trade data. These have higher authority than the playbook — if an insight says "max 2 positions per symbol" with 0.9 confidence, follow it.

Your first two tool calls every cycle should be get_playbook() followed by get_strategy_insights(). Learn from the past before acting on the present.

When you close a losing trade, ALWAYS add a playbook entry explaining what went wrong and what to do differently. When you discover a pattern (e.g., "ETF puts outperform single-stock puts by 15%"), add it with the supporting data.

The playbook is how this system gets smarter over time. Every insight you write makes the next cycle's decisions better.

## Decision Framework
1. First: Read the playbook and strategy insights (get_playbook + get_strategy_insights).
2. Second: Check the market regime. In risk-off or crisis, be very conservative or sit out entirely.
3. Third: Review open positions. Manage what you have before opening anything new.
4. Fourth: Check performance insights. Are we doing well? What's working? What isn't?
5. Fifth: Only then consider new positions from the Scanner results.
6. Sixth: Check earnings before any new position.

## Position Management Rules
- If a position has captured > 70% of max premium: close it (take profit)
- If a position is ITM with < 5 DTE: roll it or close it
- If a position is > 50% underwater: evaluate whether to hold, roll, or close based on context
- If the overall portfolio drawdown exceeds 5%: close the worst performer and pause new entries

CRITICAL: Do NOT wrap your entire response in a code fence (triple backticks). The JSON action block at the end should be in its own ```json fence, but the surrounding analysis text must be plain markdown.

## Output Format
End your response with a JSON action block containing your specific instructions:

```json
[
  {{"action": "close", "symbol": "AMD", "option_symbol": "AMD240425P00140000", "reason": "Earnings in 4 days, position underwater"}},
  {{"action": "hold", "symbol": "SPY", "option_symbol": "SPY240418P00560000", "reason": "18 DTE, only 8% underwater, no catalysts"}},
  {{"action": "open_csp", "symbol": "IWM", "delta": -0.20, "dte_target": 30, "contracts": 1, "reason": "Top Scanner pick, ETF, no earnings risk, risk-on regime"}},
  {{"action": "no_action", "reason": "Risk-off regime, preserving capital until breadth recovers above 50%"}}
]
```

Valid actions: "close", "hold", "roll", "open_csp", "open_cc", "open_wheel", "no_action", "pause_worker", "resume_worker"

Always explain your reasoning before the JSON block. The human operator reads your reasoning on the dashboard.

## Output Formatting Rules

Structure your analysis for a trading dashboard. No preamble — begin with the regime call.

1. **No filler.** Do not open with "Let me analyze..." or "I have everything I need."

2. **Regime Assessment** (`## Regime Assessment`) — one-sentence regime call, then:
   - VIX: level, direction, historical context
   - SPY: position relative to 20MA and 50MA, recent move
   - Breadth: % and participation implications
   - Sector rotation: leaders vs laggards and what the pattern signals
   - News context: key headlines driving the regime
   - Whether the quantitative regime classification is accurate

3. **Portfolio Review** (`## Portfolio Review`) — table with columns: Symbol | Strategy | P&L | vs Strike | DTE | Assessment. Then one paragraph per position needing action.

4. **Risk Summary** (`## Risk Summary`) — concentration issues, total delta, % buying power deployed, drawdown vs limits.

5. **Action Plan** (`## Action Plan`) — numbered list. Each item: symbol + action (CLOSE/HOLD/ROLL/OPEN) + one-sentence reason.

6. **Re-entry Conditions** (`## Re-entry Conditions`) — if recommending no new trades, specify exact VIX level, breadth %, or SPY condition to re-enter.

Use `##` headers for each section. Use tables for position summaries. Bullet lists for signal breakdowns. No emojis. Severity labels: CRITICAL / WARNING / WATCH / OK."""

    def _build_tools(self) -> list[dict]:
        """Build Claude tool definitions from available data services."""
        return [
            {
                "name": "get_regime",
                "description": (
                    "Get the current market regime assessment including VIX level, "
                    "market breadth, sector rotation, SPY trend, and credit stress. "
                    "Call this first to understand the macro environment."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_regime_detail",
                "description": (
                    "Get detailed data for a specific regime metric. Use when you need "
                    "to drill deeper into breadth, sectors, or VIX."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "enum": ["breadth", "sectors", "vix", "credit", "spy_trend"],
                            "description": "Which metric to get detail on",
                        }
                    },
                    "required": ["metric"],
                },
            },
            {
                "name": "get_scanner_top",
                "description": (
                    "Get the top N scored trading opportunities from the Scanner. "
                    "Returns symbols with IV rank, momentum, liquidity, and composite scores."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "n": {
                            "type": "integer",
                            "description": "Number of opportunities (default 10)",
                            "default": 10,
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "get_open_positions",
                "description": (
                    "Get all currently open option positions with health metrics: "
                    "symbol, strategy, entry price, current price, P&L, DTE remaining, "
                    "distance from break-even, profit target progress."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_position_detail",
                "description": (
                    "Get our full trading history and win rate for a specific symbol. "
                    "Shows how we've performed on this name before."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "The underlying symbol",
                        }
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_performance",
                "description": (
                    "Get performance analytics: overall win rate, per-strategy breakdown, "
                    "optimal delta range, regime correlation. Shows what's working."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Lookback period in days (default 30)",
                            "default": 30,
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "get_earnings_upcoming",
                "description": (
                    "Get symbols with earnings announcements in the next N days. "
                    "NEVER sell puts on a stock with earnings within 7 days."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Days ahead to check (default 14)",
                            "default": 14,
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "get_news",
                "description": (
                    "Get recent market headlines for qualitative context. "
                    "Use to understand WHY the market is moving."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Optional: get news for a specific symbol",
                        },
                        "n": {
                            "type": "integer",
                            "description": "Number of headlines (default 10)",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_symbol_history",
                "description": (
                    "Get our trading history and win rate for a specific symbol. "
                    "Shows how we've performed on this name before."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "The symbol to look up",
                        }
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_playbook",
                "description": (
                    "Get the strategy playbook — accumulated lessons, observations, and rules "
                    "from past trading. Read this at the start of every cycle to benefit from "
                    "what we've learned. Contains qualitative insights about symbols, regimes, "
                    "parameters, and strategy performance."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": (
                                "Optional filter: lesson_learned, parameter_adjustment, "
                                "symbol_note, regime_observation, strategy_rule, market_insight"
                            ),
                        },
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": [],
                },
            },
            {
                "name": "add_playbook_entry",
                "description": (
                    "Add a new insight to the strategy playbook. Use this when you discover "
                    "a pattern, learn something from a trade outcome, or want to record a "
                    "decision for future reference. Be specific and include the data that "
                    "supports the insight."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "lesson_learned",
                                "parameter_adjustment",
                                "symbol_note",
                                "regime_observation",
                                "strategy_rule",
                                "market_insight",
                            ],
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "The insight in plain English. Be specific: include numbers, "
                                "dates, and trade references."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": (
                                "How confident are you? 0.0-1.0. "
                                "Use 0.5 for preliminary observations, 0.8+ for patterns "
                                "confirmed by multiple trades."
                            ),
                        },
                    },
                    "required": ["category", "content"],
                },
            },
            {
                "name": "get_strategy_insights",
                "description": (
                    "Get validated strategy rules that constrain trading decisions. "
                    "These are structured rules derived from the playbook and confirmed by "
                    "trade data. Higher confidence = more trades supporting the rule."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "insight_type": {
                            "type": "string",
                            "description": "Optional filter by type",
                        },
                        "min_confidence": {"type": "number", "default": 0.6},
                    },
                    "required": [],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Execute a tool call and return the result."""
        if tool_name == "get_regime":
            if self.regime_service:
                return await self.regime_service.get_latest()
            return {"error": "Regime service not available"}

        if tool_name == "get_regime_detail":
            if self.regime_service:
                return await self.regime_service.get_regime_detail(tool_input["metric"])
            return {"error": "Regime service not available"}

        if tool_name == "get_scanner_top":
            if self.scanner:
                n = tool_input.get("n", 10)
                return {"opportunities": await self.scanner.get_top_opportunities(n=n)}
            return {"error": "Scanner not available"}

        if tool_name == "get_open_positions":
            if self.portfolio:
                await self.portfolio.sync_from_broker(self.broker)
                positions = [
                    {
                        "symbol": opt.symbol,
                        "option_symbol": opt.option_symbol,
                        "contract_type": opt.contract_type,
                        "strike": opt.strike,
                        "expiration": opt.expiration,
                        "quantity": opt.quantity,
                        "entry_price": opt.entry_price,
                        "current_price": opt.current_price,
                        "pnl": opt.pnl,
                        "pnl_pct": opt.pnl_pct,
                        "assigned_to": opt.assigned_to,
                    }
                    for opt in self.portfolio.options
                ]
                return {"positions": positions, "count": len(positions)}
            return {"positions": [], "count": 0}

        if tool_name == "get_position_detail":
            symbol = tool_input.get("symbol", "")
            if self.trade_journal:
                return await self.trade_journal.get_symbol_stats(symbol)
            return {"error": "Trade journal not available"}

        if tool_name == "get_performance":
            if self.performance_service:
                days = tool_input.get("days", 30)
                return await self.performance_service.get_summary(days=days)
            return {"error": "Performance service not available"}

        if tool_name == "get_earnings_upcoming":
            if self.earnings_service:
                days = tool_input.get("days", 14)
                return await self.earnings_service.get_upcoming(days_ahead=days)
            return {"error": "Earnings service not available"}

        if tool_name == "get_news":
            if self.news_service:
                symbol = tool_input.get("symbol")
                n = tool_input.get("n", 10)
                if symbol:
                    return {"headlines": await self.news_service.get_for_symbol(symbol, n=n)}
                return {"headlines": await self.news_service.get_recent(n=n)}
            return {"error": "News service not available"}

        if tool_name == "get_symbol_history":
            symbol = tool_input.get("symbol", "")
            if self.trade_journal:
                return await self.trade_journal.get_symbol_stats(symbol)
            return {"error": "Trade journal not available"}

        if tool_name == "get_playbook":
            from models.playbook_entry import PlaybookEntry
            from sqlalchemy import select as sa_select
            category = tool_input.get("category")
            limit = tool_input.get("limit", 20)
            async with AsyncSessionLocal() as session:
                query = sa_select(PlaybookEntry).where(PlaybookEntry.active == True)
                if category:
                    query = query.where(PlaybookEntry.category == category)
                query = query.order_by(PlaybookEntry.created_at.desc()).limit(limit)
                result = await session.execute(query)
                entries = result.scalars().all()
                return {
                    "entries": [
                        {
                            "id": e.id,
                            "category": e.category,
                            "content": e.content,
                            "confidence": e.confidence,
                            "validated": e.validated,
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in entries
                    ],
                    "total": len(entries),
                }

        if tool_name == "add_playbook_entry":
            from models.playbook_entry import PlaybookEntry
            async with AsyncSessionLocal() as session:
                entry = PlaybookEntry(
                    category=tool_input["category"],
                    content=tool_input["content"],
                    source="lead_agent",
                    confidence=tool_input.get("confidence", 0.5),
                )
                session.add(entry)
                await session.commit()
                await session.refresh(entry)
                logger.info(
                    f"[Lead] Playbook entry added: [{entry.category}] {entry.content[:80]}"
                )
                return {"status": "added", "id": entry.id}

        if tool_name == "get_strategy_insights":
            from models.strategy_insight import StrategyInsight
            from sqlalchemy import select as sa_select
            insight_type = tool_input.get("insight_type")
            min_conf = tool_input.get("min_confidence", 0.6)
            async with AsyncSessionLocal() as session:
                query = (
                    sa_select(StrategyInsight)
                    .where(StrategyInsight.active == True)
                    .where(StrategyInsight.confidence >= min_conf)
                )
                if insight_type:
                    query = query.where(StrategyInsight.insight_type == insight_type)
                query = query.order_by(StrategyInsight.confidence.desc())
                result = await session.execute(query)
                insights = result.scalars().all()
                return {
                    "insights": [
                        {
                            "type": i.insight_type,
                            "rule": i.rule,
                            "confidence": i.confidence,
                            "supporting_trades": i.supporting_trades,
                            "win_rate_with": i.win_rate_with,
                            "win_rate_without": i.win_rate_without,
                        }
                        for i in insights
                    ]
                }

        return {"error": f"Unknown tool: {tool_name}"}

    async def _execute_action(self, action: dict):
        """Validate and execute a single action from Claude's decision."""
        action_type = action.get("action", "")
        symbol = action.get("symbol", "")
        reason = action.get("reason", "")

        logger.info(f"[Lead] Action: {action_type} {symbol} — {reason}")

        if action_type in ("no_action", "hold"):
            return

        if action_type == "close":
            option_symbol = action.get("option_symbol")
            if option_symbol:
                worker = await self._find_worker_for_position(option_symbol)
                if worker:
                    await worker.close_position(option_symbol, reason=reason)
                else:
                    logger.warning(f"[Lead] No worker found for position {option_symbol}")
            return

        if action_type == "roll":
            option_symbol = action.get("option_symbol")
            if option_symbol:
                worker = await self._find_worker_for_position(option_symbol)
                if worker:
                    await worker.roll_position(option_symbol, reason=reason)
                else:
                    logger.warning(f"[Lead] No worker found for position {option_symbol}")
            return

        if action_type in ("open_csp", "open_cc", "open_wheel"):
            if not symbol:
                logger.warning(f"[Lead] {action_type} missing symbol — skipped")
                return
            if not self._validate_new_position(action):
                logger.warning(f"[Lead] Blocked {action_type} {symbol} — validation failed")
                return
            worker_map = {
                "open_csp": "Cash-Secured-Puts",
                "open_cc": "Covered-Calls",
                "open_wheel": "Wheel",
            }
            worker_name = worker_map[action_type]
            worker = self.workers.get(worker_name)
            if worker:
                # Target this symbol only — use targeted scan/evaluate/execute
                # (avoids re-running manage_positions for all existing positions)
                prev_assigned = worker.assigned_securities
                worker.assigned_securities = [symbol]
                try:
                    opportunities = await worker.scan()
                    trades = await worker.evaluate(opportunities)
                    await worker.execute(trades)
                finally:
                    worker.assigned_securities = prev_assigned
            return

        if action_type == "pause_worker":
            worker_name = action.get("worker", "")
            if worker_name in self.workers:
                await self.workers[worker_name].set_is_active(False, reason)
                logger.info(f"[Lead] Paused {worker_name}: {reason}")
            return

        if action_type == "resume_worker":
            worker_name = action.get("worker", "")
            if worker_name in self.workers:
                await self.workers[worker_name].set_is_active(True)
                logger.info(f"[Lead] Resumed {worker_name}: {reason}")
            return

        logger.warning(f"[Lead] Unknown action type: {action_type}")

    def _validate_new_position(self, action: dict) -> bool:
        """Validate a new position against hard constraints before executing."""
        if not self.portfolio:
            return False

        if self.portfolio.buying_power < 5000:
            logger.warning(
                f"[Lead] Insufficient buying power: ${self.portfolio.buying_power:,.0f}"
            )
            return False

        action_type = action.get("action", "")
        worker_map = {
            "open_csp": "Cash-Secured-Puts",
            "open_cc": "Covered-Calls",
            "open_wheel": "Wheel",
        }
        worker_name = worker_map.get(action_type)
        if worker_name:
            worker = self.workers.get(worker_name)
            if worker:
                current = self.portfolio.count_open_options_for_agent(worker_name)
                max_pos = getattr(worker, "max_positions", 5)
                if current >= max_pos:
                    logger.warning(
                        f"[Lead] {worker_name} at max positions "
                        f"({current}/{max_pos})"
                    )
                    return False

        if self.risk_manager:
            drawdown = self.risk_manager.get_current_drawdown()
            if drawdown > self.risk_manager.max_drawdown:
                logger.warning(
                    f"[Lead] Drawdown {drawdown:.1%} exceeds limit "
                    f"{self.risk_manager.max_drawdown:.1%}"
                )
                return False

        return True

    async def _find_worker_for_position(self, option_symbol: str):
        """
        Find which worker owns a specific open position.

        Fast path: read opt.assigned_to from in-memory portfolio state.
        DB fallback: query the Trade table by option_symbol — recovers after
          container restart when in-memory assigned_to is empty.
        Final fallback: default to Cash-Secured-Puts and write back so
          subsequent lookups in the same cycle hit the in-memory cache.
        """
        if not self.portfolio:
            return None

        for opt in self.portfolio.options:
            if opt.option_symbol == option_symbol:
                # Fast path: in-memory assignment still intact
                if opt.assigned_to:
                    worker = self.workers.get(opt.assigned_to)
                    if worker:
                        return worker

                # DB fallback: find the most recent sell trade for this symbol
                try:
                    from core.database import AsyncSessionLocal
                    from models.trade import Trade
                    from sqlalchemy import select
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(Trade.agent_name)
                            .where(Trade.option_symbol == option_symbol)
                            .where(Trade.side == "sell")
                            .order_by(Trade.created_at.desc())
                            .limit(1)
                        )
                        agent_name = result.scalar_one_or_none()
                    if agent_name and agent_name in self.workers:
                        opt.assigned_to = agent_name  # write-back to in-memory cache
                        logger.info(f"[Lead] Routed {option_symbol} → {agent_name} via DB lookup")
                        return self.workers[agent_name]
                except Exception as e:
                    logger.warning(f"[Lead] DB worker lookup failed for {option_symbol}: {e}")

                # Final fallback: system historically only ran CSP; default to it
                csp = self.workers.get("Cash-Secured-Puts")
                if csp:
                    logger.warning(
                        f"[Lead] No DB record for {option_symbol} — "
                        "defaulting to Cash-Secured-Puts"
                    )
                    opt.assigned_to = "Cash-Secured-Puts"
                    return csp

                return None

        return None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove surrounding triple-backtick code fences that Claude occasionally wraps responses in."""
        import re
        stripped = re.sub(r'^```[a-zA-Z]*\n', '', text.lstrip())
        stripped = re.sub(r'\n```\s*$', '', stripped.rstrip())
        return stripped.strip()

    async def _store_cycle_reasoning(self, decision: dict):
        """Persist the LLM's reasoning to the execution_log table for the dashboard."""
        try:
            async with AsyncSessionLocal() as session:
                log = ExecutionLog(
                    agent_name="Lead-Agent",
                    symbol="PORTFOLIO",
                    action="cycle_decision",
                    rationale=self._strip_code_fences(decision["reasoning"])[:8000],
                    order_status=decision["summary"][:200],
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.error(f"[Lead] Failed to store cycle reasoning: {e}")

    # ── REGIME-ADJUSTED PARAMETERS ────────────────────────────────

    def _apply_regime_params(self):
        """
        Push regime-adjusted strategy parameters to worker agents.

        Workers read delta targets and max_positions from their self.params —
        we override those in-memory when the regime changes.
        """
        if not self.strategy_manager:
            return

        mapping = {
            "Covered-Calls": "covered_calls",
            "Cash-Secured-Puts": "cash_secured_puts",
            "Wheel": "wheel",
        }

        for worker_name, strategy_name in mapping.items():
            worker = self.workers.get(worker_name)
            if not worker:
                continue

            adjusted = self.strategy_manager.get_adjusted_params(strategy_name)

            # Apply adjusted params to worker attributes
            if hasattr(worker, "delta_target") and "delta_target" in adjusted:
                worker.delta_target = abs(adjusted["delta_target"])
            if hasattr(worker, "csp_delta") and "csp_delta" in adjusted:
                worker.csp_delta = abs(adjusted["csp_delta"])
            if hasattr(worker, "cc_delta") and "cc_delta" in adjusted:
                worker.cc_delta = abs(adjusted["cc_delta"])
            if hasattr(worker, "max_positions") and "max_positions" in adjusted:
                worker.max_positions = adjusted["max_positions"]

            regime = adjusted.get("_regime", "normal")
            if regime != "normal":
                logger.debug(
                    f"[Lead] {worker_name}: applied {regime} regime params "
                    f"(delta={adjusted.get('delta_target', adjusted.get('csp_delta', '?'))}, "
                    f"max_pos={adjusted.get('max_positions', '?')})"
                )

    # ── ASSIGNMENT LOGIC (Scanner-powered) ────────────────────────

    async def _update_assignments(self):
        """
        Assign securities to workers using Scanner results (or fallback watchlist).

        The Scanner provides pre-scored opportunities with IV rank, price, liquidity,
        and support proximity already computed — we leverage those metrics directly
        to avoid redundant API calls.

        Rules:
        - Each symbol assigned to only ONE worker
        - Covered Calls: need shares + IV rank > 40
        - Cash Secured Puts: IV rank > 30 + near support + have cash
        - The Wheel: IV rank > 25 + good price range ($20-$500)
        """
        if not self.market_feed:
            logger.warning("[Lead] No market feed — skipping assignment update")
            return

        # ── Get ranked symbols from Scanner or fallback ──
        scanner_opportunities = []
        if self.scanner:
            scanner_opportunities = await self.scanner.get_top_opportunities()

        if scanner_opportunities:
            symbols = [o["symbol"] for o in scanner_opportunities]
            opp_map = {o["symbol"]: o for o in scanner_opportunities}
            logger.info(
                f"[Lead] Using Scanner results — {len(symbols)} symbols "
                f"(top: {symbols[0]} @ {opp_map[symbols[0]].get('composite_score', 0):.3f})"
            )
        else:
            symbols = self._fallback_watchlist
            opp_map = {}
            logger.info(
                f"[Lead] Scanner not available — using fallback watchlist "
                f"({len(symbols)} symbols)"
            )

        # Get IV ranks (use scanner data when available, else fetch live)
        if opp_map:
            iv_ranks = {sym: opp_map[sym].get("iv_rank", -1) for sym in symbols}
        else:
            iv_ranks = await self.market_feed.get_iv_ranks(symbols)

        # Clear current assignments
        for worker in self.workers.values():
            worker.assigned_securities = []

        assigned: set[str] = set()

        # Worker references
        cc_worker = self.workers.get("Covered-Calls")
        csp_worker = self.workers.get("Cash-Secured-Puts")
        wheel_worker = self.workers.get("Wheel")

        high_risk_earnings = getattr(self, "_high_risk_earnings", set())

        for symbol in symbols:
            if symbol in assigned:
                continue

            # Skip symbols with earnings within 7 days
            if symbol in high_risk_earnings:
                logger.debug(f"[Lead] {symbol} — skipped (earnings within 7 days)")
                continue

            iv_rank = iv_ranks.get(symbol, -1)
            if iv_rank < 0:
                continue

            # Use scanner data for price/support when available
            opp = opp_map.get(symbol, {})
            price = opp.get("current_price", 0)
            if price <= 0:
                try:
                    price = await self.market_feed.get_current_price(symbol)
                except Exception:
                    price = 0

            near_support = opp.get("near_support", False)

            # Rule 1: CC — we hold shares + IV rank > 40
            if (
                cc_worker
                and cc_worker.is_active
                and iv_rank > 40
                and self.portfolio
                and self.portfolio.get_shares_for_symbol(symbol) >= 100
            ):
                cc_worker.assigned_securities.append(symbol)
                assigned.add(symbol)
                score_str = f", score={opp.get('composite_score', '?')}" if opp else ""
                logger.debug(f"[Lead] {symbol} → CC (IV rank {iv_rank:.0f}{score_str})")
                continue

            # Rule 2: CSP — IV rank > 30 + near support + have cash
            if (
                csp_worker
                and csp_worker.is_active
                and iv_rank > 30
                and price > 0
            ):
                # Use scanner's near_support flag, or compute live
                if not near_support and not opp:
                    near_support = await self.market_feed.is_near_support(symbol, price)

                if near_support and self.portfolio and self.portfolio.buying_power > price * 100:
                    csp_worker.assigned_securities.append(symbol)
                    assigned.add(symbol)
                    score_str = f", score={opp.get('composite_score', '?')}" if opp else ""
                    logger.debug(f"[Lead] {symbol} → CSP (IV rank {iv_rank:.0f}{score_str})")
                    continue

            # Rule 3: Wheel — IV rank > 25 + good price range + liquid
            if (
                wheel_worker
                and wheel_worker.is_active
                and iv_rank > 25
                and 20 <= price <= 500
            ):
                wheel_worker.assigned_securities.append(symbol)
                assigned.add(symbol)
                score_str = f", score={opp.get('composite_score', '?')}" if opp else ""
                logger.debug(
                    f"[Lead] {symbol} → Wheel (IV rank {iv_rank:.0f}, "
                    f"price ${price:.0f}{score_str})"
                )
                continue

        # Log assignments
        for name, worker in self.workers.items():
            if worker.assigned_securities:
                logger.info(
                    f"[Lead] {name}: {', '.join(worker.assigned_securities)} "
                    f"({len(worker.assigned_securities)} symbols)"
                )
            else:
                logger.info(f"[Lead] {name}: no symbols assigned")

    # ── INTELLIGENCE CHECKS ────────────────────────────────────────

    async def _apply_intelligence_checks(self):
        """
        Apply intelligence service checks before assignments:
        1. Earnings risk: flag symbols with earnings in 7 days
        2. Regime override: reduce max_positions in risk_off/crisis
        3. Performance pause: pause workers with < 40% win rate over 30d
        """
        # ── Earnings risk flag (stored on self for use in _update_assignments) ──
        self._high_risk_earnings: set[str] = set()
        try:
            from services.earnings_calendar import EarningsCalendarService
            earnings_svc = EarningsCalendarService()
            high_risk = await earnings_svc.get_high_risk_symbols()
            self._high_risk_earnings = set(high_risk)
            if high_risk:
                logger.info(f"[Lead] Earnings risk symbols (skip): {', '.join(sorted(high_risk))}")
        except Exception as e:
            logger.debug(f"[Lead] Earnings check failed: {e}")

        # ── Regime check: tighten positions in risk_off/crisis ──
        try:
            from services.market_regime import MarketRegimeService
            regime_svc = MarketRegimeService(
                broker=self.broker,
                strategy_manager=self.strategy_manager,
            )
            latest = await regime_svc.get_latest()
            regime = latest.get("regime", "neutral")
            if regime in ("risk_off", "crisis"):
                for worker in self.workers.values():
                    if hasattr(worker, "max_positions") and worker.max_positions > 1:
                        worker.max_positions = max(1, worker.max_positions - 1)
                logger.warning(
                    f"[Lead] {regime.upper()} regime detected — reduced max_positions by 1 on all workers"
                )
        except Exception as e:
            logger.debug(f"[Lead] Regime check failed: {e}")

        # ── Performance pause: pause workers with very low win rate ──
        try:
            from services.performance_analyst import PerformanceAnalystService
            perf_svc = PerformanceAnalystService()
            strategy_data = await perf_svc.get_strategy_breakdown()
            strategies = (strategy_data.get("data") or {}).get("strategies", [])
            for s in strategies:
                name = s.get("agent_name")
                win_rate = s.get("win_rate", 100)
                closed = s.get("closed_trades", 0)
                if closed >= 10 and win_rate < 40 and name in self.workers:
                    self._paused_workers.add(name)
                    logger.warning(
                        f"[Lead] Pausing {name} — {win_rate:.0f}% win rate over {closed} closed trades"
                    )
        except Exception as e:
            logger.debug(f"[Lead] Performance pause check failed: {e}")

    # ── WORKER PERFORMANCE EVALUATION ─────────────────────────────

    async def _evaluate_worker_performance(self):
        """
        Review worker metrics and adjust behavior.

        - Win rate < 50% over last 20 trades → reduce max_positions by 1
        - Annualized return > 20% → increase max_positions by 1
        - 3 consecutive losses → pause for 1 cycle
        """
        if not self.performance_logger:
            return

        logger.info("[Lead] Evaluating worker performance...")

        for name, worker in self.workers.items():
            try:
                metrics = await self.performance_logger.get_agent_metrics(name, lookback_days=30)

                if metrics["total_trades"] == 0:
                    continue

                win_rate = metrics.get("win_rate", 0)
                total_trades = metrics["total_trades"]

                # Check win rate
                if total_trades >= 20 and win_rate < 50:
                    logger.warning(
                        f"[Lead] {name} win rate {win_rate:.0f}% < 50% "
                        f"over {total_trades} trades"
                    )
                    if hasattr(worker, "max_positions") and worker.max_positions > 1:
                        worker.max_positions -= 1
                        logger.info(f"[Lead] Reduced {name} max_positions to {worker.max_positions}")

                    # Notify on poor performance
                    if self.notifier and win_rate < 40:
                        await self.notifier.send_risk_warning(
                            f"{name} underperforming: {win_rate:.0f}% win rate",
                            details={
                                "worker": name,
                                "action": f"Reduced max_positions, win_rate={win_rate:.0f}%",
                            },
                        )

                # Check consecutive losses
                losses = metrics.get("losses", 0)
                self._consecutive_losses[name] = losses

                # Unpause workers after a cycle
                if name in self._paused_workers:
                    self._paused_workers.discard(name)
                    logger.info(f"[Lead] {name} unpaused after cooldown")

                logger.debug(
                    f"[Lead] {name}: trades={total_trades}, "
                    f"win_rate={win_rate:.0f}%, "
                    f"pnl=${metrics.get('total_pnl', 0):.2f}"
                )

            except Exception as e:
                logger.error(f"[Lead] Performance eval failed for {name}: {e}")

    # ── DAILY SUMMARY ─────────────────────────────────────────────

    async def send_daily_summary(self):
        """
        Build and send an end-of-day summary via Notifier.

        Call this from the scheduler at market close.
        """
        if not self.notifier:
            return

        summary = {
            "total_pnl": 0,
            "premium_collected": 0,
            "trades_executed": 0,
            "portfolio_value": 0,
            "equity": 0,
            "cash": 0,
            "regime": "normal",
            "agent_performance": [],
        }

        if self.portfolio:
            summary["portfolio_value"] = self.portfolio.total_value
            summary["equity"] = self.portfolio.equity
            summary["cash"] = self.portfolio.cash

        if self.strategy_manager:
            summary["regime"] = self.strategy_manager.regime.value

        if self.performance_logger:
            try:
                port_summary = await self.performance_logger.get_portfolio_summary()
                summary["total_pnl"] = port_summary.get("total_pnl", 0)
                summary["premium_collected"] = port_summary.get("total_premium", 0)
                summary["trades_executed"] = port_summary.get("trades_today", 0)
            except Exception as e:
                logger.error(f"[Lead] Failed to get portfolio summary for daily report: {e}")

            for name in self.workers:
                try:
                    metrics = await self.performance_logger.get_agent_metrics(name, lookback_days=1)
                    summary["agent_performance"].append({
                        "name": name,
                        "win_rate": metrics.get("win_rate", 0),
                        "pnl": metrics.get("total_pnl", 0),
                    })
                except Exception:
                    pass

        await self.notifier.send_daily_summary(summary)

    # ── PROPOSAL SYSTEM ───────────────────────────────────────────

    async def generate_proposals(
        self,
        batch_id: Optional[str] = None,
        capital_reserve: float = 0.20,
    ) -> list[TradeProposal]:
        """
        Generate trade proposals from latest Scanner results without executing.

        Capital-aware: fetches current buying power and only proposes trades that
        are actually executable given the account size. Stops generating when
        cumulative collateral would exceed (1 - capital_reserve) of buying power.

        Args:
            batch_id: Optional batch identifier (auto-generated if None).
            capital_reserve: Fraction of buying power to keep in reserve (default 0.20 = 20%).
        """
        if batch_id is None:
            batch_id = str(uuid4())

        logger.info(f"[Lead] Generating proposals (batch {batch_id[:8]}...)")

        # ── Fetch account state ──────────────────────────────────────────
        buying_power = 0.0
        if self.broker:
            try:
                account = await self.broker.get_account()
                buying_power = float(account.get("buying_power", 0))
                equity = float(account.get("equity", 0))
                logger.info(
                    f"[Lead] Account: equity=${equity:,.0f}, "
                    f"buying_power=${buying_power:,.0f}"
                )
            except Exception as e:
                logger.warning(f"[Lead] Could not fetch account state: {e}")

        max_deployable = buying_power * (1.0 - capital_reserve)
        cumulative_collateral = 0.0

        # ── Get scanner results ──────────────────────────────────────────
        scanner_opportunities = []
        if self.scanner:
            scanner_opportunities = await self.scanner.get_top_opportunities()

        if not scanner_opportunities:
            logger.info("[Lead] No scanner results available for proposals")
            return []

        # Sort by composite_score descending — best opportunities first
        scanner_opportunities = sorted(
            scanner_opportunities,
            key=lambda o: o.get("composite_score", 0),
            reverse=True,
        )

        opp_map = {o["symbol"]: o for o in scanner_opportunities}
        iv_ranks = {sym: opp_map[sym].get("iv_rank", -1) for sym in opp_map}

        # ── Capital-based strategy filters ──────────────────────────────
        skip_wheel = False
        wheel_skip_reason = ""
        if buying_power > 0 and buying_power < 20_000:
            skip_wheel = True
            wheel_skip_reason = f"buying power ${buying_power:,.0f} insufficient for share assignment"
            logger.info(f"[Lead] Skipping Wheel strategy — {wheel_skip_reason}")

        # ── Build assignment list ────────────────────────────────────────
        assignments: list[tuple[str, str, dict]] = []  # (symbol, agent_name, opp_data)
        assigned: set[str] = set()

        from data.options_chain import OptionsChainAnalyzer
        options_chain = OptionsChainAnalyzer(broker=self.broker)

        for symbol, opp in opp_map.items():
            if symbol in assigned:
                continue

            iv_rank = iv_ranks.get(symbol, -1)
            if iv_rank < 0:
                continue

            price = opp.get("current_price", 0)
            if price <= 0:
                try:
                    price = await self.market_feed.get_current_price(symbol)
                    opp["current_price"] = price
                except Exception:
                    continue

            near_support = opp.get("near_support", False)

            # CC rule: hold shares + IV rank > 40
            if (
                iv_rank > 40
                and self.portfolio
                and self.portfolio.get_shares_for_symbol(symbol) >= 100
            ):
                assignments.append((symbol, "Covered-Calls", opp))
                assigned.add(symbol)
                continue

            # CSP rule: IV rank > 30 + near support + have cash
            if iv_rank > 30 and price > 0:
                # Capital filter: only propose CSPs on strikes we can afford
                csp_collateral = price * 100  # approximate (1 contract)
                if buying_power > 0 and csp_collateral > buying_power:
                    logger.debug(
                        f"[Lead] Skipping CSP {symbol} — collateral ${csp_collateral:,.0f} "
                        f"> buying power ${buying_power:,.0f}"
                    )
                    continue
                # Low buying power: only propose strikes < $50
                if buying_power > 0 and buying_power < 5_000 and price > 50:
                    logger.debug(
                        f"[Lead] Skipping CSP {symbol} — price ${price:.0f} > $50 "
                        f"(buying power < $5k)"
                    )
                    continue
                if not near_support:
                    try:
                        near_support = await self.market_feed.is_near_support(symbol, price)
                    except Exception:
                        pass
                if near_support and self.portfolio and self.portfolio.buying_power > price * 100:
                    assignments.append((symbol, "Cash-Secured-Puts", opp))
                    assigned.add(symbol)
                    continue

            # Wheel rule: IV rank > 25 + good price range
            if iv_rank > 25 and 20 <= price <= 500:
                if skip_wheel:
                    logger.debug(f"[Lead] Skipping Wheel {symbol} — {wheel_skip_reason}")
                    continue
                # Wheel needs capital for both CSP collateral AND potential share assignment
                wheel_collateral = price * 100  # CSP margin
                share_purchase_cost = price * 100  # if assigned, need to buy 100 shares
                wheel_total_needed = wheel_collateral + share_purchase_cost
                if buying_power > 0 and wheel_total_needed > buying_power:
                    logger.debug(
                        f"[Lead] Skipping Wheel {symbol} — need ${wheel_total_needed:,.0f} "
                        f"(CSP + shares if assigned), have ${buying_power:,.0f}"
                    )
                    continue
                # Check if we already hold 100+ shares (can just sell calls)
                shares_held = self.portfolio.get_shares_for_symbol(symbol) if self.portfolio else 0
                if shares_held >= 100:
                    # Already hold shares — only need CSP collateral for puts, or $0 for calls
                    assignments.append((symbol, "Wheel", opp))
                    assigned.add(symbol)
                else:
                    # Need full capital buffer for potential assignment
                    if buying_power > 0 and wheel_total_needed <= buying_power:
                        assignments.append((symbol, "Wheel", opp))
                        assigned.add(symbol)
                    elif buying_power == 0:
                        assignments.append((symbol, "Wheel", opp))
                        assigned.add(symbol)

        logger.info(f"[Lead] {len(assignments)} assignments → fetching contracts...")

        proposals: list[TradeProposal] = []

        for symbol, agent_name, opp in assignments:
            # ── Capital gate: stop if we've deployed enough ──────────────
            if buying_power > 0 and cumulative_collateral >= max_deployable:
                logger.info(
                    f"[Lead] Capital limit reached — deployed "
                    f"${cumulative_collateral:,.0f} of ${max_deployable:,.0f} max. "
                    f"Stopping proposal generation."
                )
                break

            try:
                price = opp.get("current_price", 0)
                iv_rank = opp.get("iv_rank", 0)
                asset_type = opp.get("asset_type", "stock")
                scanner_score = opp.get("composite_score")

                # Fetch the optimal contract for this assignment
                contracts_list: list[dict] = []
                contract_type = "put"

                if agent_name == "Covered-Calls":
                    contracts_list = await options_chain.find_optimal_calls(
                        symbol, price, strategy_name="covered_calls", top_n=1
                    )
                    contract_type = "call"
                elif agent_name == "Cash-Secured-Puts":
                    contracts_list = await options_chain.find_optimal_puts(
                        symbol, price, strategy_name="cash_secured_puts", top_n=1
                    )
                    contract_type = "put"
                elif agent_name == "Wheel":
                    contracts_list = await options_chain.find_optimal_puts(
                        symbol, price, strategy_name="wheel", top_n=1
                    )
                    contract_type = "put"

                if not contracts_list:
                    logger.debug(f"[Lead] No contracts found for {symbol} ({agent_name})")
                    continue

                c = contracts_list[0]
                strike = c.get("strike", 0)
                dte = c.get("dte", 30)
                delta = c.get("delta", 0)
                bid = c.get("bid", 0)
                ask = c.get("ask", 0)
                mid_price = c.get("mid_price", round((bid + ask) / 2, 2))
                if mid_price <= 0:
                    logger.info(
                        f"[Lead] Skipping {symbol} ({agent_name}) — "
                        f"no market data (mid_price=0, snapshot likely missing)"
                    )
                    continue
                ann_return = c.get("annualized_return", options_chain.calculate_annualized_return(
                    mid_price, strike, dte, contract_type
                ))
                pop = c.get("probability_of_profit", round((1 - abs(delta)) * 100, 1))
                distance_otm_pct = c.get("distance_otm_pct", 0)
                num_contracts = 1

                premium_per_contract = round(mid_price * 100, 2)
                total_premium = round(premium_per_contract * num_contracts, 2)

                # Collateral and max risk
                if contract_type == "put":
                    collateral_required = round(strike * 100 * num_contracts, 2)
                    max_risk = round(collateral_required - total_premium, 2)
                else:
                    collateral_required = 0.0
                    max_risk = total_premium

                # ── Per-proposal capital feasibility check ───────────────
                if buying_power > 0 and collateral_required > buying_power:
                    logger.info(
                        f"[Lead] Skipping {symbol} — collateral ${collateral_required:,.0f} "
                        f"> buying power ${buying_power:,.0f}"
                    )
                    continue

                # ── Max position size check (15% of equity) ──────────────
                if self.risk_manager and self.portfolio and self.portfolio.equity > 0:
                    max_position = self.portfolio.equity * 0.15
                    if collateral_required > max_position:
                        logger.info(
                            f"[Lead] Skipping {symbol} — collateral ${collateral_required:,.0f} "
                            f"> 15% of equity (${max_position:,.0f})"
                        )
                        continue

                # ── Capital percentage fields ────────────────────────────
                pct_of_buying_power = (
                    round((collateral_required / buying_power) * 100, 1)
                    if buying_power > 0 else None
                )
                cumulative_collateral += collateral_required
                cumulative_pct = (
                    round((cumulative_collateral / buying_power) * 100, 1)
                    if buying_power > 0 else None
                )

                # Human-readable rationale
                support_note = " near support" if opp.get("near_support") else ""
                wheel_note = ""
                if agent_name == "Wheel" and self.portfolio:
                    shares_held = self.portfolio.get_shares_for_symbol(symbol)
                    if shares_held < 100:
                        assignment_cost = strike * 100
                        wheel_note = (
                            f" If assigned, ${assignment_cost:,.0f} buying power will be "
                            f"used to hold 100 shares of {symbol}."
                        )
                rationale = (
                    f"IV rank {iv_rank:.0f}{support_note}, {distance_otm_pct:.1f}% OTM "
                    f"at Δ{abs(delta):.2f}, {dte}DTE — {ann_return:.1f}% annualized"
                    f"{wheel_note}"
                )

                proposal = TradeProposal(
                    batch_id=batch_id,
                    status="pending",
                    agent_name=agent_name,
                    symbol=symbol,
                    asset_type=asset_type,
                    contract_type=contract_type,
                    option_symbol=c.get("option_symbol"),
                    strike=strike,
                    expiration=c.get("expiration", ""),
                    delta=delta,
                    dte=dte,
                    bid=bid,
                    ask=ask,
                    mid_price=mid_price,
                    premium_per_contract=premium_per_contract,
                    contracts=num_contracts,
                    total_premium=total_premium,
                    collateral_required=collateral_required,
                    annualized_return=ann_return,
                    probability_of_profit=pop,
                    max_risk=max_risk,
                    distance_otm_pct=distance_otm_pct,
                    iv_rank=iv_rank,
                    scanner_score=scanner_score,
                    rationale=rationale,
                    pct_of_buying_power=pct_of_buying_power,
                    cumulative_pct=cumulative_pct,
                    created_at=datetime.utcnow(),
                )

                async with AsyncSessionLocal() as db:
                    db.add(proposal)
                    await db.commit()
                    await db.refresh(proposal)

                proposals.append(proposal)
                logger.info(
                    f"[Lead] Proposal: {agent_name} {symbol} "
                    f"{contract_type.upper()} ${strike} exp {c.get('expiration')} "
                    f"@ ${mid_price:.2f} ({ann_return:.1f}% ann) "
                    f"[{pct_of_buying_power or '—'}% BP, {cumulative_pct or '—'}% cumul]"
                )

            except Exception as e:
                logger.error(f"[Lead] Failed to generate proposal for {symbol}: {e}")

        logger.info(
            f"[Lead] Generated {len(proposals)} proposals in batch {batch_id[:8]} "
            f"(${cumulative_collateral:,.0f} collateral / ${buying_power:,.0f} buying power)"
        )
        return proposals

    async def get_pending_proposals(self, batch_id: Optional[str] = None) -> list[TradeProposal]:
        """Return all pending proposals, optionally filtered by batch_id."""
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            q = select(TradeProposal).where(TradeProposal.status == "pending")
            if batch_id:
                q = q.where(TradeProposal.batch_id == batch_id)
            q = q.order_by(TradeProposal.created_at.desc())
            result = await db.execute(q)
            return list(result.scalars().all())

    async def approve_proposal(self, proposal_id: int) -> TradeProposal:
        """
        Approve a proposal and dispatch to the appropriate worker for execution.

        Builds the trade dict from proposal fields and calls worker.execute().
        Updates proposal status to "executed" on success.
        """
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TradeProposal).where(TradeProposal.id == proposal_id)
            )
            proposal = result.scalar_one_or_none()
            if not proposal:
                raise ValueError(f"Proposal {proposal_id} not found")
            if proposal.status != "pending":
                raise ValueError(
                    f"Proposal {proposal_id} is not pending (status={proposal.status})"
                )

            # Mark approved
            proposal.approved_at = datetime.utcnow()

            worker = self.workers.get(proposal.agent_name)
            if not worker:
                raise ValueError(f"No worker found for agent '{proposal.agent_name}'")

            # Build trade dict matching worker.execute() expectations
            trade_dict = {
                "symbol": proposal.symbol,
                "option_symbol": proposal.option_symbol,
                "contract_type": proposal.contract_type,
                "strike": proposal.strike,
                "expiration": proposal.expiration,
                "dte": proposal.dte,
                "side": "sell",
                "qty": proposal.contracts,
                "limit_price": proposal.mid_price,
                "premium": proposal.mid_price,
                "delta": proposal.delta,
                "annualized_return": proposal.annualized_return,
                "probability_of_profit": proposal.probability_of_profit,
                "iv_rank": proposal.iv_rank,
                "current_price": 0,  # not critical for execution
                "avg_cost": 0,
                "downside_protection": proposal.distance_otm_pct,
                "distance_from_support": 0,
                "score": proposal.scanner_score or 0,
            }

            try:
                executed = await worker.execute([trade_dict])
                if executed:
                    # Workers catch broker exceptions and return {"status": "failed"} — check for real successes
                    successful = [t for t in executed if t.get("status") not in {"failed", "rejected", "canceled", "held"}]
                    if not successful:
                        first_error = executed[0].get("error", "Order submission failed")
                        raise RuntimeError(f"Broker rejected order: {first_error}")
                    proposal.status = "executed"
                    proposal.executed_at = datetime.utcnow()
                    logger.info(
                        f"[Lead] Proposal {proposal_id} executed: "
                        f"{proposal.agent_name} {proposal.symbol} "
                        f"(order_id={successful[0].get('order_id')})"
                    )
                else:
                    raise RuntimeError("Worker returned no executed trades")
            except Exception as e:
                logger.error(f"[Lead] Proposal {proposal_id} execution failed: {e}")
                raise

            await db.commit()
            await db.refresh(proposal)
            return proposal

    async def reject_proposal(self, proposal_id: int) -> TradeProposal:
        """Mark a proposal as rejected."""
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TradeProposal).where(TradeProposal.id == proposal_id)
            )
            proposal = result.scalar_one_or_none()
            if not proposal:
                raise ValueError(f"Proposal {proposal_id} not found")
            if proposal.status != "pending":
                raise ValueError(
                    f"Proposal {proposal_id} is not pending (status={proposal.status})"
                )
            proposal.status = "rejected"
            proposal.rejected_at = datetime.utcnow()
            await db.commit()
            await db.refresh(proposal)
            return proposal

    async def approve_batch(self, batch_id: str) -> list[TradeProposal]:
        """Approve all pending proposals in a batch."""
        pending = await self.get_pending_proposals(batch_id=batch_id)
        results = []
        for p in pending:
            try:
                results.append(await self.approve_proposal(p.id))
            except Exception as e:
                logger.error(f"[Lead] Batch approve failed for proposal {p.id}: {e}")
        return results

    async def reject_batch(self, batch_id: str) -> list[TradeProposal]:
        """Reject all pending proposals in a batch."""
        from sqlalchemy import select, update as sa_update

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TradeProposal).where(
                    TradeProposal.batch_id == batch_id,
                    TradeProposal.status == "pending",
                )
            )
            proposals = list(result.scalars().all())
            now = datetime.utcnow()
            for p in proposals:
                p.status = "rejected"
                p.rejected_at = now
            await db.commit()
            for p in proposals:
                await db.refresh(p)
            return proposals

    async def modify_proposal(self, proposal_id: int, overrides: dict) -> TradeProposal:
        """
        Modify a pending proposal (strike, delta, contracts).

        Re-fetches the matching contract from the chain with the new delta target,
        updates all dependent fields (premium, annualized return, etc.), and
        keeps status as "pending".
        """
        from sqlalchemy import select
        from data.options_chain import OptionsChainAnalyzer

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TradeProposal).where(TradeProposal.id == proposal_id)
            )
            proposal = result.scalar_one_or_none()
            if not proposal:
                raise ValueError(f"Proposal {proposal_id} not found")
            if proposal.status != "pending":
                raise ValueError(f"Proposal {proposal_id} is not pending")

            # Apply simple field overrides
            if "contracts" in overrides:
                proposal.contracts = int(overrides["contracts"])

            # If delta or strike override, re-fetch matching contract
            new_delta = overrides.get("delta")
            new_strike = overrides.get("strike")

            if new_delta is not None or new_strike is not None:
                options_chain = OptionsChainAnalyzer(broker=self.broker)

                try:
                    price = await self.market_feed.get_current_price(proposal.symbol)
                except Exception:
                    price = proposal.strike  # fallback

                if proposal.contract_type == "call":
                    contracts_list = await options_chain.find_optimal_calls(
                        proposal.symbol, price,
                        strategy_name="covered_calls", top_n=10
                    )
                else:
                    contracts_list = await options_chain.find_optimal_puts(
                        proposal.symbol, price,
                        strategy_name="cash_secured_puts", top_n=10
                    )

                # Find best matching contract
                match = None
                if new_strike is not None:
                    # Find contract closest to requested strike
                    for c in contracts_list:
                        if match is None or abs(c.get("strike", 0) - new_strike) < abs(match.get("strike", 0) - new_strike):
                            match = c
                elif new_delta is not None:
                    # Find contract closest to requested delta
                    for c in contracts_list:
                        if match is None or abs(abs(c.get("delta", 0)) - abs(new_delta)) < abs(abs(match.get("delta", 0)) - abs(new_delta)):
                            match = c

                if match:
                    proposal.option_symbol = match.get("option_symbol", proposal.option_symbol)
                    proposal.strike = match.get("strike", proposal.strike)
                    proposal.expiration = match.get("expiration", proposal.expiration)
                    proposal.delta = match.get("delta", proposal.delta)
                    proposal.dte = match.get("dte", proposal.dte)
                    proposal.bid = match.get("bid", proposal.bid)
                    proposal.ask = match.get("ask", proposal.ask)
                    proposal.mid_price = match.get("mid_price", proposal.mid_price)
                    proposal.annualized_return = match.get(
                        "annualized_return",
                        options_chain.calculate_annualized_return(
                            proposal.mid_price, proposal.strike, proposal.dte, proposal.contract_type
                        )
                    )
                    proposal.probability_of_profit = match.get(
                        "probability_of_profit",
                        round((1 - abs(proposal.delta)) * 100, 1)
                    )
                    proposal.distance_otm_pct = match.get("distance_otm_pct", proposal.distance_otm_pct)

            # Recompute totals
            proposal.premium_per_contract = round(proposal.mid_price * 100, 2)
            proposal.total_premium = round(proposal.premium_per_contract * proposal.contracts, 2)
            if proposal.contract_type == "put":
                proposal.collateral_required = round(proposal.strike * 100 * proposal.contracts, 2)
                proposal.max_risk = round(proposal.collateral_required - proposal.total_premium, 2)
            else:
                proposal.collateral_required = 0.0
                proposal.max_risk = proposal.total_premium

            await db.commit()
            await db.refresh(proposal)
            return proposal

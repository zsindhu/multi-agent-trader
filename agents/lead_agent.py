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
- IV rank > 40 + we hold shares → Worker A (covered calls)
- IV rank > 30 + stock near support + we have cash → Worker B (CSPs)
- IV rank > 25 + good wheel candidate (liquid, $20-$500 range) → Worker C (Wheel)
- A symbol can only be assigned to ONE worker at a time
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import yaml
from loguru import logger

from agents.base_agent import BaseAgent
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.strategy import StrategyManager
from data.market_feed import MarketFeed
from services.logger_service import PerformanceLogger
from services.notifier import Notifier

if TYPE_CHECKING:
    from agents.scanner import ScannerAgent


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

        # Fallback watchlist (used only when scanner hasn't produced results)
        self._fallback_watchlist = _load_fallback_watchlist()

        # Track per-worker performance for rotation
        self._consecutive_losses: dict[str, int] = {}
        self._paused_workers: set[str] = set()

    async def run_cycle(self):
        """Execute one full orchestration cycle."""
        logger.info("[Lead] ═══════════════════════════════════════════")
        logger.info("[Lead] Starting orchestration cycle...")

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
            "Worker-A-CC": "covered_calls",
            "Worker-B-CSP": "cash_secured_puts",
            "Worker-C-Wheel": "wheel",
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
        - Workers A (CC): need shares + IV rank > 40
        - Workers B (CSP): IV rank > 30 + near support + have cash
        - Workers C (Wheel): IV rank > 25 + good price range ($20-$500)
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
        cc_worker = self.workers.get("Worker-A-CC")
        csp_worker = self.workers.get("Worker-B-CSP")
        wheel_worker = self.workers.get("Worker-C-Wheel")

        for symbol in symbols:
            if symbol in assigned:
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

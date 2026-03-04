"""
Worker A — Covered Calls: Sells OTM calls against held shares.

Strategy:
- Scan portfolio for positions with 100+ shares
- Filter options chain for OTM calls at target delta (~0.30), DTE 20-45, IV rank >= 30
- Score by annualized premium yield, downside protection (distance OTM), IV rank
- Execute sell-to-open limit orders at mid price
- Manage: take profit at 80%, roll up/out if stock approaches strike, close if DTE < 3

Lifecycle: scan() → evaluate() → execute() → manage_positions()
"""
from datetime import datetime
from typing import Optional

import yaml
from loguru import logger

from agents.base_agent import BaseAgent
from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from services.logger_service import PerformanceLogger
from agents.trade_journal import TradeJournalAgent


def _load_strategy_params() -> dict:
    try:
        with open("config/strategies.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("covered_calls", {})
    except FileNotFoundError:
        return {}


class CoveredCallWorker(BaseAgent):
    """
    Worker A — Sells covered calls against existing stock positions.
    """

    def __init__(
        self,
        broker: Optional[Broker] = None,
        portfolio: Optional[Portfolio] = None,
        risk_manager: Optional[RiskManager] = None,
        market_feed: Optional[MarketFeed] = None,
        options_chain: Optional[OptionsChainAnalyzer] = None,
        perf_logger: Optional[PerformanceLogger] = None,
        trade_journal: Optional[TradeJournalAgent] = None,
    ):
        super().__init__(name="Worker-A-CC", agent_type="covered_calls")
        self.broker = broker
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.market_feed = market_feed
        self.options_chain = options_chain
        self.perf_logger = perf_logger
        self.trade_journal = trade_journal

        # Strategy parameters from config
        self.params = _load_strategy_params()
        self.min_iv_rank = self.params.get("min_iv_rank", 30)
        self.delta_target = abs(self.params.get("delta_target", 0.30))
        self.dte_min = self.params.get("dte_min", 20)
        self.dte_max = self.params.get("dte_max", 45)
        self.max_positions = self.params.get("max_positions", 5)

        # Position management thresholds
        self.profit_target_pct = 0.80    # Take profit at 80% of max premium
        self.roll_approach_pct = 0.02    # Roll if stock within 2% of strike
        self.close_dte_threshold = 3     # Close if DTE < 3

    # ── SCAN ──────────────────────────────────────────────────────

    async def scan(self) -> list[dict]:
        """
        Scan portfolio for covered call opportunities.

        Requirements:
        1. Hold 100+ shares of the symbol
        2. IV rank >= min_iv_rank
        3. Available shares not already committed to calls
        4. Options chain has qualifying OTM calls at target delta/DTE
        """
        if not self.market_feed or not self.options_chain or not self.portfolio:
            logger.warning(f"[{self.name}] Missing dependencies — skipping scan")
            return []

        opportunities = []

        # Get all symbols where we hold 100+ shares
        symbols_with_shares = self.portfolio.get_symbols_with_shares(min_shares=100)

        # Intersect with assigned securities (Lead Agent decides what we can trade)
        scannable = [s for s in symbols_with_shares if s in self.assigned_securities]

        if not scannable:
            logger.info(f"[{self.name}] No eligible symbols with shares for covered calls")
            return []

        for symbol in scannable:
            try:
                # Check available shares (not already committed to other calls)
                available_shares = self.portfolio.get_available_shares(symbol)
                max_contracts = available_shares // 100

                if max_contracts < 1:
                    logger.debug(f"[{self.name}] {symbol}: all shares committed — skipping")
                    continue

                # Get current price
                current_price = await self.market_feed.get_current_price(symbol)
                if current_price <= 0:
                    continue

                # Check IV rank
                iv_rank = await self.market_feed.get_iv_rank(symbol)
                if iv_rank < self.min_iv_rank:
                    logger.debug(
                        f"[{self.name}] {symbol} IV rank {iv_rank:.1f} < {self.min_iv_rank} — skipping"
                    )
                    continue

                # Adjust delta for conservative mode
                delta_target = self.delta_target
                if self.risk_manager:
                    delta_target = self.risk_manager.get_delta_target(delta_target)

                # Find optimal calls
                calls = await self.options_chain.find_optimal_calls(
                    symbol=symbol,
                    current_price=current_price,
                    strategy_name="covered_calls",
                    top_n=3,
                )

                if not calls:
                    logger.debug(f"[{self.name}] No qualifying calls for {symbol}")
                    continue

                for contract in calls:
                    opportunities.append({
                        "symbol": symbol,
                        "current_price": current_price,
                        "iv_rank": iv_rank,
                        "max_contracts": max_contracts,
                        "avg_cost": self.portfolio.positions[symbol].avg_cost,
                        "contract": contract,
                    })

                logger.info(
                    f"[{self.name}] {symbol}: IV rank {iv_rank:.1f}, "
                    f"{available_shares} available shares, {len(calls)} qualifying calls"
                )

            except Exception as e:
                logger.error(f"[{self.name}] Error scanning {symbol}: {e}")

        logger.info(f"[{self.name}] Scan complete: {len(opportunities)} opportunities found")
        return opportunities

    # ── EVALUATE ──────────────────────────────────────────────────

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """
        Evaluate and filter covered call opportunities.

        Checks:
        1. Risk manager allows the trade (share coverage, position limits)
        2. Not selling calls below cost basis (avoid locking in losses)
        3. Ranks by composite score
        """
        if not opportunities:
            return []

        approved = []

        for opp in opportunities:
            contract = opp["contract"]
            symbol = opp["symbol"]
            strike = contract["strike"]
            avg_cost = opp["avg_cost"]

            # Check position limits
            if self.risk_manager and not self.risk_manager.can_open_position(
                self.name, self.max_positions
            ):
                logger.info(f"[{self.name}] Position limit reached — stopping evaluation")
                break

            # Check share coverage
            qty = min(1, opp["max_contracts"])  # Start with 1 contract
            if self.risk_manager and not self.risk_manager.can_sell_call(symbol, qty):
                logger.debug(f"[{self.name}] Cannot sell call on {symbol} — insufficient shares")
                continue

            # Don't sell calls below cost basis (avoid locking in losses)
            if strike < avg_cost:
                logger.debug(
                    f"[{self.name}] {symbol} call strike ${strike} < cost ${avg_cost:.2f} — skipping"
                )
                continue

            # Calculate premium
            mid_price = contract.get("mid_price", 0)
            if mid_price <= 0:
                mid_price = (contract.get("bid", 0) + contract.get("ask", 0)) / 2
            if mid_price <= 0:
                continue

            # Calculate downside protection
            downside_protection = ((strike - opp["current_price"]) / opp["current_price"]) * 100

            approved.append({
                "symbol": symbol,
                "option_symbol": contract["option_symbol"],
                "contract_type": "call",
                "strike": strike,
                "expiration": contract["expiration"],
                "dte": contract.get("dte", 0),
                "side": "sell",
                "qty": qty,
                "limit_price": round(mid_price, 2),
                "premium": round(mid_price * 100, 2),
                "delta": contract.get("delta", 0),
                "annualized_return": contract.get("annualized_return", 0),
                "probability_of_profit": contract.get("probability_of_profit", 0),
                "score": contract.get("score", 0),
                "downside_protection": round(downside_protection, 2),
                "iv_rank": opp["iv_rank"],
                "current_price": opp["current_price"],
                "avg_cost": avg_cost,
            })

        # Sort by score descending
        approved.sort(key=lambda t: t.get("score", 0), reverse=True)
        logger.info(f"[{self.name}] Evaluate complete: {len(approved)} trades approved")
        return approved

    # ── EXECUTE ───────────────────────────────────────────────────

    async def execute(self, trades: list[dict]) -> list[dict]:
        """
        Submit sell-to-open covered call orders.
        """
        if not self.broker:
            logger.warning(f"[{self.name}] No broker — cannot execute trades")
            return []

        results = []

        for trade in trades:
            try:
                order = await self.broker.submit_option_order(
                    option_symbol=trade["option_symbol"],
                    side="sell",
                    qty=trade["qty"],
                    order_type="limit",
                    limit_price=trade["limit_price"],
                    time_in_force="day",
                )

                trade["order_id"] = order.get("order_id")
                trade["status"] = order.get("status", "submitted")
                results.append(trade)

                logger.info(
                    f"[{self.name}] Sold {trade['qty']}x {trade['option_symbol']} "
                    f"@ ${trade['limit_price']:.2f} — Order {trade['order_id']}"
                )

                # Log to performance logger
                if self.perf_logger:
                    await self.perf_logger.log_trade(
                        agent_name=self.name,
                        symbol=trade["symbol"],
                        option_symbol=trade["option_symbol"],
                        trade_type="sell_to_open",
                        side="sell",
                        quantity=trade["qty"],
                        price=trade["limit_price"],
                        premium=trade["limit_price"],
                        strike=trade["strike"],
                        expiration=trade["expiration"],
                        status="submitted",
                        notes=f"CC: delta={trade['delta']:.2f}, DTE={trade['dte']}, "
                              f"ann_ret={trade['annualized_return']:.1f}%, "
                              f"downside_prot={trade['downside_protection']:.1f}%",
                    )

                # Log to trade journal
                if self.trade_journal:
                    await self.trade_journal.log_entry(
                        agent_name=self.name,
                        symbol=trade["symbol"],
                        option_symbol=trade["option_symbol"],
                        contract_type="call",
                        strike=trade["strike"],
                        expiration=trade["expiration"],
                        side="sell",
                        quantity=trade["qty"],
                        fill_price=trade["limit_price"],
                        premium=trade["limit_price"],
                        iv_rank=trade.get("iv_rank"),
                        stock_price=trade.get("current_price"),
                        delta_at_entry=trade.get("delta"),
                        dte_at_entry=trade.get("dte"),
                        annualized_return_at_entry=trade.get("annualized_return"),
                        probability_of_profit=trade.get("probability_of_profit"),
                    )

                # Assign in portfolio
                if self.portfolio:
                    self.portfolio.assign_option(trade["option_symbol"], self.name)

            except Exception as e:
                logger.error(f"[{self.name}] Execution failed for {trade['option_symbol']}: {e}")
                trade["status"] = "failed"
                trade["error"] = str(e)
                results.append(trade)

        logger.info(f"[{self.name}] Executed {len(results)} trades")
        return results

    # ── MANAGE POSITIONS ──────────────────────────────────────────

    async def manage_positions(self) -> list[dict]:
        """
        Monitor and manage open covered call positions.

        Actions:
        1. Take profit: if >80% premium captured → buy to close
        2. Roll up and out: if stock approaches strike with >5 DTE → close + reopen higher
        3. Close: if DTE < 3 → buy to close (avoid gamma risk)
        4. Detect called away: if shares disappear → log cycle completion
        """
        if not self.portfolio or not self.broker:
            return []

        actions = []
        my_options = self.portfolio.get_options_for_agent(self.name)
        call_positions = [o for o in my_options if o.contract_type == "call" and o.is_short]

        for pos in call_positions:
            try:
                action = await self._evaluate_position(pos)
                if action:
                    actions.append(action)
            except Exception as e:
                logger.error(f"[{self.name}] Error managing {pos.option_symbol}: {e}")

        # Check for called-away events
        called_away = await self._check_called_away()
        actions.extend(called_away)

        if actions:
            logger.info(f"[{self.name}] Position management: {len(actions)} actions taken")
        return actions

    async def _evaluate_position(self, pos) -> Optional[dict]:
        """Evaluate a single covered call position."""
        if pos.entry_price <= 0:
            return None

        profit_pct = (pos.entry_price - pos.current_price) / pos.entry_price
        dte = self._estimate_dte(pos.expiration)

        # ACTION 1: Take profit at 80%
        profit_target = self.profit_target_pct
        if self.risk_manager:
            profit_target = self.risk_manager.get_profit_target_pct(self.profit_target_pct)

        if profit_pct >= profit_target:
            return await self._close_position(
                pos,
                reason="profit_target",
                note=f"Profit captured: {profit_pct:.0%} (target: {profit_target:.0%})",
            )

        # ACTION 2: Close if DTE < 3 (avoid gamma risk near expiry)
        if dte is not None and dte < self.close_dte_threshold:
            return await self._close_position(
                pos,
                reason="expiry_close",
                note=f"DTE={dte} < {self.close_dte_threshold} — closing to avoid gamma risk",
            )

        # ACTION 3: Roll up and out if stock approaching strike
        if self.market_feed and dte is not None and dte > 5:
            current_price = await self.market_feed.get_current_price(pos.symbol)
            if current_price > 0 and pos.strike > 0:
                distance_pct = (pos.strike - current_price) / current_price
                if distance_pct < self.roll_approach_pct:
                    return await self._roll_position(pos, current_price)

        return None

    async def _close_position(self, pos, reason: str, note: str = "") -> dict:
        """Buy to close a short call position."""
        try:
            buy_price = pos.current_price if pos.current_price > 0 else 0.05

            order = await self.broker.submit_option_order(
                option_symbol=pos.option_symbol,
                side="buy",
                qty=abs(pos.quantity),
                order_type="limit",
                limit_price=round(buy_price, 2),
                time_in_force="day",
            )

            realized_pnl = (pos.entry_price - buy_price) * abs(pos.quantity) * 100

            logger.info(
                f"[{self.name}] Closing {pos.option_symbol}: {reason} — "
                f"P&L: ${realized_pnl:.2f}"
            )

            # Log to performance logger
            if self.perf_logger:
                await self.perf_logger.log_trade(
                    agent_name=self.name,
                    symbol=pos.symbol,
                    option_symbol=pos.option_symbol,
                    trade_type="buy_to_close",
                    side="buy",
                    quantity=abs(pos.quantity),
                    price=buy_price,
                    strike=pos.strike,
                    expiration=pos.expiration,
                    status="submitted",
                    pnl=realized_pnl,
                    notes=f"Close: {reason}. {note}",
                )

            # Log exit to journal
            if self.trade_journal:
                iv_rank = await self.market_feed.get_iv_rank(pos.symbol) if self.market_feed else None
                stock_price = await self.market_feed.get_current_price(pos.symbol) if self.market_feed else None

                await self.trade_journal.log_exit(
                    option_symbol=pos.option_symbol,
                    exit_stock_price=stock_price,
                    exit_iv_rank=iv_rank,
                    exit_reason=reason,
                    realized_pnl=realized_pnl,
                )

            return {
                "action": "close",
                "reason": reason,
                "option_symbol": pos.option_symbol,
                "buy_price": buy_price,
                "realized_pnl": realized_pnl,
                "order_id": order.get("order_id"),
            }

        except Exception as e:
            logger.error(f"[{self.name}] Failed to close {pos.option_symbol}: {e}")
            return {
                "action": "close_failed",
                "reason": reason,
                "option_symbol": pos.option_symbol,
                "error": str(e),
            }

    async def _roll_position(self, pos, current_price: float) -> dict:
        """Roll a covered call up and out (higher strike, further expiry)."""
        logger.info(
            f"[{self.name}] Rolling {pos.option_symbol} up and out — "
            f"stock approaching strike"
        )

        close_result = await self._close_position(
            pos, reason="rolled", note="Stock approaching strike — rolling up and out"
        )

        # Find a new call at higher strike
        if self.options_chain and close_result.get("action") == "close":
            try:
                new_calls = await self.options_chain.find_optimal_calls(
                    symbol=pos.symbol,
                    current_price=current_price,
                    strategy_name="covered_calls",
                    top_n=1,
                )
                if new_calls:
                    logger.info(
                        f"[{self.name}] Roll target: {new_calls[0]['option_symbol']} "
                        f"@ ${new_calls[0].get('strike', 0)}"
                    )
                    close_result["roll_target"] = new_calls[0]["option_symbol"]
            except Exception as e:
                logger.error(f"[{self.name}] Failed to find roll target: {e}")

        close_result["action"] = "roll"
        return close_result

    async def _check_called_away(self) -> list[dict]:
        """
        Detect when shares are called away (short call was exercised).

        Shares disappear from portfolio while we had an open call.
        """
        if not self.portfolio:
            return []

        actions = []
        my_options = self.portfolio.get_options_for_agent(self.name)
        call_symbols = {o.symbol for o in my_options if o.contract_type == "call"}

        for symbol in call_symbols:
            shares = self.portfolio.get_shares_for_symbol(symbol)
            if shares < 100:
                # Shares gone — likely called away
                logger.info(f"[{self.name}] Shares called away: {symbol}")
                actions.append({
                    "action": "called_away",
                    "symbol": symbol,
                    "remaining_shares": shares,
                })

        return actions

    def _estimate_dte(self, expiration: str) -> Optional[int]:
        """Estimate days to expiration from expiration date string."""
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            return (exp_date - datetime.now()).days
        except (ValueError, TypeError):
            return None

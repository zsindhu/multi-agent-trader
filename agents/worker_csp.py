"""
Cash Secured Puts Worker — Sells puts at support levels on pullbacks.

Strategy:
- Scan watchlist for high IV rank stocks near support
- Filter options chain for OTM puts at target delta (~-0.25), DTE 20-45
- Score by annualized return, probability of profit, distance OTM
- Execute limit orders at mid price
- Manage: take profit at 50-70%, roll if ITM near expiry

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
        return cfg.get("cash_secured_puts", {})
    except FileNotFoundError:
        return {}


class CashSecuredPutWorker(BaseAgent):
    """
    Cash Secured Puts — Sells cash-secured puts on high-IV stocks near support.
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
        super().__init__(name="Cash-Secured-Puts", agent_type="cash_secured_puts")
        self.broker = broker
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.market_feed = market_feed
        self.options_chain = options_chain
        self.perf_logger = perf_logger
        self.trade_journal = trade_journal

        # Strategy parameters from config
        self.params = _load_strategy_params()
        self.min_iv_rank = self.params.get("min_iv_rank", 25)
        self.delta_target = abs(self.params.get("delta_target", 0.25))
        self.dte_min = self.params.get("dte_min", 20)
        self.dte_max = self.params.get("dte_max", 45)
        self.support_buffer = self.params.get("support_buffer", 0.05)
        self.max_positions = self.params.get("max_positions", 5)

        # Position management thresholds
        self.profit_target_pct = 0.50   # Take profit at 50% of max premium
        self.roll_dte_threshold = 5     # Roll when DTE < 5 and ITM

    # ── SCAN ──────────────────────────────────────────────────────

    async def scan(self) -> list[dict]:
        """
        Scan assigned securities for CSP opportunities.

        Filters:
        1. IV rank >= min_iv_rank
        2. Stock near support level (within support_buffer %)
        3. Options chain has qualifying puts at target delta/DTE
        """
        if not self.market_feed or not self.options_chain:
            logger.warning(f"[{self.name}] Missing market_feed or options_chain — skipping scan")
            return []

        opportunities = []

        for symbol in self.assigned_securities:
            try:
                # Get current price
                current_price = await self.market_feed.get_current_price(symbol)
                if current_price <= 0:
                    logger.debug(f"[{self.name}] No price data for {symbol}")
                    continue

                # Check IV rank
                iv_rank = await self.market_feed.get_iv_rank(symbol)
                if iv_rank < self.min_iv_rank:
                    logger.debug(
                        f"[{self.name}] {symbol} IV rank {iv_rank:.1f} < {self.min_iv_rank} — skipping"
                    )
                    continue

                # Check if near support
                near_support = await self.market_feed.is_near_support(
                    symbol, current_price, self.support_buffer
                )
                if not near_support:
                    logger.debug(f"[{self.name}] {symbol} not near support — skipping")
                    continue

                # Get support levels for context
                support_levels = await self.market_feed.get_support_levels(symbol)
                nearest_support = support_levels[0] if support_levels else None

                # Adjust delta for conservative mode
                delta_target = self.delta_target
                if self.risk_manager:
                    delta_target = self.risk_manager.get_delta_target(delta_target)

                # Find optimal puts
                puts = await self.options_chain.find_optimal_puts(
                    symbol=symbol,
                    current_price=current_price,
                    strategy_name="cash_secured_puts",
                    top_n=3,
                )

                if not puts:
                    logger.debug(f"[{self.name}] No qualifying puts for {symbol}")
                    continue

                for contract in puts:
                    opportunities.append({
                        "symbol": symbol,
                        "current_price": current_price,
                        "iv_rank": iv_rank,
                        "near_support": near_support,
                        "nearest_support": nearest_support,
                        "contract": contract,
                    })

                logger.info(
                    f"[{self.name}] {symbol}: IV rank {iv_rank:.1f}, "
                    f"price ${current_price:.2f}, {len(puts)} qualifying puts"
                )

            except Exception as e:
                logger.error(f"[{self.name}] Error scanning {symbol}: {e}")

        logger.info(f"[{self.name}] Scan complete: {len(opportunities)} opportunities found")
        return opportunities

    # ── EVALUATE ──────────────────────────────────────────────────

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """
        Evaluate and filter opportunities. Returns approved trades ready for execution.

        Checks:
        1. Risk manager allows the trade (collateral, position limits)
        2. Not already holding a position on this symbol
        3. Ranks by composite score
        """
        if not opportunities:
            return []

        approved = []

        for opp in opportunities:
            contract = opp["contract"]
            symbol = opp["symbol"]
            strike = contract["strike"]

            # Check position limits
            if self.risk_manager and not self.risk_manager.can_open_position(
                self.name, self.max_positions
            ):
                logger.info(f"[{self.name}] Position limit reached — stopping evaluation")
                break

            # Check collateral
            if self.risk_manager and not self.risk_manager.can_sell_put(strike, qty=1):
                logger.debug(
                    f"[{self.name}] Insufficient collateral for {symbol} put @ ${strike}"
                )
                continue

            # Check if we already have a position on this symbol
            if self.portfolio:
                existing = [
                    o for o in self.portfolio.get_options_for_agent(self.name)
                    if o.symbol == symbol and o.contract_type == "put"
                ]
                if existing:
                    logger.debug(f"[{self.name}] Already have CSP on {symbol} — skipping")
                    continue

            # Build trade order
            mid_price = contract.get("mid_price", 0)
            if mid_price <= 0:
                mid_price = (contract.get("bid", 0) + contract.get("ask", 0)) / 2

            if mid_price <= 0:
                continue

            approved.append({
                "symbol": symbol,
                "option_symbol": contract["option_symbol"],
                "contract_type": "put",
                "strike": strike,
                "expiration": contract["expiration"],
                "dte": contract.get("dte", 0),
                "side": "sell",
                "qty": 1,
                "limit_price": round(mid_price, 2),
                "premium": round(mid_price * 100, 2),  # Per contract
                "delta": contract.get("delta", 0),
                "annualized_return": contract.get("annualized_return", 0),
                "probability_of_profit": contract.get("probability_of_profit", 0),
                "score": contract.get("score", 0),
                "iv_rank": opp["iv_rank"],
                "current_price": opp["current_price"],
                "nearest_support": opp.get("nearest_support"),
            })

        # Sort by score descending — best trades first
        approved.sort(key=lambda t: t.get("score", 0), reverse=True)
        logger.info(f"[{self.name}] Evaluate complete: {len(approved)} trades approved")
        return approved

    # ── EXECUTE ───────────────────────────────────────────────────

    async def execute(self, trades: list[dict]) -> list[dict]:
        """
        Submit limit orders for approved CSP trades.

        For each trade:
        1. Submit sell-to-open limit order at mid price
        2. Log trade via PerformanceLogger
        3. Log entry via TradeJournalAgent with full context
        """
        if not self.broker:
            logger.warning(f"[{self.name}] No broker — cannot execute trades")
            return []

        results = []

        for trade in trades:
            try:
                # Submit order
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
                        notes=f"CSP: delta={trade['delta']:.2f}, DTE={trade['dte']}, "
                              f"ann_ret={trade['annualized_return']:.1f}%",
                    )

                # Log to trade journal with full context
                if self.trade_journal:
                    distance_from_support = None
                    if trade.get("nearest_support") and trade["current_price"] > 0:
                        distance_from_support = (
                            (trade["current_price"] - trade["nearest_support"])
                            / trade["current_price"] * 100
                        )

                    await self.trade_journal.log_entry(
                        agent_name=self.name,
                        symbol=trade["symbol"],
                        option_symbol=trade["option_symbol"],
                        contract_type="put",
                        strike=trade["strike"],
                        expiration=trade["expiration"],
                        side="sell",
                        quantity=trade["qty"],
                        fill_price=trade["limit_price"],
                        premium=trade["limit_price"],
                        iv_rank=trade.get("iv_rank"),
                        stock_price=trade.get("current_price"),
                        distance_from_support=distance_from_support,
                        delta_at_entry=trade.get("delta"),
                        dte_at_entry=trade.get("dte"),
                        annualized_return_at_entry=trade.get("annualized_return"),
                        probability_of_profit=trade.get("probability_of_profit"),
                    )

                # Assign option in portfolio
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
        Monitor and manage open CSP positions.

        Actions:
        1. Take profit: if premium captured > profit_target_pct → buy to close
        2. Roll: if DTE < 5 and ITM → close + reopen at lower strike, further expiry
        3. Detect assignment: if shares appeared → log assignment event
        """
        if not self.portfolio or not self.broker:
            return []

        actions = []
        my_options = self.portfolio.get_options_for_agent(self.name)
        put_positions = [o for o in my_options if o.contract_type == "put" and o.is_short]

        for pos in put_positions:
            try:
                action = await self._evaluate_position(pos)
                if action:
                    actions.append(action)
            except Exception as e:
                logger.error(f"[{self.name}] Error managing {pos.option_symbol}: {e}")

        # Check for assignments (new stock positions that weren't there before)
        assignment_actions = await self._check_for_assignments()
        actions.extend(assignment_actions)

        if actions:
            logger.info(f"[{self.name}] Position management: {len(actions)} actions taken")
        return actions

    async def _evaluate_position(self, pos) -> Optional[dict]:
        """Evaluate a single position and determine action."""
        # Calculate profit captured
        # For short puts: profit when option price drops
        # PnL % = (entry_price - current_price) / entry_price
        if pos.entry_price <= 0:
            return None

        profit_pct = (pos.entry_price - pos.current_price) / pos.entry_price

        # Get profit target (adjusted for conservative mode)
        profit_target = self.profit_target_pct
        if self.risk_manager:
            profit_target = self.risk_manager.get_profit_target_pct(self.profit_target_pct)

        # ACTION 1: Take profit
        if profit_pct >= profit_target:
            return await self._close_position(
                pos,
                reason="profit_target",
                note=f"Profit captured: {profit_pct:.0%} (target: {profit_target:.0%})",
            )

        # ACTION 2: Roll if near expiry and ITM
        # (Simplified: we'd need to check if strike > current stock price for puts ITM)
        if self.market_feed:
            current_price = await self.market_feed.get_current_price(pos.symbol)
            if current_price > 0 and current_price < pos.strike:
                # Put is ITM
                # Check DTE (simplified — would need to parse expiration)
                dte = self._estimate_dte(pos.expiration)
                if dte is not None and dte < self.roll_dte_threshold:
                    return await self._roll_position(pos, current_price)

        return None

    async def _close_position(self, pos, reason: str, note: str = "") -> dict:
        """Buy to close a short put position."""
        try:
            # Submit buy-to-close order at market (for simplicity; could use limit)
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

            # Log exit to trade journal
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
        """
        Roll a put position down and out.

        1. Buy to close current position
        2. Sell to open new position at lower strike, further expiry
        """
        logger.info(f"[{self.name}] Rolling {pos.option_symbol} — ITM near expiry")

        # Step 1: Close the existing position
        close_result = await self._close_position(
            pos, reason="rolled", note="ITM near expiry — rolling down and out"
        )

        # Step 2: Find a new position at lower strike, further expiry
        if self.options_chain and close_result.get("action") == "close":
            try:
                new_puts = await self.options_chain.find_optimal_puts(
                    symbol=pos.symbol,
                    current_price=current_price,
                    strategy_name="cash_secured_puts",
                    top_n=1,
                )
                if new_puts:
                    # The evaluate/execute pipeline handles the new trade
                    logger.info(
                        f"[{self.name}] Roll target: {new_puts[0]['option_symbol']} "
                        f"@ ${new_puts[0].get('strike', 0)}"
                    )
                    close_result["roll_target"] = new_puts[0]["option_symbol"]
            except Exception as e:
                logger.error(f"[{self.name}] Failed to find roll target: {e}")

        close_result["action"] = "roll"
        return close_result

    async def _check_for_assignments(self) -> list[dict]:
        """
        Check if any puts were assigned (shares appeared in portfolio).

        When a put is assigned, we receive 100 shares at the strike price.
        """
        if not self.portfolio:
            return []

        actions = []
        my_options = self.portfolio.get_options_for_agent(self.name)
        put_symbols = {o.symbol for o in my_options if o.contract_type == "put"}

        # Check if we now hold shares for any put symbols
        for symbol in put_symbols:
            shares = self.portfolio.get_shares_for_symbol(symbol)
            if shares >= 100:
                # Likely assigned — check if the put position is gone
                active_puts = [
                    o for o in my_options
                    if o.symbol == symbol and o.contract_type == "put"
                ]
                # If no active puts but we have shares, assignment happened
                # (In practice, Alpaca sends assignment notifications)
                logger.info(f"[{self.name}] Possible assignment detected for {symbol}")
                actions.append({
                    "action": "assignment_detected",
                    "symbol": symbol,
                    "shares": shares,
                })

        return actions

    def _estimate_dte(self, expiration: str) -> Optional[int]:
        """Estimate days to expiration from expiration date string."""
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            return (exp_date - datetime.now()).days
        except (ValueError, TypeError):
            return None

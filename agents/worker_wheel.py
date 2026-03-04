"""
The Wheel Worker (state machine):
  SELLING_PUTS → ASSIGNED → SELLING_CALLS → CALLED_AWAY → repeat

Combines Covered Calls and Cash Secured Puts into a continuous cycle:
1. Sell cash-secured puts on a stock
2. If assigned, sell covered calls on the shares
3. If called away, start selling puts again
4. Track cumulative cost basis reduction across the full cycle

The Wheel tracks per-symbol state and accumulates premium across the full cycle.
State is persisted to the database so it survives restarts.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import select

from agents.base_agent import BaseAgent
from core.broker import Broker
from core.database import AsyncSessionLocal
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from models.wheel_state import WheelStateRecord
from services.logger_service import PerformanceLogger
from agents.trade_journal import TradeJournalAgent


class WheelState(Enum):
    SELLING_PUTS = "selling_puts"
    ASSIGNED = "assigned"
    SELLING_CALLS = "selling_calls"
    CALLED_AWAY = "called_away"


def _load_strategy_params() -> dict:
    try:
        with open("config/strategies.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("wheel", {})
    except FileNotFoundError:
        return {}


class WheelWorker(BaseAgent):
    """
    The Wheel — A state machine that cycles between
    selling puts and selling calls on assigned symbols.
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
        super().__init__(name="Wheel", agent_type="wheel")
        self.broker = broker
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.market_feed = market_feed
        self.options_chain = options_chain
        self.perf_logger = perf_logger
        self.trade_journal = trade_journal

        # Strategy parameters
        self.params = _load_strategy_params()
        self.min_iv_rank = self.params.get("min_iv_rank", 25)
        self.csp_delta = abs(self.params.get("csp_delta", 0.25))
        self.cc_delta = abs(self.params.get("cc_delta", 0.30))
        self.dte_min = self.params.get("dte_min", 25)
        self.dte_max = self.params.get("dte_max", 45)
        self.max_positions = self.params.get("max_positions", 3)

        # Per-symbol wheel state (in-memory cache — loaded from DB on first use)
        self.wheel_states: dict[str, WheelState] = {}

        # Cost basis tracking: symbol → {original_cost, total_premium, cycles}
        self.cost_basis: dict[str, dict] = {}

        # Position management thresholds
        self.put_profit_target = 0.50   # Take profit on puts at 50%
        self.call_profit_target = 0.80  # Take profit on calls at 80%
        self.roll_dte_threshold = 5

        # DB state loaded flag
        self._db_state_loaded = False

    # ── STATE MANAGEMENT (with DB persistence) ─────────────────────

    async def _load_states_from_db(self):
        """Load all wheel states from the database on first use."""
        if self._db_state_loaded:
            return

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(WheelStateRecord))
                rows = result.scalars().all()

                for row in rows:
                    try:
                        self.wheel_states[row.symbol] = WheelState(row.state)
                    except ValueError:
                        self.wheel_states[row.symbol] = WheelState.SELLING_PUTS

                    self.cost_basis[row.symbol] = {
                        "original_cost": row.original_cost,
                        "total_premium": row.total_premium_collected,
                        "cycles_completed": row.cycle_count,
                        "started_at": (
                            row.entered_state_at.isoformat()
                            if row.entered_state_at
                            else datetime.utcnow().isoformat()
                        ),
                    }

                self._db_state_loaded = True
                logger.info(
                    f"[{self.name}] Loaded {len(rows)} wheel states from DB"
                )
        except Exception as e:
            logger.error(f"[{self.name}] Failed to load wheel states from DB: {e}")
            self._db_state_loaded = True  # Don't retry forever

    async def _save_state_to_db(self, symbol: str):
        """Save a single symbol's wheel state to the database."""
        state = self.wheel_states.get(symbol, WheelState.SELLING_PUTS)
        cb = self.cost_basis.get(symbol, {})

        try:
            async with AsyncSessionLocal() as session:
                # Upsert: check if exists
                result = await session.execute(
                    select(WheelStateRecord).where(WheelStateRecord.symbol == symbol)
                )
                record = result.scalar_one_or_none()

                if record:
                    record.state = state.value
                    record.original_cost = cb.get("original_cost", 0.0)
                    record.total_premium_collected = cb.get("total_premium", 0.0)
                    record.cycle_count = cb.get("cycles_completed", 0)
                    record.updated_at = datetime.utcnow()
                else:
                    record = WheelStateRecord(
                        symbol=symbol,
                        state=state.value,
                        original_cost=cb.get("original_cost", 0.0),
                        total_premium_collected=cb.get("total_premium", 0.0),
                        cycle_count=cb.get("cycles_completed", 0),
                        entered_state_at=datetime.utcnow(),
                    )
                    session.add(record)

                await session.commit()
                logger.debug(f"[{self.name}] Saved {symbol} state to DB: {state.value}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save {symbol} state to DB: {e}")

    def get_state(self, symbol: str) -> WheelState:
        """Get current wheel state for a symbol."""
        return self.wheel_states.get(symbol, WheelState.SELLING_PUTS)

    async def set_state(self, symbol: str, state: WheelState):
        """Transition a symbol to a new wheel state and persist to DB."""
        old_state = self.wheel_states.get(symbol, WheelState.SELLING_PUTS)
        self.wheel_states[symbol] = state
        logger.info(
            f"[{self.name}] {symbol}: {old_state.value} → {state.value}"
        )
        await self._save_state_to_db(symbol)

    def _init_cost_basis(self, symbol: str, original_cost: float = 0.0):
        """Initialize cost basis tracking for a new wheel cycle."""
        if symbol not in self.cost_basis:
            self.cost_basis[symbol] = {
                "original_cost": original_cost,
                "total_premium": 0.0,
                "cycles_completed": 0,
                "started_at": datetime.utcnow().isoformat(),
            }

    async def _add_premium(self, symbol: str, premium: float):
        """Add premium collected to the cost basis tracker and persist."""
        if symbol in self.cost_basis:
            self.cost_basis[symbol]["total_premium"] += premium
            effective_cost = (
                self.cost_basis[symbol]["original_cost"]
                - self.cost_basis[symbol]["total_premium"]
            )
            logger.info(
                f"[{self.name}] {symbol} cost basis: "
                f"original=${self.cost_basis[symbol]['original_cost']:.2f}, "
                f"premium collected=${self.cost_basis[symbol]['total_premium']:.2f}, "
                f"effective=${effective_cost:.2f}"
            )
            await self._save_state_to_db(symbol)

    # ── SCAN ──────────────────────────────────────────────────────

    async def scan(self) -> list[dict]:
        """
        Scan based on current wheel state for each symbol.

        - SELLING_PUTS: Look for put selling opportunities (CSP phase)
        - SELLING_CALLS: Look for call selling opportunities (CC phase)
        - ASSIGNED: Transition to SELLING_CALLS
        - CALLED_AWAY: Transition to SELLING_PUTS, log full cycle
        """
        if not self.market_feed or not self.options_chain:
            logger.warning(f"[{self.name}] Missing dependencies — skipping scan")
            return []

        # Ensure wheel states are loaded from DB on first scan
        await self._load_states_from_db()

        opportunities = []

        for symbol in self.assigned_securities:
            try:
                state = self.get_state(symbol)

                # Initialize cost basis if new
                self._init_cost_basis(symbol)

                if state == WheelState.SELLING_PUTS:
                    opps = await self._scan_for_puts(symbol)
                    opportunities.extend(opps)

                elif state == WheelState.SELLING_CALLS:
                    opps = await self._scan_for_calls(symbol)
                    opportunities.extend(opps)

                elif state == WheelState.ASSIGNED:
                    # Transition to selling calls
                    await self._handle_assignment(symbol)
                    # Then scan for calls
                    opps = await self._scan_for_calls(symbol)
                    opportunities.extend(opps)

                elif state == WheelState.CALLED_AWAY:
                    # Log full cycle and transition back to puts
                    await self._handle_called_away(symbol)
                    opps = await self._scan_for_puts(symbol)
                    opportunities.extend(opps)

            except Exception as e:
                logger.error(f"[{self.name}] Error scanning {symbol}: {e}")

        logger.info(f"[{self.name}] Scan complete: {len(opportunities)} opportunities")
        return opportunities

    async def _scan_for_puts(self, symbol: str) -> list[dict]:
        """Scan for put-selling opportunities (CSP phase)."""
        current_price = await self.market_feed.get_current_price(symbol)
        if current_price <= 0:
            return []

        iv_rank = await self.market_feed.get_iv_rank(symbol)
        if iv_rank < self.min_iv_rank:
            logger.debug(f"[{self.name}] {symbol} IV rank {iv_rank:.1f} too low for puts")
            return []

        # For the wheel, we don't strictly require near-support
        # but we still check it as a preference
        near_support = await self.market_feed.is_near_support(symbol, current_price, 0.08)

        puts = await self.options_chain.find_wheel_contracts(
            symbol=symbol,
            current_price=current_price,
            wheel_state="selling_puts",
            top_n=3,
        )

        opportunities = []
        for contract in puts:
            opportunities.append({
                "symbol": symbol,
                "current_price": current_price,
                "iv_rank": iv_rank,
                "near_support": near_support,
                "wheel_state": "selling_puts",
                "contract": contract,
            })

        return opportunities

    async def _scan_for_calls(self, symbol: str) -> list[dict]:
        """Scan for call-selling opportunities (CC phase)."""
        if not self.portfolio:
            return []

        # Check we actually hold shares
        available_shares = self.portfolio.get_available_shares(symbol)
        if available_shares < 100:
            logger.debug(f"[{self.name}] {symbol}: not enough shares for calls ({available_shares})")
            return []

        current_price = await self.market_feed.get_current_price(symbol)
        if current_price <= 0:
            return []

        iv_rank = await self.market_feed.get_iv_rank(symbol)

        calls = await self.options_chain.find_wheel_contracts(
            symbol=symbol,
            current_price=current_price,
            wheel_state="selling_calls",
            top_n=3,
        )

        opportunities = []
        for contract in calls:
            opportunities.append({
                "symbol": symbol,
                "current_price": current_price,
                "iv_rank": iv_rank,
                "wheel_state": "selling_calls",
                "max_contracts": available_shares // 100,
                "contract": contract,
            })

        return opportunities

    # ── EVALUATE ──────────────────────────────────────────────────

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """Evaluate wheel opportunities — applies risk checks per state."""
        if not opportunities:
            return []

        approved = []

        for opp in opportunities:
            contract = opp["contract"]
            symbol = opp["symbol"]
            strike = contract["strike"]
            wheel_state = opp["wheel_state"]

            # Check position limits
            if self.risk_manager and not self.risk_manager.can_open_position(
                self.name, self.max_positions
            ):
                break

            # State-specific checks
            if wheel_state == "selling_puts":
                if self.risk_manager and not self.risk_manager.can_sell_put(strike, qty=1):
                    continue
            elif wheel_state == "selling_calls":
                qty = min(1, opp.get("max_contracts", 1))
                if self.risk_manager and not self.risk_manager.can_sell_call(symbol, qty):
                    continue

                # For calls, don't sell below cost basis
                if symbol in self.cost_basis:
                    effective_cost = (
                        self.cost_basis[symbol]["original_cost"]
                        - self.cost_basis[symbol]["total_premium"]
                    )
                    if strike < effective_cost:
                        logger.debug(
                            f"[{self.name}] {symbol} call strike ${strike} "
                            f"< effective cost ${effective_cost:.2f} — skipping"
                        )
                        continue

            # Calculate mid price
            mid_price = contract.get("mid_price", 0)
            if mid_price <= 0:
                mid_price = (contract.get("bid", 0) + contract.get("ask", 0)) / 2
            if mid_price <= 0:
                continue

            contract_type = "put" if wheel_state == "selling_puts" else "call"
            qty = 1

            approved.append({
                "symbol": symbol,
                "option_symbol": contract["option_symbol"],
                "contract_type": contract_type,
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
                "iv_rank": opp["iv_rank"],
                "current_price": opp["current_price"],
                "wheel_state": wheel_state,
            })

        approved.sort(key=lambda t: t.get("score", 0), reverse=True)
        logger.info(f"[{self.name}] Evaluate complete: {len(approved)} trades approved")
        return approved

    # ── EXECUTE ───────────────────────────────────────────────────

    async def execute(self, trades: list[dict]) -> list[dict]:
        """Execute wheel trades — sells puts or calls depending on state."""
        if not self.broker:
            logger.warning(f"[{self.name}] No broker — cannot execute")
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

                # Track premium in cost basis
                await self._add_premium(trade["symbol"], trade["limit_price"])

                logger.info(
                    f"[{self.name}] [{trade['wheel_state']}] Sold {trade['qty']}x "
                    f"{trade['option_symbol']} @ ${trade['limit_price']:.2f}"
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
                        notes=f"Wheel [{trade['wheel_state']}]: "
                              f"delta={trade['delta']:.2f}, DTE={trade['dte']}",
                    )

                # Log to trade journal
                if self.trade_journal:
                    await self.trade_journal.log_entry(
                        agent_name=self.name,
                        symbol=trade["symbol"],
                        option_symbol=trade["option_symbol"],
                        contract_type=trade["contract_type"],
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

                # Assign option in portfolio
                if self.portfolio:
                    self.portfolio.assign_option(trade["option_symbol"], self.name)

            except Exception as e:
                logger.error(f"[{self.name}] Execution failed: {e}")
                trade["status"] = "failed"
                trade["error"] = str(e)
                results.append(trade)

        return results

    # ── MANAGE POSITIONS ──────────────────────────────────────────

    async def manage_positions(self) -> list[dict]:
        """
        Monitor wheel positions and detect state transitions.

        1. Manage open puts (take profit, roll)
        2. Manage open calls (take profit, close near expiry)
        3. Detect assignment (puts → shares appeared)
        4. Detect called away (calls → shares disappeared)
        """
        if not self.portfolio or not self.broker:
            return []

        actions = []

        # Manage option positions
        my_options = self.portfolio.get_options_for_agent(self.name)

        for pos in my_options:
            if not pos.is_short:
                continue

            try:
                if pos.contract_type == "put":
                    action = await self._manage_put(pos)
                elif pos.contract_type == "call":
                    action = await self._manage_call(pos)
                else:
                    action = None

                if action:
                    actions.append(action)
            except Exception as e:
                logger.error(f"[{self.name}] Error managing {pos.option_symbol}: {e}")

        # Detect state transitions
        transition_actions = await self._detect_state_transitions()
        actions.extend(transition_actions)

        if actions:
            logger.info(f"[{self.name}] Position management: {len(actions)} actions")
        return actions

    async def _manage_put(self, pos) -> Optional[dict]:
        """Manage a short put position in the wheel."""
        if pos.entry_price <= 0:
            return None

        profit_pct = (pos.entry_price - pos.current_price) / pos.entry_price

        # Take profit
        if profit_pct >= self.put_profit_target:
            return await self._close_position(
                pos,
                reason="profit_target",
                note=f"Put profit: {profit_pct:.0%}",
            )

        # Roll if near expiry and ITM
        if self.market_feed:
            current_price = await self.market_feed.get_current_price(pos.symbol)
            dte = self._estimate_dte(pos.expiration)

            if current_price > 0 and current_price < pos.strike:
                # Put is ITM
                if dte is not None and dte < self.roll_dte_threshold:
                    return await self._close_position(
                        pos,
                        reason="rolled",
                        note=f"Put ITM (stock ${current_price:.2f} < strike ${pos.strike}), DTE={dte}",
                    )

        return None

    async def _manage_call(self, pos) -> Optional[dict]:
        """Manage a short call position in the wheel."""
        if pos.entry_price <= 0:
            return None

        profit_pct = (pos.entry_price - pos.current_price) / pos.entry_price

        # Take profit
        if profit_pct >= self.call_profit_target:
            return await self._close_position(
                pos,
                reason="profit_target",
                note=f"Call profit: {profit_pct:.0%}",
            )

        # Close near expiry
        dte = self._estimate_dte(pos.expiration)
        if dte is not None and dte < 3:
            return await self._close_position(
                pos,
                reason="expiry_close",
                note=f"Call near expiry, DTE={dte}",
            )

        return None

    async def _close_position(self, pos, reason: str, note: str = "") -> dict:
        """Buy to close a wheel option position."""
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

            # Log
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
                    notes=f"Wheel close: {reason}. {note}",
                )

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
            return {"action": "close_failed", "error": str(e)}

    # ── STATE TRANSITIONS ─────────────────────────────────────────

    async def _detect_state_transitions(self) -> list[dict]:
        """
        Detect assignment and called-away events by checking portfolio.

        - If we were SELLING_PUTS and now have 100+ shares → ASSIGNED
        - If we were SELLING_CALLS and shares dropped below 100 → CALLED_AWAY
        """
        if not self.portfolio:
            return []

        actions = []

        for symbol in self.assigned_securities:
            state = self.get_state(symbol)
            shares = self.portfolio.get_shares_for_symbol(symbol)

            if state == WheelState.SELLING_PUTS and shares >= 100:
                # Put was assigned — we now own shares
                await self._handle_assignment(symbol)
                actions.append({
                    "action": "state_transition",
                    "symbol": symbol,
                    "from": "selling_puts",
                    "to": "selling_calls",
                    "shares": shares,
                })

            elif state == WheelState.SELLING_CALLS and shares < 100:
                # Shares called away
                await self._handle_called_away(symbol)
                actions.append({
                    "action": "state_transition",
                    "symbol": symbol,
                    "from": "selling_calls",
                    "to": "selling_puts",
                    "note": "Full wheel cycle completed",
                })

        return actions

    async def _handle_assignment(self, symbol: str):
        """Handle put assignment — transition to selling calls."""
        await self.set_state(symbol, WheelState.SELLING_CALLS)

        # Update cost basis with the assignment price
        if self.portfolio and symbol in self.portfolio.positions:
            pos = self.portfolio.positions[symbol]
            if symbol in self.cost_basis:
                self.cost_basis[symbol]["original_cost"] = pos.avg_cost
            else:
                self._init_cost_basis(symbol, pos.avg_cost)

        logger.info(
            f"[{self.name}] {symbol} assigned — now selling covered calls. "
            f"Cost basis: ${self.cost_basis.get(symbol, {}).get('original_cost', 0):.2f}"
        )

        # Log assignment in performance logger
        if self.perf_logger:
            await self.perf_logger.log_trade(
                agent_name=self.name,
                symbol=symbol,
                option_symbol=None,
                trade_type="assignment",
                side="buy",
                quantity=100,
                price=self.cost_basis.get(symbol, {}).get("original_cost", 0),
                status="filled",
                notes="Put assigned — received shares",
            )

    async def _handle_called_away(self, symbol: str):
        """Handle shares called away — log full cycle metrics, restart."""
        await self.set_state(symbol, WheelState.SELLING_PUTS)

        # Calculate full wheel cycle return
        if symbol in self.cost_basis:
            cb = self.cost_basis[symbol]
            cb["cycles_completed"] += 1
            total_premium = cb["total_premium"]
            original_cost = cb["original_cost"]
            cycle_return = (total_premium / original_cost * 100) if original_cost > 0 else 0

            logger.info(
                f"[{self.name}] 🎡 Full wheel cycle completed for {symbol}! "
                f"Premium collected: ${total_premium:.2f}, "
                f"Original cost: ${original_cost:.2f}, "
                f"Cycle return: {cycle_return:.1f}%, "
                f"Total cycles: {cb['cycles_completed']}"
            )

            # Log to performance logger
            if self.perf_logger:
                await self.perf_logger.log_trade(
                    agent_name=self.name,
                    symbol=symbol,
                    option_symbol=None,
                    trade_type="wheel_cycle_complete",
                    side="sell",
                    quantity=100,
                    price=0,
                    premium=total_premium,
                    status="filled",
                    pnl=total_premium,
                    notes=f"Full wheel cycle #{cb['cycles_completed']}: "
                          f"return={cycle_return:.1f}%",
                )

            # Reset premium tracker for next cycle (keep original cost)
            cb["total_premium"] = 0.0
            cb["started_at"] = datetime.utcnow().isoformat()
            await self._save_state_to_db(symbol)

    def _estimate_dte(self, expiration: str) -> Optional[int]:
        """Estimate DTE from expiration date string."""
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            return (exp_date - datetime.now()).days
        except (ValueError, TypeError):
            return None

    # ── REPORTING ─────────────────────────────────────────────────

    async def report(self) -> dict:
        """Enhanced report with wheel-specific state information."""
        base = await super().report()
        base["wheel_states"] = {
            sym: state.value for sym, state in self.wheel_states.items()
        }
        base["cost_basis"] = dict(self.cost_basis)
        return base

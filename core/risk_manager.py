"""
Risk Manager — Position sizing, drawdown limits, collateral checks, conservative mode.

Used by all worker agents before executing trades.
The Lead Agent can switch to conservative mode during high drawdown periods.
"""
from loguru import logger
from config.settings import settings


class RiskManager:
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.max_drawdown = settings.max_drawdown
        self.max_position_pct = settings.max_position_pct
        self.high_water_mark = 0.0
        self.conservative_mode = False  # Lead Agent can toggle this

    # ── Portfolio Health ────────────────────────────────────────────

    async def check_portfolio_health(self) -> bool:
        """Check if portfolio drawdown is within limits."""
        total = self.portfolio.total_value
        if total > self.high_water_mark:
            self.high_water_mark = total

        if self.high_water_mark > 0:
            drawdown = (self.high_water_mark - total) / self.high_water_mark
            if drawdown > self.max_drawdown:
                logger.warning(
                    f"Drawdown {drawdown:.1%} exceeds limit {self.max_drawdown:.1%}. "
                    f"Engaging conservative mode."
                )
                self.conservative_mode = True
                return False
            elif drawdown > self.max_drawdown * 0.5:
                # Preemptive: switch to conservative at 50% of max drawdown
                if not self.conservative_mode:
                    logger.info(f"Drawdown {drawdown:.1%} — switching to conservative mode")
                    self.conservative_mode = True
        return True

    def get_current_drawdown(self) -> float:
        """Get current drawdown as a decimal (e.g. 0.05 = 5%)."""
        if self.high_water_mark <= 0:
            return 0.0
        total = self.portfolio.total_value
        return max(0.0, (self.high_water_mark - total) / self.high_water_mark)

    # ── Position Sizing ────────────────────────────────────────────

    def calculate_position_size(self, symbol: str, price: float) -> int:
        """
        Calculate maximum position size in shares (rounded down to 100-lot).

        In conservative mode, reduces size by 50%.
        """
        max_dollar = self.portfolio.total_value * self.max_position_pct
        if self.conservative_mode:
            max_dollar *= 0.5
        max_shares = int(max_dollar / price) if price > 0 else 0
        return (max_shares // 100) * 100

    def max_contracts(self, strike: float) -> int:
        """
        Calculate max option contracts we can sell given current buying power.

        Each put contract requires strike * 100 in collateral.
        Each call contract requires 100 shares of stock.
        """
        if strike <= 0:
            return 0
        collateral_per_contract = strike * 100
        max_cts = int(self.portfolio.buying_power / collateral_per_contract)
        if self.conservative_mode:
            max_cts = max(1, max_cts // 2)
        return max_cts

    # ── Trade Authorization ────────────────────────────────────────

    def can_sell_put(self, strike: float, qty: int = 1) -> bool:
        """
        Check if we have enough buying power to sell cash-secured puts.

        Args:
            strike: Put strike price
            qty: Number of contracts

        Returns:
            True if sufficient buying power available
        """
        collateral_needed = strike * 100 * qty
        has_collateral = self.portfolio.buying_power >= collateral_needed

        if not has_collateral:
            logger.debug(
                f"Insufficient collateral for {qty}x put @ ${strike}: "
                f"need ${collateral_needed:,.0f}, have ${self.portfolio.buying_power:,.0f}"
            )
        return has_collateral

    def can_sell_call(self, symbol: str, qty: int = 1) -> bool:
        """
        Check if we hold enough shares to sell covered calls.

        Requires 100 shares per contract.

        Args:
            symbol: Underlying stock symbol
            qty: Number of call contracts to sell

        Returns:
            True if we hold sufficient shares
        """
        shares_needed = qty * 100
        position = self.portfolio.positions.get(symbol)

        if not position:
            logger.debug(f"No position in {symbol} — cannot sell covered calls")
            return False

        # Check available shares (not already committed to other calls)
        available_shares = position.quantity - self.portfolio.get_shares_committed_to_calls(symbol)
        has_shares = available_shares >= shares_needed

        if not has_shares:
            logger.debug(
                f"Insufficient shares for {qty}x call on {symbol}: "
                f"need {shares_needed}, available {available_shares}"
            )
        return has_shares

    def can_open_position(self, agent_name: str, max_positions: int) -> bool:
        """
        Check if an agent can open a new position (hasn't hit max).

        Args:
            agent_name: Agent identifier
            max_positions: Maximum allowed positions for this agent

        Returns:
            True if under the position limit
        """
        current_count = self.portfolio.count_open_options_for_agent(agent_name)
        if self.conservative_mode:
            max_positions = max(1, max_positions - 1)

        can_open = current_count < max_positions
        if not can_open:
            logger.debug(
                f"{agent_name} at position limit: {current_count}/{max_positions}"
            )
        return can_open

    # ── Strategy Parameters (adjusted for mode) ────────────────────

    def get_delta_target(self, base_delta: float) -> float:
        """
        Adjust delta target based on market regime.

        Conservative mode uses tighter (lower) deltas for more safety.
        """
        if self.conservative_mode:
            # Reduce delta by ~30% for more OTM strikes
            return round(base_delta * 0.7, 2)
        return base_delta

    def get_profit_target_pct(self, base_pct: float = 0.50) -> float:
        """
        Get profit-taking threshold (% of max premium).

        Conservative mode takes profit earlier.
        """
        if self.conservative_mode:
            return max(0.40, base_pct - 0.15)
        return base_pct

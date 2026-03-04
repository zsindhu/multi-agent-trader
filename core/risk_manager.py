"""Risk Manager — position sizing, drawdown limits, collateral checks."""
from loguru import logger
from config.settings import settings


class RiskManager:
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.max_drawdown = settings.max_drawdown
        self.max_position_pct = settings.max_position_pct
        self.high_water_mark = 0.0

    async def check_portfolio_health(self) -> bool:
        total = self.portfolio.total_value
        if total > self.high_water_mark:
            self.high_water_mark = total
        if self.high_water_mark > 0:
            drawdown = (self.high_water_mark - total) / self.high_water_mark
            if drawdown > self.max_drawdown:
                logger.warning(f"Drawdown {drawdown:.1%} exceeds {self.max_drawdown:.1%}")
                return False
        return True

    def calculate_position_size(self, symbol: str, price: float) -> int:
        max_dollar = self.portfolio.total_value * self.max_position_pct
        max_shares = int(max_dollar / price)
        return (max_shares // 100) * 100

    def can_sell_put(self, strike: float) -> bool:
        collateral_needed = strike * 100
        return self.portfolio.buying_power >= collateral_needed

"""
Application State — Shared services singleton for the API layer.

Initializes broker, portfolio, scanner, strategy manager, and other
services once at startup. Route handlers access them via request.app.state.app.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from core.broker import Broker
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.strategy import StrategyManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from services.alpaca_broker import AlpacaBroker
from services.logger_service import PerformanceLogger
from services.notifier import Notifier
from agents.scanner import ScannerAgent
from agents.trade_journal import TradeJournalAgent


class AppState:
    """
    Holds all shared services for the API.

    Initialized once during FastAPI lifespan startup.
    """

    def __init__(self):
        self.broker: Optional[Broker] = None
        self.portfolio: Optional[Portfolio] = None
        self.risk_manager: Optional[RiskManager] = None
        self.market_feed: Optional[MarketFeed] = None
        self.options_chain: Optional[OptionsChainAnalyzer] = None
        self.strategy_manager: Optional[StrategyManager] = None
        self.perf_logger: Optional[PerformanceLogger] = None
        self.trade_journal: Optional[TradeJournalAgent] = None
        self.scanner: Optional[ScannerAgent] = None
        self.notifier: Optional[Notifier] = None

    async def initialize(self):
        """Create and wire all services."""
        logger.info("[AppState] Initializing services...")

        self.broker = AlpacaBroker()
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(self.portfolio)
        self.market_feed = MarketFeed(broker=self.broker)
        self.options_chain = OptionsChainAnalyzer(broker=self.broker)
        self.strategy_manager = StrategyManager(broker=self.broker)
        self.perf_logger = PerformanceLogger()
        self.trade_journal = TradeJournalAgent()
        self.notifier = Notifier()

        self.scanner = ScannerAgent(
            broker=self.broker,
            market_feed=self.market_feed,
            options_chain=self.options_chain,
        )

        # Sync portfolio
        try:
            await self.portfolio.sync_from_broker(self.broker)
        except Exception as e:
            logger.warning(f"[AppState] Portfolio sync failed: {e}")

        # Refresh regime
        try:
            await self.strategy_manager.refresh_regime()
        except Exception as e:
            logger.warning(f"[AppState] Regime refresh failed: {e}")

        logger.info("[AppState] All services initialized.")

    # ── Convenience methods for routes ──────────────────────────────

    async def get_portfolio_snapshot(self) -> dict:
        """Build a JSON-serializable portfolio snapshot."""
        if not self.portfolio:
            return {}

        # Refresh from broker
        try:
            await self.portfolio.sync_from_broker(self.broker)
        except Exception as e:
            logger.warning(f"[AppState] Refresh failed: {e}")

        positions = []
        for sym, pos in self.portfolio.positions.items():
            positions.append({
                "symbol": sym,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "assigned_to": pos.assigned_to,
                "market_value": pos.quantity * pos.current_price,
            })

        options = []
        for opt in self.portfolio.options:
            options.append({
                "symbol": opt.symbol,
                "option_symbol": opt.option_symbol,
                "contract_type": opt.contract_type,
                "strike": opt.strike,
                "expiration": opt.expiration,
                "quantity": opt.quantity,
                "entry_price": opt.entry_price,
                "current_price": opt.current_price,
                "premium_collected": opt.premium_collected,
                "pnl": opt.pnl,
                "pnl_pct": opt.pnl_pct,
                "is_short": opt.is_short,
                "assigned_to": opt.assigned_to,
            })

        regime = {}
        if self.strategy_manager:
            regime = self.strategy_manager.get_regime_summary()

        return {
            "cash": self.portfolio.cash,
            "buying_power": self.portfolio.buying_power,
            "equity": self.portfolio.equity,
            "total_value": self.portfolio.total_value,
            "total_premium_collected": self.portfolio.total_premium_collected,
            "positions": positions,
            "options": options,
            "regime": regime,
            "last_updated": self.portfolio.last_updated.isoformat(),
        }

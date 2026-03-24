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
from services.market_regime import MarketRegimeService
from services.earnings_calendar import EarningsCalendarService
from services.performance_analyst import PerformanceAnalystService
from services.news_feed import NewsFeedService
from services.llm_service import LLMService
from agents.scanner import ScannerAgent
from agents.trade_journal import TradeJournalAgent
from agents.lead_agent import LeadAgent
from agents.worker_cc import CoveredCallWorker
from agents.worker_csp import CashSecuredPutWorker
from agents.worker_wheel import WheelWorker


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
        self.broker_is_paper: bool = True
        self.lead_agent: Optional[LeadAgent] = None
        self.auto_approve: bool = False
        self.account_status: dict = {}
        self.regime_service: Optional[MarketRegimeService] = None
        self.earnings_service: Optional[EarningsCalendarService] = None
        self.performance_service: Optional[PerformanceAnalystService] = None
        self.news_service: Optional[NewsFeedService] = None
        self.llm_service: Optional[LLMService] = None

    async def initialize(self):
        """Create and wire all services."""
        from config.settings import settings

        logger.info("[AppState] Initializing services...")

        self.broker_is_paper = settings.trading_mode == "paper"
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

        # ── Startup verification ─────────────────────────────────────────
        await self._verify_account()

        # Build workers and lead agent for the proposal system
        cc_worker = CoveredCallWorker(
            broker=self.broker,
            portfolio=self.portfolio,
            market_feed=self.market_feed,
            options_chain=self.options_chain,
            risk_manager=self.risk_manager,
            perf_logger=self.perf_logger,
            trade_journal=self.trade_journal,
        )
        csp_worker = CashSecuredPutWorker(
            broker=self.broker,
            portfolio=self.portfolio,
            market_feed=self.market_feed,
            options_chain=self.options_chain,
            risk_manager=self.risk_manager,
            perf_logger=self.perf_logger,
            trade_journal=self.trade_journal,
        )
        wheel_worker = WheelWorker(
            broker=self.broker,
            portfolio=self.portfolio,
            market_feed=self.market_feed,
            options_chain=self.options_chain,
            risk_manager=self.risk_manager,
            perf_logger=self.perf_logger,
            trade_journal=self.trade_journal,
        )
        # ── Intelligence services ────────────────────────────────────────
        self.regime_service = MarketRegimeService(
            broker=self.broker,
            scanner=self.scanner,
            strategy_manager=self.strategy_manager,
        )
        self.earnings_service = EarningsCalendarService()
        self.performance_service = PerformanceAnalystService()
        self.news_service = NewsFeedService()
        self.llm_service = LLMService()

        self.lead_agent = LeadAgent(
            workers=[cc_worker, csp_worker, wheel_worker],
            risk_manager=self.risk_manager,
            performance_logger=self.perf_logger,
            broker=self.broker,
            portfolio=self.portfolio,
            market_feed=self.market_feed,
            scanner=self.scanner,
            strategy_manager=self.strategy_manager,
            notifier=self.notifier,
            # Phase B
            llm_service=self.llm_service,
            regime_service=self.regime_service,
            earnings_service=self.earnings_service,
            performance_service=self.performance_service,
            news_service=self.news_service,
            trade_journal=self.trade_journal,
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

    async def reinitialize_broker(self):
        """
        Reinitialize the broker and dependent services after a mode switch.

        Called when the user toggles between paper and live trading.
        The settings module must already have the updated trading_mode
        before this method is called.
        """
        from config.settings import settings

        new_mode = settings.trading_mode
        logger.info(f"[AppState] Reinitializing broker for {new_mode.upper()} mode...")

        self.broker_is_paper = new_mode == "paper"

        # Create a fresh broker with the new settings
        self.broker = AlpacaBroker()

        # Re-wire dependent services to use the new broker instance
        self.market_feed = MarketFeed(broker=self.broker)
        self.options_chain = OptionsChainAnalyzer(broker=self.broker)
        self.strategy_manager = StrategyManager(broker=self.broker)

        self.scanner = ScannerAgent(
            broker=self.broker,
            market_feed=self.market_feed,
            options_chain=self.options_chain,
        )

        # Sync portfolio from the new broker (different account!)
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(self.portfolio)
        try:
            await self.portfolio.sync_from_broker(self.broker)
        except Exception as e:
            logger.warning(f"[AppState] Portfolio sync failed after mode switch: {e}")

        # Refresh regime
        try:
            await self.strategy_manager.refresh_regime()
        except Exception as e:
            logger.warning(f"[AppState] Regime refresh failed after mode switch: {e}")

        logger.info(f"[AppState] Broker reinitialized for {new_mode.upper()} mode.")

    # ── Account verification ─────────────────────────────────────────

    async def _verify_account(self):
        """
        Verify Alpaca connection and options trading configuration at startup.

        Logs clear errors with fix instructions. Does NOT crash — runs in degraded
        mode where the Scanner works but proposals aren't generated if there are issues.
        """
        status = {
            "connection": "failed",
            "account_status": None,
            "options_enabled": False,
            "options_level": None,
        }

        try:
            raw_account = self.broker.trading.get_account()
            status["connection"] = "ok"

            account_status = str(getattr(raw_account, "status", "UNKNOWN")).split(".")[-1]
            status["account_status"] = account_status

            equity = float(getattr(raw_account, "equity", 0) or 0)
            buying_power = float(getattr(raw_account, "buying_power", 0) or 0)
            options_level_raw = getattr(raw_account, "options_approved_level", None)
            options_level = int(options_level_raw) if options_level_raw is not None else None
            status["options_level"] = options_level
            status["options_enabled"] = options_level is not None and options_level >= 2

            mode = "PAPER" if self.broker_is_paper else "LIVE"
            logger.info(
                f"[AppState] Alpaca {mode} account connected: "
                f"status={account_status}, equity=${equity:,.0f}, "
                f"buying_power=${buying_power:,.0f}, "
                f"options_level={options_level}"
            )

            if account_status != "ACTIVE":
                logger.error(
                    f"[AppState] Account status is {account_status} (expected ACTIVE). "
                    "Proposal generation disabled until account is active."
                )
            if options_level is None or options_level == 0:
                logger.error(
                    "[AppState] Options trading NOT enabled on this account. "
                    "Go to Alpaca dashboard → Account → Configure → Enable options trading. "
                    "Proposal generation will not work until options are enabled."
                )
            elif options_level == 1:
                logger.error(
                    "[AppState] Options level 1 — cannot sell puts or calls. "
                    "Upgrade to level 2 in Alpaca dashboard. "
                    "Proposal generation will not work until level is upgraded."
                )
            elif options_level >= 2:
                logger.info(
                    f"[AppState] Options level {options_level} ✓ — "
                    "can sell covered calls and cash-secured puts."
                )

        except Exception as e:
            status["connection"] = "failed"
            error_str = str(e)
            if "forbidden" in error_str.lower() or "401" in error_str or "403" in error_str:
                logger.error(
                    "[AppState] Alpaca API credentials rejected. "
                    "Check ALPACA_API_KEY and ALPACA_SECRET_KEY in your .env file."
                )
            else:
                logger.error(
                    f"[AppState] Failed to connect to Alpaca: {e}. "
                    "Running in degraded mode — Scanner only."
                )

        self.account_status = status

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

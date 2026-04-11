"""
Core Bootstrap — Single source of truth for service initialization.

Both main.py (agents entrypoint) and api/state.py (FastAPI entrypoint) call
build_services() to wire up all dependencies. This eliminates the drift bug
where adding a new service to one entrypoint but not the other causes crashes.
"""
from __future__ import annotations

from agents import (
    CoveredCallWorker,
    CashSecuredPutWorker,
    WheelWorker,
    TradeJournalAgent,
    ScannerAgent,
)
from agents.lead_agent import LeadAgent
from agents.breadth_analyst import BreadthAnalyst
from agents.tier2a_prefilter import Tier2aPrefilter
from services.alpaca_broker import AlpacaBroker
from services.logger_service import PerformanceLogger
from services.notifier import Notifier
from services.market_regime import MarketRegimeService
from services.vix_service import VIXService
from services.earnings_calendar import EarningsCalendarService
from services.performance_analyst import PerformanceAnalystService
from services.news_feed import NewsFeedService
from services.llm_service import LLMService
from services.order_reconciler import OrderReconciler
from core.broker import Broker
from core.risk_manager import RiskManager
from core.portfolio import Portfolio
from core.strategy import StrategyManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer


class Services:
    """Container for all initialized services. Attribute names match the
    existing AppState fields so api/state.py can copy them across."""

    def __init__(self):
        self.broker: Broker = None
        self.portfolio: Portfolio = None
        self.risk_manager: RiskManager = None
        self.market_feed: MarketFeed = None
        self.options_chain: OptionsChainAnalyzer = None
        self.strategy_manager: StrategyManager = None
        self.perf_logger: PerformanceLogger = None
        self.trade_journal: TradeJournalAgent = None
        self.scanner: ScannerAgent = None
        self.notifier: Notifier = None
        self.vix_service: VIXService = None
        self.regime_service: MarketRegimeService = None
        self.earnings_service: EarningsCalendarService = None
        self.performance_service: PerformanceAnalystService = None
        self.news_service: NewsFeedService = None
        self.llm_service: LLMService = None
        self.order_reconciler: OrderReconciler = None
        self.lead_agent: LeadAgent = None
        # Workers (exposed so main.py can reference them directly if needed)
        self.worker_cc: CoveredCallWorker = None
        self.worker_csp: CashSecuredPutWorker = None
        self.worker_wheel: WheelWorker = None
        self.breadth_analyst: BreadthAnalyst = None
        self.tier2a_prefilter: Tier2aPrefilter = None


def build_services() -> Services:
    """
    Create and wire all services. Returns a Services container.

    This is intentionally synchronous — it only instantiates objects.
    Async startup steps (portfolio sync, regime refresh) are the caller's
    responsibility so each entrypoint can handle errors its own way.
    """
    s = Services()

    # ── Core ────────────────────────────────────────────────────
    s.broker = AlpacaBroker()
    s.portfolio = Portfolio()
    s.risk_manager = RiskManager(s.portfolio)
    s.perf_logger = PerformanceLogger()
    s.vix_service = VIXService(broker=s.broker)
    s.strategy_manager = StrategyManager(broker=s.broker, vix_service=s.vix_service)
    s.notifier = Notifier()

    # ── Data Layer ──────────────────────────────────────────────
    s.market_feed = MarketFeed(broker=s.broker)
    s.options_chain = OptionsChainAnalyzer(broker=s.broker)

    # ── Agents ──────────────────────────────────────────────────
    s.trade_journal = TradeJournalAgent()
    s.scanner = ScannerAgent(
        broker=s.broker,
        market_feed=s.market_feed,
        options_chain=s.options_chain,
    )

    # ── Breadth Analyst ────────────────────────────────────────
    s.breadth_analyst = BreadthAnalyst(broker=s.broker)

    # ── Tier 2a Pre-filter ──────────────────────────────────────
    s.tier2a_prefilter = Tier2aPrefilter(broker=s.broker, market_feed=s.market_feed)

    # ── Intelligence Services ───────────────────────────────────
    s.regime_service = MarketRegimeService(
        broker=s.broker,
        scanner=s.scanner,
        strategy_manager=s.strategy_manager,
        vix_service=s.vix_service,
    )
    s.earnings_service = EarningsCalendarService()
    s.performance_service = PerformanceAnalystService()
    s.news_service = NewsFeedService()
    s.llm_service = LLMService()

    # ── Order Reconciler ────────────────────────────────────────
    s.order_reconciler = OrderReconciler(
        broker=s.broker,
        trade_journal=s.trade_journal,
        portfolio=s.portfolio,
    )

    # ── Worker Agents ───────────────────────────────────────────
    worker_kwargs = dict(
        broker=s.broker,
        portfolio=s.portfolio,
        risk_manager=s.risk_manager,
        market_feed=s.market_feed,
        options_chain=s.options_chain,
        perf_logger=s.perf_logger,
        trade_journal=s.trade_journal,
        strategy_manager=s.strategy_manager,
        scanner=s.scanner,
    )
    s.worker_cc = CoveredCallWorker(**worker_kwargs)
    s.worker_csp = CashSecuredPutWorker(**worker_kwargs)
    s.worker_wheel = WheelWorker(**worker_kwargs)

    # ── Lead Agent ──────────────────────────────────────────────
    s.lead_agent = LeadAgent(
        workers=[s.worker_cc, s.worker_csp, s.worker_wheel],
        risk_manager=s.risk_manager,
        performance_logger=s.perf_logger,
        broker=s.broker,
        portfolio=s.portfolio,
        market_feed=s.market_feed,
        scanner=s.scanner,
        strategy_manager=s.strategy_manager,
        notifier=s.notifier,
        llm_service=s.llm_service,
        regime_service=s.regime_service,
        earnings_service=s.earnings_service,
        performance_service=s.performance_service,
        news_service=s.news_service,
        trade_journal=s.trade_journal,
        order_reconciler=s.order_reconciler,
    )

    return s

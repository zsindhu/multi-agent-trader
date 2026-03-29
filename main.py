"""
Premium Trader — Main entry point.

Initializes all agents with full dependency injection and starts the orchestration loop.
The Lead Agent runs on a scheduled interval, coordinating all workers.
The Scanner Agent runs 2x daily (market open + midday) to refresh the opportunity universe.
Strategy regime detection refreshes each cycle. Discord notifications fire on trades/risk events.
"""
import asyncio
import argparse
from datetime import datetime, timezone, timedelta

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler


def _is_market_hours() -> bool:
    """True if US equities markets are currently open (ET, weekdays 9:30–16:00)."""
    now = datetime.now(timezone(timedelta(hours=-4)))  # ET (approx; ignores DST edge)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 570 <= t <= 960  # 9:30 = 570, 16:00 = 960


def _is_key_cycle_time() -> bool:
    """Full LLM analysis runs at 3 key times: open (9:35), midday (12:30), near-close (15:45)."""
    now = datetime.now(timezone(timedelta(hours=-4)))
    t = now.hour * 60 + now.minute
    return any(abs(t - target) < 8 for target in [575, 750, 945])

from agents import (
    CoveredCallWorker,
    CashSecuredPutWorker,
    WheelWorker,
    TradeJournalAgent,
    ScannerAgent,
)
from agents.lead_agent import LeadAgent
from services.alpaca_broker import AlpacaBroker
from services.logger_service import PerformanceLogger
from services.notifier import Notifier
from services.market_regime import MarketRegimeService
from services.earnings_calendar import EarningsCalendarService
from services.performance_analyst import PerformanceAnalystService
from services.news_feed import NewsFeedService
from services.llm_service import LLMService
from core.broker import Broker
from core.risk_manager import RiskManager
from core.portfolio import Portfolio
from core.strategy import StrategyManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from config.settings import settings


async def run_scanner_cycle(scanner: ScannerAgent, regime_service: "MarketRegimeService" = None):
    """Run a full Scanner cycle: scan → evaluate → persist to DB. Then refresh regime."""
    try:
        logger.info("[Main] ── Scanner cycle starting ──")
        raw = await scanner.scan()
        scored = await scanner.evaluate(raw)
        await scanner.execute(scored)
        logger.info(f"[Main] ── Scanner cycle done — {len(scored)} opportunities ──")
    except Exception as e:
        logger.error(f"[Main] Scanner cycle failed: {e}")

    if regime_service:
        try:
            await regime_service.compute()
        except Exception as e:
            logger.warning(f"[Main] Regime compute failed: {e}")


async def main(mode: str = "paper"):
    logger.info(f"Premium Trader starting in {mode} mode...")

    # ── Core Services ─────────────────────────────────────────────
    broker: Broker = AlpacaBroker()
    portfolio = Portfolio()
    risk_manager = RiskManager(portfolio)
    perf_logger = PerformanceLogger()

    # ── Strategy & Notifications ───────────────────────────────────
    strategy_manager = StrategyManager(broker=broker)
    notifier = Notifier()

    # ── Data Layer ────────────────────────────────────────────────
    market_feed = MarketFeed(broker=broker)
    options_chain = OptionsChainAnalyzer(broker=broker)

    # ── Trade Journal (observer agent) ────────────────────────────
    trade_journal = TradeJournalAgent()

    # ── Scanner Agent (runs 2x daily) ─────────────────────────────
    scanner = ScannerAgent(
        broker=broker,
        market_feed=market_feed,
        options_chain=options_chain,
    )

    # ── Intelligence Services ──────────────────────────────────────
    regime_service = MarketRegimeService(broker=broker, scanner=scanner, strategy_manager=strategy_manager)
    earnings_service = EarningsCalendarService()
    performance_service = PerformanceAnalystService()
    news_service = NewsFeedService()
    llm_service = LLMService()

    # ── Worker Agents (fully injected) ────────────────────────────
    worker_cc = CoveredCallWorker(
        broker=broker,
        portfolio=portfolio,
        risk_manager=risk_manager,
        market_feed=market_feed,
        options_chain=options_chain,
        perf_logger=perf_logger,
        trade_journal=trade_journal,
    )

    worker_csp = CashSecuredPutWorker(
        broker=broker,
        portfolio=portfolio,
        risk_manager=risk_manager,
        market_feed=market_feed,
        options_chain=options_chain,
        perf_logger=perf_logger,
        trade_journal=trade_journal,
    )

    worker_wheel = WheelWorker(
        broker=broker,
        portfolio=portfolio,
        risk_manager=risk_manager,
        market_feed=market_feed,
        options_chain=options_chain,
        perf_logger=perf_logger,
        trade_journal=trade_journal,
    )

    # ── Lead Agent (orchestrator) — receives Scanner, Strategy, Notifier ──
    lead = LeadAgent(
        workers=[worker_cc, worker_csp, worker_wheel],
        risk_manager=risk_manager,
        performance_logger=perf_logger,
        broker=broker,
        portfolio=portfolio,
        market_feed=market_feed,
        scanner=scanner,
        strategy_manager=strategy_manager,
        notifier=notifier,
        # Phase B — LLM reasoning engine + intelligence services
        llm_service=llm_service,
        regime_service=regime_service,
        earnings_service=earnings_service,
        performance_service=performance_service,
        news_service=news_service,
        trade_journal=trade_journal,
    )

    # ── Sync portfolio state from broker ──────────────────────────
    await portfolio.sync_from_broker(broker)
    logger.info(
        f"Portfolio: ${portfolio.equity:,.2f} equity, "
        f"${portfolio.cash:,.2f} cash, "
        f"${portfolio.buying_power:,.2f} buying power, "
        f"{len(portfolio.positions)} stocks, "
        f"{len(portfolio.options)} options"
    )

    # ── Initial regime detection ──────────────────────────────────
    await strategy_manager.refresh_regime()
    logger.info(
        f"Market regime: {strategy_manager.regime.value} "
        f"(VIX≈{strategy_manager.vix_level:.1f})"
    )

    # ── Run initial Scanner + Regime cycle before first trade cycle ──
    await run_scanner_cycle(scanner, regime_service)

    # ── Scheduled Execution Loop ──────────────────────────────────
    scheduler = AsyncIOScheduler()

    # Lead Agent: market-hours gated wrapper
    # Full LLM cycle: 3x/day at key times (open, midday, near-close)
    # Market hours non-key: rule-based position management only (no LLM)
    # Off-hours: portfolio sync only (no LLM, no trading)
    async def lead_cycle_wrapper():
        if not _is_market_hours():
            try:
                await lead.portfolio.sync_from_broker(lead.broker)
                logger.debug("[Scheduler] Off-hours sync complete.")
            except Exception as e:
                logger.debug(f"[Scheduler] Off-hours sync skipped: {e}")
            return
        if _is_key_cycle_time():
            await lead.run_cycle()
        else:
            await lead._rule_based_cycle()

    scheduler.add_job(lead_cycle_wrapper, "interval", minutes=settings.scan_interval_minutes)

    # Scanner + Regime: runs 2x daily at market open (9:35 ET) and midday (12:30 ET)
    scheduler.add_job(
        run_scanner_cycle,
        "cron",
        args=[scanner, regime_service],
        hour="9,12",
        minute="35,30",
        timezone="US/Eastern",
        id="scanner_morning",
    )

    # Earnings + News: fetch before market open (8:00 AM and 9:00 AM ET)
    async def _refresh_earnings():
        symbols = [o["symbol"] for o in await scanner.get_top_opportunities()] or []
        await earnings_service.refresh(symbols[:50])

    async def _refresh_news_morning():
        symbols = [o["symbol"] for o in await scanner.get_top_opportunities()] or []
        await news_service.refresh(symbols[:20])

    scheduler.add_job(
        _refresh_earnings,
        "cron",
        hour="8",
        minute="0",
        timezone="US/Eastern",
        id="earnings_refresh",
    )
    scheduler.add_job(
        _refresh_news_morning,
        "cron",
        hour="9",
        minute="0",
        timezone="US/Eastern",
        id="news_morning",
    )
    scheduler.add_job(
        _refresh_news_morning,
        "cron",
        hour="12",
        minute="0",
        timezone="US/Eastern",
        id="news_midday",
    )

    # Performance analytics: runs after market close (4:30 PM ET)
    scheduler.add_job(
        performance_service.compute_all,
        "cron",
        hour="16",
        minute="30",
        timezone="US/Eastern",
        id="performance_daily",
    )

    # Daily summary at market close (4:05 PM ET)
    scheduler.add_job(
        lead.send_daily_summary,
        "cron",
        hour="16",
        minute="5",
        timezone="US/Eastern",
        id="daily_summary",
    )

    scheduler.start()
    logger.info(
        f"Orchestrator running every {settings.scan_interval_minutes} min, "
        f"Scanner at 9:35 ET + 12:30 ET, Daily summary at 4:05 PM ET.  Ctrl+C to stop."
    )

    # Run first orchestration cycle immediately
    try:
        await lead.run_cycle()
    except Exception as e:
        logger.error(f"Initial cycle failed: {e}")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Premium Trader — Multi-Agent Options System")
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    args = parser.parse_args()
    asyncio.run(main(args.mode))

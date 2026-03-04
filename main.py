"""
Premium Trader — Main entry point.

Initializes all agents with full dependency injection and starts the orchestration loop.
The Lead Agent runs on a scheduled interval, coordinating all workers.
The Scanner Agent runs 2x daily (market open + midday) to refresh the opportunity universe.
"""
import asyncio
import argparse

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
from core.broker import Broker
from core.risk_manager import RiskManager
from core.portfolio import Portfolio
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from config.settings import settings


async def run_scanner_cycle(scanner: ScannerAgent):
    """Run a full Scanner cycle: scan → evaluate → persist to DB."""
    try:
        logger.info("[Main] ── Scanner cycle starting ──")
        raw = await scanner.scan()
        scored = await scanner.evaluate(raw)
        await scanner.execute(scored)
        logger.info(f"[Main] ── Scanner cycle done — {len(scored)} opportunities ──")
    except Exception as e:
        logger.error(f"[Main] Scanner cycle failed: {e}")


async def main(mode: str = "paper"):
    logger.info(f"Premium Trader starting in {mode} mode...")

    # ── Core Services ─────────────────────────────────────────────
    broker: Broker = AlpacaBroker()
    portfolio = Portfolio()
    risk_manager = RiskManager(portfolio)
    perf_logger = PerformanceLogger()

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

    # ── Lead Agent (orchestrator) — receives Scanner for dynamic assignments ──
    lead = LeadAgent(
        workers=[worker_cc, worker_csp, worker_wheel],
        risk_manager=risk_manager,
        performance_logger=perf_logger,
        broker=broker,
        portfolio=portfolio,
        market_feed=market_feed,
        scanner=scanner,
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

    # ── Run initial Scanner cycle before first trade cycle ────────
    await run_scanner_cycle(scanner)

    # ── Scheduled Execution Loop ──────────────────────────────────
    scheduler = AsyncIOScheduler()

    # Lead Agent: runs every N minutes (default 15)
    scheduler.add_job(lead.run_cycle, "interval", minutes=settings.scan_interval_minutes)

    # Scanner Agent: runs 2x daily at market open (9:35 ET) and midday (12:30 ET)
    scheduler.add_job(
        run_scanner_cycle,
        "cron",
        args=[scanner],
        hour="9,12",
        minute="35,30",
        timezone="US/Eastern",
        id="scanner_morning",
    )

    scheduler.start()
    logger.info(
        f"Orchestrator running every {settings.scan_interval_minutes} min, "
        f"Scanner at 9:35 ET + 12:30 ET.  Ctrl+C to stop."
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

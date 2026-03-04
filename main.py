"""Premium Trader — Main entry point. Initializes agents and starts orchestration loop."""
import asyncio
import argparse
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from agents import CoveredCallWorker, CashSecuredPutWorker, WheelWorker
from agents.lead_agent import LeadAgent
from services.alpaca_broker import AlpacaBroker
from services.logger_service import PerformanceLogger
from core.risk_manager import RiskManager
from core.portfolio import Portfolio
from config.settings import settings


async def main(mode: str = "paper"):
    logger.info(f"Premium Trader starting in {mode} mode...")
    broker = AlpacaBroker()
    portfolio = Portfolio()
    risk_manager = RiskManager(portfolio)
    perf_logger = PerformanceLogger()

    worker_cc = CoveredCallWorker()
    worker_csp = CashSecuredPutWorker()
    worker_wheel = WheelWorker()

    lead = LeadAgent(
        workers=[worker_cc, worker_csp, worker_wheel],
        risk_manager=risk_manager,
        performance_logger=perf_logger,
    )

    account = await broker.get_account()
    portfolio.cash = account["cash"]
    portfolio.buying_power = account["buying_power"]
    portfolio.equity = account["equity"]
    logger.info(f"Portfolio: ${portfolio.equity:,.2f} equity, ${portfolio.cash:,.2f} cash")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(lead.run_cycle, "interval", minutes=settings.scan_interval_minutes)
    scheduler.start()
    logger.info(f"Running every {settings.scan_interval_minutes} min. Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    args = parser.parse_args()
    asyncio.run(main(args.mode))

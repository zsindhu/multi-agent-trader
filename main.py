"""
Premium Trader — Main entry point.

Initializes all agents via the shared bootstrap and starts the orchestration loop.
The Lead Agent runs on a scheduled interval, coordinating all workers.
The Scanner Agent runs 2x daily (market open + midday) to refresh the opportunity universe.
Strategy regime detection refreshes each cycle. Discord notifications fire on trades/risk events.
"""
import asyncio
import argparse
from datetime import datetime, timezone, timedelta

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.bootstrap import build_services
from config.settings import settings


def _is_market_hours() -> bool:
    """True if US equities markets are currently open (ET, weekdays 9:30-16:00)."""
    now = datetime.now(timezone(timedelta(hours=-4)))  # ET (approx; ignores DST edge)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 570 <= t <= 960  # 9:30 = 570, 16:00 = 960


async def _write_equity_snapshot(portfolio):
    """Persist current portfolio equity to the equity_snapshots table."""
    from core.database import AsyncSessionLocal
    from models.equity_snapshot import EquitySnapshot
    try:
        async with AsyncSessionLocal() as session:
            session.add(EquitySnapshot(
                equity=portfolio.equity,
                cash=portfolio.cash,
                buying_power=portfolio.buying_power,
            ))
            await session.commit()
    except Exception as e:
        logger.warning(f"[Main] Equity snapshot write failed: {e}")


async def _run_breadth_analyst_sweep(breadth_analyst):
    """Run the Breadth Analyst's daily Tier 1 eligibility sweep."""
    try:
        logger.info("[Main] -- Breadth Analyst daily sweep starting --")
        result = await breadth_analyst.run_daily_sweep()
        logger.info(
            f"[Main] -- Breadth Analyst sweep done -- "
            f"{result.get('passed', 0)} passed, "
            f"{result.get('rejected', 0)} rejected, "
            f"{result.get('near_misses', 0)} near-misses --"
        )
    except Exception as e:
        logger.error(f"[Main] Breadth Analyst sweep failed: {e}")


async def _run_tier2a_sweep(tier2a_prefilter):
    """Run the Tier 2a mechanical pre-filter over today's Tier 1 universe."""
    try:
        logger.info("[Main] -- Tier 2a sweep starting --")
        result = await tier2a_prefilter.run_sweep()
        logger.info(
            f"[Main] -- Tier 2a sweep done -- "
            f"{result.get('passed', 0)} passed, "
            f"{result.get('rejected', 0)} rejected, "
            f"{result.get('near_misses', 0)} near-misses --"
        )
    except Exception as e:
        logger.error(f"[Main] Tier 2a sweep failed: {e}")


async def run_scanner_cycle(scanner, regime_service=None):
    """Run a full Scanner cycle: scan -> evaluate -> persist to DB. Then refresh regime."""
    try:
        logger.info("[Main] -- Scanner cycle starting --")
        raw = await scanner.scan()
        scored = await scanner.evaluate(raw)
        await scanner.execute(scored)
        logger.info(f"[Main] -- Scanner cycle done -- {len(scored)} opportunities --")
    except Exception as e:
        logger.error(f"[Main] Scanner cycle failed: {e}")

    if regime_service:
        try:
            await regime_service.compute()
        except Exception as e:
            logger.warning(f"[Main] Regime compute failed: {e}")


async def main(mode: str = "paper"):
    logger.info(f"Premium Trader starting in {mode} mode...")

    # ── Build all services from shared bootstrap ──────────────────
    svc = build_services()

    # Convenient aliases
    portfolio = svc.portfolio
    broker = svc.broker
    lead = svc.lead_agent
    scanner = svc.scanner
    strategy_manager = svc.strategy_manager
    regime_service = svc.regime_service
    earnings_service = svc.earnings_service
    news_service = svc.news_service
    performance_service = svc.performance_service

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
        f"(VIX~{strategy_manager.vix_level:.1f})"
    )

    # ── Run initial Scanner + Regime cycle before first trade cycle ──
    await run_scanner_cycle(scanner, regime_service)

    # ── Scheduled Execution Loop ──────────────────────────────────
    scheduler = AsyncIOScheduler()

    async def lead_cycle_wrapper():
        if not _is_market_hours():
            try:
                await lead.portfolio.sync_from_broker(lead.broker)
                logger.debug("[Scheduler] Off-hours sync complete.")
            except Exception as e:
                logger.debug(f"[Scheduler] Off-hours sync skipped: {e}")
            return
        # During market hours: always run the full LLM cycle. No parallel
        # rules-based path. If the LLM fails, run_cycle falls back to safe mode
        # (emergency-only) — there is no rules-based fallback.
        await lead.run_cycle()
        await _write_equity_snapshot(lead.portfolio)

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

    # Breadth Analyst sweep: runs daily at 8:00 AM ET (before market open)
    scheduler.add_job(
        _run_breadth_analyst_sweep,
        "cron",
        args=[svc.breadth_analyst],
        hour="8",
        minute="0",
        timezone="US/Eastern",
        id="breadth_analyst_sweep",
    )

    # Tier 2a pre-filter: runs 3x daily during market hours (10:00, 12:00, 14:00 ET)
    scheduler.add_job(
        _run_tier2a_sweep,
        "cron",
        args=[svc.tier2a_prefilter],
        hour="10,12,14",
        minute="0",
        timezone="US/Eastern",
        id="tier2a_sweep",
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
        f"Breadth Analyst at 8:00 ET, Tier 2a at 10/12/14 ET, "
        f"Scanner at 9:35+12:30 ET, Summary at 4:05 PM ET. Ctrl+C to stop."
    )

    # Run first orchestration cycle immediately
    try:
        await lead.run_cycle()
        await _write_equity_snapshot(portfolio)
    except Exception as e:
        logger.error(f"Initial cycle failed: {e}")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Premium Trader -- Multi-Agent Options System")
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    args = parser.parse_args()
    asyncio.run(main(args.mode))

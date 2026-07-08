"""
One-time repair for the July 2026 outcome-data audit.

The order reconciler used to stamp trades whose ORDER expired unfilled with
status="expired", and the outcome labeler then counted them as options that
expired worthless — labeling 70 unfilled orders (both entry and close legs)
as $6,261.70 of phantom wins. This script:

1. Reclassifies every status="expired" trade to "order_expired" (verified
   against Alpaca on 2026-07-07: all of them correspond to unfilled orders).
2. Deletes ALL trade_outcomes rows and their embeddings — the surviving
   labels also used submission limit prices instead of fills.
3. Re-runs the fixed OutcomeLabeler to rebuild outcomes from fill data.

Usage (inside the app container):
    python scripts/repair_outcome_data.py [--dry-run]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import delete, func, select, update

from core.database import AsyncSessionLocal
from models.trade import Trade
from models.trade_outcome import TradeOutcome
from models.reasoning_embedding import ReasoningEmbedding
from services.outcome_labeler import OutcomeLabeler


async def repair(dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        expired_count = (
            await session.execute(
                select(func.count()).select_from(Trade).where(Trade.status == "expired")
            )
        ).scalar()
        outcome_count = (
            await session.execute(select(func.count()).select_from(TradeOutcome))
        ).scalar()
        emb_count = (
            await session.execute(
                select(func.count())
                .select_from(ReasoningEmbedding)
                .where(ReasoningEmbedding.source_table == "trade_outcomes")
            )
        ).scalar()

    logger.info(
        f"[Repair] Will reclassify {expired_count} 'expired' trades to 'order_expired', "
        f"delete {outcome_count} outcomes and {emb_count} outcome embeddings"
    )
    if dry_run:
        logger.info("[Repair] Dry run — no writes. Labeler dry run follows:")
        await OutcomeLabeler().run(dry_run=True)
        return

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Trade).where(Trade.status == "expired").values(status="order_expired")
        )
        await session.execute(delete(TradeOutcome))
        await session.execute(
            delete(ReasoningEmbedding).where(
                ReasoningEmbedding.source_table == "trade_outcomes"
            )
        )
        await session.commit()
    logger.info("[Repair] Reclassified and purged. Relabeling from fill data...")

    summary = await OutcomeLabeler().run(dry_run=False)
    logger.info(f"[Repair] Relabel complete: {summary}")

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    TradeOutcome.outcome,
                    func.count(),
                    func.coalesce(func.sum(TradeOutcome.pnl_dollars), 0.0),
                ).group_by(TradeOutcome.outcome)
            )
        ).all()
        funnel = (
            await session.execute(
                select(func.count())
                .select_from(TradeOutcome)
                .where(TradeOutcome.funnel_driven == True)  # noqa: E712
                .where(TradeOutcome.outcome.in_(("win", "loss")))
            )
        ).scalar()
    for outcome, count, pnl in rows:
        logger.info(f"[Repair]   {outcome}: {count} trades, ${pnl:.2f}")
    logger.info(f"[Repair] Funnel-driven win/loss outcomes (counts toward 50): {funnel}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(repair(args.dry_run))

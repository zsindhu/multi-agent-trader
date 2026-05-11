"""
Clean ghost trades — Mark pre-funnel submitted trades with no order_id as cancelled.

These are 21 trades from March 2026 that were submitted but never executed.
They pollute the trades table and dashboard with noise.

Usage:
  python scripts/clean_ghost_trades.py              # Preview what would be updated
  python scripts/clean_ghost_trades.py --execute    # Actually update the records
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def main():
    parser = argparse.ArgumentParser(description="Clean ghost trades")
    parser.add_argument("--execute", action="store_true", help="Actually update records (default: preview only)")
    args = parser.parse_args()

    from sqlalchemy import select, update, func
    from core.database import AsyncSessionLocal
    from models.trade import Trade

    async with AsyncSessionLocal() as session:
        # Find ghost trades: submitted, no order_id, before funnel cutover
        result = await session.execute(
            select(Trade)
            .where(Trade.status == "submitted")
            .where(Trade.order_id.is_(None))
            .where(Trade.created_at < "2026-04-01")
            .order_by(Trade.created_at)
        )
        ghosts = list(result.scalars().all())

        print(f"\nFound {len(ghosts)} ghost trades:\n")
        for t in ghosts:
            print(f"  #{t.id:4d}  {t.symbol:6s}  {t.trade_type:15s}  {t.status:10s}  {t.created_at}  order_id={t.order_id}")

        if not ghosts:
            print("Nothing to clean.")
            return

        if args.execute:
            ghost_ids = [t.id for t in ghosts]
            await session.execute(
                update(Trade)
                .where(Trade.id.in_(ghost_ids))
                .values(status="cancelled")
            )
            await session.commit()
            print(f"\nMarked {len(ghosts)} trades as cancelled.")
        else:
            print(f"\nDry run — add --execute to update these {len(ghosts)} trades to status='cancelled'")


if __name__ == "__main__":
    asyncio.run(main())

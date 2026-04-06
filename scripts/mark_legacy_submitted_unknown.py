"""
One-shot script: mark legacy "submitted" trades with no order_id as "unknown".

These trades were created before order reconciliation was implemented. They have
no order_id, so the reconciler can never match them to a fill. Leaving them as
"submitted" pollutes performance metrics.

Usage:
    python scripts/mark_legacy_submitted_unknown.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update, func
from core.database import AsyncSessionLocal
from models.trade import Trade


async def main():
    async with AsyncSessionLocal() as session:
        # Find affected trades
        result = await session.execute(
            select(Trade.id, Trade.symbol, Trade.option_symbol, Trade.created_at)
            .where(Trade.status == "submitted")
            .where(Trade.order_id.is_(None))
            .order_by(Trade.created_at)
        )
        rows = result.all()

        if not rows:
            print("No legacy submitted trades found. Nothing to do.")
            return

        print(f"Found {len(rows)} legacy submitted trades with no order_id:\n")
        for r in rows:
            print(f"  Trade #{r.id}: {r.symbol} {r.option_symbol or ''} — created {r.created_at}")

        confirm = input(f"\nMark all {len(rows)} as status='unknown'? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return

        # Bulk update
        result = await session.execute(
            update(Trade)
            .where(Trade.status == "submitted")
            .where(Trade.order_id.is_(None))
            .values(status="unknown")
        )
        await session.commit()
        print(f"\nDone. Updated {result.rowcount} trades to status='unknown'.")


if __name__ == "__main__":
    asyncio.run(main())

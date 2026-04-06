#!/usr/bin/env python3
"""
One-shot backfill: assign legacy option trades to Cash-Secured-Puts.

Run once on the droplet after deploying the A1 worker-routing fix:

    cd /opt/multi-agent-trader
    python3 scripts/backfill_agent_assignments.py

What it does:
- Finds all sell_to_open trades with option_symbol set whose agent_name is not
  one of the three known workers (probably written by an older code version with
  a different agent name format).
- Updates those trades to agent_name='Cash-Secured-Puts'.
- Reports a summary so you can verify before any side effects.

The system only ran Cash-Secured-Puts when these positions were opened, so
defaulting to CSP is correct for every affected trade.

After running this script, the DB fallback in _find_worker_for_position will
correctly route closes for those positions.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from core.database import AsyncSessionLocal
from models.trade import Trade

KNOWN_WORKERS = {"Cash-Secured-Puts", "Covered-Calls", "Wheel"}


async def run():
    async with AsyncSessionLocal() as session:
        # Inspect affected rows first
        result = await session.execute(
            select(Trade.id, Trade.agent_name, Trade.option_symbol, Trade.status)
            .where(Trade.option_symbol.isnot(None))
            .where(Trade.side == "sell")
            .where(Trade.agent_name.notin_(KNOWN_WORKERS))
        )
        rows = result.fetchall()

        if not rows:
            print("No legacy option trades found — nothing to do.")
            return

        print(f"Found {len(rows)} trade(s) with non-standard agent_name:")
        for r in rows:
            print(f"  id={r.id}  agent={r.agent_name!r}  option={r.option_symbol}  status={r.status}")

        confirm = input(f"\nUpdate all {len(rows)} trade(s) to agent_name='Cash-Secured-Puts'? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return

        await session.execute(
            update(Trade)
            .where(Trade.option_symbol.isnot(None))
            .where(Trade.side == "sell")
            .where(Trade.agent_name.notin_(KNOWN_WORKERS))
            .values(agent_name="Cash-Secured-Puts")
        )
        await session.commit()
        print(f"Done — {len(rows)} trade(s) updated to Cash-Secured-Puts.")


if __name__ == "__main__":
    asyncio.run(run())

"""
Manual invocation script for the Breadth Analyst.

Usage:
  python scripts/run_breadth_analyst.py backfill           # Run the one-time backfill
  python scripts/run_breadth_analyst.py backfill --fresh   # Clear checkpoint and start over
  python scripts/run_breadth_analyst.py sweep              # Run the daily sweep once
  python scripts/run_breadth_analyst.py sweep --dry-run    # Run the sweep but don't write to DB
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def cmd_backfill(args):
    from core.bootstrap import build_services
    from services.breadth_checkpoint import clear_checkpoint

    svc = build_services()
    agent = svc.breadth_analyst

    if args.fresh:
        ckpt_path = agent.config.get("checkpoint_path", "/tmp/breadth_analyst_backfill_checkpoint.json")
        clear_checkpoint(ckpt_path)
        logger.info("Checkpoint cleared — starting fresh backfill")

    result = await agent.backfill_history(resume=not args.fresh)
    print(f"\nBackfill result: {result}")


async def cmd_sweep(args):
    from core.bootstrap import build_services

    svc = build_services()
    agent = svc.breadth_analyst

    result = await agent.run_daily_sweep(dry_run=args.dry_run)

    print(f"\nSweep result:")
    for k, v in result.items():
        print(f"  {k}: {v}")


def main():
    parser = argparse.ArgumentParser(description="Breadth Analyst manual invocation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bp = subparsers.add_parser("backfill", help="Run the one-time historical bars backfill")
    bp.add_argument("--fresh", action="store_true", help="Clear checkpoint and start over")

    sp = subparsers.add_parser("sweep", help="Run the daily eligibility sweep")
    sp.add_argument("--dry-run", action="store_true", help="Compute but don't write to DB")

    args = parser.parse_args()

    if args.command == "backfill":
        asyncio.run(cmd_backfill(args))
    elif args.command == "sweep":
        asyncio.run(cmd_sweep(args))


if __name__ == "__main__":
    main()

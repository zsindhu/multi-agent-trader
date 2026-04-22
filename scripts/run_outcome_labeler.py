"""
Manual invocation script for the Outcome Labeler.

Usage:
  python scripts/run_outcome_labeler.py              # Label completed trades
  python scripts/run_outcome_labeler.py --dry-run    # Compute but don't write to DB
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def main():
    parser = argparse.ArgumentParser(description="Outcome Labeler")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write to DB")
    args = parser.parse_args()

    from services.outcome_labeler import OutcomeLabeler

    logger.info("=== Outcome Labeler starting ===")
    labeler = OutcomeLabeler()
    result = await labeler.run(dry_run=args.dry_run)

    print(f"\nOutcome Labeler result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

"""
Manual invocation script for the Tier 2a mechanical pre-filter.

Usage:
  python scripts/run_tier2a.py              # Run the sweep
  python scripts/run_tier2a.py --dry-run    # Compute but don't write to DB
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def main():
    parser = argparse.ArgumentParser(description="Tier 2a mechanical pre-filter")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write to DB")
    args = parser.parse_args()

    from core.bootstrap import build_services

    logger.info("=== Tier 2a sweep starting ===")
    svc = build_services()
    result = await svc.tier2a_prefilter.run_sweep(dry_run=args.dry_run)

    print(f"\nTier 2a result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

"""
Manual invocation script for Tier 2b LLM reasoning.

Usage:
  python scripts/run_tier2b.py              # Run reasoning over Tier 2a promotions
  python scripts/run_tier2b.py --dry-run    # Call LLM but don't update DB (prints to stdout)
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def main():
    parser = argparse.ArgumentParser(description="Tier 2b LLM reasoning")
    parser.add_argument("--dry-run", action="store_true", help="Call LLM but don't update DB")
    args = parser.parse_args()

    from core.bootstrap import build_services

    logger.info("=== Tier 2b reasoning starting ===")
    svc = build_services()
    result = await svc.tier2b_reasoning.run_sweep(dry_run=args.dry_run)

    print(f"\nTier 2b result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

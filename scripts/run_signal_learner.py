"""
Manual invocation script for the Signal-Weight Learner.

Usage:
  python scripts/run_signal_learner.py              # Compute and write proposed weights
  python scripts/run_signal_learner.py --dry-run    # Compute and print without writing
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def main():
    parser = argparse.ArgumentParser(description="Signal-Weight Learner")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't write")
    args = parser.parse_args()

    from services.signal_learner import SignalLearner

    logger.info("=== Signal-Weight Learner ===")
    learner = SignalLearner()
    result = await learner.run(dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\nResult: {result.get('sample_size', 0)} samples, "
              f"confidence={result.get('confidence', '?')}")
        if result.get("weights"):
            print(f"Proposed weights written to config/learned_weights.json")
    print()


if __name__ == "__main__":
    asyncio.run(main())

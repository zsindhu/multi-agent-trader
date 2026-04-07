"""
Manual trigger for the universe sweep.

Usage:
    python3 scripts/run_universe_sweep.py

Runs the universe loader and tier writer once, prints summary, exits.
Used for testing and for catching up after a deploy without waiting for
the next scheduled 8am sweep.
"""
import asyncio
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from core.bootstrap import build_services
from services.universe_loader import UniverseLoader
from services.tier_writer import write_tier1_observations
from services.research_data import ResearchDataService


async def main():
    logger.info("=== Manual universe sweep starting ===")

    svc = build_services()

    loader = UniverseLoader(broker=svc.broker)
    passed, rejected = await loader.load_universe_with_rejections()

    print(f"\nUniverse load complete:")
    print(f"  Passed: {len(passed)}")
    print(f"  Rejected: {len(rejected)}")
    if passed:
        print(f"\nTop 10 by daily dollar volume:")
        for name in passed[:10]:
            print(
                f"  {name['symbol']:6s}  "
                f"${name['price']:8.2f}  "
                f"vol_20d={name['avg_volume_20d']:>12,}  "
                f"$vol={name['daily_dollar_volume']:>15,.0f}"
            )

    print("\nWriting to name_observations...")
    result = await write_tier1_observations(passed, rejected)
    print(f"  Passed written: {result['passed_written']}")
    print(f"  Rejected written: {result['rejected_written']}")
    print(f"  Errors: {result['errors']}")

    rd = ResearchDataService()
    await rd.post_message(
        sender="Universe-Loader",
        message_type="universe_sweep_complete",
        subject=f"Manual universe sweep: {result['passed_written']} names",
        body="Manual sweep triggered via scripts/run_universe_sweep.py",
        payload={
            "passed_count": result["passed_written"],
            "rejected_count": result["rejected_written"],
            "errors": result["errors"],
            "trigger": "manual",
        },
        ttl_hours=48,
    )

    print("\n=== Manual universe sweep complete ===")


if __name__ == "__main__":
    asyncio.run(main())

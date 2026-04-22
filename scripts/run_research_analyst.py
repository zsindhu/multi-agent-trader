"""
Manual invocation script for the Research Analyst + Pre-market Briefing.

Usage:
  python scripts/run_research_analyst.py reflect              # Run daily reflection
  python scripts/run_research_analyst.py reflect --dry-run    # Generate but don't store
  python scripts/run_research_analyst.py briefing             # Generate pre-market briefing
  python scripts/run_research_analyst.py briefing --dry-run   # Generate but don't store
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


async def cmd_reflect(args):
    from agents.research_analyst import ResearchAnalyst
    logger.info("=== Research Analyst reflection ===")
    ra = ResearchAnalyst()
    result = await ra.run_reflection(dry_run=args.dry_run)
    print(f"\nResult: {result}")


async def cmd_briefing(args):
    from services.briefing_service import BriefingService
    logger.info("=== Pre-market briefing ===")
    bs = BriefingService()
    result = await bs.generate_briefing(dry_run=args.dry_run)
    print(f"\nResult: {result}")


def main():
    parser = argparse.ArgumentParser(description="Research Analyst + Briefing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rp = subparsers.add_parser("reflect", help="Run daily reflection")
    rp.add_argument("--dry-run", action="store_true")

    bp = subparsers.add_parser("briefing", help="Generate pre-market briefing")
    bp.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "reflect":
        asyncio.run(cmd_reflect(args))
    elif args.command == "briefing":
        asyncio.run(cmd_briefing(args))


if __name__ == "__main__":
    main()

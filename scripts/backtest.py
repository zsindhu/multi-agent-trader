#!/usr/bin/env python3
"""
Backtest CLI — Run backtests from the command line.

Usage:
    # Basic backtest
    python scripts/backtest.py --agent worker_csp --days 180

    # With parameter overrides
    python scripts/backtest.py --agent worker_csp --days 180 \\
        --param delta_target=-0.20 --param min_iv_rank=35

    # Custom symbols
    python scripts/backtest.py --agent worker_csp --days 180 \\
        --symbols AAPL,MSFT,NVDA

    # Compare two parameter sets
    python scripts/backtest.py --agent worker_csp --days 180 --compare \\
        --param-a delta_target=-0.25 --param-b delta_target=-0.20

    # Save results to JSON
    python scripts/backtest.py --agent worker_csp --days 180 --save
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from services.backtester import (
    BacktestEngine,
    BacktestResult,
    compare_backtests,
    print_comparison,
)


def parse_param(param_str: str) -> tuple[str, float]:
    """Parse a 'key=value' parameter string."""
    if "=" not in param_str:
        raise ValueError(f"Invalid parameter format: '{param_str}' (expected key=value)")
    key, value = param_str.split("=", 1)
    try:
        return key.strip(), float(value.strip())
    except ValueError:
        return key.strip(), value.strip()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Premium Trader — Backtest Engine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --agent worker_csp --days 180
  %(prog)s --agent worker_csp --days 180 --param delta_target=-0.20
  %(prog)s --agent worker_csp --days 180 --compare --param-a delta_target=-0.25 --param-b delta_target=-0.20
  %(prog)s --agent worker_wheel --days 365 --symbols AAPL,MSFT,NVDA --save
        """,
    )

    parser.add_argument(
        "--agent",
        required=True,
        choices=["worker_csp", "worker_cc", "worker_wheel"],
        help="Agent type to backtest",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Number of trading days to backtest (default: 180)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbols (default: AAPL,MSFT,NVDA,AMD,TSLA)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Initial capital (default: 100000)",
    )

    # Parameter overrides (single run)
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Parameter override in key=value format (can repeat)",
    )

    # Compare mode
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare two parameter sets side by side",
    )
    parser.add_argument(
        "--param-a",
        action="append",
        default=[],
        dest="param_a",
        help="Parameter overrides for set A (compare mode)",
    )
    parser.add_argument(
        "--param-b",
        action="append",
        default=[],
        dest="param_b",
        help="Parameter overrides for set B (compare mode)",
    )

    # Output
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to JSON in data/backtest_results/",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output path for JSON results",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress logs (show only results)",
    )

    return parser.parse_args()


async def run_single_backtest(args) -> BacktestResult:
    """Run a single backtest with the given parameters."""
    symbols = (
        args.symbols.split(",") if args.symbols else ["AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
    )

    param_overrides = {}
    for p in args.param:
        key, value = parse_param(p)
        param_overrides[key] = value

    engine = BacktestEngine(
        agent_type=args.agent,
        symbols=symbols,
        days=args.days,
        param_overrides=param_overrides,
        initial_capital=args.capital,
    )

    result = await engine.run()
    result.print_summary()

    # Save if requested
    if args.save or args.output:
        output_path = args.output or _default_output_path(args.agent, param_overrides)
        result.save_json(output_path)
        print(f"  Results saved to: {output_path}")

    return result


async def run_comparison(args):
    """Run two backtests and compare results."""
    symbols = (
        args.symbols.split(",") if args.symbols else ["AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
    )

    params_a = {}
    for p in args.param_a:
        key, value = parse_param(p)
        params_a[key] = value

    params_b = {}
    for p in args.param_b:
        key, value = parse_param(p)
        params_b[key] = value

    if not params_a and not params_b:
        print("Error: --compare requires at least one --param-a or --param-b")
        sys.exit(1)

    result_a, result_b = await compare_backtests(
        agent_type=args.agent,
        symbols=symbols,
        days=args.days,
        params_a=params_a,
        params_b=params_b,
        initial_capital=args.capital,
    )

    print("\n  ── Parameter Set A ──")
    result_a.print_summary()

    print("\n  ── Parameter Set B ──")
    result_b.print_summary()

    print_comparison(result_a, result_b)

    # Save if requested
    if args.save or args.output:
        base = args.output or "data/backtest_results"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_a.save_json(f"{base}/compare_A_{args.agent}_{ts}.json")
        result_b.save_json(f"{base}/compare_B_{args.agent}_{ts}.json")
        print(f"  Comparison results saved to {base}/")


def _default_output_path(agent: str, params: dict) -> str:
    """Generate a default output filename."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    param_str = "_".join(f"{k}{v}" for k, v in params.items()) if params else "default"
    return f"data/backtest_results/{agent}_{param_str}_{ts}.json"


async def main():
    args = parse_args()

    if args.quiet:
        logger.remove()
        logger.add(sys.stderr, level="WARNING")

    if args.compare:
        await run_comparison(args)
    else:
        await run_single_backtest(args)


if __name__ == "__main__":
    asyncio.run(main())

"""
Bulk loader for historical_bars — One-time operation to populate the
persistent bar cache from multiple free public data sources.

Usage:
  python scripts/bulk_load_historical_bars.py
  python scripts/bulk_load_historical_bars.py --sources stooq,yfinance
  python scripts/bulk_load_historical_bars.py --symbols AAPL,MSFT,GOOGL --days 30
  python scripts/bulk_load_historical_bars.py --limit 100 --dry-run
  python scripts/bulk_load_historical_bars.py --chunk-size 500

Sources: stooq, yfinance
Each source adapter is independent — if one fails, the others continue.
Rows use INSERT ... ON CONFLICT DO NOTHING so re-runs are idempotent.

The universe is processed in chunks (default 250 symbols) to keep peak
memory under control on small droplets. Each chunk is fetched and written
before the next chunk starts, so only one chunk's bars are in memory at
a time.
"""
import argparse
import asyncio
import math
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import text as sql_text

from core.database import AsyncSessionLocal
from models.agent_action import AgentAction


AVAILABLE_SOURCES = ["stooq", "yfinance"]
INSERT_CHUNK_SIZE = 10_000
CHUNK_SIZE = 250  # symbols per chunk — keeps peak memory ~50 MB


def get_adapter(source_name: str):
    """Instantiate the adapter for the given source name."""
    if source_name == "stooq":
        from services.bulk_data_sources.stooq_adapter import StooqAdapter
        return StooqAdapter()
    elif source_name == "yfinance":
        from services.bulk_data_sources.yfinance_adapter import YFinanceAdapter
        return YFinanceAdapter()
    else:
        raise ValueError(f"Unknown source: {source_name}")


async def log_action(action_type: str, outcome: str, reason: str = None, payload: dict = None):
    """Write a row to agent_actions for audit."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(AgentAction(
                agent_name="bulk-loader",
                action_type=action_type,
                target_scope="universe",
                outcome=outcome,
                reason=reason,
                payload=payload,
            ))
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to log action: {e}")


async def bulk_insert_bars(bars: list[dict], dry_run: bool = False) -> int:
    """
    Insert bars into historical_bars using INSERT ... ON CONFLICT DO NOTHING.
    Returns the number of rows actually inserted (excludes conflicts).
    """
    if not bars or dry_run:
        return 0

    total_inserted = 0

    for i in range(0, len(bars), INSERT_CHUNK_SIZE):
        chunk = bars[i : i + INSERT_CHUNK_SIZE]
        try:
            async with AsyncSessionLocal() as session:
                for bar in chunk:
                    await session.execute(
                        sql_text("""
                            INSERT INTO historical_bars
                                (symbol, bar_date, open, high, low, close, volume, vwap, trade_count, source)
                            VALUES
                                (:symbol, :bar_date, :open, :high, :low, :close, :volume, :vwap, :trade_count, :source)
                            ON CONFLICT (symbol, bar_date, source) DO NOTHING
                        """),
                        {
                            "symbol": bar["symbol"],
                            "bar_date": bar["bar_date"],
                            "open": bar["open"],
                            "high": bar["high"],
                            "low": bar["low"],
                            "close": bar["close"],
                            "volume": bar["volume"],
                            "vwap": bar.get("vwap"),
                            "trade_count": bar.get("trade_count"),
                            "source": bar["source"],
                        },
                    )
                await session.commit()
                total_inserted += len(chunk)
        except Exception as e:
            logger.error(f"Bulk insert failed for chunk at index {i}: {e}")

    return total_inserted


async def main():
    parser = argparse.ArgumentParser(description="Bulk load historical bars from free data sources")
    parser.add_argument("--sources", default=",".join(AVAILABLE_SOURCES),
                        help=f"Comma-separated sources to run (default: all). Options: {AVAILABLE_SOURCES}")
    parser.add_argument("--days", type=int, default=252, help="Trading days back from today (default: 252)")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols (overrides Alpaca universe)")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N symbols from universe")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help=f"Symbols per chunk (default: {CHUNK_SIZE})")
    parser.add_argument("--dry-run", action="store_true", help="Fetch from sources but don't write to DB")
    args = parser.parse_args()

    chunk_size = args.chunk_size

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    for s in sources:
        if s not in AVAILABLE_SOURCES:
            print(f"Unknown source: {s}. Available: {AVAILABLE_SOURCES}")
            sys.exit(1)

    # Compute date range
    end_date = date.today()
    start_date = end_date - timedelta(days=int(args.days * 1.5))  # Overshoot to account for weekends/holidays

    # Get symbols
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        logger.info("Fetching optionable universe from Alpaca...")
        from core.bootstrap import build_services
        svc = build_services()
        assets = await svc.broker.get_tradable_assets(options_enabled=True)
        symbols = [a["symbol"] for a in assets]
        logger.info(f"Universe: {len(symbols)} optionable symbols")

    if args.limit:
        symbols = symbols[:args.limit]
        logger.info(f"Limited to first {args.limit} symbols")

    total_chunks = math.ceil(len(symbols) / chunk_size)

    print(f"\nBulk load configuration:")
    print(f"  Sources: {sources}")
    print(f"  Symbols: {len(symbols)}")
    print(f"  Chunk size: {chunk_size} ({total_chunks} chunks)")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Dry run: {args.dry_run}")
    print()

    # Run each source
    results = {}
    overall_start = time.time()

    for source_name in sources:
        print(f"{'=' * 60}")
        print(f"Source: {source_name}")
        print(f"{'=' * 60}")

        await log_action(
            f"bulk_load_{source_name}", "in_progress", None,
            {"source": source_name, "symbol_count": len(symbols), "chunk_size": chunk_size},
        )

        source_start = time.time()
        source_bars_total = 0
        source_inserted_total = 0
        source_symbols = set()

        try:
            # Instantiate adapter ONCE outside the chunk loop so indexes
            # (e.g. Stooq's ZIP index) are built once and reused.
            adapter = get_adapter(source_name)

            for chunk_idx in range(0, len(symbols), chunk_size):
                chunk_symbols = symbols[chunk_idx : chunk_idx + chunk_size]
                chunk_num = chunk_idx // chunk_size + 1

                # Fetch this chunk
                bars = await adapter.fetch_bars(chunk_symbols, start_date, end_date)
                chunk_bar_count = len(bars)
                source_bars_total += chunk_bar_count
                source_symbols.update(b["symbol"] for b in bars)

                # Write immediately, then discard
                if not args.dry_run:
                    inserted = await bulk_insert_bars(bars)
                    source_inserted_total += inserted
                else:
                    inserted = 0

                # Discard bars to free memory
                del bars

                logger.info(
                    f"[{source_name}] Chunk {chunk_num}/{total_chunks}: "
                    f"fetched {chunk_bar_count:,} bars, inserted {inserted:,} rows "
                    f"(cumulative {len(source_symbols):,}/{len(symbols):,} symbols)"
                )

            source_elapsed = time.time() - source_start
            print(f"  Fetched: {source_bars_total:,} bars from {len(source_symbols):,} symbols in {source_elapsed:.0f}s")

            if not args.dry_run:
                print(f"  Inserted: {source_inserted_total:,} rows (conflicts skipped)")
            else:
                print(f"  DRY RUN: would insert {source_bars_total:,} rows")

            results[source_name] = {
                "bars_fetched": source_bars_total,
                "symbols": len(source_symbols),
                "inserted": source_inserted_total,
                "elapsed_seconds": round(source_elapsed, 1),
            }

            await log_action(
                f"bulk_load_{source_name}", "executed", None,
                results[source_name],
            )

        except Exception as e:
            source_elapsed = time.time() - source_start
            logger.error(f"{source_name} failed: {e}")
            results[source_name] = {
                "bars_fetched": source_bars_total,
                "symbols": len(source_symbols),
                "inserted": source_inserted_total,
                "elapsed_seconds": round(source_elapsed, 1),
                "error": str(e),
            }
            await log_action(
                f"bulk_load_{source_name}", "failed", str(e)[:256],
                results[source_name],
            )

        print()

    # Summary
    overall_elapsed = time.time() - overall_start
    total_bars = sum(r.get("bars_fetched", 0) for r in results.values())
    total_inserted = sum(r.get("inserted", 0) for r in results.values())

    print(f"{'=' * 60}")
    print(f"Bulk load complete:")
    for source, r in results.items():
        if "error" in r:
            print(f"  {source:12s}: FAILED — {r['error'][:80]}")
        else:
            print(f"  {source:12s}: {r['bars_fetched']:>12,} bars from {r['symbols']:,} symbols")
    print(f"  {'Total':12s}: {total_bars:>12,} bars fetched, {total_inserted:,} rows inserted")
    print(f"  Elapsed: {overall_elapsed / 60:.1f} minutes")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())

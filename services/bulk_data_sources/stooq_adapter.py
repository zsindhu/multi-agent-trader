"""
Stooq Adapter — Fetches historical daily bars from Stooq via
pandas-datareader's built-in Stooq reader.

Processes symbols one at a time (Stooq's reader is per-symbol), batched
with 2s sleeps between batches to stay under Stooq's daily request limits.
Synchronous pandas-datareader calls run in a thread executor for async compat.
"""
import asyncio
import math
from datetime import date

from loguru import logger

from services.bulk_data_sources.base import BulkDataSourceAdapter

BATCH_SIZE = 25
BATCH_SLEEP = 2.0  # seconds between batches — Stooq has daily hit limits


class StooqAdapter(BulkDataSourceAdapter):
    """Fetches daily bars from Stooq via pandas-datareader."""

    source_name = "stooq"

    async def fetch_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        logger.info(f"[Stooq] Fetching bars for {len(symbols)} symbols ({start_date} to {end_date})")

        all_bars = []
        total_batches = math.ceil(len(symbols) / BATCH_SIZE)
        hit_limit = False

        for batch_idx in range(0, len(symbols), BATCH_SIZE):
            if hit_limit:
                break

            batch = symbols[batch_idx : batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1

            for symbol in batch:
                if hit_limit:
                    break
                try:
                    bars = await self._fetch_symbol(symbol, start_date, end_date)
                    all_bars.extend(bars)
                except StooqRateLimitError:
                    logger.warning(f"[Stooq] Daily hits limit reached at symbol {symbol}. Stopping.")
                    hit_limit = True
                except Exception as e:
                    logger.warning(f"[Stooq] Failed to fetch {symbol}: {e}")

            if batch_num % 10 == 0 or batch_num == total_batches:
                unique = len({b["symbol"] for b in all_bars})
                logger.info(f"[Stooq] Batch {batch_num}/{total_batches} done, {len(all_bars)} bars from {unique} symbols")

            if batch_idx + BATCH_SIZE < len(symbols) and not hit_limit:
                await asyncio.sleep(BATCH_SLEEP)

        unique_symbols = len({b["symbol"] for b in all_bars})
        logger.info(f"[Stooq] Fetched {len(all_bars)} total bars from {unique_symbols} symbols")
        return all_bars

    async def _fetch_symbol(self, symbol: str, start_date: date, end_date: date) -> list[dict]:
        """Fetch bars for a single symbol via pandas-datareader in a thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_symbol_sync, symbol, start_date, end_date)

    def _fetch_symbol_sync(self, symbol: str, start_date: date, end_date: date) -> list[dict]:
        """Synchronous single-symbol fetch via pandas-datareader."""
        import pandas_datareader.data as pdr

        sym_upper = symbol.upper()

        try:
            df = pdr.DataReader(sym_upper, "stooq", start_date, end_date)
        except Exception as e:
            err_str = str(e).lower()
            if "limit" in err_str or "too many" in err_str or "429" in err_str:
                raise StooqRateLimitError(f"Rate limit hit for {sym_upper}: {e}")
            raise

        if df is None or df.empty:
            logger.debug(f"[Stooq] No data for {sym_upper}")
            return []

        bars = []
        for idx, row in df.iterrows():
            try:
                bar_date = idx.date() if hasattr(idx, "date") else idx

                if bar_date < start_date or bar_date > end_date:
                    continue

                close = row.get("Close")
                volume = row.get("Volume")
                if close is None or volume is None:
                    continue

                import math as _math
                if _math.isnan(float(close)) or _math.isnan(float(volume)):
                    continue

                bars.append({
                    "symbol": sym_upper,
                    "bar_date": bar_date,
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(close),
                    "volume": int(float(volume)),
                    "vwap": None,
                    "trade_count": None,
                    "source": self.source_name,
                })
            except (ValueError, TypeError):
                continue

        return bars


class StooqRateLimitError(Exception):
    """Raised when Stooq's daily hits limit is exceeded."""
    pass

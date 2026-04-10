"""
yfinance Bulk Adapter — Fetches historical daily bars from Yahoo Finance
via the yfinance library's batched download endpoint.

Uses yfinance.download() for multi-ticker batch calls (much faster than
per-ticker Ticker.history()). Runs synchronous yfinance calls in a thread
executor to stay compatible with the async adapter interface.
"""
import asyncio
import math
from datetime import date

import yfinance as yf
from loguru import logger

from services.bulk_data_sources.base import BulkDataSourceAdapter

BATCH_SIZE = 50
BATCH_SLEEP = 1.0  # seconds between batches, be polite to Yahoo


class YFinanceAdapter(BulkDataSourceAdapter):
    """Fetches daily bars from Yahoo Finance via yfinance."""

    source_name = "yfinance"

    async def fetch_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        logger.info(f"[yfinance] Fetching bars for {len(symbols)} symbols ({start_date} to {end_date})")

        all_bars = []
        total_batches = math.ceil(len(symbols) / BATCH_SIZE)

        for batch_idx in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[batch_idx : batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1

            try:
                bars = await self._fetch_batch(batch, start_date, end_date)
                all_bars.extend(bars)
            except Exception as e:
                logger.warning(f"[yfinance] Batch {batch_num}/{total_batches} failed: {e}")

            if batch_num % 10 == 0 or batch_num == total_batches:
                logger.info(f"[yfinance] Batch {batch_num}/{total_batches} done, {len(all_bars)} bars so far")

            if batch_idx + BATCH_SIZE < len(symbols):
                await asyncio.sleep(BATCH_SLEEP)

        logger.info(f"[yfinance] Fetched {len(all_bars)} total bars")
        return all_bars

    async def _fetch_batch(self, symbols: list[str], start_date: date, end_date: date) -> list[dict]:
        """Download a batch of symbols via yfinance in a thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_batch_sync, symbols, start_date, end_date)

    def _fetch_batch_sync(self, symbols: list[str], start_date: date, end_date: date) -> list[dict]:
        """Synchronous yfinance download and parse."""
        tickers_str = " ".join(symbols)
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        df = yf.download(
            tickers_str,
            start=start_str,
            end=end_str,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        if df is None or df.empty:
            return []

        bars = []

        if len(symbols) == 1:
            # Single ticker: columns are just Open, High, Low, Close, Volume
            sym = symbols[0].upper()
            for idx, row in df.iterrows():
                bar = self._row_to_bar(sym, idx, row)
                if bar:
                    bars.append(bar)
        else:
            # Multi-ticker: columns are MultiIndex (ticker, field)
            for sym in symbols:
                sym_upper = sym.upper()
                try:
                    if sym in df.columns.get_level_values(0):
                        sym_df = df[sym]
                    elif sym_upper in df.columns.get_level_values(0):
                        sym_df = df[sym_upper]
                    else:
                        continue

                    for idx, row in sym_df.iterrows():
                        bar = self._row_to_bar(sym_upper, idx, row)
                        if bar:
                            bars.append(bar)
                except Exception:
                    continue

        return bars

    def _row_to_bar(self, symbol: str, timestamp, row) -> dict:
        """Convert a DataFrame row to a standard bar dict. Returns None for invalid rows."""
        try:
            close = row.get("Close")
            volume = row.get("Volume")

            # Skip NaN rows (weekends/holidays that yfinance sometimes returns)
            if close is None or (hasattr(close, "__float__") and math.isnan(float(close))):
                return None
            if volume is None or (hasattr(volume, "__float__") and math.isnan(float(volume))):
                return None

            bar_date = timestamp.date() if hasattr(timestamp, "date") else timestamp

            return {
                "symbol": symbol,
                "bar_date": bar_date,
                "open": float(row.get("Open", 0)),
                "high": float(row.get("High", 0)),
                "low": float(row.get("Low", 0)),
                "close": float(close),
                "volume": int(float(volume)),
                "vwap": None,
                "trade_count": None,
                "source": self.source_name,
            }
        except (ValueError, TypeError):
            return None

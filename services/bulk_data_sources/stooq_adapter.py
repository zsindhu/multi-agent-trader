"""
Stooq Adapter — Reads historical daily bars from a local Stooq US daily
archive ZIP file. No network calls.

The ZIP is manually downloaded from Stooq and placed on the droplet at a
configurable path. Standard Stooq layout inside the ZIP:
  data/daily/us/{exchange}/{bucket}/{symbol}.us.txt

CSV format per file (header uses angle brackets):
  <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
  AAPL.US,D,20240315,000000,171.17,172.62,170.29,172.62,65002928,0

Dates are YYYYMMDD. Volume is in shares.
"""
import csv
import io
import os
import zipfile
from datetime import date, datetime
from typing import Optional

from loguru import logger

from services.bulk_data_sources.base import BulkDataSourceAdapter

# Default path on the droplet. Override via constructor if needed.
DEFAULT_ZIP_PATH = "/app/stooq_data/d_us_txt.zip"


class StooqAdapter(BulkDataSourceAdapter):
    """Reads daily bars from a local Stooq ZIP archive."""

    source_name = "stooq"

    def __init__(self, zip_path: str = DEFAULT_ZIP_PATH):
        self.zip_path = zip_path
        self._zf: Optional[zipfile.ZipFile] = None
        # Maps uppercase symbol -> internal zip path (built once on first use)
        self._index: Optional[dict[str, str]] = None

    def _ensure_index(self):
        """Open the ZIP and build the symbol -> path index on first call."""
        if self._index is not None:
            return

        if not os.path.exists(self.zip_path):
            raise FileNotFoundError(
                f"Stooq ZIP not found at {self.zip_path}. "
                f"Download from https://stooq.com/db/h/ and place it there."
            )

        self._zf = zipfile.ZipFile(self.zip_path, "r")
        self._index = {}

        for entry in self._zf.namelist():
            if not entry.endswith(".txt"):
                continue
            basename = os.path.basename(entry).lower()

            # Strip .us.txt suffix to get the ticker
            if basename.endswith(".us.txt"):
                raw_ticker = basename[:-7]
            elif basename.endswith(".txt"):
                raw_ticker = basename[:-4]
            else:
                continue

            # Stooq uses hyphens for dot-class symbols: brk-b.us.txt -> BRK.B
            ticker = raw_ticker.replace("-", ".").upper()
            self._index[ticker] = entry

        logger.info(f"[Stooq] Indexed {len(self._index)} symbols from {self.zip_path}")

    async def fetch_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        logger.info(f"[Stooq] Reading bars for {len(symbols)} symbols ({start_date} to {end_date})")

        self._ensure_index()

        all_bars = []
        found = 0
        missing = 0

        for symbol in symbols:
            sym_upper = symbol.upper()
            zip_path = self._index.get(sym_upper)

            if zip_path is None:
                logger.debug(f"[Stooq] {sym_upper} not in archive")
                missing += 1
                continue

            try:
                bars = self._read_symbol(sym_upper, zip_path, start_date, end_date)
                all_bars.extend(bars)
                found += 1
            except Exception as e:
                logger.warning(f"[Stooq] Failed to parse {sym_upper}: {e}")

        logger.info(
            f"[Stooq] Done: {len(all_bars)} bars from {found} symbols "
            f"({missing} not in archive)"
        )
        return all_bars

    def _read_symbol(
        self, symbol: str, zip_path: str, start_date: date, end_date: date,
    ) -> list[dict]:
        """Read and parse one symbol's CSV from the ZIP."""
        bars = []

        with self._zf.open(zip_path) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.reader(text)

            for row in reader:
                # Skip header lines (start with <) and short rows
                if not row or row[0].startswith("<"):
                    continue
                if len(row) < 9:
                    continue

                try:
                    # TICKER,PER,DATE,TIME,OPEN,HIGH,LOW,CLOSE,VOL,OPENINT
                    bar_dt = datetime.strptime(row[2], "%Y%m%d").date()

                    if bar_dt < start_date or bar_dt > end_date:
                        continue

                    bars.append({
                        "symbol": symbol,
                        "bar_date": bar_dt,
                        "open": float(row[4]),
                        "high": float(row[5]),
                        "low": float(row[6]),
                        "close": float(row[7]),
                        "volume": int(float(row[8])),
                        "vwap": None,
                        "trade_count": None,
                        "source": self.source_name,
                    })
                except (ValueError, IndexError):
                    continue

        return bars

    def close(self):
        """Close the ZIP file handle if open."""
        if self._zf:
            self._zf.close()
            self._zf = None
            self._index = None

"""
Stooq Bulk Adapter — Downloads the US daily stocks archive from Stooq
and parses individual symbol CSV files from the ZIP without extracting
to disk.

Stooq publishes free bulk archives at https://stooq.com/db/h/. The US
daily archive is a single ZIP (~150-300 MB) containing one .txt CSV per
symbol with format: <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
"""
import csv
import io
import os
import zipfile
from datetime import date, datetime

import httpx
from loguru import logger

from services.bulk_data_sources.base import BulkDataSourceAdapter

STOOQ_ARCHIVE_URL = "https://stooq.com/db/d/?b=d_us_txt"
STOOQ_CACHE_PATH = "/tmp/stooq_us_daily.zip"


class StooqAdapter(BulkDataSourceAdapter):
    """Fetches daily bars from the Stooq US daily archive."""

    source_name = "stooq"

    async def fetch_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        logger.info(f"[Stooq] Fetching bars for {len(symbols)} symbols ({start_date} to {end_date})")

        # Step 1: Download archive if not cached
        archive_path = await self._ensure_archive()
        if not archive_path:
            raise RuntimeError("Failed to download Stooq archive")

        # Step 2: Build lookup set for fast matching
        wanted = {s.upper() for s in symbols}

        # Step 3: Parse bars from archive
        bars = []
        found_symbols = set()

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Build a map of lowercase filename stem -> full path in zip
                # Stooq uses paths like data/daily/us/nasdaq stocks/1/aapl.us.txt
                name_map = {}
                for entry in zf.namelist():
                    if not entry.endswith(".txt"):
                        continue
                    basename = os.path.basename(entry)
                    # Strip .us.txt suffix to get the ticker
                    if basename.endswith(".us.txt"):
                        ticker = basename[:-7].upper()
                    elif basename.endswith(".txt"):
                        ticker = basename[:-4].upper()
                    else:
                        continue
                    if ticker in wanted:
                        name_map[ticker] = entry

                logger.info(f"[Stooq] Archive has {len(name_map)} of {len(wanted)} requested symbols")

                for ticker, zip_path in name_map.items():
                    try:
                        with zf.open(zip_path) as f:
                            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                            reader = csv.reader(text)
                            for row in reader:
                                # Skip header lines (start with <)
                                if not row or row[0].startswith("<"):
                                    continue
                                if len(row) < 9:
                                    continue
                                try:
                                    # Format: TICKER,PER,DATE,TIME,OPEN,HIGH,LOW,CLOSE,VOL,OPENINT
                                    bar_date_str = row[2]
                                    bar_dt = datetime.strptime(bar_date_str, "%Y%m%d").date()

                                    if bar_dt < start_date or bar_dt > end_date:
                                        continue

                                    bars.append({
                                        "symbol": ticker,
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
                        found_symbols.add(ticker)
                    except Exception as e:
                        logger.warning(f"[Stooq] Failed to parse {ticker}: {e}")

        except zipfile.BadZipFile as e:
            # Corrupted cache — delete and raise so operator can retry
            os.unlink(archive_path)
            raise RuntimeError(f"Stooq archive is corrupted (deleted cache): {e}")

        missing = wanted - found_symbols
        if missing:
            logger.info(f"[Stooq] {len(missing)} symbols not in archive (expected for OTC/recent IPOs)")

        logger.info(f"[Stooq] Parsed {len(bars)} bars from {len(found_symbols)} symbols")
        return bars

    async def _ensure_archive(self) -> str:
        """Download the Stooq archive if not already cached."""
        if os.path.exists(STOOQ_CACHE_PATH):
            size_mb = os.path.getsize(STOOQ_CACHE_PATH) / (1024 * 1024)
            logger.info(f"[Stooq] Using cached archive ({size_mb:.0f} MB)")
            return STOOQ_CACHE_PATH

        logger.info(f"[Stooq] Downloading archive from {STOOQ_ARCHIVE_URL}...")
        try:
            async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
                async with client.stream("GET", STOOQ_ARCHIVE_URL) as resp:
                    if resp.status_code != 200:
                        logger.error(f"[Stooq] Download failed: HTTP {resp.status_code}")
                        return None

                    tmp_path = STOOQ_CACHE_PATH + ".tmp"
                    total = 0
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                            total += len(chunk)

                    os.replace(tmp_path, STOOQ_CACHE_PATH)
                    logger.info(f"[Stooq] Downloaded {total / (1024*1024):.0f} MB")
                    return STOOQ_CACHE_PATH

        except Exception as e:
            logger.error(f"[Stooq] Download failed: {e}")
            return None

"""
FRED Service — Fetches macro indicators from the Federal Reserve Economic
Data API (https://fred.stlouisfed.org/).

Free, no API key needed for basic access via the public JSON endpoint.
Provides: Treasury yields (2Y, 10Y), yield curve spread, Fed funds rate,
VIX (official CBOE), HYG/LQD credit spread proxy, unemployment, inflation
expectations. Cached for 6 hours since macro data changes slowly.

Exposed as a Lead Agent tool: get_macro_indicators().
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger


# FRED series IDs for the indicators we track
FRED_SERIES = {
    "treasury_10y": "DGS10",        # 10-Year Treasury Constant Maturity Rate
    "treasury_2y": "DGS2",          # 2-Year Treasury Constant Maturity Rate
    "fed_funds_rate": "DFF",        # Federal Funds Effective Rate
    "vix_cboe": "VIXCLS",           # CBOE VIX (official, daily)
    "unemployment": "UNRATE",        # Unemployment Rate (monthly)
    "inflation_expectations_5y": "T5YIE",  # 5-Year Breakeven Inflation Rate
    "inflation_expectations_10y": "T10YIE", # 10-Year Breakeven Inflation Rate
}

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
CACHE_TTL = 6 * 3600  # 6 hours


class FredService:
    """Fetches and caches macro indicators from FRED."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._cache: dict[str, dict] = {}
        self._cache_time: float = 0

    async def get_macro_indicators(self) -> dict:
        """
        Return a dict of current macro indicators.

        Returns:
            {
                "treasury_10y": 4.35,
                "treasury_2y": 4.72,
                "yield_curve_spread": -0.37,  # 10Y - 2Y (negative = inverted)
                "fed_funds_rate": 5.33,
                "vix_cboe": 18.5,
                "unemployment": 3.8,
                "inflation_expectations_5y": 2.35,
                "inflation_expectations_10y": 2.28,
                "fetched_at": "2026-04-11T12:00:00",
                "source": "fred",
            }
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        indicators = {}
        for name, series_id in FRED_SERIES.items():
            try:
                value = await self._fetch_latest(series_id)
                indicators[name] = value
            except Exception as e:
                logger.warning(f"[FRED] Failed to fetch {name} ({series_id}): {e}")
                indicators[name] = None

        # Computed spreads
        t10 = indicators.get("treasury_10y")
        t2 = indicators.get("treasury_2y")
        if t10 is not None and t2 is not None:
            indicators["yield_curve_spread"] = round(t10 - t2, 3)
        else:
            indicators["yield_curve_spread"] = None

        indicators["fetched_at"] = datetime.utcnow().isoformat()
        indicators["source"] = "fred"

        self._cache = indicators
        self._cache_time = now
        logger.info(f"[FRED] Fetched {sum(1 for v in indicators.values() if v is not None)} indicators")
        return indicators

    async def _fetch_latest(self, series_id: str) -> Optional[float]:
        """Fetch the most recent observation for a FRED series."""
        params = {
            "series_id": series_id,
            "sort_order": "desc",
            "limit": "5",
            "file_type": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(FRED_BASE_URL, params=params)
            if resp.status_code != 200:
                logger.warning(f"[FRED] HTTP {resp.status_code} for {series_id}")
                return None

            data = resp.json()
            observations = data.get("observations", [])

            # Find the most recent non-empty value
            for obs in observations:
                val = obs.get("value", ".")
                if val != "." and val:
                    try:
                        return float(val)
                    except ValueError:
                        continue

            return None

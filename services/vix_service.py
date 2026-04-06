"""
VIX Service — Fetches real spot VIX from Yahoo Finance with 5-minute cache.

Single source of truth for VIX across StrategyManager and MarketRegimeService.
Falls back to VIXY proxy only if Yahoo is unreachable.
"""
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger

_CACHE_TTL = timedelta(minutes=5)


class VIXService:
    """Fetches spot VIX from Yahoo Finance. Caches for 5 minutes."""

    def __init__(self, broker=None):
        self.broker = broker  # Used only for fallback
        self._cache: Optional[tuple[float, datetime]] = None

    async def get_vix(self) -> float:
        """
        Return current spot VIX level.

        Primary: Yahoo Finance ^VIX (real spot VIX, free, no auth)
        Fallback: VIXY ETF mid price × 1.67 (proxy, inaccurate but always available)
        """
        # Check cache
        if self._cache:
            value, fetched_at = self._cache
            if datetime.utcnow() - fetched_at < _CACHE_TTL:
                return value

        # Try Yahoo Finance first
        vix = await self._fetch_from_yahoo()
        if vix is not None:
            self._cache = (vix, datetime.utcnow())
            logger.info(f"[VIX] Spot VIX from Yahoo: {vix:.2f}")
            return vix

        # Fallback to VIXY proxy
        vix = await self._fetch_from_vixy_proxy()
        if vix is not None:
            self._cache = (vix, datetime.utcnow())
            logger.warning(f"[VIX] Using VIXY proxy (Yahoo unavailable): {vix:.2f}")
            return vix

        # Last resort default
        logger.error("[VIX] All sources failed, returning default 20.0")
        return 20.0

    async def _fetch_from_yahoo(self) -> Optional[float]:
        """Fetch real spot VIX from Yahoo Finance chart API."""
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PremiumTrader/1.0)"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.debug(f"[VIX] Yahoo returned {resp.status_code}")
                    return None
                data = resp.json()
                # Yahoo response structure: chart.result[0].meta.regularMarketPrice
                result = data.get("chart", {}).get("result", [])
                if not result:
                    return None
                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                if price is None or price <= 0 or price > 200:
                    return None
                return float(price)
        except Exception as e:
            logger.debug(f"[VIX] Yahoo fetch failed: {e}")
            return None

    async def _fetch_from_vixy_proxy(self) -> Optional[float]:
        """
        Legacy fallback — VIXY ETF price × approximate multiplier.
        Inaccurate but always available if broker is reachable.
        """
        if not self.broker:
            return None
        try:
            quote = await self.broker.get_latest_quote("VIXY")
            if not quote or quote.get("bid", 0) <= 0:
                return None
            mid = (quote["bid"] + quote["ask"]) / 2
            # VIXY ≈ VIX × 0.6 historically, but this is a rough approximation
            vix = mid / 0.6
            return max(8.0, min(80.0, round(vix, 1)))
        except Exception:
            return None

    async def get_vix_direction(self, current_vix: float) -> str:
        """
        Classify 5-day VIX direction using Yahoo historical data.
        Returns: 'rising', 'falling', or 'flat'.
        """
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=10d"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PremiumTrader/1.0)"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return "flat"
                data = resp.json()
                result = data.get("chart", {}).get("result", [])
                if not result:
                    return "flat"
                closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                closes = [c for c in closes if c is not None]
                if len(closes) < 6:
                    return "flat"
                old = closes[-6]
                new = closes[-1]
                if old <= 0:
                    return "flat"
                change = (new - old) / old
                if change > 0.05:
                    return "rising"
                elif change < -0.05:
                    return "falling"
                return "flat"
        except Exception:
            return "flat"

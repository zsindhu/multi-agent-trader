"""
Market Feed — Real-time quote streaming, IV rank calculation, and data caching.
Provides current IV rank for watchlist symbols using Alpaca websockets + historical data.
"""
import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from config.settings import settings
from core.broker import Broker


class MarketDataCache:
    """
    In-memory cache for market data with TTL expiration.
    Falls back to this when Redis is unavailable.
    """

    def __init__(self, default_ttl: int = 60):
        self._cache: dict[str, dict] = {}
        self._timestamps: dict[str, float] = {}
        self._ttl = default_ttl

    def get(self, key: str) -> Optional[dict]:
        if key in self._cache:
            if time.time() - self._timestamps[key] < self._ttl:
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None

    def set(self, key: str, value: dict, ttl: Optional[int] = None):
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def invalidate(self, key: str):
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    def clear(self):
        self._cache.clear()
        self._timestamps.clear()


class MarketFeed:
    """
    Market data service providing:
    - Real-time quote streaming via Alpaca websocket
    - IV rank calculation (current IV percentile vs 52-week range)
    - Cached market data for fast lookups
    """

    def __init__(self, broker: Optional[Broker] = None):
        if broker is None:
            from services.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()
        self.broker = broker
        self.cache = MarketDataCache(default_ttl=60)

        # Real-time quote storage
        self._quotes: dict[str, dict] = {}
        self._quote_callbacks: list = []
        self._streaming = False
        self._stream_task: Optional[asyncio.Task] = None

        # IV history for IV rank calculation (symbol -> list of IV values)
        self._iv_history: dict[str, list[float]] = defaultdict(list)
        self._iv_history_loaded: set[str] = set()

    # ── Real-Time Quote Streaming ─────────────────────────────────────

    async def start_streaming(self, symbols: list[str]):
        """
        Start real-time quote streaming via Alpaca websocket.
        Updates internal quote cache on each tick.
        """
        if self._streaming:
            logger.warning("Streaming already active")
            return

        try:
            from alpaca.data.live import StockDataStream

            stream = StockDataStream(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
            )

            async def _handle_quote(data):
                symbol = data.symbol
                quote = {
                    "symbol": symbol,
                    "bid": float(data.bid_price) if data.bid_price else 0.0,
                    "ask": float(data.ask_price) if data.ask_price else 0.0,
                    "bid_size": int(data.bid_size) if data.bid_size else 0,
                    "ask_size": int(data.ask_size) if data.ask_size else 0,
                    "timestamp": str(data.timestamp),
                    "mid": (
                        (float(data.bid_price) + float(data.ask_price)) / 2
                        if data.bid_price and data.ask_price
                        else 0.0
                    ),
                }
                self._quotes[symbol] = quote
                self.cache.set(f"quote:{symbol}", quote, ttl=30)

                # Notify callbacks
                for cb in self._quote_callbacks:
                    try:
                        await cb(quote)
                    except Exception as e:
                        logger.error(f"Quote callback error: {e}")

            stream.subscribe_quotes(_handle_quote, *symbols)
            self._streaming = True
            logger.info(f"Starting quote stream for {len(symbols)} symbols")

            # Run in background
            self._stream_task = asyncio.create_task(
                asyncio.to_thread(stream.run)
            )

        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            self._streaming = False

    async def stop_streaming(self):
        """Stop the quote stream."""
        self._streaming = False
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None
        logger.info("Quote stream stopped")

    def on_quote(self, callback):
        """Register a callback for real-time quote updates."""
        self._quote_callbacks.append(callback)

    # ── Quote Retrieval ───────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> dict:
        """
        Get latest quote for a symbol.
        First checks streaming cache, then API.
        """
        # Check streaming cache
        if symbol in self._quotes:
            return self._quotes[symbol]

        # Check general cache
        cached = self.cache.get(f"quote:{symbol}")
        if cached:
            return cached

        # Fetch from API
        quote = await self.broker.get_latest_quote(symbol)
        if quote:
            quote["mid"] = (quote.get("bid", 0) + quote.get("ask", 0)) / 2
            self._quotes[symbol] = quote
            self.cache.set(f"quote:{symbol}", quote, ttl=30)
        return quote

    async def get_current_price(self, symbol: str) -> float:
        """Get the current mid price for a symbol."""
        quote = await self.get_quote(symbol)
        if quote and quote.get("mid", 0) > 0:
            return quote["mid"]
        # Fallback: use last close from daily bars
        bars = await self.broker.get_historical_bars(symbol, "1Day", days_back=5)
        if bars:
            return bars[-1]["close"]
        return 0.0

    # ── IV Rank Calculation ───────────────────────────────────────────

    async def _load_iv_history(self, symbol: str):
        """
        Load 52-week IV history for a symbol.
        Uses historical option chain snapshots to build an IV time series.
        We approximate IV history using historical ATM option IV from daily bars.
        """
        if symbol in self._iv_history_loaded:
            return

        try:
            # Get 1 year of daily bars to compute historical volatility as IV proxy
            bars = await self.broker.get_historical_bars(
                symbol, "1Day", days_back=365
            )
            if not bars or len(bars) < 20:
                logger.warning(f"Insufficient bar data for {symbol} IV history")
                self._iv_history_loaded.add(symbol)
                return

            # Calculate rolling 20-day realized volatility as IV proxy
            # (this is common when historical IV data isn't directly available)
            import math

            closes = [b["close"] for b in bars]
            returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    returns.append(math.log(closes[i] / closes[i - 1]))

            # Rolling 20-day realized vol (annualized)
            window = 20
            iv_series = []
            for i in range(window, len(returns)):
                window_returns = returns[i - window : i]
                if window_returns:
                    std = (
                        sum((r - sum(window_returns) / len(window_returns)) ** 2 for r in window_returns)
                        / len(window_returns)
                    ) ** 0.5
                    annualized_vol = std * math.sqrt(252)
                    iv_series.append(annualized_vol)

            self._iv_history[symbol] = iv_series
            self._iv_history_loaded.add(symbol)
            logger.debug(
                f"Loaded IV history for {symbol}: {len(iv_series)} data points, "
                f"range [{min(iv_series):.2f}, {max(iv_series):.2f}]"
            )

        except Exception as e:
            logger.error(f"Failed to load IV history for {symbol}: {e}")
            self._iv_history_loaded.add(symbol)

    async def get_iv_rank(self, symbol: str) -> float:
        """
        Calculate IV rank: where current IV sits relative to 52-week range.

        IV Rank = (Current IV - 52w Low IV) / (52w High IV - 52w Low IV) * 100

        Returns:
            Float 0-100 representing IV percentile. Returns -1 if insufficient data.
        """
        await self._load_iv_history(symbol)

        iv_series = self._iv_history.get(symbol, [])
        if len(iv_series) < 20:
            logger.warning(f"Insufficient IV data for {symbol} rank calculation")
            return -1.0

        # Get current IV (most recent value in the series)
        # Ideally we'd fetch live ATM IV from the options chain
        current_iv = await self._get_current_iv(symbol)
        if current_iv <= 0:
            current_iv = iv_series[-1]  # fallback to last computed

        iv_low = min(iv_series)
        iv_high = max(iv_series)

        if iv_high == iv_low:
            return 50.0  # flat IV, return neutral

        iv_rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100.0
        iv_rank = max(0.0, min(100.0, iv_rank))

        # Cache the result
        self.cache.set(f"iv_rank:{symbol}", {"iv_rank": iv_rank, "current_iv": current_iv}, ttl=300)

        return round(iv_rank, 1)

    async def _get_current_iv(self, symbol: str) -> float:
        """
        Get current implied volatility for a symbol by looking at
        near-ATM options with ~30 DTE.
        """
        cached = self.cache.get(f"current_iv:{symbol}")
        if cached:
            return cached.get("iv", 0.0)

        try:
            price = await self.get_current_price(symbol)
            if price <= 0:
                return 0.0

            # Fetch near-term options to get ATM IV
            now = datetime.now()
            chain = await self.broker.get_options_chain(
                symbol=symbol,
                expiration_date_gte=(now + timedelta(days=20)).strftime("%Y-%m-%d"),
                expiration_date_lte=(now + timedelta(days=45)).strftime("%Y-%m-%d"),
            )

            if not chain:
                return 0.0

            # Find the ATM options (closest strike to current price)
            atm_options = sorted(
                [c for c in chain if c.get("implied_volatility", 0) > 0],
                key=lambda c: abs(c["strike"] - price),
            )

            if not atm_options:
                return 0.0

            # Average IV of the 2-4 closest-to-ATM options
            n = min(4, len(atm_options))
            avg_iv = sum(c["implied_volatility"] for c in atm_options[:n]) / n

            self.cache.set(f"current_iv:{symbol}", {"iv": avg_iv}, ttl=300)
            return avg_iv

        except Exception as e:
            logger.error(f"Failed to get current IV for {symbol}: {e}")
            return 0.0

    async def get_iv_ranks(self, symbols: list[str]) -> dict[str, float]:
        """
        Get IV rank for a list of symbols.

        Returns:
            Dict mapping symbol -> IV rank (0-100)
        """
        results = {}
        tasks = [self.get_iv_rank(sym) for sym in symbols]
        ranks = await asyncio.gather(*tasks, return_exceptions=True)

        for sym, rank in zip(symbols, ranks):
            if isinstance(rank, Exception):
                logger.error(f"IV rank failed for {sym}: {rank}")
                results[sym] = -1.0
            else:
                results[sym] = rank

        return results

    # ── Support / Resistance Detection ────────────────────────────────

    async def get_support_levels(self, symbol: str, lookback_days: int = 60) -> list[float]:
        """
        Identify recent support levels for a symbol.
        Uses swing lows from daily price data.
        """
        cached = self.cache.get(f"support:{symbol}")
        if cached:
            return cached.get("levels", [])

        bars = await self.broker.get_historical_bars(symbol, "1Day", lookback_days)
        if not bars or len(bars) < 10:
            return []

        lows = [b["low"] for b in bars]
        support_levels = []

        # Find local minimums (swing lows)
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
               lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                support_levels.append(lows[i])

        # Also include the 20-day low
        recent_20d_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        if recent_20d_low not in support_levels:
            support_levels.append(recent_20d_low)

        # Sort descending (strongest/nearest first)
        support_levels.sort(reverse=True)

        self.cache.set(f"support:{symbol}", {"levels": support_levels}, ttl=3600)
        return support_levels

    async def is_near_support(
        self, symbol: str, current_price: float, buffer_pct: float = 0.05
    ) -> bool:
        """
        Check if current price is within buffer_pct of a support level.
        """
        support_levels = await self.get_support_levels(symbol)
        if not support_levels:
            return False

        for level in support_levels:
            distance_pct = (current_price - level) / current_price
            if 0 <= distance_pct <= buffer_pct:
                return True

        return False

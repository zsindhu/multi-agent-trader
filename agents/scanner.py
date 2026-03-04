"""
Scanner Agent — Dynamic Universe Discovery + Scored Opportunity Ranking.

Instead of scanning a hardcoded symbol list, the Scanner:
1. Queries the Broker for ALL tradable, optionable assets (stocks + ETFs)
2. Applies a cheap batch pre-filter (volume, price, basic OI check)
3. Full-analyses only survivors: IV rank, momentum, MA distance, liquidity, support
4. Scores with a weighted composite, writes to ScannerOpportunity table
5. Exposes get_top_opportunities(n) for the Lead Agent

Smart caching:
- IV history: loads once at market open, cached 12 hours
- Historical bars: cached 12 hours (momentum/MA don't change intraday)
- Support levels: cached 24 hours (swing lows are static intraday)
- Pre-filter results: cached 12 hours (discovery runs once, midday reuses)

ETF support:
- Classifies each asset as "stock" or "etf"
- IV rank threshold lowered by etf.iv_rank_discount for ETFs
- Broad index ETFs get reduced support weight
- ETFs get a liquidity bonus in composite scoring
- ETFs bypass future earnings avoidance filters

Runs 2x daily (market open + midday). All config in scanner_universe.yaml.
"""
import asyncio
import time
from datetime import datetime
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import select, desc

from agents.base_agent import BaseAgent
from core.broker import Broker
from core.database import AsyncSessionLocal
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer
from models.opportunity import ScannerOpportunity


# ── Configuration ─────────────────────────────────────────────────


def _load_scanner_config() -> dict:
    """Load scanner config from config/scanner_universe.yaml."""
    try:
        with open("config/scanner_universe.yaml", "r") as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("scanner", {})
    except FileNotFoundError:
        logger.warning("scanner_universe.yaml not found — using defaults")
        return {}


# ── Smart Cache ───────────────────────────────────────────────────


class _TTLCache:
    """Simple dict-based cache with per-key TTL."""

    def __init__(self):
        self._data: dict[str, tuple[float, object]] = {}  # key -> (expires_at, value)

    def get(self, key: str) -> Optional[object]:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: object, ttl: int):
        self._data[key] = (time.time() + ttl, value)

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def clear(self):
        self._data.clear()

    def invalidate_prefix(self, prefix: str):
        keys = [k for k in self._data if k.startswith(prefix)]
        for k in keys:
            del self._data[k]


# ── Scanner Agent ─────────────────────────────────────────────────


class ScannerAgent(BaseAgent):
    """
    Scanner Agent — Dynamic universe discovery, scoring, DB persistence.

    Lifecycle: scan() → evaluate() → execute()
    scan()   = discover universe + pre-filter + full analysis
    evaluate() = composite scoring + ranking
    execute()  = persist to ScannerOpportunity table
    """

    def __init__(
        self,
        broker: Optional[Broker] = None,
        market_feed: Optional[MarketFeed] = None,
        options_chain: Optional[OptionsChainAnalyzer] = None,
    ):
        super().__init__(name="Scanner", agent_type="scanner")
        self.broker = broker
        self.market_feed = market_feed
        self.options_chain = options_chain

        # Load config
        self.config = _load_scanner_config()

        # Pre-filter thresholds
        self.min_daily_volume = self.config.get("min_daily_volume", 1_000_000)
        self.min_price = self.config.get("min_price", 5.0)
        self.max_price = self.config.get("max_price", 500.0)
        self.min_options_oi = self.config.get("min_options_oi", 100)

        # Scoring weights
        weights = self.config.get("weights", {})
        self.weight_iv_rank = weights.get("iv_rank", 0.30)
        self.weight_momentum = weights.get("momentum", 0.20)
        self.weight_liquidity = weights.get("liquidity", 0.25)
        self.weight_support = weights.get("support_proximity", 0.15)
        self.weight_mean_reversion = weights.get("mean_reversion", 0.10)

        # Thresholds
        self.min_iv_rank = self.config.get("min_iv_rank", 15)
        self.min_liquidity = self.config.get("min_liquidity_score", 0.3)
        self.max_spread_pct = self.config.get("max_spread_pct", 0.10)
        self.top_n = self.config.get("top_n", 20)

        # Technical parameters
        self.momentum_days = self.config.get("momentum_lookback_days", 30)
        self.ma_short = self.config.get("ma_short_period", 20)
        self.ma_long = self.config.get("ma_long_period", 50)

        # Cache TTLs
        cache_cfg = self.config.get("cache", {})
        self.ttl_iv_history = cache_cfg.get("iv_history_ttl", 43200)
        self.ttl_bars = cache_cfg.get("historical_bars_ttl", 43200)
        self.ttl_support = cache_cfg.get("support_levels_ttl", 86400)
        self.ttl_prefilter = cache_cfg.get("prefilter_ttl", 43200)

        # ETF config
        etf_cfg = self.config.get("etf", {})
        self.etf_iv_discount = etf_cfg.get("iv_rank_discount", 10)
        self.etf_support_weight_reduction = etf_cfg.get("support_weight_reduction", 0.5)
        self.etf_liquidity_bonus = etf_cfg.get("liquidity_bonus", 0.10)
        self.broad_index_etfs = set(etf_cfg.get("broad_index_etfs", ["SPY", "QQQ", "IWM", "DIA"]))

        # Override lists
        self.always_include = set(self.config.get("always_include", []))
        self.always_exclude = set(self.config.get("always_exclude", []))

    def _load_config(self):
        """Reload config from scanner_universe.yaml (called by API after param changes)."""
        self.config = _load_scanner_config()
        weights = self.config.get("weights", {})
        self.weight_iv_rank = weights.get("iv_rank", 0.30)
        self.weight_momentum = weights.get("momentum", 0.20)
        self.weight_liquidity = weights.get("liquidity", 0.25)
        self.weight_support = weights.get("support_proximity", 0.15)
        self.weight_mean_reversion = weights.get("mean_reversion", 0.10)
        self.min_daily_volume = self.config.get("min_daily_volume", 1_000_000)
        self.min_price = self.config.get("min_price", 5.0)
        self.max_price = self.config.get("max_price", 500.0)
        self.min_iv_rank = self.config.get("min_iv_rank", 15)
        self.min_liquidity = self.config.get("min_liquidity_score", 0.3)
        self.top_n = self.config.get("top_n", 20)
        self.always_include = set(self.config.get("always_include", []))
        self.always_exclude = set(self.config.get("always_exclude", []))
        logger.info("[Scanner] Config reloaded from scanner_universe.yaml")

        # Smart caches
        self._cache = _TTLCache()

        # In-memory results
        self._latest_opportunities: list[dict] = []
        self._last_scan_at: Optional[datetime] = None
        # Asset type map: symbol -> "stock" or "etf" (populated during discovery)
        self._asset_type_map: dict[str, str] = {}

        logger.info(
            f"[{self.name}] Initialized — dynamic universe discovery mode, "
            f"always_include={len(self.always_include)}, "
            f"always_exclude={len(self.always_exclude)}"
        )

    # ══════════════════════════════════════════════════════════════
    # SCAN — Discover universe + pre-filter + full analysis
    # ══════════════════════════════════════════════════════════════

    async def scan(self) -> list[dict]:
        """
        Full scan pipeline:
        1. Discover tradable optionable assets from broker (cached)
        2. Batch pre-filter by volume + price (one batched bar request)
        3. Full expensive analysis on survivors only
        """
        if not self.broker or not self.market_feed:
            logger.warning(f"[{self.name}] Missing broker or market_feed — skipping scan")
            return []

        # Step 1: Discover + pre-filter (uses cache on midday scan)
        prefiltered = await self._get_prefiltered_universe()
        if not prefiltered:
            logger.warning(f"[{self.name}] Pre-filter returned 0 symbols")
            return []

        logger.info(
            f"[{self.name}] Pre-filter passed: {len(prefiltered)} symbols — "
            f"starting full analysis..."
        )

        # Step 2: Batch IV ranks
        symbols = [p["symbol"] for p in prefiltered]
        iv_ranks = await self.market_feed.get_iv_ranks(symbols)

        # Step 3: Full analysis on each survivor (concurrency-limited)
        sem = asyncio.Semaphore(10)
        tasks = [
            self._analyze_symbol(p, iv_ranks.get(p["symbol"], -1), sem)
            for p in prefiltered
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        opportunities = []
        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"[{self.name}] Analysis error: {result}")
            elif result is not None:
                opportunities.append(result)

        logger.info(
            f"[{self.name}] Scan complete: {len(opportunities)}/{len(prefiltered)} "
            f"passed full analysis"
        )
        return opportunities

    # ── Universe Discovery ────────────────────────────────────────

    async def _get_prefiltered_universe(self) -> list[dict]:
        """
        Discover + pre-filter the universe.
        Cached for ttl_prefilter seconds so the midday scan reuses morning results.
        """
        cached = self._cache.get("prefiltered_universe")
        if cached is not None:
            logger.info(f"[{self.name}] Using cached pre-filter ({len(cached)} symbols)")
            return cached

        # Step 1: Query broker for all tradable, optionable assets
        logger.info(f"[{self.name}] Discovering tradable optionable assets from broker...")
        all_assets = await self.broker.get_tradable_assets(options_enabled=True)

        # Build asset type map
        self._asset_type_map = {a["symbol"]: a["asset_type"] for a in all_assets}

        # Remove excluded symbols
        candidates = [
            a for a in all_assets
            if a["symbol"] not in self.always_exclude
        ]
        logger.info(
            f"[{self.name}] Broker returned {len(all_assets)} assets, "
            f"{len(candidates)} after exclusions"
        )

        # Step 2: Batch pre-filter by price + volume
        # Pull 5 days of daily bars in one batched request
        candidate_symbols = [a["symbol"] for a in candidates]

        # Add always_include symbols that may have been missed
        for sym in self.always_include:
            if sym not in candidate_symbols and sym not in self.always_exclude:
                candidate_symbols.append(sym)
                # Default to ETF if in always_include and unknown
                if sym not in self._asset_type_map:
                    self._asset_type_map[sym] = "etf"

        logger.info(f"[{self.name}] Fetching batch bars for {len(candidate_symbols)} symbols...")
        bars_batch = await self.broker.get_historical_bars_batch(
            candidate_symbols, timeframe="1Day", days_back=5
        )

        # Apply pre-filter
        prefiltered = []
        for sym in candidate_symbols:
            bars = bars_batch.get(sym, [])
            is_always_include = sym in self.always_include

            # Must have at least 1 bar (unless always_include)
            if not bars and not is_always_include:
                continue

            if bars:
                # Average daily volume
                avg_volume = sum(b["volume"] for b in bars) / len(bars)
                # Latest close price
                latest_close = bars[-1]["close"]
            else:
                avg_volume = 0
                latest_close = 0

            # Volume filter (skip for always_include)
            if avg_volume < self.min_daily_volume and not is_always_include:
                continue

            # Price filter (skip for always_include)
            if (latest_close < self.min_price or latest_close > self.max_price) and not is_always_include:
                continue

            asset_type = self._asset_type_map.get(sym, "stock")

            prefiltered.append({
                "symbol": sym,
                "asset_type": asset_type,
                "avg_daily_volume": round(avg_volume),
                "latest_close": latest_close,
                "is_always_include": is_always_include,
            })

        # Cache the pre-filter results
        self._cache.set("prefiltered_universe", prefiltered, self.ttl_prefilter)

        logger.info(
            f"[{self.name}] Pre-filter: {len(prefiltered)}/{len(candidate_symbols)} passed "
            f"(vol >= {self.min_daily_volume:,}, price ${self.min_price}-${self.max_price})"
        )
        return prefiltered

    # ── Full Symbol Analysis ──────────────────────────────────────

    async def _analyze_symbol(
        self, prefilter_data: dict, iv_rank: float, sem: asyncio.Semaphore
    ) -> Optional[dict]:
        """
        Full expensive analysis for a single symbol that passed pre-filter.

        Computes: IV rank check, momentum, MA distance, liquidity score, support.
        Uses smart caching for bars + support levels.
        """
        async with sem:
            symbol = prefilter_data["symbol"]
            asset_type = prefilter_data["asset_type"]
            avg_volume = prefilter_data["avg_daily_volume"]

            try:
                # IV rank threshold (lower for ETFs)
                effective_min_iv = self.min_iv_rank
                if asset_type == "etf":
                    effective_min_iv = max(0, self.min_iv_rank - self.etf_iv_discount)

                if iv_rank < effective_min_iv and not prefilter_data.get("is_always_include"):
                    return None

                # Get current price
                current_price = prefilter_data.get("latest_close", 0)
                if current_price <= 0:
                    current_price = await self.market_feed.get_current_price(symbol)
                if current_price <= 0:
                    return None

                # Historical bars (cached 12h)
                bars = await self._get_cached_bars(symbol)
                if not bars or len(bars) < self.ma_short:
                    return None

                closes = [b["close"] for b in bars]

                # Momentum
                momentum_30d = self._calc_momentum(closes, self.momentum_days)

                # MA distances
                dist_20ma = self._calc_ma_distance(closes, current_price, self.ma_short)
                dist_50ma = self._calc_ma_distance(closes, current_price, self.ma_long)

                # Liquidity score
                liquidity_score = await self._calc_liquidity_score(symbol, current_price)

                # ETF liquidity bonus
                if asset_type == "etf":
                    liquidity_score = min(1.0, liquidity_score + self.etf_liquidity_bonus)

                if liquidity_score < self.min_liquidity and not prefilter_data.get("is_always_include"):
                    return None

                # Support proximity (cached 24h)
                near_support = await self._get_cached_support(symbol, current_price)

                return {
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "current_price": current_price,
                    "avg_daily_volume": avg_volume,
                    "iv_rank": iv_rank,
                    "momentum_30d": momentum_30d,
                    "distance_from_20ma": dist_20ma,
                    "distance_from_50ma": dist_50ma,
                    "options_liquidity_score": liquidity_score,
                    "near_support": near_support,
                }

            except Exception as e:
                logger.debug(f"[{self.name}] Error analyzing {symbol}: {e}")
                return None

    # ── Cached Data Fetchers ──────────────────────────────────────

    async def _get_cached_bars(self, symbol: str) -> list[dict]:
        """Fetch historical bars with 12h cache."""
        cache_key = f"bars:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        bars = await self.broker.get_historical_bars(
            symbol, "1Day", days_back=max(self.ma_long + 10, self.momentum_days + 5)
        )
        if bars:
            self._cache.set(cache_key, bars, self.ttl_bars)
        return bars or []

    async def _get_cached_support(self, symbol: str, current_price: float) -> bool:
        """Check support proximity with 24h cache."""
        cache_key = f"support:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            # cached is the list of support levels
            return self._is_near_support(current_price, cached)

        # Fetch and cache support levels
        support_levels = await self.market_feed.get_support_levels(symbol)
        self._cache.set(cache_key, support_levels, self.ttl_support)
        return self._is_near_support(current_price, support_levels)

    @staticmethod
    def _is_near_support(price: float, levels: list[float], buffer_pct: float = 0.05) -> bool:
        """Check if price is within buffer of any support level."""
        for level in levels:
            if price <= 0:
                return False
            distance_pct = (price - level) / price
            if 0 <= distance_pct <= buffer_pct:
                return True
        return False

    # ══════════════════════════════════════════════════════════════
    # EVALUATE — Composite scoring + ranking
    # ══════════════════════════════════════════════════════════════

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """
        Score each opportunity with a weighted composite and rank.

        ETF adjustments applied during scoring:
        - Broad index ETFs get reduced support weight
        - ETFs get calibrated IV thresholds
        """
        if not opportunities:
            return []

        for opp in opportunities:
            opp["composite_score"] = self._compute_composite_score(opp)

        opportunities.sort(key=lambda o: o["composite_score"], reverse=True)

        if opportunities:
            logger.info(
                f"[{self.name}] Scored {len(opportunities)} opportunities — "
                f"Top: {opportunities[0]['symbol']} "
                f"({opportunities[0].get('asset_type', '?')}, "
                f"score={opportunities[0]['composite_score']:.3f}), "
                f"Bottom: {opportunities[-1]['symbol']} "
                f"({opportunities[-1]['composite_score']:.3f})"
            )

        return opportunities

    def _compute_composite_score(self, opp: dict) -> float:
        """
        Weighted composite score with ETF-aware adjustments.

        Factors (all normalized 0-1):
        1. IV Rank — higher = better for premium selling
        2. Momentum — mild pullback preferred for put entry
        3. Liquidity — tighter spreads + deeper OI
        4. Support proximity — near support = safer put entry
        5. Mean reversion — close to 20-day MA = stable
        """
        asset_type = opp.get("asset_type", "stock")
        is_broad_etf = opp.get("symbol") in self.broad_index_etfs

        # Factor 1: IV Rank (0-100 → 0-1)
        iv_score = min(max(opp.get("iv_rank", 0), 0), 100) / 100.0

        # Factor 2: Momentum — mild pullback ideal for CSP entry
        mom = opp.get("momentum_30d", 0)
        if -8 <= mom <= -2:
            mom_score = 1.0   # Sweet spot: mild pullback
        elif -15 <= mom < -8:
            mom_score = 0.6   # Deeper pullback — still ok
        elif -2 < mom <= 3:
            mom_score = 0.7   # Flat/slight up — decent
        elif 3 < mom <= 10:
            mom_score = 0.4   # Strong up — less ideal for puts
        else:
            mom_score = 0.2   # Extreme move either direction

        # Factor 3: Liquidity (already 0-1, ETF bonus already applied)
        liq_score = min(max(opp.get("options_liquidity_score", 0), 0), 1.0)

        # Factor 4: Support proximity
        support_score = 1.0 if opp.get("near_support", False) else 0.3

        # Factor 5: Mean reversion — distance from 20MA
        dist_20 = abs(opp.get("distance_from_20ma", 0))
        mr_score = max(0, 1.0 - (dist_20 / 10.0))

        # ETF adjustments
        w_support = self.weight_support
        if is_broad_etf:
            # Broad index ETFs mean-revert differently — reduce support weight
            w_support *= self.etf_support_weight_reduction

        # Re-normalize weights if we reduced support weight
        total_weight = (
            self.weight_iv_rank
            + self.weight_momentum
            + self.weight_liquidity
            + w_support
            + self.weight_mean_reversion
        )

        composite = (
            self.weight_iv_rank * iv_score
            + self.weight_momentum * mom_score
            + self.weight_liquidity * liq_score
            + w_support * support_score
            + self.weight_mean_reversion * mr_score
        )

        # Normalize so weights always sum to 1.0 effective
        if total_weight > 0:
            composite /= total_weight

        return round(composite, 4)

    # ══════════════════════════════════════════════════════════════
    # EXECUTE — Persist to DB
    # ══════════════════════════════════════════════════════════════

    async def execute(self, trades: list[dict]) -> list[dict]:
        """
        Persist scored opportunities to the ScannerOpportunity table.
        Scanner doesn't place trades — 'execute' writes scan results to DB.
        """
        if not trades:
            return []

        scan_time = datetime.utcnow()

        async with AsyncSessionLocal() as session:
            records = []
            for opp in trades:
                record = ScannerOpportunity(
                    symbol=opp["symbol"],
                    asset_type=opp.get("asset_type", "stock"),
                    iv_rank=opp.get("iv_rank"),
                    momentum_30d=opp.get("momentum_30d"),
                    distance_from_20ma=opp.get("distance_from_20ma"),
                    distance_from_50ma=opp.get("distance_from_50ma"),
                    options_liquidity_score=opp.get("options_liquidity_score"),
                    near_support=opp.get("near_support", False),
                    composite_score=opp.get("composite_score", 0),
                    avg_daily_volume=opp.get("avg_daily_volume"),
                    scanned_at=scan_time,
                )
                session.add(record)
                records.append(record)

            await session.commit()

        # Update in-memory cache
        self._latest_opportunities = trades
        self._last_scan_at = scan_time

        # Count by type
        stocks = sum(1 for o in trades if o.get("asset_type") == "stock")
        etfs = sum(1 for o in trades if o.get("asset_type") == "etf")
        logger.info(
            f"[{self.name}] Persisted {len(records)} opportunities "
            f"({stocks} stocks, {etfs} ETFs) at {scan_time.strftime('%H:%M:%S')}"
        )
        return trades

    # ══════════════════════════════════════════════════════════════
    # MANAGE POSITIONS — N/A for Scanner
    # ══════════════════════════════════════════════════════════════

    async def manage_positions(self) -> list[dict]:
        """Scanner doesn't manage positions."""
        return []

    # ══════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════

    async def get_top_opportunities(self, n: Optional[int] = None) -> list[dict]:
        """
        Return top N scored opportunities for the Lead Agent.

        Cache-first, DB fallback.

        Args:
            n: Number of opportunities (default: self.top_n)

        Returns:
            Sorted list of opportunity dicts (composite_score descending).
        """
        n = n or self.top_n

        if self._latest_opportunities:
            return self._latest_opportunities[:n]

        return await self._query_latest_from_db(n)

    async def _query_latest_from_db(self, n: int = 20) -> list[dict]:
        """Query the most recent scan results from the database."""
        async with AsyncSessionLocal() as session:
            latest_time_stmt = select(ScannerOpportunity.scanned_at).order_by(
                desc(ScannerOpportunity.scanned_at)
            ).limit(1)
            result = await session.execute(latest_time_stmt)
            latest_time = result.scalar_one_or_none()

            if not latest_time:
                return []

            stmt = (
                select(ScannerOpportunity)
                .where(ScannerOpportunity.scanned_at == latest_time)
                .order_by(desc(ScannerOpportunity.composite_score))
                .limit(n)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "symbol": r.symbol,
                    "asset_type": r.asset_type,
                    "iv_rank": r.iv_rank,
                    "momentum_30d": r.momentum_30d,
                    "distance_from_20ma": r.distance_from_20ma,
                    "distance_from_50ma": r.distance_from_50ma,
                    "options_liquidity_score": r.options_liquidity_score,
                    "near_support": r.near_support,
                    "composite_score": r.composite_score,
                    "avg_daily_volume": r.avg_daily_volume,
                    "scanned_at": r.scanned_at.isoformat() if r.scanned_at else None,
                }
                for r in rows
            ]

    def get_asset_type(self, symbol: str) -> str:
        """Get asset type (stock/etf) for a symbol."""
        return self._asset_type_map.get(symbol, "stock")

    # ══════════════════════════════════════════════════════════════
    # METRIC CALCULATIONS
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _calc_momentum(closes: list[float], days: int) -> float:
        """% price change over N days."""
        if len(closes) < days + 1:
            return 0.0
        old_price = closes[-(days + 1)]
        new_price = closes[-1]
        if old_price <= 0:
            return 0.0
        return round(((new_price - old_price) / old_price) * 100, 2)

    @staticmethod
    def _calc_ma_distance(closes: list[float], current_price: float, period: int) -> float:
        """% distance from a moving average. Positive = above MA."""
        if len(closes) < period:
            return 0.0
        ma = sum(closes[-period:]) / period
        if ma <= 0:
            return 0.0
        return round(((current_price - ma) / ma) * 100, 2)

    async def _calc_liquidity_score(self, symbol: str, current_price: float) -> float:
        """
        Options liquidity score (0-1) based on ATM bid-ask spread + open interest.
        """
        if not self.options_chain:
            return 0.5

        try:
            chain = await self.options_chain.get_filtered_chain(
                symbol=symbol,
                contract_type="put",
                dte_min=20,
                dte_max=45,
                delta_min=0.20,
                delta_max=0.40,
                min_open_interest=1,
                min_bid=0.01,
            )

            if not chain:
                return 0.0

            spreads = []
            oi_values = []
            for c in chain[:10]:
                bid = c.get("bid", 0)
                ask = c.get("ask", 0)
                mid = c.get("mid_price", 0) or ((bid + ask) / 2)
                oi = c.get("open_interest", 0)

                if mid > 0:
                    spread_pct = (ask - bid) / mid
                    spreads.append(spread_pct)
                oi_values.append(oi)

            if not spreads:
                return 0.0

            avg_spread = sum(spreads) / len(spreads)
            avg_oi = sum(oi_values) / len(oi_values) if oi_values else 0

            spread_score = max(0, 1.0 - (avg_spread / self.max_spread_pct))
            oi_score = min(avg_oi / 1000.0, 1.0)

            liquidity = 0.6 * spread_score + 0.4 * oi_score
            return round(min(max(liquidity, 0), 1.0), 3)

        except Exception as e:
            logger.debug(f"[{self.name}] Liquidity calc failed for {symbol}: {e}")
            return 0.0

    # ══════════════════════════════════════════════════════════════
    # WORKSHOP SUPPORT (Phase 9)
    # ══════════════════════════════════════════════════════════════

    async def simulate_with_params(self, overrides: dict) -> list[dict]:
        """
        Re-score cached scan data with overridden weights/thresholds.
        Used by the Scanner Workshop for live parameter tuning.
        """
        if not self._latest_opportunities:
            return []

        orig = {
            "weight_iv_rank": self.weight_iv_rank,
            "weight_momentum": self.weight_momentum,
            "weight_liquidity": self.weight_liquidity,
            "weight_support": self.weight_support,
            "weight_mean_reversion": self.weight_mean_reversion,
        }

        self.weight_iv_rank = overrides.get("weight_iv_rank", self.weight_iv_rank)
        self.weight_momentum = overrides.get("weight_momentum", self.weight_momentum)
        self.weight_liquidity = overrides.get("weight_liquidity", self.weight_liquidity)
        self.weight_support = overrides.get("weight_support_proximity", self.weight_support)
        self.weight_mean_reversion = overrides.get("weight_mean_reversion", self.weight_mean_reversion)

        min_iv = overrides.get("min_iv_rank", self.min_iv_rank)

        simulated = []
        for opp in self._latest_opportunities:
            if opp.get("iv_rank", 0) < min_iv:
                continue
            new_opp = dict(opp)
            new_opp["composite_score"] = self._compute_composite_score(new_opp)
            simulated.append(new_opp)

        simulated.sort(key=lambda o: o["composite_score"], reverse=True)

        # Restore
        self.weight_iv_rank = orig["weight_iv_rank"]
        self.weight_momentum = orig["weight_momentum"]
        self.weight_liquidity = orig["weight_liquidity"]
        self.weight_support = orig["weight_support"]
        self.weight_mean_reversion = orig["weight_mean_reversion"]

        return simulated

"""
Universe Loader — Fetches the daily universe of tradeable names.

Pulls all optionable US equities and ETFs from Alpaca, fetches a year of
daily bars in batched calls, computes multi-window volume averages,
applies the universe filters, and trims to the maximum universe size.

Returns a list of enriched name dicts ready to be written to
name_observations as Tier 1 entries.

This is a pure data processing module — it does not write to the database.
The Tier 1 writer (services/tier_writer.py) handles persistence.
"""
from datetime import datetime, timezone
from loguru import logger

from services.alpaca_broker import AlpacaBroker
from services.universe_filters import (
    MIN_PRICE_USD,
    MIN_AVG_DAILY_VOLUME_SHARES,
    MAX_UNIVERSE_SIZE,
    VOLUME_WINDOW_SHORT,
    VOLUME_WINDOW_MEDIUM,
    VOLUME_WINDOW_LONG,
)


class UniverseLoader:
    """Loads and filters the daily universe of tradeable names."""

    def __init__(self, broker: AlpacaBroker):
        self.broker = broker

    async def load_universe(self) -> list[dict]:
        """
        Execute the full universe load pipeline.

        Returns a list of name dicts that passed all filters, sorted by
        daily dollar volume descending.
        """
        passed, _ = await self.load_universe_with_rejections()
        return passed

    async def load_universe_with_rejections(self) -> tuple[list[dict], list[dict]]:
        """
        Same as load_universe but also returns the rejected names with reasons.

        Returns:
            (passed, rejected) where each is a list of name dicts.
            Rejected dicts include a 'rejected_reason' field explaining why.
        """
        start = datetime.now(timezone.utc)
        logger.info("[Universe] Starting universe load...")

        # Step 1: Fetch all optionable assets from Alpaca
        try:
            assets = await self.broker.get_tradable_assets(options_enabled=True)
        except Exception as e:
            logger.error(f"[Universe] Failed to fetch optionable assets: {e}")
            return [], []

        logger.info(f"[Universe] Fetched {len(assets)} optionable assets from Alpaca")

        if not assets:
            logger.warning("[Universe] No assets returned — aborting")
            return [], []

        symbols = [a["symbol"] for a in assets]

        # Step 2: Fetch ~1 year of daily bars for all symbols (batched)
        try:
            bars_by_symbol = await self.broker.get_historical_bars_batch(
                symbols=symbols,
                timeframe="1Day",
                days_back=365,
            )
        except Exception as e:
            logger.error(f"[Universe] Failed to fetch bars batch: {e}")
            return [], []

        logger.info(
            f"[Universe] Fetched bars for {sum(1 for b in bars_by_symbol.values() if b)} "
            f"of {len(symbols)} symbols"
        )

        # Step 3: Build enriched name dicts with volume averages and filter
        passed: list[dict] = []
        rejected: list[dict] = []

        for asset in assets:
            symbol = asset["symbol"]
            bars = bars_by_symbol.get(symbol, [])

            if not bars:
                rejected.append({
                    **asset,
                    "rejected_reason": "no_bars_data",
                })
                continue

            # Sort bars by date descending
            try:
                bars_sorted = sorted(
                    bars,
                    key=lambda b: b.get("timestamp") or b.get("t") or "",
                    reverse=True,
                )
            except Exception:
                bars_sorted = bars

            # Latest price
            try:
                latest_price = float(bars_sorted[0].get("close") or bars_sorted[0].get("c") or 0)
            except (ValueError, TypeError, IndexError):
                rejected.append({
                    **asset,
                    "rejected_reason": "invalid_price_data",
                })
                continue

            if latest_price < MIN_PRICE_USD:
                rejected.append({
                    **asset,
                    "price": latest_price,
                    "rejected_reason": f"price_below_{int(MIN_PRICE_USD)}",
                })
                continue

            # Compute volume averages for three windows
            volumes = []
            for b in bars_sorted:
                try:
                    v = int(b.get("volume") or b.get("v") or 0)
                    volumes.append(v)
                except (ValueError, TypeError):
                    continue

            avg_vol_20 = sum(volumes[:VOLUME_WINDOW_SHORT]) / max(1, min(len(volumes), VOLUME_WINDOW_SHORT))
            avg_vol_60 = sum(volumes[:VOLUME_WINDOW_MEDIUM]) / max(1, min(len(volumes), VOLUME_WINDOW_MEDIUM))
            avg_vol_252 = sum(volumes[:VOLUME_WINDOW_LONG]) / max(1, min(len(volumes), VOLUME_WINDOW_LONG))

            # Volume filter — pass if ANY window meets the threshold
            volume_signals = []
            if avg_vol_20 >= MIN_AVG_DAILY_VOLUME_SHARES:
                volume_signals.append("volume_passed_20d")
            if avg_vol_60 >= MIN_AVG_DAILY_VOLUME_SHARES:
                volume_signals.append("volume_passed_60d")
            if avg_vol_252 >= MIN_AVG_DAILY_VOLUME_SHARES:
                volume_signals.append("volume_passed_252d")

            if not volume_signals:
                rejected.append({
                    **asset,
                    "price": latest_price,
                    "avg_volume_20d": int(avg_vol_20),
                    "avg_volume_60d": int(avg_vol_60),
                    "avg_volume_252d": int(avg_vol_252),
                    "rejected_reason": "volume_below_threshold_all_windows",
                })
                continue

            daily_dollar_volume = latest_price * avg_vol_20

            selection_signals = ["has_options", f"price_above_{int(MIN_PRICE_USD)}"] + volume_signals

            passed.append({
                "symbol": symbol,
                "name": asset.get("name", ""),
                "asset_type": asset.get("asset_type", "stock"),
                "exchange": asset.get("exchange", ""),
                "price": latest_price,
                "market_cap": None,
                "avg_volume_20d": int(avg_vol_20),
                "avg_volume_60d": int(avg_vol_60),
                "avg_volume_252d": int(avg_vol_252),
                "daily_dollar_volume": daily_dollar_volume,
                "selection_signals": selection_signals,
                "selection_score": daily_dollar_volume,
                "selection_reason": "universe_sweep",
            })

        # Step 4: Trim to MAX_UNIVERSE_SIZE if needed
        if len(passed) > MAX_UNIVERSE_SIZE:
            passed.sort(key=lambda x: x["selection_score"], reverse=True)
            displaced = passed[MAX_UNIVERSE_SIZE:]
            passed = passed[:MAX_UNIVERSE_SIZE]
            for d in displaced:
                d["rejected_reason"] = f"outside_top_{MAX_UNIVERSE_SIZE}_by_dollar_volume"
                rejected.append(d)
            logger.info(
                f"[Universe] Trimmed to top {MAX_UNIVERSE_SIZE} "
                f"by daily dollar volume ({len(displaced)} displaced)"
            )

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            f"[Universe] Load complete: {len(passed)} passed, "
            f"{len(rejected)} rejected, {elapsed:.1f}s elapsed"
        )

        return passed, rejected

"""
Strategy — Market regime detection and dynamic parameter adjustment.

Fetches the current VIX level, classifies the market regime, and adjusts
strategy parameters (delta targets, max positions) accordingly.

Regime classification:
  VIX > 25  →  high_vol  → tighten deltas by 0.05, reduce max_positions by 1
  VIX 15-25 →  normal    → use base params
  VIX < 15  →  low_vol   → widen deltas by 0.05, allow +1 max_positions

Usage:
    strategy = StrategyManager(broker)
    await strategy.refresh_regime()
    params = strategy.get_adjusted_params("cash_secured_puts")
"""
from enum import Enum
from typing import Optional

import yaml
from loguru import logger

from core.broker import Broker


class MarketRegime(Enum):
    LOW_VOL = "low_vol"
    NORMAL = "normal"
    HIGH_VOL = "high_vol"


class StrategyManager:
    """
    Loads base strategy params from strategies.yaml, fetches VIX to
    determine market regime, and exposes regime-adjusted parameters.
    """

    # VIX symbols to try — Alpaca doesn't carry ^VIX directly,
    # so we try VIXY / VXX (VIX ETPs) as proxies, or fall back to SPY
    # volatility as a rough VIX estimate.
    _VIX_PROXIES = ["VIXY", "VXX", "UVXY"]

    def __init__(self, broker: Optional[Broker] = None):
        self.broker = broker
        self._base_params = self._load_strategies()
        self._regime = MarketRegime.NORMAL
        self._vix_level: float = 20.0  # default mid-range
        self._last_refresh: Optional[str] = None

    # ── Config Loading ────────────────────────────────────────────

    @staticmethod
    def _load_strategies() -> dict:
        """Load all strategy parameter blocks from strategies.yaml."""
        try:
            with open("config/strategies.yaml", "r") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("[Strategy] strategies.yaml not found — using empty defaults")
            return {}

    # ── Regime Detection ──────────────────────────────────────────

    async def refresh_regime(self):
        """
        Fetch VIX (or proxy) and classify the current market regime.

        Tries multiple VIX proxy ETPs. If none are available, estimates
        volatility from SPY's recent 20-day realized vol (annualized).
        """
        if not self.broker:
            logger.warning("[Strategy] No broker — using default NORMAL regime")
            return

        vix = await self._fetch_vix_level()
        self._vix_level = vix

        if vix > 25:
            self._regime = MarketRegime.HIGH_VOL
        elif vix < 15:
            self._regime = MarketRegime.LOW_VOL
        else:
            self._regime = MarketRegime.NORMAL

        from datetime import datetime
        self._last_refresh = datetime.utcnow().isoformat()

        logger.info(
            f"[Strategy] Regime: {self._regime.value} "
            f"(VIX proxy={vix:.1f}) — refreshed at {self._last_refresh}"
        )

    async def _fetch_vix_level(self) -> float:
        """
        Attempt to get a VIX proxy price.

        Strategy:
        1. Try VIX ETP tickers (VIXY, VXX, UVXY) — these trade on Alpaca
           and roughly track VIX futures. Their absolute price ≠ VIX, but
           we normalize to a VIX-like scale.
        2. If none available, compute SPY 20-day realized vol * √252 as
           a rough VIX approximation.
        """
        # Try VIX proxy ETPs
        for proxy in self._VIX_PROXIES:
            try:
                quote = await self.broker.get_latest_quote(proxy)
                if quote and quote.get("bid", 0) > 0:
                    mid = (quote["bid"] + quote["ask"]) / 2
                    # VIXY/VXX prices don't equal VIX directly.
                    # Use a rough mapping: these ETPs tend to trade
                    # in the $10-$80 range. We'll use a heuristic:
                    # if the proxy is VIXY, its price ≈ VIX * 0.6 historically.
                    # For VXX, price ≈ VIX * 0.8.
                    # This is imperfect but gives us directional signal.
                    if proxy == "VIXY":
                        estimated_vix = mid / 0.6
                    elif proxy == "UVXY":
                        estimated_vix = mid / 1.5
                    else:
                        estimated_vix = mid  # VXX ≈ VIX roughly
                    estimated_vix = max(8, min(80, estimated_vix))
                    logger.debug(f"[Strategy] VIX via {proxy}: mid=${mid:.2f} → VIX≈{estimated_vix:.1f}")
                    return round(estimated_vix, 1)
            except Exception as e:
                logger.debug(f"[Strategy] {proxy} quote failed: {e}")

        # Fallback: SPY realized volatility
        return await self._estimate_vix_from_spy()

    async def _estimate_vix_from_spy(self) -> float:
        """
        Estimate VIX from SPY's recent realized volatility.
        VIX ≈ 20-day realized vol * √252 (annualized).
        """
        try:
            import math
            bars = await self.broker.get_historical_bars("SPY", "1Day", days_back=30)
            if not bars or len(bars) < 20:
                return 20.0  # default

            closes = [b["close"] for b in bars]
            returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    returns.append(math.log(closes[i] / closes[i - 1]))

            if len(returns) < 10:
                return 20.0

            # 20-day realized vol
            window = min(20, len(returns))
            recent = returns[-window:]
            mean = sum(recent) / len(recent)
            variance = sum((r - mean) ** 2 for r in recent) / len(recent)
            daily_vol = math.sqrt(variance)
            annualized_vol = daily_vol * math.sqrt(252) * 100  # as percentage

            logger.debug(f"[Strategy] SPY realized vol → VIX estimate: {annualized_vol:.1f}")
            return round(max(8, min(80, annualized_vol)), 1)

        except Exception as e:
            logger.error(f"[Strategy] SPY vol estimation failed: {e}")
            return 20.0

    # ── Parameter Adjustment ──────────────────────────────────────

    @property
    def regime(self) -> MarketRegime:
        """Current market regime."""
        return self._regime

    @property
    def vix_level(self) -> float:
        """Latest VIX proxy level."""
        return self._vix_level

    def get_adjusted_params(self, strategy_name: str) -> dict:
        """
        Return strategy parameters adjusted for the current market regime.

        Adjustments:
        - HIGH_VOL: delta targets tightened by 0.05 (more OTM),
                    max_positions reduced by 1
        - LOW_VOL:  delta targets widened by 0.05 (slightly closer ATM),
                    max_positions increased by 1
        - NORMAL:   base params unchanged

        Args:
            strategy_name: "covered_calls", "cash_secured_puts", or "wheel"

        Returns:
            Dict of adjusted parameters.
        """
        base = dict(self._base_params.get(strategy_name, {}))

        if self._regime == MarketRegime.HIGH_VOL:
            # Tighten delta targets (more OTM = safer)
            if "delta_target" in base:
                dt = base["delta_target"]
                if dt < 0:  # put delta (negative)
                    base["delta_target"] = round(dt + 0.05, 2)  # e.g. -0.25 → -0.20
                else:  # call delta (positive)
                    base["delta_target"] = round(dt - 0.05, 2)  # e.g. 0.30 → 0.25

            if "csp_delta" in base:
                base["csp_delta"] = round(base["csp_delta"] + 0.05, 2)
            if "cc_delta" in base:
                base["cc_delta"] = round(base["cc_delta"] - 0.05, 2)

            # Reduce max positions
            if "max_positions" in base:
                base["max_positions"] = max(1, base["max_positions"] - 1)

        elif self._regime == MarketRegime.LOW_VOL:
            # Widen delta targets (slightly more ATM for enough premium)
            if "delta_target" in base:
                dt = base["delta_target"]
                if dt < 0:
                    base["delta_target"] = round(dt - 0.05, 2)  # e.g. -0.25 → -0.30
                else:
                    base["delta_target"] = round(dt + 0.05, 2)  # e.g. 0.30 → 0.35

            if "csp_delta" in base:
                base["csp_delta"] = round(base["csp_delta"] - 0.05, 2)
            if "cc_delta" in base:
                base["cc_delta"] = round(base["cc_delta"] + 0.05, 2)

            # Allow one more position
            if "max_positions" in base:
                base["max_positions"] = base["max_positions"] + 1

        # Tag with regime info
        base["_regime"] = self._regime.value
        base["_vix_level"] = self._vix_level

        return base

    def get_regime_summary(self) -> dict:
        """Return a summary of the current regime for logging / dashboard."""
        return {
            "regime": self._regime.value,
            "vix_level": self._vix_level,
            "last_refresh": self._last_refresh,
            "adjustments": self._describe_adjustments(),
        }

    def _describe_adjustments(self) -> str:
        if self._regime == MarketRegime.HIGH_VOL:
            return "Tightened deltas by 0.05, reduced max_positions by 1"
        elif self._regime == MarketRegime.LOW_VOL:
            return "Widened deltas by 0.05, increased max_positions by 1"
        return "No adjustments — normal regime"

"""
Technical Indicators Service — Computes common technical indicators from
OHLCV bar data without external dependencies (no TA-Lib required).

All functions take lists of floats (most-recent-first) and return the
computed values. Pure math — no DB access, no broker calls.

Indicators: RSI, MACD, Bollinger Bands, ATR, SMA, EMA, ADX, OBV.
"""
import math
from typing import Optional


# ── Moving Averages ──────────────────────────────────────────────

def sma(values: list[float], period: int) -> Optional[float]:
    """Simple Moving Average of the most recent `period` values."""
    if len(values) < period:
        return None
    return sum(values[:period]) / period


def ema(values: list[float], period: int) -> Optional[float]:
    """
    Exponential Moving Average.

    Values should be most-recent-first. We reverse internally to
    compute from oldest to newest.
    """
    if len(values) < period:
        return None
    data = list(reversed(values[:period * 2]))  # Use 2x period for warmup
    if len(data) < period:
        data = list(reversed(values))

    multiplier = 2 / (period + 1)
    ema_val = sum(data[:period]) / period  # Seed with SMA

    for price in data[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val

    return ema_val


def sma_series(values: list[float], period: int) -> list[float]:
    """Compute SMA for every valid position. Returns most-recent-first."""
    if len(values) < period:
        return []
    result = []
    for i in range(len(values) - period + 1):
        result.append(sum(values[i : i + period]) / period)
    return result


# ── RSI ──────────────────────────────────────────────────────────

def rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """
    Relative Strength Index (Wilder's smoothing).

    closes: most-recent-first.
    Returns RSI value (0-100) or None if insufficient data.
    """
    if len(closes) < period + 2:
        return None

    # Compute price changes (most-recent-first, so changes[0] = closes[0] - closes[1])
    changes = [closes[i] - closes[i + 1] for i in range(len(closes) - 1)]

    gains = [max(0, c) for c in changes]
    losses = [max(0, -c) for c in changes]

    if len(gains) < period:
        return None

    # Initial average (simple average of first `period` values from the end)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    # Wilder smoothing forward
    for i in range(len(gains) - period - 1, -1, -1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ── MACD ─────────────────────────────────────────────────────────

def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[dict]:
    """
    MACD (Moving Average Convergence Divergence).

    Returns {"macd": float, "signal": float, "histogram": float} or None.
    """
    if len(closes) < slow + signal:
        return None

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)

    if fast_ema is None or slow_ema is None:
        return None

    macd_val = fast_ema - slow_ema

    # For signal line, we need MACD series — approximate with current value
    # (full implementation would compute MACD at every point then EMA of that)
    # This is a simplified version suitable for screening, not precision charting
    return {
        "macd": round(macd_val, 4),
        "signal": None,  # Would need full series computation
        "histogram": None,
    }


# ── Bollinger Bands ──────────────────────────────────────────────

def bollinger_bands(
    closes: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> Optional[dict]:
    """
    Bollinger Bands.

    Returns {"upper": float, "middle": float, "lower": float,
             "width": float, "pct_b": float} or None.
    """
    if len(closes) < period:
        return None

    middle = sum(closes[:period]) / period
    variance = sum((c - middle) ** 2 for c in closes[:period]) / period
    std = math.sqrt(variance)

    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width = (upper - lower) / middle if middle != 0 else 0
    pct_b = (closes[0] - lower) / (upper - lower) if upper != lower else 0.5

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "width": round(width, 4),
        "pct_b": round(pct_b, 4),
    }


# ── ATR ──────────────────────────────────────────────────────────

def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """
    Average True Range.

    Returns ATR value or None if insufficient data.
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    true_ranges = []
    for i in range(period):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i + 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        true_ranges.append(tr)

    return sum(true_ranges) / period


def atr_percent(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """ATR as a percentage of the current price."""
    atr_val = atr(highs, lows, closes, period)
    if atr_val is None or closes[0] == 0:
        return None
    return round((atr_val / closes[0]) * 100, 2)


# ── OBV (On-Balance Volume) ─────────────────────────────────────

def obv_trend(closes: list[float], volumes: list[int], period: int = 20) -> Optional[float]:
    """
    OBV slope over `period` days, normalized by average volume.

    Positive = accumulation, Negative = distribution.
    Returns normalized slope or None.
    """
    if len(closes) < period + 1 or len(volumes) < period + 1:
        return None

    obv = 0
    obv_series = []
    for i in range(period, -1, -1):
        if i < len(closes) - 1:
            if closes[i] < closes[i + 1]:
                obv += volumes[i]
            elif closes[i] > closes[i + 1]:
                obv -= volumes[i]
        obv_series.append(obv)

    if len(obv_series) < 2:
        return None

    # Linear slope of OBV
    n = len(obv_series)
    x_mean = (n - 1) / 2
    y_mean = sum(obv_series) / n
    num = sum((i - x_mean) * (obv_series[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))

    if den == 0:
        return None

    slope = num / den
    avg_vol = sum(volumes[:period]) / period if volumes else 1
    if avg_vol == 0:
        return None

    return round(slope / avg_vol, 4)


# ── Convenience: compute all indicators for a symbol ─────────────

def compute_all(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[int],
) -> dict:
    """
    Compute all available indicators from OHLCV data.

    Returns a flat dict of indicator values. Missing values are None.
    """
    return {
        "rsi_14": rsi(closes, 14),
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "sma_200": sma(closes, 200),
        "ema_12": ema(closes, 12),
        "ema_26": ema(closes, 26),
        "macd": macd(closes),
        "bollinger": bollinger_bands(closes, 20, 2.0),
        "atr_14": atr(highs, lows, closes, 14),
        "atr_pct": atr_percent(highs, lows, closes, 14),
        "obv_trend_20": obv_trend(closes, volumes, 20),
    }

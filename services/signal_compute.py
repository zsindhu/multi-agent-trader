"""
Signal Computation — Pure math functions for Tier 2a change-detection rules.

Each function takes pre-fetched data (lists of floats, bars, etc.) and returns
a dict with {"score": float 0-1, "raw": float, "fired": bool}. No DB access,
no broker calls — pure computation. This makes them testable and reusable.

The 6 rules shipping initially (data exists today):
  1. Volume z-score vs name's own 60d distribution
  2. Range expansion vs 20d ATR
  3. Gap z-score vs name's own 60d overnight gap distribution
  4. IV rank delta over 5 trading days
  7. Correlation breakdown vs sector ETF (SPY)
 10. News density z-score vs 30d baseline

Rules 5, 6, 8, 9, 11 light up as their data dependencies land.
"""
import math
from typing import Optional


def _safe_std(values: list[float]) -> float:
    """Standard deviation with zero-division protection."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def _safe_mean(values: list[float]) -> float:
    """Mean with empty-list protection."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 on degenerate input."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0
    x, y = x[:n], y[:n]
    mx, my = _safe_mean(x), _safe_mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


# ── Rule 1: Volume z-score ─────────────────────────────────────

def volume_zscore(volumes: list[int], window: int = 60) -> dict:
    """
    Z-score of the most recent day's volume vs the name's own distribution.

    Args:
        volumes: Daily volumes, most-recent-first (index 0 = today).
        window: Lookback for mean/std (default 60 trading days).

    Threshold: z >= 2.0. JNJ at 2x average is a five-sigma event;
    NVDA at 2x is noise — per-name baselines handle this automatically.
    """
    if len(volumes) < 10:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    today_vol = volumes[0]
    history = volumes[1 : window + 1]
    mean = _safe_mean(history)
    std = _safe_std(history)

    if std == 0:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    z = (today_vol - mean) / std
    return {
        "score": min(1.0, max(0.0, z / 4.0)),
        "raw": round(z, 2),
        "fired": z >= 2.0,
    }


# ── Rule 2: Range expansion vs ATR ────────────────────────────

def range_expansion_vs_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr_period: int = 20,
) -> dict:
    """
    Today's high-low range divided by the 20-day ATR.

    ATR-relative because absolute dollar moves are useless without
    normalization. A $5 range in AMZN is nothing; $5 in a $20 stock
    is a 25% range.

    Threshold: ratio >= 1.5x.
    """
    if len(highs) < atr_period + 2 or len(lows) < atr_period + 2 or len(closes) < atr_period + 2:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    # Compute True Range for last atr_period+1 days (need prev close)
    true_ranges = []
    for i in range(atr_period + 1):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i + 1] if i + 1 < len(closes) else closes[i]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        true_ranges.append(tr)

    atr = _safe_mean(true_ranges[1:])  # Exclude today from the ATR baseline
    if atr == 0:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    today_range = highs[0] - lows[0]
    ratio = today_range / atr

    return {
        "score": min(1.0, max(0.0, (ratio - 1.0) / 2.0)),
        "raw": round(ratio, 2),
        "fired": ratio >= 1.5,
    }


# ── Rule 3: Gap z-score ───────────────────────────────────────

def gap_zscore(opens: list[float], closes: list[float], window: int = 60) -> dict:
    """
    Z-score of today's overnight gap vs the name's own gap distribution.

    A 2% gap in TSLA is Tuesday; a 2% gap in PG is a major story.
    Per-name baselines handle this automatically.

    Threshold: |z| >= 2.0.
    """
    if len(opens) < 2 or len(closes) < window + 2:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    # Today's gap: (today_open - yesterday_close) / yesterday_close
    today_gap = (opens[0] - closes[1]) / closes[1] if closes[1] != 0 else 0

    # Historical gaps for the distribution
    gaps = []
    for i in range(1, min(window + 1, len(opens))):
        prev_close = closes[i + 1] if i + 1 < len(closes) else closes[i]
        if prev_close != 0:
            gaps.append((opens[i] - prev_close) / prev_close)

    if len(gaps) < 10:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    mean = _safe_mean(gaps)
    std = _safe_std(gaps)
    if std == 0:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    z = abs(today_gap - mean) / std
    return {
        "score": min(1.0, max(0.0, z / 4.0)),
        "raw": round(z, 2),
        "fired": z >= 2.0,
    }


# ── Rule 4: IV rank delta (5-day change) ──────────────────────

def iv_rank_delta(iv_rank_today: float, iv_rank_5d_ago: float) -> dict:
    """
    Absolute change in IV rank over 5 trading days.

    The level is stale; the delta is what matters. Strong leading
    indicator for catalysts.

    Threshold: |delta| >= 15 points.
    """
    delta = iv_rank_today - iv_rank_5d_ago
    abs_delta = abs(delta)

    return {
        "score": min(1.0, max(0.0, abs_delta / 30.0)),
        "raw": round(delta, 1),
        "fired": abs_delta >= 15.0,
    }


# ── Rule 7: Correlation breakdown vs SPY ──────────────────────

def correlation_breakdown(
    symbol_closes: list[float],
    spy_closes: list[float],
    short_window: int = 20,
    long_window: int = 60,
) -> dict:
    """
    Drop in rolling correlation between the symbol and SPY.

    20-day rolling corr vs 60-day average corr. A drop >= 0.3 means
    the name is decoupling from the sector — idiosyncratic story.
    One of the highest-quality signals.

    Threshold: breakdown >= 0.3.
    """
    if len(symbol_closes) < long_window + 1 or len(spy_closes) < long_window + 1:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    # Compute daily returns
    def returns(prices):
        return [(prices[i] - prices[i + 1]) / prices[i + 1]
                for i in range(len(prices) - 1)
                if prices[i + 1] != 0]

    sym_ret = returns(symbol_closes)
    spy_ret = returns(spy_closes)

    if len(sym_ret) < long_window or len(spy_ret) < long_window:
        return {"score": 0.0, "raw": 0.0, "fired": False}

    corr_short = _pearson(sym_ret[:short_window], spy_ret[:short_window])
    corr_long = _pearson(sym_ret[:long_window], spy_ret[:long_window])

    breakdown = corr_long - corr_short  # Positive = correlation dropped recently
    return {
        "score": min(1.0, max(0.0, breakdown / 0.6)),
        "raw": round(breakdown, 3),
        "fired": breakdown >= 0.3,
    }


# ── Rule 10: News density z-score ─────────────────────────────

def news_density_zscore(
    headlines_24h: int,
    headlines_30d_daily_avg: float,
    headlines_30d_daily_std: float,
) -> dict:
    """
    Z-score of today's headline count vs the name's 30-day baseline.

    Most names get 1-2 headlines/week; 8 in a day means something
    is happening.

    Threshold: z >= 2.0.
    """
    if headlines_30d_daily_std == 0:
        if headlines_24h > headlines_30d_daily_avg + 3:
            return {"score": 0.5, "raw": 3.0, "fired": True}
        return {"score": 0.0, "raw": 0.0, "fired": False}

    z = (headlines_24h - headlines_30d_daily_avg) / headlines_30d_daily_std
    return {
        "score": min(1.0, max(0.0, z / 4.0)),
        "raw": round(z, 2),
        "fired": z >= 2.0,
    }

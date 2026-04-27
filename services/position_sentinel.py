"""
Position Sentinel — monitors open short option positions between LLM cycles.

Runs every 5 minutes during market hours. For each short put, fetches the
underlying price and compares to strike. Alerts at WARNING (10%), DANGER (5%),
and CRITICAL (at/below strike) thresholds via Discord notifications.

Results stored in-memory for the dashboard endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger


# Alert level thresholds (distance from strike as fraction)
THRESHOLD_WARNING = 0.10
THRESHOLD_DANGER = 0.05

# In-memory store: {option_symbol: {symbol, strike, underlying_price, distance, level, checked_at}}
_sentinel_results: dict[str, dict] = {}


def get_results() -> dict[str, dict]:
    """Return current sentinel results for the dashboard."""
    return dict(_sentinel_results)


def _is_market_hours() -> bool:
    """True if US equities markets are currently open (ET, weekdays 9:30-16:00)."""
    now = datetime.now(timezone(timedelta(hours=-4)))
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 570 <= t <= 960  # 9:30 = 570, 16:00 = 960


async def check_positions(broker, portfolio, notifier) -> dict:
    """
    Check all open short put positions against their strike prices.

    Args:
        broker: AlpacaBroker instance (has get_latest_quote)
        portfolio: Portfolio instance (has .options list)
        notifier: Notifier instance (has send_risk_warning)

    Returns:
        Summary dict with counts per alert level.
    """
    if not _is_market_hours():
        logger.debug("[Sentinel] Outside market hours, skipping.")
        return {"skipped": True}

    short_puts = [
        opt for opt in portfolio.options
        if opt.is_short and opt.contract_type == "put"
    ]

    if not short_puts:
        logger.debug("[Sentinel] No short put positions to monitor.")
        return {"positions": 0}

    # Deduplicate underlying symbols
    symbols = list({opt.symbol for opt in short_puts})
    logger.info(f"[Sentinel] Checking {len(short_puts)} short puts across {len(symbols)} underlyings")

    # Fetch quotes for all underlyings
    quotes: dict[str, float] = {}
    for sym in symbols:
        try:
            quote = await broker.get_latest_quote(sym)
            if quote:
                mid = (quote.get("bid", 0) + quote.get("ask", 0)) / 2
                if mid > 0:
                    quotes[sym] = mid
        except Exception as e:
            logger.warning(f"[Sentinel] Failed to get quote for {sym}: {e}")

    counts = {"WARNING": 0, "DANGER": 0, "CRITICAL": 0, "OK": 0}
    now_iso = datetime.now(timezone.utc).isoformat()

    for opt in short_puts:
        price = quotes.get(opt.symbol)
        if price is None:
            continue

        distance = (price - opt.strike) / opt.strike if opt.strike > 0 else 999

        if distance <= 0:
            level = "CRITICAL"
        elif distance <= THRESHOLD_DANGER:
            level = "DANGER"
        elif distance <= THRESHOLD_WARNING:
            level = "WARNING"
        else:
            level = "OK"

        counts[level] += 1

        _sentinel_results[opt.option_symbol] = {
            "symbol": opt.symbol,
            "option_symbol": opt.option_symbol,
            "strike": opt.strike,
            "expiration": opt.expiration,
            "underlying_price": round(price, 2),
            "distance_pct": round(distance * 100, 1),
            "level": level,
            "checked_at": now_iso,
        }

        if level == "CRITICAL":
            msg = f"{opt.symbol} at ${price:.2f}, BELOW strike ${opt.strike:.2f} -- assignment risk"
            logger.error(f"[Sentinel] CRITICAL: {msg}")
            if notifier:
                try:
                    await notifier.send_risk_warning(msg, {"level": "CRITICAL", "symbol": opt.symbol, "distance": f"{distance*100:.1f}%"})
                except Exception as e:
                    logger.warning(f"[Sentinel] Notify failed: {e}")

        elif level == "DANGER":
            msg = f"{opt.symbol} at ${price:.2f}, strike ${opt.strike:.2f} -- {distance*100:.1f}% buffer"
            logger.warning(f"[Sentinel] DANGER: {msg}")
            if notifier:
                try:
                    await notifier.send_risk_warning(msg, {"level": "DANGER", "symbol": opt.symbol, "distance": f"{distance*100:.1f}%"})
                except Exception as e:
                    logger.warning(f"[Sentinel] Notify failed: {e}")

        elif level == "WARNING":
            logger.info(f"[Sentinel] WARNING: {opt.symbol} at ${price:.2f}, strike ${opt.strike:.2f} -- {distance*100:.1f}% buffer")

    logger.info(f"[Sentinel] Done: {counts}")
    return counts

"""
Order Chaser — near-touch pricing + deterministic poll-and-chase.

Root-cause fix for the "submitted but unfilled → expired at 16:00 ET" failure
mode. The previous flow priced every option order at the bid/ask MID and let
it rest as a DAY limit with no re-pricing; on wide option spreads a mid limit
sits *inside* the spread and frequently never fills before the 4pm expiry.

This service instead:
  1. Prices at the NEAR TOUCH — sell at the bid, buy at the ask — so the order
     is immediately marketable.
  2. Polls the order; if it is still working after chase_poll_seconds, cancels
     it and re-submits one `chase_step` more aggressive, up to
     chase_max_attempts, bounded by chase_max_cross past the original touch.

There is NO LLM in this path — pricing and chasing are fully deterministic, so
it adds no token cost or model latency. The OrderReconciler remains the source
of truth for final fill state; this just maximises the chance of a fill during
the session. Set CHASE_ENABLED=false to revert to a single near-touch submit.
"""
import asyncio
from typing import Optional

from loguru import logger

from config.settings import settings

# Broker status strings (already lower-cased by AlpacaBroker.get_order).
_FILLED = {"filled"}
_DEAD = {"rejected", "canceled", "cancelled", "expired", "done_for_day", "held", "suspended"}


class OrderChaser:
    """Wraps order submission with near-touch pricing and a bounded chase."""

    def __init__(self, broker):
        self.broker = broker

    # ── Pricing ────────────────────────────────────────────────────
    async def _quote(self, option_symbol: str) -> dict:
        getq = getattr(self.broker, "get_option_quote", None)
        if getq is None:
            return {"bid": 0.0, "ask": 0.0, "mid": 0.0}
        try:
            return await getq(option_symbol)
        except Exception as e:
            logger.warning(f"[OrderChaser] quote fetch failed for {option_symbol}: {e}")
            return {"bid": 0.0, "ask": 0.0, "mid": 0.0}

    @staticmethod
    def _near_touch(side: str, quote: dict, reference: Optional[float]) -> Optional[float]:
        """Immediately-marketable price: sell at the bid, buy at the ask.

        Falls back to the caller's reference price (then the mid) when that
        side of the quote is missing, so we never submit an unpriced order.
        """
        bid, ask = quote.get("bid", 0.0), quote.get("ask", 0.0)
        if side == "sell" and bid > 0:
            return bid
        if side == "buy" and ask > 0:
            return ask
        if reference and reference > 0:
            return reference
        mid = quote.get("mid", 0.0)
        return mid if mid > 0 else None

    @staticmethod
    def _chase_price(side, quote, reference, attempt, anchor) -> Optional[float]:
        """Price for chase `attempt` (>=1): near touch stepped toward a fill,
        clamped to chase_max_cross past the original touch (`anchor`)."""
        base = OrderChaser._near_touch(side, quote, reference)
        if base is None:
            return None
        step = settings.chase_step * attempt
        if side == "sell":
            floor = (anchor or base) - settings.chase_max_cross
            price = max(base - step, floor)
        else:  # buy
            ceil = (anchor or base) + settings.chase_max_cross
            price = min(base + step, ceil)
        return max(round(price, 2), 0.01)

    # ── Submit + chase ─────────────────────────────────────────────
    async def submit_and_chase(
        self,
        *,
        option_symbol: str,
        side: str,
        qty: int,
        reference_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> dict:
        """Submit a marketable limit order and chase it to a fill.

        Returns the same dict shape as ``broker.submit_option_order`` (order_id,
        status, limit_price, …) for the order that is live when this returns,
        augmented with ``filled_avg_price`` / ``chase_attempts`` when known.
        """
        side = side.lower()

        quote = await self._quote(option_symbol)
        price = self._near_touch(side, quote, reference_price)
        if price is None or price <= 0:
            raise ValueError(
                f"No marketable price for {option_symbol} "
                f"(quote={quote}, ref={reference_price})"
            )
        price = max(round(price, 2), 0.01)
        anchor = (quote.get("bid") if side == "sell" else quote.get("ask")) or price

        order = await self.broker.submit_option_order(
            option_symbol=option_symbol,
            side=side,
            qty=qty,
            order_type="limit",
            limit_price=price,
            time_in_force=time_in_force,
        )
        order_id = order.get("order_id")
        status = str(order.get("status", "")).lower()
        order["limit_price"] = price

        if status in _DEAD:
            return order

        # Skip the chase loop when disabled, or when the broker can't poll /
        # cancel (e.g. a lightweight test double) — avoids blocking on sleeps.
        chase_ok = (
            settings.chase_enabled
            and order_id
            and settings.chase_max_attempts > 0
            and callable(getattr(self.broker, "get_order", None))
            and callable(getattr(self.broker, "cancel_order", None))
        )
        if not chase_ok:
            return order

        for attempt in range(1, settings.chase_max_attempts + 1):
            await asyncio.sleep(settings.chase_poll_seconds)

            try:
                cur = await self.broker.get_order(order_id)
            except Exception as e:
                logger.warning(f"[OrderChaser] status poll failed for {order_id}: {e}")
                return order  # leave the working order for the reconciler

            st = str(cur.get("status", "")).lower()
            filled_qty = int(cur.get("filled_qty", 0) or 0)

            if st in _FILLED:
                logger.info(
                    f"[OrderChaser] {side} {option_symbol} filled @ "
                    f"${cur.get('filled_avg_price') or price} (attempt {attempt - 1})"
                )
                return {
                    **order,
                    "order_id": order_id,
                    "status": "filled",
                    "limit_price": price,
                    "filled_avg_price": cur.get("filled_avg_price"),
                    "chase_attempts": attempt - 1,
                }
            if st in _DEAD:
                return {**order, "order_id": order_id, "status": st,
                        "chase_attempts": attempt - 1}
            if filled_qty > 0:
                # Partial fill — never cancel-replace a partial (risks
                # over-filling); hand the remainder to the reconciler.
                logger.info(
                    f"[OrderChaser] {option_symbol} partial fill {filled_qty}/{qty}; "
                    f"holding remainder."
                )
                return {**order, "order_id": order_id, "status": st,
                        "chase_attempts": attempt - 1}

            # Still working and unfilled — cancel and re-price more aggressively.
            quote = await self._quote(option_symbol)
            new_price = self._chase_price(side, quote, reference_price, attempt, anchor)
            if new_price is None:
                return order
            if not await self.broker.cancel_order(order_id):
                logger.warning(
                    f"[OrderChaser] could not cancel {order_id}; leaving it working."
                )
                return order

            try:
                order = await self.broker.submit_option_order(
                    option_symbol=option_symbol,
                    side=side,
                    qty=qty,
                    order_type="limit",
                    limit_price=new_price,
                    time_in_force=time_in_force,
                )
            except Exception as e:
                logger.error(f"[OrderChaser] re-submit failed for {option_symbol}: {e}")
                raise
            order_id = order.get("order_id")
            price = new_price
            order["limit_price"] = price
            logger.info(
                f"[OrderChaser] chased {side} {option_symbol} → ${price:.2f} "
                f"(attempt {attempt}/{settings.chase_max_attempts})"
            )
            if str(order.get("status", "")).lower() in _DEAD:
                return order

        # Chase exhausted — the most-aggressive order is resting; the
        # reconciler trues it up (fill or expiry) on the next cycle.
        return {**order, "order_id": order_id, "status": "submitted",
                "limit_price": price, "chase_exhausted": True}

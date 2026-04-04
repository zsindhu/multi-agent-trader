"""
Order Reconciler — Checks the actual status of submitted orders and updates the DB.

Runs at the START of every Lead Agent cycle (before any LLM decisions) so the
LLM always sees the true, filled state of the portfolio rather than stale
"submitted" records.

Also detects positions that disappeared between cycles (expired, assigned) and
logs them to the trade journal.
"""
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, update

from core.database import AsyncSessionLocal
from models.trade import Trade
from models.journal_entry import JournalEntry


class OrderReconciler:
    """
    Reconciles submitted orders against Alpaca's actual order state.

    Responsibilities:
    1. Query all trades with status="submitted"
    2. Fetch the real order status from Alpaca
    3. Update trade records (status, fill_price, filled_at, notes)
    4. Detect positions that expired or were assigned between cycles
    5. Log expiry/assignment events to the trade journal
    """

    def __init__(self, broker, trade_journal=None, portfolio=None):
        self.broker = broker
        self.trade_journal = trade_journal
        self.portfolio = portfolio
        # Stores option symbols from the previous cycle for disappearance detection
        self._previous_option_symbols: set[str] = set()

    async def reconcile(self) -> dict:
        """
        Reconcile all submitted orders.  Returns summary counts.

        Run this at the START of every cycle, before portfolio sync and before
        any LLM calls.
        """
        summary = {"reconciled": 0, "filled": 0, "rejected": 0, "pending": 0, "errors": 0}

        async with AsyncSessionLocal() as session:
            stmt = select(Trade).where(Trade.status == "submitted")
            result = await session.execute(stmt)
            submitted_trades = result.scalars().all()

        if not submitted_trades:
            logger.debug("[Reconciler] No submitted orders to reconcile.")
            return summary

        logger.info(f"[Reconciler] Reconciling {len(submitted_trades)} submitted orders...")

        for trade in submitted_trades:
            if not trade.order_id:
                logger.debug(f"[Reconciler] Trade {trade.id} has no order_id — skipping")
                continue

            try:
                order = await self.broker.get_order(trade.order_id)
                status = order.get("status", "")
                summary["reconciled"] += 1

                if status == "filled":
                    fill_price = order.get("filled_avg_price")
                    filled_at_str = order.get("filled_at")
                    filled_at = None
                    if filled_at_str:
                        try:
                            filled_at = datetime.fromisoformat(filled_at_str.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass

                    async with AsyncSessionLocal() as session:
                        stmt = (
                            update(Trade)
                            .where(Trade.id == trade.id)
                            .values(
                                status="filled",
                                price=fill_price or trade.price,
                                notes=(trade.notes or "") + f" | Filled @ ${fill_price} at {filled_at_str}",
                            )
                        )
                        await session.execute(stmt)
                        await session.commit()

                    summary["filled"] += 1
                    logger.info(
                        f"[Reconciler] Order filled: {trade.option_symbol} "
                        f"@ ${fill_price} ({filled_at_str})"
                    )

                elif status in ("rejected", "cancelled", "canceled", "expired"):
                    reject_reason = order.get("reject_reason") or status
                    async with AsyncSessionLocal() as session:
                        stmt = (
                            update(Trade)
                            .where(Trade.id == trade.id)
                            .values(
                                status=status,
                                notes=(trade.notes or "") + f" | {status.upper()}: {reject_reason}",
                            )
                        )
                        await session.execute(stmt)
                        await session.commit()

                    summary["rejected"] += 1
                    logger.warning(
                        f"[Reconciler] Order {status}: {trade.option_symbol} "
                        f"— reason: {reject_reason}"
                    )

                else:
                    # Still pending/open/partially filled
                    summary["pending"] += 1

            except Exception as e:
                logger.error(
                    f"[Reconciler] Failed to reconcile trade {trade.id} "
                    f"(order {trade.order_id}): {e}"
                )
                summary["errors"] += 1

        logger.info(
            f"[Reconciler] Done — filled:{summary['filled']}, "
            f"rejected:{summary['rejected']}, pending:{summary['pending']}, "
            f"errors:{summary['errors']}"
        )
        return summary

    async def detect_position_changes(
        self,
        current_option_symbols: set[str],
    ) -> list[dict]:
        """
        Compare current portfolio positions to previous cycle's positions.
        Positions that disappeared may have expired or been assigned.

        Args:
            current_option_symbols: Set of option_symbols currently in the portfolio.

        Returns:
            List of change events with action, option_symbol, and inferred_reason.
        """
        events = []
        if not self._previous_option_symbols:
            # First cycle — no comparison possible; store and return
            self._previous_option_symbols = current_option_symbols.copy()
            return events

        disappeared = self._previous_option_symbols - current_option_symbols

        for opt_sym in disappeared:
            # Try to figure out why it disappeared
            reason = await self._infer_disappearance_reason(opt_sym)
            logger.info(f"[Reconciler] Position disappeared: {opt_sym} — {reason}")
            events.append({
                "action": reason,
                "option_symbol": opt_sym,
            })

            # Log to trade journal if available
            if self.trade_journal:
                try:
                    await self.trade_journal.log_exit(
                        option_symbol=opt_sym,
                        exit_reason=reason,
                    )
                except Exception as e:
                    logger.debug(f"[Reconciler] Journal exit log failed for {opt_sym}: {e}")

        self._previous_option_symbols = current_option_symbols.copy()
        return events

    async def _infer_disappearance_reason(self, option_symbol: str) -> str:
        """
        Try to determine why a position disappeared.

        Heuristics:
        - If the option symbol's expiration date is in the past → expired
        - We don't have direct Alpaca history here, so use date-based inference
        """
        try:
            # Parse expiration from OCC symbol: e.g. "GDX240419P00027000"
            # Format: SYMBOL + YYMMDD + C/P + STRIKE8DIGITS
            import re
            m = re.search(r"(\d{6})[CP]", option_symbol)
            if m:
                date_str = m.group(1)  # YYMMDD
                exp_date = datetime.strptime(date_str, "%y%m%d")
                if exp_date.date() <= datetime.utcnow().date():
                    return "expired_worthless"
        except Exception:
            pass
        return "position_closed"

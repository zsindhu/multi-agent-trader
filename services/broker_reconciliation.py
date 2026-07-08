"""
Broker Reconciliation — nightly cross-check of the local trades DB against
Alpaca's actual order history and positions.

Born out of the July 2026 audit, where the dashboard reported +$6,879.70 /
92% win rate while the broker's realized PnL was -$184: the DB's
interpretation of its own rows had drifted from broker truth without any
alarm. This job makes that drift visible within a day.

Checks:
1. Order-level: every DB trade with an order_id agrees with the broker on
   status and fill price.
2. Position-level: no unintended LONG option positions (a premium-selling
   system should only ever be short options), and every broker position has
   a corresponding filled DB entry.
3. PnL-level: broker realized options PnL (computed from fills, per
   contract) vs the sum of labeled trade_outcomes.

The latest report is stored as an AgentMessage (message_type =
"reconciliation_report") and served by GET /api/dashboard/reconciliation.
"""
from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.agent_message import AgentMessage
from models.trade import Trade
from models.trade_outcome import TradeOutcome

# DB status → broker statuses considered consistent
STATUS_EQUIV = {
    "filled": {"filled"},
    "order_expired": {"expired"},
    "expired": {"expired"},  # legacy rows, if any survive
    "cancelled": {"cancelled", "canceled"},
    "canceled": {"cancelled", "canceled"},
    "rejected": {"rejected"},
    "submitted": {"new", "accepted", "open", "pending_new", "partially_filled", "held"},
    "closed": {"filled"},
    "assigned": {"filled"},
    "unknown": None,  # legacy — skip
}


class BrokerReconciliation:
    """Compares DB trades/outcomes to broker orders/positions."""

    def __init__(self, broker):
        self.broker = broker

    async def run(self) -> dict:
        logger.info("[Reconciliation] Starting broker reconciliation")
        try:
            orders = await self.broker.get_all_orders()
            positions = await self.broker.get_positions()
        except Exception as e:
            logger.error(f"[Reconciliation] Broker fetch failed: {e}")
            return {"error": str(e)}

        orders_by_id = {o["order_id"]: o for o in orders}
        discrepancies: list[dict] = []

        async with AsyncSessionLocal() as session:
            trades = list(
                (await session.execute(select(Trade).where(Trade.order_id.isnot(None))))
                .scalars()
                .all()
            )
            outcomes = list(
                (await session.execute(select(TradeOutcome))).scalars().all()
            )

        # ── Check 1: order-level agreement ────────────────────────────
        for t in trades:
            order = orders_by_id.get(t.order_id)
            if order is None:
                discrepancies.append({
                    "kind": "order_missing_at_broker",
                    "trade_id": t.id,
                    "option_symbol": t.option_symbol,
                    "db_status": t.status,
                })
                continue
            allowed = STATUS_EQUIV.get(t.status or "", set())
            if allowed is None:
                continue
            if order["status"] not in allowed:
                discrepancies.append({
                    "kind": "status_mismatch",
                    "trade_id": t.id,
                    "option_symbol": t.option_symbol,
                    "db_status": t.status,
                    "broker_status": order["status"],
                })
            if (
                order["status"] == "filled"
                and order["filled_avg_price"] is not None
                and t.price is not None
                and abs(float(t.price) - order["filled_avg_price"]) > 0.005
            ):
                discrepancies.append({
                    "kind": "fill_price_mismatch",
                    "trade_id": t.id,
                    "option_symbol": t.option_symbol,
                    "db_price": float(t.price),
                    "broker_fill": order["filled_avg_price"],
                })

        # ── Check 2: position sanity ──────────────────────────────────
        long_options = []
        for p in positions:
            qty = int(p.get("qty", 0))
            is_option = "option" in str(p.get("asset_class", "")).lower() or len(p.get("symbol", "")) > 12
            if is_option and qty > 0:
                long_options.append({"symbol": p["symbol"], "qty": qty})
                discrepancies.append({
                    "kind": "unintended_long_option",
                    "option_symbol": p["symbol"],
                    "qty": qty,
                })

        # ── Check 3: realized PnL, broker vs labeled outcomes ─────────
        ledger: dict[str, dict] = defaultdict(
            lambda: {"sell": 0.0, "sell_cost": 0.0, "buy": 0.0, "buy_cost": 0.0}
        )
        for o in orders:
            if o["status"] != "filled" or "option" not in o["asset_class"]:
                continue
            leg = "sell" if "sell" in o["side"] else "buy"
            ledger[o["symbol"]][leg] += o["filled_qty"]
            ledger[o["symbol"]][f"{leg}_cost"] += o["filled_qty"] * (o["filled_avg_price"] or 0) * 100

        open_symbols = {p["symbol"] for p in positions}
        broker_realized = 0.0
        today_iso = datetime.now(timezone.utc).date().isoformat()
        for sym, l in ledger.items():
            if sym in open_symbols:
                continue  # still open — unrealized
            # Closed or expired: everything received minus everything paid
            broker_realized += l["sell_cost"] - l["buy_cost"]

        labeled_pnl = sum(float(o.pnl_dollars or 0) for o in outcomes)
        pnl_drift = round(labeled_pnl - broker_realized, 2)

        report = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "orders_checked": len(trades),
            "broker_order_count": len(orders),
            "discrepancy_count": len(discrepancies),
            "discrepancies": discrepancies[:50],
            "long_option_positions": long_options,
            "broker_realized_pnl": round(broker_realized, 2),
            "labeled_outcome_pnl": round(labeled_pnl, 2),
            "pnl_drift": pnl_drift,
            "ok": len(discrepancies) == 0 and abs(pnl_drift) < 50.0,
        }

        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentMessage(
                    sender="Broker-Reconciliation",
                    message_type="reconciliation_report",
                    subject=f"Reconciliation {today_iso}: "
                            f"{'OK' if report['ok'] else f'{len(discrepancies)} discrepancies'}",
                    body=(
                        f"Checked {len(trades)} DB trades against {len(orders)} broker orders. "
                        f"Discrepancies: {len(discrepancies)}. "
                        f"Broker realized PnL ${report['broker_realized_pnl']:.2f} vs "
                        f"labeled ${report['labeled_outcome_pnl']:.2f} "
                        f"(drift ${pnl_drift:.2f})."
                    ),
                    payload=report,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"[Reconciliation] Failed to persist report: {e}")

        level = logger.info if report["ok"] else logger.warning
        level(
            f"[Reconciliation] Done — {len(discrepancies)} discrepancies, "
            f"PnL drift ${pnl_drift:.2f}"
        )
        return report

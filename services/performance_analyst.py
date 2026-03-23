"""
Performance Analyst Service — Analyzes trade history to surface actionable insights.

Reads from Trade, JournalEntry, and RegimeSnapshot tables. Computes win rates,
optimal deltas, regime correlations, and open position health. Requires minimum
5 completed trades to produce meaningful results.

Runs once daily at 4:30 PM ET after market close.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc

from core.database import AsyncSessionLocal
from models.trade import Trade
from models.journal_entry import JournalEntry
from models.performance_insight import PerformanceInsight


MIN_TRADES_FOR_INSIGHTS = 5


class PerformanceAnalystService:
    """Analyzes trading history and stores structured insights in the DB."""

    # ── Public API ──────────────────────────────────────────────────

    async def compute_all(self):
        """Run all analyses and persist results. Called once daily."""
        logger.info("[PerfAnalyst] Computing performance insights...")
        try:
            await self._compute_overall("7d", 7)
            await self._compute_overall("30d", 30)
            await self._compute_overall("all_time", 3650)
            await self._compute_strategy_breakdown()
            await self._compute_delta_analysis()
            await self._compute_regime_correlation()
            await self._compute_symbol_scorecard()
            await self._compute_position_health()
            logger.info("[PerfAnalyst] All insights computed and stored.")
        except Exception as e:
            logger.error(f"[PerfAnalyst] Compute failed: {e}")

    async def get_summary(self, days: int = 30) -> dict:
        period = "30d" if days <= 30 else ("7d" if days <= 7 else "all_time")
        return await self._get_latest_insight("overall", period)

    async def get_strategy_breakdown(self) -> dict:
        return await self._get_latest_insight("strategy", "all_time")

    async def get_delta_analysis(self) -> dict:
        return await self._get_latest_insight("delta", "all_time")

    async def get_regime_correlation(self) -> dict:
        return await self._get_latest_insight("regime", "all_time")

    async def get_symbol_scorecard(self) -> dict:
        return await self._get_latest_insight("symbol", "all_time")

    async def get_open_position_health(self) -> dict:
        return await self._get_latest_insight("position_health", "all_time")

    async def get_recommendations(self) -> list[str]:
        """Synthesize insights into actionable text recommendations (rule-based)."""
        recs = []
        try:
            strategy = await self.get_strategy_breakdown()
            if strategy.get("data"):
                data = strategy["data"]
                strategies = data.get("strategies", [])
                if strategies:
                    best = max(strategies, key=lambda s: s.get("win_rate", 0))
                    worst = min(strategies, key=lambda s: s.get("win_rate", 0))
                    if best["win_rate"] > 0:
                        recs.append(
                            f"Best strategy: {best['agent_name']} with "
                            f"{best['win_rate']:.0f}% win rate."
                        )
                    if worst["win_rate"] < 40 and worst["total_trades"] >= MIN_TRADES_FOR_INSIGHTS:
                        recs.append(
                            f"Consider pausing {worst['agent_name']} — "
                            f"win rate {worst['win_rate']:.0f}% below 40% threshold."
                        )

            delta = await self.get_delta_analysis()
            if delta.get("data"):
                buckets = delta["data"].get("buckets", [])
                if buckets:
                    best_bucket = max(
                        (b for b in buckets if b["count"] >= 3),
                        key=lambda b: b.get("win_rate", 0),
                        default=None,
                    )
                    if best_bucket:
                        recs.append(
                            f"Optimal delta range: {best_bucket['range']} "
                            f"({best_bucket['win_rate']:.0f}% win rate, "
                            f"{best_bucket['count']} trades)."
                        )

            regime = await self.get_regime_correlation()
            if regime.get("data"):
                by_regime = regime["data"].get("by_regime", {})
                if "risk_off" in by_regime and by_regime["risk_off"].get("trades", 0) >= 3:
                    risk_off_wr = by_regime["risk_off"]["win_rate"]
                    if risk_off_wr < 40:
                        recs.append(
                            f"Risk-off regime shows only {risk_off_wr:.0f}% win rate. "
                            "Consider reducing position size during risk-off periods."
                        )
        except Exception as e:
            logger.debug(f"[PerfAnalyst] Recommendations failed: {e}")

        if not recs:
            recs.append("Not enough closed trade data for recommendations yet.")
        return recs

    # ── Internal compute methods ─────────────────────────────────────

    async def _compute_overall(self, period: str, days: int):
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Trade).where(Trade.created_at >= cutoff)
            )
            all_trades = list(result.scalars().all())
            closed = [t for t in all_trades if t.closed_at is not None]

        data = {
            "period": period,
            "total_trades": len(all_trades),
            "closed_trades": len(closed),
            "open_trades": len(all_trades) - len(closed),
            "wins": sum(1 for t in closed if (t.pnl or 0) > 0),
            "losses": sum(1 for t in closed if (t.pnl or 0) < 0),
            "win_rate": 0.0,
            "total_pnl": round(sum(t.pnl or 0 for t in closed), 2),
            "avg_pnl": 0.0,
            "total_premium": round(sum(t.premium or 0 for t in all_trades), 2),
            "avg_hold_days": 0.0,
        }

        if closed:
            data["win_rate"] = round((data["wins"] / len(closed)) * 100, 1)
            data["avg_pnl"] = round(data["total_pnl"] / len(closed), 2)

        days_held = [
            (t.closed_at - t.created_at).days
            for t in closed if t.created_at and t.closed_at
        ]
        if days_held:
            data["avg_hold_days"] = round(sum(days_held) / len(days_held), 1)

        await self._store_insight("overall", period, data)

    async def _compute_strategy_breakdown(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade))
            all_trades = list(result.scalars().all())

        agent_groups: dict[str, list] = {}
        for t in all_trades:
            agent_groups.setdefault(t.agent_name, []).append(t)

        strategies = []
        for agent_name, trades in agent_groups.items():
            closed = [t for t in trades if t.closed_at is not None]
            wins = sum(1 for t in closed if (t.pnl or 0) > 0)
            strategies.append({
                "agent_name": agent_name,
                "total_trades": len(trades),
                "closed_trades": len(closed),
                "wins": wins,
                "win_rate": round((wins / len(closed)) * 100, 1) if closed else 0.0,
                "total_pnl": round(sum(t.pnl or 0 for t in closed), 2),
                "total_premium": round(sum(t.premium or 0 for t in trades), 2),
                "avg_pnl": round(sum(t.pnl or 0 for t in closed) / len(closed), 2) if closed else 0.0,
            })

        await self._store_insight("strategy", "all_time", {"strategies": strategies})

    async def _compute_delta_analysis(self):
        """Group closed trades by delta bucket and compute win rate per bucket."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(JournalEntry).where(JournalEntry.exit_at.isnot(None))
            )
            closed = list(result.scalars().all())

        # Delta buckets: (label, min_abs_delta, max_abs_delta)
        buckets_def = [
            ("0.10–0.15", 0.10, 0.15),
            ("0.15–0.20", 0.15, 0.20),
            ("0.20–0.25", 0.20, 0.25),
            ("0.25–0.30", 0.25, 0.30),
            ("0.30+", 0.30, 1.0),
        ]

        buckets = []
        for label, lo, hi in buckets_def:
            trades_in_bucket = [
                t for t in closed
                if t.delta_at_entry is not None
                and lo <= abs(t.delta_at_entry) < hi
            ]
            wins = sum(1 for t in trades_in_bucket if (t.realized_pnl or 0) > 0)
            buckets.append({
                "range": label,
                "count": len(trades_in_bucket),
                "wins": wins,
                "win_rate": round((wins / len(trades_in_bucket)) * 100, 1) if trades_in_bucket else 0.0,
                "avg_pnl": round(
                    sum(t.realized_pnl or 0 for t in trades_in_bucket) / len(trades_in_bucket), 2
                ) if trades_in_bucket else 0.0,
            })

        await self._store_insight("delta", "all_time", {"buckets": buckets})

    async def _compute_regime_correlation(self):
        """Cross-reference trade entries with regime snapshots."""
        try:
            from models.regime_snapshot import RegimeSnapshot

            async with AsyncSessionLocal() as session:
                trades_result = await session.execute(
                    select(JournalEntry).where(JournalEntry.exit_at.isnot(None))
                )
                closed_trades = list(trades_result.scalars().all())

                regimes_result = await session.execute(
                    select(RegimeSnapshot).order_by(RegimeSnapshot.computed_at)
                )
                regime_snapshots = list(regimes_result.scalars().all())

            if not closed_trades or not regime_snapshots:
                await self._store_insight("regime", "all_time", {"by_regime": {}, "note": "No data"})
                return

            def _find_regime_at(ts: datetime) -> str:
                """Find the regime snapshot closest to (and before) trade entry."""
                best = None
                for snap in regime_snapshots:
                    if snap.computed_at <= ts:
                        best = snap
                return best.regime if best else "unknown"

            by_regime: dict[str, list] = {}
            for trade in closed_trades:
                regime = _find_regime_at(trade.entry_at) if trade.entry_at else "unknown"
                by_regime.setdefault(regime, []).append(trade)

            summary = {}
            for regime, trades in by_regime.items():
                wins = sum(1 for t in trades if (t.realized_pnl or 0) > 0)
                summary[regime] = {
                    "trades": len(trades),
                    "wins": wins,
                    "win_rate": round((wins / len(trades)) * 100, 1) if trades else 0.0,
                    "total_pnl": round(sum(t.realized_pnl or 0 for t in trades), 2),
                }

            await self._store_insight("regime", "all_time", {"by_regime": summary})
        except Exception as e:
            logger.debug(f"[PerfAnalyst] Regime correlation failed: {e}")
            await self._store_insight("regime", "all_time", {"by_regime": {}, "error": str(e)})

    async def _compute_symbol_scorecard(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade))
            all_trades = list(result.scalars().all())

        sym_groups: dict[str, list] = {}
        for t in all_trades:
            sym_groups.setdefault(t.symbol, []).append(t)

        scorecard = []
        for symbol, trades in sym_groups.items():
            closed = [t for t in trades if t.closed_at is not None]
            wins = sum(1 for t in closed if (t.pnl or 0) > 0)
            scorecard.append({
                "symbol": symbol,
                "total_trades": len(trades),
                "closed_trades": len(closed),
                "wins": wins,
                "win_rate": round((wins / len(closed)) * 100, 1) if closed else 0.0,
                "total_pnl": round(sum(t.pnl or 0 for t in closed), 2),
                "total_premium": round(sum(t.premium or 0 for t in trades), 2),
                "avg_premium": round(sum(t.premium or 0 for t in trades) / len(trades), 2) if trades else 0.0,
            })

        scorecard.sort(key=lambda x: x["total_pnl"], reverse=True)
        await self._store_insight("symbol", "all_time", {"symbols": scorecard})

    async def _compute_position_health(self):
        """Flag open positions that need attention."""
        try:
            from core.portfolio import Portfolio
            from services.alpaca_broker import AlpacaBroker

            broker = AlpacaBroker()
            portfolio = Portfolio()
            await portfolio.sync_from_broker(broker)

            from datetime import date
            today = date.today()
            health = []

            for opt in portfolio.options:
                if not opt.is_short:
                    continue
                try:
                    exp_date = date.fromisoformat(opt.expiration) if opt.expiration else None
                except ValueError:
                    exp_date = None

                dte = (exp_date - today).days if exp_date else None
                pnl_pct = opt.pnl_pct if opt.pnl_pct is not None else 0.0

                flags = []
                if pnl_pct < -0.5:
                    flags.append("deeply_underwater")
                if dte is not None and dte < 5 and pnl_pct < 0:
                    flags.append("itm_near_expiry")

                health.append({
                    "symbol": opt.symbol,
                    "option_symbol": opt.option_symbol,
                    "strike": opt.strike,
                    "expiration": opt.expiration,
                    "dte": dte,
                    "pnl_pct": round(pnl_pct * 100, 1),
                    "premium_collected": opt.premium_collected,
                    "flags": flags,
                })

            await self._store_insight("position_health", "all_time", {"positions": health})
        except Exception as e:
            logger.debug(f"[PerfAnalyst] Position health failed: {e}")
            await self._store_insight("position_health", "all_time", {"positions": [], "error": str(e)})

    # ── DB helpers ───────────────────────────────────────────────────

    async def _store_insight(self, insight_type: str, period: str, data: dict):
        async with AsyncSessionLocal() as session:
            row = PerformanceInsight(
                insight_type=insight_type,
                period=period,
                data=json.dumps(data),
            )
            session.add(row)
            await session.commit()

    async def _get_latest_insight(self, insight_type: str, period: str) -> dict:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PerformanceInsight)
                .where(
                    PerformanceInsight.insight_type == insight_type,
                    PerformanceInsight.period == period,
                )
                .order_by(desc(PerformanceInsight.computed_at))
                .limit(1)
            )
            row = result.scalar_one_or_none()
        if not row:
            return {"insight_type": insight_type, "period": period, "data": None}
        try:
            data = json.loads(row.data)
        except Exception:
            data = {}
        return {
            "insight_type": row.insight_type,
            "period": row.period,
            "data": data,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }

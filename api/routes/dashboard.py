"""
Dashboard API — JSON endpoints for the React research dashboard.

Serves the data needed by the Command Center (Screen 1) and
History & Learning (Screen 2) views. No HTML — pure JSON.
"""
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select, desc, func as sa_func, cast, Date, text, case

from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.trade import Trade
from models.trade_outcome import TradeOutcome
from models.cycle_snapshot import CycleSnapshot
from models.agent_message import AgentMessage
from models.agent_action import AgentAction
from models.equity_snapshot import EquitySnapshot
from models.llm_usage_log import LlmUsageLog

router = APIRouter()


@router.get("/status")
async def dashboard_status():
    """System status — sweep times, funnel counts, cost, error count."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        # Tier 1 / Tier 2 counts today
        r = await session.execute(
            select(
                NameObservation.tier,
                NameObservation.was_considered,
                sa_func.count(NameObservation.id),
            )
            .where(NameObservation.timestamp >= today_start)
            .group_by(NameObservation.tier, NameObservation.was_considered)
        )
        tier_counts = r.all()

        t1_total = sum(c for t, _, c in tier_counts if t == 1)
        t2_pass = sum(c for t, w, c in tier_counts if t == 2 and w)
        t2_reject = sum(c for t, w, c in tier_counts if t == 2 and not w)

        # Last Tier 1 sweep timestamp
        r = await session.execute(
            select(sa_func.max(NameObservation.timestamp))
            .where(NameObservation.tier == 1, NameObservation.timestamp >= today_start)
        )
        last_t1 = r.scalar()

        # Last Tier 2 sweep timestamp
        r = await session.execute(
            select(sa_func.max(NameObservation.timestamp))
            .where(NameObservation.tier == 2, NameObservation.timestamp >= today_start)
        )
        last_t2 = r.scalar()

        # Last Lead Agent cycle
        r = await session.execute(
            select(CycleSnapshot.timestamp, CycleSnapshot.llm_cost_usd)
            .order_by(desc(CycleSnapshot.timestamp)).limit(1)
        )
        last_cycle = r.one_or_none()

        # Today's total LLM cost (from persistent usage log, survives restarts)
        r = await session.execute(
            select(sa_func.sum(LlmUsageLog.cost_usd))
            .where(LlmUsageLog.timestamp >= today_start)
        )
        today_cost_db = r.scalar() or 0.0
        # Fall back to cycle_snapshots if no usage log rows yet
        if today_cost_db == 0:
            r = await session.execute(
                select(sa_func.sum(CycleSnapshot.llm_cost_usd))
                .where(CycleSnapshot.timestamp >= today_start)
            )
            today_cost_db = r.scalar() or 0.0
        today_cost = today_cost_db

        # Today's errors (agent_actions with outcome containing 'error' or 'failed')
        r = await session.execute(
            select(sa_func.count(AgentAction.id))
            .where(
                AgentAction.timestamp >= today_start,
                AgentAction.outcome.in_(["error", "failed"]),
            )
        )
        error_count = r.scalar() or 0

    return {
        "funnel": {
            "tier1_universe": t1_total,
            "tier2_promoted": t2_pass,
            "tier2_rejected": t2_reject,
        },
        "last_tier1_sweep": last_t1.isoformat() if last_t1 else None,
        "last_tier2_sweep": last_t2.isoformat() if last_t2 else None,
        "last_cycle": {
            "timestamp": last_cycle[0].isoformat() if last_cycle else None,
            "cost": last_cycle[1] if last_cycle else None,
        },
        "today_llm_cost": round(today_cost, 4),
        "today_errors": error_count,
    }


@router.get("/promotions")
async def dashboard_promotions(date_str: Optional[str] = Query(None, alias="date")):
    """Today's Tier 2 promotions with full signal breakdown."""
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            target = datetime.now(timezone.utc)
    else:
        target = datetime.now(timezone.utc)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(NameObservation)
            .where(
                NameObservation.tier == 2,
                NameObservation.was_considered == True,
                NameObservation.timestamp >= day_start,
                NameObservation.timestamp < day_end,
            )
            .order_by(NameObservation.composite_score.desc())
            .limit(50)
        )
        rows = list(r.scalars().all())

    promotions = []
    for obs in rows:
        analysis = obs.analysis or {}
        signals = analysis.get("signals", {})
        firing = [name for name, sig in signals.items() if sig.get("fired")]

        signal_details = {}
        for sig_name, sig_data in signals.items():
            signal_details[sig_name] = {
                "fired": sig_data.get("fired", False),
                "raw": sig_data.get("raw"),
                "z_score": sig_data.get("z_score"),
                "threshold": sig_data.get("threshold"),
            }

        promotions.append({
            "symbol": obs.symbol,
            "composite_score": obs.composite_score,
            "price": obs.price,
            "asset_type": obs.asset_type,
            "signals_fired": len(firing),
            "firing_rules": firing,
            "amplification": analysis.get("amplification_applied", 1.0),
            "reasoning": analysis.get("tier2b_reasoning"),
            "signals": signal_details,
            "sleeve_id": obs.sleeve_id,
            "timestamp": obs.timestamp.isoformat() if obs.timestamp else None,
        })

    return {"promotions": promotions, "count": len(promotions)}


@router.get("/signals")
async def dashboard_signals(days: int = Query(14, ge=1, le=90)):
    """Signal firing rates from recent Tier 2 observations."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(NameObservation.analysis)
            .where(
                NameObservation.tier == 2,
                NameObservation.was_considered == True,
                NameObservation.timestamp >= cutoff,
            )
        )
        analyses = [row[0] for row in r.all() if row[0]]

    stats = {}
    for analysis in analyses:
        signals = analysis.get("signals", {})
        for name, sig in signals.items():
            if name not in stats:
                stats[name] = {"total": 0, "fired": 0}
            stats[name]["total"] += 1
            if sig.get("fired"):
                stats[name]["fired"] += 1

    result = []
    for name, s in sorted(stats.items(), key=lambda x: x[1]["fired"] / max(x[1]["total"], 1), reverse=True):
        rate = s["fired"] / max(s["total"], 1) * 100
        result.append({
            "signal": name,
            "total": s["total"],
            "fired": s["fired"],
            "rate": round(rate, 1),
        })

    return {"signals": result, "observations": len(analyses), "days": days}


@router.get("/reflection")
async def dashboard_reflection():
    """Latest Research Analyst daily reflection."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentMessage.body, AgentMessage.timestamp, AgentMessage.subject)
            .where(
                AgentMessage.sender == "Research-Analyst",
                AgentMessage.message_type == "daily_reflection",
            )
            .order_by(desc(AgentMessage.timestamp))
            .limit(1)
        )
        ref = r.one_or_none()

    if not ref:
        return {"body": None, "timestamp": None, "is_today": False}

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    is_today = ref[1] >= today_start if ref[1] else False

    return {
        "body": ref[0],
        "timestamp": ref[1].isoformat() if ref[1] else None,
        "subject": ref[2],
        "is_today": is_today,
    }


@router.get("/playbook")
async def dashboard_playbook(limit: int = Query(30, ge=1, le=100)):
    """Active playbook entries."""
    from models.playbook_entry import PlaybookEntry

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(PlaybookEntry)
            .where(PlaybookEntry.active == True)
            .order_by(desc(PlaybookEntry.created_at))
            .limit(limit)
        )
        entries = list(r.scalars().all())

    return {
        "entries": [
            {
                "id": e.id,
                "category": e.category,
                "content": e.content,
                "confidence": e.confidence,
                "validated": e.validated,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.get("/cycles")
async def dashboard_cycles(limit: int = Query(10, ge=1, le=50)):
    """Recent Lead Agent cycles with summaries."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(CycleSnapshot)
            .order_by(desc(CycleSnapshot.timestamp))
            .limit(limit)
        )
        cycles = list(r.scalars().all())

    return {
        "cycles": [
            {
                "id": c.id,
                "timestamp": c.timestamp.isoformat() if c.timestamp else None,
                "regime": c.regime,
                "vix_level": c.vix_level,
                "equity": c.equity,
                "cash": c.cash,
                "actions_decided": c.actions_decided,
                "actions_executed": c.actions_executed,
                "summary": c.summary,
                "reasoning": c.reasoning,
                "llm_cost_usd": c.llm_cost_usd,
                "llm_model": c.llm_model,
                "llm_tokens_in": c.llm_tokens_in,
                "llm_tokens_out": c.llm_tokens_out,
            }
            for c in cycles
        ],
    }


@router.get("/daily-stats")
async def dashboard_daily_stats(days: int = Query(30, ge=1, le=365)):
    """Daily promotion counts + PnL for charts."""
    cutoff_tz = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_naive = datetime.utcnow() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        # Daily promotion counts (NameObservation.timestamp is tz-aware)
        r = await session.execute(
            select(
                cast(NameObservation.timestamp, Date).label("day"),
                sa_func.count(NameObservation.id),
            )
            .where(
                NameObservation.tier == 2,
                NameObservation.was_considered == True,
                NameObservation.timestamp >= cutoff_tz,
            )
            .group_by("day")
            .order_by("day")
        )
        promo_by_day = {str(row[0]): row[1] for row in r.all()}

        # Daily PnL from trade outcomes (TradeOutcome.labeled_at is tz-aware)
        r = await session.execute(
            select(
                cast(TradeOutcome.labeled_at, Date).label("day"),
                sa_func.sum(TradeOutcome.pnl_dollars),
                sa_func.count(TradeOutcome.id),
                sa_func.sum(case((TradeOutcome.outcome == "win", 1), else_=0)),
            )
            .where(TradeOutcome.labeled_at >= cutoff_tz)
            .group_by("day")
            .order_by("day")
        )
        pnl_rows = r.all()

        # Equity history (EquitySnapshot.recorded_at is naive DateTime)
        r = await session.execute(
            select(
                cast(EquitySnapshot.recorded_at, Date).label("day"),
                sa_func.avg(EquitySnapshot.equity),
            )
            .where(EquitySnapshot.recorded_at >= cutoff_naive)
            .group_by("day")
            .order_by("day")
        )
        equity_by_day = {str(row[0]): round(row[1], 2) for row in r.all()}

    # Build daily series
    daily = []
    cumulative_pnl = 0.0
    pnl_by_day = {}
    for row in pnl_rows:
        day_str = str(row[0])
        pnl_by_day[day_str] = {
            "pnl": round(row[1] or 0, 2),
            "trades": row[2] or 0,
            "wins": row[3] or 0,
        }

    # Generate complete date range
    current = cutoff.date()
    end = datetime.now(timezone.utc).date()
    while current <= end:
        day_str = str(current)
        day_pnl = pnl_by_day.get(day_str, {}).get("pnl", 0)
        cumulative_pnl += day_pnl
        daily.append({
            "date": day_str,
            "promotions": promo_by_day.get(day_str, 0),
            "pnl": day_pnl,
            "cumulative_pnl": round(cumulative_pnl, 2),
            "trades": pnl_by_day.get(day_str, {}).get("trades", 0),
            "wins": pnl_by_day.get(day_str, {}).get("wins", 0),
            "equity": equity_by_day.get(day_str),
        })
        current += timedelta(days=1)

    return {"daily": daily, "days": days}


@router.get("/trades")
async def dashboard_trades(days: int = Query(30, ge=1, le=365)):
    """Trade history with outcomes for the trades table."""
    # Trade.created_at is naive DateTime — use naive cutoff to avoid tz mismatch
    cutoff_naive = datetime.utcnow() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Trade, TradeOutcome)
            .outerjoin(TradeOutcome, TradeOutcome.trade_id == Trade.id)
            .where(Trade.created_at >= cutoff_naive)
            .where(Trade.trade_type != "buy_to_close")
            .order_by(Trade.created_at.desc())
            .limit(200)
        )
        results = r.all()

    trades = []
    for trade, outcome in results:
        trades.append({
            "id": trade.id,
            "symbol": trade.symbol,
            "option_symbol": trade.option_symbol,
            "trade_type": trade.trade_type,
            "side": trade.side,
            "quantity": trade.quantity,
            "price": trade.price,
            "premium": trade.premium,
            "strike": trade.strike,
            "expiration": trade.expiration,
            "status": trade.status,
            "pnl": trade.pnl,
            "order_id": trade.order_id,
            "created_at": trade.created_at.isoformat() if trade.created_at else None,
            "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
            "outcome": outcome.outcome if outcome else None,
            "outcome_pnl": outcome.pnl_dollars if outcome else None,
            "outcome_pnl_pct": outcome.pnl_percent if outcome else None,
            "holding_days": outcome.holding_days if outcome else None,
            "funnel_driven": outcome.funnel_driven if outcome else None,
            "sleeve_id": outcome.sleeve_id if outcome else None,
            "estimated_edge": outcome.estimated_edge if outcome else None,
        })

    # Summary stats
    completed = [t for t in trades if t["outcome"] in ("win", "loss", "breakeven")]
    wins = sum(1 for t in completed if t["outcome"] == "win")
    losses = sum(1 for t in completed if t["outcome"] == "loss")
    total_pnl = sum(t["outcome_pnl"] or 0 for t in completed)
    avg_pnl = total_pnl / len(completed) if completed else 0
    avg_hold = (
        sum(t["holding_days"] or 0 for t in completed) / len(completed)
        if completed
        else 0
    )

    return {
        "trades": trades,
        "summary": {
            "total": len(completed),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / max(wins + losses, 1) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "avg_hold_days": round(avg_hold, 1),
        },
    }


@router.get("/position-alerts")
async def dashboard_position_alerts():
    """Latest position sentinel results for each monitored position."""
    from services.position_sentinel import get_results

    results = get_results()
    alerts = list(results.values())
    alerts.sort(key=lambda a: {"CRITICAL": 0, "DANGER": 1, "WARNING": 2, "OK": 3}.get(a.get("level", "OK"), 4))

    danger_or_critical = [a for a in alerts if a["level"] in ("CRITICAL", "DANGER")]

    return {
        "alerts": alerts,
        "has_critical": any(a["level"] == "CRITICAL" for a in alerts),
        "has_danger": any(a["level"] in ("CRITICAL", "DANGER") for a in alerts),
        "danger_count": len(danger_or_critical),
    }

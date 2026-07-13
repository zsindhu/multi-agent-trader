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
        # Tier 1 / Tier 2 counts from each tier's LATEST sweep. Sweeps are
        # append-only; counting all of today's rows would multiply by the
        # number of sweeps run so far.
        from sqlalchemy import or_, and_
        from services.sweep_utils import latest_sweep_subq
        r = await session.execute(
            select(
                NameObservation.tier,
                NameObservation.was_considered,
                sa_func.count(NameObservation.id),
            )
            .where(NameObservation.timestamp >= today_start)
            .where(or_(
                and_(NameObservation.tier == 1,
                     NameObservation.sweep_id == latest_sweep_subq(1, today_start)),
                and_(NameObservation.tier == 2,
                     NameObservation.sweep_id == latest_sweep_subq(2, today_start)),
            ))
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

        # Learning progress, 3-state, using the SAME math as the signal
        # learner: distinct decisions (not contracts), contaminated labels
        # excluded, plus the count of unknown-evidence outcomes.
        from services.signal_learner import SignalLearner
        contaminated = SignalLearner.CONTAMINATED_OUTCOME_IDS
        r = await session.execute(
            select(TradeOutcome.id, TradeOutcome.name_observation_id).where(
                TradeOutcome.funnel_driven == True,  # noqa: E712
                TradeOutcome.outcome.in_(["win", "loss"]),
            )
        )
        decisions = set()
        for oid, obs_id in r.all():
            if oid in contaminated:
                continue
            decisions.add(obs_id or f"outcome:{oid}")
        clean_samples = len(decisions)
        r = await session.execute(
            select(sa_func.count(TradeOutcome.id)).where(
                TradeOutcome.funnel_driven.is_(None)
            )
        )
        unknown_samples = r.scalar() or 0

    return {
        "funnel": {
            "tier1_universe": t1_total,
            "tier2_promoted": t2_pass,
            "tier2_rejected": t2_reject,
        },
        "learning_progress": {
            "samples": clean_samples,  # legacy key = clean count
            "clean": clean_samples,
            "unknown": unknown_samples,
            "contaminated_excluded": len(SignalLearner.CONTAMINATED_OUTCOME_IDS),
            "threshold": 50,
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
        # Latest sweep of the requested day (legacy days have one sweep,
        # dedup filter keeps them via the NULL branch)
        from services.sweep_utils import sweep_dedup_filter
        r = await session.execute(
            select(NameObservation)
            .where(
                NameObservation.tier == 2,
                NameObservation.was_considered == True,
                NameObservation.timestamp >= day_start,
                NameObservation.timestamp < day_end,
            )
            .where(sweep_dedup_filter(2, day_start))
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
            "reasoning": obs.tier2b_reasoning or analysis.get("tier2b_reasoning"),
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
        # One sweep per day (latest) so firing rates aren't skewed toward
        # days with more sweeps
        from services.sweep_utils import sweep_dedup_filter
        r = await session.execute(
            select(NameObservation.analysis)
            .where(
                NameObservation.tier == 2,
                NameObservation.was_considered == True,
                NameObservation.timestamp >= cutoff,
            )
            .where(sweep_dedup_filter(2, cutoff))
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
            select(
                AgentMessage.body, AgentMessage.timestamp,
                AgentMessage.subject, AgentMessage.payload,
            )
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
        "structured": ref[3],
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
async def dashboard_cycles(
    limit: int = Query(10, ge=1, le=100),
    days: int = Query(None, ge=1, le=365),
):
    """Recent Lead Agent cycles with summaries."""
    async with AsyncSessionLocal() as session:
        query = select(CycleSnapshot).order_by(desc(CycleSnapshot.timestamp))
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.where(CycleSnapshot.timestamp >= cutoff)
        r = await session.execute(query.limit(limit))
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
                "envelope": (c.full_context or {}).get("envelope"),
                "sleeve_envelopes": (c.full_context or {}).get("sleeve_envelopes"),
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
        # Daily promotion counts, deduped to each day's latest sweep
        # (NameObservation.timestamp is tz-aware)
        from services.sweep_utils import sweep_dedup_filter
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
            .where(sweep_dedup_filter(2, cutoff_tz))
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
    current = cutoff_tz.date()
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
            .order_by(Trade.created_at.desc())
        )
        results = r.all()

    # Build a lookup of buy_to_close trades by (symbol, strike, expiration)
    # so we can check if a sell_to_open has a matching close
    btc_by_key = {}
    for trade, _ in results:
        if trade.trade_type == "buy_to_close" and trade.status == "filled":
            key = (trade.symbol, str(trade.strike), str(trade.expiration))
            btc_by_key.setdefault(key, []).append(trade)

    trades = []
    for trade, outcome in results:
        # Compute display_pnl priority: outcome_pnl → trade.pnl → None.
        # buy_to_close legs never get a display_pnl — the round trip's PnL is
        # shown on the entry row, and counting both legs doubled every close.
        display_pnl = None
        if trade.trade_type == "buy_to_close":
            display_pnl = None
        elif outcome and outcome.pnl_dollars is not None:
            display_pnl = outcome.pnl_dollars
        elif trade.pnl is not None and trade.status == "filled":
            display_pnl = float(trade.pnl)
        elif trade.trade_type == "sell_to_open" and trade.status == "filled":
            # Not yet labeled — borrow the matching close leg's estimate
            key = (trade.symbol, str(trade.strike), str(trade.expiration))
            for btc in btc_by_key.get(key, []):
                if btc.created_at and trade.created_at and btc.created_at >= trade.created_at and btc.pnl is not None:
                    display_pnl = float(btc.pnl)
                    break

        # Compute display_outcome based on trade type and state
        if trade.trade_type == "buy_to_close":
            display_outcome = "Close"
        elif outcome and outcome.outcome:
            display_outcome = outcome.outcome.capitalize()  # Win, Loss, Breakeven
        elif trade.status in ("order_expired", "expired"):
            # Order expired unfilled — never a position, never an outcome
            display_outcome = "Unfilled"
        elif trade.status == "partially_filled":
            display_outcome = "Partial Fill"
        elif trade.status == "assigned":
            display_outcome = "Assigned"
        elif trade.status == "closed":
            display_outcome = "Closed"
        elif trade.trade_type == "sell_to_open" and trade.status == "filled":
            # Check if there's a matching buy_to_close or broker-side close
            key = (trade.symbol, str(trade.strike), str(trade.expiration))
            has_close = any(
                btc.created_at >= trade.created_at
                for btc in btc_by_key.get(key, [])
                if btc.created_at and trade.created_at
            )
            display_outcome = "Closed" if has_close else "Open"
        else:
            display_outcome = trade.status.capitalize() if trade.status else "--"

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
            "fill_price": trade.fill_price,
            "filled_at": trade.filled_at.isoformat() if trade.filled_at else None,
            "trade_sleeve_id": trade.sleeve_id,
            "display_pnl": round(display_pnl, 2) if display_pnl is not None else None,
            "display_outcome": display_outcome,
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

    # Summary stats from full dataset (not capped)
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

    # Per-sleeve scorecard (labeled outcomes only; sleeve from outcome, else trade)
    by_sleeve: dict = {}
    for t in completed:
        sid = t["sleeve_id"] or t["trade_sleeve_id"] or "unattributed"
        s = by_sleeve.setdefault(sid, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        s["trades"] += 1
        s["wins"] += 1 if t["outcome"] == "win" else 0
        s["losses"] += 1 if t["outcome"] == "loss" else 0
        s["pnl"] += t["outcome_pnl"] or 0
    for s in by_sleeve.values():
        s["pnl"] = round(s["pnl"], 2)
        s["win_rate"] = round(s["wins"] / max(s["wins"] + s["losses"], 1) * 100, 1)

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
            "by_sleeve": by_sleeve,
        },
    }


@router.get("/conflicts")
async def dashboard_conflicts(days: int = Query(7, ge=1, le=90)):
    """Sleeve conflict-resolution verdicts (persisted by the orchestrator)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentAction)
            .where(AgentAction.action_type == "conflict_resolved")
            .where(AgentAction.timestamp >= cutoff)
            .order_by(desc(AgentAction.timestamp))
            .limit(100)
        )
        rows = list(r.scalars().all())
    return {
        "conflicts": [
            {
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "symbol": a.target_symbol,
                "winner": a.outcome,
                **(a.payload or {}),
            }
            for a in rows
        ],
        "count": len(rows),
    }


@router.get("/activity")
async def dashboard_activity(limit: int = Query(40, ge=1, le=200)):
    """Recent agent actions for the live-activity terminal feed."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentAction).order_by(desc(AgentAction.timestamp)).limit(limit)
        )
        rows = list(r.scalars().all())
    return {
        "events": [
            {
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "agent": a.agent_name,
                "action_type": a.action_type,
                "outcome": a.outcome,
                "symbol": a.target_symbol,
                "reason": a.reason,
            }
            for a in rows
        ]
    }


@router.get("/message-bus")
async def dashboard_message_bus(limit: int = Query(30, ge=1, le=100)):
    """Recent inter-agent messages (agent_messages table)."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentMessage).order_by(desc(AgentMessage.timestamp)).limit(limit)
        )
        rows = list(r.scalars().all())
    return {
        "messages": [
            {
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "sender": m.sender,
                "recipient": getattr(m, "recipient", None),
                "message_type": m.message_type,
                "subject": m.subject,
            }
            for m in rows
        ]
    }


@router.get("/agent-costs")
async def dashboard_agent_costs():
    """Per-caller LLM cost today + month-to-date total (llm_usage_log)."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(
                LlmUsageLog.caller,
                sa_func.count(LlmUsageLog.id),
                sa_func.sum(LlmUsageLog.cost_usd),
            )
            .where(LlmUsageLog.timestamp >= today_start)
            .group_by(LlmUsageLog.caller)
            .order_by(desc(sa_func.sum(LlmUsageLog.cost_usd)))
        )
        today_rows = r.all()
        r = await session.execute(
            select(sa_func.sum(LlmUsageLog.cost_usd)).where(
                LlmUsageLog.timestamp >= month_start
            )
        )
        mtd = float(r.scalar() or 0.0)
    return {
        "today": [
            {"caller": c or "unknown", "calls": n, "cost_usd": round(float(cost or 0), 4)}
            for c, n, cost in today_rows
        ],
        "mtd_usd": round(mtd, 2),
        "budget_usd": 150.0,
    }


@router.get("/fill-quality")
async def dashboard_fill_quality(days: int = Query(30, ge=1, le=365)):
    """Entry-order fill rate and slippage (fill vs submitted limit)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Trade.status, Trade.premium, Trade.fill_price)
            .where(Trade.trade_type == "sell_to_open")
            .where(Trade.created_at >= cutoff)
        )
        rows = r.all()
    submitted = len(rows)
    filled = [x for x in rows if x[0] in ("filled", "partially_filled", "closed", "assigned")]
    slippages = [
        float(fp) - float(prem)
        for st, prem, fp in filled
        if fp is not None and prem is not None
    ]
    return {
        "days": days,
        "entry_orders": submitted,
        "filled": len(filled),
        "fill_rate_pct": round(len(filled) / submitted * 100, 1) if submitted else None,
        "avg_slippage": round(sum(slippages) / len(slippages), 4) if slippages else None,
        "slippage_samples": len(slippages),
    }


@router.get("/reconciliation")
async def dashboard_reconciliation():
    """Latest nightly broker-reconciliation report (DB vs Alpaca)."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentMessage)
            .where(AgentMessage.message_type == "reconciliation_report")
            .order_by(desc(AgentMessage.timestamp))
            .limit(1)
        )
        msg = r.scalar_one_or_none()

    if msg is None:
        return {"report": None}
    return {"report": msg.payload, "subject": msg.subject}


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

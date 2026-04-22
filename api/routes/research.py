"""
Research Inspector — Plain HTML routes for inspecting the research data layer.

No JavaScript, no CSS framework. Server-rendered HTML tables.
The goal is inspectability, not beauty.
"""
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, desc, func as sa_func

from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.trade import Trade
from models.trade_outcome import TradeOutcome
from models.cycle_snapshot import CycleSnapshot
from models.agent_message import AgentMessage
from models.agent_action import AgentAction

router = APIRouter()

STYLE = """
<style>
  body { font-family: 'Courier New', monospace; background: #f5f5f5; color: #222; padding: 20px; max-width: 1400px; margin: 0 auto; }
  h1 { border-bottom: 2px solid #222; padding-bottom: 8px; }
  h2 { margin-top: 30px; border-bottom: 1px solid #999; }
  table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
  th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: #ddd; font-weight: bold; }
  tr:nth-child(even) { background: #eee; }
  .win { color: green; font-weight: bold; }
  .loss { color: red; font-weight: bold; }
  nav { margin-bottom: 20px; }
  nav a { margin-right: 15px; text-decoration: none; color: #0066cc; font-weight: bold; }
  nav a:hover { text-decoration: underline; }
  .stat { display: inline-block; margin: 5px 15px 5px 0; padding: 8px 12px; background: #ddd; }
  .stat b { display: block; font-size: 18px; }
  pre { background: #e8e8e8; padding: 10px; overflow-x: auto; white-space: pre-wrap; font-size: 12px; }
</style>
"""

NAV = """
<nav>
  <a href="/research">Dashboard</a>
  <a href="/research/promotions">Promotions</a>
  <a href="/research/trades">Trades</a>
  <a href="/research/signals">Signals</a>
</nav>
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<html><head><title>{title}</title>{STYLE}</head><body>{NAV}<h1>{title}</h1>{body}</body></html>")


@router.get("/research", response_class=HTMLResponse)
async def research_dashboard():
    """Main research dashboard — summary stats + latest data."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    parts = []

    async with AsyncSessionLocal() as session:
        # Tier counts today
        r = await session.execute(
            select(NameObservation.tier, NameObservation.was_considered, sa_func.count(NameObservation.id))
            .where(NameObservation.timestamp >= today_start)
            .group_by(NameObservation.tier, NameObservation.was_considered)
        )
        tier_counts = r.all()

        t1_pass = sum(c for t, w, c in tier_counts if t == 1 and w)
        t2_pass = sum(c for t, w, c in tier_counts if t == 2 and w)
        t2_rej = sum(c for t, w, c in tier_counts if t == 2 and not w)

        parts.append(f'<div class="stat"><b>{t1_pass}</b>Tier 1 passes</div>')
        parts.append(f'<div class="stat"><b>{t2_pass}</b>Tier 2 promoted</div>')
        parts.append(f'<div class="stat"><b>{t2_rej}</b>Tier 2 rejected</div>')

        # Trade outcomes
        r = await session.execute(
            select(TradeOutcome.outcome, sa_func.count(TradeOutcome.id))
            .group_by(TradeOutcome.outcome)
        )
        outcomes = dict(r.all())
        wins = outcomes.get("win", 0)
        losses = outcomes.get("loss", 0)
        parts.append(f'<div class="stat"><b>{wins}W / {losses}L</b>All-time</div>')

        # Latest cycle
        r = await session.execute(
            select(CycleSnapshot.timestamp, CycleSnapshot.summary, CycleSnapshot.llm_cost_usd)
            .order_by(desc(CycleSnapshot.timestamp)).limit(1)
        )
        cycle = r.one_or_none()
        if cycle:
            parts.append(f'<div class="stat"><b>${cycle[2] or 0:.4f}</b>Last cycle cost</div>')

    parts.append("<h2>Top 15 Promotions Today</h2>")

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(NameObservation)
            .where(NameObservation.tier == 2, NameObservation.was_considered == True, NameObservation.timestamp >= today_start)
            .order_by(NameObservation.composite_score.desc()).limit(15)
        )
        promos = list(r.scalars().all())

    if promos:
        parts.append("<table><tr><th>Symbol</th><th>Score</th><th>Signals</th><th>Reasoning</th></tr>")
        for p in promos:
            analysis = p.analysis or {}
            signals = analysis.get("signals", {})
            firing = [n for n, s in signals.items() if s.get("fired")]
            reasoning = (analysis.get("tier2b_reasoning") or "—")[:100]
            parts.append(f"<tr><td>{p.symbol}</td><td>{p.composite_score or 0:.4f}</td><td>{', '.join(firing[:3])}</td><td>{reasoning}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>No promotions today.</p>")

    # Latest reflection
    parts.append("<h2>Latest Research Analyst Reflection</h2>")
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(AgentMessage.body, AgentMessage.timestamp)
            .where(AgentMessage.sender == "Research-Analyst", AgentMessage.message_type == "daily_reflection")
            .order_by(desc(AgentMessage.timestamp)).limit(1)
        )
        ref = r.one_or_none()
    if ref:
        parts.append(f"<p><i>{ref[1]}</i></p><pre>{ref[0] or '(empty)'}</pre>")
    else:
        parts.append("<p>No reflection available.</p>")

    return _page("Research Dashboard", "\n".join(parts))


@router.get("/research/promotions", response_class=HTMLResponse)
async def research_promotions(days: int = Query(1, ge=1, le=30)):
    """Full promotion list with signal details."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(NameObservation)
            .where(NameObservation.tier == 2, NameObservation.was_considered == True, NameObservation.timestamp >= cutoff)
            .order_by(NameObservation.composite_score.desc()).limit(200)
        )
        promos = list(r.scalars().all())

    rows = []
    for p in promos:
        analysis = p.analysis or {}
        signals = analysis.get("signals", {})
        firing = [n for n, s in signals.items() if s.get("fired")]
        amp = analysis.get("amplification_applied", 1.0)
        reasoning = (analysis.get("tier2b_reasoning") or "")[:80]
        ts = p.timestamp.strftime("%m-%d %H:%M") if p.timestamp else ""

        rows.append(f"<tr><td>{p.symbol}</td><td>{p.composite_score or 0:.4f}</td>"
                     f"<td>{len(firing)}</td><td>{', '.join(firing)}</td>"
                     f"<td>{'%.1fx' % amp if amp != 1.0 else ''}</td>"
                     f"<td>{reasoning}</td><td>{ts}</td></tr>")

    table = ("<table><tr><th>Symbol</th><th>Score</th><th>#</th><th>Firing Rules</th>"
             "<th>Amp</th><th>Reasoning</th><th>Time</th></tr>" + "\n".join(rows) + "</table>")

    return _page(f"Promotions (last {days}d, {len(promos)} shown)", table)


@router.get("/research/trades", response_class=HTMLResponse)
async def research_trades(days: int = Query(30, ge=1, le=365)):
    """Trade history with outcomes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Trade, TradeOutcome)
            .outerjoin(TradeOutcome, TradeOutcome.trade_id == Trade.id)
            .where(Trade.created_at >= cutoff)
            .order_by(Trade.created_at.desc()).limit(100)
        )
        trades = r.all()

    rows = []
    for trade, outcome in trades:
        pnl = f"${outcome.pnl_dollars:.0f}" if outcome and outcome.pnl_dollars else "—"
        result_cls = ""
        result_str = trade.status
        if outcome:
            result_str = outcome.outcome
            result_cls = "win" if outcome.outcome == "win" else ("loss" if outcome.outcome == "loss" else "")
        funnel = "✓" if outcome and outcome.funnel_driven else ""
        ts = trade.created_at.strftime("%m-%d") if trade.created_at else ""

        rows.append(f'<tr><td>{trade.symbol}</td><td>{trade.trade_type or ""}</td>'
                     f'<td class="{result_cls}">{result_str}</td><td>{pnl}</td>'
                     f'<td>{outcome.holding_days if outcome and outcome.holding_days else "—"}d</td>'
                     f'<td>{funnel}</td><td>{ts}</td></tr>')

    table = ("<table><tr><th>Symbol</th><th>Type</th><th>Outcome</th><th>PnL</th>"
             "<th>Days</th><th>Funnel</th><th>Date</th></tr>" + "\n".join(rows) + "</table>")

    return _page(f"Trades (last {days}d, {len(trades)} shown)", table)


@router.get("/research/signals", response_class=HTMLResponse)
async def research_signals():
    """Signal performance — firing rates from last 14 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(NameObservation.analysis)
            .where(NameObservation.tier == 2, NameObservation.was_considered == True, NameObservation.timestamp >= cutoff)
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

    rows = []
    for name, s in sorted(stats.items(), key=lambda x: x[1]["fired"] / max(x[1]["total"], 1), reverse=True):
        rate = s["fired"] / max(s["total"], 1) * 100
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        rows.append(f"<tr><td>{name}</td><td>{s['total']}</td><td>{s['fired']}</td>"
                     f"<td>{rate:.1f}%</td><td><code>{bar}</code></td></tr>")

    table = ("<table><tr><th>Signal</th><th>Evaluated</th><th>Fired</th>"
             "<th>Fire Rate</th><th>Distribution</th></tr>" + "\n".join(rows) + "</table>")

    return _page(f"Signal Performance (14d, {len(analyses)} observations)", table)


@router.get("/research/cycle/{cycle_id}", response_class=HTMLResponse)
async def research_cycle(cycle_id: int):
    """Drill into a specific Lead Agent cycle."""
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(CycleSnapshot).where(CycleSnapshot.id == cycle_id)
        )
        cycle = r.scalar_one_or_none()

    if not cycle:
        return _page("Cycle Not Found", f"<p>No cycle with ID {cycle_id}</p>")

    parts = [
        f"<p>Time: {cycle.timestamp} | Regime: {cycle.regime} | VIX: {cycle.vix_level}</p>",
        f"<p>Equity: ${cycle.equity or 0:,.0f} | Cash: ${cycle.cash or 0:,.0f} | "
        f"Actions: {cycle.actions_decided} decided, {cycle.actions_executed} executed</p>",
        f"<p>LLM: {cycle.llm_tokens_in or 0} in / {cycle.llm_tokens_out or 0} out | "
        f"Cost: ${cycle.llm_cost_usd or 0:.4f} | Model: {cycle.llm_model or '?'}</p>",
        f"<h2>Summary</h2><pre>{cycle.summary or '(none)'}</pre>",
        f"<h2>Reasoning</h2><pre>{(cycle.reasoning or '(none)')[:3000]}</pre>",
    ]

    return _page(f"Cycle #{cycle_id}", "\n".join(parts))

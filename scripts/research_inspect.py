#!/usr/bin/env python3
"""
Research Inspector CLI — Quick lookups into the research data layer.

Usage:
  python scripts/inspect.py promotions [--date DATE]
  python scripts/inspect.py trades [--days N]
  python scripts/inspect.py signals
  python scripts/inspect.py cycle [--id ID]
  python scripts/inspect.py reflection [--date DATE]
  python scripts/inspect.py health
"""
import argparse
import asyncio
import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, desc, func as sa_func, text as sql_text

from core.database import AsyncSessionLocal
from models.name_observation import NameObservation
from models.trade import Trade
from models.trade_outcome import TradeOutcome
from models.cycle_snapshot import CycleSnapshot
from models.agent_message import AgentMessage
from models.agent_action import AgentAction


def _table(headers, rows, widths=None):
    """Simple table formatter (no rich dependency required, but uses it if available)."""
    try:
        from rich.console import Console
        from rich.table import Table
        console = Console()
        t = Table(show_lines=False)
        for h in headers:
            t.add_column(h)
        for row in rows:
            t.add_row(*[str(v) for v in row])
        console.print(t)
        return
    except ImportError:
        pass

    # Fallback: plain text
    if not rows:
        print("  (no data)")
        return
    col_widths = widths or [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
    header_line = "  ".join(str(h).ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))


async def cmd_promotions(args):
    """Today's top Tier 2 promotions with signal profiles."""
    target_date = date.fromisoformat(args.date) if args.date else date.today()
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(NameObservation)
            .where(NameObservation.tier == 2)
            .where(NameObservation.was_considered == True)
            .where(NameObservation.timestamp >= day_start)
            .where(NameObservation.timestamp < day_end)
            .order_by(NameObservation.composite_score.desc())
            .limit(args.limit)
        )
        rows = list(result.scalars().all())

    print(f"\n=== Tier 2 Promotions for {target_date} ({len(rows)} shown) ===\n")

    table_rows = []
    for obs in rows:
        analysis = obs.analysis or {}
        signals = analysis.get("signals", {})
        firing = [n for n, s in signals.items() if s.get("fired")]
        reasoning = (analysis.get("tier2b_reasoning") or "")[:60]
        amp = analysis.get("amplification_applied", 1.0)

        table_rows.append([
            obs.symbol,
            f"{obs.composite_score or 0:.4f}",
            str(len(firing)),
            ", ".join(firing[:3]) + ("..." if len(firing) > 3 else ""),
            f"{amp:.1f}x" if amp != 1.0 else "",
            reasoning or "—",
        ])

    _table(["Symbol", "Score", "Fired", "Top Signals", "Amp", "Reasoning"], table_rows)


async def cmd_trades(args):
    """Recent trades with outcomes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade, TradeOutcome)
            .outerjoin(TradeOutcome, TradeOutcome.trade_id == Trade.id)
            .where(Trade.created_at >= cutoff)
            .order_by(Trade.created_at.desc())
            .limit(30)
        )
        rows = result.all()

    print(f"\n=== Trades (last {args.days} days, {len(rows)} shown) ===\n")

    table_rows = []
    for trade, outcome in rows:
        pnl = f"${outcome.pnl_dollars:.0f}" if outcome and outcome.pnl_dollars else "—"
        result_str = outcome.outcome if outcome else trade.status
        funnel = "✓" if outcome and outcome.funnel_driven else ""

        table_rows.append([
            str(trade.id),
            trade.symbol,
            trade.trade_type or "",
            trade.status,
            result_str,
            pnl,
            f"{outcome.holding_days}d" if outcome and outcome.holding_days else "—",
            funnel,
        ])

    _table(["ID", "Symbol", "Type", "Status", "Outcome", "PnL", "Days", "Funnel"], table_rows)


async def cmd_signals(args):
    """Signal firing rates from recent Tier 2 observations."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(NameObservation.analysis)
            .where(NameObservation.tier == 2)
            .where(NameObservation.was_considered == True)
            .where(NameObservation.timestamp >= cutoff)
        )
        analyses = [r[0] for r in result.all() if r[0]]

    if not analyses:
        print("\nNo Tier 2 observations in last 14 days.")
        return

    # Aggregate signal stats
    signal_stats = {}
    for analysis in analyses:
        signals = analysis.get("signals", {})
        for name, sig in signals.items():
            if name not in signal_stats:
                signal_stats[name] = {"total": 0, "fired": 0}
            signal_stats[name]["total"] += 1
            if sig.get("fired"):
                signal_stats[name]["fired"] += 1

    print(f"\n=== Signal Performance (last 14 days, {len(analyses)} observations) ===\n")

    table_rows = []
    for name, stats in sorted(signal_stats.items(), key=lambda x: x[1]["fired"] / max(x[1]["total"], 1), reverse=True):
        rate = stats["fired"] / max(stats["total"], 1) * 100
        table_rows.append([name, str(stats["total"]), str(stats["fired"]), f"{rate:.1f}%"])

    _table(["Signal", "Evaluated", "Fired", "Fire Rate"], table_rows)


async def cmd_cycle(args):
    """Drill into a specific Lead Agent cycle."""
    async with AsyncSessionLocal() as session:
        if args.id:
            result = await session.execute(
                select(CycleSnapshot).where(CycleSnapshot.id == args.id)
            )
        else:
            result = await session.execute(
                select(CycleSnapshot).order_by(CycleSnapshot.timestamp.desc()).limit(1)
            )
        cycle = result.scalar_one_or_none()

    if not cycle:
        print("\nNo cycle found.")
        return

    print(f"\n=== Cycle #{cycle.id} — {cycle.timestamp} ===")
    print(f"  Regime: {cycle.regime}, VIX: {cycle.vix_level}")
    print(f"  Equity: ${cycle.equity or 0:,.0f}, Cash: ${cycle.cash or 0:,.0f}")
    print(f"  Actions decided: {cycle.actions_decided}, executed: {cycle.actions_executed}")
    print(f"  LLM: {cycle.llm_tokens_in or 0} in / {cycle.llm_tokens_out or 0} out, cost: ${cycle.llm_cost_usd or 0:.4f}")
    print(f"\n--- Summary ---")
    print(cycle.summary or "(none)")
    print(f"\n--- Reasoning ---")
    print((cycle.reasoning or "(none)")[:2000])
    if cycle.full_context:
        actions = cycle.full_context.get("actions", [])
        if actions:
            print(f"\n--- Actions ({len(actions)}) ---")
            for a in actions:
                print(f"  {a}")


async def cmd_reflection(args):
    """Latest Research Analyst reflection."""
    target_date = date.fromisoformat(args.date) if args.date else None

    async with AsyncSessionLocal() as session:
        query = (
            select(AgentMessage)
            .where(AgentMessage.sender == "Research-Analyst")
            .where(AgentMessage.message_type == "daily_reflection")
            .order_by(desc(AgentMessage.timestamp))
            .limit(1)
        )
        if target_date:
            day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            query = query.where(AgentMessage.timestamp >= day_start)

        result = await session.execute(query)
        msg = result.scalar_one_or_none()

    if not msg:
        print("\nNo reflection found.")
        return

    print(f"\n=== Research Analyst Reflection — {msg.timestamp} ===")
    print(f"Subject: {msg.subject}\n")
    print(msg.body or "(empty)")


async def cmd_health(args):
    """System health check — last sweep times, error counts, cost."""
    print("\n=== System Health ===\n")

    async with AsyncSessionLocal() as session:
        # Last Tier 1 sweep
        r = await session.execute(
            select(sa_func.max(NameObservation.timestamp))
            .where(NameObservation.tier == 1)
        )
        t1_last = r.scalar()
        print(f"  Last Tier 1 sweep: {t1_last or 'never'}")

        # Last Tier 2 sweep
        r = await session.execute(
            select(sa_func.max(NameObservation.timestamp))
            .where(NameObservation.tier == 2)
        )
        t2_last = r.scalar()
        print(f"  Last Tier 2 sweep: {t2_last or 'never'}")

        # Last Lead Agent cycle
        r = await session.execute(
            select(sa_func.max(CycleSnapshot.timestamp))
        )
        cycle_last = r.scalar()
        print(f"  Last Lead Agent cycle: {cycle_last or 'never'}")

        # Today's observation counts
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        r = await session.execute(
            select(
                NameObservation.tier,
                NameObservation.was_considered,
                sa_func.count(NameObservation.id),
            )
            .where(NameObservation.timestamp >= today_start)
            .group_by(NameObservation.tier, NameObservation.was_considered)
        )
        counts = r.all()
        if counts:
            print(f"\n  Today's observations:")
            for tier, considered, count in counts:
                label = "passed" if considered else "rejected"
                print(f"    Tier {tier} {label}: {count}")

        # Today's errors in agent_actions
        r = await session.execute(
            select(sa_func.count(AgentAction.id))
            .where(AgentAction.outcome == "failed")
            .where(AgentAction.timestamp >= today_start)
        )
        errors = r.scalar() or 0
        print(f"\n  Today's errors: {errors}")

        # Today's LLM cost
        r = await session.execute(
            select(sa_func.sum(CycleSnapshot.llm_cost_usd))
            .where(CycleSnapshot.timestamp >= today_start)
        )
        cost = r.scalar() or 0
        print(f"  Today's LLM cost: ${cost:.4f}")

        # Trade outcomes
        r = await session.execute(
            select(TradeOutcome.outcome, sa_func.count(TradeOutcome.id))
            .group_by(TradeOutcome.outcome)
        )
        outcomes = r.all()
        if outcomes:
            print(f"\n  Trade outcomes (all time):")
            for outcome, count in outcomes:
                print(f"    {outcome}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Research Inspector CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("promotions", help="Today's Tier 2 promotions")
    p.add_argument("--date", default=None, help="Date (YYYY-MM-DD, default today)")
    p.add_argument("--limit", type=int, default=20, help="Max rows (default 20)")

    p = subparsers.add_parser("trades", help="Recent trades with outcomes")
    p.add_argument("--days", type=int, default=30, help="Lookback days (default 30)")

    subparsers.add_parser("signals", help="Signal firing rates")

    p = subparsers.add_parser("cycle", help="Lead Agent cycle detail")
    p.add_argument("--id", type=int, default=None, help="Cycle ID (default: latest)")

    p = subparsers.add_parser("reflection", help="Research Analyst reflection")
    p.add_argument("--date", default=None, help="Date (YYYY-MM-DD, default latest)")

    subparsers.add_parser("health", help="System health check")

    args = parser.parse_args()

    cmd_map = {
        "promotions": cmd_promotions,
        "trades": cmd_trades,
        "signals": cmd_signals,
        "cycle": cmd_cycle,
        "reflection": cmd_reflection,
        "health": cmd_health,
    }
    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()

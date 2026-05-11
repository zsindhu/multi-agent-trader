"""
Trades Routes — Trade history, journal entries, performance metrics, CSV exports.
"""
import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse

from api.state import AppState
from services.logger_service import PerformanceLogger
from agents.trade_journal import TradeJournalAgent

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/history")
async def get_trade_history(
    request: Request,
    agent: Optional[str] = Query(None, description="Filter by agent name"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    include_cancelled: bool = Query(False, description="Include cancelled/ghost trades"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated trade history with optional filters."""
    state = _get_state(request)
    if not state.perf_logger:
        return {"trades": [], "total": 0}

    trades = await state.perf_logger.get_trade_history(
        agent_name=agent, symbol=symbol, limit=limit, offset=offset,
    )

    if not include_cancelled:
        trades = [t for t in trades if t.status != "cancelled"]

    return {
        "trades": [
            {
                "id": t.id,
                "agent_name": t.agent_name,
                "symbol": t.symbol,
                "option_symbol": t.option_symbol,
                "trade_type": t.trade_type,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "premium": t.premium,
                "strike": t.strike,
                "expiration": t.expiration,
                "status": t.status,
                "pnl": t.pnl,
                "notes": t.notes,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/journal")
async def get_journal_entries(
    request: Request,
    agent: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Full journal entries with market context."""
    state = _get_state(request)
    if not state.trade_journal:
        return {"entries": []}

    entries = await state.trade_journal.get_full_journal(
        agent_name=agent, symbol=symbol, limit=limit,
    )

    return {
        "entries": [
            {
                "id": e.id,
                "agent_name": e.agent_name,
                "symbol": e.symbol,
                "asset_type": e.asset_type,
                "option_symbol": e.option_symbol,
                "contract_type": e.contract_type,
                "strike": e.strike,
                "expiration": e.expiration,
                "side": e.side,
                "quantity": e.quantity,
                "fill_price": e.fill_price,
                "premium": e.premium,
                "entry_iv_rank": e.entry_iv_rank,
                "entry_stock_price": e.entry_stock_price,
                "entry_vix_level": e.entry_vix_level,
                "delta_at_entry": e.delta_at_entry,
                "dte_at_entry": e.dte_at_entry,
                "annualized_return_at_entry": e.annualized_return_at_entry,
                "exit_stock_price": e.exit_stock_price,
                "exit_reason": e.exit_reason,
                "realized_pnl": e.realized_pnl,
                "days_held": e.days_held,
                "return_pct": e.return_pct,
                "entry_at": e.entry_at.isoformat() if e.entry_at else None,
                "exit_at": e.exit_at.isoformat() if e.exit_at else None,
            }
            for e in entries
        ],
    }


@router.get("/performance")
async def get_performance(request: Request):
    """Portfolio-wide performance summary."""
    state = _get_state(request)
    if not state.perf_logger:
        return {}

    return await state.perf_logger.get_portfolio_summary()


@router.get("/performance/{agent_name}")
async def get_agent_performance(
    request: Request,
    agent_name: str,
    days: int = Query(30, ge=1, le=365),
):
    """Per-agent performance metrics."""
    state = _get_state(request)
    if not state.perf_logger:
        return {}

    return await state.perf_logger.get_agent_metrics(agent_name, lookback_days=days)


@router.get("/symbol/{symbol}")
async def get_symbol_stats(request: Request, symbol: str):
    """Per-symbol aggregated stats from the trade journal."""
    state = _get_state(request)
    if not state.trade_journal:
        return {}

    return await state.trade_journal.get_symbol_stats(symbol.upper())


@router.get("/export")
async def export_trades_csv():
    """Download all trades as CSV."""
    from sqlalchemy import select
    from core.database import AsyncSessionLocal
    from models.trade import Trade
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).order_by(Trade.created_at.desc()).limit(10000))
        rows = result.scalars().all()
    output = io.StringIO()
    cols = [c.name for c in Trade.__table__.columns]
    writer = csv.writer(output)
    writer.writerow(cols)
    for r in rows:
        writer.writerow([getattr(r, c, '') for c in cols])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )


@router.get("/journal/export")
async def export_journal_csv(request: Request):
    """Download full trade journal as CSV."""
    from models.journal_entry import JournalEntry
    state = _get_state(request)
    entries = []
    if state.trade_journal:
        entries = await state.trade_journal.get_full_journal(limit=10000)
    output = io.StringIO()
    cols = [c.name for c in JournalEntry.__table__.columns]
    writer = csv.writer(output)
    writer.writerow(cols)
    for e in entries:
        writer.writerow([getattr(e, c, '') for c in cols])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trade_journal.csv"},
    )


@router.get("/debug/counts")
async def get_trade_counts():
    """Diagnostic: raw row counts from database tables. Use to verify data is being written."""
    from sqlalchemy import func, select
    from core.database import AsyncSessionLocal
    from models.trade import Trade
    from models.journal_entry import JournalEntry
    from models.proposal import TradeProposal
    from models.opportunity import ScannerOpportunity

    async with AsyncSessionLocal() as session:
        counts = {}
        for label, model in [
            ("trades_in_db", Trade),
            ("journal_entries_in_db", JournalEntry),
            ("proposals_in_db", TradeProposal),
            ("opportunities_in_db", ScannerOpportunity),
        ]:
            r = await session.execute(select(func.count(model.id)))
            counts[label] = r.scalar()
    return counts

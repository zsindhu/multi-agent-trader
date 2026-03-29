"""
Executions Routes — Auto-trade execution history with full reasoning.

Every trade executed autonomously by the agents is logged here with a
plain-English rationale explaining why it was taken.
"""
import csv
import io
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc

from core.database import AsyncSessionLocal
from models.execution_log import ExecutionLog

router = APIRouter()


def _log_to_dict(e: ExecutionLog) -> dict:
    return {
        "id": e.id,
        "agent_name": e.agent_name,
        "symbol": e.symbol,
        "option_symbol": e.option_symbol,
        "action": e.action,
        "contract_type": e.contract_type,
        "strike": e.strike,
        "expiration": e.expiration,
        "delta": e.delta,
        "dte": e.dte,
        "premium": e.premium,
        "annualized_return": e.annualized_return,
        "probability_of_profit": e.probability_of_profit,
        "collateral_required": e.collateral_required,
        "break_even_price": e.break_even_price,
        "iv_rank_at_entry": e.iv_rank_at_entry,
        "scanner_score": e.scanner_score,
        "stock_price_at_entry": e.stock_price_at_entry,
        "rationale": e.rationale,
        "order_id": e.order_id,
        "order_status": e.order_status,
        "fill_price": e.fill_price,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/latest")
async def get_latest_executions(limit: int = 10):
    """Return the N most recent execution logs — for the dashboard activity feed."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExecutionLog)
            .order_by(desc(ExecutionLog.created_at))
            .limit(limit)
        )
        logs = list(result.scalars().all())
    return [_log_to_dict(e) for e in logs]


@router.get("/export")
async def export_executions_csv():
    """Download all execution logs as CSV."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExecutionLog).order_by(desc(ExecutionLog.created_at)).limit(10000)
        )
        logs = result.scalars().all()
    output = io.StringIO()
    cols = [c.name for c in ExecutionLog.__table__.columns]
    writer = csv.writer(output)
    writer.writerow(cols)
    for log in logs:
        writer.writerow([getattr(log, c, '') for c in cols])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=execution_logs.csv"},
    )


@router.get("")
async def get_executions(
    agent_name: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """Return execution logs with optional filtering by agent or symbol."""
    async with AsyncSessionLocal() as db:
        q = select(ExecutionLog).order_by(desc(ExecutionLog.created_at))
        if agent_name:
            q = q.where(ExecutionLog.agent_name == agent_name)
        if symbol:
            q = q.where(ExecutionLog.symbol == symbol)
        q = q.limit(limit).offset(offset)
        result = await db.execute(q)
        logs = list(result.scalars().all())
    return [_log_to_dict(e) for e in logs]

"""
Diagnostics Routes — LLM usage stats, system health, DB table counts.
"""
from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from api.state import AppState
from core.database import AsyncSessionLocal

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/llm-usage")
async def get_llm_usage(request: Request):
    """Daily token usage and estimated cost for the LLM service."""
    state = _get_state(request)
    if state.llm_service:
        return state.llm_service.get_usage_stats()
    return {"enabled": False}


@router.get("/health")
async def get_system_health(request: Request):
    """Check connectivity for Alpaca, database, and LLM service."""
    state = _get_state(request)
    checks: dict[str, str] = {}

    # Alpaca broker
    try:
        checks["alpaca"] = "ok" if (state.broker and hasattr(state.broker, 'trading') and state.broker.trading) else "not_configured"
    except Exception as e:
        checks["alpaca"] = f"error: {e}"

    # Database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # LLM service
    checks["llm"] = "ok" if (state.llm_service and state.llm_service.is_enabled) else "not_configured"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@router.get("/db-counts")
async def get_db_counts():
    """Row counts for all major database tables."""
    from models.trade import Trade
    from models.execution_log import ExecutionLog
    from models.journal_entry import JournalEntry
    from models.opportunity import ScannerOpportunity
    from models.performance import AgentPerformance
    from models.proposal import TradeProposal

    tables = {
        "trades": Trade,
        "execution_logs": ExecutionLog,
        "journal_entries": JournalEntry,
        "scanner_opportunities": ScannerOpportunity,
        "agent_performance": AgentPerformance,
        "proposals": TradeProposal,
    }
    counts: dict[str, int | None] = {}
    async with AsyncSessionLocal() as session:
        for name, model in tables.items():
            try:
                result = await session.execute(select(func.count()).select_from(model))
                counts[name] = result.scalar()
            except Exception:
                counts[name] = None
    return counts

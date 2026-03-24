"""
Intelligence Routes — Market regime, earnings, performance analytics, and news.

All data comes from the four intelligence services computed on schedule.
Read-only endpoints — no writes from the API layer.
"""
from fastapi import APIRouter, Request, Query
from typing import Optional
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.execution_log import ExecutionLog

router = APIRouter()


def _get_state(request: Request):
    return request.app.state.app


# ── Market Regime ────────────────────────────────────────────────────

@router.get("/regime")
async def get_regime(request: Request):
    """Latest market regime assessment."""
    state = _get_state(request)
    if not state.regime_service:
        return {"regime": "unknown", "summary": "Service not initialized."}
    return await state.regime_service.get_latest()


@router.get("/regime/history")
async def get_regime_history(request: Request, days: int = Query(7, ge=1, le=90)):
    """Regime snapshots over the last N days."""
    state = _get_state(request)
    if not state.regime_service:
        return []
    return await state.regime_service.get_history(days=days)


@router.get("/regime/detail/{metric}")
async def get_regime_detail(request: Request, metric: str):
    """Expanded data for a specific regime metric (e.g. 'sectors', 'breadth')."""
    state = _get_state(request)
    if not state.regime_service:
        return {}
    return await state.regime_service.get_regime_detail(metric)


# ── Earnings Calendar ────────────────────────────────────────────────

@router.get("/earnings")
async def get_earnings(request: Request, days: int = Query(14, ge=1, le=30)):
    """Upcoming earnings events in the next N days."""
    state = _get_state(request)
    if not state.earnings_service:
        return []
    return await state.earnings_service.get_upcoming(days_ahead=days)


@router.get("/earnings/{symbol}")
async def get_earnings_for_symbol(request: Request, symbol: str):
    """Next earnings event for a specific symbol."""
    state = _get_state(request)
    if not state.earnings_service:
        return {"symbol": symbol, "event": None, "risk_level": "unknown"}
    return await state.earnings_service.check_symbol(symbol.upper())


# ── Performance Analytics ────────────────────────────────────────────

@router.get("/performance")
async def get_performance_summary(request: Request, days: int = Query(30, ge=1)):
    """Overall performance summary for the given lookback period."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_summary(days=days)


@router.get("/performance/strategy")
async def get_strategy_breakdown(request: Request):
    """Per-strategy win rates and P&L breakdown."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_strategy_breakdown()


@router.get("/performance/delta")
async def get_delta_analysis(request: Request):
    """Win rate by delta bucket — identifies optimal delta range."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_delta_analysis()


@router.get("/performance/regime")
async def get_regime_correlation(request: Request):
    """Win rate correlated with market regime at trade entry."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_regime_correlation()


@router.get("/performance/symbols")
async def get_symbol_scorecard(request: Request):
    """Per-symbol track record sorted by total P&L."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_symbol_scorecard()


@router.get("/performance/health")
async def get_position_health(request: Request):
    """Health check for currently open positions — flags ITM or deeply underwater."""
    state = _get_state(request)
    if not state.performance_service:
        return {}
    return await state.performance_service.get_open_position_health()


@router.get("/performance/recommendations")
async def get_recommendations(request: Request):
    """Rule-based actionable recommendations from performance data."""
    state = _get_state(request)
    if not state.performance_service:
        return []
    return await state.performance_service.get_recommendations()


# ── News Feed ────────────────────────────────────────────────────────

@router.get("/news")
async def get_news(request: Request, n: int = Query(20, ge=1, le=100)):
    """Recent market headlines."""
    state = _get_state(request)
    if not state.news_service:
        return []
    return await state.news_service.get_recent(n=n)


@router.get("/news/market")
async def get_market_news(request: Request, n: int = Query(10, ge=1, le=50)):
    """Top general market headlines only."""
    state = _get_state(request)
    if not state.news_service:
        return []
    return await state.news_service.get_market_summary(n=n)


@router.get("/news/{symbol}")
async def get_news_for_symbol(request: Request, symbol: str, n: int = Query(10, ge=1, le=50)):
    """Headlines mentioning a specific symbol."""
    state = _get_state(request)
    if not state.news_service:
        return []
    return await state.news_service.get_for_symbol(symbol.upper(), n=n)


# ── Lead Agent Reasoning ──────────────────────────────────────────────

@router.get("/reasoning")
async def get_lead_reasoning(request: Request, limit: int = Query(5, ge=1, le=20)):
    """
    Return the most recent Lead Agent cycle reasoning entries.

    Each entry contains:
    - summary: one-line decision summary
    - reasoning: full Claude reasoning text
    - timestamp: ISO8601 UTC timestamp
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(ExecutionLog)
            .where(
                ExecutionLog.agent_name == "Lead-Agent",
                ExecutionLog.action == "cycle_decision",
            )
            .order_by(ExecutionLog.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()
    return [
        {
            "summary": log.order_status,
            "reasoning": log.rationale,
            "timestamp": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]

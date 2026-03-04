"""
Portfolio Routes — Account overview, positions, options.
"""
from fastapi import APIRouter, Request

from api.state import AppState

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/")
async def get_portfolio(request: Request):
    """Full portfolio snapshot: balances, positions, options, regime."""
    state = _get_state(request)
    return await state.get_portfolio_snapshot()


@router.get("/positions")
async def get_positions(request: Request):
    """Stock positions only."""
    state = _get_state(request)
    snapshot = await state.get_portfolio_snapshot()
    return {"positions": snapshot.get("positions", [])}


@router.get("/options")
async def get_options(request: Request):
    """Option positions only."""
    state = _get_state(request)
    snapshot = await state.get_portfolio_snapshot()
    return {"options": snapshot.get("options", [])}


@router.get("/summary")
async def get_summary(request: Request):
    """High-level portfolio summary for dashboard cards."""
    state = _get_state(request)
    snapshot = await state.get_portfolio_snapshot()

    # Compute aggregates
    positions = snapshot.get("positions", [])
    options = snapshot.get("options", [])

    total_stock_value = sum(p.get("market_value", 0) for p in positions)
    total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
    total_option_pnl = sum(o.get("pnl", 0) for o in options)
    short_options = [o for o in options if o.get("is_short")]
    long_options = [o for o in options if not o.get("is_short")]

    return {
        "equity": snapshot.get("equity", 0),
        "cash": snapshot.get("cash", 0),
        "buying_power": snapshot.get("buying_power", 0),
        "total_value": snapshot.get("total_value", 0),
        "total_stock_value": total_stock_value,
        "total_unrealized_pnl": total_unrealized,
        "total_option_pnl": total_option_pnl,
        "total_premium_collected": snapshot.get("total_premium_collected", 0),
        "stock_positions": len(positions),
        "short_options": len(short_options),
        "long_options": len(long_options),
        "regime": snapshot.get("regime", {}),
        "last_updated": snapshot.get("last_updated", ""),
    }


@router.post("/refresh")
async def refresh_portfolio(request: Request):
    """Force a portfolio sync from the broker."""
    state = _get_state(request)
    if state.portfolio and state.broker:
        await state.portfolio.sync_from_broker(state.broker)
    return {"status": "refreshed"}

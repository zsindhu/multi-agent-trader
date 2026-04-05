"""
Agents Routes — Agent status, regime info, strategy parameters.
"""
import yaml
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.state import AppState

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/status")
async def get_agent_status(request: Request):
    """Status of all known worker agents."""
    # We can't directly access the running workers from the API (they live
    # in main.py's event loop), but we can report scanner + regime state.
    state = _get_state(request)

    regime = {}
    if state.strategy_manager:
        regime = state.strategy_manager.get_regime_summary()

    risk = {}
    if state.risk_manager:
        risk = {
            "conservative_mode": state.risk_manager.conservative_mode,
            "current_drawdown": state.risk_manager.get_current_drawdown(),
            "max_drawdown_limit": state.risk_manager.max_drawdown,
            "high_water_mark": state.risk_manager.high_water_mark,
        }

    # Read worker active state from DB so both containers share truth
    workers_list = []
    try:
        from sqlalchemy import select
        from core.database import AsyncSessionLocal
        from models.worker_state import WorkerState
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(WorkerState).order_by(WorkerState.id))
            rows = list(result.scalars().all())
        if rows:
            _type_map = {
                "Covered-Calls": "Covered Calls",
                "Cash-Secured-Puts": "Cash Secured Puts",
                "Wheel": "The Wheel",
            }
            workers_list = [
                {
                    "name": r.worker_name,
                    "type": _type_map.get(r.worker_name, r.worker_name),
                    "is_active": r.is_active,
                    "paused_reason": r.paused_reason,
                }
                for r in rows
            ]
    except Exception:
        pass

    if not workers_list:
        workers_list = [
            {"name": "Covered-Calls", "type": "Covered Calls", "is_active": True, "paused_reason": None},
            {"name": "Cash-Secured-Puts", "type": "Cash Secured Puts", "is_active": True, "paused_reason": None},
            {"name": "Wheel", "type": "The Wheel", "is_active": True, "paused_reason": None},
        ]

    return {
        "regime": regime,
        "risk": risk,
        "workers": workers_list,
    }


@router.get("/regime")
async def get_regime(request: Request):
    """Current market regime details."""
    state = _get_state(request)
    if not state.strategy_manager:
        return {"regime": "unknown"}

    return state.strategy_manager.get_regime_summary()


@router.post("/regime/refresh")
async def refresh_regime(request: Request):
    """Force a VIX regime refresh."""
    state = _get_state(request)
    if state.strategy_manager:
        await state.strategy_manager.refresh_regime()
    return state.strategy_manager.get_regime_summary() if state.strategy_manager else {}


@router.get("/strategies")
async def get_strategies(request: Request):
    """Return current strategy parameters from strategies.yaml."""
    try:
        with open("config/strategies.yaml", "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg
    except FileNotFoundError:
        return {}


class StrategyUpdate(BaseModel):
    strategy_name: str
    params: dict


@router.put("/strategies")
async def update_strategy(request: Request, update: StrategyUpdate):
    """Update strategy parameters in strategies.yaml."""
    try:
        with open("config/strategies.yaml", "r") as f:
            cfg = yaml.safe_load(f) or {}

        if update.strategy_name not in cfg:
            raise HTTPException(status_code=404, detail=f"Strategy '{update.strategy_name}' not found")

        cfg[update.strategy_name].update(update.params)

        with open("config/strategies.yaml", "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)

        # Reload in strategy manager
        state = _get_state(request)
        if state.strategy_manager:
            state.strategy_manager._base_params = state.strategy_manager._load_strategies()

        return {"status": "updated", "strategy": update.strategy_name, "params": cfg[update.strategy_name]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

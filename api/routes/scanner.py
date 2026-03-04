"""
Scanner Routes — Scanner results, universe info, parameter tuning (Scanner Workshop).
"""
import yaml
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.state import AppState

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/opportunities")
async def get_opportunities(
    request: Request,
    top_n: Optional[int] = None,
):
    """Get the latest scanner opportunities (scored and ranked)."""
    state = _get_state(request)
    if not state.scanner:
        return {"opportunities": []}

    opps = await state.scanner.get_top_opportunities(top_n=top_n)
    return {"opportunities": opps, "count": len(opps)}


@router.post("/run")
async def run_scanner(request: Request):
    """Trigger a full scanner cycle (scan → evaluate → persist)."""
    state = _get_state(request)
    if not state.scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    try:
        raw = await state.scanner.scan()
        scored = await state.scanner.evaluate(raw)
        await state.scanner.execute(scored)
        return {
            "status": "completed",
            "symbols_scanned": len(raw),
            "opportunities_scored": len(scored),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_scanner_config():
    """Get current scanner_universe.yaml config."""
    try:
        with open("config/scanner_universe.yaml", "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("scanner", cfg)
    except FileNotFoundError:
        return {}


class ScannerConfigUpdate(BaseModel):
    """Partial update to scanner config."""
    min_daily_volume: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_iv_rank: Optional[float] = None
    min_liquidity_score: Optional[float] = None
    top_n: Optional[int] = None
    weights: Optional[dict] = None


@router.put("/config")
async def update_scanner_config(request: Request, update: ScannerConfigUpdate):
    """
    Update scanner parameters (Scanner Workshop).

    Only updates provided fields. Writes to scanner_universe.yaml
    and reloads the scanner's config.
    """
    try:
        with open("config/scanner_universe.yaml", "r") as f:
            full_cfg = yaml.safe_load(f) or {}

        scanner_cfg = full_cfg.get("scanner", {})

        # Apply non-None updates
        update_data = update.dict(exclude_none=True)
        for key, value in update_data.items():
            if key == "weights" and isinstance(value, dict):
                scanner_cfg.setdefault("weights", {}).update(value)
            else:
                scanner_cfg[key] = value

        full_cfg["scanner"] = scanner_cfg

        with open("config/scanner_universe.yaml", "w") as f:
            yaml.safe_dump(full_cfg, f, default_flow_style=False)

        # Reload in scanner agent
        state = _get_state(request)
        if state.scanner:
            state.scanner._load_config()

        return {"status": "updated", "config": scanner_cfg}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview")
async def preview_scanner(request: Request, update: ScannerConfigUpdate):
    """
    Preview scanner results with temporary parameter overrides.

    Does NOT persist the config changes — just runs a scan with them
    and returns what the results would look like.
    """
    state = _get_state(request)
    if not state.scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    # Temporarily override scanner params
    original_cfg = dict(state.scanner.config) if hasattr(state.scanner, "config") else {}

    try:
        update_data = update.dict(exclude_none=True)

        # Apply overrides
        if hasattr(state.scanner, "config") and state.scanner.config:
            for key, value in update_data.items():
                if key == "weights" and isinstance(value, dict):
                    state.scanner.config.setdefault("weights", {}).update(value)
                else:
                    state.scanner.config[key] = value

        # Run scan with overridden params
        raw = await state.scanner.scan()
        scored = await state.scanner.evaluate(raw)

        return {
            "status": "preview",
            "overrides": update_data,
            "symbols_scanned": len(raw),
            "opportunities": scored[:20],  # Top 20
        }
    finally:
        # Restore original config
        if hasattr(state.scanner, "config"):
            state.scanner.config = original_cfg

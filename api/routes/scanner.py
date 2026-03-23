"""
Scanner Routes — Scanner results, universe info, parameter tuning (Scanner Workshop).
"""
import yaml
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.state import AppState

router = APIRouter()

# Factory defaults — the original values from scanner_universe.yaml before any
# user customisation.  The Workshop uses these as the baseline reference.
FACTORY_DEFAULTS = {
    "min_daily_volume": 1_000_000,
    "min_price": 5.0,
    "max_price": 500.0,
    "min_iv_rank": 15,
    "min_liquidity_score": 0.3,
    "top_n": 20,
    "weights": {
        "iv_rank": 0.30,
        "momentum": 0.20,
        "liquidity": 0.25,
        "support_proximity": 0.15,
        "mean_reversion": 0.10,
    },
}


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

    opps = await state.scanner.get_top_opportunities(n=top_n)
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
    """Get current scanner_universe.yaml config + factory defaults."""
    try:
        with open("config/scanner_universe.yaml", "r") as f:
            cfg = yaml.safe_load(f) or {}
        current = cfg.get("scanner", cfg)
        return {"current": current, "defaults": FACTORY_DEFAULTS}
    except FileNotFoundError:
        return {"current": {}, "defaults": FACTORY_DEFAULTS}


@router.get("/config/defaults")
async def get_scanner_defaults():
    """Return the factory-default scanner parameters."""
    return FACTORY_DEFAULTS


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


@router.get("/diagnostic")
async def scanner_diagnostic(request: Request):
    """
    Mini diagnostic scan on a fixed set of liquid symbols (SPY, QQQ, AAPL).
    Returns step-by-step pipeline results for each symbol so you can see
    exactly where the scanner is dropping things.
    """
    state = _get_state(request)
    if not state.scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    DIAG_SYMBOLS = ["SPY", "QQQ", "AAPL"]
    results = []

    for sym in DIAG_SYMBOLS:
        entry = {"symbol": sym, "steps": {}}

        # Step 1: Asset discovery
        try:
            all_assets = await state.scanner.broker.get_tradable_assets(options_enabled=False)
            found = next((a for a in all_assets if a["symbol"] == sym), None)
            entry["steps"]["asset_discovery"] = {
                "found": found is not None,
                "tradable": found.get("tradable") if found else None,
                "options_enabled": found.get("options_enabled") if found else None,
                "asset_type": found.get("asset_type") if found else None,
            }
        except Exception as e:
            entry["steps"]["asset_discovery"] = {"error": str(e)}

        # Step 2: Historical bars (pre-filter input)
        try:
            bars = await state.scanner.broker.get_historical_bars(sym, "1Day", days_back=5)
            avg_vol = round(sum(b["volume"] for b in bars) / len(bars)) if bars else 0
            latest_close = bars[-1]["close"] if bars else 0
            entry["steps"]["pre_filter"] = {
                "bars_returned": len(bars),
                "avg_daily_volume": avg_vol,
                "latest_close": latest_close,
                "passes_volume": avg_vol >= state.scanner.min_daily_volume,
                "passes_price": state.scanner.min_price <= latest_close <= state.scanner.max_price,
            }
        except Exception as e:
            entry["steps"]["pre_filter"] = {"error": str(e)}

        # Step 3: IV rank
        try:
            iv_rank = await state.scanner.market_feed.get_iv_rank(sym)
            iv_series_len = len(state.scanner.market_feed._iv_history.get(sym, []))
            entry["steps"]["iv_rank"] = {
                "iv_rank": iv_rank,
                "iv_series_length": iv_series_len,
                "passes_threshold": iv_rank >= state.scanner.min_iv_rank or iv_rank == -1,
                "note": "IV rank -1 means insufficient history data" if iv_rank == -1 else None,
            }
        except Exception as e:
            entry["steps"]["iv_rank"] = {"error": str(e)}

        # Step 4: Liquidity score
        try:
            current_price = latest_close if "latest_close" in entry["steps"].get("pre_filter", {}) else 0
            if current_price <= 0:
                current_price = await state.scanner.market_feed.get_current_price(sym)
            liq = await state.scanner._calc_liquidity_score(sym, current_price)
            entry["steps"]["liquidity"] = {
                "score": liq,
                "passes_threshold": liq >= state.scanner.min_liquidity,
                "current_price_used": current_price,
            }
        except Exception as e:
            entry["steps"]["liquidity"] = {"error": str(e)}

        # Step 5: Composite score (if we have enough data)
        try:
            iv = entry["steps"].get("iv_rank", {}).get("iv_rank", -1)
            liq = entry["steps"].get("liquidity", {}).get("score", 0)
            if iv >= 0 and liq > 0:
                fake_opp = {
                    "symbol": sym,
                    "asset_type": entry["steps"].get("asset_discovery", {}).get("asset_type", "stock"),
                    "iv_rank": iv,
                    "momentum_30d": 0,
                    "distance_from_20ma": 0,
                    "options_liquidity_score": liq,
                    "near_support": False,
                }
                score = state.scanner._compute_composite_score(fake_opp)
                entry["steps"]["composite_score"] = {"score": round(score, 3)}
            else:
                entry["steps"]["composite_score"] = {"score": None, "reason": "IV or liquidity unavailable"}
        except Exception as e:
            entry["steps"]["composite_score"] = {"error": str(e)}

        results.append(entry)

    return {"diagnostic": results, "thresholds": {
        "min_iv_rank": state.scanner.min_iv_rank,
        "min_liquidity": state.scanner.min_liquidity,
        "min_daily_volume": state.scanner.min_daily_volume,
        "min_price": state.scanner.min_price,
        "max_price": state.scanner.max_price,
    }}

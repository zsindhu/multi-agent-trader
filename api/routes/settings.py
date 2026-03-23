"""
Settings Routes — Trading mode toggle and system configuration.

Allows switching between paper and live trading modes via the dashboard.
"""
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, field_validator
from loguru import logger

from api.state import AppState
from config.settings import settings

router = APIRouter()

ENV_PATH = Path(".env")


def _get_state(request: Request) -> AppState:
    return request.app.state.app


class TradingModeUpdate(BaseModel):
    trading_mode: str

    @field_validator("trading_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("paper", "live"):
            raise ValueError("trading_mode must be 'paper' or 'live'")
        return v


@router.get("/mode")
async def get_trading_mode(request: Request):
    """Return the current trading mode and base URL."""
    state = _get_state(request)
    current_mode = "paper" if state.broker_is_paper else "live"
    return {
        "trading_mode": current_mode,
        "base_url": settings.alpaca_base_url,
    }


@router.post("/mode")
async def set_trading_mode(request: Request, body: TradingModeUpdate):
    """
    Switch between paper and live trading.

    Updates the .env file, reconfigures settings, and reinitializes the
    broker + portfolio so that subsequent API calls use the correct account.
    """
    state = _get_state(request)
    new_mode = body.trading_mode
    current_mode = "paper" if state.broker_is_paper else "live"

    if new_mode == current_mode:
        return {"status": "no_change", "trading_mode": current_mode}

    # Update the in-memory settings
    new_base_url = (
        "https://paper-api.alpaca.markets"
        if new_mode == "paper"
        else "https://api.alpaca.markets"
    )
    settings.trading_mode = new_mode
    settings.alpaca_base_url = new_base_url

    # Persist to .env file so restarts keep the setting
    _update_env_file("TRADING_MODE", new_mode)
    _update_env_file("ALPACA_BASE_URL", new_base_url)

    # Reinitialize broker + portfolio with new credentials/endpoint
    try:
        await state.reinitialize_broker()
        logger.info(f"[Settings] Trading mode switched to {new_mode.upper()}")
    except Exception as e:
        logger.error(f"[Settings] Broker reinitialization failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reinitialize broker after mode switch: {e}",
        )

    return {
        "status": "switched",
        "trading_mode": new_mode,
        "base_url": new_base_url,
    }


def _update_env_file(key: str, value: str):
    """Update or add a key=value pair in the .env file."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n")
        return

    lines = ENV_PATH.read_text().splitlines()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")

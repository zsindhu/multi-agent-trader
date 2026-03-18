"""
Account Status Route — Alpaca connection health and options trading configuration.

GET /api/account/status returns everything needed to verify the paper account
is properly configured for options trading.
"""
from fastapi import APIRouter, Request
from loguru import logger

from api.state import AppState

router = APIRouter()


def _get_state(request: Request) -> AppState:
    return request.app.state.app


@router.get("/status")
async def get_account_status(request: Request):
    """
    Return Alpaca connection health and options trading configuration.

    Checks:
    - API key validity (connection ok/failed)
    - Account status (ACTIVE or other)
    - Options trading enabled and level
    - Paper vs live mode
    - Current equity, cash, buying power
    - Actionable warnings if anything is misconfigured
    """
    state = _get_state(request)

    result = {
        "connection": "failed",
        "account_status": None,
        "options_enabled": False,
        "options_level": None,
        "trading_mode": "paper" if state.broker_is_paper else "live",
        "equity": None,
        "cash": None,
        "buying_power": None,
        "warnings": [],
    }

    if not state.broker:
        result["warnings"].append("Broker not initialized — check API keys in .env")
        return result

    try:
        # Get raw account object from Alpaca SDK (not the broker's dict wrapper)
        raw_account = state.broker.trading.get_account()
        result["connection"] = "ok"

        account_status = str(getattr(raw_account, "status", "UNKNOWN")).split(".")[-1]
        result["account_status"] = account_status

        if account_status != "ACTIVE":
            result["warnings"].append(
                f"Account status is {account_status} (expected ACTIVE). "
                "Check your Alpaca dashboard."
            )

        # Options level: Alpaca uses options_approved_level (int 0-4)
        # Level 0 or None = not enabled
        # Level 1 = long options only
        # Level 2 = covered calls + cash-secured puts (required for this system)
        # Level 3 = spreads
        # Level 4 = naked options
        options_level_raw = getattr(raw_account, "options_approved_level", None)
        options_level = int(options_level_raw) if options_level_raw is not None else None
        result["options_level"] = options_level
        result["options_enabled"] = options_level is not None and options_level >= 2

        if options_level is None or options_level == 0:
            result["warnings"].append(
                "Options trading not enabled on this account. "
                "Go to Alpaca dashboard → Account → Configure → Enable options trading."
            )
        elif options_level == 1:
            result["warnings"].append(
                "Options level 1 — can only buy options, cannot sell puts. "
                "Upgrade to level 2 in Alpaca dashboard to sell covered calls and cash-secured puts."
            )

        # Financial data
        result["equity"] = float(getattr(raw_account, "equity", 0) or 0)
        result["cash"] = float(getattr(raw_account, "cash", 0) or 0)
        result["buying_power"] = float(getattr(raw_account, "buying_power", 0) or 0)

        # Buying power sanity check
        if result["buying_power"] == 0 and result["equity"] > 0:
            result["warnings"].append(
                "Buying power is $0 despite positive equity — "
                "account may have restrictions or pending margin calls."
            )

    except Exception as e:
        result["connection"] = "failed"
        error_msg = str(e)
        logger.error(f"[AccountStatus] Failed to fetch account: {error_msg}")

        if "forbidden" in error_msg.lower() or "401" in error_msg or "403" in error_msg:
            result["warnings"].append(
                "API credentials rejected — check ALPACA_API_KEY and ALPACA_SECRET_KEY in .env"
            )
        else:
            result["warnings"].append(f"Connection failed: {error_msg}")

    return result


@router.get("/orders")
async def get_alpaca_orders(request: Request, limit: int = 30):
    """
    Fetch recent orders from Alpaca — any status (open, filled, rejected, cancelled).

    Useful for diagnosing whether orders are reaching Alpaca and why they may be failing.
    """
    state = _get_state(request)
    if not state.broker:
        return []
    try:
        orders = await state.broker.get_orders(status="all")
        return orders[:limit]
    except Exception as e:
        logger.error(f"[AccountOrders] Failed to fetch orders: {e}")
        raise

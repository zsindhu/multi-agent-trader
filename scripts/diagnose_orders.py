"""
Order Execution Diagnostic — runs a full diagnostic of the order pipeline.

Usage:
    python scripts/diagnose_orders.py

Tests:
    1. Alpaca connection & account state
    2. Proposal pipeline (DB query)
    3. Capital feasibility check per proposal
    4. Test order submission (low limit price, immediately cancelled)
    5. Options trading permissions check
"""
import asyncio
import os
import sys
from datetime import datetime

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from sqlalchemy import select

# Silence loguru for cleaner output — we print our own results
logger.remove()


# ── ANSI colours ──────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET}  {msg}")
def info(msg): print(f"  {CYAN}·{RESET}  {msg}")


# ── Diagnostic results collector ─────────────────────────────────────
root_causes: list[str] = []
recommendations: list[str] = []


async def test1_account(broker) -> dict:
    """Test 1: Alpaca connection & account state."""
    print(f"\n{BOLD}Test 1: Alpaca Connection & Account State{RESET}")
    print("─" * 50)

    result = {
        "connected": False,
        "account_status": None,
        "equity": 0,
        "cash": 0,
        "buying_power": 0,
        "options_level": None,
        "positions": [],
        "recent_orders": [],
    }

    try:
        raw = broker.trading.get_account()
        result["connected"] = True

        status_str = str(getattr(raw, "status", "UNKNOWN")).split(".")[-1]
        result["account_status"] = status_str
        result["equity"] = float(getattr(raw, "equity", 0) or 0)
        result["cash"] = float(getattr(raw, "cash", 0) or 0)
        result["buying_power"] = float(getattr(raw, "buying_power", 0) or 0)

        options_level_raw = getattr(raw, "options_approved_level", None)
        result["options_level"] = int(options_level_raw) if options_level_raw is not None else None

        ok(f"Connected to Alpaca")
        info(f"Account status: {status_str}")
        info(f"Equity:         ${result['equity']:,.2f}")
        info(f"Cash:           ${result['cash']:,.2f}")
        info(f"Buying power:   ${result['buying_power']:,.2f}")

        if status_str != "ACTIVE":
            fail(f"Account status is {status_str} — not ACTIVE")
            root_causes.append(f"Account status is {status_str} (not ACTIVE)")

        if result["buying_power"] == 0:
            fail("Buying power is $0 — orders will be rejected for insufficient funds")
            root_causes.append("Buying power is $0")

    except Exception as e:
        fail(f"Connection failed: {e}")
        root_causes.append(f"Alpaca connection failed: {e}")
        return result

    # Positions
    try:
        positions = await broker.get_positions()
        result["positions"] = positions
        if positions:
            info(f"Open positions ({len(positions)}):")
            for p in positions:
                info(f"  {p['symbol']} — qty={p['qty']}, cost=${p['avg_cost']:.2f}, "
                     f"class={p['asset_class']}")
        else:
            info("No open positions")
    except Exception as e:
        warn(f"Could not fetch positions: {e}")

    # Recent orders
    try:
        orders = await broker.get_orders(status="all")
        recent = orders[:10]
        result["recent_orders"] = recent
        if recent:
            info(f"Recent orders (last {len(recent)}):")
            for o in recent:
                price_str = f"${o['limit_price']:.2f}" if o["limit_price"] else "MKT"
                filled_str = f", filled@${o['filled_avg_price']:.2f}" if o["filled_avg_price"] else ""
                info(f"  {o['symbol']} {o['side']} {o['qty']}x {price_str} — "
                     f"{o['status']}{filled_str}")
        else:
            info("No recent orders found")
    except Exception as e:
        warn(f"Could not fetch orders: {e}")

    return result


async def test2_proposals() -> dict:
    """Test 2: Check proposal pipeline."""
    print(f"\n{BOLD}Test 2: Proposal Pipeline{RESET}")
    print("─" * 50)

    from core.database import AsyncSessionLocal
    from models.proposal import TradeProposal

    result = {
        "total": 0,
        "by_status": {},
        "approved_never_executed": 0,
    }

    try:
        async with AsyncSessionLocal() as db:
            q = select(TradeProposal).order_by(TradeProposal.created_at.desc()).limit(10)
            rows = list((await db.execute(q)).scalars().all())

        result["total"] = len(rows)

        status_counts: dict[str, int] = {}
        approved_not_executed: list = []

        for p in rows:
            status_counts[p.status] = status_counts.get(p.status, 0) + 1
            if p.status == "approved" and not p.executed_at:
                approved_not_executed.append(p)

        result["by_status"] = status_counts
        result["approved_never_executed"] = len(approved_not_executed)

        if not rows:
            fail("No proposals in database — Lead Agent isn't generating proposals")
            root_causes.append("No proposals in database — Lead Agent hasn't run or scanner has no results")
            return result

        info(f"Found {len(rows)} recent proposals:")
        for status, count in sorted(status_counts.items()):
            info(f"  {status}: {count}")

        info("Most recent proposals:")
        for p in rows[:5]:
            coll_str = f"${p.collateral_required:,.0f}" if p.collateral_required else "—"
            info(
                f"  [{p.id}] {p.symbol} {p.agent_name} ${p.strike} "
                f"collateral={coll_str} status={p.status} "
                f"created={p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '?'}"
            )

        if approved_not_executed:
            fail(
                f"Found {len(approved_not_executed)} approved proposals that never executed "
                "— the execution pipeline is broken"
            )
            root_causes.append(
                f"{len(approved_not_executed)} approved proposals never executed — "
                "check lead_agent.py approve_proposal() method"
            )
            recommendations.append("Check lead_agent.py approve_proposal() method and worker.execute() call")
        else:
            ok("No stuck approved proposals")

    except Exception as e:
        fail(f"Database query failed: {e}")
        root_causes.append(f"Database error: {e}")

    return result


async def test3_feasibility(broker, proposals_result: dict, account_result: dict) -> dict:
    """Test 3: Capital feasibility check per proposal."""
    print(f"\n{BOLD}Test 3: Capital Feasibility Check{RESET}")
    print("─" * 50)

    from core.database import AsyncSessionLocal
    from models.proposal import TradeProposal

    result = {
        "feasible": 0,
        "infeasible": 0,
        "best_feasible": None,
    }

    buying_power = account_result.get("buying_power", 0)
    info(f"Available buying power: ${buying_power:,.2f}")

    if buying_power == 0:
        warn("Buying power is $0 — all proposals will be INFEASIBLE")

    try:
        async with AsyncSessionLocal() as db:
            q = (
                select(TradeProposal)
                .where(TradeProposal.status.in_(["pending", "approved"]))
                .order_by(TradeProposal.created_at.desc())
                .limit(20)
            )
            proposals = list((await db.execute(q)).scalars().all())

        if not proposals:
            info("No pending/approved proposals to check")
            return result

        feasible_proposals = []

        for p in proposals:
            collateral = p.collateral_required or 0

            # Basic feasibility: can we afford the collateral?
            feasible = buying_power == 0 or collateral <= buying_power

            if feasible:
                result["feasible"] += 1
                feasible_proposals.append(p)
                ok(
                    f"{p.symbol} ${p.strike}{'P' if p.contract_type == 'put' else 'C'} — "
                    f"collateral=${collateral:,.0f}, buying_power=${buying_power:,.0f} — FEASIBLE"
                )
            else:
                result["infeasible"] += 1
                fail(
                    f"{p.symbol} ${p.strike}{'P' if p.contract_type == 'put' else 'C'} — "
                    f"collateral=${collateral:,.0f} > buying_power=${buying_power:,.0f} — INFEASIBLE"
                )

        # Pick cheapest feasible for test order
        if feasible_proposals:
            result["best_feasible"] = min(
                feasible_proposals,
                key=lambda p: p.collateral_required or float("inf")
            )
            info(
                f"Best feasible proposal for test order: "
                f"{result['best_feasible'].symbol} "
                f"${result['best_feasible'].strike} "
                f"(collateral=${result['best_feasible'].collateral_required:,.0f})"
            )

        if result["infeasible"] > 0:
            root_causes.append(
                f"{result['infeasible']} proposals require more collateral than available buying power"
            )

    except Exception as e:
        fail(f"Feasibility check failed: {e}")

    return result


async def test4_test_order(broker, feasibility_result: dict, account_result: dict) -> dict:
    """Test 4: Try submitting a test order (below market, immediately cancelled)."""
    print(f"\n{BOLD}Test 4: Test Order Submission{RESET}")
    print("─" * 50)

    result = {
        "submitted": False,
        "order_id": None,
        "status": None,
        "error": None,
        "cancelled": False,
    }

    best = feasibility_result.get("best_feasible")

    if not best or not best.option_symbol:
        # Try to find any cheap optionable stock as fallback
        warn("No feasible proposal with option_symbol — looking for a fallback test symbol")
        info("Skipping test order (no option symbol available)")
        return result

    option_sym = best.option_symbol
    # Use a limit price well below market — should be accepted but never fill
    test_limit = 0.01

    info(f"Submitting test SELL order: {option_sym} @ ${test_limit:.2f} limit (below market)")
    info("(This will be immediately cancelled — we just want to see if Alpaca accepts it)")

    try:
        order = await broker.submit_option_order(
            option_symbol=option_sym,
            side="sell",
            qty=1,
            order_type="limit",
            limit_price=test_limit,
            time_in_force="day",
        )

        result["submitted"] = True
        result["order_id"] = order.get("order_id")
        result["status"] = order.get("status")

        ok(f"Order ACCEPTED — ID: {result['order_id']}, status: {result['status']}")

        # Immediately cancel
        if result["order_id"]:
            cancelled = await broker.cancel_order(result["order_id"])
            result["cancelled"] = cancelled
            if cancelled:
                ok(f"Test order cancelled successfully")
            else:
                warn("Could not cancel test order — check Alpaca dashboard")

    except Exception as e:
        result["error"] = str(e)
        fail(f"Order REJECTED: {e}")

        err_lower = str(e).lower()
        if "insufficient" in err_lower or "buying power" in err_lower:
            root_causes.append("Order rejected: insufficient buying power")
            recommendations.append("Fund your paper account or reduce position size")
        elif "options" in err_lower or "not approved" in err_lower:
            root_causes.append("Order rejected: options trading not approved on account")
            recommendations.append(
                "Enable options trading in Alpaca dashboard → Account → Configure"
            )
        elif "invalid" in err_lower or "not found" in err_lower:
            root_causes.append(f"Order rejected: invalid option symbol ({option_sym})")
            recommendations.append(
                "The option contract may have expired or been delisted — regenerate proposals"
            )
        else:
            root_causes.append(f"Order rejected: {e}")

    return result


def test5_options_permissions(account_result: dict) -> dict:
    """Test 5: Check options trading permissions."""
    print(f"\n{BOLD}Test 5: Options Trading Permissions{RESET}")
    print("─" * 50)

    result = {
        "options_level": account_result.get("options_level"),
        "can_sell_puts": False,
        "can_sell_calls": False,
    }

    level = result["options_level"]

    if level is None:
        fail("Options trading NOT enabled on this account")
        fail(
            "FIX: Go to Alpaca dashboard → Account → Configure → Enable options trading"
        )
        root_causes.append("Options trading not enabled on this Alpaca account")
        recommendations.append(
            "Enable options trading: Alpaca dashboard → Account → Configure → Enable options"
        )
    elif level == 0:
        fail("Options level 0 — options trading is disabled")
        root_causes.append("Options level 0 — options disabled")
    elif level == 1:
        warn("Options level 1 — can BUY options only, cannot SELL puts or calls")
        fail(
            "FIX: Upgrade to level 2 in Alpaca dashboard → Account → Configure"
        )
        root_causes.append("Options level 1 — cannot sell puts/calls (need level 2+)")
        recommendations.append(
            "Upgrade options level to 2: Alpaca dashboard → Account → Configure"
        )
    elif level >= 2:
        result["can_sell_puts"] = True
        result["can_sell_calls"] = True
        ok(f"Options level {level} — can sell covered calls and cash-secured puts ✓")
        if level >= 3:
            info(f"Level {level} also allows spreads")

    return result


async def run_diagnostic():
    """Run all 5 diagnostic tests and print summary."""
    from services.alpaca_broker import AlpacaBroker
    from config.settings import settings

    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  ORDER EXECUTION DIAGNOSTIC{RESET}")
    print(f"{BOLD}  Mode: {'PAPER' if settings.trading_mode == 'paper' else '⚠️  LIVE'}{RESET}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{BOLD}{'═' * 60}{RESET}")

    broker = AlpacaBroker()

    account_result    = await test1_account(broker)
    proposals_result  = await test2_proposals()
    feasibility_result = await test3_feasibility(broker, proposals_result, account_result)
    order_result      = await test4_test_order(broker, feasibility_result, account_result)
    permissions_result = test5_options_permissions(account_result)

    # ── SUMMARY ──────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  ORDER DIAGNOSTIC SUMMARY{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")

    acct_status = account_result.get("account_status") or "UNKNOWN"
    equity = account_result.get("equity", 0)
    bp = account_result.get("buying_power", 0)
    connected = account_result.get("connected", False)
    opts_level = permissions_result.get("options_level")

    conn_str = f"{GREEN}ok{RESET}" if connected else f"{RED}FAILED{RESET}"
    print(f"\nAccount:        {conn_str}, ${equity:,.0f} equity, ${bp:,.0f} buying power")
    print(f"Account status: {acct_status}")

    if opts_level is None:
        opts_str = f"{RED}NOT ENABLED{RESET}"
    elif opts_level < 2:
        opts_str = f"{YELLOW}Level {opts_level} (need 2+ to sell){RESET}"
    else:
        opts_str = f"{GREEN}Level {opts_level} (can sell puts and calls){RESET}"
    print(f"Options:        {opts_str}")

    total = proposals_result.get("total", 0)
    by_status = proposals_result.get("by_status", {})
    pending = by_status.get("pending", 0)
    stuck = proposals_result.get("approved_never_executed", 0)
    feasible = feasibility_result.get("feasible", 0)
    infeasible = feasibility_result.get("infeasible", 0)

    print(f"Proposals:      {total} total ({pending} pending, {stuck} approved-not-executed)")
    if total > 0:
        print(f"Feasibility:    {feasible} feasible, {infeasible} infeasible")

    if order_result.get("submitted"):
        order_id = order_result.get("order_id", "?")
        cancelled = "cancelled ✓" if order_result.get("cancelled") else "cancel FAILED"
        print(f"Test order:     {GREEN}ACCEPTED{RESET} (ID: {order_id}, {cancelled})")
    elif order_result.get("error"):
        print(f"Test order:     {RED}REJECTED{RESET} — {order_result['error']}")
    else:
        print(f"Test order:     {YELLOW}SKIPPED{RESET} (no option symbol available)")

    if root_causes:
        print(f"\n{RED}{BOLD}ROOT CAUSES FOUND:{RESET}")
        for cause in root_causes:
            print(f"  {RED}→{RESET} {cause}")
    else:
        print(f"\n{GREEN}{BOLD}No root causes found — pipeline looks healthy{RESET}")

    if recommendations:
        print(f"\n{YELLOW}{BOLD}RECOMMENDED FIXES:{RESET}")
        for rec in recommendations:
            print(f"  {YELLOW}→{RESET} {rec}")

    print(f"\n{BOLD}{'═' * 60}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_diagnostic())

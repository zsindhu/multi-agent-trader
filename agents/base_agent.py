"""
Base Agent — Abstract base class for all trading agents.
Every agent implements: scan() -> evaluate() -> execute() -> report()
"""
from abc import ABC, abstractmethod
from datetime import datetime
from loguru import logger


class BaseAgent(ABC):
    def __init__(self, name: str, agent_type: str):
        self.name = name
        self.agent_type = agent_type
        self.is_active = True
        self.last_run = None
        self.assigned_securities = []

    @abstractmethod
    async def scan(self) -> list[dict]:
        """Scan assigned securities for opportunities."""
        pass

    @abstractmethod
    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        """Evaluate and rank opportunities."""
        pass

    @abstractmethod
    async def execute(self, trades: list[dict]) -> list[dict]:
        """Execute approved trades via broker API."""
        pass

    @abstractmethod
    async def manage_positions(self) -> list[dict]:
        """Monitor and manage open positions."""
        pass

    async def report(self) -> dict:
        return {
            "agent": self.name,
            "type": self.agent_type,
            "last_run": self.last_run,
            "assigned": self.assigned_securities,
        }

    # ── Rationale Builders ────────────────────────────────────────

    @staticmethod
    def build_csp_rationale(symbol, strike, expiration, delta, dte, premium,
                            iv_rank, stock_price, annualized_return, qty=1) -> str:
        collateral = strike * 100 * abs(qty)
        break_even = strike - premium
        cushion_pct = ((stock_price - break_even) / stock_price * 100) if stock_price > 0 else 0
        pop = (1 - abs(delta)) * 100
        return (
            f"Sold {symbol} ${strike:.0f}P expiring {expiration} — "
            f"IV rank {iv_rank:.0f} (elevated), delta {delta:.2f} gives {pop:.0f}% PoP, "
            f"annualized return {annualized_return:.1f}% on ${collateral:,.0f} collateral. "
            f"Break-even ${break_even:.2f} ({cushion_pct:.1f}% below current ${stock_price:.2f})."
        )

    @staticmethod
    def build_cc_rationale(symbol, strike, expiration, delta, dte, premium,
                           iv_rank, stock_price, annualized_return, avg_cost,
                           downside_protection=0.0, qty=1) -> str:
        pop = (1 - abs(delta)) * 100
        return (
            f"Sold {symbol} ${strike:.0f}C expiring {expiration} — "
            f"stock held at ${avg_cost:.2f}, IV rank {iv_rank:.0f}, "
            f"delta {delta:.2f} gives {pop:.0f}% probability of keeping shares, "
            f"premium ${premium:.2f}/share ({annualized_return:.1f}% annualized). "
            f"Stock can rise {downside_protection:.1f}% before called away."
        )

    @staticmethod
    def build_wheel_rationale(symbol, strike, expiration, contract_type, delta, dte,
                               premium, iv_rank, stock_price, annualized_return,
                               wheel_state, qty=1, effective_cost=None) -> str:
        pop = (1 - abs(delta)) * 100
        phase = wheel_state.replace("_", " ").title()
        if contract_type == "call" and effective_cost:
            return (
                f"Wheel [{phase}]: Sold {symbol} ${strike:.0f}C expiring {expiration} — "
                f"shares at effective cost ${effective_cost:.2f} after accumulated premium. "
                f"Premium ${premium:.2f}/share ({annualized_return:.1f}% annualized), "
                f"{dte}d DTE, {pop:.0f}% PoP."
            )
        return (
            f"Wheel [{phase}]: Sold {symbol} ${strike:.0f}P expiring {expiration} — "
            f"IV rank {iv_rank:.0f}, delta {delta:.2f} gives {pop:.0f}% PoP, "
            f"annualized return {annualized_return:.1f}%, {dte}d DTE."
        )

    async def run_cycle(self):
        """Execute one full agent cycle."""
        logger.info(f"[{self.name}] Starting cycle...")
        self.last_run = datetime.utcnow()
        position_actions = await self.manage_positions()
        opportunities = await self.scan()
        trades = await self.evaluate(opportunities)
        results = await self.execute(trades)
        report = await self.report()
        logger.info(f"[{self.name}] Cycle complete. {len(results)} trades executed.")
        return {"position_actions": position_actions, "new_trades": results, "report": report}

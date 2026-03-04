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

"""
Worker C — The Wheel (state machine):
  SELLING_PUTS -> ASSIGNED -> SELLING_CALLS -> CALLED_AWAY -> repeat
"""
from enum import Enum
from .base_agent import BaseAgent
from loguru import logger


class WheelState(Enum):
    SELLING_PUTS = "selling_puts"
    ASSIGNED = "assigned"
    SELLING_CALLS = "selling_calls"
    CALLED_AWAY = "called_away"


class WheelWorker(BaseAgent):
    def __init__(self):
        super().__init__(name="Worker-C-Wheel", agent_type="wheel")
        self.wheel_states: dict[str, WheelState] = {}
        self.cost_basis: dict[str, float] = {}

    async def scan(self) -> list[dict]:
        opportunities = []
        for symbol in self.assigned_securities:
            state = self.wheel_states.get(symbol, WheelState.SELLING_PUTS)
            logger.info(f"[{self.name}] {symbol} in state: {state.value}")
            if state == WheelState.SELLING_PUTS:
                pass  # TODO: Scan for CSP entry
            elif state == WheelState.SELLING_CALLS:
                pass  # TODO: Scan for CC entry
            elif state == WheelState.ASSIGNED:
                self.wheel_states[symbol] = WheelState.SELLING_CALLS
            elif state == WheelState.CALLED_AWAY:
                self.wheel_states[symbol] = WheelState.SELLING_PUTS
        return opportunities

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        return opportunities

    async def execute(self, trades: list[dict]) -> list[dict]:
        results = []
        for trade in trades:
            logger.info(f"[{self.name}] Executing wheel trade: {trade}")
        return results

    async def manage_positions(self) -> list[dict]:
        # TODO: Detect assignment/called-away, track cost basis reduction
        return []

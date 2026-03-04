"""Portfolio state management — tracks positions, cash, options."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    assigned_to: str = ""


@dataclass
class OptionsPosition:
    symbol: str
    option_symbol: str
    contract_type: str  # "call" or "put"
    strike: float
    expiration: str
    quantity: int
    premium_collected: float
    current_price: float = 0.0
    assigned_to: str = ""


@dataclass
class Portfolio:
    cash: float = 0.0
    buying_power: float = 0.0
    equity: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    options: list[OptionsPosition] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_value(self) -> float:
        stock_value = sum(p.quantity * p.current_price for p in self.positions.values())
        return self.cash + stock_value

    @property
    def total_premium_collected(self) -> float:
        return sum(o.premium_collected for o in self.options)

    def get_positions_for_agent(self, agent_name: str) -> list:
        return [p for p in self.positions.values() if p.assigned_to == agent_name]

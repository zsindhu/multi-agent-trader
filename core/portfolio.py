"""
Portfolio State Management — Tracks positions, cash, options, and syncs from broker.

The Portfolio is the single source of truth for the current account state.
It's synced from the broker at the start of each cycle.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger


@dataclass
class Position:
    """Stock position (100+ shares)."""
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    assigned_to: str = ""  # Which agent owns this position


@dataclass
class OptionsPosition:
    """Open option contract position."""
    symbol: str              # Underlying symbol (e.g. "AAPL")
    option_symbol: str       # OCC symbol (e.g. "AAPL240119P00150000")
    contract_type: str       # "call" or "put"
    strike: float
    expiration: str
    quantity: int            # Positive = long, negative = short
    entry_price: float       # Price per contract at entry
    current_price: float = 0.0
    premium_collected: float = 0.0
    assigned_to: str = ""    # Which agent owns this position

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def pnl(self) -> float:
        """Unrealized P&L. For short options: positive when price drops."""
        if self.is_short:
            return (self.entry_price - self.current_price) * abs(self.quantity) * 100
        return (self.current_price - self.entry_price) * self.quantity * 100

    @property
    def pnl_pct(self) -> float:
        """P&L as a percentage of premium collected."""
        if self.premium_collected > 0:
            return (self.pnl / (self.premium_collected * 100)) * 100
        return 0.0


@dataclass
class Portfolio:
    """
    Complete portfolio state — synced from broker each cycle.

    Tracks:
    - Account balances (cash, buying power, equity)
    - Stock positions
    - Option positions
    - Agent assignments
    """
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

    # ── Sync from Broker ──────────────────────────────────────────

    async def sync_from_broker(self, broker) -> None:
        """
        Pull latest account state and positions from the broker.
        Called at the start of each orchestration cycle.
        """
        try:
            # Sync account info
            account = await broker.get_account()
            self.cash = account["cash"]
            self.buying_power = account["buying_power"]
            self.equity = account["equity"]

            # Sync positions
            raw_positions = await broker.get_positions()

            # Preserve agent assignments from existing positions
            old_assignments = {s: p.assigned_to for s, p in self.positions.items()}
            old_option_assignments = {o.option_symbol: o.assigned_to for o in self.options}

            # Rebuild positions
            new_positions: dict[str, Position] = {}
            new_options: list[OptionsPosition] = []

            for pos in raw_positions:
                symbol = pos["symbol"]
                asset_class = pos.get("asset_class", "us_equity")

                if "option" in asset_class.lower() or len(symbol) > 10:
                    # This is an option position
                    # Parse underlying from option symbol (simplified)
                    underlying = self._parse_underlying(symbol)
                    opt = OptionsPosition(
                        symbol=underlying,
                        option_symbol=symbol,
                        contract_type=self._parse_contract_type(symbol),
                        strike=0.0,  # Would need to parse from OCC symbol
                        expiration="",
                        quantity=pos["qty"],
                        entry_price=pos["avg_cost"],
                        current_price=pos["current_price"],
                        assigned_to=old_option_assignments.get(symbol, ""),
                    )
                    new_options.append(opt)
                else:
                    # Stock position
                    new_positions[symbol] = Position(
                        symbol=symbol,
                        quantity=pos["qty"],
                        avg_cost=pos["avg_cost"],
                        current_price=pos["current_price"],
                        unrealized_pnl=pos.get("unrealized_pl", 0.0),
                        assigned_to=old_assignments.get(symbol, ""),
                    )

            self.positions = new_positions
            self.options = new_options
            self.last_updated = datetime.utcnow()

            logger.info(
                f"[Portfolio] Synced: ${self.equity:,.2f} equity, "
                f"{len(self.positions)} stocks, {len(self.options)} options"
            )

        except Exception as e:
            logger.error(f"[Portfolio] Sync failed: {e}")

    # ── Query Methods ─────────────────────────────────────────────

    def get_positions_for_agent(self, agent_name: str) -> list[Position]:
        """Get all stock positions assigned to a specific agent."""
        return [p for p in self.positions.values() if p.assigned_to == agent_name]

    def get_options_for_agent(self, agent_name: str) -> list[OptionsPosition]:
        """Get all option positions assigned to a specific agent."""
        return [o for o in self.options if o.assigned_to == agent_name]

    def get_shares_for_symbol(self, symbol: str) -> int:
        """Get total shares held for a symbol."""
        pos = self.positions.get(symbol)
        return pos.quantity if pos else 0

    def get_shares_committed_to_calls(self, symbol: str) -> int:
        """
        Get shares committed to existing short call positions.
        Each short call contract commits 100 shares.
        """
        committed = 0
        for opt in self.options:
            if opt.symbol == symbol and opt.contract_type == "call" and opt.is_short:
                committed += abs(opt.quantity) * 100
        return committed

    def get_available_shares(self, symbol: str) -> int:
        """Get shares available (not committed to calls) for a symbol."""
        total = self.get_shares_for_symbol(symbol)
        committed = self.get_shares_committed_to_calls(symbol)
        return max(0, total - committed)

    def count_open_options_for_agent(self, agent_name: str) -> int:
        """Count how many open option positions an agent has."""
        return len(self.get_options_for_agent(agent_name))

    def has_open_option(self, option_symbol: str) -> bool:
        """Check if we already have an open position for this option symbol."""
        return any(o.option_symbol == option_symbol for o in self.options)

    def get_symbols_with_shares(self, min_shares: int = 100) -> list[str]:
        """Get symbols where we hold at least min_shares (for covered calls)."""
        return [
            sym for sym, pos in self.positions.items()
            if pos.quantity >= min_shares
        ]

    def assign_position(self, symbol: str, agent_name: str):
        """Assign a stock position to an agent."""
        if symbol in self.positions:
            self.positions[symbol].assigned_to = agent_name

    def assign_option(self, option_symbol: str, agent_name: str):
        """Assign an option position to an agent."""
        for opt in self.options:
            if opt.option_symbol == option_symbol:
                opt.assigned_to = agent_name
                break

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_underlying(option_symbol: str) -> str:
        """Parse underlying symbol from OCC option symbol (e.g. AAPL240119P00150000 -> AAPL)."""
        # OCC format: SYMBOLYYMMDDTSSSSSSSS (T=C/P, S=strike*1000)
        # Find where the date digits start
        for i, c in enumerate(option_symbol):
            if c.isdigit():
                return option_symbol[:i]
        return option_symbol[:4]  # Fallback

    @staticmethod
    def _parse_contract_type(option_symbol: str) -> str:
        """Parse contract type from OCC option symbol."""
        # Find C or P after the date portion
        for c in option_symbol:
            if c == 'C':
                return "call"
            elif c == 'P':
                return "put"
        return "unknown"

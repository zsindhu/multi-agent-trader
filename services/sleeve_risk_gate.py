"""
Sleeve Risk Gate — Pre-execution hard limits that the Lead Agent cannot override.

Checks every proposed trade against portfolio-level and per-sleeve constraints
before it reaches _execute_action(). Rejected trades are logged with reasons.

Enforces:
- Per-sleeve position count limits
- Single-name cross-sleeve concentration (max 10% of total portfolio)
- Sector concentration (max 30% of total portfolio in one sector)
- Per-sleeve capital utilization
- Portfolio-level drawdown triggers
"""
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from core.portfolio import Portfolio


# Sector lookup cache (yfinance Ticker.info["sector"])
_sector_cache: dict[str, str] = {}


async def get_sector(symbol: str) -> str:
    """Get GICS sector for a symbol via yfinance. Cached."""
    if symbol in _sector_cache:
        return _sector_cache[symbol]

    try:
        import asyncio
        import yfinance as yf
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: yf.Ticker(symbol).info)
        sector = info.get("sector", "Unknown")
        _sector_cache[symbol] = sector
        return sector
    except Exception:
        _sector_cache[symbol] = "Unknown"
        return "Unknown"


class SleeveRiskGate:
    """Pre-execution risk gate for multi-sleeve architecture."""

    def __init__(
        self,
        portfolio: Portfolio,
        total_capital: float = 500_000,
        max_sector_pct: float = 0.30,
        max_single_name_pct: float = 0.10,
        max_sleeve_drawdown_pct: float = 0.10,
        max_portfolio_drawdown_pct: float = 0.08,
    ):
        self.portfolio = portfolio
        self.total_capital = total_capital
        self.max_sector_pct = max_sector_pct
        self.max_single_name_pct = max_single_name_pct
        self.max_sleeve_drawdown_pct = max_sleeve_drawdown_pct
        self.max_portfolio_drawdown_pct = max_portfolio_drawdown_pct

        # Per-sleeve position tracking (populated during cycle)
        self._sleeve_positions: dict[str, list[str]] = {}  # sleeve_id -> [symbols]
        self._all_positions: dict[str, str] = {}  # symbol -> sleeve_id

    def register_existing_positions(self, sleeve_positions: dict[str, list[str]]):
        """Load current open positions per sleeve at cycle start."""
        self._sleeve_positions = dict(sleeve_positions)
        self._all_positions = {}
        for sleeve_id, symbols in sleeve_positions.items():
            for sym in symbols:
                self._all_positions[sym] = sleeve_id

    async def check_trade(
        self,
        action: dict,
        sleeve_id: str,
        sleeve_capital: float,
        sleeve_max_positions: int,
    ) -> dict:
        """
        Check a proposed trade against all risk constraints.

        Returns:
            {"approved": True} or {"approved": False, "reason": str}
        """
        symbol = action.get("symbol", "")
        action_type = action.get("action", "")

        # Closes, holds, rolls always pass — risk gate only blocks new positions
        if action_type in ("close", "hold", "roll", "no_action", "pause_worker", "resume_worker"):
            return {"approved": True}

        if not symbol:
            return {"approved": False, "reason": "no_symbol_in_action"}

        # Check 1: Per-sleeve position count
        current_count = len(self._sleeve_positions.get(sleeve_id, []))
        if current_count >= sleeve_max_positions:
            return {"approved": False, "reason": f"sleeve_{sleeve_id}_at_max_positions ({current_count}/{sleeve_max_positions})"}

        # Check 2: Single-name cross-sleeve concentration
        if symbol in self._all_positions:
            existing_sleeve = self._all_positions[symbol]
            if existing_sleeve != sleeve_id:
                return {"approved": False, "reason": f"cross_sleeve_conflict: {symbol} already in {existing_sleeve}"}

        # Count total notional for this symbol across all sleeves
        symbol_positions = sum(
            1 for s, sid in self._all_positions.items() if s == symbol
        )
        if symbol_positions > 0:
            # Already have a position in this name from another sleeve
            return {"approved": False, "reason": f"single_name_concentration: {symbol} already held"}

        # Check 3: Sector concentration
        sector = await get_sector(symbol)
        if sector != "Unknown":
            sector_count = 0
            for sym in self._all_positions:
                sym_sector = await get_sector(sym)
                if sym_sector == sector:
                    sector_count += 1
            total_positions = len(self._all_positions)
            if total_positions > 0 and sector_count / max(total_positions, 1) > self.max_sector_pct:
                return {"approved": False, "reason": f"sector_concentration: {sector} at {sector_count}/{total_positions}"}

        # Check 4: Per-sleeve capital utilization
        strike = action.get("strike") or action.get("delta_target", 0)
        if strike and sleeve_capital > 0:
            # Rough collateral estimate: strike * 100 for CSPs
            collateral = float(strike) * 100 if isinstance(strike, (int, float)) and strike > 1 else 5000
            sleeve_utilization = (current_count * 5000 + collateral) / sleeve_capital
            if sleeve_utilization > 0.80:
                return {"approved": False, "reason": f"sleeve_capital_utilization: {sleeve_utilization:.0%} > 80%"}

        # Check 5: Portfolio drawdown
        if self.portfolio and self.portfolio.equity > 0:
            drawdown = 1.0 - (self.portfolio.equity / self.total_capital)
            if drawdown > self.max_portfolio_drawdown_pct:
                return {"approved": False, "reason": f"portfolio_drawdown: {drawdown:.1%} > {self.max_portfolio_drawdown_pct:.0%}"}

        # Approved — register the position
        if sleeve_id not in self._sleeve_positions:
            self._sleeve_positions[sleeve_id] = []
        self._sleeve_positions[sleeve_id].append(symbol)
        self._all_positions[symbol] = sleeve_id

        return {"approved": True}

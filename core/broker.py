"""
Broker Abstraction Layer — Abstract interface for brokerage operations.

All agents and services use the Broker interface, never broker-specific implementations.
This allows swapping brokers (Alpaca, Interactive Brokers, etc.) without touching agent code.

See ADR-006 for architecture decision.
"""
from abc import ABC, abstractmethod
from typing import Optional


class Broker(ABC):
    """
    Abstract Broker interface for options trading operations.
    
    All methods are async and return standardized dict/list[dict] formats.
    Implementations handle broker-specific API calls and data transformations.
    """

    @abstractmethod
    async def get_account(self) -> dict:
        """
        Fetch current account info.
        
        Returns:
            Dict with keys: cash, buying_power, equity, portfolio_value
        """
        pass

    @abstractmethod
    async def get_positions(self) -> list[dict]:
        """
        Fetch all open positions (stocks + options).
        
        Returns:
            List of dicts with keys: symbol, qty, avg_cost, current_price, 
            unrealized_pl, asset_class, side
        """
        pass

    @abstractmethod
    async def get_options_chain(
        self,
        symbol: str,
        expiration_date_gte: Optional[str] = None,
        expiration_date_lte: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Fetch full options chain for a symbol with greeks and quotes.
        
        Args:
            symbol: Underlying stock ticker (e.g. "AAPL")
            expiration_date_gte: Minimum expiration date (YYYY-MM-DD)
            expiration_date_lte: Maximum expiration date (YYYY-MM-DD)
            contract_type: "call" or "put" (optional filter)
        
        Returns:
            List of dicts with keys: symbol, option_symbol, strike, expiration,
            contract_type, bid, ask, last, volume, open_interest,
            implied_volatility, delta, gamma, theta, vega, mid_price
        """
        pass

    @abstractmethod
    async def submit_option_order(
        self,
        option_symbol: str,
        side: str,
        qty: int,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> dict:
        """
        Submit an options order (sell to open, buy to close, etc.).
        
        Args:
            option_symbol: OCC option symbol (e.g. "AAPL240119P00150000")
            side: "buy" or "sell"
            qty: Number of contracts
            order_type: "limit" or "market"
            limit_price: Required for limit orders
            time_in_force: "day", "gtc", "ioc"
        
        Returns:
            Dict with keys: order_id, symbol, side, qty, type, limit_price,
            status, submitted_at
        """
        pass

    @abstractmethod
    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        days_back: int = 60,
    ) -> list[dict]:
        """
        Fetch historical OHLCV bars for a stock symbol.
        
        Args:
            symbol: Stock ticker (e.g. "AAPL")
            timeframe: "1Min", "5Min", "15Min", "1Hour", "1Day"
            days_back: Number of calendar days to look back
        
        Returns:
            List of dicts with keys: timestamp, open, high, low, close, volume, vwap
        """
        pass

    @abstractmethod
    async def get_latest_quote(self, symbol: str) -> dict:
        """
        Fetch the latest stock quote for a symbol.
        
        Args:
            symbol: Stock ticker (e.g. "AAPL")
        
        Returns:
            Dict with keys: symbol, bid, ask, bid_size, ask_size, timestamp
        """
        pass

    @abstractmethod
    async def get_orders(self, status: str = "open") -> list[dict]:
        """
        Fetch orders by status.
        
        Args:
            status: "open", "closed", or "all"
        
        Returns:
            List of dicts with keys: order_id, symbol, side, qty, type, status,
            limit_price, filled_avg_price, submitted_at
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order by ID.
        
        Args:
            order_id: Order identifier
        
        Returns:
            True if successful, False otherwise
        """
        pass

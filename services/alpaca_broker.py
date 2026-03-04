"""
Alpaca Broker — Alpaca implementation of the Broker interface.

Moves all Alpaca-specific logic from alpaca_client.py into a Broker implementation.
Uses alpaca-py (modern SDK) for all API calls.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)
from alpaca.trading.enums import (
    AssetClass,
    AssetStatus,
    ContractType,
    OrderSide,
    OrderType,
    TimeInForce,
    QueryOrderStatus,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    OptionSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame
from loguru import logger

from config.settings import settings
from core.broker import Broker


class RateLimiter:
    """Simple async rate limiter for API calls."""

    def __init__(self, max_calls: int = 200, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            # Remove expired timestamps
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                sleep_time = self.period - (now - self._calls[0])
                logger.debug(f"Rate limit reached. Sleeping {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
            self._calls.append(asyncio.get_event_loop().time())


class AlpacaBroker(Broker):
    """
    Alpaca implementation of the Broker interface.
    
    Handles all Alpaca-specific API calls and data transformations.
    """

    def __init__(self):
        self.trading = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.trading_mode == "paper",
        )
        self.stock_data = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self.option_data = OptionHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self._rate_limiter = RateLimiter(max_calls=200, period=60.0)

    # ── Account & Positions ───────────────────────────────────────────

    async def get_account(self) -> dict:
        """Fetch current account info (cash, equity, buying power)."""
        await self._rate_limiter.acquire()
        try:
            account = self.trading.get_account()
            return {
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "equity": float(account.equity),
                "portfolio_value": float(account.portfolio_value),
            }
        except Exception as e:
            logger.error(f"Failed to fetch account: {e}")
            raise

    async def get_positions(self) -> list[dict]:
        """Fetch all open positions (stocks + options)."""
        await self._rate_limiter.acquire()
        try:
            positions = self.trading.get_all_positions()
            return [
                {
                    "symbol": p.symbol,
                    "qty": int(p.qty),
                    "avg_cost": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "unrealized_pl": float(p.unrealized_pl),
                    "asset_class": str(getattr(p, "asset_class", "us_equity")),
                    "side": str(p.side),
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            raise

    # ── Options Chain ─────────────────────────────────────────────────

    async def get_options_chain(
        self,
        symbol: str,
        expiration_date_gte: Optional[str] = None,
        expiration_date_lte: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Fetch full options chain for a symbol with greeks and quotes.
        
        Returns list of dicts with: symbol, strike, expiration, contract_type,
        bid, ask, last, volume, open_interest, implied_volatility,
        delta, gamma, theta, vega
        """
        await self._rate_limiter.acquire()

        if not expiration_date_gte:
            expiration_date_gte = datetime.now().strftime("%Y-%m-%d")
        if not expiration_date_lte:
            expiration_date_lte = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        try:
            # Step 1: Get option contracts from the Trading API
            request_params = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                status=AssetStatus.ACTIVE,
                expiration_date_gte=expiration_date_gte,
                expiration_date_lte=expiration_date_lte,
            )
            if contract_type:
                request_params.type = (
                    ContractType.CALL if contract_type.lower() == "call" else ContractType.PUT
                )

            contracts_response = self.trading.get_option_contracts(request_params)
            contracts = contracts_response.option_contracts if contracts_response else []

            if not contracts:
                logger.warning(f"No option contracts found for {symbol}")
                return []

            logger.info(f"Found {len(contracts)} contracts for {symbol}")

            # Step 2: Get snapshots with greeks from the Option Data API
            contract_symbols = [c.symbol for c in contracts]
            chain_data = await self._get_option_snapshots_batched(contract_symbols)

            # Step 3: Merge contract metadata with snapshot data
            result = []
            for contract in contracts:
                snap = chain_data.get(contract.symbol, {})
                result.append({
                    "symbol": symbol,
                    "option_symbol": contract.symbol,
                    "strike": float(contract.strike_price),
                    "expiration": str(contract.expiration_date),
                    "contract_type": str(contract.type).split(".")[-1].lower(),
                    "bid": snap.get("bid", 0.0),
                    "ask": snap.get("ask", 0.0),
                    "last": snap.get("last", 0.0),
                    "volume": snap.get("volume", 0),
                    "open_interest": int(contract.open_interest) if contract.open_interest else 0,
                    "implied_volatility": snap.get("implied_volatility", 0.0),
                    "delta": snap.get("delta", 0.0),
                    "gamma": snap.get("gamma", 0.0),
                    "theta": snap.get("theta", 0.0),
                    "vega": snap.get("vega", 0.0),
                    "mid_price": snap.get("mid_price", 0.0),
                })

            return result

        except Exception as e:
            logger.error(f"Failed to fetch options chain for {symbol}: {e}")
            raise

    async def _get_option_snapshots_batched(
        self, symbols: list[str], batch_size: int = 100
    ) -> dict:
        """Fetch option snapshots in batches to stay within API limits."""
        all_snapshots = {}

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            await self._rate_limiter.acquire()

            try:
                request = OptionSnapshotRequest(symbol_or_symbols=batch)
                snapshots = self.option_data.get_option_snapshot(request)

                for sym, snap in snapshots.items():
                    greeks = snap.greeks if hasattr(snap, "greeks") and snap.greeks else None
                    quote = snap.latest_quote if hasattr(snap, "latest_quote") and snap.latest_quote else None
                    trade = snap.latest_trade if hasattr(snap, "latest_trade") and snap.latest_trade else None

                    all_snapshots[sym] = {
                        "bid": float(quote.bid_price) if quote and quote.bid_price else 0.0,
                        "ask": float(quote.ask_price) if quote and quote.ask_price else 0.0,
                        "last": float(trade.price) if trade and trade.price else 0.0,
                        "volume": int(snap.daily_bar.volume) if hasattr(snap, "daily_bar") and snap.daily_bar else 0,
                        "implied_volatility": float(snap.implied_volatility) if hasattr(snap, "implied_volatility") and snap.implied_volatility else 0.0,
                        "delta": float(greeks.delta) if greeks and greeks.delta else 0.0,
                        "gamma": float(greeks.gamma) if greeks and greeks.gamma else 0.0,
                        "theta": float(greeks.theta) if greeks and greeks.theta else 0.0,
                        "vega": float(greeks.vega) if greeks and greeks.vega else 0.0,
                        "mid_price": (
                            (float(quote.bid_price) + float(quote.ask_price)) / 2
                            if quote and quote.bid_price and quote.ask_price
                            else 0.0
                        ),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch snapshots for batch starting at {i}: {e}")

        return all_snapshots

    # ── Order Submission ──────────────────────────────────────────────

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
            Dict with order details
        """
        await self._rate_limiter.acquire()

        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif_map = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
            "ioc": TimeInForce.IOC,
        }
        tif = tif_map.get(time_in_force.lower(), TimeInForce.DAY)

        try:
            if order_type.lower() == "limit" and limit_price is not None:
                order_data = LimitOrderRequest(
                    symbol=option_symbol,
                    qty=qty,
                    side=order_side,
                    type=OrderType.LIMIT,
                    time_in_force=tif,
                    limit_price=round(limit_price, 2),
                )
            else:
                order_data = MarketOrderRequest(
                    symbol=option_symbol,
                    qty=qty,
                    side=order_side,
                    type=OrderType.MARKET,
                    time_in_force=tif,
                )

            order = self.trading.submit_order(order_data)
            logger.info(
                f"Order submitted: {side.upper()} {qty}x {option_symbol} "
                f"@ {'$' + str(limit_price) if limit_price else 'MKT'} — ID: {order.id}"
            )

            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "side": str(order.side),
                "qty": int(order.qty),
                "type": str(order.type),
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "status": str(order.status),
                "submitted_at": str(order.submitted_at),
            }

        except Exception as e:
            logger.error(f"Order submission failed for {option_symbol}: {e}")
            raise

    # ── Historical Data ───────────────────────────────────────────────

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
            List of dicts with: timestamp, open, high, low, close, volume
        """
        await self._rate_limiter.acquire()

        tf_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, "Min"),
            "15Min": TimeFrame(15, "Min"),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)
        start = datetime.now() - timedelta(days=days_back)

        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
            )
            bars_set = self.stock_data.get_stock_bars(request)
            bars = bars_set[symbol] if symbol in bars_set else []

            return [
                {
                    "timestamp": str(bar.timestamp),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume),
                    "vwap": float(bar.vwap) if hasattr(bar, "vwap") and bar.vwap else None,
                }
                for bar in bars
            ]

        except Exception as e:
            logger.error(f"Failed to fetch historical bars for {symbol}: {e}")
            raise

    # ── Latest Quote ──────────────────────────────────────────────────

    async def get_latest_quote(self, symbol: str) -> dict:
        """Fetch the latest stock quote for a symbol."""
        await self._rate_limiter.acquire()
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.stock_data.get_stock_latest_quote(request)
            quote = quotes.get(symbol)
            if not quote:
                return {}
            return {
                "symbol": symbol,
                "bid": float(quote.bid_price) if quote.bid_price else 0.0,
                "ask": float(quote.ask_price) if quote.ask_price else 0.0,
                "bid_size": int(quote.bid_size) if quote.bid_size else 0,
                "ask_size": int(quote.ask_size) if quote.ask_size else 0,
                "timestamp": str(quote.timestamp),
            }
        except Exception as e:
            logger.error(f"Failed to fetch latest quote for {symbol}: {e}")
            raise

    # ── Order Management ──────────────────────────────────────────────

    async def get_orders(self, status: str = "open") -> list[dict]:
        """Fetch orders by status (open, closed, all)."""
        await self._rate_limiter.acquire()
        try:
            status_map = {
                "open": QueryOrderStatus.OPEN,
                "closed": QueryOrderStatus.CLOSED,
                "all": QueryOrderStatus.ALL,
            }
            orders = self.trading.get_orders(
                filter=status_map.get(status, QueryOrderStatus.OPEN)
            )
            return [
                {
                    "order_id": str(o.id),
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": int(o.qty),
                    "type": str(o.type),
                    "status": str(o.status),
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                    "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                    "submitted_at": str(o.submitted_at),
                }
                for o in orders
            ]
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID."""
        await self._rate_limiter.acquire()
        try:
            self.trading.cancel_order_by_id(order_id)
            logger.info(f"Order {order_id} cancelled.")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    # ── Asset Discovery ───────────────────────────────────────────────

    async def get_tradable_assets(self, options_enabled: bool = True) -> list[dict]:
        """
        Fetch all tradable US equity assets from Alpaca.

        Filters by status=ACTIVE and asset_class=US_EQUITY, then optionally
        keeps only those with options support via the 'attributes' field.

        Alpaca marks options-eligible assets with 'options_enabled' in the
        attributes list on the Asset object.
        """
        await self._rate_limiter.acquire()
        try:
            from alpaca.trading.requests import GetAssetsRequest

            request = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=AssetClass.US_EQUITY,
            )
            # Pass attributes filter for options_enabled if supported
            if options_enabled:
                request.attributes = "options_enabled"

            assets = self.trading.get_all_assets(request)

            results = []
            for a in assets:
                if not a.tradable:
                    continue

                # Determine asset type: ETF vs stock
                # Alpaca doesn't have a dedicated "etf" asset_class — ETFs
                # appear under us_equity. We classify by exchange:
                # ARCA / BATS / NYSEARCA are common ETF exchanges.
                etf_exchanges = {"ARCA", "BATS", "NYSEARCA"}
                exchange_str = str(a.exchange) if a.exchange else ""
                # Strip enum prefix if present (e.g. "AssetExchange.ARCA" → "ARCA")
                exchange_clean = exchange_str.split(".")[-1] if "." in exchange_str else exchange_str

                asset_type = "etf" if exchange_clean in etf_exchanges else "stock"

                has_options = False
                if a.attributes:
                    has_options = "options_enabled" in a.attributes

                if options_enabled and not has_options:
                    continue

                results.append({
                    "symbol": a.symbol,
                    "name": a.name or "",
                    "asset_type": asset_type,
                    "tradable": a.tradable,
                    "options_enabled": has_options,
                    "exchange": exchange_clean,
                })

            logger.info(
                f"Fetched {len(results)} tradable assets "
                f"({'options-enabled only' if options_enabled else 'all'})"
            )
            return results

        except Exception as e:
            logger.error(f"Failed to fetch tradable assets: {e}")
            raise

    # ── Batch Historical Bars ─────────────────────────────────────────

    async def get_historical_bars_batch(
        self,
        symbols: list[str],
        timeframe: str = "1Day",
        days_back: int = 5,
    ) -> dict[str, list[dict]]:
        """
        Fetch historical bars for multiple symbols in one API call.

        Alpaca's StockBarsRequest natively supports a list of symbols.
        We batch in groups of 200 to stay within API limits.
        """
        tf_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, "Min"),
            "15Min": TimeFrame(15, "Min"),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)
        start = datetime.now() - timedelta(days=days_back)

        all_results: dict[str, list[dict]] = {}
        batch_size = 200

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            await self._rate_limiter.acquire()

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=batch,
                    timeframe=tf,
                    start=start,
                )
                bars_set = self.stock_data.get_stock_bars(request)

                for sym in batch:
                    bars = bars_set.get(sym, []) if bars_set else []
                    all_results[sym] = [
                        {
                            "timestamp": str(bar.timestamp),
                            "open": float(bar.open),
                            "high": float(bar.high),
                            "low": float(bar.low),
                            "close": float(bar.close),
                            "volume": int(bar.volume),
                            "vwap": float(bar.vwap) if hasattr(bar, "vwap") and bar.vwap else None,
                        }
                        for bar in bars
                    ]
            except Exception as e:
                logger.warning(f"Batch bar fetch failed for batch at index {i}: {e}")
                # Fill missing symbols with empty lists
                for sym in batch:
                    if sym not in all_results:
                        all_results[sym] = []

        return all_results

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
    GetOrdersRequest,
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

    # ── Multi-Leg Orders ─────────────────────────────────────────────
    #
    # Infrastructure only — not activated in the orchestration loop.
    # Supports vertical spreads, iron condors, and other multi-leg
    # strategies for future phases.

    async def submit_multi_leg_order(
        self,
        legs: list[dict],
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> dict:
        """
        Submit a multi-leg options order (spread, iron condor, etc.).

        NOT ACTIVATED — infrastructure only. The orchestration loop does not
        call this method. It exists so Phase 2+ can enable multi-leg strategies
        without broker-layer changes.

        Args:
            legs: List of leg dicts, each with:
                - option_symbol: OCC symbol (e.g. "AAPL240119P00150000")
                - side: "buy" or "sell"
                - qty: number of contracts (ratio legs supported)
            order_type: "limit", "market", "net_debit", "net_credit"
            limit_price: Net price for the combo (required for limit/debit/credit)
            time_in_force: "day" or "gtc"

        Returns:
            Dict with order_id, status, legs summary

        Example — bull put spread:
            await broker.submit_multi_leg_order(
                legs=[
                    {"option_symbol": "SPY260501P00540000", "side": "sell", "qty": 1},
                    {"option_symbol": "SPY260501P00530000", "side": "buy", "qty": 1},
                ],
                order_type="limit",
                limit_price=0.85,  # net credit received
            )
        """
        await self._rate_limiter.acquire()

        if not legs or len(legs) < 2:
            raise ValueError("Multi-leg orders require at least 2 legs")

        tif_map = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
        }
        tif = tif_map.get(time_in_force.lower(), TimeInForce.DAY)

        try:
            # Build leg order requests
            order_legs = []
            for leg in legs:
                order_side = OrderSide.BUY if leg["side"].lower() == "buy" else OrderSide.SELL
                order_legs.append({
                    "symbol": leg["option_symbol"],
                    "qty": str(leg["qty"]),
                    "side": order_side,
                    "type": "market",
                })

            # Use the Alpaca REST API directly for multi-leg orders
            # since alpaca-py SDK doesn't have first-class multi-leg support
            import httpx

            order_payload = {
                "order_class": "mleg",
                "time_in_force": time_in_force.lower(),
                "legs": [
                    {
                        "symbol": leg["option_symbol"],
                        "qty": str(leg["qty"]),
                        "side": leg["side"].lower(),
                    }
                    for leg in legs
                ],
            }

            if order_type.lower() == "limit" and limit_price is not None:
                order_payload["type"] = "limit"
                order_payload["limit_price"] = str(round(limit_price, 2))
            else:
                order_payload["type"] = "market"

            base_url = "https://paper-api.alpaca.markets" if settings.trading_mode == "paper" else "https://api.alpaca.markets"
            url = f"{base_url}/v2/orders"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json=order_payload,
                    headers={
                        "APCA-API-KEY-ID": settings.alpaca_api_key,
                        "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
                        "Content-Type": "application/json",
                    },
                )

                if resp.status_code not in (200, 201):
                    error_text = resp.text[:300]
                    logger.error(f"[AlpacaBroker] Multi-leg order failed: HTTP {resp.status_code} — {error_text}")
                    raise RuntimeError(f"Multi-leg order rejected: {error_text}")

                data = resp.json()

            leg_summary = [
                f"{leg['side'].upper()} {leg['qty']}x {leg['option_symbol']}"
                for leg in legs
            ]
            logger.info(
                f"[AlpacaBroker] Multi-leg order submitted: {' / '.join(leg_summary)} "
                f"@ {'$' + str(limit_price) if limit_price else 'MKT'} — ID: {data.get('id')}"
            )

            return {
                "order_id": str(data.get("id", "")),
                "status": data.get("status", ""),
                "order_class": "mleg",
                "legs": leg_summary,
                "type": order_type,
                "limit_price": limit_price,
                "submitted_at": data.get("submitted_at", ""),
            }

        except Exception as e:
            logger.error(f"[AlpacaBroker] Multi-leg order failed: {e}")
            raise

    # ── Historical Data ───────────────────────────────────────────────
    #
    # NOTE: The alpaca-py StockHistoricalDataClient.get_stock_bars() returns
    # empty BarSets despite valid credentials. The raw REST API works correctly.
    # Both methods below use httpx directly to work around the SDK bug.

    _DATA_BASE = "https://data.alpaca.markets/v2/stocks"

    @property
    def _data_headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }

    @staticmethod
    def _parse_bar(raw: dict) -> dict:
        """Convert Alpaca compact bar dict (c/h/l/o/t/v/vw) to our format."""
        return {
            "timestamp": raw.get("t", ""),
            "open": float(raw.get("o", 0)),
            "high": float(raw.get("h", 0)),
            "low": float(raw.get("l", 0)),
            "close": float(raw.get("c", 0)),
            "volume": int(raw.get("v", 0)),
            "vwap": float(raw.get("vw")) if raw.get("vw") else None,
        }

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        days_back: int = 60,
    ) -> list[dict]:
        """
        Fetch historical OHLCV bars for a stock symbol via direct REST call.
        Uses httpx instead of the Alpaca SDK (SDK returns empty BarSets on free plan).
        """
        import httpx
        await self._rate_limiter.acquire()

        tf_str = timeframe if timeframe in ("1Min", "5Min", "15Min", "1Hour", "1Day") else "1Day"
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        url = f"{self._DATA_BASE}/{symbol}/bars"
        params = {"timeframe": tf_str, "start": start, "limit": 1000}

        bars: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    resp = await client.get(url, params=params, headers=self._data_headers)
                    if resp.status_code != 200:
                        logger.error(
                            f"Bars HTTP {resp.status_code} for {symbol}: {resp.text[:200]}"
                        )
                        break
                    data = resp.json()
                    for raw in data.get("bars") or []:
                        bars.append(self._parse_bar(raw))
                    token = data.get("next_page_token")
                    if not token:
                        break
                    params["page_token"] = token
            return bars
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

    async def get_all_orders(self) -> list[dict]:
        """
        Fetch the COMPLETE order history (all statuses), paginating past the
        API's per-request cap. Used by the nightly broker reconciliation.
        """
        all_orders: list[dict] = []
        after = None
        while True:
            await self._rate_limiter.acquire()
            req = GetOrdersRequest(
                status=QueryOrderStatus.ALL,
                limit=500,
                direction="asc",
                after=after,
            )
            batch = self.trading.get_orders(filter=req)
            if not batch:
                break
            def _enum_val(v):
                return getattr(v, "value", str(v) if v is not None else "")

            for o in batch:
                all_orders.append({
                    "order_id": str(o.id),
                    "symbol": o.symbol,
                    "side": _enum_val(o.side).lower(),
                    "qty": float(o.qty) if o.qty else 0.0,
                    "filled_qty": float(o.filled_qty) if o.filled_qty else 0.0,
                    "status": _enum_val(o.status).lower(),
                    "asset_class": _enum_val(getattr(o, "asset_class", None)).lower(),
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                    "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                    "submitted_at": o.submitted_at,
                    "filled_at": o.filled_at,
                })
            if len(batch) < 500:
                break
            after = batch[-1].submitted_at
        return all_orders

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

            # Fetch ALL active US equity assets without server-side attributes filter.
            # The attributes field is unreliable — many options-eligible assets have
            # it unpopulated. We apply a two-tier client-side check instead.
            request = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=AssetClass.US_EQUITY,
            )

            assets = self.trading.get_all_assets(request)

            with_attrs = sum(1 for a in assets if a.attributes)
            without_attrs = sum(1 for a in assets if not a.attributes)
            logger.info(
                f"[AlpacaBroker] Raw asset fetch: {len(assets)} total, "
                f"{with_attrs} with attributes populated, {without_attrs} without"
            )

            results = []
            for a in assets:
                if not a.tradable:
                    continue

                # Determine asset type: ETF vs stock
                etf_exchanges = {"ARCA", "BATS", "NYSEARCA"}
                exchange_str = str(a.exchange) if a.exchange else ""
                exchange_clean = exchange_str.split(".")[-1] if "." in exchange_str else exchange_str
                asset_type = "etf" if exchange_clean in etf_exchanges else "stock"

                # Two-tier options check:
                # Tier 1: attributes populated — check explicitly
                # Tier 2: attributes missing — assume optionable, let liquidity score filter it
                if a.attributes and isinstance(a.attributes, (list, set)):
                    has_options = "has_options" in a.attributes
                else:
                    # Attributes not populated by Alpaca — pass through, downstream will filter
                    has_options = True

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
                f"[AlpacaBroker] Passing {len(results)} assets to pre-filter "
                f"({'options-enabled filter applied' if options_enabled else 'all assets'})"
            )

            if len(results) < 10:
                logger.warning(
                    f"[AlpacaBroker] Only {len(results)} assets discovered — "
                    f"possible API permission issue. Scanner will supplement with always_include list."
                )

            return results

        except Exception as e:
            logger.error(f"Failed to fetch tradable assets: {e}")
            raise

    async def get_order(self, order_id: str) -> dict:
        """
        Fetch a single order by ID and return its current status and fill details.

        Returns:
            Dict with id, symbol, status, side, qty, filled_avg_price, filled_at,
            submitted_at, reject_reason, order_type, limit_price
        """
        await self._rate_limiter.acquire()
        try:
            order = self.trading.get_order_by_id(order_id)
            return {
                "id": str(order.id),
                "symbol": getattr(order, "symbol", None),
                "status": str(getattr(order, "status", "")).split(".")[-1].lower(),
                "side": str(getattr(order, "side", "")).split(".")[-1].lower(),
                "qty": int(order.qty) if getattr(order, "qty", None) else 0,
                "filled_qty": int(order.filled_qty) if getattr(order, "filled_qty", None) else 0,
                "filled_avg_price": float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None,
                "filled_at": str(order.filled_at) if getattr(order, "filled_at", None) else None,
                "submitted_at": str(order.submitted_at) if getattr(order, "submitted_at", None) else None,
                "reject_reason": str(order.reject_reason) if getattr(order, "reject_reason", None) else None,
                "order_type": str(getattr(order, "type", getattr(order, "order_type", ""))).split(".")[-1].lower(),
                "limit_price": float(order.limit_price) if getattr(order, "limit_price", None) else None,
            }
        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {e}")
            raise

    async def get_option_quote(self, option_symbol: str) -> dict:
        """
        Fetch the current NBBO for a single option contract.

        Returns {"bid": float, "ask": float, "mid": float}. Any leg that is
        unavailable comes back as 0.0 so callers (e.g. OrderChaser) can fall
        back to a reference price rather than submitting an unmarketable order.
        """
        snapshots = await self._get_option_snapshots_batched([option_symbol])
        snap = snapshots.get(option_symbol, {})
        bid = float(snap.get("bid", 0.0) or 0.0)
        ask = float(snap.get("ask", 0.0) or 0.0)
        mid = float(snap.get("mid_price", 0.0) or 0.0)
        return {"bid": bid, "ask": ask, "mid": mid}

    async def close_option_position(self, option_symbol: str) -> dict:
        """
        Close an open option position by submitting a market order via the close_position endpoint.

        Returns:
            Dict with order_id, status, filled_avg_price
        """
        await self._rate_limiter.acquire()
        try:
            order = self.trading.close_position(option_symbol)
            logger.info(f"[AlpacaBroker] Closed position {option_symbol} — Order {order.id}")
            return {
                "order_id": str(order.id),
                "status": str(order.status).split(".")[-1].lower(),
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            }
        except Exception as e:
            logger.error(f"Failed to close position {option_symbol}: {e}")
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

        Uses the multi-symbol REST endpoint directly (SDK returns empty BarSet
        on free tier). Batches in groups of 100 with explicit pacing to stay
        under Alpaca's free tier rate limits. Retries on 429 with backoff.
        """
        import httpx

        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        all_results: dict[str, list[dict]] = {}
        batch_size = 100
        total_batches = (len(symbols) + batch_size - 1) // batch_size

        logger.info(
            f"[AlpacaBroker] Fetching bars for {len(symbols)} symbols "
            f"in {total_batches} batches of {batch_size}..."
        )

        for batch_idx, i in enumerate(range(0, len(symbols), batch_size)):
            batch = symbols[i : i + batch_size]
            await self._rate_limiter.acquire()

            # Pace at 500ms = 120 req/min, leaving ~80 req/min headroom for other
            # agent activity (reconciler, portfolio sync, lead agent cycles) that
            # shares the same Alpaca free-tier 200/min budget.
            if batch_idx > 0:
                await asyncio.sleep(0.5)

            url = f"{self._DATA_BASE}/bars"
            params: dict = {
                "symbols": ",".join(batch),
                "timeframe": timeframe,
                "start": start,
                "limit": 1000,
            }

            # Single retry on 429 with 10s backoff
            attempts_remaining = 2
            while attempts_remaining > 0:
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        while True:
                            resp = await client.get(
                                url, params=params, headers=self._data_headers
                            )

                            if resp.status_code == 429:
                                attempts_remaining -= 1
                                if attempts_remaining > 0:
                                    logger.warning(
                                        f"[AlpacaBroker] Batch {batch_idx + 1}/{total_batches}: "
                                        f"429 rate limited, backing off 10s and retrying"
                                    )
                                    await asyncio.sleep(10.0)
                                    break  # break inner while, retry outer while
                                else:
                                    logger.error(
                                        f"[AlpacaBroker] Batch {batch_idx + 1}/{total_batches}: "
                                        f"429 after retry, giving up on this batch"
                                    )
                                    break

                            if resp.status_code != 200:
                                logger.warning(
                                    f"[AlpacaBroker] Batch {batch_idx + 1}/{total_batches}: "
                                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                                )
                                attempts_remaining = 0
                                break

                            # Success — parse and accumulate
                            data = resp.json()
                            bars_by_sym = data.get("bars") or {}
                            for sym, raw_bars in bars_by_sym.items():
                                all_results.setdefault(sym, []).extend(
                                    self._parse_bar(r) for r in raw_bars
                                )
                            token = data.get("next_page_token")
                            if not token:
                                attempts_remaining = 0  # success, done with this batch
                                break
                            params["page_token"] = token

                except Exception as e:
                    logger.warning(
                        f"[AlpacaBroker] Batch {batch_idx + 1}/{total_batches} failed: {e}"
                    )
                    attempts_remaining = 0

            # Fill any symbols in this batch that got no data
            for sym in batch:
                all_results.setdefault(sym, [])

            # Progress log every 10 batches
            if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
                symbols_with_data = sum(1 for v in all_results.values() if v)
                logger.info(
                    f"[AlpacaBroker] Batches {batch_idx + 1}/{total_batches} done, "
                    f"{symbols_with_data} symbols with data so far"
                )

        return all_results

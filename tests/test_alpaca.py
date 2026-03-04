"""
Test suite for Alpaca integration — verifies connection and basic data fetching.
Run with: pytest tests/test_alpaca.py -v
"""
import asyncio
import os

import pytest
import pytest_asyncio

# ── Skip all tests if no API keys configured ──────────────────────────

SKIP_REASON = "ALPACA_API_KEY not set — set it in .env for live API tests"
HAS_API_KEYS = bool(os.environ.get("ALPACA_API_KEY") or os.path.exists(".env"))


@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Alpaca Client Tests ───────────────────────────────────────────────


@pytest.mark.skipif(not HAS_API_KEYS, reason=SKIP_REASON)
class TestAlpacaBroker:
    """Tests that require a live Alpaca paper trading connection."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from services.alpaca_broker import AlpacaBroker
        self.broker = AlpacaBroker()

    @pytest.mark.asyncio
    async def test_connection_and_account(self):
        """Verify we can connect to Alpaca and fetch account info."""
        account = await self.broker.get_account()
        assert "cash" in account
        assert "equity" in account
        assert "buying_power" in account
        assert account["equity"] >= 0
        print(f"\n✓ Connected to Alpaca paper account")
        print(f"  Equity: ${account['equity']:,.2f}")
        print(f"  Cash: ${account['cash']:,.2f}")
        print(f"  Buying Power: ${account['buying_power']:,.2f}")

    @pytest.mark.asyncio
    async def test_get_latest_quote_aapl(self):
        """Verify we can fetch a quote for AAPL."""
        quote = await self.broker.get_latest_quote("AAPL")
        assert quote, "No quote returned for AAPL"
        assert quote.get("bid", 0) > 0, "Bid should be positive"
        assert quote.get("ask", 0) > 0, "Ask should be positive"
        print(f"\n✓ AAPL Quote: bid=${quote['bid']:.2f}, ask=${quote['ask']:.2f}")

    @pytest.mark.asyncio
    async def test_get_historical_bars(self):
        """Verify we can fetch historical daily bars for AAPL."""
        bars = await self.broker.get_historical_bars("AAPL", "1Day", days_back=30)
        assert bars, "No bars returned"
        assert len(bars) > 10, f"Expected 10+ bars, got {len(bars)}"
        bar = bars[-1]
        assert "close" in bar
        assert "volume" in bar
        assert bar["close"] > 0
        print(f"\n✓ AAPL Bars: {len(bars)} days, last close=${bar['close']:.2f}")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        """Verify we can fetch positions (may be empty in paper)."""
        positions = await self.broker.get_positions()
        assert isinstance(positions, list)
        print(f"\n✓ Positions: {len(positions)} open")

    @pytest.mark.asyncio
    async def test_get_options_chain(self):
        """Verify we can fetch an options chain for AAPL."""
        chain = await self.broker.get_options_chain("AAPL")
        if chain:
            assert len(chain) > 0
            contract = chain[0]
            assert "strike" in contract
            assert "expiration" in contract
            assert "option_symbol" in contract
            assert "delta" in contract
            print(f"\n✓ AAPL Options Chain: {len(chain)} contracts")
            print(f"  Sample: {contract['option_symbol']}")
            print(f"    Strike: ${contract['strike']:.2f}")
            print(f"    Exp: {contract['expiration']}")
            print(f"    Delta: {contract['delta']:.3f}")
            print(f"    Bid/Ask: ${contract['bid']:.2f} / ${contract['ask']:.2f}")
        else:
            pytest.skip("No options chain data available (may be outside market hours)")


# ── Market Feed Tests ─────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_API_KEYS, reason=SKIP_REASON)
class TestMarketFeed:
    """Tests for the market feed service."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from data.market_feed import MarketFeed
        self.feed = MarketFeed()

    @pytest.mark.asyncio
    async def test_get_current_price(self):
        """Verify we can get a current price for AAPL."""
        price = await self.feed.get_current_price("AAPL")
        assert price > 0, f"Expected positive price, got {price}"
        print(f"\n✓ AAPL current price: ${price:.2f}")

    @pytest.mark.asyncio
    async def test_iv_rank_calculation(self):
        """Verify IV rank calculation for AAPL."""
        iv_rank = await self.feed.get_iv_rank("AAPL")
        # IV rank should be between 0-100, or -1 if insufficient data
        assert -1.0 <= iv_rank <= 100.0, f"IV rank out of range: {iv_rank}"
        if iv_rank >= 0:
            print(f"\n✓ AAPL IV Rank: {iv_rank:.1f}%")
        else:
            print(f"\n⚠ AAPL IV Rank: insufficient data")

    @pytest.mark.asyncio
    async def test_iv_ranks_batch(self):
        """Verify batch IV rank calculation."""
        symbols = ["AAPL", "MSFT", "NVDA"]
        ranks = await self.feed.get_iv_ranks(symbols)
        assert len(ranks) == 3
        for sym in symbols:
            assert sym in ranks
        print(f"\n✓ IV Ranks: {ranks}")

    @pytest.mark.asyncio
    async def test_support_levels(self):
        """Verify support level detection for AAPL."""
        levels = await self.feed.get_support_levels("AAPL")
        assert isinstance(levels, list)
        if levels:
            print(f"\n✓ AAPL Support Levels: {['$'+f'{l:.2f}' for l in levels[:5]]}")


# ── Options Chain Analyzer Tests ──────────────────────────────────────


@pytest.mark.skipif(not HAS_API_KEYS, reason=SKIP_REASON)
class TestOptionsChainAnalyzer:
    """Tests for the options chain analyzer."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from data.options_chain import OptionsChainAnalyzer
        self.analyzer = OptionsChainAnalyzer()

    def test_annualized_return_calculation(self):
        """Verify annualized return math."""
        # $2.50 premium on $150 strike with 30 DTE
        # Return = (2.50 / 150) * (365 / 30) * 100 = 20.28%
        result = self.analyzer.calculate_annualized_return(
            premium=2.50, strike=150.0, dte=30, contract_type="put"
        )
        assert 20.0 < result < 21.0, f"Expected ~20.28%, got {result}%"
        print(f"\n✓ Annualized Return: {result}%")

    def test_score_contract(self):
        """Verify contract scoring logic."""
        contract = {
            "strike": 145.0,
            "mid_price": 2.50,
            "dte": 30,
            "delta": -0.25,
            "contract_type": "put",
            "bid": 2.40,
            "ask": 2.60,
        }
        score = self.analyzer.score_contract(contract, current_price=150.0)
        assert 0 < score <= 1.0
        assert "annualized_return" in contract
        assert "probability_of_profit" in contract
        assert "distance_otm_pct" in contract
        print(f"\n✓ Contract Score: {score:.4f}")
        print(f"  Ann. Return: {contract['annualized_return']}%")
        print(f"  PoP: {contract['probability_of_profit']}%")
        print(f"  Distance OTM: {contract['distance_otm_pct']}%")

    @pytest.mark.asyncio
    async def test_find_optimal_puts(self):
        """Verify optimal put discovery for AAPL."""
        from data.market_feed import MarketFeed
        feed = MarketFeed()
        price = await feed.get_current_price("AAPL")

        if price <= 0:
            pytest.skip("Could not get AAPL price")

        puts = await self.analyzer.find_optimal_puts("AAPL", price)
        if puts:
            print(f"\n✓ Top {len(puts)} puts for AAPL (price=${price:.2f}):")
            for p in puts:
                print(
                    f"  {p['option_symbol']} | "
                    f"Strike ${p['strike']:.0f} | "
                    f"DTE {p['dte']} | "
                    f"Δ {p['delta']:.2f} | "
                    f"Return {p.get('annualized_return', 0):.1f}% | "
                    f"Score {p.get('score', 0):.3f}"
                )
        else:
            pytest.skip("No puts found (may be outside market hours)")


# ── Unit Tests (no API keys needed) ──────────────────────────────────


class TestCalculations:
    """Pure calculation tests — no API keys required."""

    def test_annualized_return_zero_dte(self):
        from data.options_chain import OptionsChainAnalyzer
        analyzer = OptionsChainAnalyzer.__new__(OptionsChainAnalyzer)
        analyzer.strategies = {}
        result = analyzer.calculate_annualized_return(2.0, 100.0, 0)
        assert result == 0.0

    def test_annualized_return_zero_strike(self):
        from data.options_chain import OptionsChainAnalyzer
        analyzer = OptionsChainAnalyzer.__new__(OptionsChainAnalyzer)
        analyzer.strategies = {}
        result = analyzer.calculate_annualized_return(2.0, 0, 30)
        assert result == 0.0

    def test_cache_ttl(self):
        from data.market_feed import MarketDataCache
        cache = MarketDataCache(default_ttl=1)
        cache.set("test", {"value": 42})
        assert cache.get("test") == {"value": 42}

    def test_cache_invalidate(self):
        from data.market_feed import MarketDataCache
        cache = MarketDataCache(default_ttl=60)
        cache.set("test", {"value": 42})
        cache.invalidate("test")
        assert cache.get("test") is None

    def test_cache_clear(self):
        from data.market_feed import MarketDataCache
        cache = MarketDataCache(default_ttl=60)
        cache.set("a", {"v": 1})
        cache.set("b", {"v": 2})
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

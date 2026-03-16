"""
Diagnostic script: why is get_historical_bars returning empty results?

Tests five approaches in order, logging PASS/FAIL for each.
Run from the project root:
    python scripts/diagnose_bars.py
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Make sure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings

SYMBOL = "SPY"
DAYS_BACK = 10


def _mask(key: str) -> str:
    if not key or len(key) < 8:
        return f"<empty or too short: {repr(key)}>"
    return f"{key[:4]}...{key[-4:]}"


def _result(label: str, bars, extra: str = ""):
    if bars:
        print(f"  PASS — {len(bars)} bars returned. First: {bars[0]}")
    else:
        print(f"  FAIL — 0 bars returned. {extra}")
    return bool(bars)


# ── Test E (run first so key check is always visible) ────────────────────────

def test_e_key_check():
    print("\n=== Test E: API key check ===")
    api_key = settings.alpaca_api_key
    secret_key = settings.alpaca_secret_key
    print(f"  ALPACA_API_KEY    : {_mask(api_key)}")
    print(f"  ALPACA_SECRET_KEY : {_mask(secret_key)}")
    if not api_key or not secret_key:
        print("  FAIL — one or both keys are empty strings. Check your .env file.")
        return False
    print("  PASS — keys are present")
    return True


# ── Test A: current implementation (baseline) ────────────────────────────────

def test_a_baseline():
    print(f"\n=== Test A: Baseline (current implementation) ===")
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        start = datetime.now() - timedelta(days=DAYS_BACK)
        req = StockBarsRequest(symbol_or_symbols=SYMBOL, timeframe=TimeFrame.Day, start=start)
        print(f"  Request: symbol={SYMBOL}, timeframe=Day, start={start.isoformat()}, feed=<default>")

        bars_set = client.get_stock_bars(req)
        raw_keys = list(bars_set.keys()) if hasattr(bars_set, "keys") else []
        print(f"  Response keys: {raw_keys}")
        bars = list(bars_set[SYMBOL]) if SYMBOL in bars_set else []
        return _result("A", bars, f"Response object type: {type(bars_set)}, keys: {raw_keys}")
    except Exception as e:
        print(f"  FAIL — exception: {e}")
        return False


# ── Test B: add feed=DataFeed.IEX ────────────────────────────────────────────

def test_b_iex_feed():
    print(f"\n=== Test B: DataFeed.IEX ===")
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        start = datetime.now() - timedelta(days=DAYS_BACK)
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOL,
            timeframe=TimeFrame.Day,
            start=start,
            feed=DataFeed.IEX,
        )
        print(f"  Request: symbol={SYMBOL}, timeframe=Day, start={start.isoformat()}, feed=IEX")

        bars_set = client.get_stock_bars(req)
        bars = list(bars_set[SYMBOL]) if SYMBOL in bars_set else []
        return _result("B", bars)
    except Exception as e:
        print(f"  FAIL — exception: {e}")
        return False


# ── Test C: timezone-aware datetime ──────────────────────────────────────────

def test_c_tz_aware():
    print(f"\n=== Test C: Timezone-aware start datetime (UTC) ===")
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        start = datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK)
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOL,
            timeframe=TimeFrame.Day,
            start=start,
        )
        print(f"  Request: symbol={SYMBOL}, timeframe=Day, start={start.isoformat()}, feed=<default>")

        bars_set = client.get_stock_bars(req)
        bars = list(bars_set[SYMBOL]) if SYMBOL in bars_set else []
        return _result("C", bars)
    except Exception as e:
        print(f"  FAIL — exception: {e}")
        return False


# ── Test C2: IEX + timezone-aware ────────────────────────────────────────────

def test_c2_iex_tz():
    print(f"\n=== Test C2: DataFeed.IEX + timezone-aware datetime ===")
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        start = datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK)
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOL,
            timeframe=TimeFrame.Day,
            start=start,
            feed=DataFeed.IEX,
        )
        print(f"  Request: symbol={SYMBOL}, timeframe=Day, start={start.isoformat()}, feed=IEX")

        bars_set = client.get_stock_bars(req)
        bars = list(bars_set[SYMBOL]) if SYMBOL in bars_set else []
        return _result("C2", bars)
    except Exception as e:
        print(f"  FAIL — exception: {e}")
        return False


# ── Test D: raw HTTP with httpx ───────────────────────────────────────────────

async def test_d_raw_http():
    print(f"\n=== Test D: Raw HTTP (bypass SDK) ===")
    try:
        import httpx

        url = f"https://data.alpaca.markets/v2/stocks/{SYMBOL}/bars"
        params = {
            "timeframe": "1Day",
            "start": "2025-01-01",
            "limit": 5,
        }
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        print(f"  GET {url} params={params}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=headers)

        print(f"  HTTP status: {resp.status_code}")
        body = resp.json()
        print(f"  Response body: {body}")

        bars = body.get("bars", [])
        if resp.status_code == 200 and bars:
            print(f"  PASS — {len(bars)} bars in raw response")
            return True
        elif resp.status_code == 200 and not bars:
            print(f"  FAIL — HTTP 200 but bars array is empty. Full body: {body}")
            # Also try with IEX feed param
            params["feed"] = "iex"
            print(f"\n  Retrying with feed=iex...")
            async with httpx.AsyncClient(timeout=15) as client:
                resp2 = await client.get(url, params=params, headers=headers)
            body2 = resp2.json()
            bars2 = body2.get("bars", [])
            print(f"  feed=iex HTTP {resp2.status_code}: {len(bars2)} bars — body: {body2}")
            return bool(bars2)
        else:
            print(f"  FAIL — HTTP {resp.status_code}: {body}")
            return False
    except ImportError:
        print("  SKIP — httpx not installed. Run: pip3 install httpx")
        return None
    except Exception as e:
        print(f"  FAIL — exception: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(f"Alpaca Historical Bars Diagnostic — symbol={SYMBOL}")
    print("=" * 60)

    results = {}
    results["E"] = test_e_key_check()

    if not results["E"]:
        print("\n⚠ API keys are missing — remaining tests will likely fail.")

    results["A"] = test_a_baseline()
    results["B"] = test_b_iex_feed()
    results["C"] = test_c_tz_aware()
    results["C2"] = test_c2_iex_tz()
    results["D"] = await test_d_raw_http()

    print("\n" + "=" * 60)
    print("Summary:")
    for k, v in results.items():
        status = "PASS" if v else ("SKIP" if v is None else "FAIL")
        print(f"  Test {k}: {status}")

    passing = [k for k, v in results.items() if v]
    if not passing:
        print("\n⚠ All tests failed. Check API keys and account status.")
        print("  1. Verify keys in .env match the Alpaca dashboard")
        print("  2. Paper trading data may require a separate subscription")
        print("  3. Try logging into Alpaca and checking account status")
    else:
        first_pass = passing[0] if passing[0] != "E" else (passing[1] if len(passing) > 1 else None)
        if first_pass == "B":
            print("\n✓ Fix: add feed=DataFeed.IEX to StockBarsRequest in alpaca_broker.py")
        elif first_pass == "C":
            print("\n✓ Fix: use timezone-aware datetime (datetime.now(tz=timezone.utc))")
        elif first_pass == "C2":
            print("\n✓ Fix: use BOTH feed=DataFeed.IEX AND timezone-aware datetime")
        elif first_pass == "D":
            print("\n✓ Raw HTTP works — SDK configuration issue. Check SDK version.")
        print(f"  First passing test: {first_pass}")


if __name__ == "__main__":
    asyncio.run(main())

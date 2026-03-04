"""
Backtesting Engine — Historical replay of any agent's logic against past market data.

Architecture:
  1. BacktestBroker: Mock broker serving cached historical data & recording simulated orders
  2. BacktestMarketFeed: Steps through trading days, provides IV rank / support on each day
  3. BacktestEngine: Replay loop — for each day, runs agent scan → evaluate → execute → manage
  4. BacktestResult: Comprehensive stats — equity curve, trade log, summary, monthly returns

Usage:
    engine = BacktestEngine(
        agent_type="worker_csp",
        symbols=["AAPL", "MSFT"],
        days=180,
        param_overrides={"delta_target": -0.20, "min_iv_rank": 35},
    )
    result = await engine.run()
    result.print_summary()
    result.save_json("data/backtest_results/csp_180d.json")
"""
from __future__ import annotations

import json
import math
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

from core.broker import Broker
from core.portfolio import Portfolio, Position, OptionsPosition
from core.risk_manager import RiskManager
from data.market_feed import MarketFeed
from data.options_chain import OptionsChainAnalyzer

# Cache directory
CACHE_DIR = Path("data/backtest_cache")
RESULTS_DIR = Path("data/backtest_results")


# ═══════════════════════════════════════════════════════════════════
#  BacktestResult
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    """Comprehensive backtest output."""

    # Core
    agent_type: str = ""
    symbols: list[str] = field(default_factory=list)
    param_overrides: dict = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    days: int = 0

    # Equity curve: list of (date_str, portfolio_value)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)

    # Trade log: every simulated trade
    trade_log: list[dict] = field(default_factory=list)

    # Summary stats
    initial_capital: float = 100_000.0
    final_value: float = 100_000.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    win_rate: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    profit_factor: float = 0.0
    total_premium_collected: float = 0.0
    trade_count: int = 0
    avg_hold_time_days: float = 0.0

    # Per-symbol breakdown
    per_symbol: dict[str, dict] = field(default_factory=dict)

    # Monthly returns: YYYY-MM → return %
    monthly_returns: dict[str, float] = field(default_factory=dict)

    def compute_summary(self):
        """Compute all summary statistics from equity_curve and trade_log."""
        # ── Total and annualized return ──
        if self.initial_capital > 0:
            self.total_return = (
                (self.final_value - self.initial_capital) / self.initial_capital * 100
            )
        trading_days = len(self.equity_curve)
        if trading_days > 1 and self.initial_capital > 0:
            years = trading_days / 252
            if years > 0:
                self.annualized_return = (
                    ((self.final_value / self.initial_capital) ** (1 / years) - 1) * 100
                )

        # ── Daily returns for Sharpe / Sortino ──
        daily_returns = []
        for i in range(1, len(self.equity_curve)):
            prev_val = self.equity_curve[i - 1][1]
            curr_val = self.equity_curve[i][1]
            if prev_val > 0:
                daily_returns.append((curr_val - prev_val) / prev_val)

        if len(daily_returns) >= 10:
            mean_ret = sum(daily_returns) / len(daily_returns)
            std_ret = math.sqrt(
                sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
            )
            downside = [r for r in daily_returns if r < 0]
            downside_std = (
                math.sqrt(sum(r ** 2 for r in downside) / len(downside))
                if downside
                else 0.001
            )

            risk_free = 0.05 / 252  # ~5% annual
            self.sharpe_ratio = round(
                (mean_ret - risk_free) / max(std_ret, 0.0001) * math.sqrt(252), 2
            )
            self.sortino_ratio = round(
                (mean_ret - risk_free) / max(downside_std, 0.0001) * math.sqrt(252), 2
            )

        # ── Max drawdown ──
        peak = self.initial_capital
        max_dd = 0.0
        dd_start = 0
        max_dd_duration = 0
        current_dd_start: Optional[int] = None

        for i, (_, val) in enumerate(self.equity_curve):
            if val > peak:
                peak = val
                if current_dd_start is not None:
                    duration = i - current_dd_start
                    max_dd_duration = max(max_dd_duration, duration)
                current_dd_start = None
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                if current_dd_start is None:
                    current_dd_start = i

        self.max_drawdown = round(max_dd * 100, 2)
        self.max_drawdown_duration_days = max_dd_duration

        # ── Trade stats ──
        closed_trades = [t for t in self.trade_log if t.get("realized_pnl") is not None]
        self.trade_count = len(closed_trades)

        if closed_trades:
            winners = [t for t in closed_trades if t["realized_pnl"] > 0]
            losers = [t for t in closed_trades if t["realized_pnl"] <= 0]

            self.win_rate = round(len(winners) / len(closed_trades) * 100, 1)
            self.avg_winner = (
                round(sum(t["realized_pnl"] for t in winners) / len(winners), 2)
                if winners
                else 0
            )
            self.avg_loser = (
                round(sum(t["realized_pnl"] for t in losers) / len(losers), 2)
                if losers
                else 0
            )

            gross_profit = sum(t["realized_pnl"] for t in winners)
            gross_loss = abs(sum(t["realized_pnl"] for t in losers))
            self.profit_factor = (
                round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
            )

            # Hold time
            hold_times = []
            for t in closed_trades:
                if t.get("entry_date") and t.get("exit_date"):
                    try:
                        entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                        exit_ = datetime.strptime(t["exit_date"], "%Y-%m-%d")
                        hold_times.append((exit_ - entry).days)
                    except (ValueError, TypeError):
                        pass
            self.avg_hold_time_days = (
                round(sum(hold_times) / len(hold_times), 1) if hold_times else 0
            )

        # ── Premium collected ──
        self.total_premium_collected = sum(
            t.get("premium", 0) for t in self.trade_log if t.get("side") == "sell"
        )

        # ── Per-symbol breakdown ──
        sym_trades: dict[str, list[dict]] = defaultdict(list)
        for t in closed_trades:
            sym_trades[t.get("symbol", "?")].append(t)

        for sym, trades in sym_trades.items():
            wins = [t for t in trades if t["realized_pnl"] > 0]
            self.per_symbol[sym] = {
                "trades": len(trades),
                "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
                "total_pnl": round(sum(t["realized_pnl"] for t in trades), 2),
                "avg_pnl": round(
                    sum(t["realized_pnl"] for t in trades) / len(trades), 2
                ),
                "premium_collected": round(
                    sum(t.get("premium", 0) for t in trades if t.get("side") == "sell"), 2
                ),
            }

        # ── Monthly returns ──
        monthly_start: dict[str, float] = {}
        monthly_end: dict[str, float] = {}
        for date_str, val in self.equity_curve:
            month_key = date_str[:7]  # YYYY-MM
            if month_key not in monthly_start:
                monthly_start[month_key] = val
            monthly_end[month_key] = val

        for month in monthly_start:
            start_val = monthly_start[month]
            end_val = monthly_end[month]
            if start_val > 0:
                self.monthly_returns[month] = round(
                    (end_val - start_val) / start_val * 100, 2
                )

    def print_summary(self):
        """Print a formatted summary table to stdout."""
        print("\n" + "═" * 60)
        print(f"  BACKTEST RESULTS — {self.agent_type}")
        print("═" * 60)
        print(f"  Period:          {self.start_date} → {self.end_date} ({self.days} days)")
        print(f"  Symbols:         {', '.join(self.symbols[:10])}" +
              (f" (+{len(self.symbols)-10} more)" if len(self.symbols) > 10 else ""))
        if self.param_overrides:
            print(f"  Param overrides: {self.param_overrides}")
        print("─" * 60)
        print(f"  Initial Capital: ${self.initial_capital:>12,.2f}")
        print(f"  Final Value:     ${self.final_value:>12,.2f}")
        print(f"  Total Return:    {self.total_return:>12.2f}%")
        print(f"  Annual Return:   {self.annualized_return:>12.2f}%")
        print("─" * 60)
        print(f"  Sharpe Ratio:    {self.sharpe_ratio:>12.2f}")
        print(f"  Sortino Ratio:   {self.sortino_ratio:>12.2f}")
        print(f"  Max Drawdown:    {self.max_drawdown:>12.2f}%")
        print(f"  DD Duration:     {self.max_drawdown_duration_days:>12} days")
        print("─" * 60)
        print(f"  Trade Count:     {self.trade_count:>12}")
        print(f"  Win Rate:        {self.win_rate:>12.1f}%")
        print(f"  Avg Winner:      ${self.avg_winner:>12,.2f}")
        print(f"  Avg Loser:       ${self.avg_loser:>12,.2f}")
        print(f"  Profit Factor:   {self.profit_factor:>12.2f}")
        print(f"  Premium Coll:    ${self.total_premium_collected:>12,.2f}")
        print(f"  Avg Hold Time:   {self.avg_hold_time_days:>12.1f} days")
        print("═" * 60)

        if self.per_symbol:
            print("\n  Per-Symbol Breakdown:")
            print(f"  {'Symbol':<8} {'Trades':>6} {'WR%':>6} {'PnL':>10} {'Avg PnL':>10}")
            print("  " + "─" * 44)
            for sym, stats in sorted(
                self.per_symbol.items(), key=lambda x: x[1]["total_pnl"], reverse=True
            ):
                print(
                    f"  {sym:<8} {stats['trades']:>6} "
                    f"{stats['win_rate']:>5.1f}% "
                    f"${stats['total_pnl']:>9,.2f} "
                    f"${stats['avg_pnl']:>9,.2f}"
                )

        if self.monthly_returns:
            print("\n  Monthly Returns:")
            for month, ret in sorted(self.monthly_returns.items()):
                bar = "█" * max(0, int(ret / 0.5)) if ret > 0 else "▒" * max(0, int(abs(ret) / 0.5))
                sign = "+" if ret >= 0 else ""
                print(f"  {month}  {sign}{ret:>6.2f}%  {bar}")

        print()

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "agent_type": self.agent_type,
            "symbols": self.symbols,
            "param_overrides": self.param_overrides,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "days": self.days,
            "initial_capital": self.initial_capital,
            "final_value": self.final_value,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
            "win_rate": self.win_rate,
            "avg_winner": self.avg_winner,
            "avg_loser": self.avg_loser,
            "profit_factor": self.profit_factor,
            "total_premium_collected": self.total_premium_collected,
            "trade_count": self.trade_count,
            "avg_hold_time_days": self.avg_hold_time_days,
            "per_symbol": self.per_symbol,
            "monthly_returns": self.monthly_returns,
            "equity_curve": self.equity_curve,
            "trade_log": self.trade_log,
        }

    def save_json(self, path: str):
        """Save full results to JSON."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        logger.info(f"[Backtest] Results saved to {path}")


# ═══════════════════════════════════════════════════════════════════
#  BacktestBroker — Mock broker serving cached historical data
# ═══════════════════════════════════════════════════════════════════

class BacktestBroker(Broker):
    """
    Mock broker that:
    - Serves pre-loaded historical bars for each trading day
    - Generates synthetic options chains with realistic greeks
    - Records simulated orders (fills at mid price)
    - Maintains simulated account state
    """

    def __init__(
        self,
        real_broker: Broker,
        initial_capital: float = 100_000.0,
    ):
        self._real_broker = real_broker
        self._initial_capital = initial_capital

        # Simulated account state
        self._cash = initial_capital
        self._equity = initial_capital
        self._buying_power = initial_capital

        # Cached historical data: symbol → list of bars
        self._bars_cache: dict[str, list[dict]] = {}

        # Current simulation date index
        self._current_date: Optional[str] = None
        self._current_day_idx: int = 0

        # Simulated orders
        self._orders: list[dict] = []
        self._next_order_id = 1

        # Simulated positions
        self._positions: list[dict] = []

    # ── Data Loading ──────────────────────────────────────────────

    async def load_historical_data(
        self,
        symbols: list[str],
        days_back: int = 400,
    ):
        """
        Fetch and cache historical bars for all symbols.
        Uses local cache if available, otherwise fetches from real broker.
        """
        for symbol in symbols:
            cache_path = CACHE_DIR / f"{symbol}_bars.pkl"

            # Check local cache
            if cache_path.exists():
                try:
                    with open(cache_path, "rb") as f:
                        cached = pickle.load(f)
                    # Use cache if it has enough data
                    if len(cached) >= days_back * 0.6:  # Allow some slack for weekends
                        self._bars_cache[symbol] = cached
                        logger.debug(
                            f"[BacktestBroker] Loaded {len(cached)} bars for {symbol} from cache"
                        )
                        continue
                except Exception:
                    pass

            # Fetch from real broker
            try:
                bars = await self._real_broker.get_historical_bars(
                    symbol, "1Day", days_back=days_back
                )
                if bars:
                    self._bars_cache[symbol] = bars
                    # Save to local cache
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(cache_path, "wb") as f:
                        pickle.dump(bars, f)
                    logger.debug(
                        f"[BacktestBroker] Fetched {len(bars)} bars for {symbol}"
                    )
                else:
                    logger.warning(f"[BacktestBroker] No bars for {symbol}")
            except Exception as e:
                logger.error(f"[BacktestBroker] Failed to fetch {symbol}: {e}")

    def set_simulation_date(self, date_str: str, day_idx: int):
        """Set the current simulation date (called by the engine each day)."""
        self._current_date = date_str
        self._current_day_idx = day_idx

    def update_account(self, cash: float, equity: float):
        """Update simulated account balances."""
        self._cash = cash
        self._equity = equity
        self._buying_power = cash

    def set_positions(self, positions: list[dict]):
        """Update simulated positions."""
        self._positions = positions

    # ── Broker Interface Implementation ───────────────────────────

    async def get_account(self) -> dict:
        return {
            "cash": self._cash,
            "buying_power": self._buying_power,
            "equity": self._equity,
            "portfolio_value": self._equity,
        }

    async def get_positions(self) -> list[dict]:
        return list(self._positions)

    async def get_options_chain(
        self,
        symbol: str,
        expiration_date_gte: Optional[str] = None,
        expiration_date_lte: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Generate a synthetic options chain based on the stock price
        on the current simulation date.
        """
        bars = self._bars_cache.get(symbol, [])
        if not bars or self._current_day_idx >= len(bars):
            return []

        current_bar = bars[self._current_day_idx]
        price = current_bar["close"]

        if price <= 0:
            return []

        # Compute historical vol for IV proxy
        lookback = min(20, self._current_day_idx)
        if lookback < 5:
            hist_vol = 0.25  # Default 25%
        else:
            window_bars = bars[self._current_day_idx - lookback : self._current_day_idx + 1]
            closes = [b["close"] for b in window_bars]
            log_returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    log_returns.append(math.log(closes[i] / closes[i - 1]))
            if log_returns:
                std = math.sqrt(
                    sum((r - sum(log_returns) / len(log_returns)) ** 2 for r in log_returns)
                    / len(log_returns)
                )
                hist_vol = std * math.sqrt(252)
            else:
                hist_vol = 0.25

        # Add IV premium over realized vol (typical: 10-30%)
        iv = hist_vol * 1.15

        # Parse date filters
        sim_date = datetime.strptime(self._current_date, "%Y-%m-%d")

        dte_min = 0
        dte_max = 365
        if expiration_date_gte:
            try:
                gte = datetime.strptime(expiration_date_gte, "%Y-%m-%d")
                dte_min = max(0, (gte - sim_date).days)
            except ValueError:
                pass
        if expiration_date_lte:
            try:
                lte = datetime.strptime(expiration_date_lte, "%Y-%m-%d")
                dte_max = max(0, (lte - sim_date).days)
            except ValueError:
                pass

        chain = []

        # Generate expirations (weekly-ish: every Friday in range)
        for dte in range(max(dte_min, 7), min(dte_max + 1, 90), 7):
            exp_date = sim_date + timedelta(days=dte)
            # Snap to Friday
            days_to_friday = (4 - exp_date.weekday()) % 7
            exp_date = exp_date + timedelta(days=days_to_friday)
            actual_dte = (exp_date - sim_date).days

            if actual_dte < dte_min or actual_dte > dte_max:
                continue

            exp_str = exp_date.strftime("%Y-%m-%d")

            # Generate strikes around ATM
            strike_step = max(1, round(price * 0.025))  # ~2.5% increments
            strikes = [
                round(price + i * strike_step, 0)
                for i in range(-6, 7)
                if (price + i * strike_step) > 0
            ]

            for strike in strikes:
                for ct in (["put", "call"] if not contract_type else [contract_type]):
                    # Black-Scholes-ish approximation for greeks
                    moneyness = (strike - price) / price if ct == "call" else (price - strike) / price
                    time_factor = math.sqrt(actual_dte / 365)

                    # Delta
                    if ct == "put":
                        raw_delta = -0.5 * math.exp(-moneyness / (iv * time_factor + 0.01))
                        raw_delta = max(-0.95, min(-0.02, raw_delta))
                    else:
                        raw_delta = 0.5 * math.exp(moneyness / (iv * time_factor + 0.01))
                        raw_delta = max(0.02, min(0.95, raw_delta))

                    # Price (simplified: use |delta| * price * time_factor * IV)
                    theoretical = abs(raw_delta) * price * time_factor * iv * 0.4
                    theoretical = max(0.01, theoretical)

                    # Bid/ask spread (~5-15% of theoretical)
                    spread_pct = 0.08
                    bid = round(max(0.01, theoretical * (1 - spread_pct)), 2)
                    ask = round(theoretical * (1 + spread_pct), 2)
                    mid = round((bid + ask) / 2, 2)

                    # Theta (approximate: -premium / DTE)
                    theta = round(-theoretical / max(actual_dte, 1), 4)

                    # OI/volume (synthetic — higher for ATM, lower for OTM)
                    atm_factor = max(0.1, 1 - abs(moneyness) * 5)
                    oi = int(500 * atm_factor + 50)
                    volume = int(100 * atm_factor + 10)

                    # OCC symbol format: SYMBOLYYMMDDTSSSSSSSS
                    strike_str = f"{int(strike * 1000):08d}"
                    ct_char = "C" if ct == "call" else "P"
                    occ = f"{symbol}{exp_date.strftime('%y%m%d')}{ct_char}{strike_str}"

                    chain.append({
                        "symbol": symbol,
                        "option_symbol": occ,
                        "strike": float(strike),
                        "expiration": exp_str,
                        "contract_type": ct,
                        "bid": bid,
                        "ask": ask,
                        "last": mid,
                        "volume": volume,
                        "open_interest": oi,
                        "implied_volatility": round(iv, 4),
                        "delta": round(raw_delta, 4),
                        "gamma": round(abs(raw_delta) * 0.05, 4),
                        "theta": theta,
                        "vega": round(price * time_factor * 0.01, 4),
                        "mid_price": mid,
                    })

        return chain

    async def submit_option_order(
        self,
        option_symbol: str,
        side: str,
        qty: int,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> dict:
        """Simulate order fill at limit price (or mid)."""
        fill_price = limit_price or 0.0

        order = {
            "order_id": f"bt-{self._next_order_id:06d}",
            "symbol": option_symbol,
            "side": side,
            "qty": qty,
            "type": order_type,
            "limit_price": fill_price,
            "filled_avg_price": fill_price,
            "status": "filled",
            "submitted_at": self._current_date,
        }
        self._next_order_id += 1
        self._orders.append(order)

        # Update cash for premium
        if side == "sell":
            self._cash += fill_price * qty * 100
        else:
            self._cash -= fill_price * qty * 100

        self._buying_power = self._cash

        return order

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        days_back: int = 60,
    ) -> list[dict]:
        """Return bars up to the current simulation date."""
        bars = self._bars_cache.get(symbol, [])
        if not bars:
            return []

        end_idx = min(self._current_day_idx + 1, len(bars))
        start_idx = max(0, end_idx - days_back)
        return bars[start_idx:end_idx]

    async def get_latest_quote(self, symbol: str) -> dict:
        """Return a quote from the current day's bar."""
        bars = self._bars_cache.get(symbol, [])
        if not bars or self._current_day_idx >= len(bars):
            return {}

        bar = bars[self._current_day_idx]
        price = bar["close"]
        return {
            "symbol": symbol,
            "bid": round(price * 0.999, 2),
            "ask": round(price * 1.001, 2),
            "bid_size": 100,
            "ask_size": 100,
            "timestamp": bar.get("timestamp", self._current_date),
        }

    async def get_orders(self, status: str = "open") -> list[dict]:
        if status == "open":
            return []  # All orders fill instantly in backtest
        return list(self._orders)

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_tradable_assets(self, options_enabled: bool = True) -> list[dict]:
        return [
            {
                "symbol": sym,
                "name": sym,
                "asset_type": "stock",
                "tradable": True,
                "options_enabled": True,
                "exchange": "NYSE",
            }
            for sym in self._bars_cache.keys()
        ]

    async def get_historical_bars_batch(
        self,
        symbols: list[str],
        timeframe: str = "1Day",
        days_back: int = 5,
    ) -> dict[str, list[dict]]:
        result = {}
        for sym in symbols:
            result[sym] = await self.get_historical_bars(sym, timeframe, days_back)
        return result


# ═══════════════════════════════════════════════════════════════════
#  Simulated Position Tracker
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SimulatedPosition:
    """A tracked simulated option position."""
    symbol: str            # Underlying
    option_symbol: str
    contract_type: str     # "put" or "call"
    strike: float
    expiration: str        # YYYY-MM-DD
    quantity: int          # negative = short
    entry_price: float     # per-share premium
    entry_date: str
    agent_name: str = ""

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


# ═══════════════════════════════════════════════════════════════════
#  BacktestEngine
# ═══════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Runs an agent's logic day-by-day against historical data.

    For each trading day:
    1. Update simulation date on the mock broker
    2. Reconstruct portfolio state (positions, cash)
    3. Handle expirations and assignments
    4. Run agent: scan → evaluate → execute → manage_positions
    5. Record equity curve point
    """

    AGENT_MAP = {
        "worker_csp": "CashSecuredPutWorker",
        "worker_cc": "CoveredCallWorker",
        "worker_wheel": "WheelWorker",
    }

    def __init__(
        self,
        agent_type: str,
        symbols: list[str],
        days: int = 180,
        param_overrides: Optional[dict] = None,
        initial_capital: float = 100_000.0,
        real_broker: Optional[Broker] = None,
    ):
        self.agent_type = agent_type
        self.symbols = symbols
        self.days = days
        self.param_overrides = param_overrides or {}
        self.initial_capital = initial_capital
        self._real_broker = real_broker

        # Internal state
        self._sim_positions: list[SimulatedPosition] = []
        self._sim_shares: dict[str, int] = defaultdict(int)  # symbol → shares held
        self._share_cost_basis: dict[str, float] = {}  # symbol → avg cost
        self._cash = initial_capital
        self._trade_log: list[dict] = []

    async def run(self) -> BacktestResult:
        """Execute the full backtest and return results."""
        logger.info(
            f"[Backtest] Starting: agent={self.agent_type}, "
            f"symbols={self.symbols}, days={self.days}, "
            f"overrides={self.param_overrides}"
        )

        # ── Initialize mock broker ──
        if not self._real_broker:
            from services.alpaca_broker import AlpacaBroker
            self._real_broker = AlpacaBroker()

        bt_broker = BacktestBroker(
            real_broker=self._real_broker,
            initial_capital=self.initial_capital,
        )

        # Load historical data (extra days for IV calculation lookback)
        await bt_broker.load_historical_data(
            self.symbols, days_back=self.days + 400
        )

        # Find the common trading days across all symbols
        trading_days = self._get_trading_days(bt_broker)
        if not trading_days:
            logger.error("[Backtest] No trading days found")
            return BacktestResult(agent_type=self.agent_type)

        # Trim to requested window
        if len(trading_days) > self.days:
            trading_days = trading_days[-self.days:]

        # ── Create agent with mock dependencies ──
        market_feed = MarketFeed(broker=bt_broker)
        options_chain = OptionsChainAnalyzer(broker=bt_broker)
        portfolio = Portfolio(
            cash=self.initial_capital,
            buying_power=self.initial_capital,
            equity=self.initial_capital,
        )
        risk_manager = RiskManager(portfolio)

        agent = self._create_agent(
            bt_broker, portfolio, risk_manager, market_feed, options_chain
        )

        # Apply parameter overrides
        for key, value in self.param_overrides.items():
            if hasattr(agent, key):
                setattr(agent, key, abs(float(value)) if isinstance(value, (int, float)) else value)
                logger.debug(f"[Backtest] Override: {key} = {value}")

        # Assign all symbols to the agent
        agent.assigned_securities = list(self.symbols)

        # ── Replay loop ──
        result = BacktestResult(
            agent_type=self.agent_type,
            symbols=list(self.symbols),
            param_overrides=dict(self.param_overrides),
            initial_capital=self.initial_capital,
        )

        logger.info(f"[Backtest] Replaying {len(trading_days)} trading days...")

        for day_idx, (abs_idx, date_str) in enumerate(trading_days):
            # Update simulation state
            bt_broker.set_simulation_date(date_str, abs_idx)

            # Handle expirations first
            self._handle_expirations(date_str, bt_broker)

            # Update portfolio from simulated state
            self._sync_portfolio(portfolio, bt_broker, date_str)
            bt_broker.update_account(self._cash, self._get_equity(bt_broker))
            bt_broker.set_positions(self._get_broker_positions(bt_broker))

            # Run agent cycle (every 3rd trading day to simulate realistic frequency)
            if day_idx % 3 == 0:
                try:
                    # Clear IV cache for the new day
                    market_feed.cache.clear()
                    market_feed._iv_history_loaded.clear()

                    # Run the lifecycle
                    position_actions = await agent.manage_positions()
                    self._process_position_actions(position_actions, date_str)

                    opportunities = await agent.scan()
                    trades = await agent.evaluate(opportunities)
                    executed = await agent.execute(trades)

                    # Record executed trades
                    for trade in executed:
                        if trade.get("status") == "filled" or trade.get("order_id"):
                            self._record_trade_entry(trade, date_str)

                except Exception as e:
                    logger.debug(f"[Backtest] Day {date_str} agent error: {e}")

            # Record equity curve point
            equity = self._get_equity(bt_broker)
            result.equity_curve.append((date_str, round(equity, 2)))

            # Progress log every 30 days
            if day_idx % 30 == 0 and day_idx > 0:
                pnl = equity - self.initial_capital
                logger.info(
                    f"[Backtest] Day {day_idx}/{len(trading_days)} "
                    f"({date_str}): equity=${equity:,.2f}, "
                    f"PnL=${pnl:+,.2f}, "
                    f"positions={len(self._sim_positions)}"
                )

        # ── Finalize ──
        result.trade_log = list(self._trade_log)
        result.final_value = self._get_equity(bt_broker)
        result.start_date = trading_days[0][1]
        result.end_date = trading_days[-1][1]
        result.days = len(trading_days)

        # Close any remaining open positions for final P&L
        self._close_remaining_positions(bt_broker, trading_days[-1][1])
        result.trade_log = list(self._trade_log)
        result.final_value = self._get_equity(bt_broker)

        result.compute_summary()

        logger.info(
            f"[Backtest] Complete: {result.total_return:+.2f}% return, "
            f"{result.trade_count} trades, "
            f"Sharpe={result.sharpe_ratio:.2f}"
        )

        return result

    # ── Agent Factory ─────────────────────────────────────────────

    def _create_agent(self, broker, portfolio, risk_manager, market_feed, options_chain):
        """Create the appropriate agent type with mock dependencies."""
        # Lazy import to avoid circular deps
        if self.agent_type == "worker_csp":
            from agents.worker_csp import CashSecuredPutWorker
            return CashSecuredPutWorker(
                broker=broker,
                portfolio=portfolio,
                risk_manager=risk_manager,
                market_feed=market_feed,
                options_chain=options_chain,
            )
        elif self.agent_type == "worker_cc":
            from agents.worker_cc import CoveredCallWorker
            return CoveredCallWorker(
                broker=broker,
                portfolio=portfolio,
                risk_manager=risk_manager,
                market_feed=market_feed,
                options_chain=options_chain,
            )
        elif self.agent_type == "worker_wheel":
            from agents.worker_wheel import WheelWorker
            return WheelWorker(
                broker=broker,
                portfolio=portfolio,
                risk_manager=risk_manager,
                market_feed=market_feed,
                options_chain=options_chain,
            )
        else:
            raise ValueError(f"Unknown agent type: {self.agent_type}")

    # ── Trading Days ──────────────────────────────────────────────

    def _get_trading_days(self, broker: BacktestBroker) -> list[tuple[int, str]]:
        """
        Get list of (absolute_index, date_string) for all trading days.
        Uses the first symbol's bar data as reference.
        """
        ref_symbol = self.symbols[0]
        bars = broker._bars_cache.get(ref_symbol, [])
        if not bars:
            return []

        days = []
        for i, bar in enumerate(bars):
            ts = bar.get("timestamp", "")
            if isinstance(ts, str) and len(ts) >= 10:
                date_str = ts[:10]
            else:
                try:
                    date_str = str(ts)[:10]
                except Exception:
                    continue
            days.append((i, date_str))

        return days

    # ── Position Management ───────────────────────────────────────

    def _record_trade_entry(self, trade: dict, date_str: str):
        """Record a new simulated position from an executed trade."""
        symbol = trade.get("symbol", "?")
        option_symbol = trade.get("option_symbol", "?")
        contract_type = trade.get("contract_type", "put")
        strike = trade.get("strike", 0)
        expiration = trade.get("expiration", "")
        qty = trade.get("qty", 1)
        limit_price = trade.get("limit_price", 0)
        side = trade.get("side", "sell")

        # Create simulated position
        sim_pos = SimulatedPosition(
            symbol=symbol,
            option_symbol=option_symbol,
            contract_type=contract_type,
            strike=strike,
            expiration=expiration,
            quantity=-qty if side == "sell" else qty,
            entry_price=limit_price,
            entry_date=date_str,
        )
        self._sim_positions.append(sim_pos)

        # Record in trade log
        self._trade_log.append({
            "symbol": symbol,
            "option_symbol": option_symbol,
            "contract_type": contract_type,
            "strike": strike,
            "expiration": expiration,
            "side": side,
            "qty": qty,
            "entry_price": limit_price,
            "premium": limit_price * qty * 100 if side == "sell" else 0,
            "entry_date": date_str,
            "exit_date": None,
            "exit_price": None,
            "realized_pnl": None,
            "status": "open",
        })

        # Update cash
        if side == "sell":
            self._cash += limit_price * qty * 100

    def _process_position_actions(self, actions: list[dict], date_str: str):
        """Process manage_positions results (close/roll actions)."""
        for action in actions:
            if action.get("action") in ("close", "roll", "profit_target", "expiry_close"):
                opt_sym = action.get("option_symbol", "")
                buy_price = action.get("buy_price", 0)
                realized_pnl = action.get("realized_pnl", 0)

                # Remove the position
                self._sim_positions = [
                    p for p in self._sim_positions if p.option_symbol != opt_sym
                ]

                # Update trade log
                for trade in self._trade_log:
                    if (
                        trade["option_symbol"] == opt_sym
                        and trade["status"] == "open"
                    ):
                        trade["exit_date"] = date_str
                        trade["exit_price"] = buy_price
                        trade["realized_pnl"] = realized_pnl
                        trade["status"] = "closed"
                        break

                # Update cash
                self._cash -= buy_price * 100  # buying to close

    def _handle_expirations(self, date_str: str, broker: BacktestBroker):
        """Handle option expirations on this date."""
        expired = []
        for pos in self._sim_positions:
            if pos.expiration <= date_str:
                expired.append(pos)

        for pos in expired:
            self._sim_positions.remove(pos)

            # Check if ITM at expiration
            bars = broker._bars_cache.get(pos.symbol, [])
            current_idx = broker._current_day_idx
            stock_price = bars[current_idx]["close"] if current_idx < len(bars) else 0

            pnl = 0.0
            assigned = False

            if pos.is_short:
                if pos.contract_type == "put" and stock_price < pos.strike:
                    # Put assigned — we buy shares at strike
                    assigned = True
                    self._sim_shares[pos.symbol] += abs(pos.quantity) * 100
                    self._share_cost_basis[pos.symbol] = pos.strike
                    self._cash -= pos.strike * abs(pos.quantity) * 100
                    pnl = pos.entry_price * abs(pos.quantity) * 100  # Keep premium
                    logger.debug(
                        f"[Backtest] {pos.symbol} put assigned @ ${pos.strike} "
                        f"(stock=${stock_price:.2f})"
                    )
                elif pos.contract_type == "call" and stock_price > pos.strike:
                    # Call assigned — we sell shares at strike
                    assigned = True
                    shares_to_sell = min(
                        self._sim_shares.get(pos.symbol, 0),
                        abs(pos.quantity) * 100,
                    )
                    if shares_to_sell > 0:
                        self._sim_shares[pos.symbol] -= shares_to_sell
                        self._cash += pos.strike * shares_to_sell
                        cost = self._share_cost_basis.get(pos.symbol, pos.strike)
                        pnl = (pos.strike - cost) * shares_to_sell
                        pnl += pos.entry_price * abs(pos.quantity) * 100
                    logger.debug(
                        f"[Backtest] {pos.symbol} call assigned @ ${pos.strike} "
                        f"(stock=${stock_price:.2f})"
                    )
                else:
                    # OTM — expired worthless (we keep full premium)
                    pnl = pos.entry_price * abs(pos.quantity) * 100

            # Update trade log
            for trade in self._trade_log:
                if (
                    trade["option_symbol"] == pos.option_symbol
                    and trade["status"] == "open"
                ):
                    trade["exit_date"] = date_str
                    trade["exit_price"] = 0 if not assigned else None
                    trade["realized_pnl"] = round(pnl, 2)
                    trade["status"] = "assigned" if assigned else "expired"
                    break

    def _close_remaining_positions(self, broker: BacktestBroker, date_str: str):
        """Close all remaining positions at market price for final accounting."""
        for pos in list(self._sim_positions):
            bars = broker._bars_cache.get(pos.symbol, [])
            idx = broker._current_day_idx
            if idx < len(bars):
                stock_price = bars[idx]["close"]
            else:
                stock_price = pos.strike

            # Estimate current option price (intrinsic + small time value)
            if pos.contract_type == "put":
                intrinsic = max(0, pos.strike - stock_price)
            else:
                intrinsic = max(0, stock_price - pos.strike)
            est_price = intrinsic + 0.05  # tiny time value at close

            if pos.is_short:
                pnl = (pos.entry_price - est_price) * abs(pos.quantity) * 100
                self._cash -= est_price * abs(pos.quantity) * 100
            else:
                pnl = (est_price - pos.entry_price) * pos.quantity * 100
                self._cash += est_price * pos.quantity * 100

            for trade in self._trade_log:
                if (
                    trade["option_symbol"] == pos.option_symbol
                    and trade["status"] == "open"
                ):
                    trade["exit_date"] = date_str
                    trade["exit_price"] = est_price
                    trade["realized_pnl"] = round(pnl, 2)
                    trade["status"] = "closed_eod"
                    break

        self._sim_positions.clear()

        # Liquidate any shares at market price
        for symbol, shares in list(self._sim_shares.items()):
            if shares > 0:
                bars = broker._bars_cache.get(symbol, [])
                idx = broker._current_day_idx
                if idx < len(bars):
                    price = bars[idx]["close"]
                else:
                    price = self._share_cost_basis.get(symbol, 0)
                self._cash += price * shares
                self._sim_shares[symbol] = 0

    def _sync_portfolio(self, portfolio: Portfolio, broker: BacktestBroker, date_str: str):
        """Sync the mock portfolio state for the agent to use."""
        portfolio.cash = self._cash
        portfolio.buying_power = self._cash
        portfolio.equity = self._get_equity(broker)

        # Rebuild stock positions
        portfolio.positions = {}
        for symbol, shares in self._sim_shares.items():
            if shares > 0:
                bars = broker._bars_cache.get(symbol, [])
                idx = broker._current_day_idx
                current_price = bars[idx]["close"] if idx < len(bars) else 0
                cost = self._share_cost_basis.get(symbol, current_price)
                portfolio.positions[symbol] = Position(
                    symbol=symbol,
                    quantity=shares,
                    avg_cost=cost,
                    current_price=current_price,
                )

        # Rebuild option positions
        portfolio.options = []
        for pos in self._sim_positions:
            # Estimate current option price
            bars = broker._bars_cache.get(pos.symbol, [])
            idx = broker._current_day_idx
            stock_price = bars[idx]["close"] if idx < len(bars) else pos.strike

            if pos.contract_type == "put":
                intrinsic = max(0, pos.strike - stock_price)
            else:
                intrinsic = max(0, stock_price - pos.strike)

            # Time value decay
            try:
                exp = datetime.strptime(pos.expiration, "%Y-%m-%d")
                sim = datetime.strptime(date_str, "%Y-%m-%d")
                dte = max(0, (exp - sim).days)
            except ValueError:
                dte = 30

            time_value = pos.entry_price * (dte / 45) * 0.3  # Rough decay
            est_price = max(0.01, intrinsic + time_value)

            portfolio.options.append(OptionsPosition(
                symbol=pos.symbol,
                option_symbol=pos.option_symbol,
                contract_type=pos.contract_type,
                strike=pos.strike,
                expiration=pos.expiration,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=est_price,
                premium_collected=pos.entry_price if pos.is_short else 0,
                assigned_to=pos.agent_name,
            ))

    def _get_equity(self, broker: BacktestBroker) -> float:
        """Calculate total equity (cash + stock positions + option positions)."""
        equity = self._cash

        # Stock positions
        for symbol, shares in self._sim_shares.items():
            if shares > 0:
                bars = broker._bars_cache.get(symbol, [])
                idx = broker._current_day_idx
                if idx < len(bars):
                    equity += bars[idx]["close"] * shares

        # Option positions (approximate mark-to-market)
        for pos in self._sim_positions:
            bars = broker._bars_cache.get(pos.symbol, [])
            idx = broker._current_day_idx
            if idx < len(bars):
                stock_price = bars[idx]["close"]
                if pos.contract_type == "put":
                    intrinsic = max(0, pos.strike - stock_price)
                else:
                    intrinsic = max(0, stock_price - pos.strike)
                est_price = max(0.01, intrinsic + pos.entry_price * 0.3)
                if pos.is_short:
                    equity -= est_price * abs(pos.quantity) * 100
                else:
                    equity += est_price * pos.quantity * 100

        return equity

    def _get_broker_positions(self, broker: BacktestBroker) -> list[dict]:
        """Build positions list for the mock broker."""
        positions = []

        for symbol, shares in self._sim_shares.items():
            if shares > 0:
                bars = broker._bars_cache.get(symbol, [])
                idx = broker._current_day_idx
                price = bars[idx]["close"] if idx < len(bars) else 0
                cost = self._share_cost_basis.get(symbol, price)
                positions.append({
                    "symbol": symbol,
                    "qty": shares,
                    "avg_cost": cost,
                    "current_price": price,
                    "unrealized_pl": (price - cost) * shares,
                    "asset_class": "us_equity",
                    "side": "long",
                })

        for pos in self._sim_positions:
            positions.append({
                "symbol": pos.option_symbol,
                "qty": pos.quantity,
                "avg_cost": pos.entry_price,
                "current_price": pos.entry_price * 0.7,  # Rough estimate
                "unrealized_pl": 0,
                "asset_class": "us_option",
                "side": "short" if pos.is_short else "long",
            })

        return positions


# ═══════════════════════════════════════════════════════════════════
#  Compare utility
# ═══════════════════════════════════════════════════════════════════

async def compare_backtests(
    agent_type: str,
    symbols: list[str],
    days: int,
    params_a: dict,
    params_b: dict,
    initial_capital: float = 100_000.0,
    real_broker: Optional[Broker] = None,
) -> tuple[BacktestResult, BacktestResult]:
    """
    Run two backtests with different parameters and return both results.
    The historical data is loaded once and shared.
    """
    logger.info(f"[Compare] Running side-by-side: A={params_a} vs B={params_b}")

    engine_a = BacktestEngine(
        agent_type=agent_type,
        symbols=symbols,
        days=days,
        param_overrides=params_a,
        initial_capital=initial_capital,
        real_broker=real_broker,
    )
    result_a = await engine_a.run()

    engine_b = BacktestEngine(
        agent_type=agent_type,
        symbols=symbols,
        days=days,
        param_overrides=params_b,
        initial_capital=initial_capital,
        real_broker=real_broker,
    )
    result_b = await engine_b.run()

    return result_a, result_b


def print_comparison(result_a: BacktestResult, result_b: BacktestResult):
    """Print a side-by-side comparison table."""
    print("\n" + "═" * 70)
    print("  BACKTEST COMPARISON")
    print("═" * 70)
    print(f"  {'Metric':<25} {'Param Set A':>20} {'Param Set B':>20}")
    print("─" * 70)

    metrics = [
        ("Total Return", f"{result_a.total_return:+.2f}%", f"{result_b.total_return:+.2f}%"),
        ("Annual Return", f"{result_a.annualized_return:+.2f}%", f"{result_b.annualized_return:+.2f}%"),
        ("Sharpe Ratio", f"{result_a.sharpe_ratio:.2f}", f"{result_b.sharpe_ratio:.2f}"),
        ("Sortino Ratio", f"{result_a.sortino_ratio:.2f}", f"{result_b.sortino_ratio:.2f}"),
        ("Max Drawdown", f"{result_a.max_drawdown:.2f}%", f"{result_b.max_drawdown:.2f}%"),
        ("Win Rate", f"{result_a.win_rate:.1f}%", f"{result_b.win_rate:.1f}%"),
        ("Trade Count", f"{result_a.trade_count}", f"{result_b.trade_count}"),
        ("Avg Winner", f"${result_a.avg_winner:,.2f}", f"${result_b.avg_winner:,.2f}"),
        ("Avg Loser", f"${result_a.avg_loser:,.2f}", f"${result_b.avg_loser:,.2f}"),
        ("Profit Factor", f"{result_a.profit_factor:.2f}", f"{result_b.profit_factor:.2f}"),
        ("Premium Collected", f"${result_a.total_premium_collected:,.2f}", f"${result_b.total_premium_collected:,.2f}"),
        ("Final Value", f"${result_a.final_value:,.2f}", f"${result_b.final_value:,.2f}"),
    ]

    for label, val_a, val_b in metrics:
        # Highlight winner
        print(f"  {label:<25} {val_a:>20} {val_b:>20}")

    print("─" * 70)
    print(f"  Params A: {result_a.param_overrides}")
    print(f"  Params B: {result_b.param_overrides}")
    print("═" * 70)
    print()

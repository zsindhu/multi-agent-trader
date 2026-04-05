"""
Market Regime Service — Computes macro environment signals for premium selling decisions.

Combines VIX direction, market breadth, SPY trend, sector rotation, and credit stress
into a single regime classification: "risk_on", "neutral", "risk_off", or "crisis".

Runs twice daily (9:35 AM and 12:30 PM ET), right after the Scanner cycle.
All data fetched via the Broker interface (Alpaca). No external APIs required.
"""
import json
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from loguru import logger
from sqlalchemy import select, desc

from core.database import AsyncSessionLocal
from models.regime_snapshot import RegimeSnapshot

if TYPE_CHECKING:
    from core.broker import Broker
    from agents.scanner import ScannerAgent
    from core.strategy import StrategyManager


_SP500_SAMPLE = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "BRK.B", "LLY", "AVGO", "JPM",
    "UNH", "XOM", "V", "TSLA", "PG", "MA", "COST", "JNJ", "HD", "MRK",
    "CVX", "ABBV", "BAC", "KO", "WMT", "PEP", "ADBE", "CRM", "ACN", "MCD",
    "TMO", "CSCO", "LIN", "DHR", "NKE", "TXN", "ABT", "NEE", "PM", "WFC",
    "RTX", "AMGN", "ORCL", "INTC", "QCOM", "IBM", "HON", "CAT", "GS", "SPGI",
]

_BREADTH_CACHE_TTL = timedelta(minutes=15)

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLRE": "Real Estate",
    "XBI": "Biotech",
}

DEFENSIVE_SECTORS = {"XLV", "XLRE"}
CYCLICAL_SECTORS = {"XLK", "XLF", "XLE"}


class MarketRegimeService:
    """
    Computes comprehensive market regime by combining multiple macro signals.

    Accepts broker, scanner, and strategy_manager to reuse existing data where
    possible rather than making redundant API calls.
    """

    def __init__(
        self,
        broker: Optional["Broker"] = None,
        scanner: Optional["ScannerAgent"] = None,
        strategy_manager: Optional["StrategyManager"] = None,
    ):
        self.broker = broker
        self.scanner = scanner
        self.strategy_manager = strategy_manager
        self._breadth_cache: Optional[tuple] = None  # (pct, trend, computed_at)

    # ── Public API ──────────────────────────────────────────────────

    async def compute(self) -> dict:
        """Run full regime computation and persist to DB. Returns the snapshot dict."""
        logger.info("[Regime] Computing market regime...")
        try:
            snapshot = await self._compute_snapshot()
            await self._persist(snapshot)
            logger.info(
                f"[Regime] Regime: {snapshot['regime']} "
                f"(confidence={snapshot['confidence']:.0%}, "
                f"VIX={snapshot['vix_level']:.1f}, "
                f"breadth={snapshot['breadth_pct']:.0f}%)"
            )
            return snapshot
        except Exception as e:
            logger.error(f"[Regime] Compute failed: {e}")
            return {}

    async def get_latest(self) -> dict:
        """Return the most recent RegimeSnapshot as a dict."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RegimeSnapshot)
                .order_by(desc(RegimeSnapshot.computed_at))
                .limit(1)
            )
            row = result.scalar_one_or_none()
        if not row:
            return {"regime": "unknown", "summary": "No regime data yet."}
        return self._to_dict(row)

    async def get_history(self, days: int = 7) -> list[dict]:
        """Return regime snapshots over the last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RegimeSnapshot)
                .where(RegimeSnapshot.computed_at >= cutoff)
                .order_by(desc(RegimeSnapshot.computed_at))
            )
            rows = list(result.scalars().all())
        return [self._to_dict(r) for r in rows]

    async def get_regime_detail(self, metric: str) -> dict:
        """Return expanded detail for a specific metric from the latest snapshot."""
        latest = await self.get_latest()
        if metric == "sectors" and latest.get("sector_returns"):
            try:
                returns = json.loads(latest["sector_returns"])
                return {"sector_returns": returns, "leader": latest.get("sector_leader"),
                        "laggard": latest.get("sector_laggard"),
                        "rotation_signal": latest.get("rotation_signal")}
            except Exception:
                pass
        return {metric: latest.get(metric)}

    # ── Internal computation ─────────────────────────────────────────

    async def _compute_snapshot(self) -> dict:
        vix_level, vix_direction = await self._get_vix()
        breadth_pct, breadth_trend = await self._get_breadth()
        spy_trend, spy_dist_20ma = await self._get_spy_trend()
        sector_returns, rotation_signal, sector_leader, sector_laggard = await self._get_sectors()
        credit_stress = await self._get_credit_stress()

        regime, confidence = self._classify(
            vix_level, breadth_pct, spy_trend, rotation_signal, credit_stress
        )
        summary = self._build_summary(
            regime, vix_level, breadth_pct, spy_trend, rotation_signal, credit_stress
        )

        return {
            "regime": regime,
            "confidence": confidence,
            "vix_level": vix_level,
            "vix_direction": vix_direction,
            "breadth_pct": breadth_pct,
            "breadth_trend": breadth_trend,
            "spy_trend": spy_trend,
            "spy_distance_from_20ma": spy_dist_20ma,
            "sector_leader": sector_leader,
            "sector_laggard": sector_laggard,
            "rotation_signal": rotation_signal,
            "credit_stress": credit_stress,
            "summary": summary,
            "sector_returns": json.dumps(sector_returns),
        }

    async def _get_vix(self) -> tuple[float, str]:
        """Get VIX level (via proxy) and 5-day direction."""
        # Delegate to existing StrategyManager if available — avoids duplication
        if self.strategy_manager:
            try:
                await self.strategy_manager.refresh_regime()
                vix = self.strategy_manager.vix_level
                if vix and vix > 0:
                    direction = await self._get_vix_direction(vix)
                    return vix, direction
            except Exception as e:
                logger.debug(f"[Regime] StrategyManager VIX failed: {e}")

        # Fallback: fetch VIX proxy directly
        if not self.broker:
            return 20.0, "flat"

        vix_proxies = ["VIXY", "VXX", "UVXY"]
        for proxy in vix_proxies:
            try:
                quote = await self.broker.get_latest_quote(proxy)
                if quote and quote.get("bid", 0) > 0:
                    mid = (quote["bid"] + quote["ask"]) / 2
                    if proxy == "VIXY":
                        vix = mid / 0.6
                    elif proxy == "UVXY":
                        vix = mid / 1.5
                    else:
                        vix = mid
                    vix = max(8.0, min(80.0, vix))
                    direction = await self._get_vix_direction(vix)
                    return round(vix, 1), direction
            except Exception:
                continue

        return 20.0, "flat"

    async def _get_vix_direction(self, current_vix: float) -> str:
        """Classify VIX direction using 5-day proxy bar change."""
        if not self.broker:
            return "flat"
        try:
            bars = await self.broker.get_historical_bars("VIXY", timeframe="1Day", days_back=10)
            if bars and len(bars) >= 6:
                old_mid = bars[-6].get("close", 0)
                new_mid = bars[-1].get("close", 0)
                if old_mid > 0:
                    change_pct = (new_mid - old_mid) / old_mid
                    if change_pct > 0.05:
                        return "rising"
                    elif change_pct < -0.05:
                        return "falling"
        except Exception:
            pass
        return "flat"

    async def _get_breadth(self) -> tuple[float, str]:
        """
        Compute % of a fixed 50-symbol S&P 500 sample above their 50-day SMA.
        Results are cached for 15 minutes to avoid redundant API calls.
        """
        now = datetime.utcnow()
        if self._breadth_cache and (now - self._breadth_cache[2]) < _BREADTH_CACHE_TTL:
            return self._breadth_cache[0], self._breadth_cache[1]

        if not self.broker:
            return 50.0, "stable"

        above = 0
        total = 0
        for symbol in _SP500_SAMPLE:
            try:
                bars = await self.broker.get_historical_bars(symbol, timeframe="1Day", days_back=60)
                if bars and len(bars) >= 50:
                    closes = [b["close"] for b in bars]
                    sma50 = sum(closes[-50:]) / 50
                    if closes[-1] >= sma50:
                        above += 1
                    total += 1
            except Exception:
                continue

        if total == 0:
            return 50.0, "stable"

        pct = round((above / total) * 100, 1)
        trend = self._breadth_trend(pct)
        self._breadth_cache = (pct, trend, now)
        logger.debug(f"[Regime] Breadth from S&P500 universe: {pct:.0f}% ({above}/{total} symbols above 50MA)")
        return pct, trend

    def _breadth_trend(self, pct: float) -> str:
        if pct > 60:
            return "improving"
        elif pct < 40:
            return "deteriorating"
        return "stable"

    async def _get_spy_trend(self) -> tuple[str, float]:
        """Compute SPY 20MA/50MA trend and distance from 20MA."""
        if not self.broker:
            return "unknown", 0.0
        try:
            bars = await self.broker.get_historical_bars("SPY", timeframe="1Day", days_back=60)
            if not bars or len(bars) < 20:
                return "unknown", 0.0

            closes = [b.get("close", 0) for b in bars]
            current = closes[-1]
            ma20 = sum(closes[-20:]) / 20
            ma50 = sum(closes[-50:]) / len(closes[-50:]) if len(closes) >= 50 else sum(closes) / len(closes)

            dist_20ma = ((current - ma20) / ma20) * 100 if ma20 > 0 else 0.0

            if current > ma20 and current > ma50:
                trend = "uptrend"
            elif current > ma50 and current <= ma20:
                trend = "pullback"
            else:
                trend = "downtrend"

            return trend, round(dist_20ma, 2)
        except Exception as e:
            logger.debug(f"[Regime] SPY trend failed: {e}")
            return "unknown", 0.0

    async def _get_sectors(self) -> tuple[dict, str, str, str]:
        """Compute 5-day returns for sector ETFs and classify rotation."""
        if not self.broker:
            return {}, "neutral", "", ""

        sector_returns = {}
        for etf in SECTOR_ETFS:
            try:
                bars = await self.broker.get_historical_bars(etf, timeframe="1Day", days_back=10)
                if bars and len(bars) >= 6:
                    old_close = bars[-6].get("close", 0)
                    new_close = bars[-1].get("close", 0)
                    if old_close > 0:
                        ret = ((new_close - old_close) / old_close) * 100
                        sector_returns[etf] = round(ret, 2)
            except Exception as e:
                logger.debug(f"[Regime] Sector {etf} failed: {e}")

        if not sector_returns:
            return {}, "neutral", "", ""

        sorted_sectors = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
        leader_etf = sorted_sectors[0][0] if sorted_sectors else ""
        laggard_etf = sorted_sectors[-1][0] if sorted_sectors else ""
        leader = f"{leader_etf} ({SECTOR_ETFS.get(leader_etf, leader_etf)})"
        laggard = f"{laggard_etf} ({SECTOR_ETFS.get(laggard_etf, laggard_etf)})"

        # Risk-off: defensive outperforming cyclical by > 1.5%
        def_avg = sum(sector_returns.get(s, 0) for s in DEFENSIVE_SECTORS) / len(DEFENSIVE_SECTORS)
        cyc_avg = sum(sector_returns.get(s, 0) for s in CYCLICAL_SECTORS) / len(CYCLICAL_SECTORS)

        if def_avg - cyc_avg > 1.5:
            rotation = "risk_off"
        elif cyc_avg - def_avg > 1.5:
            rotation = "risk_on"
        else:
            rotation = "neutral"

        return sector_returns, rotation, leader, laggard

    async def _get_credit_stress(self) -> bool:
        """Check HYG vs TLT 10-day returns for credit stress signal."""
        if not self.broker:
            return False
        try:
            hyg_bars = await self.broker.get_historical_bars("HYG", timeframe="1Day", days_back=20)
            tlt_bars = await self.broker.get_historical_bars("TLT", timeframe="1Day", days_back=20)

            if hyg_bars and tlt_bars and len(hyg_bars) >= 11 and len(tlt_bars) >= 11:
                hyg_ret = ((hyg_bars[-1]["close"] - hyg_bars[-11]["close"]) / hyg_bars[-11]["close"]) * 100
                tlt_ret = ((tlt_bars[-1]["close"] - tlt_bars[-11]["close"]) / tlt_bars[-11]["close"]) * 100
                # Credit stress: HYG underperforming TLT by > 2%
                if tlt_ret - hyg_ret > 2.0:
                    logger.debug(f"[Regime] Credit stress: HYG {hyg_ret:.1f}% vs TLT {tlt_ret:.1f}%")
                    return True
        except Exception as e:
            logger.debug(f"[Regime] Credit stress check failed: {e}")
        return False

    def _classify(
        self,
        vix: float,
        breadth: float,
        spy_trend: str,
        rotation: str,
        credit_stress: bool,
    ) -> tuple[str, float]:
        """Combine signals into regime + confidence score."""
        signals_risk_on = 0
        signals_risk_off = 0
        total = 5  # number of signals

        # VIX
        if vix < 20:
            signals_risk_on += 1
        elif vix > 25:
            signals_risk_off += 1

        # Breadth
        if breadth > 55:
            signals_risk_on += 1
        elif breadth < 45:
            signals_risk_off += 1

        # SPY trend
        if spy_trend == "uptrend":
            signals_risk_on += 1
        elif spy_trend == "downtrend":
            signals_risk_off += 1

        # Sector rotation
        if rotation == "risk_on":
            signals_risk_on += 1
        elif rotation == "risk_off":
            signals_risk_off += 1

        # Credit stress
        if not credit_stress:
            signals_risk_on += 1
        else:
            signals_risk_off += 1

        # Crisis: breadth < 30 AND VIX > 30 AND credit stress
        if breadth < 30 and vix > 30 and credit_stress:
            return "crisis", round(signals_risk_off / total, 2)

        # Risk-off: any strong signal
        if signals_risk_off >= 3 or (vix > 25 and breadth < 45) or (spy_trend == "downtrend" and credit_stress):
            return "risk_off", round(signals_risk_off / total, 2)

        # Risk-on: multiple confirming signals
        if signals_risk_on >= 4:
            return "risk_on", round(signals_risk_on / total, 2)

        return "neutral", round(max(signals_risk_on, signals_risk_off) / total, 2)

    def _build_summary(
        self, regime: str, vix: float, breadth: float,
        spy_trend: str, rotation: str, credit_stress: bool,
    ) -> str:
        regime_label = {
            "risk_on": "Risk-on environment",
            "neutral": "Neutral environment",
            "risk_off": "Risk-off environment",
            "crisis": "Crisis conditions",
        }.get(regime, regime)

        parts = [f"{regime_label}: VIX {vix:.0f}"]
        parts.append(f"breadth {breadth:.0f}% above 50MA")
        parts.append(f"SPY in {spy_trend.replace('_', ' ')}")
        if credit_stress:
            parts.append("credit stress detected")
        if rotation != "neutral":
            parts.append(f"{rotation.replace('_', ' ')} sector rotation")
        return ", ".join(parts) + "."

    async def _persist(self, snapshot: dict):
        async with AsyncSessionLocal() as session:
            row = RegimeSnapshot(
                regime=snapshot["regime"],
                confidence=snapshot["confidence"],
                vix_level=snapshot.get("vix_level"),
                vix_direction=snapshot.get("vix_direction"),
                breadth_pct=snapshot.get("breadth_pct"),
                breadth_trend=snapshot.get("breadth_trend"),
                spy_trend=snapshot.get("spy_trend"),
                spy_distance_from_20ma=snapshot.get("spy_distance_from_20ma"),
                sector_leader=snapshot.get("sector_leader"),
                sector_laggard=snapshot.get("sector_laggard"),
                rotation_signal=snapshot.get("rotation_signal"),
                credit_stress=snapshot.get("credit_stress"),
                summary=snapshot.get("summary"),
                sector_returns=snapshot.get("sector_returns"),
            )
            session.add(row)
            await session.commit()

    @staticmethod
    def _to_dict(row: RegimeSnapshot) -> dict:
        return {
            "id": row.id,
            "regime": row.regime,
            "confidence": row.confidence,
            "vix_level": row.vix_level,
            "vix_direction": row.vix_direction,
            "breadth_pct": row.breadth_pct,
            "breadth_trend": row.breadth_trend,
            "spy_trend": row.spy_trend,
            "spy_distance_from_20ma": row.spy_distance_from_20ma,
            "sector_leader": row.sector_leader,
            "sector_laggard": row.sector_laggard,
            "rotation_signal": row.rotation_signal,
            "credit_stress": row.credit_stress,
            "summary": row.summary,
            "sector_returns": json.loads(row.sector_returns) if row.sector_returns else {},
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }

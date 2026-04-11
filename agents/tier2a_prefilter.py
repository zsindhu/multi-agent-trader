"""
Tier 2a Mechanical Pre-filter — Change-detection rules over Tier 1 universe.

Reads today's Tier 1 passes from name_observations, fetches 60-day bars
from historical_bars, applies 6 change-detection rules, and writes new
tier=2 rows for every symbol (pass, reject, near-miss) with full signal
transparency.

No LLM calls. Pure mechanical signal scoring. The LLM reasoning layer
(Tier 2b) comes in Batch 1.4.0b-b, layered on top of this output.

Runs every 2 hours during market hours (10 AM, 12 PM, 2 PM ET).
"""
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import select, delete, func as sa_func

from agents.base_agent import BaseAgent
from core.database import AsyncSessionLocal
from models.historical_bar import HistoricalBar
from models.name_observation import NameObservation
from models.news_headline import NewsHeadline
from models.agent_action import AgentAction
from services.signal_compute import (
    volume_zscore,
    range_expansion_vs_atr,
    gap_zscore,
    iv_rank_delta,
    correlation_breakdown,
    news_density_zscore,
)


class Tier2aPrefilter(BaseAgent):
    """Tier 2a: mechanical change-detection filter over the Tier 1 universe."""

    def __init__(self, broker, market_feed=None, config_path: str = "config/tier2a.yaml"):
        super().__init__(name="Tier2a-Prefilter", agent_type="analyst")
        self.broker = broker
        self.market_feed = market_feed
        self.config = self._load_config(config_path)

    @staticmethod
    def _load_config(path: str) -> dict:
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            return raw.get("tier2a_prefilter", {})
        except FileNotFoundError:
            logger.warning(f"[Tier2a] Config not found at {path}, using defaults")
            return {}
        except Exception as e:
            logger.error(f"[Tier2a] Failed to load config: {e}")
            return {}

    # ── BaseAgent lifecycle (not used) ───────────────────────────

    async def scan(self) -> list:
        return []

    async def evaluate(self, opportunities) -> list:
        return []

    async def execute(self, trades) -> list:
        return []

    async def manage_positions(self) -> list:
        return []

    # ── Main sweep ───────────────────────────────────────────────

    async def run_sweep(self, dry_run: bool = False) -> dict:
        """
        Run the Tier 2a mechanical pre-filter over today's Tier 1 universe.

        Returns a summary dict with counts.
        """
        cfg = self.config
        rules_cfg = cfg.get("rules", {})
        min_signals = cfg.get("min_signals_to_fire", 2)
        near_miss_count = cfg.get("near_miss_count", 30)
        batch_size = cfg.get("batch_size", 100)
        progress_interval = cfg.get("progress_log_interval", 500)

        start_time = datetime.now(timezone.utc)
        await self._log_action("tier2a_sweep_started", "in_progress", None, {"dry_run": dry_run})
        logger.info(f"[Tier2a] Sweep starting (dry_run={dry_run})")

        # Step 1: Get today's Tier 1 passes
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(NameObservation.symbol, NameObservation.price, NameObservation.asset_type)
                    .where(NameObservation.tier == 1)
                    .where(NameObservation.was_considered == True)
                    .where(NameObservation.timestamp >= today_start)
                )
                tier1_rows = result.all()
        except Exception as e:
            logger.error(f"[Tier2a] Failed to fetch Tier 1 universe: {e}")
            await self._log_action("tier2a_sweep_failed", "failed", str(e), None)
            return {"error": str(e)}

        if not tier1_rows:
            logger.warning("[Tier2a] No Tier 1 passes found for today — is the Breadth Analyst sweep current?")
            await self._log_action("tier2a_sweep_failed", "failed", "no_tier1_data", None)
            return {"error": "no_tier1_data", "passed": 0, "rejected": 0}

        symbols = [r[0] for r in tier1_rows]
        tier1_map = {r[0]: {"price": r[1], "asset_type": r[2]} for r in tier1_rows}
        logger.info(f"[Tier2a] Processing {len(symbols)} Tier 1 passes")

        # Step 2: Fetch SPY bars once (for correlation rule)
        spy_closes = await self._get_closes(
            "SPY", cfg.get("rules", {}).get("correlation_breakdown", {}).get("long_window", 60) + 5
        )

        # Step 3: Score each symbol
        scored = []
        errors = 0

        for idx, symbol in enumerate(symbols):
            try:
                result = await self._score_symbol(symbol, tier1_map.get(symbol, {}), spy_closes, rules_cfg)
                scored.append(result)
            except Exception as e:
                logger.debug(f"[Tier2a] Scoring failed for {symbol}: {e}")
                errors += 1
                scored.append({
                    "symbol": symbol,
                    "total_score": 0.0,
                    "signals_fired": 0,
                    "signals": {},
                    "passed": False,
                    "reason": f"scoring_error: {str(e)[:100]}",
                    "asset_type": tier1_map.get(symbol, {}).get("asset_type"),
                    "price": tier1_map.get(symbol, {}).get("price"),
                })

            if (idx + 1) % progress_interval == 0:
                logger.info(f"[Tier2a] Progress: {idx + 1}/{len(symbols)} scored")

        # Step 4: Determine passes, rejects, near-misses
        # Sort by total_score descending
        scored.sort(key=lambda x: x["total_score"], reverse=True)

        passed = [s for s in scored if s["passed"]]
        rejected_all = [s for s in scored if not s["passed"]]

        # Near-misses: top N rejects that had at least 1 signal fire
        near_misses = [s for s in rejected_all if s["signals_fired"] >= 1][:near_miss_count]
        near_miss_symbols = {s["symbol"] for s in near_misses}
        rejected = [s for s in rejected_all if s["symbol"] not in near_miss_symbols]

        logger.info(
            f"[Tier2a] Scored {len(symbols)}: {len(passed)} passed, "
            f"{len(rejected)} rejected, {len(near_misses)} near-misses, {errors} errors"
        )

        # Step 5: Write to name_observations
        if not dry_run:
            # Clear today's tier=2 rows (idempotent re-runs)
            try:
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        delete(NameObservation).where(
                            NameObservation.tier == 2,
                            NameObservation.timestamp >= today_start,
                        )
                    )
                    await session.commit()
            except Exception as e:
                logger.error(f"[Tier2a] Failed to clear old tier 2 rows: {e}")

            await self._write_observations(passed, "tier2a_pass", near_misses, rejected)
        else:
            logger.info(f"[Tier2a] DRY RUN — would write {len(passed) + len(rejected) + len(near_misses)} observations")

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary = {
            "passed": len(passed),
            "rejected": len(rejected),
            "near_misses": len(near_misses),
            "errors": errors,
            "elapsed_seconds": round(elapsed, 1),
            "dry_run": dry_run,
        }
        await self._log_action("tier2a_sweep_completed", "executed", None, summary)
        logger.info(f"[Tier2a] Sweep complete: {summary}")
        return summary

    # ── Per-symbol scoring ───────────────────────────────────────

    async def _score_symbol(
        self, symbol: str, tier1_info: dict, spy_closes: list[float],
        rules_cfg: dict,
    ) -> dict:
        """Score a single symbol across all enabled rules."""
        cfg = self.config
        min_signals = cfg.get("min_signals_to_fire", 2)

        # Fetch bars for this symbol
        bars = await self._get_bars(symbol, 65)

        if len(bars) < 10:
            return {
                "symbol": symbol,
                "total_score": 0.0,
                "signals_fired": 0,
                "signals": {},
                "passed": False,
                "reason": "insufficient_bars",
                "asset_type": tier1_info.get("asset_type"),
                "price": tier1_info.get("price"),
            }

        # Extract arrays (most-recent-first from DB query)
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        opens = [b.open for b in bars]
        volumes = [b.volume for b in bars]

        signals = {}
        total_weight = 0.0
        weighted_score = 0.0

        # Rule 1: Volume z-score
        r1_cfg = rules_cfg.get("volume_zscore", {})
        if r1_cfg.get("enabled", True):
            r1 = volume_zscore(volumes, r1_cfg.get("window", 60))
            signals["volume_zscore"] = r1
            w = r1_cfg.get("weight", 0.20)
            weighted_score += r1["score"] * w
            total_weight += w

        # Rule 2: Range expansion vs ATR
        r2_cfg = rules_cfg.get("range_expansion", {})
        if r2_cfg.get("enabled", True):
            r2 = range_expansion_vs_atr(highs, lows, closes, r2_cfg.get("atr_period", 20))
            signals["range_expansion"] = r2
            w = r2_cfg.get("weight", 0.15)
            weighted_score += r2["score"] * w
            total_weight += w

        # Rule 3: Gap z-score
        r3_cfg = rules_cfg.get("gap_zscore", {})
        if r3_cfg.get("enabled", True):
            r3 = gap_zscore(opens, closes, r3_cfg.get("window", 60))
            signals["gap_zscore"] = r3
            w = r3_cfg.get("weight", 0.15)
            weighted_score += r3["score"] * w
            total_weight += w

        # Rule 4: IV rank delta
        r4_cfg = rules_cfg.get("iv_rank_delta", {})
        if r4_cfg.get("enabled", True):
            iv_result = await self._compute_iv_rank_delta(symbol, closes, cfg)
            signals["iv_rank_delta"] = iv_result
            w = r4_cfg.get("weight", 0.20)
            weighted_score += iv_result["score"] * w
            total_weight += w

        # Rule 7: Correlation breakdown
        r7_cfg = rules_cfg.get("correlation_breakdown", {})
        if r7_cfg.get("enabled", True) and spy_closes:
            r7 = correlation_breakdown(
                closes, spy_closes,
                r7_cfg.get("short_window", 20),
                r7_cfg.get("long_window", 60),
            )
            signals["correlation_breakdown"] = r7
            w = r7_cfg.get("weight", 0.15)
            weighted_score += r7["score"] * w
            total_weight += w

        # Rule 10: News density
        r10_cfg = rules_cfg.get("news_density", {})
        if r10_cfg.get("enabled", True):
            news_result = await self._compute_news_density(symbol)
            signals["news_density"] = news_result
            w = r10_cfg.get("weight", 0.15)
            weighted_score += news_result["score"] * w
            total_weight += w

        # Normalize score
        total_score = weighted_score / total_weight if total_weight > 0 else 0.0
        signals_fired = sum(1 for s in signals.values() if s.get("fired", False))
        passed = signals_fired >= min_signals

        firing_rules = [name for name, s in signals.items() if s.get("fired", False)]
        reason = ", ".join(firing_rules) if passed else "below_min_signals"

        return {
            "symbol": symbol,
            "total_score": round(total_score, 4),
            "signals_fired": signals_fired,
            "signals": signals,
            "passed": passed,
            "reason": reason,
            "asset_type": tier1_info.get("asset_type"),
            "price": tier1_info.get("price"),
        }

    # ── Data fetchers ────────────────────────────────────────────

    async def _get_bars(self, symbol: str, limit: int) -> list:
        """Fetch recent bars from historical_bars, most-recent-first.
        Reads all sources and dedupes by bar_date. Priority: stooq > yfinance > alpaca.
        Stooq and yfinance carry ~259 days of historical body; alpaca is a 2-bar
        freshness top-up that only contributes the most recent dates."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(HistoricalBar)
                .where(HistoricalBar.symbol == symbol)
                .order_by(HistoricalBar.bar_date.desc())
            )
            all_rows = result.scalars().all()

        source_priority = {"stooq": 0, "yfinance": 1, "alpaca": 2}
        seen: dict = {}
        for row in all_rows:
            existing = seen.get(row.bar_date)
            if existing is None:
                seen[row.bar_date] = row
            elif source_priority.get(row.source, 99) < source_priority.get(existing.source, 99):
                seen[row.bar_date] = row

        return sorted(seen.values(), key=lambda r: r.bar_date, reverse=True)[:limit]

    async def _get_closes(self, symbol: str, limit: int) -> list[float]:
        """Fetch closing prices, most-recent-first."""
        bars = await self._get_bars(symbol, limit)
        return [b.close for b in bars]

    async def _compute_iv_rank_delta(self, symbol: str, closes: list[float], cfg: dict) -> dict:
        """
        Compute IV rank delta over 5 trading days.

        Uses realized volatility as a proxy for IV rank when the market feed
        is unavailable. Computes 20-day realized vol percentile over 252 days.
        """
        iv_window = cfg.get("iv_rank_window_days", 252)
        delta_lookback = cfg.get("iv_rank_delta_lookback", 5)

        if len(closes) < iv_window:
            # Not enough data — try with what we have
            if len(closes) < 30:
                return {"score": 0.0, "raw": 0.0, "fired": False}

        # Compute rolling 20-day realized vol
        def realized_vol_at(idx, window=20):
            if idx + window >= len(closes):
                return None
            log_rets = []
            for i in range(idx, idx + window):
                if closes[i + 1] != 0:
                    log_rets.append(math.log(closes[i] / closes[i + 1]))
            if len(log_rets) < 10:
                return None
            mean = sum(log_rets) / len(log_rets)
            var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
            return math.sqrt(var) * math.sqrt(252) * 100  # Annualized %

        # Current IV rank
        all_vols = []
        for i in range(min(iv_window, len(closes) - 21)):
            v = realized_vol_at(i)
            if v is not None:
                all_vols.append(v)

        if len(all_vols) < 20:
            return {"score": 0.0, "raw": 0.0, "fired": False}

        current_vol = all_vols[0]
        min_vol = min(all_vols)
        max_vol = max(all_vols)
        iv_rank_today = ((current_vol - min_vol) / (max_vol - min_vol) * 100) if max_vol != min_vol else 50.0

        # 5-day-ago IV rank
        if delta_lookback < len(all_vols):
            vol_5d = all_vols[delta_lookback]
            vols_at_5d = all_vols[delta_lookback:]
            min_5d = min(vols_at_5d)
            max_5d = max(vols_at_5d)
            iv_rank_5d = ((vol_5d - min_5d) / (max_5d - min_5d) * 100) if max_5d != min_5d else 50.0
        else:
            iv_rank_5d = iv_rank_today

        return iv_rank_delta(iv_rank_today, iv_rank_5d)

    async def _compute_news_density(self, symbol: str) -> dict:
        """Query news_headlines for density metrics."""
        try:
            now = datetime.now(timezone.utc)
            day_ago = now - timedelta(hours=24)
            month_ago = now - timedelta(days=30)

            async with AsyncSessionLocal() as session:
                # Headlines in last 24h
                r1 = await session.execute(
                    select(sa_func.count(NewsHeadline.id))
                    .where(NewsHeadline.symbols.contains(symbol))
                    .where(NewsHeadline.published_at >= day_ago)
                )
                count_24h = r1.scalar() or 0

                # Headlines in last 30d
                r2 = await session.execute(
                    select(sa_func.count(NewsHeadline.id))
                    .where(NewsHeadline.symbols.contains(symbol))
                    .where(NewsHeadline.published_at >= month_ago)
                )
                count_30d = r2.scalar() or 0

            avg_daily = count_30d / 30.0
            # Approximate std from count (Poisson-ish: std ≈ sqrt(mean))
            std_daily = math.sqrt(max(avg_daily, 0.1))

            return news_density_zscore(count_24h, avg_daily, std_daily)

        except Exception as e:
            logger.debug(f"[Tier2a] News query failed for {symbol}: {e}")
            return {"score": 0.0, "raw": 0.0, "fired": False}

    # ── Writers ──────────────────────────────────────────────────

    async def _write_observations(
        self, passed: list[dict], pass_reason: str,
        near_misses: list[dict], rejected: list[dict],
    ) -> int:
        """Write tier=2 observations in batches."""
        all_obs = []

        for s in passed:
            all_obs.append(self._make_obs(s, was_considered=True, selection_reason=pass_reason))

        for s in near_misses:
            all_obs.append(self._make_obs(s, was_considered=False, selection_reason="near_miss_tier_2a",
                                          rejection_reason=s.get("reason")))

        for s in rejected:
            all_obs.append(self._make_obs(s, was_considered=False, rejection_reason=s.get("reason")))

        written = 0
        batch_size = 100
        for i in range(0, len(all_obs), batch_size):
            batch = all_obs[i : i + batch_size]
            try:
                async with AsyncSessionLocal() as session:
                    for obs in batch:
                        session.add(obs)
                        written += 1
                    await session.commit()
            except Exception as e:
                logger.error(f"[Tier2a] Failed to write observation batch at {i}: {e}")

        logger.info(f"[Tier2a] Wrote {written} observations")
        return written

    def _make_obs(self, scored: dict, was_considered: bool,
                  selection_reason: str = None, rejection_reason: str = None) -> NameObservation:
        """Build a NameObservation from a scored symbol dict."""
        return NameObservation(
            symbol=scored["symbol"],
            tier=2,
            price=scored.get("price"),
            composite_score=scored.get("total_score"),
            asset_type=scored.get("asset_type"),
            selection_reason=selection_reason,
            rejection_reason=rejection_reason,
            decision_layer="tier2a_prefilter",
            was_considered=was_considered,
            was_traded=False,
            analysis={
                "signals": {
                    name: {k: v for k, v in sig.items()}
                    for name, sig in scored.get("signals", {}).items()
                },
                "signals_fired": scored.get("signals_fired", 0),
                "total_score": scored.get("total_score", 0),
                "reason": scored.get("reason"),
            },
        )

    async def _log_action(self, action_type: str, outcome: str, reason: Optional[str], payload: Optional[dict]):
        """Write to agent_actions."""
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentAction(
                    agent_name=self.name,
                    action_type=action_type,
                    target_scope="universe",
                    outcome=outcome,
                    reason=reason,
                    payload=payload,
                ))
                await session.commit()
        except Exception as e:
            logger.warning(f"[Tier2a] Failed to log action {action_type}: {e}")

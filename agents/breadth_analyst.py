"""
Breadth Analyst Agent — Owns Tier 1 of the scanning pipeline.

Runs a daily eligibility sweep over the full optionable universe. Writes
decision records to name_observations with full transparency (passes and
rejects, with reasons). Owns the persistent historical_bars cache.

Currently a dumb agent (rule-based filtering only). The LLM intelligence
layer is planned for Batch 1.4.
"""
import asyncio
from datetime import datetime, date, timezone
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import select, func as sa_func

from agents.base_agent import BaseAgent
from core.database import AsyncSessionLocal
from models.historical_bar import HistoricalBar
from models.name_observation import NameObservation
from models.agent_action import AgentAction


class BreadthAnalyst(BaseAgent):
    """Owns Tier 1: daily universe eligibility sweep and historical bar cache."""

    def __init__(self, broker, config_path: str = "config/breadth_analyst.yaml"):
        super().__init__(name="Breadth-Analyst", agent_type="analyst")
        self.broker = broker
        self.config = self._load_config(config_path)

    @staticmethod
    def _load_config(path: str) -> dict:
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            return raw.get("breadth_analyst", {})
        except FileNotFoundError:
            logger.warning(f"[Breadth] Config not found at {path}, using defaults")
            return {}
        except Exception as e:
            logger.error(f"[Breadth] Failed to load config: {e}")
            return {}

    # ── BaseAgent lifecycle (not used — Breadth Analyst has its own methods) ──

    async def scan(self) -> list[dict]:
        return []

    async def evaluate(self, opportunities: list[dict]) -> list[dict]:
        return []

    async def execute(self, trades: list[dict]) -> list[dict]:
        return []

    async def manage_positions(self) -> list[dict]:
        return []

    # ── Backfill ─────────────────────────────────────────────────

    async def backfill_history(self, resume: bool = True) -> dict:
        """
        One-time backfill: populate historical_bars with ~252 days of daily
        bars for every optionable symbol. Supports checkpointing for resume.
        """
        from services.breadth_checkpoint import load_checkpoint, save_checkpoint

        cfg = self.config
        days_back = cfg.get("backfill_days", 252)
        batch_size = cfg.get("batch_size", 50)
        sleep_s = cfg.get("batch_sleep_seconds", 2.0)
        ckpt_path = cfg.get("checkpoint_path", "/tmp/breadth_analyst_backfill_checkpoint.json")

        await self._log_action("backfill_started", "in_progress", None, {"days_back": days_back})
        logger.info(f"[Breadth] Backfill starting (days_back={days_back}, resume={resume})")

        # Step 1: Get universe
        try:
            assets = await self.broker.get_tradable_assets(options_enabled=True)
        except Exception as e:
            logger.error(f"[Breadth] Failed to fetch assets for backfill: {e}")
            await self._log_action("backfill_failed", "failed", str(e), None)
            return {"error": str(e)}

        all_symbols = [a["symbol"] for a in assets]
        logger.info(f"[Breadth] Universe: {len(all_symbols)} symbols")

        # Step 2: Determine which symbols need backfill
        completed = load_checkpoint(ckpt_path) if resume else set()
        if completed:
            logger.info(f"[Breadth] Checkpoint: {len(completed)} symbols already done")

        # Also check DB for symbols that already have enough data
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(HistoricalBar.symbol, sa_func.count(HistoricalBar.id))
                    .group_by(HistoricalBar.symbol)
                    .having(sa_func.count(HistoricalBar.id) >= days_back * 0.8)
                )
                db_done = {row[0] for row in result.all()}
                completed |= db_done
                if db_done:
                    logger.info(f"[Breadth] DB check: {len(db_done)} symbols already have sufficient data")
        except Exception as e:
            logger.warning(f"[Breadth] DB check failed, proceeding without: {e}")

        remaining = [s for s in all_symbols if s not in completed]
        logger.info(f"[Breadth] {len(remaining)} symbols to backfill")

        # Step 3: Fetch bars in batches
        total_written = 0
        errors = 0
        total_batches = (len(remaining) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(remaining), batch_size):
            batch = remaining[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            bars_map = await self._fetch_bars_with_retry(batch, days_back)

            # Write to historical_bars
            written = await self._write_bars_to_db(bars_map)
            total_written += written

            # Update checkpoint
            completed.update(batch)
            save_checkpoint(ckpt_path, completed)

            if batch_num % 5 == 0 or batch_num == total_batches:
                logger.info(
                    f"[Breadth] Backfill batch {batch_num}/{total_batches}: "
                    f"{total_written} bars written, {len(completed)}/{len(all_symbols)} symbols done"
                )
                await self._log_action(
                    "backfill_progress", "in_progress", None,
                    {"batch": batch_num, "total_batches": total_batches, "bars_written": total_written},
                )

            if batch_idx + batch_size < len(remaining):
                await asyncio.sleep(sleep_s)

        summary = {
            "symbols_total": len(all_symbols),
            "symbols_backfilled": len(remaining),
            "symbols_skipped": len(all_symbols) - len(remaining),
            "bars_written": total_written,
            "errors": errors,
        }
        await self._log_action("backfill_completed", "executed", None, summary)
        logger.info(f"[Breadth] Backfill complete: {summary}")
        return summary

    # ── Daily Sweep ──────────────────────────────────────────────

    async def run_daily_sweep(self, dry_run: bool = False) -> dict:
        """
        Daily eligibility check: fetch incremental bars, compute metrics
        from cached data, write decision records to name_observations.
        """
        cfg = self.config
        batch_size = cfg.get("batch_size", 50)
        sleep_s = cfg.get("batch_sleep_seconds", 2.0)
        min_price = cfg.get("min_price", 5.0)
        max_price = cfg.get("max_price", 1000.0)
        min_vol_20d = cfg.get("min_avg_volume_20d", 100_000)
        min_vol_60d = cfg.get("min_avg_volume_60d", 100_000)
        max_universe = cfg.get("max_universe_size", 4500)
        near_miss_pct = cfg.get("near_miss_threshold_pct", 0.15)
        always_include = set(cfg.get("always_include", []))
        always_exclude = set(cfg.get("always_exclude", []))

        start_time = datetime.now(timezone.utc)
        await self._log_action("sweep_started", "in_progress", None, {"dry_run": dry_run})
        logger.info(f"[Breadth] Daily sweep starting (dry_run={dry_run})")

        # Step 1: Get universe
        try:
            assets = await self.broker.get_tradable_assets(options_enabled=True)
        except Exception as e:
            logger.error(f"[Breadth] Failed to fetch assets: {e}")
            await self._log_action("sweep_failed", "failed", str(e), None)
            return {"error": str(e)}

        asset_map = {a["symbol"]: a for a in assets}
        all_symbols = list(asset_map.keys())
        logger.info(f"[Breadth] Universe: {len(all_symbols)} optionable symbols")

        # Step 2: Fetch incremental bars (yesterday's close)
        inc_days = cfg.get("incremental_days", 1)
        bars_map = await self._fetch_bars_with_retry(all_symbols, inc_days)
        if not dry_run:
            await self._write_bars_to_db(bars_map)

        # Step 3: Check for symbols needing mini-backfill (not in historical_bars)
        backfill_days = cfg.get("backfill_days", 252)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(HistoricalBar.symbol).distinct()
                )
                known_symbols = {row[0] for row in result.all()}
        except Exception:
            known_symbols = set()

        needs_backfill = [s for s in all_symbols if s not in known_symbols]
        if needs_backfill:
            logger.info(f"[Breadth] {len(needs_backfill)} symbols need mini-backfill")
            for i in range(0, len(needs_backfill), batch_size):
                batch = needs_backfill[i : i + batch_size]
                bf_bars = await self._fetch_bars_with_retry(batch, backfill_days)
                if not dry_run:
                    await self._write_bars_to_db(bf_bars)
                if i + batch_size < len(needs_backfill):
                    await asyncio.sleep(sleep_s)

        # Step 4: Compute metrics and filter
        passed = []
        rejected = []
        near_misses = []
        errors = 0

        # Compute the volume threshold for near-miss detection
        vol_threshold_near = min_vol_20d * (1 - near_miss_pct)

        progress_interval = max(1, len(all_symbols) // 10)

        for idx, symbol in enumerate(all_symbols):
            if symbol in always_exclude:
                rejected.append(self._make_observation(
                    symbol, asset_map.get(symbol, {}), None,
                    passed=False, reason="always_exclude",
                ))
                continue

            try:
                metrics = await self._compute_metrics_for_symbol(symbol)
            except Exception as e:
                logger.debug(f"[Breadth] Metrics failed for {symbol}: {e}")
                errors += 1
                rejected.append(self._make_observation(
                    symbol, asset_map.get(symbol, {}), None,
                    passed=False, reason="metrics_computation_failed",
                ))
                continue

            if metrics is None:
                rejected.append(self._make_observation(
                    symbol, asset_map.get(symbol, {}), None,
                    passed=False, reason="no_bars_data",
                ))
                continue

            asset_info = asset_map.get(symbol, {})

            # Apply filters
            price = metrics.get("price", 0)
            avg_vol_20 = metrics.get("avg_volume_20d", 0)
            avg_vol_60 = metrics.get("avg_volume_60d", 0)

            if price < min_price:
                obs = self._make_observation(symbol, asset_info, metrics, passed=False, reason=f"price_below_{min_price}")
                # Near-miss check for price
                if price >= min_price * (1 - near_miss_pct):
                    obs["selection_reason"] = "near_miss_tier_1"
                    obs["analysis"]["near_miss_detail"] = f"price {price:.2f} vs threshold {min_price}"
                    near_misses.append(obs)
                else:
                    rejected.append(obs)
                continue

            if price > max_price:
                rejected.append(self._make_observation(
                    symbol, asset_info, metrics, passed=False, reason=f"price_above_{max_price}",
                ))
                continue

            # Volume filter — must pass on at least one window (20d or 60d)
            vol_passed = avg_vol_20 >= min_vol_20d or avg_vol_60 >= min_vol_60d

            if not vol_passed and symbol not in always_include:
                obs = self._make_observation(symbol, asset_info, metrics, passed=False, reason="volume_below_threshold")
                # Near-miss check for volume
                if avg_vol_20 >= vol_threshold_near or avg_vol_60 >= min_vol_60d * (1 - near_miss_pct):
                    obs["selection_reason"] = "near_miss_tier_1"
                    obs["analysis"]["near_miss_detail"] = (
                        f"vol_20d {avg_vol_20:,} vs threshold {min_vol_20d:,} "
                        f"(within {near_miss_pct:.0%})"
                    )
                    near_misses.append(obs)
                else:
                    rejected.append(obs)
                continue

            # Passed all filters
            signals = ["has_options", f"price_{min_price}-{max_price}"]
            if avg_vol_20 >= min_vol_20d:
                signals.append("volume_passed_20d")
            if avg_vol_60 >= min_vol_60d:
                signals.append("volume_passed_60d")
            if symbol in always_include:
                signals.append("always_include")

            obs = self._make_observation(
                symbol, asset_info, metrics, passed=True,
                reason="universe_sweep",
                signals=signals,
            )
            passed.append(obs)

            if (idx + 1) % progress_interval == 0:
                logger.info(f"[Breadth] Progress: {idx + 1}/{len(all_symbols)} symbols processed")

        # Step 5: Trim to max_universe_size by daily_dollar_volume
        passed.sort(key=lambda x: x.get("daily_dollar_volume") or 0, reverse=True)
        displaced = []
        if len(passed) > max_universe:
            displaced = passed[max_universe:]
            passed = passed[:max_universe]
            for obs in displaced:
                obs["was_considered"] = False
                obs["rejection_reason"] = f"outside_top_{max_universe}_by_dollar_volume"
                obs["selection_reason"] = None

        # Step 6: Write to name_observations. Append-only: sweeps are
        # stamped with a sweep_id instead of deleting the day's prior rows;
        # readers select the latest sweep (services/sweep_utils). Idempotency
        # comes from the unique constraint (sweep_id, symbol, tier).
        if not dry_run:
            from services.sweep_utils import new_sweep_id
            self._current_sweep_id = new_sweep_id(tier=1)
            all_obs = passed + rejected + near_misses + displaced
            await self._write_observations_batch(all_obs)
        else:
            logger.info(f"[Breadth] DRY RUN — would write {len(passed) + len(rejected) + len(near_misses) + len(displaced)} observations")

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary = {
            "passed": len(passed),
            "rejected": len(rejected),
            "near_misses": len(near_misses),
            "displaced": len(displaced),
            "errors": errors,
            "elapsed_seconds": round(elapsed, 1),
            "dry_run": dry_run,
        }

        await self._log_action("sweep_completed", "executed", None, summary)
        logger.info(f"[Breadth] Sweep complete: {summary}")
        return summary

    # ── Helpers ──────────────────────────────────────────────────

    async def _fetch_bars_with_retry(self, symbols: list[str], days_back: int) -> dict:
        """Fetch bars with config-based pacing and retry."""
        cfg = self.config
        max_retries = cfg.get("max_retries", 3)
        backoff = cfg.get("retry_backoff_seconds", 30.0)
        batch_size = cfg.get("batch_size", 50)
        sleep_s = cfg.get("batch_sleep_seconds", 2.0)

        all_bars: dict[str, list[dict]] = {}

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]

            for attempt in range(max_retries):
                try:
                    result = await self.broker.get_historical_bars_batch(
                        symbols=batch, timeframe="1Day", days_back=days_back,
                    )
                    for sym, bars in result.items():
                        all_bars.setdefault(sym, []).extend(bars)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"[Breadth] Bars fetch attempt {attempt + 1} failed: {e}, retrying in {backoff}s")
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"[Breadth] Bars fetch failed after {max_retries} attempts: {e}")

            if i + batch_size < len(symbols):
                await asyncio.sleep(sleep_s)

        return all_bars

    async def _write_bars_to_db(self, bars_map: dict) -> int:
        """Write bars to historical_bars, skipping duplicates. Returns count written."""
        written = 0
        try:
            async with AsyncSessionLocal() as session:
                for symbol, bars in bars_map.items():
                    for bar in bars:
                        ts = bar.get("timestamp") or bar.get("t") or ""
                        try:
                            bar_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if ts else None
                        except (ValueError, AttributeError):
                            try:
                                bar_date = datetime.strptime(ts[:10], "%Y-%m-%d").date() if ts else None
                            except (ValueError, AttributeError):
                                continue

                        if not bar_date:
                            continue

                        # Check for existing row from this source
                        existing = await session.execute(
                            select(HistoricalBar.id).where(
                                HistoricalBar.symbol == symbol,
                                HistoricalBar.bar_date == bar_date,
                                HistoricalBar.source == "alpaca",
                            )
                        )
                        if existing.scalar_one_or_none() is not None:
                            continue

                        try:
                            session.add(HistoricalBar(
                                symbol=symbol,
                                bar_date=bar_date,
                                open=float(bar.get("open") or bar.get("o") or 0),
                                high=float(bar.get("high") or bar.get("h") or 0),
                                low=float(bar.get("low") or bar.get("l") or 0),
                                close=float(bar.get("close") or bar.get("c") or 0),
                                volume=int(bar.get("volume") or bar.get("v") or 0),
                                vwap=float(bar["vwap"]) if bar.get("vwap") else None,
                                trade_count=int(bar["trade_count"]) if bar.get("trade_count") else None,
                                source="alpaca",
                            ))
                            written += 1
                        except Exception:
                            continue

                await session.commit()
        except Exception as e:
            logger.error(f"[Breadth] Failed to write bars: {e}")
        return written

    async def _compute_metrics_for_symbol(self, symbol: str) -> Optional[dict]:
        """Compute metrics from cached historical_bars. Pure computation."""
        cfg = self.config
        w_short = cfg.get("volume_window_short", 20)
        w_medium = cfg.get("volume_window_medium", 60)
        w_long = cfg.get("volume_window_long", 252)

        # Fetch from all sources, dedup by bar_date. Priority: stooq > yfinance > alpaca.
        # Stooq and yfinance carry ~259 days of historical body each; alpaca is a
        # 2-bar freshness top-up that only contributes the most recent dates.
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

        rows = sorted(seen.values(), key=lambda r: r.bar_date, reverse=True)[:w_long]

        if not rows:
            return None

        latest = rows[0]
        price = latest.close
        volumes = [r.volume for r in rows]

        def avg(lst, n):
            subset = lst[:n]
            return sum(subset) / max(1, len(subset)) if subset else 0

        avg_vol_20 = avg(volumes, w_short)
        avg_vol_60 = avg(volumes, w_medium)
        avg_vol_252 = avg(volumes, w_long)
        daily_dollar_vol = price * avg_vol_20

        return {
            "price": price,
            "avg_volume_20d": int(avg_vol_20),
            "avg_volume_60d": int(avg_vol_60),
            "avg_volume_252d": int(avg_vol_252),
            "daily_dollar_volume": daily_dollar_vol,
            "bar_count": len(rows),
        }

    def _make_observation(
        self, symbol: str, asset_info: dict, metrics: Optional[dict],
        passed: bool, reason: str, signals: Optional[list] = None,
    ) -> dict:
        """Build a dict ready for writing to name_observations."""
        m = metrics or {}
        return {
            "symbol": symbol,
            "tier": 1,
            "price": m.get("price"),
            "daily_volume": m.get("avg_volume_20d"),
            "avg_volume_20d": m.get("avg_volume_20d"),
            "avg_volume_60d": m.get("avg_volume_60d"),
            "avg_volume_252d": m.get("avg_volume_252d"),
            "daily_dollar_volume": m.get("daily_dollar_volume"),
            "composite_score": m.get("daily_dollar_volume"),
            "asset_type": asset_info.get("asset_type"),
            "selection_reason": reason if passed else None,
            "rejection_reason": None if passed else reason,
            "decision_layer": "breadth_analyst",
            "was_considered": passed,
            "was_traded": False,
            "analysis": {
                "name": asset_info.get("name", ""),
                "exchange": asset_info.get("exchange", ""),
                "asset_type": asset_info.get("asset_type", ""),
                "bar_count": m.get("bar_count"),
                "signals": signals or [],
                "selection_reason": reason,
            },
        }

    async def _write_observations_batch(self, observations: list[dict]) -> int:
        """Write observation dicts to name_observations in batches."""
        written = 0
        batch_size = 100
        for i in range(0, len(observations), batch_size):
            batch = observations[i : i + batch_size]
            try:
                async with AsyncSessionLocal() as session:
                    for obs in batch:
                        session.add(NameObservation(
                            symbol=obs["symbol"],
                            tier=obs["tier"],
                            sweep_id=getattr(self, "_current_sweep_id", None),
                            price=obs.get("price"),
                            daily_volume=obs.get("daily_volume"),
                            avg_volume_20d=obs.get("avg_volume_20d"),
                            avg_volume_60d=obs.get("avg_volume_60d"),
                            avg_volume_252d=obs.get("avg_volume_252d"),
                            daily_dollar_volume=obs.get("daily_dollar_volume"),
                            composite_score=obs.get("composite_score"),
                            asset_type=obs.get("asset_type"),
                            selection_reason=obs.get("selection_reason"),
                            rejection_reason=obs.get("rejection_reason"),
                            decision_layer=obs.get("decision_layer"),
                            was_considered=obs.get("was_considered", False),
                            was_traded=obs.get("was_traded", False),
                            analysis=obs.get("analysis"),
                        ))
                        written += 1
                    await session.commit()
            except Exception as e:
                logger.error(f"[Breadth] Failed to write observation batch at index {i}: {e}")
        return written

    async def _log_action(
        self, action_type: str, outcome: str, reason: Optional[str], payload: Optional[dict],
    ) -> None:
        """Write a row to agent_actions."""
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
            logger.warning(f"[Breadth] Failed to log action {action_type}: {e}")

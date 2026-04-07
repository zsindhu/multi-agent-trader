"""
Tier Writer — Persists tier observations to the name_observations table.

Each tier of the funnel (1, 2, 3, 4) writes through this module so the
data layer captures consistent decision transparency: what was selected,
what was rejected, and why.

This is a thin wrapper over name_observations writes. The actual selection
logic lives in the loader/scanner that produces the data.
"""
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from sqlalchemy import delete

from core.database import AsyncSessionLocal
from models.name_observation import NameObservation


async def write_tier1_observations(
    passed: list[dict],
    rejected: list[dict],
    cycle_snapshot_id: Optional[int] = None,
) -> dict:
    """
    Write a complete Tier 1 universe sweep to name_observations.

    First clears any existing tier=1 rows from today's date (so a re-run
    of the universe loader replaces the previous sweep instead of
    accumulating duplicates), then inserts new rows for both passed and
    rejected names.

    Returns:
        {"passed_written": int, "rejected_written": int, "errors": int}
    """
    summary = {"passed_written": 0, "rejected_written": 0, "errors": 0}

    try:
        async with AsyncSessionLocal() as session:
            # Step 1: Clear today's existing tier 1 rows so re-runs replace
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            await session.execute(
                delete(NameObservation).where(
                    NameObservation.tier == 1,
                    NameObservation.timestamp >= today_start,
                )
            )

            # Step 2: Insert passed names (was_considered=True)
            for name_data in passed:
                try:
                    obs = NameObservation(
                        cycle_snapshot_id=cycle_snapshot_id,
                        symbol=name_data["symbol"],
                        tier=1,
                        price=name_data.get("price"),
                        daily_volume=name_data.get("avg_volume_20d"),
                        market_cap=name_data.get("market_cap"),
                        composite_score=name_data.get("selection_score"),
                        was_considered=True,
                        was_traded=False,
                        rejection_reason=None,
                        analysis={
                            "name": name_data.get("name", ""),
                            "asset_type": name_data.get("asset_type", ""),
                            "exchange": name_data.get("exchange", ""),
                            "avg_volume_20d": name_data.get("avg_volume_20d"),
                            "avg_volume_60d": name_data.get("avg_volume_60d"),
                            "avg_volume_252d": name_data.get("avg_volume_252d"),
                            "daily_dollar_volume": name_data.get("daily_dollar_volume"),
                            "selection_signals": name_data.get("selection_signals", []),
                            "selection_score": name_data.get("selection_score"),
                            "selection_reason": name_data.get("selection_reason", "universe_sweep"),
                        },
                    )
                    session.add(obs)
                    summary["passed_written"] += 1
                except Exception as e:
                    logger.error(f"[TierWriter] Failed to write passed name {name_data.get('symbol')}: {e}")
                    summary["errors"] += 1

            # Step 3: Insert rejected names (was_considered=False, with reason)
            for name_data in rejected:
                try:
                    obs = NameObservation(
                        cycle_snapshot_id=cycle_snapshot_id,
                        symbol=name_data["symbol"],
                        tier=1,
                        price=name_data.get("price"),
                        daily_volume=name_data.get("avg_volume_20d"),
                        market_cap=name_data.get("market_cap"),
                        composite_score=name_data.get("selection_score"),
                        was_considered=False,
                        was_traded=False,
                        rejection_reason=name_data.get("rejected_reason", "unknown"),
                        analysis={
                            "name": name_data.get("name", ""),
                            "asset_type": name_data.get("asset_type", ""),
                            "exchange": name_data.get("exchange", ""),
                            "avg_volume_20d": name_data.get("avg_volume_20d"),
                            "avg_volume_60d": name_data.get("avg_volume_60d"),
                            "avg_volume_252d": name_data.get("avg_volume_252d"),
                            "daily_dollar_volume": name_data.get("daily_dollar_volume"),
                            "rejected_reason": name_data.get("rejected_reason", "unknown"),
                        },
                    )
                    session.add(obs)
                    summary["rejected_written"] += 1
                except Exception as e:
                    logger.error(f"[TierWriter] Failed to write rejected name {name_data.get('symbol')}: {e}")
                    summary["errors"] += 1

            await session.commit()

        logger.info(
            f"[TierWriter] Tier 1 written: {summary['passed_written']} passed, "
            f"{summary['rejected_written']} rejected, {summary['errors']} errors"
        )

    except Exception as e:
        logger.error(f"[TierWriter] Tier 1 write failed: {e}")
        summary["errors"] += 1

    return summary

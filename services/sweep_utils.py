"""
Sweep identity helpers for append-only name_observations.

Sweeps used to DELETE the day's rows and reinsert — destroying traded-on
signal snapshots and tier2b reasoning three times a day (see
RECON_PRE_REMEDIATION_VERIFICATION.md Q1: 6 of the first 10 funnel labels
were provably wrong-sweep). Sweeps now append, stamped with a sweep_id.

The id is lexically sortable ("YYYYMMDDTHHMMSS-t<tier>-<suffix>") so "the
latest sweep" is simply MAX(sweep_id) — no join against timestamps needed.
The random suffix keeps concurrent/manual sweeps distinct; the unique
constraint (sweep_id, symbol, tier) makes re-runs idempotent per sweep.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func as sa_func, or_, cast, Date

from models.name_observation import NameObservation


def new_sweep_id(tier: int) -> str:
    """Mint a sortable sweep id, e.g. '20260711T140002-t2-3fa9c1d2'."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-t{tier}-{uuid.uuid4().hex[:8]}"


def latest_sweep_subq(tier: int, since: Optional[datetime] = None):
    """
    Scalar subquery for the most recent sweep_id of a tier, optionally
    bounded to observations at/after `since` (default: today UTC).

    Usage:
        .where(NameObservation.sweep_id == latest_sweep_subq(2))

    When no stamped rows exist in the window, the subquery is NULL and the
    equality matches nothing — identical to the pre-migration empty-day
    behavior. Legacy (NULL sweep_id) rows never match, by design: they are
    reachable through explicit timestamp queries only.
    """
    if since is None:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        select(sa_func.max(NameObservation.sweep_id))
        .where(NameObservation.tier == tier)
        .where(NameObservation.timestamp >= since)
        .scalar_subquery()
    )


async def latest_sweep_id(session, tier: int, since: Optional[datetime] = None) -> Optional[str]:
    """Imperative variant of latest_sweep_subq for callers that branch on it."""
    if since is None:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(sa_func.max(NameObservation.sweep_id))
        .where(NameObservation.tier == tier)
        .where(NameObservation.timestamp >= since)
    )
    return result.scalar()


def sweep_dedup_filter(tier: int, since: datetime):
    """
    Filter clause for multi-day windows: keep only each day's LATEST sweep,
    plus legacy pre-migration rows (sweep_id IS NULL — those days already
    hold exactly one surviving sweep, courtesy of the old delete semantics).

    Without this, firing-rate and per-day promotion counts multiply by the
    number of sweeps per day once sweeps become append-only.
    """
    latest_per_day = (
        select(sa_func.max(NameObservation.sweep_id))
        .where(NameObservation.tier == tier)
        .where(NameObservation.timestamp >= since)
        .group_by(cast(NameObservation.timestamp, Date))
    )
    return or_(
        NameObservation.sweep_id.is_(None),
        NameObservation.sweep_id.in_(latest_per_day),
    )

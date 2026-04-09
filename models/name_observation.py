"""
NameObservation — One row per name per cycle.

Tracks what the system looked at and why it did or didn't act on it.
The 'tier' field indicates which scanning tier surfaced this name:
  1 = Universe sweep (daily, all 4000 names)
  2 = Active universe (hourly, ~200-400 interesting names)
  3 = Deep analysis (15min, ~30-60 candidates)
  4 = Position management (15min, only open positions)

First-class columns capture the most commonly queried fields for fast
filtering (price, volumes, tier, asset_type, selection_reason, etc.).
The JSONB 'analysis' column stores free-form diagnostic data, signal
breakdowns, and tier-specific analysis that doesn't benefit from
column-level queries.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class NameObservation(Base):
    __tablename__ = "name_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    cycle_snapshot_id = Column(Integer, index=True)

    symbol = Column(String(16), index=True, nullable=False)
    tier = Column(Integer, nullable=False, index=True)

    # ── Basic snapshot metrics ─────────────────────────────────
    price = Column(Float)
    daily_volume = Column(Integer)
    market_cap = Column(Float)
    iv_rank = Column(Float)
    composite_score = Column(Float)

    # ── Volume averages (multi-window) ─────────────────────────
    avg_volume_20d = Column(Integer)
    avg_volume_60d = Column(Integer)
    avg_volume_252d = Column(Integer)
    daily_dollar_volume = Column(Float)

    # ── Classification & selection ─────────────────────────────
    asset_type = Column(String(16), index=True)
    selection_reason = Column(String(64), index=True)
    decision_layer = Column(String(32), index=True)

    # ── Trading decision ───────────────────────────────────────
    was_considered = Column(Boolean, default=False)
    was_traded = Column(Boolean, default=False)
    rejection_reason = Column(String(256))

    # ── Full per-name analysis (free-form JSONB) ───────────────
    analysis = Column(JSON)

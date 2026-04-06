"""
NameObservation — One row per name per cycle.

Tracks what the system looked at and why it did or didn't act on it.
The 'tier' field indicates which scanning tier surfaced this name:
  1 = Universe sweep (daily, all 4000 names)
  2 = Active universe (hourly, ~200-400 interesting names)
  3 = Deep analysis (15min, ~30-60 candidates)
  4 = Position management (15min, only open positions)
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.dialects.postgresql import JSONB
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

    # ── Trading decision ───────────────────────────────────────
    was_considered = Column(Boolean, default=False)
    was_traded = Column(Boolean, default=False)
    rejection_reason = Column(String(256))

    # ── Full per-name analysis ─────────────────────────────────
    analysis = Column(JSONB)

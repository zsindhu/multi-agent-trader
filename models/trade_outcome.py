"""
TradeOutcome — Labeled trade outcomes joined to signal profiles.

One row per completed trade. Links the trade to the name_observation that
surfaced it (for funnel-driven trades), captures the computed PnL, holding
period, underlying return, and a snapshot of the signal profile at entry.

This is the ground truth substrate for the statistical learner (1.4.2.2),
Research Analyst reflection (1.4.2.3), and citation tracking (1.4.2.5).
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class TradeOutcome(Base):
    __tablename__ = "trade_outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, nullable=False, unique=True, index=True)
    name_observation_id = Column(Integer, nullable=True, index=True)
    funnel_driven = Column(Boolean, default=False)
    sleeve_id = Column(String(32), index=True, nullable=True)
    outcome = Column(String(16), nullable=False)  # 'win', 'loss', 'breakeven', 'pending'
    pnl_dollars = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    holding_days = Column(Integer, nullable=True)
    underlying_return = Column(Float, nullable=True)
    signal_profile = Column(JSON, nullable=True)
    labeled_at = Column(DateTime(timezone=True), server_default=func.now())

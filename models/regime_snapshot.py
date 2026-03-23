"""RegimeSnapshot Model — Stores computed market regime assessments."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func

from models import Base


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    regime = Column(String, nullable=False, index=True)       # "risk_on", "neutral", "risk_off", "crisis"
    confidence = Column(Float, nullable=False)                 # 0.0 to 1.0
    vix_level = Column(Float, nullable=True)
    vix_direction = Column(String, nullable=True)             # "rising", "falling", "flat"
    breadth_pct = Column(Float, nullable=True)                # % of universe above 50MA
    breadth_trend = Column(String, nullable=True)             # "improving", "stable", "deteriorating"
    spy_trend = Column(String, nullable=True)                 # "uptrend", "pullback", "downtrend"
    spy_distance_from_20ma = Column(Float, nullable=True)     # % distance from 20MA
    sector_leader = Column(String, nullable=True)             # top 5-day sector
    sector_laggard = Column(String, nullable=True)            # worst 5-day sector
    rotation_signal = Column(String, nullable=True)           # "risk_on", "risk_off", "neutral"
    credit_stress = Column(Boolean, nullable=True)
    summary = Column(Text, nullable=True)                     # one-sentence human-readable
    sector_returns = Column(Text, nullable=True)              # JSON: {sector: 5d_return}
    computed_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True,
        server_default=func.now(),
    )

"""PerformanceInsight Model — Computed trading analytics stored as JSON blobs."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from models import Base


class PerformanceInsight(Base):
    __tablename__ = "performance_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    insight_type = Column(String, nullable=False, index=True)
    # "overall", "strategy", "asset_type", "delta", "regime", "symbol", "position_health"
    period = Column(String, nullable=False)   # "7d", "30d", "all_time"
    data = Column(Text, nullable=False)       # JSON blob of computed metrics
    computed_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True,
        server_default=func.now(),
    )

"""EarningsEvent Model — Upcoming earnings and dividend dates per symbol."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime
from sqlalchemy.sql import func

from models import Base


class EarningsEvent(Base):
    __tablename__ = "earnings_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)   # "earnings", "ex_dividend"
    event_date = Column(Date, nullable=False)
    days_until = Column(Integer, nullable=True)   # recomputed on read
    risk_level = Column(String, nullable=False)   # "high_risk" (0-7d), "approaching" (7-14d), "safe" (14+d)
    fetched_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True,
        server_default=func.now(),
    )

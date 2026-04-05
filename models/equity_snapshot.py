"""EquitySnapshot Model — Records portfolio equity after each orchestration cycle."""
from datetime import datetime
from sqlalchemy import Column, Integer, Float, DateTime
from sqlalchemy.sql import func

from models import Base


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    equity = Column(Float, nullable=False)
    cash = Column(Float, nullable=True)
    buying_power = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True,
                         server_default=func.now())

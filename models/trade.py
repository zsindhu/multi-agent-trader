"""Trade Model — SQLAlchemy model for trade records."""
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.sql import func
from datetime import datetime

from models import Base


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    option_symbol = Column(String, nullable=True)
    trade_type = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    premium = Column(Float, nullable=True)
    strike = Column(Float, nullable=True)
    expiration = Column(String, nullable=True)
    status = Column(String, default="filled")
    pnl = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    order_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)
    # Freeze-at-decision: the tier-2 observation (id + signal analysis) this
    # trade was decided from, copied at write time because sweep rewrites can
    # destroy the source row before the nightly labeler runs.
    name_observation_id = Column(Integer, nullable=True, index=True)
    signal_snapshot = Column(JSON, nullable=True)
    sleeve_id = Column(String(32), nullable=True, index=True)
    # Broker fill data, recorded by the order reconciler. `price` retains its
    # legacy semantics (limit at submit, overwritten on fill); fill_price is
    # the authoritative value for outcome labeling.
    fill_price = Column(Float, nullable=True)
    filled_at = Column(DateTime(timezone=True), nullable=True)

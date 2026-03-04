"""Trade Model — SQLAlchemy model for trade records."""
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


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
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

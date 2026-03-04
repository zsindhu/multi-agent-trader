"""Position Model — SQLAlchemy model for active option positions."""
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from sqlalchemy.sql import func
from datetime import datetime
import enum

from models import Base


class PositionStatus(enum.Enum):
    """Position status enumeration."""
    OPEN = "open"
    CLOSED = "closed"
    ASSIGNED = "assigned"
    EXPIRED = "expired"


class ActivePosition(Base):
    """Active option position tracking open option trades."""
    
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    option_symbol = Column(String, nullable=False, unique=True, index=True)
    contract_type = Column(String, nullable=False)  # "call" or "put"
    strike = Column(Float, nullable=False)
    expiration = Column(String, nullable=False)  # YYYY-MM-DD format
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    premium_collected = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="open", index=True)
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)
    pnl = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())

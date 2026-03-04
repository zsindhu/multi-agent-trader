"""Wheel State Model — Persists Wheel strategy state across restarts."""
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from datetime import datetime

from models import Base


class WheelStateRecord(Base):
    """
    Persists per-symbol Wheel state so the strategy survives restarts.

    Tracks which phase of the Wheel cycle each symbol is in, cost basis
    reductions from collected premium, and how many full cycles completed.
    """

    __tablename__ = "wheel_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, unique=True, index=True)

    # Current wheel state
    state = Column(
        String, nullable=False, default="selling_puts"
    )  # selling_puts | assigned | selling_calls | called_away

    # Cost basis tracking
    original_cost = Column(Float, nullable=False, default=0.0)
    total_premium_collected = Column(Float, nullable=False, default=0.0)
    cycle_count = Column(Integer, nullable=False, default=0)

    # Timing
    entered_state_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())

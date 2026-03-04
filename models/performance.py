"""Performance Model — SQLAlchemy model for daily agent performance snapshots."""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from datetime import date

from models import Base


class AgentPerformance(Base):
    """Daily performance snapshot per agent."""
    
    __tablename__ = "agent_performance"
    __table_args__ = (
        UniqueConstraint("agent_name", "date", name="uq_agent_performance_date"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    total_trades = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    total_premium = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    win_rate = Column(Float, nullable=True)  # Computed: wins / total_trades
    avg_return_per_trade = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())

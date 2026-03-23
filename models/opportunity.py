"""Opportunity Model — SQLAlchemy model for scanner opportunities."""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from datetime import datetime

from models import Base


class ScannerOpportunity(Base):
    """Scanner-detected trading opportunities."""
    
    __tablename__ = "scanner_opportunities"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    asset_type = Column(String, nullable=False, default="stock", index=True)  # "stock" or "etf"
    iv_rank = Column(Float, nullable=True)
    momentum_30d = Column(Float, nullable=True)  # 30-day price change %
    distance_from_20ma = Column(Float, nullable=True)  # % distance from 20-day MA
    distance_from_50ma = Column(Float, nullable=True)  # % distance from 50-day MA
    options_liquidity_score = Column(Float, nullable=True)  # Composite liquidity metric
    near_support = Column(Boolean, nullable=False, default=False)
    composite_score = Column(Float, nullable=False, index=True)
    avg_daily_volume = Column(Float, nullable=True)  # Avg daily volume from pre-filter
    scanned_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())

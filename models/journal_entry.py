"""Journal Entry Model — Comprehensive trade journal with full context."""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from datetime import datetime

from models import Base


class JournalEntry(Base):
    """
    Comprehensive trade journal entry capturing:
    - Trade details (entry and exit)
    - Market context at entry/exit
    - Strategy context
    - Performance metrics
    """
    
    __tablename__ = "journal_entries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Trade Details
    agent_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    asset_type = Column(String, nullable=True, index=True)  # "stock" or "etf"
    option_symbol = Column(String, nullable=True, index=True)
    contract_type = Column(String, nullable=False)  # "call" or "put"
    strike = Column(Float, nullable=False)
    expiration = Column(String, nullable=False)  # YYYY-MM-DD
    side = Column(String, nullable=False)  # "buy" or "sell"
    quantity = Column(Integer, nullable=False)
    fill_price = Column(Float, nullable=False)
    premium = Column(Float, nullable=True)
    
    # Entry Context (market conditions when trade opened)
    entry_iv_rank = Column(Float, nullable=True)
    entry_stock_price = Column(Float, nullable=True)
    entry_vix_level = Column(Float, nullable=True)
    entry_distance_from_support = Column(Float, nullable=True)  # % distance
    entry_distance_from_20ma = Column(Float, nullable=True)
    entry_distance_from_50ma = Column(Float, nullable=True)
    entry_scanner_composite_score = Column(Float, nullable=True)
    entry_sector = Column(String, nullable=True)
    
    # Strategy Context
    delta_at_entry = Column(Float, nullable=True)
    dte_at_entry = Column(Integer, nullable=True)
    annualized_return_at_entry = Column(Float, nullable=True)
    probability_of_profit = Column(Float, nullable=True)
    
    # Exit Context (market conditions when trade closed)
    exit_stock_price = Column(Float, nullable=True)
    exit_iv_rank = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)  # "profit_target", "stop_loss", "expired", "assigned", "rolled"
    
    # Performance
    realized_pnl = Column(Float, nullable=True)
    days_held = Column(Integer, nullable=True)
    return_pct = Column(Float, nullable=True)
    
    # Timestamps
    entry_at = Column(DateTime, nullable=False, index=True)
    exit_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    
    # Notes
    notes = Column(Text, nullable=True)

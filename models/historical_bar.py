"""
HistoricalBar — Persistent daily bar storage.

One row per symbol per trading day. Serves as the source of truth for
historical price data, replacing per-fetch Alpaca API calls for anything
that needs bars older than the current session.

The composite unique constraint on (symbol, bar_date) ensures re-running
a backfill or incremental update cannot create duplicate rows.
"""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, UniqueConstraint, Index
from sqlalchemy.sql import func

from models import Base


class HistoricalBar(Base):
    __tablename__ = "historical_bars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    bar_date = Column(Date, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    vwap = Column(Float, nullable=True)
    trade_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('symbol', 'bar_date', name='uq_historical_bars_symbol_date'),
        Index('ix_historical_bars_symbol_bar_date', 'symbol', 'bar_date'),
    )

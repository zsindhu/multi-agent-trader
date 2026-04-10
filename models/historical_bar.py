"""
HistoricalBar — Persistent daily bar storage.

One row per symbol per trading day per source. Serves as the source of
truth for historical price data, replacing per-fetch Alpaca API calls
for anything that needs bars older than the current session.

Each row records which data source it came from (e.g. 'alpaca', 'stooq',
'yfinance', 'kaggle'). The same (symbol, bar_date) can appear once per
source, enabling cross-validation between providers.
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
    source = Column(String(32), nullable=False, default='alpaca')

    __table_args__ = (
        UniqueConstraint('symbol', 'bar_date', 'source', name='uq_historical_bars_symbol_date_source'),
        Index('ix_historical_bars_symbol_bar_date', 'symbol', 'bar_date'),
        Index('ix_historical_bars_source', 'source'),
    )

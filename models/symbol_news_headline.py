"""
SymbolNewsHeadline — Per-name company news from Finnhub's company news endpoint.

Feeds the news_density rule in Tier 2a. Symbol is a first-class indexed column
(not a comma-separated string search). Retention: 35 days (sufficient for the
30-day baseline computation in news_density).
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func

from models import Base


class SymbolNewsHeadline(Base):
    __tablename__ = "symbol_news_headlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    headline = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    source = Column(String(128), nullable=True)
    url = Column(String(512), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_symbol_news_symbol_published', 'symbol', 'published_at'),
    )

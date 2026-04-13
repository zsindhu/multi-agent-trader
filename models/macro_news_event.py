"""
MacroNewsEvent — Broad-market news from Finnhub's general news endpoint.

Environmental context for future agents (Research Analyst, Lead Agent,
Tier 2b reasoning). Does NOT affect Tier 2a scoring. Retention: 90 days.
Topics tagged at ingestion via keyword map.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class MacroNewsEvent(Base):
    __tablename__ = "macro_news_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    headline = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    source = Column(String(128), nullable=True)
    url = Column(String(512), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    topics = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

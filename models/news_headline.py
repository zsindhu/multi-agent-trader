"""NewsHeadline Model — Market and company news headlines."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from models import Base


class NewsHeadline(Base):
    __tablename__ = "news_headlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    headline = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    url = Column(String, nullable=True)
    symbols = Column(String, nullable=True)     # comma-separated related tickers
    category = Column(String, nullable=False)   # "general", "company"
    published_at = Column(DateTime, nullable=False, index=True)
    fetched_at = Column(
        DateTime, nullable=False, default=datetime.utcnow,
        server_default=func.now(),
    )

"""LLM Usage Log — Persistent per-call cost tracking that survives container restarts."""
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func

from models import Base


class LlmUsageLog(Base):
    __tablename__ = "llm_usage_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    model = Column(String(64), nullable=True)
    caller = Column(String(64), nullable=True, index=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cache_read = Column(Integer, default=0)
    cache_create = Column(Integer, default=0)
    cost_usd = Column(Float, nullable=True)
    cycle_id = Column(Integer, nullable=True)

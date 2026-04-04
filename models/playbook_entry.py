"""
Playbook Entry — Qualitative narrative institutional memory for the Lead Agent.

The LLM reads all active entries at the start of every cycle and writes new
entries when it discovers patterns, learns from losses, or wants to record a
decision for future reference.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from models import Base


class PlaybookEntry(Base):
    __tablename__ = "playbook_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False, index=True)
    # Categories: "lesson_learned", "parameter_adjustment", "symbol_note",
    #             "regime_observation", "strategy_rule", "market_insight"
    content = Column(Text, nullable=False)
    source = Column(String, nullable=False)  # "lead_agent", "performance_analyst", "operator"
    confidence = Column(Float, nullable=True)  # 0-1
    validated = Column(Boolean, default=False)  # Has subsequent data confirmed this?
    trades_supporting = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    superseded_by = Column(Integer, nullable=True)  # ID of newer entry replacing this
    active = Column(Boolean, default=True)  # False if superseded or invalidated

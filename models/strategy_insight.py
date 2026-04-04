"""
Strategy Insight — Structured, enforceable rules extracted from playbook + trade data.

Generated and validated by the Performance Analyst (weekly). The LLM reads these
every cycle alongside the playbook — higher confidence = more trades confirming
the rule.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from models import Base


class StrategyInsight(Base):
    __tablename__ = "strategy_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    insight_type = Column(String, nullable=False, index=True)
    # Types: "max_concentration", "regime_filter", "delta_range",
    #        "symbol_blacklist", "dte_preference", "entry_condition"
    rule = Column(Text, nullable=False)
    # Human-readable: "Never hold more than 2 positions in a single symbol"
    parameters = Column(Text, nullable=True)
    # JSON with structured params: {"max_positions_per_symbol": 2}
    confidence = Column(Float, nullable=False, default=0.5)
    supporting_trades = Column(Integer, default=0)
    contradicting_trades = Column(Integer, default=0)
    win_rate_with = Column(Float, nullable=True)   # Win rate when rule is followed
    win_rate_without = Column(Float, nullable=True)  # Win rate when rule is violated
    discovered_at = Column(DateTime, nullable=False, server_default=func.now())
    last_validated = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)

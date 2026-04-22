"""
PendingChange — Tracks proposed config changes through the validation pipeline.

When a signal learner proposes new weights or an operator wants to change
thresholds, the proposal is recorded here with backtest results. Changes
move through stages: proposed → backtested → approved → applied (or rejected).
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class PendingChange(Base):
    __tablename__ = "pending_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    change_type = Column(String(64), nullable=False)  # 'weight_update', 'threshold_change', 'rule_toggle'
    description = Column(Text, nullable=False)
    proposed_config = Column(JSON, nullable=False)  # The proposed tier2a.yaml changes
    current_config = Column(JSON, nullable=True)    # Snapshot of current config at proposal time
    backtest_result = Column(JSON, nullable=True)   # Output of the backtester
    status = Column(String(32), default="proposed")  # proposed, backtested, approved, applied, rejected
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)

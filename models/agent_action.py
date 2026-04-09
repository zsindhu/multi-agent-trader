"""
AgentAction — Unified audit log for every decision any agent makes.

One row per action. Captures who did it, what they did, what symbol it
was about, what the outcome was, and why. The payload JSONB column holds
action-type-specific data that doesn't need its own column.

This replaces ad-hoc logging spread across multiple tables with a single
queryable timeline of system behavior.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from sqlalchemy import JSON
from sqlalchemy.sql import func

from models import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    agent_name = Column(String(64), nullable=False, index=True)
    action_type = Column(String(64), nullable=False, index=True)

    target_symbol = Column(String(16), nullable=True, index=True)
    target_scope = Column(String(32), nullable=True)

    outcome = Column(String(32), nullable=True, index=True)
    reason = Column(String(256), nullable=True)
    score = Column(Float, nullable=True)

    cycle_snapshot_id = Column(Integer, nullable=True, index=True)
    name_observation_id = Column(Integer, nullable=True, index=True)

    payload = Column(JSON, nullable=True)

    __table_args__ = (
        Index('ix_agent_actions_agent_timestamp', 'agent_name', 'timestamp'),
    )

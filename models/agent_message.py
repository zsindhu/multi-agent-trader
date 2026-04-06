"""
AgentMessage — Inter-agent communication bus.

Agents don't call each other directly. They write messages here, and other
agents read them at their next cycle. This is the loose coupling that lets
us add new agents without modifying existing ones.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from models import Base


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    sender = Column(String(64), nullable=False, index=True)
    recipient = Column(String(64), index=True)
    message_type = Column(String(64), nullable=False, index=True)

    subject = Column(String(256))
    body = Column(Text)
    payload = Column(JSONB)

    read_by_lead_agent = Column(Boolean, default=False, index=True)
    expires_at = Column(DateTime(timezone=True))

"""
AgentCapability — Registry of agents and their capabilities.

When a new agent starts, it registers itself here with a list of
capabilities it provides. Other agents can query this registry to discover
what services are available — e.g. the Lead Agent can ask "is there a
fundamentals analyst available right now?" before requesting a deep dive.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from models import Base


class AgentCapability(Base):
    __tablename__ = "agent_capabilities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(64), nullable=False, unique=True, index=True)
    agent_type = Column(String(64), nullable=False)

    capabilities = Column(JSONB)
    description = Column(Text)

    is_active = Column(Boolean, default=True)
    last_heartbeat = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    config = Column(JSONB)

"""
SkillDocument — Versioned markdown documents that agents maintain about
their own strategies and capabilities.

This is the system's self-documentation. As the system learns, it updates
its skill documents. Old versions are preserved so we can audit how the
strategy evolved over time. Humans can also read and edit these directly.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint
from sqlalchemy.sql import func

from models import Base


class SkillDocument(Base):
    __tablename__ = "skill_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)

    title = Column(String(256))
    content = Column(Text, nullable=False)
    summary = Column(String(512))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(64))

    __table_args__ = (
        UniqueConstraint('agent_name', 'version', name='uq_skill_doc_agent_version'),
    )

"""
ReasoningEmbedding — Vector embeddings for semantic search.

Stores 1536-dimensional embeddings (OpenAI text-embedding-3-small format)
of reasoning traces, playbook entries, skill documents, and other text
artifacts. Powers natural-language queries like "show me all cycles where
the system was wrong about a regime call."
"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from models import Base


class ReasoningEmbedding(Base):
    __tablename__ = "reasoning_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source_table = Column(String(64), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)
    text_excerpt = Column(Text)

    embedding = Column(Vector(1536), nullable=False)

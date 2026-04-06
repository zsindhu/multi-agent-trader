"""
ReasoningEmbedding — Vector embeddings for semantic search.

Stores 1536-dimensional embeddings (OpenAI text-embedding-3-small format)
of reasoning traces, playbook entries, skill documents, and other text
artifacts. Powers natural-language queries like "show me all cycles where
the system was wrong about a regime call."

Uses pgvector's Vector type on PostgreSQL for proper vector operations.
On SQLite (preflight smoke test only), falls back to a Text column —
semantic search features require the real PostgreSQL deployment.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from models import Base

# pgvector is only available on PostgreSQL. The Text fallback lets us
# import this model during preflight (which runs against SQLite) without
# breaking the import chain.
try:
    from pgvector.sqlalchemy import Vector
    _EMBEDDING_COLUMN = Column(Vector(1536), nullable=False)
except ImportError:
    _EMBEDDING_COLUMN = Column(Text, nullable=False)


class ReasoningEmbedding(Base):
    __tablename__ = "reasoning_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source_table = Column(String(64), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)
    text_excerpt = Column(Text)

    embedding = _EMBEDDING_COLUMN

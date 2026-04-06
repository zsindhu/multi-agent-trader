"""add_reasoning_embeddings_table

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-04-06 00:00:05.000000

Vector embeddings for semantic search across reasoning traces, playbook
entries, and skill documents. Uses pgvector HNSW index for fast similarity.
"""
from alembic import op

revision = 'l6m7n8o9p0q1'
down_revision = 'k5l6m7n8o9p0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE reasoning_embeddings (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            source_table VARCHAR(64) NOT NULL,
            source_id INTEGER NOT NULL,
            text_excerpt TEXT,
            embedding vector(1536) NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_reasoning_embeddings_source_table ON reasoning_embeddings (source_table)")
    op.execute("CREATE INDEX ix_reasoning_embeddings_source_id ON reasoning_embeddings (source_id)")
    # HNSW index for fast cosine similarity search
    op.execute("""
        CREATE INDEX ix_reasoning_embeddings_embedding
        ON reasoning_embeddings
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS reasoning_embeddings")

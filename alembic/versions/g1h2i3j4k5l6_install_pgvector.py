"""install_pgvector

Revision ID: g1h2i3j4k5l6
Revises: e4f5a6b7c8d9
Create Date: 2026-04-06 00:00:00.000000

Enables the pgvector extension for vector similarity search.
"""
from alembic import op

revision = 'g1h2i3j4k5l6'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade():
    op.execute("DROP EXTENSION IF EXISTS vector")

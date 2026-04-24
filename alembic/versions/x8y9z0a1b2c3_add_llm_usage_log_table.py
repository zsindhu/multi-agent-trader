"""Add llm_usage_log table

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "x8y9z0a1b2c3"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("caller", sa.String(64), nullable=True, index=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cache_read", sa.Integer(), server_default="0"),
        sa.Column("cache_create", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("cycle_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("llm_usage_log")

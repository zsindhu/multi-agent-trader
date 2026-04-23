"""Add estimated_edge column to trade_outcomes

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "w7x8y9z0a1b2"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trade_outcomes", sa.Column("estimated_edge", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_outcomes", "estimated_edge")

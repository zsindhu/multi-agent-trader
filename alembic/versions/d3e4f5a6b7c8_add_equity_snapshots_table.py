"""add_equity_snapshots_table

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-02 00:00:00.000000

Adds equity_snapshots table. One row is written after each orchestration cycle
so the dashboard can render a real historical equity chart instead of synthesizing
one backwards from trade P&L.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'equity_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('equity', sa.Float(), nullable=False),
        sa.Column('cash', sa.Float(), nullable=True),
        sa.Column('buying_power', sa.Float(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_equity_snapshots_recorded_at', 'equity_snapshots', ['recorded_at'])


def downgrade():
    op.drop_index('ix_equity_snapshots_recorded_at', table_name='equity_snapshots')
    op.drop_table('equity_snapshots')

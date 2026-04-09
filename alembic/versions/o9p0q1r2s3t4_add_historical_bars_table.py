"""add_historical_bars_table

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-04-09 00:00:02.000000

Persistent daily bar storage. One row per symbol per trading day with
OHLCV, VWAP, and trade count. Composite unique on (symbol, bar_date)
prevents duplicate rows on re-runs.
"""
from alembic import op
import sqlalchemy as sa

revision = 'o9p0q1r2s3t4'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'historical_bars',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(16), nullable=False),
        sa.Column('bar_date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Integer(), nullable=False),
        sa.Column('vwap', sa.Float(), nullable=True),
        sa.Column('trade_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'bar_date', name='uq_historical_bars_symbol_date'),
    )
    op.create_index('ix_historical_bars_symbol', 'historical_bars', ['symbol'])
    op.create_index('ix_historical_bars_bar_date', 'historical_bars', ['bar_date'])
    op.create_index('ix_historical_bars_symbol_bar_date', 'historical_bars', ['symbol', 'bar_date'])


def downgrade():
    op.drop_index('ix_historical_bars_symbol_bar_date', table_name='historical_bars')
    op.drop_index('ix_historical_bars_bar_date', table_name='historical_bars')
    op.drop_index('ix_historical_bars_symbol', table_name='historical_bars')
    op.drop_table('historical_bars')

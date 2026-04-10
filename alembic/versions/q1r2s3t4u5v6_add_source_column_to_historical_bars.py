"""add_source_column_to_historical_bars

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-04-09 00:00:04.000000

Add source provenance column to historical_bars. Changes the unique
constraint from (symbol, bar_date) to (symbol, bar_date, source) so
the same date can have one row per data provider.
"""
from alembic import op
import sqlalchemy as sa

revision = 'q1r2s3t4u5v6'
down_revision = 'p0q1r2s3t4u5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Add column with server_default so NOT NULL works even on non-empty tables
    op.add_column('historical_bars', sa.Column('source', sa.String(32), nullable=False, server_default='alpaca'))

    if bind.dialect.name == "postgresql":
        # Drop old 2-column unique, create new 3-column unique
        op.drop_constraint('uq_historical_bars_symbol_date', 'historical_bars', type_='unique')
        op.create_unique_constraint('uq_historical_bars_symbol_date_source', 'historical_bars', ['symbol', 'bar_date', 'source'])
        op.create_index('ix_historical_bars_source', 'historical_bars', ['source'])
        # Drop the server_default so future inserts must specify source explicitly
        op.alter_column('historical_bars', 'source', server_default=None)
    # SQLite (preflight): skip constraint changes — they only matter on PostgreSQL


def downgrade():
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.drop_index('ix_historical_bars_source', table_name='historical_bars')
        op.drop_constraint('uq_historical_bars_symbol_date_source', 'historical_bars', type_='unique')
        op.create_unique_constraint('uq_historical_bars_symbol_date', 'historical_bars', ['symbol', 'bar_date'])

    op.drop_column('historical_bars', 'source')

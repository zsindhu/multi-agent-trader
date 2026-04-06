"""add_name_observations_table

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-04-06 00:00:02.000000

One row per name per cycle. Tracks what the system looked at, at which
scanning tier, and whether it traded or rejected.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'name_observations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('cycle_snapshot_id', sa.Integer(), nullable=True),
        sa.Column('symbol', sa.String(16), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=False),
        # Basic snapshot metrics
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('daily_volume', sa.Integer(), nullable=True),
        sa.Column('market_cap', sa.Float(), nullable=True),
        sa.Column('iv_rank', sa.Float(), nullable=True),
        sa.Column('composite_score', sa.Float(), nullable=True),
        # Trading decision
        sa.Column('was_considered', sa.Boolean(), default=False, nullable=True),
        sa.Column('was_traded', sa.Boolean(), default=False, nullable=True),
        sa.Column('rejection_reason', sa.String(256), nullable=True),
        # Full per-name analysis
        sa.Column('analysis', postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_name_observations_timestamp', 'name_observations', ['timestamp'])
    op.create_index('ix_name_observations_symbol', 'name_observations', ['symbol'])
    op.create_index('ix_name_observations_tier', 'name_observations', ['tier'])
    op.create_index('ix_name_observations_cycle_snapshot_id', 'name_observations', ['cycle_snapshot_id'])
    op.create_index('ix_name_observations_symbol_timestamp', 'name_observations', ['symbol', 'timestamp'])


def downgrade():
    op.drop_index('ix_name_observations_symbol_timestamp', table_name='name_observations')
    op.drop_index('ix_name_observations_cycle_snapshot_id', table_name='name_observations')
    op.drop_index('ix_name_observations_tier', table_name='name_observations')
    op.drop_index('ix_name_observations_symbol', table_name='name_observations')
    op.drop_index('ix_name_observations_timestamp', table_name='name_observations')
    op.drop_table('name_observations')

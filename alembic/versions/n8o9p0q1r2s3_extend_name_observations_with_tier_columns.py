"""extend_name_observations_with_tier_columns

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-04-09 00:00:01.000000

Add first-class columns for volume averages, dollar volume, asset type,
selection reason, and decision layer to name_observations. These support
fast queries without digging into the JSONB analysis column.
"""
from alembic import op
import sqlalchemy as sa

revision = 'n8o9p0q1r2s3'
down_revision = 'm7n8o9p0q1r2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('name_observations', sa.Column('avg_volume_20d', sa.Integer(), nullable=True))
    op.add_column('name_observations', sa.Column('avg_volume_60d', sa.Integer(), nullable=True))
    op.add_column('name_observations', sa.Column('avg_volume_252d', sa.Integer(), nullable=True))
    op.add_column('name_observations', sa.Column('daily_dollar_volume', sa.Float(), nullable=True))
    op.add_column('name_observations', sa.Column('asset_type', sa.String(16), nullable=True))
    op.add_column('name_observations', sa.Column('selection_reason', sa.String(64), nullable=True))
    op.add_column('name_observations', sa.Column('decision_layer', sa.String(32), nullable=True))

    op.create_index('ix_name_observations_asset_type', 'name_observations', ['asset_type'])
    op.create_index('ix_name_observations_selection_reason', 'name_observations', ['selection_reason'])
    op.create_index('ix_name_observations_decision_layer', 'name_observations', ['decision_layer'])


def downgrade():
    op.drop_index('ix_name_observations_decision_layer', table_name='name_observations')
    op.drop_index('ix_name_observations_selection_reason', table_name='name_observations')
    op.drop_index('ix_name_observations_asset_type', table_name='name_observations')

    op.drop_column('name_observations', 'decision_layer')
    op.drop_column('name_observations', 'selection_reason')
    op.drop_column('name_observations', 'asset_type')
    op.drop_column('name_observations', 'daily_dollar_volume')
    op.drop_column('name_observations', 'avg_volume_252d')
    op.drop_column('name_observations', 'avg_volume_60d')
    op.drop_column('name_observations', 'avg_volume_20d')

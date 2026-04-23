"""add_sleeve_id_columns

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-04-23 00:00:01.000000

Add sleeve_id column to name_observations and trade_outcomes for
multi-sleeve architecture. Nullable — existing rows get NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = 'v6w7x8y9z0a1'
down_revision = 'u5v6w7x8y9z0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('name_observations', sa.Column('sleeve_id', sa.String(32), nullable=True))
    op.create_index('ix_name_observations_sleeve_id', 'name_observations', ['sleeve_id'])

    op.add_column('trade_outcomes', sa.Column('sleeve_id', sa.String(32), nullable=True))
    op.create_index('ix_trade_outcomes_sleeve_id', 'trade_outcomes', ['sleeve_id'])


def downgrade():
    op.drop_index('ix_trade_outcomes_sleeve_id', table_name='trade_outcomes')
    op.drop_column('trade_outcomes', 'sleeve_id')

    op.drop_index('ix_name_observations_sleeve_id', table_name='name_observations')
    op.drop_column('name_observations', 'sleeve_id')

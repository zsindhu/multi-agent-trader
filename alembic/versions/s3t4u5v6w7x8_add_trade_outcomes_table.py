"""add_trade_outcomes_table

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-04-22 00:00:01.000000

Labeled trade outcomes joined to signal profiles. Ground truth for
statistical learner, Research Analyst, and citation tracking.
"""
from alembic import op
import sqlalchemy as sa

revision = 's3t4u5v6w7x8'
down_revision = 'r2s3t4u5v6w7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trade_outcomes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=False),
        sa.Column('name_observation_id', sa.Integer(), nullable=True),
        sa.Column('funnel_driven', sa.Boolean(), default=False, nullable=True),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('pnl_dollars', sa.Float(), nullable=True),
        sa.Column('pnl_percent', sa.Float(), nullable=True),
        sa.Column('holding_days', sa.Integer(), nullable=True),
        sa.Column('underlying_return', sa.Float(), nullable=True),
        sa.Column('signal_profile', sa.JSON(), nullable=True),
        sa.Column('labeled_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_id', name='uq_trade_outcomes_trade_id'),
    )
    op.create_index('ix_trade_outcomes_trade_id', 'trade_outcomes', ['trade_id'])
    op.create_index('ix_trade_outcomes_name_observation_id', 'trade_outcomes', ['name_observation_id'])


def downgrade():
    op.drop_index('ix_trade_outcomes_name_observation_id', table_name='trade_outcomes')
    op.drop_index('ix_trade_outcomes_trade_id', table_name='trade_outcomes')
    op.drop_table('trade_outcomes')

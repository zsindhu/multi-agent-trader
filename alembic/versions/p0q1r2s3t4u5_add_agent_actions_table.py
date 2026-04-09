"""add_agent_actions_table

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-04-09 00:00:03.000000

Unified audit log for every decision any agent makes. One row per action
with agent, type, target, outcome, reason, and free-form payload.
"""
from alembic import op
import sqlalchemy as sa

revision = 'p0q1r2s3t4u5'
down_revision = 'o9p0q1r2s3t4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_actions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('agent_name', sa.String(64), nullable=False),
        sa.Column('action_type', sa.String(64), nullable=False),
        sa.Column('target_symbol', sa.String(16), nullable=True),
        sa.Column('target_scope', sa.String(32), nullable=True),
        sa.Column('outcome', sa.String(32), nullable=True),
        sa.Column('reason', sa.String(256), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('cycle_snapshot_id', sa.Integer(), nullable=True),
        sa.Column('name_observation_id', sa.Integer(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_actions_timestamp', 'agent_actions', ['timestamp'])
    op.create_index('ix_agent_actions_agent_name', 'agent_actions', ['agent_name'])
    op.create_index('ix_agent_actions_action_type', 'agent_actions', ['action_type'])
    op.create_index('ix_agent_actions_target_symbol', 'agent_actions', ['target_symbol'])
    op.create_index('ix_agent_actions_outcome', 'agent_actions', ['outcome'])
    op.create_index('ix_agent_actions_cycle_snapshot_id', 'agent_actions', ['cycle_snapshot_id'])
    op.create_index('ix_agent_actions_name_observation_id', 'agent_actions', ['name_observation_id'])
    op.create_index('ix_agent_actions_agent_timestamp', 'agent_actions', ['agent_name', 'timestamp'])


def downgrade():
    op.drop_index('ix_agent_actions_agent_timestamp', table_name='agent_actions')
    op.drop_index('ix_agent_actions_name_observation_id', table_name='agent_actions')
    op.drop_index('ix_agent_actions_cycle_snapshot_id', table_name='agent_actions')
    op.drop_index('ix_agent_actions_outcome', table_name='agent_actions')
    op.drop_index('ix_agent_actions_target_symbol', table_name='agent_actions')
    op.drop_index('ix_agent_actions_action_type', table_name='agent_actions')
    op.drop_index('ix_agent_actions_agent_name', table_name='agent_actions')
    op.drop_index('ix_agent_actions_timestamp', table_name='agent_actions')
    op.drop_table('agent_actions')

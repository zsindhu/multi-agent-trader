"""add_agent_capabilities_table

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-04-06 00:00:06.000000

Registry of agents and their capabilities. New agents register here on
startup; other agents query to discover available services.
"""
from alembic import op
import sqlalchemy as sa

revision = 'm7n8o9p0q1r2'
down_revision = 'l6m7n8o9p0q1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_capabilities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_name', sa.String(64), nullable=False),
        sa.Column('agent_type', sa.String(64), nullable=False),
        sa.Column('capabilities', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=True),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_name', name='uq_agent_capabilities_agent_name'),
    )
    op.create_index('ix_agent_capabilities_agent_name', 'agent_capabilities', ['agent_name'])


def downgrade():
    op.drop_index('ix_agent_capabilities_agent_name', table_name='agent_capabilities')
    op.drop_table('agent_capabilities')

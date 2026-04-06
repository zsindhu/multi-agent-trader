"""add_agent_messages_table

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-04-06 00:00:03.000000

Inter-agent communication bus. Any agent writes, any agent reads.
"""
from alembic import op
import sqlalchemy as sa

revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('sender', sa.String(64), nullable=False),
        sa.Column('recipient', sa.String(64), nullable=True),
        sa.Column('message_type', sa.String(64), nullable=False),
        sa.Column('subject', sa.String(256), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('read_by_lead_agent', sa.Boolean(), default=False, nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_messages_timestamp', 'agent_messages', ['timestamp'])
    op.create_index('ix_agent_messages_sender', 'agent_messages', ['sender'])
    op.create_index('ix_agent_messages_recipient', 'agent_messages', ['recipient'])
    op.create_index('ix_agent_messages_message_type', 'agent_messages', ['message_type'])
    op.create_index('ix_agent_messages_read_by_lead_agent', 'agent_messages', ['read_by_lead_agent'])


def downgrade():
    op.drop_index('ix_agent_messages_read_by_lead_agent', table_name='agent_messages')
    op.drop_index('ix_agent_messages_message_type', table_name='agent_messages')
    op.drop_index('ix_agent_messages_recipient', table_name='agent_messages')
    op.drop_index('ix_agent_messages_sender', table_name='agent_messages')
    op.drop_index('ix_agent_messages_timestamp', table_name='agent_messages')
    op.drop_table('agent_messages')

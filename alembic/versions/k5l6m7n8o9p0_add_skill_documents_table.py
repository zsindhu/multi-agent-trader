"""add_skill_documents_table

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-04-06 00:00:04.000000

Versioned markdown documents per agent. Each agent maintains its own
evolving self-description. Old versions preserved for audit.
"""
from alembic import op
import sqlalchemy as sa

revision = 'k5l6m7n8o9p0'
down_revision = 'j4k5l6m7n8o9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'skill_documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_name', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(256), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_name', 'version', name='uq_skill_doc_agent_version'),
    )
    op.create_index('ix_skill_documents_agent_name', 'skill_documents', ['agent_name'])


def downgrade():
    op.drop_index('ix_skill_documents_agent_name', table_name='skill_documents')
    op.drop_table('skill_documents')

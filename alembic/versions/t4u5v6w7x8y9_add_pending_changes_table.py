"""add_pending_changes_table

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-04-22 00:00:02.000000

Tracks proposed config changes through the validation pipeline.
"""
from alembic import op
import sqlalchemy as sa

revision = 't4u5v6w7x8y9'
down_revision = 's3t4u5v6w7x8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pending_changes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('change_type', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('proposed_config', sa.JSON(), nullable=False),
        sa.Column('current_config', sa.JSON(), nullable=True),
        sa.Column('backtest_result', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(32), default='proposed', nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewer_notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('pending_changes')

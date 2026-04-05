"""add_worker_state_table

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-02 00:00:00.000000

Adds worker_states table so both the API container and agents container
can read/write worker is_active state without inter-process communication.
Seeds the three known workers as active.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    worker_states = op.create_table(
        'worker_states',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('worker_name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('paused_reason', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('worker_name'),
    )
    op.create_index('ix_worker_states_worker_name', 'worker_states', ['worker_name'])

    op.bulk_insert(worker_states, [
        {'worker_name': 'Covered-Calls', 'is_active': True, 'paused_reason': None},
        {'worker_name': 'Cash-Secured-Puts', 'is_active': True, 'paused_reason': None},
        {'worker_name': 'Wheel', 'is_active': True, 'paused_reason': None},
    ])


def downgrade():
    op.drop_index('ix_worker_states_worker_name', table_name='worker_states')
    op.drop_table('worker_states')

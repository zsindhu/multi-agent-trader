"""add_execution_log_table

Revision ID: f1e2d3c4b5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'execution_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('option_symbol', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('contract_type', sa.String(), nullable=True),
        sa.Column('strike', sa.Float(), nullable=True),
        sa.Column('expiration', sa.String(), nullable=True),
        sa.Column('delta', sa.Float(), nullable=True),
        sa.Column('dte', sa.Integer(), nullable=True),
        sa.Column('premium', sa.Float(), nullable=True),
        sa.Column('annualized_return', sa.Float(), nullable=True),
        sa.Column('probability_of_profit', sa.Float(), nullable=True),
        sa.Column('collateral_required', sa.Float(), nullable=True),
        sa.Column('break_even_price', sa.Float(), nullable=True),
        sa.Column('iv_rank_at_entry', sa.Float(), nullable=True),
        sa.Column('scanner_score', sa.Float(), nullable=True),
        sa.Column('stock_price_at_entry', sa.Float(), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('order_status', sa.String(), nullable=True),
        sa.Column('fill_price', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_execution_logs_agent_name', 'execution_logs', ['agent_name'])
    op.create_index('ix_execution_logs_symbol', 'execution_logs', ['symbol'])
    op.create_index('ix_execution_logs_created_at', 'execution_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_execution_logs_created_at', table_name='execution_logs')
    op.drop_index('ix_execution_logs_symbol', table_name='execution_logs')
    op.drop_index('ix_execution_logs_agent_name', table_name='execution_logs')
    op.drop_table('execution_logs')

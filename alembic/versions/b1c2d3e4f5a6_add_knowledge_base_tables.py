"""add_knowledge_base_tables

Revision ID: b1c2d3e4f5a6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-02 00:00:00.000000

Adds two tables for the evolving knowledge base:
- playbook_entries: qualitative narrative insights written by the LLM each cycle
- strategy_insights: structured, enforceable rules validated by the Performance Analyst
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── playbook_entries ────────────────────────────────────────────
    op.create_table(
        'playbook_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('validated', sa.Boolean(), server_default=sa.false(), nullable=True),
        sa.Column('trades_supporting', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('superseded_by', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_playbook_entries_category', 'playbook_entries', ['category'])
    op.create_index('ix_playbook_entries_active', 'playbook_entries', ['active'])

    # ── strategy_insights ───────────────────────────────────────────
    op.create_table(
        'strategy_insights',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('insight_type', sa.String(), nullable=False),
        sa.Column('rule', sa.Text(), nullable=False),
        sa.Column('parameters', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default=sa.text('0.5')),
        sa.Column('supporting_trades', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('contradicting_trades', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('win_rate_with', sa.Float(), nullable=True),
        sa.Column('win_rate_without', sa.Float(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_validated', sa.DateTime(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_strategy_insights_insight_type', 'strategy_insights', ['insight_type'])
    op.create_index('ix_strategy_insights_active', 'strategy_insights', ['active'])


def downgrade() -> None:
    op.drop_index('ix_strategy_insights_active', table_name='strategy_insights')
    op.drop_index('ix_strategy_insights_insight_type', table_name='strategy_insights')
    op.drop_table('strategy_insights')

    op.drop_index('ix_playbook_entries_active', table_name='playbook_entries')
    op.drop_index('ix_playbook_entries_category', table_name='playbook_entries')
    op.drop_table('playbook_entries')

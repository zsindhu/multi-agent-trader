"""add_cycle_snapshots_table

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-04-06 00:00:01.000000

One row per LLM cycle. Captures full system state at decision time,
with structured columns for fast queries and a JSONB blob for everything else.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cycle_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Regime context
        sa.Column('regime', sa.String(32), nullable=True),
        sa.Column('regime_confidence', sa.Float(), nullable=True),
        sa.Column('vix_level', sa.Float(), nullable=True),
        sa.Column('vix_direction', sa.String(16), nullable=True),
        sa.Column('breadth_pct', sa.Float(), nullable=True),
        sa.Column('spy_trend', sa.String(16), nullable=True),
        sa.Column('credit_stress', sa.String(8), nullable=True),
        # Portfolio state
        sa.Column('equity', sa.Float(), nullable=True),
        sa.Column('cash', sa.Float(), nullable=True),
        sa.Column('buying_power', sa.Float(), nullable=True),
        sa.Column('open_positions_count', sa.Integer(), nullable=True),
        sa.Column('unrealized_pnl', sa.Float(), nullable=True),
        # Cycle outcomes
        sa.Column('actions_decided', sa.Integer(), nullable=True),
        sa.Column('actions_executed', sa.Integer(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        # LLM cost tracking
        sa.Column('llm_tokens_in', sa.Integer(), nullable=True),
        sa.Column('llm_tokens_out', sa.Integer(), nullable=True),
        sa.Column('llm_cost_usd', sa.Float(), nullable=True),
        sa.Column('llm_model', sa.String(64), nullable=True),
        # Full context blob
        sa.Column('full_context', postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cycle_snapshots_timestamp', 'cycle_snapshots', ['timestamp'])
    op.create_index('ix_cycle_snapshots_regime', 'cycle_snapshots', ['regime'])


def downgrade():
    op.drop_index('ix_cycle_snapshots_regime', table_name='cycle_snapshots')
    op.drop_index('ix_cycle_snapshots_timestamp', table_name='cycle_snapshots')
    op.drop_table('cycle_snapshots')

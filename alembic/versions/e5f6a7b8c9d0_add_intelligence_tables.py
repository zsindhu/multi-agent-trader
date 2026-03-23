"""add_intelligence_tables

Revision ID: e5f6a7b8c9d0
Revises: f1e2d3c4b5a6
Create Date: 2026-03-23 00:00:00.000000

Adds four tables for the market intelligence services:
- regime_snapshots: macro regime assessments (VIX, breadth, SPY trend, sectors)
- earnings_events: upcoming earnings and dividend dates per symbol
- performance_insights: computed trading analytics stored as JSON blobs
- news_headlines: market and company news headlines from Finnhub
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'f1e2d3c4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── regime_snapshots ────────────────────────────────────────────
    op.create_table(
        'regime_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('regime', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('vix_level', sa.Float(), nullable=True),
        sa.Column('vix_direction', sa.String(), nullable=True),
        sa.Column('breadth_pct', sa.Float(), nullable=True),
        sa.Column('breadth_trend', sa.String(), nullable=True),
        sa.Column('spy_trend', sa.String(), nullable=True),
        sa.Column('spy_distance_from_20ma', sa.Float(), nullable=True),
        sa.Column('sector_leader', sa.String(), nullable=True),
        sa.Column('sector_laggard', sa.String(), nullable=True),
        sa.Column('rotation_signal', sa.String(), nullable=True),
        sa.Column('credit_stress', sa.Boolean(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('sector_returns', sa.Text(), nullable=True),
        sa.Column('computed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_regime_snapshots_regime', 'regime_snapshots', ['regime'])
    op.create_index('ix_regime_snapshots_computed_at', 'regime_snapshots', ['computed_at'])

    # ── earnings_events ─────────────────────────────────────────────
    op.create_table(
        'earnings_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('days_until', sa.Integer(), nullable=True),
        sa.Column('risk_level', sa.String(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_earnings_events_symbol', 'earnings_events', ['symbol'])
    op.create_index('ix_earnings_events_fetched_at', 'earnings_events', ['fetched_at'])

    # ── performance_insights ─────────────────────────────────────────
    op.create_table(
        'performance_insights',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('insight_type', sa.String(), nullable=False),
        sa.Column('period', sa.String(), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_performance_insights_insight_type', 'performance_insights', ['insight_type'])
    op.create_index('ix_performance_insights_computed_at', 'performance_insights', ['computed_at'])

    # ── news_headlines ───────────────────────────────────────────────
    op.create_table(
        'news_headlines',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('symbols', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_news_headlines_published_at', 'news_headlines', ['published_at'])


def downgrade() -> None:
    op.drop_index('ix_news_headlines_published_at', table_name='news_headlines')
    op.drop_table('news_headlines')

    op.drop_index('ix_performance_insights_computed_at', table_name='performance_insights')
    op.drop_index('ix_performance_insights_insight_type', table_name='performance_insights')
    op.drop_table('performance_insights')

    op.drop_index('ix_earnings_events_fetched_at', table_name='earnings_events')
    op.drop_index('ix_earnings_events_symbol', table_name='earnings_events')
    op.drop_table('earnings_events')

    op.drop_index('ix_regime_snapshots_computed_at', table_name='regime_snapshots')
    op.drop_index('ix_regime_snapshots_regime', table_name='regime_snapshots')
    op.drop_table('regime_snapshots')

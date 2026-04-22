"""add_research_views

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-04-22 00:00:03.000000

PostgreSQL views for the Research Inspector. Provides pre-aggregated
queries for promotions, trades, signal performance, daily summaries,
and the learning loop.
"""
from alembic import op

revision = 'u5v6w7x8y9z0'
down_revision = 't4u5v6w7x8y9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # Views use PostgreSQL-specific syntax

    op.execute("""
        CREATE OR REPLACE VIEW v_today_promotions AS
        SELECT
            no.symbol,
            no.composite_score,
            no.price,
            no.asset_type,
            no.analysis->'signals_fired' AS signals_fired,
            no.analysis->>'reason' AS firing_rules,
            no.analysis->'signals'->'earnings_proximity'->>'raw' AS earnings_days,
            no.analysis->>'amplification_applied' AS amplification,
            LEFT(no.analysis->>'tier2b_reasoning', 200) AS reasoning_preview,
            no.analysis->>'config_version' AS config_version,
            no.timestamp
        FROM name_observations no
        WHERE no.tier = 2
          AND no.was_considered = true
          AND no.timestamp >= CURRENT_DATE
        ORDER BY no.composite_score DESC
    """)

    op.execute("""
        CREATE OR REPLACE VIEW v_recent_trades AS
        SELECT
            t.id AS trade_id,
            t.symbol,
            t.trade_type,
            t.side,
            t.strike,
            t.expiration,
            t.premium,
            t.status,
            t.created_at,
            t.closed_at,
            o.outcome,
            o.pnl_dollars,
            o.pnl_percent,
            o.holding_days,
            o.underlying_return,
            o.funnel_driven
        FROM trades t
        LEFT JOIN trade_outcomes o ON o.trade_id = t.id
        WHERE t.created_at >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY t.created_at DESC
    """)

    op.execute("""
        CREATE OR REPLACE VIEW v_signal_performance AS
        SELECT
            key AS signal_name,
            COUNT(*) AS total_observations,
            COUNT(*) FILTER (WHERE (value->>'fired')::boolean = true) AS times_fired,
            ROUND(
                COUNT(*) FILTER (WHERE (value->>'fired')::boolean = true)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS fire_rate_pct
        FROM name_observations,
             jsonb_each(analysis::jsonb->'signals') AS s(key, value)
        WHERE tier = 2
          AND was_considered = true
          AND timestamp >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY key
        ORDER BY fire_rate_pct DESC
    """)

    op.execute("""
        CREATE OR REPLACE VIEW v_daily_summary AS
        SELECT
            DATE(timestamp) AS day,
            COUNT(*) FILTER (WHERE tier = 1 AND was_considered = true) AS tier1_passed,
            COUNT(*) FILTER (WHERE tier = 2 AND was_considered = true) AS tier2_promoted,
            COUNT(*) FILTER (WHERE tier = 2 AND NOT was_considered) AS tier2_rejected
        FROM name_observations
        WHERE timestamp >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
    """)

    op.execute("""
        CREATE OR REPLACE VIEW v_learning_loop AS
        SELECT
            sender,
            message_type,
            subject,
            LEFT(body, 500) AS body_preview,
            timestamp
        FROM agent_messages
        WHERE sender IN ('Research-Analyst', 'Pre-Market-Briefing', 'Signal-Learner', 'Fundamentals-Analyst')
          AND timestamp >= CURRENT_DATE - INTERVAL '7 days'
        ORDER BY timestamp DESC
        LIMIT 20
    """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS v_learning_loop")
    op.execute("DROP VIEW IF EXISTS v_daily_summary")
    op.execute("DROP VIEW IF EXISTS v_signal_performance")
    op.execute("DROP VIEW IF EXISTS v_recent_trades")
    op.execute("DROP VIEW IF EXISTS v_today_promotions")

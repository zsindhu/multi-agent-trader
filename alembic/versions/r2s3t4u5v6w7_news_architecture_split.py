"""news_architecture_split

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-04-13 00:00:01.000000

Split news_headlines into two purpose-specific tables:
- macro_news_events: broad-market environmental context (90d retention)
- symbol_news_headlines: per-name company news for Tier 2a scoring (35d retention)

Renames the old news_headlines table to news_headlines_legacy.
"""
from alembic import op
import sqlalchemy as sa

revision = 'r2s3t4u5v6w7'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Create macro_news_events
    op.create_table(
        'macro_news_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('source', sa.String(128), nullable=True),
        sa.Column('url', sa.String(512), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('topics', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_macro_news_events_published_at', 'macro_news_events', ['published_at'])

    # Create symbol_news_headlines
    op.create_table(
        'symbol_news_headlines',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(16), nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('source', sa.String(128), nullable=True),
        sa.Column('url', sa.String(512), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_symbol_news_headlines_symbol', 'symbol_news_headlines', ['symbol'])
    op.create_index('ix_symbol_news_headlines_published_at', 'symbol_news_headlines', ['published_at'])
    op.create_index('ix_symbol_news_symbol_published', 'symbol_news_headlines', ['symbol', 'published_at'])

    # Rename old table to legacy (keep data accessible for rollback)
    if bind.dialect.name == "postgresql":
        op.rename_table('news_headlines', 'news_headlines_legacy')
    # SQLite (preflight): just create the new tables, skip rename


def downgrade():
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.rename_table('news_headlines_legacy', 'news_headlines')

    op.drop_index('ix_symbol_news_symbol_published', table_name='symbol_news_headlines')
    op.drop_index('ix_symbol_news_headlines_published_at', table_name='symbol_news_headlines')
    op.drop_index('ix_symbol_news_headlines_symbol', table_name='symbol_news_headlines')
    op.drop_table('symbol_news_headlines')

    op.drop_index('ix_macro_news_events_published_at', table_name='macro_news_events')
    op.drop_table('macro_news_events')

"""add_order_id_to_trades

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-06 00:00:00.000000

Adds order_id column to the trades table so OrderReconciler can match
Trade records back to Alpaca orders. Without this column the reconciler
raised AttributeError every cycle and all submitted orders stayed stuck
in status="submitted" forever.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('trades', sa.Column('order_id', sa.String(64), nullable=True))
    op.create_index('ix_trades_order_id', 'trades', ['order_id'])


def downgrade():
    op.drop_index('ix_trades_order_id', table_name='trades')
    op.drop_column('trades', 'order_id')

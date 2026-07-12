"""Add decision-snapshot, sleeve, and fill columns to trades

Freeze-at-decision (RECON_PRE_REMEDIATION_VERIFICATION.md Q5a): the signal
snapshot the Lead Agent traded on is copied onto the trade at write time,
because tier2a's sweeps used to destroy it before the nightly labeler ran.
sleeve_id rides the same new plumbing. fill_price/filled_at give the
reconciler a home for broker fill data without overloading `price`.

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("name_observation_id", sa.Integer(), nullable=True))
    op.add_column("trades", sa.Column("signal_snapshot", sa.JSON(), nullable=True))
    op.add_column("trades", sa.Column("sleeve_id", sa.String(32), nullable=True))
    op.add_column("trades", sa.Column("fill_price", sa.Float(), nullable=True))
    op.add_column("trades", sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_trades_name_observation_id", "trades", ["name_observation_id"])
    op.create_index("ix_trades_sleeve_id", "trades", ["sleeve_id"])


def downgrade() -> None:
    op.drop_index("ix_trades_sleeve_id", table_name="trades")
    op.drop_index("ix_trades_name_observation_id", table_name="trades")
    op.drop_column("trades", "filled_at")
    op.drop_column("trades", "fill_price")
    op.drop_column("trades", "sleeve_id")
    op.drop_column("trades", "signal_snapshot")
    op.drop_column("trades", "name_observation_id")

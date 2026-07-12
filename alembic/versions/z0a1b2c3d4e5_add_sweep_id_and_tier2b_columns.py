"""Append-only sweeps: sweep_id + dedicated tier2b columns on name_observations

tier2a/breadth sweeps used to DELETE the day's rows and reinsert, destroying
traded-on signal snapshots and tier2b reasoning 3x/day. Sweeps now append,
stamped with a sortable sweep_id ("YYYYMMDDTHHMMSS-t<tier>-<suffix>") so
"latest sweep" is MAX(sweep_id). Tier2b reasoning moves out of the analysis
JSONB into its own columns so the mechanical snapshot is never mutated.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("name_observations", sa.Column("sweep_id", sa.String(48), nullable=True))
    op.create_index("ix_name_observations_sweep_id", "name_observations", ["sweep_id"])
    # Unique INDEX (not constraint): same idempotency guarantee, and SQLite
    # (used by the preflight smoke test) can't ALTER constraints in place.
    op.create_index(
        "uq_nobs_sweep_symbol_tier",
        "name_observations",
        ["sweep_id", "symbol", "tier"],
        unique=True,
    )
    op.add_column("name_observations", sa.Column("tier2b_reasoning", sa.Text(), nullable=True))
    op.add_column(
        "name_observations",
        sa.Column("tier2b_reasoned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("name_observations", "tier2b_reasoned_at")
    op.drop_column("name_observations", "tier2b_reasoning")
    op.drop_index("uq_nobs_sweep_symbol_tier", table_name="name_observations")
    op.drop_index("ix_name_observations_sweep_id", table_name="name_observations")
    op.drop_column("name_observations", "sweep_id")

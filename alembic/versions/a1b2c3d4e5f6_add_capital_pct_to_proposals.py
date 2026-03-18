"""add_capital_pct_to_proposals

Revision ID: a1b2c3d4e5f6
Revises: 5c460d2ff840
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '5c460d2ff840'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add capital-awareness columns to proposals table."""
    op.add_column('proposals', sa.Column('pct_of_buying_power', sa.Float(), nullable=True))
    op.add_column('proposals', sa.Column('cumulative_pct', sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove capital-awareness columns from proposals table."""
    op.drop_column('proposals', 'cumulative_pct')
    op.drop_column('proposals', 'pct_of_buying_power')

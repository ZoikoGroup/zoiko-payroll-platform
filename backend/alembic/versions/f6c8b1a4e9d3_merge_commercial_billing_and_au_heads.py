"""merge commercial billing standard chain and AU/main head

Revision ID: f6c8b1a4e9d3
Revises: e5b3f9a1d7c4, 1dc04f15a9b7
Create Date: 2026-09-18 00:00:04.000000

No-op bookkeeping merge, same pattern as fbfe6d7eeb2e_merge_australia_and_
remaining_heads.py and 02d251c47245_merge_au_chain_with_reconciled_main_.py.
The Commercial Billing & Subscription Operating Standard chain
(a3f5c9d1b2e4 ... e5b3f9a1d7c4) forked from fbfe6d7eeb2e at the same point
the AU chain did (via cf02e8e13ac3 / 02d251c47245 / 1dc04f15a9b7) — both are
real, independent lines of work on the same common ancestor, landing at
different times. This migration only unifies the Alembic graph bookkeeping
into a single head; it changes nothing in the database schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c8b1a4e9d3'
down_revision: Union[str, Sequence[str], None] = ('e5b3f9a1d7c4', '1dc04f15a9b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "Cannot safely downgrade a merge point without selecting a branch."
    )

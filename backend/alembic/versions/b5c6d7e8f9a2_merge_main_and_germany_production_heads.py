"""merge main and germany production heads

Revision ID: b5c6d7e8f9a2
Revises: a2c3e4f5b6d7, d6e7f8a9b0c1
Create Date: 2026-09-08 00:00:00.000000

Phase 8BK — reconciles the two independently-developed Alembic chains
that diverged after the shared ancestor `d7e2f4a91b53`: `d6e7f8a9b0c1`
(main's own Canada/US/UK work, 19 migrations) and `a2c3e4f5b6d7`
(the Germany production chain, 25 migrations, preserved via
`germany-production-preservation`/`nikhil`). No-op, additive-only merge
point — it changes nothing in the database schema itself, it only
unifies the migration graph bookkeeping into a single head so
`alembic upgrade head` has one unambiguous target. Mirrors the exact
same pattern this repository already used once before for an earlier
head divergence (`de3521c74a64_merge_conflicting_heads.py`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a2'
down_revision: Union[str, Sequence[str], None] = ('a2c3e4f5b6d7', 'd6e7f8a9b0c1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

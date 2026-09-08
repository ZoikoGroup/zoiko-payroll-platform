"""merge main and germany production heads 2

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a2, b6c7d8e9f0a1
Create Date: 2026-09-08 00:00:00.000000

Phase 8BK follow-up — reconciles the two heads that appeared after
`origin/main` advanced past the point (`9f7c230`) the first merge
(`b5c6d7e8f9a2`) was based on: `b6c7d8e9f0a1` (main's own further India/
UK work — employer NPS, tax residency status, gender, director fields,
date of leaving, LWF, EPS/EDLI, apprenticeship levy, employee
establishments, contribution-rate precision). No-op, additive-only merge
point — changes nothing in the database schema itself, only unifies the
migration graph bookkeeping into a single head.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = ('b5c6d7e8f9a2', 'b6c7d8e9f0a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

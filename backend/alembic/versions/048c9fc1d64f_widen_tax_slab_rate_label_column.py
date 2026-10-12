"""widen tax slab rate_label column

Revision ID: 048c9fc1d64f
Revises: 71d815f06d78
Create Date: 2026-08-31 15:50:24.456933

payroll_tax_slabs.rate_label was VARCHAR(20) — sized for the short values
it was originally meant for ("5%", "Nil"). The Super Admin NI Category
Band form (added for UK NI_BAND rows) invites a real descriptive label
(e.g. "Main Rate Band (PT to UEL)", 27 chars), which crashed with a raw
psycopg StringDataRightTruncation on save (surfaced to the UI as a bare
"Request failed (500)"). Widened to 150, matching the sibling
tax_formula column's length and this model's other *_label columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '048c9fc1d64f'
down_revision: Union[str, Sequence[str], None] = '71d815f06d78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'payroll_tax_slabs', 'rate_label',
        existing_type=sa.String(length=20), type_=sa.String(length=150),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Lossy if any row's rate_label now exceeds 20 chars — narrowing back
    # would raise the same StringDataRightTruncation this migration fixes.
    op.alter_column(
        'payroll_tax_slabs', 'rate_label',
        existing_type=sa.String(length=150), type_=sa.String(length=20),
        existing_nullable=False,
    )

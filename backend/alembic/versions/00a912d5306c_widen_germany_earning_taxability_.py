"""widen germany earning taxability treatment columns to 40

Revision ID: 00a912d5306c
Revises: 752aa7829541
Create Date: 2026-09-18 11:56:28.962603

Schema drift found while seeding the real Germany 2026 earning taxability
matrix: models.py's GermanyEarningTaxabilityRule.gkv_pv_treatment/
rv_alv_treatment were widened to String(40) in code, but no migration ever
applied that to the actual database — the live columns were still
VARCHAR(30), left over from before the widen. Real spec values (e.g.
"CONTRIBUTORY_SUBJECT_TO_ALLOCATION", 34 chars) exceed 30 and raised
StringDataRightTruncation on insert. Purely additive: widening a VARCHAR
never truncates or rejects any existing row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00a912d5306c'
down_revision: Union[str, Sequence[str], None] = '752aa7829541'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "payroll_germany_earning_taxability_rules", "gkv_pv_treatment",
        existing_type=sa.String(length=30), type_=sa.String(length=40), existing_nullable=False,
    )
    op.alter_column(
        "payroll_germany_earning_taxability_rules", "rv_alv_treatment",
        existing_type=sa.String(length=30), type_=sa.String(length=40), existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "payroll_germany_earning_taxability_rules", "rv_alv_treatment",
        existing_type=sa.String(length=40), type_=sa.String(length=30), existing_nullable=False,
    )
    op.alter_column(
        "payroll_germany_earning_taxability_rules", "gkv_pv_treatment",
        existing_type=sa.String(length=40), type_=sa.String(length=30), existing_nullable=False,
    )

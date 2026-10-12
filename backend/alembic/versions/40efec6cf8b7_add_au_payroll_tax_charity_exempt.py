"""add au payroll tax charity exempt column

Revision ID: 40efec6cf8b7
Revises: 821472fb0a99
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), §18 employer
overlay follow-up — payroll_company_compliance.au_payroll_tax_charity_exempt,
a human-entered eligibility determination (never computed) that suppresses
state/territory payroll tax liability to $0 while true. See
models.CompanyComplianceDetails's own docstring.

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
821472fb0a99 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision; this file is not applied to any
database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40efec6cf8b7'
down_revision: Union[str, Sequence[str], None] = '821472fb0a99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_company_compliance', sa.Column('au_payroll_tax_charity_exempt', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_company_compliance', 'au_payroll_tax_charity_exempt')

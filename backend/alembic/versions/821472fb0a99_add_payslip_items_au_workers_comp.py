"""add payslip items au workers compensation premium

Revision ID: 821472fb0a99
Revises: 8849ac83b135
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), §18 employer
overlay follow-up — payslip_items.au_workers_compensation_premium, an
employer-liability-only figure resolved from a tenant-specific
EmployerTaxProfile row (component_code "AU_WORKERS_COMP"), same AU-D05
contract as employer_payroll_tax. See models.PayslipItem's own docstring.

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
8849ac83b135 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision; this file is not applied to any
database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '821472fb0a99'
down_revision: Union[str, Sequence[str], None] = '8849ac83b135'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('au_workers_compensation_premium', sa.Numeric(12, 2), server_default='0', nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'au_workers_compensation_premium')

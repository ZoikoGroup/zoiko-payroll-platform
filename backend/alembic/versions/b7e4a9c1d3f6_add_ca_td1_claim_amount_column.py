"""add payroll_employees.td1_claim_amount (Canada TD1 federal claim amount)

Revision ID: b7e4a9c1d3f6
Revises: d7e2f4a91b53
Create Date: 2026-09-02 00:00:00.000000

Additive only: one new nullable column on payroll_employees. Promotes the
Canada TD1 federal total claim amount out of the pre-existing
compliance_fields JSON blob (already collected via the employee form/
CAEmployeeValidation, but never read by the payroll engine) into a real,
engine-read column — the same "close the dead-plumbing gap" pattern
already applied to US w4_filing_status and UK tax_code/ni_category. No
existing column/table semantics change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e4a9c1d3f6'
down_revision: Union[str, Sequence[str], None] = 'd7e2f4a91b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('td1_claim_amount', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'td1_claim_amount')

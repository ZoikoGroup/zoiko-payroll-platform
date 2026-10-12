"""add australia declaration columns

Revision ID: 2fdc8b69e57d
Revises: 4b296dbd4181
Create Date: 2026-09-16

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Phase 0 —
employee declaration fields driving ATO Schedule 1/8 scale selection
(payroll_employees.au_*) and the regional-employer payroll-tax
classification flag (payroll_company_compliance.au_payroll_tax_regional_status).
See models.PayrollEmployee/models.CompanyComplianceDetails docstrings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fdc8b69e57d'
down_revision: Union[str, Sequence[str], None] = '4b296dbd4181'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('au_tfn_status', sa.String(20), nullable=True))
    op.add_column('payroll_employees', sa.Column('au_residency_status', sa.String(25), nullable=True))
    op.add_column('payroll_employees', sa.Column('au_tax_free_threshold_claimed', sa.Boolean(), nullable=True))
    op.add_column('payroll_employees', sa.Column('au_medicare_levy_exemption', sa.String(10), nullable=True))
    op.add_column('payroll_employees', sa.Column('au_withholding_variation_pct', sa.Numeric(5, 2), nullable=True))
    op.add_column('payroll_company_compliance', sa.Column('au_payroll_tax_regional_status', sa.String(20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_company_compliance', 'au_payroll_tax_regional_status')
    op.drop_column('payroll_employees', 'au_withholding_variation_pct')
    op.drop_column('payroll_employees', 'au_medicare_levy_exemption')
    op.drop_column('payroll_employees', 'au_tax_free_threshold_claimed')
    op.drop_column('payroll_employees', 'au_residency_status')
    op.drop_column('payroll_employees', 'au_tfn_status')

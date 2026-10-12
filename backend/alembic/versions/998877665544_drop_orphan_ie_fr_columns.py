"""drop orphan IE and FR columns left by unmerged branches

Revision ID: 998877665544
Revises: f0b1c2d3e4f5
Create Date: 2026-09-28 00:00:00.000000

Revisions from unmerged Ireland (IE) and France (FR) feature branches previously
stamped into the live production database added the following columns directly
to the live database:

  payroll_employee_statutory_profiles:
    ie_contracted_weekly_hours, ie_emergency_reason, ie_emergency_week,
    ie_employer_reference, ie_pension_qualifying_exemption_effective_from,
    ie_pension_qualifying_exemption_reference, ie_pension_scheme_reference,
    ie_ppsn, ie_prsi_class, ie_prsi_exemption_reference,
    ie_revenue_employment_id, ie_sector_wage_order, ie_usc_status

  payslip_items:
    fr_calculation_snapshot

None of these columns are referenced by any current model, service, schema,
or test. This migration removes them so the DB schema matches the declared
SQLAlchemy models (checked by scripts/check_schema_drift.py at deploy time).

Written defensively: each column is only dropped if it actually exists, so
this migration is safe to re-run and safe to apply to databases that were
never affected by the orphan branches.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '998877665544'
down_revision: Union[str, Sequence[str], None] = 'f0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IE_PROFILE_COLUMNS = [
    'ie_contracted_weekly_hours',
    'ie_emergency_reason',
    'ie_emergency_week',
    'ie_employer_reference',
    'ie_pension_qualifying_exemption_effective_from',
    'ie_pension_qualifying_exemption_reference',
    'ie_pension_scheme_reference',
    'ie_ppsn',
    'ie_prsi_class',
    'ie_prsi_exemption_reference',
    'ie_revenue_employment_id',
    'ie_sector_wage_order',
    'ie_usc_status',
]

_FR_PAYSLIP_COLUMNS = [
    'fr_calculation_snapshot',
]


def _existing_columns(bind, table_name):
    """Return the set of column names currently on *table_name*."""
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Drop orphaned IE and FR columns that have no matching model definitions."""
    bind = op.get_bind()

    existing_profiles = _existing_columns(bind, 'payroll_employee_statutory_profiles')
    for col in _IE_PROFILE_COLUMNS:
        if col in existing_profiles:
            op.drop_column('payroll_employee_statutory_profiles', col)

    existing_payslips = _existing_columns(bind, 'payslip_items')
    for col in _FR_PAYSLIP_COLUMNS:
        if col in existing_payslips:
            op.drop_column('payslip_items', col)


def downgrade() -> None:
    """Re-add the IE and FR columns (restores the orphan branch DB state)."""
    op.add_column(
        'payslip_items',
        sa.Column('fr_calculation_snapshot', sa.JSON(), nullable=True),
    )
    for col in _IE_PROFILE_COLUMNS:
        if 'effective_from' in col:
            op.add_column('payroll_employee_statutory_profiles', sa.Column(col, sa.Date(), nullable=True))
        elif col in ('ie_contracted_weekly_hours', 'ie_emergency_week'):
            op.add_column('payroll_employee_statutory_profiles', sa.Column(col, sa.Integer(), nullable=True))
        else:
            op.add_column('payroll_employee_statutory_profiles', sa.Column(col, sa.String(length=100), nullable=True))

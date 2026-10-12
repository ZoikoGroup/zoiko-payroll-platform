"""merge main's orphan-column drop with venu's IE/FR chain; restore IE/FR columns

Revision ID: 7c3e1a9d5f20
Revises: 998877665544, a1b2c3d4e5f7
Create Date: 2026-09-28 00:00:00.000000

Main's ``998877665544`` dropped 13 ``ie_*`` columns from
payroll_employee_statutory_profiles and ``fr_calculation_snapshot`` from
payslip_items as "orphans from unmerged branches". On venu's branch those
columns are live model fields (Ireland: ``b1c2d3e4f5a6``; France:
``74aeb450aeee``), so this merge re-adds any that are missing, with the exact
types the models declare.

Written defensively: each column is only added if it is absent, so it is a
no-op on databases where ``998877665544`` never ran (or found nothing to drop).
``998877665544`` itself is left untouched because it may already be recorded
in a live database's history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c3e1a9d5f20'
down_revision: Union[str, Sequence[str], None] = ('998877665544', 'a1b2c3d4e5f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IE_PROFILE_COLUMNS = [
    ('ie_ppsn', sa.String(length=15)),
    ('ie_employer_reference', sa.String(length=32)),
    ('ie_revenue_employment_id', sa.String(length=64)),
    ('ie_prsi_class', sa.String(length=10)),
    ('ie_prsi_exemption_reference', sa.String(length=64)),
    ('ie_usc_status', sa.String(length=20)),
    ('ie_pension_scheme_reference', sa.String(length=64)),
    ('ie_pension_qualifying_exemption_reference', sa.String(length=64)),
    ('ie_pension_qualifying_exemption_effective_from', sa.Date()),
    ('ie_contracted_weekly_hours', sa.Numeric(precision=5, scale=2)),
    ('ie_sector_wage_order', sa.String(length=10)),
    ('ie_emergency_reason', sa.Text()),
    ('ie_emergency_week', sa.Integer()),
]

_FR_PAYSLIP_COLUMNS = [
    ('fr_calculation_snapshot', sa.JSON()),
]


def _existing_columns(bind, table_name):
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    existing_profiles = _existing_columns(bind, 'payroll_employee_statutory_profiles')
    for name, type_ in _IE_PROFILE_COLUMNS:
        if name not in existing_profiles:
            op.add_column('payroll_employee_statutory_profiles', sa.Column(name, type_, nullable=True))

    existing_payslips = _existing_columns(bind, 'payslip_items')
    for name, type_ in _FR_PAYSLIP_COLUMNS:
        if name not in existing_payslips:
            op.add_column('payslip_items', sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    # Intentionally a no-op: the columns belong to b1c2d3e4f5a6 / 74aeb450aeee
    # on venu's side of the merge, which still expects them after downgrading
    # past this revision; 998877665544's own downgrade handles main's side.
    pass

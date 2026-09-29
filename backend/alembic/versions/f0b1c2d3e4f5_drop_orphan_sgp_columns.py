"""drop orphan SGP columns left by unmerged branch

Revision ID: f0b1c2d3e4f5
Revises: e7f1a2b3c4d5
Create Date: 2026-09-25 00:00:00.000000

The revision 'd2e3c4b5a6f7' (a Singapore payroll feature branch that was
never merged into main) was previously stamped into the production
alembic_version table and added the following columns directly to the live
database:

  payroll_employees:
    sgp_cpf_contribution_arrangement, sgp_cpf_residency_status,
    sgp_shg_funds, sgp_spr_effective_date, sgp_work_pass_end_date,
    sgp_work_pass_issue_date, sgp_work_pass_type, sgp_wp_levy_tier,
    sgp_wp_sector, sgp_wp_skill_level

  payslip_items:
    sgp_calculation_trace

None of these columns are referenced by any current model, service, schema,
or test. This migration removes them so the DB schema matches the declared
SQLAlchemy models (checked by scripts/check_schema_drift.py at deploy time).

Written defensively: each column is only dropped if it actually exists, so
this migration is safe to re-run and safe to apply to databases that were
never affected by the orphan branch.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0b1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = 'e7f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SGP_EMPLOYEE_COLUMNS = [
    'sgp_cpf_contribution_arrangement',
    'sgp_cpf_residency_status',
    'sgp_shg_funds',
    'sgp_spr_effective_date',
    'sgp_work_pass_end_date',
    'sgp_work_pass_issue_date',
    'sgp_work_pass_type',
    'sgp_wp_levy_tier',
    'sgp_wp_sector',
    'sgp_wp_skill_level',
]

_SGP_PAYSLIP_COLUMNS = [
    'sgp_calculation_trace',
]


def _existing_columns(bind, table_name):
    """Return the set of column names currently on *table_name*."""
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Drop orphaned SGP columns that have no matching model definitions."""
    bind = op.get_bind()

    existing_employee = _existing_columns(bind, 'payroll_employees')
    for col in _SGP_EMPLOYEE_COLUMNS:
        if col in existing_employee:
            op.drop_column('payroll_employees', col)

    existing_payslip = _existing_columns(bind, 'payslip_items')
    for col in _SGP_PAYSLIP_COLUMNS:
        if col in existing_payslip:
            op.drop_column('payslip_items', col)


def downgrade() -> None:
    """Re-add the SGP columns (restores the orphan branch's DB state).

    Column types are inferred from the orphan branch's schema dump.
    All columns are nullable so no existing data is affected.
    """
    op.add_column(
        'payslip_items',
        sa.Column('sgp_calculation_trace', sa.JSON(), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_wp_skill_level', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_wp_sector', sa.String(length=30), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_wp_levy_tier', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_work_pass_type', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_work_pass_issue_date', sa.Date(), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_work_pass_end_date', sa.Date(), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_spr_effective_date', sa.Date(), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_shg_funds', sa.String(length=50), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_cpf_residency_status', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('sgp_cpf_contribution_arrangement', sa.String(length=5), nullable=True),
    )

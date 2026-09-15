"""add germany payslip statutory snapshot columns

Revision ID: c4d6e8f9a0b1
Revises: b3c8d9e2f147
Create Date: 2026-09-03 00:00:00.000000

Additive only: two new nullable columns on the existing payslip_items
table (Phase 7, ZP-TAX-DE-2026-001) —

  employee_statutory_profile_id  FK -> payroll_employee_statutory_profiles.id
  germany_calculation_snapshot   JSON

These freeze, per finalized German payslip, exactly which
EmployeeStatutoryProfile version and which resolved PAP/health-fund/
ceiling/PV registry values produced it — the reproducibility guarantee
tax_policy_pack_id/tax_rule_snapshot already give every other country
(see PHASE_7_GERMANY_PAP_CALCULATION_INTEGRATION_REPORT.md §11/§12). No
existing column altered, no data migrated, no seed data inserted; both
columns are NULL for every payslip that exists today (zero German
payslips have ever been generated on this platform — see the Pre-Phase-7
audit and this phase's own report §18).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d6e8f9a0b1'
down_revision: Union[str, Sequence[str], None] = 'b3c8d9e2f147'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('employee_statutory_profile_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'payslip_items',
        sa.Column('germany_calculation_snapshot', sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        'fk_payslip_items_statutory_profile_id',
        'payslip_items', 'payroll_employee_statutory_profiles',
        ['employee_statutory_profile_id'], ['id'],
    )
    op.create_index(
        op.f('ix_payslip_items_employee_statutory_profile_id'),
        'payslip_items', ['employee_statutory_profile_id'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_payslip_items_employee_statutory_profile_id'), table_name='payslip_items')
    op.drop_constraint('fk_payslip_items_statutory_profile_id', 'payslip_items', type_='foreignkey')
    op.drop_column('payslip_items', 'germany_calculation_snapshot')
    op.drop_column('payslip_items', 'employee_statutory_profile_id')

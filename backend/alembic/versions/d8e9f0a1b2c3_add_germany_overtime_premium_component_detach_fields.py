"""add germany overtime premium component detach fields

Revision ID: d8e9f0a1b2c3
Revises: c7e2a94f6b31
Create Date: 2026-09-07 00:00:00.000000

Phase 8AQ — docs/PHASE_8AQ_GERMANY_OVERTIME_REVERSAL_AND_SOURCE_PRECEDENCE_HARDENING_REPORT.md.

Additive only: three new nullable-or-defaulted columns on the existing
payroll_germany_overtime_premium_components table —
attachment_status (NOT NULL, server_default 'NEVER_ATTACHED'),
detached_at, detached_by_id. No existing column is altered or dropped.

Backfill: every pre-existing row where payslip_allowance_item_id
IS NOT NULL (i.e. was already attached under the pre-Phase-8AQ scheme,
which had no separate status field) is set to attachment_status =
'ATTACHED' so its current state is preserved exactly — this migration
never changes which components are or aren't currently on a payslip,
it only makes that fact explicit in a dedicated column instead of
being inferred from payslip_allowance_item_id's nullability.

LOCAL/TEST VERIFICATION ONLY per this phase's explicit database-safety
rule — this migration was never applied to the shared remote Postgres
instance; it was verified only against a throwaway local SQLite
database (see the phase report's own Database Changes section).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7e2a94f6b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('attachment_status', sa.String(length=20), nullable=False, server_default='NEVER_ATTACHED'),
    )
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('detached_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('detached_by_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_overtime_premium_component_detached_by',
        'payroll_germany_overtime_premium_components', 'users',
        ['detached_by_id'], ['id'],
    )
    op.execute(
        "UPDATE payroll_germany_overtime_premium_components "
        "SET attachment_status = 'ATTACHED' "
        "WHERE payslip_allowance_item_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint('fk_overtime_premium_component_detached_by', 'payroll_germany_overtime_premium_components', type_='foreignkey')
    op.drop_column('payroll_germany_overtime_premium_components', 'detached_by_id')
    op.drop_column('payroll_germany_overtime_premium_components', 'detached_at')
    op.drop_column('payroll_germany_overtime_premium_components', 'attachment_status')

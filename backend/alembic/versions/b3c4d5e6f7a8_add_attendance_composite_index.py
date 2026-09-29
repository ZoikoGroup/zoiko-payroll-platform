"""add composite index on payroll_attendance_records for attendance queries

Revision ID: a1b2c3d4e5f7
Revises: 9f8e7d6c5b4a
Create Date: 2026-09-28

Phase 1.1: Add composite index on payroll_attendance_records(organization_id, date, employee_id)
to accelerate attendance history queries (get_attendance_records, get_attendance_history)
which filter by org + date range + optional employee_id.
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f7'
down_revision: str = '9f8e7d6c5b4a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index for the common query pattern:
    # WHERE organization_id = ? AND date >= ? AND date <= ? AND employee_id = ?
    op.create_index(
        'ix_payroll_attendance_org_date_emp',
        'payroll_attendance_records',
        ['organization_id', 'date', 'employee_id'],
        # CONCURRENTLY not supported in Alembic offline mode; run manually on prod if needed
    )


def downgrade() -> None:
    op.drop_index('ix_payroll_attendance_org_date_emp', table_name='payroll_attendance_records')
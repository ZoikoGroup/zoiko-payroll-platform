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


# ── Idempotency guards (2026-09-30) ──────────────────────────────────────
# Production already holds part of this schema: an earlier, unmerged
# France/Ireland branch ran these same migrations against it, and the
# 2026-09-29 deploy failed with DuplicateTable on payroll_fr_establishments.
# Each operation below is therefore skipped when its object already exists
# (or, for a drop, is already gone). A pre-existing object with the wrong
# SHAPE is not papered over: scripts.check_schema_drift runs right after
# the upgrade and fails the deploy, before the service restarts.
def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Composite index for the common query pattern:
    # WHERE organization_id = ? AND date >= ? AND date <= ? AND employee_id = ?
    if not _has_index('payroll_attendance_records', 'ix_payroll_attendance_org_date_emp'):
        op.create_index(
            'ix_payroll_attendance_org_date_emp',
            'payroll_attendance_records',
            ['organization_id', 'date', 'employee_id'],
            # CONCURRENTLY not supported in Alembic offline mode; run manually on prod if needed
        )


def downgrade() -> None:
    op.drop_index('ix_payroll_attendance_org_date_emp', table_name='payroll_attendance_records')
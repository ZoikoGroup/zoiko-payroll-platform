"""attendance gate: policy settings + run override audit

Revision ID: c5981cbcbe13
Revises: 376bb8637603
Create Date: 2026-10-06 00:00:00.000000

Phase 1 (attendance gate) of the 2026-10-06 attendance/state-tax/deploy fix
plan.

1. payroll_policies: attendance_required (default true),
   attendance_required_employment_types (JSON, null = every employee),
   attendance_weekly_off_days (JSON, null = Sat+Sun).
2. payroll_runs: attendance_override_reason / _by / _at — the audit trail
   for a run deliberately created with incomplete attendance.

Additive only. Every column is skipped when it already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5981cbcbe13'
down_revision: Union[str, Sequence[str], None] = '376bb8637603'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table):
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {c['name'] for c in inspector.get_columns(table)}


POLICY_COLUMNS = (
    ('attendance_required', lambda: sa.Column('attendance_required', sa.Boolean(), nullable=False, server_default='true')),
    ('attendance_required_employment_types', lambda: sa.Column('attendance_required_employment_types', sa.JSON(), nullable=True)),
    ('attendance_weekly_off_days', lambda: sa.Column('attendance_weekly_off_days', sa.JSON(), nullable=True)),
)

RUN_COLUMNS = (
    ('attendance_override_reason', lambda: sa.Column('attendance_override_reason', sa.Text(), nullable=True)),
    ('attendance_override_by', lambda: sa.Column('attendance_override_by', sa.Integer(), nullable=True)),
    ('attendance_override_at', lambda: sa.Column('attendance_override_at', sa.DateTime(timezone=True), nullable=True)),
)


def _add_missing(table, columns):
    existing = _columns(table)
    if existing is None:
        return
    for name, make in columns:
        if name not in existing:
            op.add_column(table, make())


def _drop_present(table, columns):
    existing = _columns(table)
    if existing is None:
        return
    for name, _make in reversed(columns):
        if name in existing:
            op.drop_column(table, name)


OVERRIDE_BY_FK = 'fk_payroll_runs_attendance_override_by'


def _is_sqlite():
    return op.get_bind().dialect.name == 'sqlite'


def _has_override_fk():
    inspector = sa.inspect(op.get_bind())
    return any(fk.get('name') == OVERRIDE_BY_FK for fk in inspector.get_foreign_keys('payroll_runs'))


def upgrade() -> None:
    _add_missing('payroll_policies', POLICY_COLUMNS)
    _add_missing('payroll_runs', RUN_COLUMNS)
    # Named FK added separately (same shape as 0800e995078f). SQLite cannot
    # ALTER constraints; it is only used by the migration test.
    if _columns('payroll_runs') is not None and not _is_sqlite() and not _has_override_fk():
        op.create_foreign_key(OVERRIDE_BY_FK, 'payroll_runs', 'users', ['attendance_override_by'], ['id'])


def downgrade() -> None:
    if _columns('payroll_runs') is not None and not _is_sqlite() and _has_override_fk():
        op.drop_constraint(OVERRIDE_BY_FK, 'payroll_runs', type_='foreignkey')
    _drop_present('payroll_runs', RUN_COLUMNS)
    _drop_present('payroll_policies', POLICY_COLUMNS)

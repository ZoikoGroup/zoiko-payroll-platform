"""jp_attendance_calendar: Japan work calendar and approved attendance periods

Revision ID: a1a748b50902
Revises: a7c4e9d1b2f8
Create Date: 2026-11-02

ZP-JP-ENG-001 Phase 6 correction.

  payroll_jp_work_conditions.scheduled_weekdays         the scheduled working
      weekdays ("0,1,2,3,4", 0 = Monday) - work on any other day is outside
      the schedule;
  payroll_jp_work_conditions.statutory_day_off_weekday  the statutory weekly
      day off from the work rules - the only day the day-off premium applies
      to (a national holiday is not a statutory day off);
  payroll_jp_work_conditions.public_holidays_off        whether national
      holidays are days off under the work rules; NULL means not recorded,
      and work on a holiday then BLOCKS;
  payroll_jp_attendance_approvals                       a four-eyes approval
      of one employee's attendance for one period, bound to a fingerprint of
      the attendance rows - a changed row voids it.

Additive only, idempotent both ways, lock_timeout fail-fast on PostgreSQL.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1a748b50902"
down_revision: Union[str, Sequence[str], None] = "a7c4e9d1b2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONDITIONS = "payroll_jp_work_conditions"
APPROVALS = "payroll_jp_attendance_approvals"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    predicate = rls._TENANT_PREDICATE
    rls._sql(bind, f'ALTER TABLE "{APPROVALS}" ENABLE ROW LEVEL SECURITY')
    rls._sql(bind, f'ALTER TABLE "{APPROVALS}" FORCE ROW LEVEL SECURITY')
    rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{APPROVALS}"')
    rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{APPROVALS}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    existing = _columns(CONDITIONS)
    if "scheduled_weekdays" not in existing:
        op.add_column("payroll_jp_work_conditions",
                      sa.Column("scheduled_weekdays", sa.String(length=13), nullable=True))
    if "statutory_day_off_weekday" not in existing:
        op.add_column("payroll_jp_work_conditions",
                      sa.Column("statutory_day_off_weekday", sa.SmallInteger(), nullable=True))
    if "public_holidays_off" not in existing:
        op.add_column("payroll_jp_work_conditions",
                      sa.Column("public_holidays_off", sa.Boolean(), nullable=True))

    if not _has_table(APPROVALS):
        op.create_table(
            "payroll_jp_attendance_approvals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="REQUESTED"),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("created_by_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'VOID')",
                               name="ck_jp_attendance_approval_status"),
            sa.CheckConstraint("period_end >= period_start",
                               name="ck_jp_attendance_approval_dates"),
        )
        op.create_index("ix_jp_attendance_approval_employee_period", APPROVALS,
                        ["organization_id", "employee_id", "period_start"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(APPROVALS):
        op.drop_table(APPROVALS)
    existing = _columns(CONDITIONS)
    for column in ("public_holidays_off", "statutory_day_off_weekday", "scheduled_weekdays"):
        if column in existing:
            op.drop_column(CONDITIONS, column)

"""mx_terminations_m9: Mexico terminations (Phase 9c)

Revision ID: b4d8f2c6a9e3
Revises: c3e5a7b9d1f4
Create Date: 2026-10-21

ZP-MX-ENG-001 Phase 9c (docs/mexico/MEXICO_PHASE_9_PLAN.md §3): ONE new table —
payroll_mx_terminations. No column is added to any shared table. (The
finiquito computation lives in the payslip snapshot like every Mexican line;
the vacation paid out is written to payroll_mx_vacation_records, 9b.)

Merging to main runs this in production. Creating the FKs to payroll_runs /
payroll_employees / users takes a brief SHARE ROW EXCLUSIVE lock on each
(reads continue; writes wait) that alembic/env.py holds until the upgrade
transaction commits — so the revision runs under SET LOCAL lock_timeout = '5s'.
Measured on PostgreSQL 17 in tests/test_mexico_termination_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the new worker table the policy
d7f9b1c3e5a6 derives for it — on THIS table only: re-running apply_rls()
would re-take ACCESS EXCLUSIVE on every tenant and worker table for the whole
migration transaction.
Guarded and idempotent; downgrade drops only this table.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d8f2c6a9e3"
down_revision: Union[str, Sequence[str], None] = "c3e5a7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TERM = "payroll_mx_terminations"
NEW_TABLES = (TERM,)


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def _fk(target, ondelete):
    return sa.ForeignKey(f"{target}.id", ondelete=ondelete)


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _index(name, table, cols, **kw):
    if not _has_index(table, name):
        op.create_index(name, table, cols, **kw)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s = sa.Integer, sa.String
    if not _has_table(TERM):
        op.create_table(
            "payroll_mx_terminations",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("termination_date", sa.Date(), nullable=False),
            sa.Column("reason_code", s(40), nullable=False),
            sa.Column("reason_source", s(200), nullable=True),
            sa.Column("evidence_ref", s(300), nullable=False),
            sa.Column("note", s(300), nullable=True),
            sa.Column("status", s(10), nullable=False),
            sa.Column("recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("approved_at"),
            sa.Column("previous_date_of_leaving", sa.Date(), nullable=True),
            sa.Column("baja_movement_ids", sa.JSON(), nullable=True),
            sa.Column("finiquito_run_id", i(), _fk("payroll_runs", "SET NULL"), nullable=True),
            sa.Column("cancelled_reason", s(300), nullable=True),
            sa.Column("cancelled_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'COMMITTED', 'CANCELLED')",
                               name="ck_mx_termination_status"),
        )
    for col in ("id", "organization_id", "employee_id", "finiquito_run_id"):
        _index(f"ix_{TERM}_{col}", TERM, [col])
    _index("uq_mx_termination_live_employee", TERM, ["employee_id"], unique=True,
           sqlite_where=sa.text("status <> 'CANCELLED'"), postgresql_where=sa.text("status <> 'CANCELLED'"))
    if bind.dialect.name == "postgresql":
        _rls_for_new_table(bind)


def _rls_for_new_table(bind) -> None:
    """The policy d7f9b1c3e5a6's classify() derives for this table: it has
    employee_id and organization_id, so a WORKER table, strategy "org"
    (tests/test_mexico_termination_migrations.py proves classify() agrees).
    Not re-derived here: classify() scans information_schema for the whole
    schema, which held the FK locks for ~4 s on PostgreSQL 17."""
    rls = _rls_module()
    predicate = rls._worker_predicate("org")
    rls._sql(bind, f'ALTER TABLE "{TERM}" ENABLE ROW LEVEL SECURITY')
    rls._sql(bind, f'ALTER TABLE "{TERM}" FORCE ROW LEVEL SECURITY')
    rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{TERM}"')
    rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{TERM}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(TERM):
        op.drop_table(TERM)

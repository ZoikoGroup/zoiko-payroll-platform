"""my_events_holds: Malaysia employer events (CP22 / CP22A / CP21 / death) and tax-clearance holds

Revision ID: 5f314f975ac3
Revises: 13574b996ccf
Create Date: 2026-11-12

ZP-MY-ENG-001 Phase 7 (database). Additive only: three new payroll_my_*
tables; no existing row is touched.

  payroll_my_employer_events        CP22 (new employee), CP22A (cessation),
      CP21 (departure from Malaysia) and death notices (MY-019): the event
      date, the due date computed from SIGNED pack content when the event is
      recorded (NULL = not yet computable -> preflight refuses approval),
      whether a tax-clearance hold is required, status OPEN -> SUBMITTED
      (receipt reference + evidence, recorded by a second person) or
      CANCELLED (reason).
  payroll_my_clearance_holds        the employer's tax-clearance hold of cash
      due to a departing employee (MY-020): opened from its event, held until
      the signed maximum hold date or a release on HASiL's clearance letter
      (release requested by one person, approved by another).
  payroll_my_clearance_hold_lines   one line per held payslip: the amount is
      the payslip's net pay, which REMAINS OWED to the employee (a legal hold,
      never a deduction); RELEASED when the hold is released.

No statutory number appears in any CHECK constraint (due dates and the
maximum hold come from signed pack rows). RLS (d7f9b1c3e5a6 classify): all
three WORKER "org". PostgreSQL only; literal names; lock_timeout; idempotent
both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5f314f975ac3"
down_revision: Union[str, Sequence[str], None] = "13574b996ccf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENTS = "payroll_my_employer_events"
HOLDS = "payroll_my_clearance_holds"
HOLD_LINES = "payroll_my_clearance_hold_lines"
WORKER_TABLES = (EVENTS, HOLDS, HOLD_LINES)
_TABLES = (HOLD_LINES, HOLDS, EVENTS)          # drop order (children first)

EVENT_TYPES = ("CP22", "CP22A", "CP21", "DEATH_NOTICE")
EVENT_STATUSES = ("OPEN", "SUBMITTED", "CANCELLED")
HOLD_STATES = ("HELD", "RELEASE_REQUESTED", "RELEASED", "LAPSED")
LINE_STATUSES = ("HELD", "RELEASED")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False, where=None):
    if _has_index(table, name):
        return
    kw = {}
    if where is not None:
        kw = {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}
    op.create_index(name, table, cols, unique=unique, **kw)


def _common(table: str) -> list:
    """id / tenant / legal employer / evidence / version / approval / stamps."""
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legal_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_ref", sa.String(300), nullable=True),
        sa.Column("previous_version_id", sa.Integer(),
                  sa.ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _employee():
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False)


def _standard_indexes(table: str) -> None:
    _index(table, f"ix_{table}_id", ["id"])
    _index(table, f"ix_{table}_organization_id", ["organization_id"])
    _index(table, f"ix_{table}_legal_entity_id", ["legal_entity_id"])
    _index(table, f"ix_{table}_employee_id", ["employee_id"])


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Give each table this revision creates the policy d7f9b1c3e5a6 derives."""
    rls = _rls_module()
    for table in WORKER_TABLES:
        predicate = rls._worker_predicate("org")
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # 1) payroll_my_employer_events (WORKER)
    t = EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_my_employer_events",
            *_common(t),
            _employee(),
            sa.Column("event_type", sa.String(14), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("due_rule", sa.String(60), nullable=True),
            sa.Column("clearance_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("submitted_on", sa.Date(), nullable=True),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.Column("cancel_reason", sa.String(300), nullable=True),
            sa.CheckConstraint(f"event_type IN {_in(EVENT_TYPES)}", name="ck_my_event_type"),
            sa.CheckConstraint(f"status IN {_in(EVENT_STATUSES)}", name="ck_my_event_status"),
            sa.CheckConstraint("status <> 'SUBMITTED' OR (submitted_on IS NOT NULL AND receipt_ref IS NOT NULL "
                               "AND evidence_ref IS NOT NULL AND approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_my_event_submitted"),
            sa.CheckConstraint("status <> 'CANCELLED' OR cancel_reason IS NOT NULL", name="ck_my_event_cancelled"),
            sa.CheckConstraint("event_type IN ('CP22A', 'CP21') OR clearance_required = false",
                               name="ck_my_event_clearance_type"),
        )
    _standard_indexes(t)
    _index(t, "ix_my_event_lookup", ["organization_id", "employee_id", "event_type", "status"])

    # 2) payroll_my_clearance_holds (WORKER)
    t = HOLDS
    if not _has_table(t):
        op.create_table(
            "payroll_my_clearance_holds",
            *_common(t),
            _employee(),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey(f"{EVENTS}.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("opened_on", sa.Date(), nullable=False),
            sa.Column("hold_until", sa.Date(), nullable=False),
            sa.Column("state", sa.String(18), nullable=False, server_default="HELD"),
            sa.Column("release_reference", sa.String(100), nullable=True),
            sa.Column("release_evidence_ref", sa.String(300), nullable=True),
            sa.Column("release_requested_by_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("released_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"state IN {_in(HOLD_STATES)}", name="ck_my_hold_state"),
            sa.CheckConstraint("hold_until >= opened_on", name="ck_my_hold_dates"),
            sa.CheckConstraint("state NOT IN ('RELEASE_REQUESTED', 'RELEASED') OR (release_reference IS NOT NULL "
                               "AND release_evidence_ref IS NOT NULL AND release_requested_by_id IS NOT NULL)",
                               name="ck_my_hold_release_request"),
            sa.CheckConstraint("state <> 'RELEASED' OR (released_by_id IS NOT NULL AND released_at IS NOT NULL AND "
                               "released_by_id <> release_requested_by_id)", name="ck_my_hold_release_four_eyes"),
        )
    _standard_indexes(t)
    _index(t, "uq_my_hold_one_open_per_employee", ["organization_id", "employee_id"], unique=True,
           where="state IN ('HELD', 'RELEASE_REQUESTED')")

    # 3) payroll_my_clearance_hold_lines (WORKER)
    t = HOLD_LINES
    if not _has_table(t):
        op.create_table(
            "payroll_my_clearance_hold_lines",
            *_common(t),
            _employee(),
            sa.Column("hold_id", sa.Integer(), sa.ForeignKey(f"{HOLDS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="HELD"),
            sa.CheckConstraint(f"status IN {_in(LINE_STATUSES)}", name="ck_my_hold_line_status"),
            sa.CheckConstraint("amount >= 0", name="ck_my_hold_line_amount"),
        )
    _standard_indexes(t)
    _index(t, "ix_my_hold_line_hold", ["hold_id"])
    _index(t, "uq_my_hold_line_payslip", ["payslip_item_id"], unique=True)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

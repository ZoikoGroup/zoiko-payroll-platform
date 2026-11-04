"""nz_leave_pay: New Zealand leave-pay calculations, cash-ups, final-pay cases, corrections

Revision ID: c6ea8c6c35ce
Revises: ac08988ecd3a
Create Date: 2026-11-04

ZP-NZ-ENG-001 Phase 6 (Holidays Act II and non-standard payments; NZ-006,
NZ-017, NZ-021). Additive only.

  payroll_nz_final_pay_cases          one open case per employment: termination,
      every outstanding entitlement resolved (never zeroed, NZ-021).
  payroll_nz_leave_pay_calculations   append-only: both candidates (OWP/AWE or
      RDP/ADP), the winner and the statutory reason, units, rate, amount, the
      ordinary pay it displaces and its inputs (NZ-017).
  payroll_nz_cash_up_requests         annual-holiday cash-up on a written request.
  payroll_nz_corrections              compensating corrections; the original
      payslip is never modified (NZ-006).
  payslip_items.nz_correction_of_id   a correction payslip -> the payslip it corrects.
  payroll_nz_leave_events.leave_pay_calculation_id
  payroll_runs.nz_run_options         per-run options (holiday-advance method and
      periods, lump-sum component, final-pay case).

The three added columns are plain nullable integers / JSON (no foreign key, the
P2 shared-column pattern): the service checks the reference. No statutory
number appears in any CHECK. Every table has employee_id: WORKER "org" RLS
(d7f9b1c3e5a6). PostgreSQL only for RLS; literal names; lock_timeout;
idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6ea8c6c35ce"
down_revision: Union[str, Sequence[str], None] = "ac08988ecd3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CASES = "payroll_nz_final_pay_cases"
CALCS = "payroll_nz_leave_pay_calculations"
CASHUPS = "payroll_nz_cash_up_requests"
CORRECTIONS = "payroll_nz_corrections"
PAYSLIPS = "payslip_items"
EVENTS = "payroll_nz_leave_events"
RUNS = "payroll_runs"

WORKER_TABLES = (CASES, CALCS, CASHUPS, CORRECTIONS)
_TABLES = (CORRECTIONS, CASHUPS, CALCS, CASES)
PURPOSES = ("('ANNUAL_LEAVE', 'SICK', 'BEREAVEMENT', 'FAMILY_VIOLENCE', 'PUBLIC_HOLIDAY_NOT_WORKED', "
            "'PUBLIC_HOLIDAY_WORKED', 'ALTERNATIVE_HOLIDAY', 'CASH_UP', 'PAYG', 'FINAL_VESTED', 'FINAL_UNVESTED')")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)} if _has_table(table) else set()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False, where=None):
    if _has_index(table, name):
        return
    kw = {}
    if where is not None:
        kw = {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}
    op.create_index(name, table, cols, unique=unique, **kw)


def _common(table: str, with_updated: bool = True):
    columns = [
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
    ]
    if with_updated:
        columns.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _employee():
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False)


def _employment():
    return sa.Column("employment_id", sa.Integer(),
                     sa.ForeignKey("payroll_nz_employments.id", ondelete="CASCADE"), nullable=False)


def _standard_indexes(table):
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
    """Give each table this revision creates the WORKER "org" policy
    d7f9b1c3e5a6 derives for it, on THESE tables only."""
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

    # 1) Shared columns (nullable; references checked by the service).
    if "nz_correction_of_id" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("nz_correction_of_id", sa.Integer(), nullable=True))
    if "nz_run_options" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("nz_run_options", _json(), nullable=True))
    if "leave_pay_calculation_id" not in _columns(EVENTS):
        op.add_column("payroll_nz_leave_events", sa.Column("leave_pay_calculation_id", sa.Integer(), nullable=True))

    # 2) payroll_nz_final_pay_cases (first: calculations reference it)
    t = CASES
    if not _has_table(t):
        op.create_table(
            "payroll_nz_final_pay_cases",
            *_common(t),
            _employee(),
            _employment(),
            sa.Column("termination_date", sa.Date(), nullable=False),
            sa.Column("termination_reason", sa.String(30), nullable=False),
            sa.Column("last_anniversary", sa.Date(), nullable=True),
            sa.Column("outstanding", _json(), nullable=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
            sa.CheckConstraint("status IN ('OPEN', 'CALCULATED', 'APPROVED', 'PAID', 'CANCELLED')",
                               name="ck_nz_final_pay_status"),
        )
    _standard_indexes(t)
    _index(t, "uq_nz_final_pay_one_per_employment", ["employment_id"], unique=True, where="status <> 'CANCELLED'")

    # 3) payroll_nz_leave_pay_calculations (append-only, NZ-017)
    t = CALCS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_leave_pay_calculations",
            *_common(t, with_updated=False),
            _employee(),
            _employment(),
            sa.Column("leave_event_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_leave_events.id", ondelete="SET NULL"), nullable=True),
            sa.Column("public_holiday_decision_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_public_holiday_decisions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("final_pay_case_id", sa.Integer(),
                      sa.ForeignKey(f"{CASES}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entitlement_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_leave_entitlements.id", ondelete="SET NULL"), nullable=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pay_on", sa.Date(), nullable=False),
            sa.Column("purpose", sa.String(28), nullable=False),
            sa.Column("method_pair", sa.String(10), nullable=False),
            sa.Column("candidate_a_name", sa.String(4), nullable=True),
            sa.Column("candidate_a_amount", sa.Numeric(14, 4), nullable=True),
            sa.Column("candidate_b_name", sa.String(4), nullable=True),
            sa.Column("candidate_b_amount", sa.Numeric(14, 4), nullable=True),
            sa.Column("chosen", sa.String(4), nullable=False),
            sa.Column("statutory_reason", sa.String(200), nullable=False),
            sa.Column("units", sa.Numeric(14, 4), nullable=False),
            sa.Column("unit", sa.String(6), nullable=False),
            sa.Column("rate_amount", sa.Numeric(14, 4), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("displaced_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("inputs", _json(), nullable=False),
            sa.Column("pack_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="CALCULATED"),
            sa.CheckConstraint(f"purpose IN {PURPOSES}", name="ck_nz_leave_pay_purpose"),
            sa.CheckConstraint("method_pair IN ('OWP_AWE', 'RDP_ADP', 'PAYG_PCT', 'PCT_GROSS')",
                               name="ck_nz_leave_pay_method"),
            sa.CheckConstraint("chosen IN ('OWP', 'AWE', 'RDP', 'ADP', 'PCT')", name="ck_nz_leave_pay_chosen_enum"),
            sa.CheckConstraint("chosen = 'PCT' OR chosen = candidate_a_name OR chosen = candidate_b_name",
                               name="ck_nz_leave_pay_chosen_candidate"),
            sa.CheckConstraint("unit IN ('WEEKS', 'DAYS', 'HOURS', 'AMOUNT')", name="ck_nz_leave_pay_unit"),
            sa.CheckConstraint("amount >= 0 AND displaced_amount >= 0", name="ck_nz_leave_pay_amount"),
            sa.CheckConstraint("purpose <> 'FAMILY_VIOLENCE' OR restricted = true", name="ck_nz_leave_pay_restricted"),
            sa.CheckConstraint("status IN ('CALCULATED', 'PAID', 'VOID')", name="ck_nz_leave_pay_status"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_leave_pay_employee_pay_on", ["employee_id", "pay_on"])
    _index(t, "uq_nz_leave_pay_event_live", ["leave_event_id"], unique=True,
           where="leave_event_id IS NOT NULL AND status <> 'VOID'")
    _index(t, "uq_nz_leave_pay_decision_live", ["public_holiday_decision_id"], unique=True,
           where="public_holiday_decision_id IS NOT NULL AND status <> 'VOID'")

    # 4) payroll_nz_cash_up_requests
    t = CASHUPS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_cash_up_requests",
            *_common(t),
            _employee(),
            _employment(),
            sa.Column("entitlement_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_leave_entitlements.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_on", sa.Date(), nullable=False),
            sa.Column("written_request_ref", sa.String(300), nullable=False),
            sa.Column("weeks", sa.Numeric(6, 4), nullable=False),
            sa.Column("leave_pay_calculation_id", sa.Integer(),
                      sa.ForeignKey(f"{CALCS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="REQUESTED"),
            sa.CheckConstraint("weeks > 0", name="ck_nz_cash_up_weeks"),
            sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'PAID', 'REJECTED')", name="ck_nz_cash_up_status"),
        )
    _standard_indexes(t)
    _index(t, "uq_nz_cash_up_one_open", ["entitlement_id"], unique=True,
           where="status IN ('REQUESTED', 'APPROVED')")

    # 5) payroll_nz_corrections (NZ-006)
    t = CORRECTIONS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_corrections",
            *_common(t),
            _employee(),
            sa.Column("original_payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("correction_run_id", sa.Integer(),
                      sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("correction_payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reason", sa.String(300), nullable=False),
            sa.Column("input_delta", _json(), nullable=False),
            sa.Column("result_delta", _json(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'APPLIED', 'VOID')", name="ck_nz_correction_status"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_correction_original", ["original_payslip_item_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "leave_pay_calculation_id" in _columns(EVENTS):
        op.drop_column(EVENTS, "leave_pay_calculation_id")
    if "nz_run_options" in _columns(RUNS):
        op.drop_column(RUNS, "nz_run_options")
    if "nz_correction_of_id" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "nz_correction_of_id")

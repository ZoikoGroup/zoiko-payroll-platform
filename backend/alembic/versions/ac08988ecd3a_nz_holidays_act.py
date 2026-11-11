"""nz_holidays_act: New Zealand employments, leave entitlements, gross-earnings ledger, public-holiday decisions, leave events

Revision ID: ac08988ecd3a
Revises: 0e697c2388bf
Create Date: 2026-11-04

ZP-NZ-ENG-001 Phase 5 (Holidays Act 2003, entitlement side; spec §8, gate G2).
Additive only: five new payroll_nz_* tables; no existing row or column changes.

  payroll_nz_employments                 one row per employment instance (a rehire
      is a NEW instance unless continuity is evidenced, spec §10); anniversary
      anchor; pay-as-you-go eligibility with its basis and written agreement.
  payroll_nz_public_holiday_decisions    per employee and holiday: region,
      otherwise-working-day decision with its basis and evidence, hours worked
      (midnight crossing), alternative holiday due.
  payroll_nz_leave_entitlements          the LEGAL entitlement record (NZ-016):
      weeks or days vested on a qualifying date / anniversary, carried in,
      taken, paid out - never a generic hours accrual.
  payroll_nz_gross_earnings_ledger       statutory gross earnings per paid payslip
      and pay component with its inclusion reason (append-only).
  payroll_nz_leave_events                leave taken against an entitlement. There
      is deliberately NO reason / narrative column; family-violence leave is
      always restricted (NZ-023).

No statutory number appears in any CHECK constraint (spec page 1). Every table
has employee_id, so each gets the WORKER "org" row-level-security policy
d7f9b1c3e5a6's classify() derives. PostgreSQL only; literal table and column
names for scripts/drift_pending_filter; lock_timeout fail-fast; idempotent both
ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ac08988ecd3a"
down_revision: Union[str, Sequence[str], None] = "0e697c2388bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPLOYMENTS = "payroll_nz_employments"
DECISIONS = "payroll_nz_public_holiday_decisions"
ENTITLEMENTS = "payroll_nz_leave_entitlements"
LEDGER = "payroll_nz_gross_earnings_ledger"
EVENTS = "payroll_nz_leave_events"

WORKER_TABLES = (EMPLOYMENTS, DECISIONS, ENTITLEMENTS, LEDGER, EVENTS)
_TABLES = (EVENTS, LEDGER, ENTITLEMENTS, DECISIONS, EMPLOYMENTS)
LEAVE_TYPES = "('ANNUAL', 'SICK', 'BEREAVEMENT_CLOSE', 'BEREAVEMENT_OTHER', 'FAMILY_VIOLENCE', 'ALTERNATIVE')"


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


def _common(table: str, with_updated: bool = True):
    """id / tenant / legal employer / evidence / version / approval / stamps."""
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


def _employment(nullable=False):
    return sa.Column("employment_id", sa.Integer(),
                     sa.ForeignKey(f"{EMPLOYMENTS}.id", ondelete="CASCADE"), nullable=nullable)


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
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give each table this revision creates the policy d7f9b1c3e5a6
    derives for it, on THESE tables only."""
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

    # 1) payroll_nz_employments
    t = EMPLOYMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_employments",
            *_common(t),
            _employee(),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("continuity_rule", sa.String(16), nullable=False, server_default="NEW_INSTANCE"),
            sa.Column("prior_employment_id", sa.Integer(),
                      sa.ForeignKey(f"{EMPLOYMENTS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("termination_reason", sa.String(30), nullable=True),
            sa.Column("payg_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payg_basis", sa.String(28), nullable=True),
            sa.Column("payg_agreement_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_nz_employment_dates"),
            sa.CheckConstraint("continuity_rule IN ('NEW_INSTANCE', 'CONTINUOUS')",
                               name="ck_nz_employment_continuity"),
            sa.CheckConstraint("continuity_rule <> 'CONTINUOUS' OR (evidence_ref IS NOT NULL AND "
                               "prior_employment_id IS NOT NULL)", name="ck_nz_employment_continuity_evidence"),
            sa.CheckConstraint("payg_basis IS NULL OR payg_basis IN ('FIXED_TERM_UNDER_12_MONTHS', "
                               "'IRREGULAR_INTERMITTENT')", name="ck_nz_employment_payg_basis"),
            sa.CheckConstraint("payg_eligible = false OR (payg_basis IS NOT NULL AND payg_agreement_ref IS NOT NULL)",
                               name="ck_nz_employment_payg_evidence"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ENDED')", name="ck_nz_employment_status"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_employment_employee_start", ["employee_id", "start_date"])
    _index(t, "uq_nz_employment_one_active", ["organization_id", "employee_id"], unique=True,
           where="status = 'ACTIVE'")

    # 2) payroll_nz_public_holiday_decisions
    t = DECISIONS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_public_holiday_decisions",
            *_common(t),
            _employee(),
            _employment(),
            sa.Column("holiday_date", sa.Date(), nullable=False),
            sa.Column("holiday_name", sa.String(80), nullable=False),
            sa.Column("region", sa.String(3), nullable=True),
            sa.Column("otherwise_working_day", sa.String(12), nullable=False),
            sa.Column("owd_basis", sa.String(24), nullable=False),
            sa.Column("owd_evidence_ref", sa.String(300), nullable=True),
            sa.Column("worked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("shift_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("shift_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("timezone", sa.String(40), nullable=False, server_default="Pacific/Auckland"),
            sa.Column("hours_on_holiday", sa.Numeric(6, 2), nullable=True),
            sa.Column("alternative_holiday_due", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("otherwise_working_day IN ('YES', 'NO', 'UNDETERMINED')", name="ck_nz_phd_owd"),
            sa.CheckConstraint("owd_basis IN ('FIXED_PATTERN', 'ROSTER', 'HISTORY', 'AGREEMENT', "
                               "'OPERATOR_DECISION')", name="ck_nz_phd_owd_basis"),
            sa.CheckConstraint("owd_basis NOT IN ('AGREEMENT', 'OPERATOR_DECISION') OR owd_evidence_ref IS NOT NULL",
                               name="ck_nz_phd_owd_evidence"),
            sa.CheckConstraint("worked = false OR (shift_start IS NOT NULL AND shift_end IS NOT NULL)",
                               name="ck_nz_phd_shift"),
            sa.CheckConstraint("shift_end IS NULL OR shift_start IS NULL OR shift_end > shift_start",
                               name="ck_nz_phd_shift_order"),
            sa.CheckConstraint("timezone IN ('Pacific/Auckland', 'Pacific/Chatham')", name="ck_nz_phd_timezone"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')", name="ck_nz_phd_status"),
        )
    _standard_indexes(t)
    _index(t, "uq_nz_phd_one_approved", ["employee_id", "holiday_date"], unique=True, where="status = 'APPROVED'")

    # 3) payroll_nz_leave_entitlements (legal entitlement source of truth, NZ-016)
    t = ENTITLEMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_leave_entitlements",
            *_common(t),
            _employee(),
            _employment(),
            sa.Column("leave_type", sa.String(20), nullable=False),
            sa.Column("qualifying_date", sa.Date(), nullable=False),
            sa.Column("entitlement_date", sa.Date(), nullable=False),
            sa.Column("unit", sa.String(6), nullable=False),
            sa.Column("quantity", sa.Numeric(8, 4), nullable=False),
            sa.Column("carried_in", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("taken", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("paid_out", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("source", sa.String(24), nullable=False),
            sa.Column("source_decision_id", sa.Integer(),
                      sa.ForeignKey(f"{DECISIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pack_hash", sa.String(64), nullable=False),
            sa.Column("expires_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint(f"leave_type IN {LEAVE_TYPES}", name="ck_nz_entitlement_type"),
            sa.CheckConstraint("unit IN ('WEEKS', 'DAYS')", name="ck_nz_entitlement_unit"),
            sa.CheckConstraint("quantity >= 0 AND carried_in >= 0 AND taken >= 0 AND paid_out >= 0",
                               name="ck_nz_entitlement_non_negative"),
            sa.CheckConstraint("taken + paid_out <= quantity + carried_in", name="ck_nz_entitlement_balance"),
            sa.CheckConstraint("source IN ('HOLIDAYS_ACT_2003', 'EMPLOYMENT_AGREEMENT', 'PUBLIC_HOLIDAY_WORKED')",
                               name="ck_nz_entitlement_source"),
            sa.CheckConstraint("leave_type <> 'ALTERNATIVE' OR source_decision_id IS NOT NULL",
                               name="ck_nz_entitlement_alternative_source"),
            sa.CheckConstraint("status IN ('ACTIVE', 'EXHAUSTED', 'PAID_OUT', 'SUPERSEDED')",
                               name="ck_nz_entitlement_status"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_entitlement_lookup", ["employee_id", "leave_type", "entitlement_date"])
    _index(t, "uq_nz_entitlement_vest", ["employment_id", "leave_type", "entitlement_date"], unique=True,
           where="leave_type <> 'ALTERNATIVE'")
    _index(t, "uq_nz_entitlement_alternative", ["source_decision_id"], unique=True,
           where="leave_type = 'ALTERNATIVE'")

    # 4) payroll_nz_gross_earnings_ledger (append-only; no updated_at)
    t = LEDGER
    if not _has_table(t):
        op.create_table(
            "payroll_nz_gross_earnings_ledger",
            *_common(t, with_updated=False),
            _employee(),
            _employment(nullable=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("component", sa.String(24), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("included", sa.Boolean(), nullable=False),
            sa.Column("treatment", sa.String(14), nullable=False),
            sa.Column("reason", sa.String(120), nullable=False),
            sa.Column("days_worked", sa.Numeric(6, 2), nullable=True),
            sa.Column("pack_hash", sa.String(64), nullable=True),
            sa.CheckConstraint("treatment IN ('INCLUDED', 'EXCLUDED', 'LUMP_SUM_PATH', 'REVIEW')",
                               name="ck_nz_gross_ledger_treatment"),
            sa.CheckConstraint("period_end >= period_start", name="ck_nz_gross_ledger_period"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_gross_ledger_lookup", ["employee_id", "employment_id", "pay_date"])
    _index(t, "uq_nz_gross_ledger_payslip_component", ["payslip_item_id", "component"], unique=True)

    # 5) payroll_nz_leave_events (no reason / narrative column, NZ-023)
    t = EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_leave_events",
            *_common(t),
            _employee(),
            _employment(),
            sa.Column("entitlement_id", sa.Integer(),
                      sa.ForeignKey(f"{ENTITLEMENTS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("leave_type", sa.String(20), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Numeric(8, 4), nullable=False),
            sa.Column("unit", sa.String(6), nullable=False),
            sa.Column("source_request_id", sa.Integer(),
                      sa.ForeignKey("payroll_leave_requests.id", ondelete="SET NULL"), nullable=True),
            sa.Column("restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(12), nullable=False, server_default="REQUESTED"),
            sa.CheckConstraint(f"leave_type IN {LEAVE_TYPES}", name="ck_nz_leave_event_type"),
            sa.CheckConstraint("unit IN ('WEEKS', 'DAYS')", name="ck_nz_leave_event_unit"),
            sa.CheckConstraint("quantity > 0", name="ck_nz_leave_event_quantity"),
            sa.CheckConstraint("end_date >= start_date", name="ck_nz_leave_event_dates"),
            sa.CheckConstraint("leave_type <> 'FAMILY_VIOLENCE' OR restricted = true",
                               name="ck_nz_leave_event_restricted"),
            sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'PAID', 'CANCELLED')",
                               name="ck_nz_leave_event_status"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_leave_event_employee_dates", ["employee_id", "start_date"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

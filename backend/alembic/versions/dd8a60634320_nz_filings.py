"""nz_filings: New Zealand payday filings, remittances, settlements, run exceptions, journal accounts

Revision ID: dd8a60634320
Revises: c6ea8c6c35ce
Create Date: 2026-11-04

ZP-NZ-ENG-001 Phase 8 (spec §9; NZ-018 idempotent filing, NZ-019 filing
acceptance is not payment; gate G3). Decisions D-P8-1..4 (2026-11-04).
Additive only.

  payroll_nz_filings             one record per legal employer, payday, schedule
      (Employment Information / Employee Details), version and kind (original /
      amendment): payload generated from PAID payslips only (IRD numbers as
      vault id + masked form, D-P8-4), its hash, channel, due date (NULL while
      the working-day rule is unsigned) and the authority response.
  payroll_nz_remittances         one row per remittance period, obligation and
      destination: amount, settled, due date, late flag (D-P8-3); PAID only
      through matched settlements (NZ-019).
  payroll_nz_remittance_lines    append-only: each payslip's share.
  payroll_nz_settlements         money recorded and matched by a second person.
  payroll_nz_run_exceptions      a second person's approval of a documented
      exception, bound to the run fingerprint; a minimum-wage FAIL can never be
      one (D-P8-1, CHECK).
  payroll_nz_employer_profiles.nz_journal_accounts   the employer's account map.

RLS (d7f9b1c3e5a6 classify): filings, remittances and settlements TENANT;
remittance lines (payslip_item_id) and run exceptions (employee_id) WORKER
"org". PostgreSQL only; literal names; lock_timeout; idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dd8a60634320"
down_revision: Union[str, Sequence[str], None] = "c6ea8c6c35ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILINGS = "payroll_nz_filings"
REMITTANCES = "payroll_nz_remittances"
LINES = "payroll_nz_remittance_lines"
SETTLEMENTS = "payroll_nz_settlements"
EXCEPTIONS = "payroll_nz_run_exceptions"
EMPLOYERS = "payroll_nz_employer_profiles"

TENANT_TABLES = (FILINGS, REMITTANCES, SETTLEMENTS)
WORKER_TABLES = (LINES, EXCEPTIONS)
_TABLES = (EXCEPTIONS, SETTLEMENTS, LINES, REMITTANCES, FILINGS)
OBLIGATIONS = "('PAYE', 'STUDENT_LOAN', 'KS_EMPLOYEE', 'KS_EMPLOYER_NET', 'ESCT', 'CHILD_SUPPORT')"


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


def _base_indexes(table, employee=False):
    _index(table, f"ix_{table}_id", ["id"])
    _index(table, f"ix_{table}_organization_id", ["organization_id"])
    _index(table, f"ix_{table}_legal_entity_id", ["legal_entity_id"])
    if employee:
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
    policies = [(table, rls._TENANT_PREDICATE) for table in TENANT_TABLES]
    policies += [(table, rls._worker_predicate("org")) for table in WORKER_TABLES]
    for table, predicate in policies:
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if "nz_journal_accounts" not in _columns(EMPLOYERS):
        op.add_column("payroll_nz_employer_profiles", sa.Column("nz_journal_accounts", _json(), nullable=True))

    # 1) payroll_nz_filings (TENANT)
    t = FILINGS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_filings",
            *_common(t),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("filing_type", sa.String(24), nullable=False),
            sa.Column("kind", sa.String(10), nullable=False, server_default="ORIGINAL"),
            sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("run_ids", _json(), nullable=False),
            sa.Column("payload", _json(), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("amends_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("correction_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_corrections.id", ondelete="SET NULL"), nullable=True),
            sa.Column("authority_reference", sa.String(100), nullable=True),
            sa.Column("authority_errors", _json(), nullable=True),
            sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("filing_type IN ('EMPLOYMENT_INFORMATION', 'EMPLOYEE_DETAILS')",
                               name="ck_nz_filing_type"),
            sa.CheckConstraint("kind IN ('ORIGINAL', 'AMENDMENT')", name="ck_nz_filing_kind"),
            sa.CheckConstraint("kind <> 'AMENDMENT' OR amends_id IS NOT NULL", name="ck_nz_filing_amends"),
            sa.CheckConstraint("version >= 1", name="ck_nz_filing_version"),
            sa.CheckConstraint("channel IN ('PAYDAY_GATEWAY', 'MYIR_FILE_UPLOAD', 'MYIR_ONSCREEN', 'PAPER')",
                               name="ck_nz_filing_channel"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUBMITTED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED')",
                               name="ck_nz_filing_status"),
        )
    _base_indexes(t)
    _index(t, "ix_nz_filing_due", ["organization_id", "due_on"])
    _index(t, "uq_nz_filing_version_entity", ["organization_id", "legal_entity_id", "pay_date", "filing_type", "kind",
                                              "version"], unique=True, where="legal_entity_id IS NOT NULL")
    _index(t, "uq_nz_filing_version_org", ["organization_id", "pay_date", "filing_type", "kind", "version"],
           unique=True, where="legal_entity_id IS NULL")

    # 2) payroll_nz_remittances (TENANT)
    t = REMITTANCES
    if not _has_table(t):
        op.create_table(
            "payroll_nz_remittances",
            *_common(t),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("remittance_class", sa.String(15), nullable=False),
            sa.Column("obligation", sa.String(20), nullable=False),
            sa.Column("destination", sa.String(16), nullable=False),
            sa.Column("fund_ref", sa.String(100), nullable=False, server_default=""),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("settled", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("late", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.CheckConstraint("period_end >= period_start", name="ck_nz_remittance_period"),
            sa.CheckConstraint("remittance_class IN ('MONTHLY', 'TWICE_MONTHLY')", name="ck_nz_remittance_class"),
            sa.CheckConstraint(f"obligation IN {OBLIGATIONS}", name="ck_nz_remittance_obligation"),
            sa.CheckConstraint("destination IN ('INLAND_REVENUE', 'COMPLYING_FUND')",
                               name="ck_nz_remittance_destination"),
            sa.CheckConstraint("status IN ('OPEN', 'PART_PAID', 'PAID')", name="ck_nz_remittance_status"),
        )
    _base_indexes(t)
    _index(t, "ix_nz_remittance_due", ["organization_id", "due_on"])
    _index(t, "uq_nz_remittance_entity", ["organization_id", "legal_entity_id", "period_start", "obligation",
                                          "destination", "fund_ref"], unique=True, where="legal_entity_id IS NOT NULL")
    _index(t, "uq_nz_remittance_org", ["organization_id", "period_start", "obligation", "destination", "fund_ref"],
           unique=True, where="legal_entity_id IS NULL")

    # 3) payroll_nz_remittance_lines (WORKER; append-only)
    t = LINES
    if not _has_table(t):
        op.create_table(
            "payroll_nz_remittance_lines",
            *_common(t, with_updated=False),
            sa.Column("remittance_id", sa.Integer(), sa.ForeignKey(f"{REMITTANCES}.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("source", sa.String(10), nullable=False),
            sa.Column("correction_id", sa.Integer(),
                      sa.ForeignKey("payroll_nz_corrections.id", ondelete="SET NULL"), nullable=True),
            sa.CheckConstraint("source IN ('RUN', 'CORRECTION')", name="ck_nz_remittance_line_source"),
            sa.CheckConstraint("source <> 'CORRECTION' OR correction_id IS NOT NULL",
                               name="ck_nz_remittance_line_correction"),
        )
    _base_indexes(t)
    _index(t, "ix_nz_remittance_line_remittance", ["remittance_id"])
    _index(t, "uq_nz_remittance_line_payslip", ["payslip_item_id", "remittance_id"], unique=True)

    # 4) payroll_nz_settlements (TENANT)
    t = SETTLEMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_settlements",
            *_common(t),
            sa.Column("remittance_id", sa.Integer(), sa.ForeignKey(f"{REMITTANCES}.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("paid_on", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("payment_reference", sa.String(100), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="RECORDED"),
            sa.Column("matched_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("amount > 0", name="ck_nz_settlement_amount"),
            sa.CheckConstraint("status IN ('RECORDED', 'MATCHED', 'REVERSED')", name="ck_nz_settlement_status"),
        )
    _base_indexes(t)
    _index(t, "ix_nz_settlement_remittance", ["remittance_id"])

    # 5) payroll_nz_run_exceptions (WORKER)
    t = EXCEPTIONS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_run_exceptions",
            *_common(t),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("detail", _json(), nullable=True),
            sa.Column("run_fingerprint", sa.String(64), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="REQUESTED"),
            sa.CheckConstraint("code <> 'NZ_MIN_WAGE_FAIL'", name="ck_nz_run_exception_never_min_wage_fail"),
            sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'REJECTED')", name="ck_nz_run_exception_status"),
        )
    _base_indexes(t, employee=True)
    _index(t, "uq_nz_run_exception", ["run_id", "payslip_item_id", "code", "run_fingerprint"], unique=True,
           where="status <> 'REJECTED'")

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "nz_journal_accounts" in _columns(EMPLOYERS):
        op.drop_column(EMPLOYERS, "nz_journal_accounts")

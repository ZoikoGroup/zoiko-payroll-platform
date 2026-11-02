"""jp_lifecycle_filings: Japan run-exception approvals, obligations and year-end adjustment

Revision ID: 41a1fafbbfdc
Revises: a1a748b50902
Create Date: 2026-11-02

ZP-JP-ENG-001 Phase 8.

  payroll_jp_run_exceptions   a second person's approval of one computed run
      exception, bound to the run's payload fingerprint at the time: a later
      change to the payslips needs a new approval;
  payroll_jp_obligations      the remittances a PAID run creates (withholding,
      social insurance, resident tax per municipality), written once, with
      approval / submission / receipt;
  payroll_jp_yea_declarations the employee's year-end declarations (spouse,
      dependants, premiums, housing loan, previous employer), versioned and
      four-eyes approved;
  payroll_jp_yea_cases        one year-end adjustment per employee and year:
      OPEN -> CALCULATED -> REVIEWED -> APPLIED -> LOCKED (or EXCLUDED).

Additive only, literal table names, idempotent both ways, lock_timeout
fail-fast and tenant row-level security on PostgreSQL.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "41a1fafbbfdc"
down_revision: Union[str, Sequence[str], None] = "a1a748b50902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXCEPTIONS = "payroll_jp_run_exceptions"
OBLIGATIONS = "payroll_jp_obligations"
DECLARATIONS = "payroll_jp_yea_declarations"
CASES = "payroll_jp_yea_cases"
TABLES = (EXCEPTIONS, OBLIGATIONS, DECLARATIONS, CASES)


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _user(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _org():
    return sa.Column("organization_id", sa.Integer(),
                     sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    predicate = rls._TENANT_PREDICATE
    for table in TABLES:
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if not _has_table(EXCEPTIONS):
        op.create_table(
            "payroll_jp_run_exceptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("exception_key", sa.String(120), nullable=False),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="SET NULL"), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("payload_fingerprint", sa.String(64), nullable=False),
            sa.Column("note", sa.String(500), nullable=True),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
            _created_at(),
        )
        op.create_index("uq_jp_run_exception_approval", EXCEPTIONS,
                        ["run_id", "exception_key", "payload_fingerprint"], unique=True)

    if not _has_table(OBLIGATIONS):
        op.create_table(
            "payroll_jp_obligations",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("obligation_type", sa.String(30), nullable=False),
            sa.Column("obligation_key", sa.String(80), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("municipality_code", sa.String(6), nullable=True),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("amount", sa.Numeric(14, 0), nullable=False),
            sa.Column("source_run_id", sa.Integer(),
                      sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="CREATED"),
            sa.Column("channel", sa.String(40), nullable=True),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.Column("detail", _json(), nullable=True),
            _user("created_by_id"),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            _created_at(),
            sa.CheckConstraint("obligation_type IN ('WHT_REMITTANCE', 'SI_REMITTANCE', "
                               "'RESIDENT_TAX_REMITTANCE')", name="ck_jp_obligation_type"),
            sa.CheckConstraint("status IN ('CREATED', 'APPROVED', 'SUBMITTED', 'ACCEPTED', "
                               "'REJECTED', 'CORRECTED')", name="ck_jp_obligation_status"),
            sa.CheckConstraint("amount >= 0", name="ck_jp_obligation_amount"),
        )
        op.create_index("uq_jp_obligation_run_key", OBLIGATIONS,
                        ["source_run_id", "obligation_key"], unique=True)
        op.create_index("ix_jp_obligation_org_due", OBLIGATIONS, ["organization_id", "due_on"])

    if not _has_table(DECLARATIONS):
        op.create_table(
            "payroll_jp_yea_declarations",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tax_year", sa.SmallInteger(), nullable=False),
            sa.Column("declaration_type", sa.String(30), nullable=False),
            sa.Column("payload", _json(), nullable=False),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("previous_version_id", sa.Integer(),
                      sa.ForeignKey("payroll_jp_yea_declarations.id", ondelete="SET NULL"), nullable=True),
            _user("created_by_id"),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            _created_at(),
            sa.CheckConstraint("declaration_type IN ('SPOUSE', 'DEPENDANTS', 'INSURANCE_PREMIUMS', "
                               "'HOUSING_LOAN', 'PREVIOUS_EMPLOYER', 'SMALL_ENTERPRISE_MUTUAL_AID')",
                               name="ck_jp_yea_declaration_type"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')",
                               name="ck_jp_yea_declaration_status"),
            sa.CheckConstraint("tax_year >= 2000", name="ck_jp_yea_declaration_year"),
        )
        op.create_index("ix_jp_yea_declaration_employee_year", DECLARATIONS,
                        ["organization_id", "employee_id", "tax_year"])

    if not _has_table(CASES):
        op.create_table(
            "payroll_jp_yea_cases",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tax_year", sa.SmallInteger(), nullable=False),
            sa.Column("state", sa.String(12), nullable=False, server_default="OPEN"),
            sa.Column("excluded_reason", sa.String(300), nullable=True),
            sa.Column("annual_income", sa.Numeric(14, 0), nullable=True),
            sa.Column("tax_withheld", sa.Numeric(14, 0), nullable=True),
            sa.Column("si_withheld", sa.Numeric(14, 0), nullable=True),
            sa.Column("annual_tax", sa.Numeric(14, 0), nullable=True),
            sa.Column("difference", sa.Numeric(14, 0), nullable=True),
            sa.Column("facts", _json(), nullable=True),
            sa.Column("result", _json(), nullable=True),
            sa.Column("applied_run_id", sa.Integer(),
                      sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            _user("created_by_id"),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
            _user("reviewed_by_id"),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            _user("applied_by_id"),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            _created_at(),
            sa.CheckConstraint("state IN ('OPEN', 'CALCULATED', 'REVIEWED', 'APPLIED', 'LOCKED', "
                               "'EXCLUDED', 'VOID')", name="ck_jp_yea_case_state"),
            sa.CheckConstraint("tax_year >= 2000", name="ck_jp_yea_case_year"),
        )
        op.create_index("uq_jp_yea_case_one_live", CASES, ["organization_id", "employee_id", "tax_year"],
                        unique=True, postgresql_where=sa.text("state <> 'VOID'"),
                        sqlite_where=sa.text("state <> 'VOID'"))

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (CASES, DECLARATIONS, OBLIGATIONS, EXCEPTIONS):
        if _has_table(table):
            op.drop_table(table)

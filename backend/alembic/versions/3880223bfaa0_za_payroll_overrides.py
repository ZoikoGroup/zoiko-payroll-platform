"""za_payroll_overrides: approved result overrides, ZA deduction authority, journal accounts

Revision ID: 3880223bfaa0
Revises: c15d5b87d6f5
Create Date: 2026-10-27

ZP-ZA-ENG-001 Phase 9 (labour controls, lifecycle, corrections). "ZA" is South
Africa ("SA" is Saudi Arabia).

  payroll_za_payroll_overrides   a recorded manual override of ONE result field
      of one employee in one run (ZA-017): before / after, reason code, reason,
      evidence, expiry; counts only once a second person approves it, changes a
      result never the rule pack, and goes stale when the computation moves.

Shared tables (nullable columns only):
  payroll_court_ordered_deductions.za_authority_type / za_evidence_ref
      ZA non-statutory deductions reuse the court-order table with
      jurisdiction = 'ZA'; ZA-013 needs the authority (statutory, court order,
      consent, collective agreement) and its evidence on the row. NULL for every
      UK order, which never reads them.
  payroll_za_employer_registrations.za_journal_accounts
      the employer's chart-of-accounts map for the ZA payroll journal (spec
      §10). No tenant payroll-settings JSON exists on the platform, so it lives
      beside the ZA registration; NULL means "not configured" and the journal
      BLOCKS — never a default account.

Row-level security: the new table has employee_id, so it gets the WORKER "org"
policy d7f9b1c3e5a6's classify() derives (tests/test_south_africa_migrations.py
proves it), PostgreSQL only. Literal table and column names so
scripts/drift_pending_filter explains every change. PostgreSQL: lock_timeout
fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3880223bfaa0"
down_revision: Union[str, Sequence[str], None] = "c15d5b87d6f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OVERRIDES = "payroll_za_payroll_overrides"
COURT_ORDERS = "payroll_court_ordered_deductions"
REGISTRATIONS = "payroll_za_employer_registrations"
_TABLES = (OVERRIDES,)


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols):
    if not _has_index(table, name):
        op.create_index(name, table, cols)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give the table this revision creates the WORKER "org" policy
    d7f9b1c3e5a6 derives for it (tests/test_south_africa_migrations.py proves
    classify() agrees), on THIS table only, as 447f57564983."""
    rls = _rls_module()
    predicate = rls._worker_predicate("org")
    for table in (OVERRIDES,):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # ── 1) Shared tables: nullable columns only (one literal op.add_column each) ──
    present = _columns(COURT_ORDERS)
    if "za_authority_type" not in present:
        op.add_column("payroll_court_ordered_deductions",
                      sa.Column("za_authority_type", sa.String(30), nullable=True))
    if "za_evidence_ref" not in present:
        op.add_column("payroll_court_ordered_deductions",
                      sa.Column("za_evidence_ref", sa.String(300), nullable=True))
    if "za_journal_accounts" not in _columns(REGISTRATIONS):
        op.add_column("payroll_za_employer_registrations",
                      sa.Column("za_journal_accounts", _json(), nullable=True))

    # ── 2) payroll_za_payroll_overrides (WORKER / org) ────────────────────
    t = OVERRIDES
    if not _has_table(t):
        op.create_table(
            "payroll_za_payroll_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("field", sa.String(40), nullable=False),
            sa.Column("before_value", sa.Numeric(14, 2), nullable=False),
            sa.Column("after_value", sa.Numeric(14, 2), nullable=False),
            sa.Column("reason_code", sa.String(40), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="PROPOSED"),
            sa.Column("expires_on", sa.Date(), nullable=False),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("field IN ('za_paye', 'za_uif_employee', 'za_uif_employer', 'za_sdl', "
                               "'za_other_deductions')", name="ck_za_override_field"),
            sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'APPLIED', 'EXPIRED', 'WITHDRAWN')",
                               name="ck_za_override_status"),
            sa.CheckConstraint("after_value >= 0", name="ck_za_override_after"),
        )
    _index(t, "ix_payroll_za_payroll_overrides_id", ["id"])
    _index(t, "ix_payroll_za_payroll_overrides_organization_id", ["organization_id"])
    _index(t, "ix_payroll_za_payroll_overrides_employee_id", ["employee_id"])
    _index(t, "ix_za_override_org_run", ["organization_id", "payroll_run_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "za_journal_accounts" in _columns(REGISTRATIONS):
        op.drop_column(REGISTRATIONS, "za_journal_accounts")
    present = _columns(COURT_ORDERS)
    for name in ("za_evidence_ref", "za_authority_type"):
        if name in present:
            op.drop_column(COURT_ORDERS, name)

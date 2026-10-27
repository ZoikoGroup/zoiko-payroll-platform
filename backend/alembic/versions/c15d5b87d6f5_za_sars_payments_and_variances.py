"""za_sars_payments_and_variances: SARS payments and approved reconciliation variances

Revision ID: c15d5b87d6f5
Revises: 447f57564983
Create Date: 2026-10-27

ZP-ZA-ENG-001 Phase 8 (SARS filing and reconciliation). "ZA" is South Africa
("SA" is Saudi Arabia).

  payroll_za_sars_payments            one payment made to SARS against an EMP201
      period (PRN, date, amount and its PAYE / SDL / UIF allocation); reversed,
      never edited (ZA-019: payroll = EMP201 = payment = certificates)
  payroll_za_reconciliation_variances an explained difference for one month of
      an EMP501 period; counts only once a second person approves it (ZA-019)

Additive only: two new tables; no existing row or column is touched.
Row-level security: both tables get the TENANT policy d7f9b1c3e5a6's classify()
derives (organization_id, no worker column), PostgreSQL only;
tests/test_south_africa_migrations.py proves classify() agrees. Literal table
and column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c15d5b87d6f5"
down_revision: Union[str, Sequence[str], None] = "447f57564983"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAYMENTS = "payroll_za_sars_payments"
VARIANCES = "payroll_za_reconciliation_variances"
_TABLES = (VARIANCES, PAYMENTS)


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


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


def _stamps():
    return [sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)]


def _org():
    return sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                     nullable=False)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give each table this revision creates the TENANT policy
    d7f9b1c3e5a6 derives for it (tests/test_south_africa_migrations.py proves
    classify() agrees), on THESE tables only, as 447f57564983."""
    rls = _rls_module()
    for table in (PAYMENTS, VARIANCES):
        predicate = rls._TENANT_PREDICATE
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    t = PAYMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_za_sars_payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("period_key", sa.String(20), nullable=False),
            sa.Column("paid_on", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("payment_reference", sa.String(60), nullable=False),
            sa.Column("allocation", _json(), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="RECORDED"),
            sa.Column("reverses_id", sa.Integer(),
                      sa.ForeignKey("payroll_za_sars_payments.id", ondelete="SET NULL"), nullable=True),
            *_stamps(),
            sa.CheckConstraint("amount > 0", name="ck_za_sars_payment_amount"),
            sa.CheckConstraint("status IN ('RECORDED', 'RECONCILED', 'REVERSED')", name="ck_za_sars_payment_status"),
        )
    _index(t, "ix_payroll_za_sars_payments_id", ["id"])
    _index(t, "ix_payroll_za_sars_payments_organization_id", ["organization_id"])
    _index(t, "ix_za_sars_payment_org_period", ["organization_id", "period_key"])
    _index(t, "uq_za_sars_payment_reference", ["organization_id", "payment_reference"], unique=True)

    t = VARIANCES
    if not _has_table(t):
        op.create_table(
            "payroll_za_reconciliation_variances",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("reconciliation_period", sa.String(20), nullable=False),
            sa.Column("month_key", sa.String(7), nullable=False),
            sa.Column("measure", sa.String(30), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="PROPOSED"),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
            sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'WITHDRAWN')", name="ck_za_variance_status"),
            sa.CheckConstraint("measure IN ('PAYROLL_VS_EMP201', 'EMP201_VS_PAYMENT', 'CERTIFICATES_VS_EMP201')",
                               name="ck_za_variance_measure"),
        )
    _index(t, "ix_payroll_za_reconciliation_variances_id", ["id"])
    _index(t, "ix_payroll_za_reconciliation_variances_organization_id", ["organization_id"])
    _index(t, "ix_za_variance_org_period", ["organization_id", "reconciliation_period"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

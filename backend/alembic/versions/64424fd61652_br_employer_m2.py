"""br_employer_m2: Brazil employer onboarding — risk by year, CPRB options and credential references

Revision ID: 64424fd61652
Revises: a6ca8aab2043
Create Date: 2026-10-16

ZP-BR-ENG-001 Phase 3 (docs/brazil/BRAZIL_PHASE_3_PLAN.md):
  - payroll_br_risk_assignments  RAT (1/2/3 %) + FAP (0.5–2.0) per establishment per calendar year, with evidence
  - payroll_br_cprb_options      the employer's CPRB option per calendar year (Lei 14.973/2024)
  - payroll_br_credential_refs   gcp-sm:// references + PUBLIC certificate metadata ONLY — never a secret

Partial unique indexes guard the one ACTIVE row per scope (NULL-safe), with
sqlite_where mirroring postgresql_where, as ContributionRate.

Additive only: three new tables; no existing row or column is touched.
Row-level security: each new table gets the TENANT policy d7f9b1c3e5a6
derives for it (organization_id, no worker column), PostgreSQL only.
Idempotent: every create is skipped when its object exists, every drop when it is gone.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "64424fd61652"
down_revision: Union[str, Sequence[str], None] = "a6ca8aab2043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("payroll_br_credential_refs", "payroll_br_cprb_options", "payroll_br_risk_assignments")


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
    when it ran: give each table this revision creates the policy d7f9b1c3e5a6
    derives for it (tests/test_brazil_rls_migrations.py proves classify() agrees),
    on THESE tables only, as mx_ptu_m10."""
    rls = _rls_module()
    for table, predicate in (("payroll_br_risk_assignments", rls._TENANT_PREDICATE), ("payroll_br_cprb_options", rls._TENANT_PREDICATE),
                             ("payroll_br_credential_refs", rls._TENANT_PREDICATE)):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))   # FKs to users / organizations lock briefly
    t = "payroll_br_risk_assignments"
    if not _has_table(t):
        op.create_table(
            "payroll_br_risk_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("establishment_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_establishments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("calendar_year", sa.SmallInteger(), nullable=False),
            sa.Column("rat_pct", sa.Numeric(4, 2), nullable=False),
            sa.Column("fap_factor", sa.Numeric(5, 4), nullable=False),
            sa.Column("evidence_ref", sa.String(300), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            *_stamps(),
            sa.CheckConstraint("rat_pct IN (1.00, 2.00, 3.00)", name="ck_br_risk_rat"),
            sa.CheckConstraint("fap_factor >= 0.5000 AND fap_factor <= 2.0000", name="ck_br_risk_fap"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_br_risk_status"),
            sa.CheckConstraint("calendar_year >= 2026 AND calendar_year <= 2100", name="ck_br_risk_year"),
        )
    _index(t, "ix_payroll_br_risk_assignments_id", ["id"])
    _index(t, "ix_payroll_br_risk_assignments_organization_id", ["organization_id"])
    _index(t, "ix_payroll_br_risk_assignments_establishment_id", ["establishment_id"])
    _index(t, "uq_br_risk_active_year", ["establishment_id", "calendar_year"], unique=True, where="status = 'ACTIVE'")

    t = "payroll_br_cprb_options"
    if not _has_table(t):
        op.create_table(
            "payroll_br_cprb_options",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("calendar_year", sa.SmallInteger(), nullable=False),
            sa.Column("opted", sa.Boolean(), nullable=False),
            sa.Column("sector_reference", sa.String(200), nullable=True),
            sa.Column("cprb_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="ACTIVE"),
            *_stamps(),
            sa.CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED')", name="ck_br_cprb_status"),
            sa.CheckConstraint("calendar_year >= 2026 AND calendar_year <= 2100", name="ck_br_cprb_year"),
            sa.CheckConstraint("cprb_rate_pct IS NULL OR (cprb_rate_pct > 0 AND cprb_rate_pct <= 100)",
                               name="ck_br_cprb_rate"),
        )
    _index(t, "ix_payroll_br_cprb_options_id", ["id"])
    _index(t, "ix_payroll_br_cprb_options_organization_id", ["organization_id"])
    _index(t, "ix_payroll_br_cprb_options_employer_profile_id", ["employer_profile_id"])
    _index(t, "uq_br_cprb_active_year", ["employer_profile_id", "calendar_year"], unique=True,
           where="status = 'ACTIVE'")

    t = "payroll_br_credential_refs"
    if not _has_table(t):
        op.create_table(
            "payroll_br_credential_refs",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("secret_ref", sa.String(300), nullable=False),
            sa.Column("certificate_serial", sa.String(80), nullable=True),
            sa.Column("fingerprint_sha256", sa.String(64), nullable=True),
            sa.Column("subject_summary", sa.String(500), nullable=True),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
            sa.Column("rotated_from_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_credential_refs.id", ondelete="SET NULL"), nullable=True),
            *_stamps(),
            sa.CheckConstraint("kind IN ('ESOCIAL_A1', 'BANK')", name="ck_br_credential_kind"),
            sa.CheckConstraint("status IN ('ACTIVE', 'ROTATED', 'REVOKED')", name="ck_br_credential_status"),
        )
    _index(t, "ix_payroll_br_credential_refs_id", ["id"])
    _index(t, "ix_payroll_br_credential_refs_organization_id", ["organization_id"])
    _index(t, "ix_payroll_br_credential_refs_employer_profile_id", ["employer_profile_id"])
    _index(t, "uq_br_credential_active_kind", ["employer_profile_id", "kind"], unique=True,
           where="status = 'ACTIVE'")
    if op.get_bind().dialect.name == "postgresql":
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

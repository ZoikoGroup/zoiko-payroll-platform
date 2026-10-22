"""br_employer_reshape: Brazil employer + establishment tables to the Phase 3 shape

Revision ID: a6ca8aab2043
Revises: b3f7c1e9d5a2
Create Date: 2026-10-19

ZP-BR-ENG-001 Phase 3 (docs/brazil/BRAZIL_PHASE_3_PLAN.md). b7a1c9e3d5f2 is
on main and may already be applied, so its tables are reshaped here, never by
editing that revision:

  payroll_br_employer_profiles  versioned + effective-dated (eSocial S-1000):
      + version, previous_version_id, effective_from, effective_to, created_by_id
      - cprb_opted, cprb_rate_pct (per year: payroll_br_cprb_options),
        esocial_cert_alias (vault reference: payroll_br_credential_refs)
      uq_br_employer_org (one per org) -> uq_br_employer_org_root_version
      + uq_br_employer_open_version (one open version per CNPJ root)
      status DRAFT/ACTIVE/SUSPENDED -> ACTIVE/SUSPENDED, default ACTIVE
  payroll_br_establishments
      + organization_id, fpas_status, fpas_evidence_ref, active_from, active_to,
        created_by_id, updated_at
      - rat_pct, fap_factor (per year: payroll_br_risk_assignments)
      + uq_br_establishment_active_hq (one ACTIVE headquarters per employer)

Fail-closed on data: Brazil is dormant, so both tables are expected to be
empty everywhere. If either holds a row the upgrade REFUSES (dropping the
CPRB / certificate / RAT / FAP columns would lose it) — review and migrate
those rows by hand first. Idempotent: every step is skipped when already
applied. created_by_id -> users is ON DELETE SET NULL, so delete_organization
(users before the org) never trips it. PostgreSQL: lock_timeout fail-fast, and
payroll_br_establishments gets the TENANT row-level-security policy
d7f9b1c3e5a6 derives now that it carries organization_id (employer profiles
already have theirs).
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6ca8aab2043"
down_revision: Union[str, Sequence[str], None] = "b3f7c1e9d5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPLOYER = "payroll_br_employer_profiles"
ESTABLISHMENT = "payroll_br_establishments"


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table):
    return {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table, name):
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def _named(table):
    """Names of the unique and CHECK constraints currently on the table."""
    insp = _inspector()
    names = {u["name"] for u in insp.get_unique_constraints(table)}
    try:
        names |= {c["name"] for c in insp.get_check_constraints(table)}
    except NotImplementedError:
        pass
    return names


def _fk_names(table):
    return {fk["name"] for fk in _inspector().get_foreign_keys(table) if fk.get("name")}


def _refuse_if_rows():
    bind = op.get_bind()
    for table in (EMPLOYER, ESTABLISHMENT):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        if count:
            raise RuntimeError(
                f"br_employer_reshape refuses: {table} holds {count} row(s). Brazil is dormant, so these "
                "tables should be empty; reshaping would drop CPRB / certificate / RAT / FAP columns. "
                "Review and migrate the rows by hand, then re-run."
            )


def _partial_unique(name, table, cols, where):
    if not _has_index(table, name):
        op.create_index(name, table, cols, unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_establishments(bind) -> None:
    """d7f9b1c3e5a6 left payroll_br_establishments without a policy (it had no
    organization_id then); with organization_id it is a TENANT table — give it
    the policy d7f9b1c3e5a6 derives, on this table only, as mx_ptu_m10."""
    rls = _rls_module()
    predicate = rls._TENANT_PREDICATE
    rls._sql(bind, f'ALTER TABLE "{ESTABLISHMENT}" ENABLE ROW LEVEL SECURITY')
    rls._sql(bind, f'ALTER TABLE "{ESTABLISHMENT}" FORCE ROW LEVEL SECURITY')
    rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{ESTABLISHMENT}"')
    rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{ESTABLISHMENT}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    # The reshape is nested here, with literal table names, so that
    # scripts/drift_pending_filter.py (the deploy's orphan self-heal) can read
    # every column this revision adds — it scans upgrade() text only.
    def _reshape() -> None:
        cols_e, cols_s = _columns(EMPLOYER), _columns(ESTABLISHMENT)
        employer_done = "effective_from" in cols_e and "cprb_opted" not in cols_e
        establishment_done = "active_from" in cols_s and "rat_pct" not in cols_s
        if employer_done and establishment_done:
            _partial_unique("uq_br_employer_open_version", EMPLOYER, ["organization_id", "cnpj_root"],
                            "effective_to IS NULL")
            _partial_unique("uq_br_establishment_active_hq", ESTABLISHMENT, ["employer_profile_id"],
                            "is_headquarters AND active_to IS NULL")
            return
        _refuse_if_rows()

        if not employer_done:
            named = _named(EMPLOYER)
            with op.batch_alter_table("payroll_br_employer_profiles") as b:
                if "version" not in cols_e:
                    b.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
                if "previous_version_id" not in cols_e:
                    b.add_column(sa.Column("previous_version_id", sa.Integer(), nullable=True))
                    b.create_foreign_key("fk_br_employer_previous_version", EMPLOYER,
                                         ["previous_version_id"], ["id"], ondelete="SET NULL")
                if "effective_from" not in cols_e:
                    b.add_column(sa.Column("effective_from", sa.Date(), nullable=False))
                if "effective_to" not in cols_e:
                    b.add_column(sa.Column("effective_to", sa.Date(), nullable=True))
                if "created_by_id" not in cols_e:
                    b.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
                    b.create_foreign_key("fk_br_employer_created_by", "users", ["created_by_id"], ["id"],
                                         ondelete="SET NULL")
                for col in ("cprb_opted", "cprb_rate_pct", "esocial_cert_alias"):
                    if col in cols_e:
                        b.drop_column(col)
                b.alter_column("status", existing_type=sa.String(20), existing_nullable=False,
                               server_default="ACTIVE")
                if "uq_br_employer_org" in named:
                    b.drop_constraint("uq_br_employer_org", type_="unique")
                if "ck_br_employer_status" in named:
                    b.drop_constraint("ck_br_employer_status", type_="check")
                b.create_check_constraint("ck_br_employer_status", "status IN ('ACTIVE', 'SUSPENDED')")
                if "uq_br_employer_org_root_version" not in named:
                    b.create_unique_constraint("uq_br_employer_org_root_version",
                                               ["organization_id", "cnpj_root", "version"])
                if "ck_br_employer_dates" not in named:
                    b.create_check_constraint("ck_br_employer_dates",
                                              "effective_to IS NULL OR effective_to >= effective_from")

        if not establishment_done:
            named = _named(ESTABLISHMENT)
            with op.batch_alter_table("payroll_br_establishments") as b:
                if "organization_id" not in cols_s:
                    b.add_column(sa.Column("organization_id", sa.Integer(), nullable=False))
                    b.create_foreign_key("fk_br_establishment_org", "organizations", ["organization_id"], ["id"],
                                         ondelete="CASCADE")
                if "fpas_status" not in cols_s:
                    b.add_column(sa.Column("fpas_status", sa.String(12), nullable=False, server_default="DECLARED"))
                if "fpas_evidence_ref" not in cols_s:
                    b.add_column(sa.Column("fpas_evidence_ref", sa.String(300), nullable=False))
                if "active_from" not in cols_s:
                    b.add_column(sa.Column("active_from", sa.Date(), nullable=False))
                if "active_to" not in cols_s:
                    b.add_column(sa.Column("active_to", sa.Date(), nullable=True))
                if "created_by_id" not in cols_s:
                    b.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
                    b.create_foreign_key("fk_br_establishment_created_by", "users", ["created_by_id"], ["id"],
                                         ondelete="SET NULL")
                if "updated_at" not in cols_s:
                    b.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
                for ck in ("ck_br_establishment_rat", "ck_br_establishment_fap"):
                    if ck in named:
                        b.drop_constraint(ck, type_="check")
                for col in ("rat_pct", "fap_factor"):
                    if col in cols_s:
                        b.drop_column(col)
                if "ck_br_establishment_fpas_status" not in named:
                    b.create_check_constraint("ck_br_establishment_fpas_status", "fpas_status IN ('DECLARED', 'VERIFIED')")
                if "ck_br_establishment_third_pct" not in named:
                    b.create_check_constraint("ck_br_establishment_third_pct",
                                              "third_party_pct >= 0 AND third_party_pct <= 100")
                if "ck_br_establishment_dates" not in named:
                    b.create_check_constraint("ck_br_establishment_dates",
                                              "active_to IS NULL OR active_to >= active_from")

        if not _has_index(ESTABLISHMENT, f"ix_{ESTABLISHMENT}_organization_id"):
            op.create_index(f"ix_{ESTABLISHMENT}_organization_id", ESTABLISHMENT, ["organization_id"])
        _partial_unique("uq_br_employer_open_version", EMPLOYER, ["organization_id", "cnpj_root"],
                        "effective_to IS NULL")
        _partial_unique("uq_br_establishment_active_hq", ESTABLISHMENT, ["employer_profile_id"],
                        "is_headquarters AND active_to IS NULL")

    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    _reshape()
    if postgres:
        _rls_for_establishments(bind)


def downgrade() -> None:
    """Back to the b7a1c9e3d5f2 shape. Refuses on data, like upgrade. On
    PostgreSQL the establishment policy (it reads organization_id) goes first."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        rls = _rls_module()
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{ESTABLISHMENT}"')
        rls._sql(bind, f'ALTER TABLE "{ESTABLISHMENT}" NO FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{ESTABLISHMENT}" DISABLE ROW LEVEL SECURITY')
    cols_e, cols_s = _columns(EMPLOYER), _columns(ESTABLISHMENT)
    if "effective_from" not in cols_e and "active_from" not in cols_s:
        return
    _refuse_if_rows()
    for table, name in ((EMPLOYER, "uq_br_employer_open_version"),
                        (ESTABLISHMENT, "uq_br_establishment_active_hq"),
                        (ESTABLISHMENT, f"ix_{ESTABLISHMENT}_organization_id")):
        if _has_index(table, name):
            op.drop_index(name, table_name=table)

    if "active_from" in cols_s:
        named, fks = _named(ESTABLISHMENT), _fk_names(ESTABLISHMENT)
        with op.batch_alter_table(ESTABLISHMENT) as b:
            for ck in ("ck_br_establishment_fpas_status", "ck_br_establishment_third_pct", "ck_br_establishment_dates"):
                if ck in named:
                    b.drop_constraint(ck, type_="check")
            for fk in ("fk_br_establishment_org", "fk_br_establishment_created_by"):
                if fk in fks:
                    b.drop_constraint(fk, type_="foreignkey")
            for col in ("organization_id", "fpas_status", "fpas_evidence_ref", "active_from", "active_to",
                        "created_by_id", "updated_at"):
                if col in cols_s:
                    b.drop_column(col)
            b.add_column(sa.Column("rat_pct", sa.Numeric(4, 2), nullable=False))
            b.add_column(sa.Column("fap_factor", sa.Numeric(5, 4), nullable=False, server_default="1.0000"))
            b.create_check_constraint("ck_br_establishment_rat", "rat_pct IN (1.00, 2.00, 3.00)")
            b.create_check_constraint("ck_br_establishment_fap", "fap_factor >= 0.5000 AND fap_factor <= 2.0000")

    if "effective_from" in cols_e:
        named, fks = _named(EMPLOYER), _fk_names(EMPLOYER)
        with op.batch_alter_table(EMPLOYER) as b:
            for ck in ("ck_br_employer_dates", "ck_br_employer_status"):
                if ck in named:
                    b.drop_constraint(ck, type_="check")
            if "uq_br_employer_org_root_version" in named:
                b.drop_constraint("uq_br_employer_org_root_version", type_="unique")
            for fk in ("fk_br_employer_previous_version", "fk_br_employer_created_by"):
                if fk in fks:
                    b.drop_constraint(fk, type_="foreignkey")
            for col in ("version", "previous_version_id", "effective_from", "effective_to", "created_by_id"):
                if col in cols_e:
                    b.drop_column(col)
            b.add_column(sa.Column("cprb_opted", sa.Boolean(), nullable=False, server_default=sa.false()))
            b.add_column(sa.Column("cprb_rate_pct", sa.Numeric(5, 2), nullable=True))
            b.add_column(sa.Column("esocial_cert_alias", sa.String(255), nullable=True))
            b.alter_column("status", existing_type=sa.String(20), existing_nullable=False, server_default="DRAFT")
            b.create_check_constraint("ck_br_employer_status", "status IN ('DRAFT', 'ACTIVE', 'SUSPENDED')")
            b.create_unique_constraint("uq_br_employer_org", ["organization_id"])

"""mx_employee_m3: Mexico employee statutory profile columns + INFONAVIT credit notices

Revision ID: 8b2f6d4e1a93
Revises: 6e4a1d9c3f27
Create Date: 2026-10-16

ZP-MX-ENG-001 Phase 4b (docs/mexico/MEXICO_PHASE_4_PLAN.md §4):
  - payroll_employee_statutory_profiles  + 24 nullable mx_* columns (no default) and two
    nullable FKs to the Phase 3 Mexico establishment / IMSS registration tables.
  - payroll_mx_infonavit_notices          new table (authority-notice-driven credit, MX-031).

Merging to main runs this in production, on a SHARED table, so (plan §4, approved change 5):
  1. PostgreSQL: SET LOCAL lock_timeout = '5s' — fail fast instead of queueing every payroll
     read behind a long transaction; the deploy then fails visibly and is re-run.
  2. ONE `ALTER TABLE … ADD COLUMN …, ADD COLUMN …` for every missing column — one brief
     ACCESS EXCLUSIVE lock, metadata-only (nullable, no default: no table rewrite).
  3. The two FKs are added NOT VALID in that same statement (no scan), then validated in
     separate statements (SHARE UPDATE EXCLUSIVE: reads and writes continue). Every
     existing value is NULL, so validation cannot fail.
  4. SQLite (dev/test): plain add_column per column — no lock settings.
Guarded and idempotent: a column / constraint / table / index already present is skipped;
downgrade removes only what this revision added.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8b2f6d4e1a93"
down_revision: Union[str, Sequence[str], None] = "6e4a1d9c3f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE = "payroll_employee_statutory_profiles"
NOTICES = "payroll_mx_infonavit_notices"

# (name, SQL type for PostgreSQL, SQLAlchemy type for SQLite) — all nullable, no default.
_COLUMNS = (
    ("mx_rfc_token", "VARCHAR(80)", sa.String(80)),
    ("mx_rfc_last4", "VARCHAR(4)", sa.String(4)),
    ("mx_curp_token", "VARCHAR(80)", sa.String(80)),
    ("mx_nss_token", "VARCHAR(80)", sa.String(80)),
    ("mx_identifier_validation_status", "VARCHAR(16)", sa.String(16)),
    ("mx_identifier_findings", "JSON", sa.JSON()),
    ("mx_fiscal_postal_code", "VARCHAR(5)", sa.String(5)),
    ("mx_receiver_fiscal_regime", "VARCHAR(10)", sa.String(10)),
    ("mx_establishment_id", "INTEGER", sa.Integer()),
    ("mx_imss_registration_id", "INTEGER", sa.Integer()),
    ("mx_work_state", "VARCHAR(5)", sa.String(5)),
    ("mx_work_municipality", "VARCHAR(200)", sa.String(200)),
    ("mx_remote_state_exception_ref", "VARCHAR(200)", sa.String(200)),
    ("mx_seniority_date", "DATE", sa.Date()),
    ("mx_contract_type_code", "VARCHAR(10)", sa.String(10)),
    ("mx_regime_type_code", "VARCHAR(10)", sa.String(10)),
    ("mx_workday_type_code", "VARCHAR(10)", sa.String(10)),
    ("mx_job_risk_code", "VARCHAR(10)", sa.String(10)),
    ("mx_professional_min_code", "VARCHAR(20)", sa.String(20)),
    ("mx_pay_frequency_code", "VARCHAR(10)", sa.String(10)),
    ("mx_daily_salary", "NUMERIC(14, 2)", sa.Numeric(14, 2)),
    ("mx_salary_type", "VARCHAR(10)", sa.String(10)),
    ("mx_annual_adjustment_exclusion", "VARCHAR(40)", sa.String(40)),
    ("mx_annual_adjustment_exclusion_evidence_ref", "VARCHAR(200)", sa.String(200)),
)
# (constraint name, column, referenced table)
_FKS = (
    ("fk_statutory_profile_mx_establishment", "mx_establishment_id", "payroll_mx_establishments"),
    ("fk_statutory_profile_mx_imss_registration", "mx_imss_registration_id", "payroll_mx_imss_registrations"),
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _inspector().get_indexes(table)}


def _columns(table):
    return {c["name"] for c in _inspector().get_columns(table)} if _has_table(table) else set()


def _fk_names(table):
    return {fk.get("name") for fk in _inspector().get_foreign_keys(table)} if _has_table(table) else set()


def _upgrade_profile_postgres(missing, missing_fks):
    bind = op.get_bind()
    bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    clauses = [f"ADD COLUMN {name} {sql_type}" for name, sql_type, _ in _COLUMNS if name in missing]
    clauses += [f"ADD CONSTRAINT {fk} FOREIGN KEY ({col}) REFERENCES {ref} (id) ON DELETE SET NULL NOT VALID"
                for fk, col, ref in _FKS if fk in missing_fks]
    if clauses:
        bind.execute(sa.text(f"ALTER TABLE {PROFILE} " + ", ".join(clauses)))
    for fk, _col, _ref in _FKS:
        if fk in missing_fks:
            bind.execute(sa.text(f"ALTER TABLE {PROFILE} VALIDATE CONSTRAINT {fk}"))


def _upgrade_profile_sqlite(missing):
    """SQLite cannot add a FK column in place, so batch mode (copy-and-move) —
    dev/test only; production is PostgreSQL (_upgrade_profile_postgres)."""
    if not missing:
        return
    fk_for = {col: (fk, ref) for fk, col, ref in _FKS}
    with op.batch_alter_table(PROFILE) as batch:
        for name, _sql_type, sa_type in _COLUMNS:
            if name not in missing:
                continue
            batch.add_column(sa.Column(name, sa_type, nullable=True))
            if name in fk_for:
                fk, ref = fk_for[name]
                batch.create_foreign_key(fk, ref, [name], ["id"], ondelete="SET NULL")


def upgrade() -> None:
    present = _columns(PROFILE)
    missing = {name for name, _t, _s in _COLUMNS if name not in present}
    if op.get_bind().dialect.name == "postgresql":
        existing_fks = _fk_names(PROFILE)
        missing_fks = {fk for fk, _c, _r in _FKS if fk not in existing_fks}
        _upgrade_profile_postgres(missing, missing_fks)
    else:
        _upgrade_profile_sqlite(missing)

    if not _has_table("payroll_mx_infonavit_notices"):
        op.create_table(
            "payroll_mx_infonavit_notices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("credit_number", sa.String(30), nullable=False),
            sa.Column("notice_type", sa.String(12), nullable=False),
            sa.Column("discount_method", sa.String(12), nullable=True),
            sa.Column("discount_value", sa.Numeric(14, 4), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("authority_reference", sa.String(100), nullable=False),
            sa.Column("evidence_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("notice_type IN ('RETENCION', 'SUSPENSION', 'MODIFICACION')", name="ck_mx_infonavit_type"),
            sa.CheckConstraint("discount_method IS NULL OR discount_method IN ('FIXED_AMOUNT', 'PERCENTAGE', 'VSM', "
                               "'UMA_FACTOR')", name="ck_mx_infonavit_method"),
            sa.CheckConstraint("status IN ('RECORDED', 'SUPERSEDED', 'CLOSED')", name="ck_mx_infonavit_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_infonavit_window"),
        )
    for name, cols in (("ix_payroll_mx_infonavit_notices_id", ["id"]),
                       ("ix_payroll_mx_infonavit_notices_organization_id", ["organization_id"]),
                       ("ix_payroll_mx_infonavit_notices_employee_id", ["employee_id"])):
        if not _has_index(NOTICES, name):
            op.create_index(name, NOTICES, cols)
    if not _has_index(NOTICES, "uq_mx_infonavit_employee_credit_open"):
        where = "effective_to IS NULL AND status = 'RECORDED'"
        op.create_index("uq_mx_infonavit_employee_credit_open", NOTICES, ["employee_id", "credit_number"], unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))


def downgrade() -> None:
    if _has_table(NOTICES):
        op.drop_table(NOTICES)
    present = _columns(PROFILE)
    if op.get_bind().dialect.name == "postgresql":
        bind = op.get_bind()
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        existing_fks = _fk_names(PROFILE)
        clauses = [f"DROP CONSTRAINT {fk}" for fk, _c, _r in _FKS if fk in existing_fks]
        clauses += [f"DROP COLUMN {name}" for name, _t, _s in _COLUMNS if name in present]
        if clauses:
            bind.execute(sa.text(f"ALTER TABLE {PROFILE} " + ", ".join(clauses)))
    else:
        drop = [name for name, _t, _s in _COLUMNS if name in present]
        if drop:
            with op.batch_alter_table(PROFILE) as batch:
                for name in drop:
                    batch.drop_column(name)

"""br_employee_m3: Brazil employee statutory-profile columns + concurrent-INSS / alimony / VT tables

Revision ID: b9f3a7c2e5d1
Revises: 64424fd61652
Create Date: 2026-10-19

ZP-BR-ENG-001 Phase 4b (docs/brazil/BRAZIL_PHASE_4_PLAN.md §2, §8):
  - payroll_employee_statutory_profiles  + 10 nullable br_* columns (no default) and one
    nullable FK to the Phase 3 Brazil establishment table (ON DELETE SET NULL).
  - payroll_br_concurrent_inss_declarations  new table (BR-009).
  - payroll_br_alimony_orders                new table (court orders, fixed or %×base).
  - payroll_br_vale_transporte_elections     new table (VT elections).
  - payroll_br_statutory_profiles            DROPPED — its facts move to the shared br_* block
    above (every other jurisdiction keeps its employee facts there). Table is empty everywhere.

Merging to main runs this in production, on a SHARED table, so (plan §2, the mx_employee_m3
precedent):
  1. PostgreSQL: SET LOCAL lock_timeout = '5s' — fail fast instead of queueing every payroll read
     behind a long transaction; the deploy fails visibly and is re-run.
  2. ONE `ALTER TABLE … ADD COLUMN …, ADD COLUMN …` for every missing column — one brief ACCESS
     EXCLUSIVE lock, metadata-only (nullable, no default: no table rewrite).
  3. The FK is added NOT VALID in that same statement (no scan), then validated separately
     (SHARE UPDATE EXCLUSIVE: reads and writes continue). Every existing value is NULL.
  4. SQLite (dev/test): plain add_column per column — no lock settings.
  5. Row-level security: the three new tables are WORKER tables (employee_id +
     organization_id, strategy "org") and get the policy d7f9b1c3e5a6 derives; the
     shared profile table keeps the policy it already has.
  Guarded and idempotent: a column / constraint / table / index already present is skipped;
  downgrade removes only what this revision added (it does NOT recreate the dropped legacy table).
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9f3a7c2e5d1"
down_revision: Union[str, Sequence[str], None] = "64424fd61652"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE = "payroll_employee_statutory_profiles"
CONCURRENT = "payroll_br_concurrent_inss_declarations"
ALIMONY = "payroll_br_alimony_orders"
VALE = "payroll_br_vale_transporte_elections"
LEGACY_PROFILE = "payroll_br_statutory_profiles"

# (name, SQL type for PostgreSQL, SQLAlchemy type for SQLite) — all nullable, no default.
_COLUMNS = (
    ("br_establishment_id", "INTEGER", sa.Integer()),
    ("br_esocial_category", "VARCHAR(3)", sa.String(3)),
    ("br_cbo_code", "VARCHAR(6)", sa.String(6)),
    ("br_contract_type", "VARCHAR(20)", sa.String(20)),
    ("br_weekly_hours", "NUMERIC(4, 2)", sa.Numeric(4, 2)),
    ("br_simplified_irrf_opt_out", "BOOLEAN", sa.Boolean()),
    ("br_irrf_dependents_count", "SMALLINT", sa.SmallInteger()),
    ("br_irrf_dependents_evidence_ref", "VARCHAR(300)", sa.String(300)),
    ("br_salario_familia_dependents_count", "SMALLINT", sa.SmallInteger()),
    ("br_salario_familia_dependents_evidence_ref", "VARCHAR(300)", sa.String(300)),
)

# (constraint name, column, referenced table)
_FKS = (("fk_br_profile_establishment", "br_establishment_id", "payroll_br_establishments"),)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set:
    if not _has_table(table):
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _fk_names(table: str) -> set:
    if not _has_table(table):
        return set()
    return {fk.get("name") for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)}


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return name in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}


def _upgrade_profile_postgres(missing, missing_fks) -> None:
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
    for table, predicate in ((CONCURRENT, rls._worker_predicate("org")), (ALIMONY, rls._worker_predicate("org")),
                             (VALE, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    present = _columns(PROFILE)
    missing = {name for name, _sql_type, _sa in _COLUMNS if name not in present}
    if op.get_bind().dialect.name == "postgresql":
        existing_fks = _fk_names(PROFILE)
        missing_fks = {fk for fk, _col, _ref in _FKS if fk not in existing_fks}
        _upgrade_profile_postgres(missing, missing_fks)
    else:
        # SQLite cannot add a FK column in place, so batch mode (copy-and-move) —
        # dev/test only. Literal names, so scripts/drift_pending_filter.py (the
        # deploy's orphan self-heal) sees every column this revision adds.
        if missing:
            with op.batch_alter_table("payroll_employee_statutory_profiles") as batch:
                if "br_establishment_id" in missing:
                    batch.add_column(sa.Column("br_establishment_id", sa.Integer(), nullable=True))
                if "br_esocial_category" in missing:
                    batch.add_column(sa.Column("br_esocial_category", sa.String(3), nullable=True))
                if "br_cbo_code" in missing:
                    batch.add_column(sa.Column("br_cbo_code", sa.String(6), nullable=True))
                if "br_contract_type" in missing:
                    batch.add_column(sa.Column("br_contract_type", sa.String(20), nullable=True))
                if "br_weekly_hours" in missing:
                    batch.add_column(sa.Column("br_weekly_hours", sa.Numeric(4, 2), nullable=True))
                if "br_simplified_irrf_opt_out" in missing:
                    batch.add_column(sa.Column("br_simplified_irrf_opt_out", sa.Boolean(), nullable=True))
                if "br_irrf_dependents_count" in missing:
                    batch.add_column(sa.Column("br_irrf_dependents_count", sa.SmallInteger(), nullable=True))
                if "br_irrf_dependents_evidence_ref" in missing:
                    batch.add_column(sa.Column("br_irrf_dependents_evidence_ref", sa.String(300), nullable=True))
                if "br_salario_familia_dependents_count" in missing:
                    batch.add_column(sa.Column("br_salario_familia_dependents_count", sa.SmallInteger(), nullable=True))
                if "br_salario_familia_dependents_evidence_ref" in missing:
                    batch.add_column(sa.Column("br_salario_familia_dependents_evidence_ref", sa.String(300), nullable=True))
                if "br_establishment_id" in missing:
                    batch.create_foreign_key("fk_br_profile_establishment", "payroll_br_establishments",
                                             ["br_establishment_id"], ["id"], ondelete="SET NULL")
    t = "payroll_br_concurrent_inss_declarations"
    if not _has_table(t):
        op.create_table(
            "payroll_br_concurrent_inss_declarations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("competence_month", sa.Date(), nullable=False),
            sa.Column("base_external", sa.Numeric(12, 2), nullable=False),
            sa.Column("deducted_external", sa.Numeric(12, 2), nullable=False),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("status IN ('RECORDED', 'SUPERSEDED')", name="ck_br_conc_inss_status"),
            sa.CheckConstraint("base_external >= 0", name="ck_br_concurrent_base"),
            sa.CheckConstraint("deducted_external >= 0", name="ck_br_concurrent_deducted"),
        )
    for name, cols in ((f"ix_{t}_id", ["id"]), (f"ix_{t}_organization_id", ["organization_id"]),
                       (f"ix_{t}_employee_id", ["employee_id"])):
        if not _has_index(t, name):
            op.create_index(name, t, cols)
    if not _has_index(t, "uq_br_concurrent_employee_month_open"):
        where = "status = 'RECORDED'"
        op.create_index("uq_br_concurrent_employee_month_open", t, ["employee_id", "competence_month"], unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))
    t = "payroll_br_alimony_orders"
    if not _has_table(t):
        op.create_table(
            "payroll_br_alimony_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("order_reference", sa.String(100), nullable=False),
            sa.Column("method", sa.String(12), nullable=False),
            sa.Column("fixed_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("base", sa.String(12), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("method IN ('FIXED_AMOUNT', 'PERCENTAGE')", name="ck_br_alimony_method"),
            sa.CheckConstraint(
                "(method = 'FIXED_AMOUNT' AND fixed_amount IS NOT NULL AND percentage IS NULL AND base IS NULL) OR "
                "(method = 'PERCENTAGE' AND percentage IS NOT NULL AND base IS NOT NULL AND fixed_amount IS NULL)",
                name="ck_br_alimony_shape"),
            sa.CheckConstraint("percentage IS NULL OR (percentage > 0 AND percentage <= 100)", name="ck_br_alimony_pct"),
            sa.CheckConstraint("fixed_amount IS NULL OR fixed_amount > 0", name="ck_br_alimony_fixed"),
            sa.CheckConstraint("base IS NULL OR base IN ('GROSS', 'NET', 'BASE_INSS', 'BASE_IRRF')",
                               name="ck_br_alimony_base"),
            sa.CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED', 'CLOSED')", name="ck_br_alimony_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_br_alimony_window"),
        )
    for name, cols in ((f"ix_{t}_id", ["id"]), (f"ix_{t}_organization_id", ["organization_id"]),
                       (f"ix_{t}_employee_id", ["employee_id"])):
        if not _has_index(t, name):
            op.create_index(name, t, cols)
    if not _has_index(t, "uq_br_alimony_employee_order_open"):
        where = "effective_to IS NULL AND status = 'ACTIVE'"
        op.create_index("uq_br_alimony_employee_order_open", t, ["employee_id", "order_reference"], unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))
    t = "payroll_br_vale_transporte_elections"
    if not _has_table(t):
        op.create_table(
            "payroll_br_vale_transporte_elections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("elected", sa.Boolean(), nullable=False),
            sa.Column("daily_cost", sa.Numeric(8, 2), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("elected = false OR daily_cost IS NOT NULL", name="ck_br_vt_elected_cost"),
            sa.CheckConstraint("daily_cost IS NULL OR daily_cost >= 0", name="ck_br_vt_daily_cost"),
            sa.CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED')", name="ck_br_vt_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_br_vt_window"),
        )
    for name, cols in ((f"ix_{t}_id", ["id"]), (f"ix_{t}_organization_id", ["organization_id"]),
                       (f"ix_{t}_employee_id", ["employee_id"])):
        if not _has_index(t, name):
            op.create_index(name, t, cols)
    if not _has_index(t, "uq_br_vt_employee_open"):
        where = "effective_to IS NULL AND status = 'ACTIVE'"
        op.create_index("uq_br_vt_employee_open", t, ["employee_id"], unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))
    if _has_table(LEGACY_PROFILE):
        op.drop_table(LEGACY_PROFILE)
    if op.get_bind().dialect.name == "postgresql":
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    # The new tables are this revision's own — drop the ones that exist.
    for t in ("payroll_br_vale_transporte_elections", "payroll_br_alimony_orders",
              "payroll_br_concurrent_inss_declarations"):
        if _has_table(t):
            op.drop_table(t)
    # The old dedicated table is intentionally NOT recreated: its facts now live
    # on the shared br_* block, and recreating an empty duplicate would restore
    # the split-brain this revision removed.
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

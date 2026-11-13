"""pl_incapacity_episodes: Poland sickness / incapacity episodes (restricted)

Revision ID: e11c2c36df17
Revises: 1ee3bbde33bb
Create Date: 2026-11-05

ZP-PL-ENG-001 Phase 6 (spec §9, PL-017 / PL-018). Additive only: one new
payroll_pl_* table; no existing row is touched.

  payroll_pl_incapacity_episodes   one row per certified incapacity episode:
      from / to dates, statutory category, the certificate reference and a
      POINTER to the protected medical record (never a diagnosis or any
      medical detail, PL-017), the approved benefit-base snapshot (daily base,
      reference window, evidence) the employer sick pay uses, four-eyes
      approval and supersession. A retro change is a NEW version that
      supersedes the old one (PL-018): committed payslips are never edited,
      the transition point is rebuilt by recalculation.

No statutory number appears in any CHECK constraint (spec page 1).
Row-level security: WORKER "org" (d7f9b1c3e5a6's classify()); PostgreSQL only.
Literal table and column names (scripts/drift_pending_filter). PostgreSQL
lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e11c2c36df17"
down_revision: Union[str, Sequence[str], None] = "1ee3bbde33bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EPISODES = "payroll_pl_incapacity_episodes"
WORKER_TABLES = (EPISODES,)
_TABLES = (EPISODES,)
CATEGORIES = ("ILLNESS", "ROUTE_ACCIDENT", "PREGNANCY", "DONOR", "WORK_ACCIDENT", "OTHER")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


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

    t = EPISODES
    if not _has_table(t):
        op.create_table(
            "payroll_pl_incapacity_episodes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("legal_entity_id", sa.Integer(),
                      sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("date_from", sa.Date(), nullable=False),
            sa.Column("date_to", sa.Date(), nullable=False),
            sa.Column("category", sa.String(16), nullable=False),
            sa.Column("certificate_ref", sa.String(60), nullable=True),
            sa.Column("medical_record_ref", sa.String(100), nullable=True),
            sa.Column("daily_base_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("base_reference_from", sa.Date(), nullable=True),
            sa.Column("base_reference_to", sa.Date(), nullable=True),
            sa.Column("base_evidence_ref", sa.String(300), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("previous_version_id", sa.Integer(),
                      sa.ForeignKey(f"{EPISODES}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"category IN {_in(CATEGORIES)}", name="ck_pl_incapacity_category"),
            sa.CheckConstraint("date_to >= date_from", name="ck_pl_incapacity_dates"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED', 'CANCELLED')",
                               name="ck_pl_incapacity_status"),
            sa.CheckConstraint("evidence_ref IS NOT NULL OR certificate_ref IS NOT NULL",
                               name="ck_pl_incapacity_evidence"),
            sa.CheckConstraint("daily_base_amount IS NULL OR (daily_base_amount > 0 AND base_reference_from IS NOT NULL "
                               "AND base_reference_to IS NOT NULL AND base_evidence_ref IS NOT NULL)",
                               name="ck_pl_incapacity_base_evidence"),
            sa.CheckConstraint("base_reference_to IS NULL OR base_reference_from IS NULL OR "
                               "base_reference_to >= base_reference_from", name="ck_pl_incapacity_base_dates"),
            sa.CheckConstraint("status <> 'APPROVED' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_pl_incapacity_four_eyes"),
        )
    _index(t, f"ix_{t}_id", ["id"])
    _index(t, f"ix_{t}_organization_id", ["organization_id"])
    _index(t, f"ix_{t}_legal_entity_id", ["legal_entity_id"])
    _index(t, f"ix_{t}_employee_id", ["employee_id"])
    _index(t, "ix_pl_incapacity_employee_dates", ["employee_id", "date_from"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

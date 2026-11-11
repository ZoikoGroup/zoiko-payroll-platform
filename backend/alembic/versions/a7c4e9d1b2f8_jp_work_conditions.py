"""jp_work_conditions: effective-dated Japan working-time facts

Revision ID: a7c4e9d1b2f8
Revises: 9c1d7e4a2b6f
Create Date: 2026-11-02

ZP-JP-ENG-001 Phase 6. One additive tenant table for the facts the Japan
engine needs before it can classify hours or compare the minimum wage:
working-time system, scheduled daily/monthly hours, week start, workplace
prefecture and whether the specific minimum wage applies. Additive only,
idempotent both ways, lock_timeout fail-fast on PostgreSQL.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c4e9d1b2f8"
down_revision: Union[str, Sequence[str], None] = "9c1d7e4a2b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_jp_work_conditions"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    predicate = rls._TENANT_PREDICATE
    rls._sql(bind, f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    rls._sql(bind, f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
    rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{TABLE}"')
    rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{TABLE}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if not _has_table(TABLE):
        op.create_table(
            "payroll_jp_work_conditions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("legal_entity_id", sa.Integer(),
                      sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("previous_version_id", sa.Integer(),
                      sa.ForeignKey(f"{TABLE}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("working_time_system", sa.String(20), nullable=False,
                      server_default="STANDARD"),
            sa.Column("week_start_day", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("scheduled_daily_minutes", sa.Integer(), nullable=False),
            sa.Column("scheduled_monthly_hours", sa.Numeric(6, 2), nullable=False),
            sa.Column("workplace_prefecture", sa.String(2), nullable=False),
            sa.Column("specific_minimum_wage_applies", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("working_time_system IN ('STANDARD')",
                               name="ck_jp_work_conditions_system"),
            sa.CheckConstraint("week_start_day BETWEEN 0 AND 6",
                               name="ck_jp_work_conditions_week_start"),
            sa.CheckConstraint("scheduled_daily_minutes > 0",
                               name="ck_jp_work_conditions_daily_minutes"),
            sa.CheckConstraint("scheduled_monthly_hours > 0",
                               name="ck_jp_work_conditions_monthly_hours"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')",
                               name="ck_jp_work_conditions_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_work_conditions_dates"),
        )
        op.create_index("ix_jp_work_conditions_org_period", TABLE,
                        ["organization_id", "effective_from"])
        op.create_index(
            "uq_jp_work_conditions_one_active", TABLE, ["organization_id"], unique=True,
            postgresql_where=sa.text("status = 'ACTIVE' AND effective_to IS NULL"),
            sqlite_where=sa.text("status = 'ACTIVE' AND effective_to IS NULL"),
        )

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(TABLE):
        op.drop_table(TABLE)

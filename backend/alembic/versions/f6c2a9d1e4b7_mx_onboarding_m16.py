"""mx_onboarding_m16: the Mexico "no new organisations" switch (Phase 10g)

Revision ID: f6c2a9d1e4b7
Revises: e5b1d8f3a7c2
Create Date: 2026-10-22

ZP-MX-ENG-001 Phase 10g (MEXICO_PHASE_10G_IMPLEMENTATION_REPORT.md): ONE new table,
payroll_mx_onboarding_pauses — platform configuration (no organisation_id, no worker
column), so it carries no row-level-security policy, like every other platform
table. No shared table is touched.

Merging to main runs this in production. Creating the FKs to users takes a brief
SHARE ROW EXCLUSIVE lock on users (reads continue; writes wait) that alembic/env.py
holds until the upgrade transaction commits — so the revision runs under SET LOCAL
lock_timeout = '5s'. Measured on PostgreSQL 17 in tests/test_mexico_onboarding_migrations.py.
Guarded and idempotent; downgrade drops only this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6c2a9d1e4b7"
down_revision: Union[str, Sequence[str], None] = "e5b1d8f3a7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAUSE = "payroll_mx_onboarding_pauses"
NEW_TABLES = (PAUSE,)


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s = sa.Integer, sa.String
    if not _has_table(PAUSE):
        op.create_table(
            "payroll_mx_onboarding_pauses",
            sa.Column("id", i(), primary_key=True),
            sa.Column("action", s(8), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("reason", s(300), nullable=False),
            sa.Column("proposed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("action IN ('PAUSE', 'RESUME')", name="ck_mx_onboarding_pause_action"),
            sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'WITHDRAWN')", name="ck_mx_onboarding_pause_status"),
        )
    if not _has_index(PAUSE, f"ix_{PAUSE}_id"):
        op.create_index(f"ix_{PAUSE}_id", PAUSE, ["id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(PAUSE):
        op.drop_table(PAUSE)

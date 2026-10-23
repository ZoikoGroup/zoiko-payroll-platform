"""mx_cfdi_system_concepts_m17: SAT codes for engine-produced amounts (Phase 11a)

Revision ID: a8e4c1f7d3b5
Revises: f6c2a9d1e4b7
Create Date: 2026-10-23

ZP-MX-ENG-001 Phase 11a (MEXICO_PHASE_11_PLAN.md §4.3, decision D4): ONE new table,
payroll_mx_cfdi_system_concepts — platform configuration per CFDI schema release
(no organisation_id, no worker column), so it carries no row-level-security
policy, like every other platform table. No shared table is touched.

Merging to main runs this in production. Creating the FKs takes a brief SHARE ROW
EXCLUSIVE lock on users and payroll_mx_cfdi_schema_releases (reads continue; writes
wait) that alembic/env.py holds until the upgrade transaction commits — so the
revision runs under SET LOCAL lock_timeout = '5s'. Measured on PostgreSQL 17 in
tests/test_mexico_cfdi_concept_migrations.py. Guarded and idempotent; downgrade
drops only this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8e4c1f7d3b5"
down_revision: Union[str, Sequence[str], None] = "f6c2a9d1e4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONCEPTS = "payroll_mx_cfdi_system_concepts"
NEW_TABLES = (CONCEPTS,)


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
    if not _has_table(CONCEPTS):
        op.create_table(
            "payroll_mx_cfdi_system_concepts",
            sa.Column("id", i(), primary_key=True),
            sa.Column("schema_release_id", i(),
                      sa.ForeignKey("payroll_mx_cfdi_schema_releases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("concept_key", s(40), nullable=False),
            sa.Column("node_type", s(12), nullable=False),
            sa.Column("sat_code", s(10), nullable=False),
            sa.Column("source_ref", s(300), nullable=False),
            sa.Column("status", s(12), nullable=False),
            sa.Column("proposed_by_id", i(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("node_type IN ('PERCEPCION', 'DEDUCCION', 'OTRO_PAGO')", name="ck_mx_cfdi_sysc_node"),
            sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'WITHDRAWN', 'SUPERSEDED')",
                               name="ck_mx_cfdi_sysc_status"),
        )
    if not _has_index(CONCEPTS, f"ix_{CONCEPTS}_id"):
        op.create_index(f"ix_{CONCEPTS}_id", CONCEPTS, ["id"])
    if not _has_index(CONCEPTS, f"ix_{CONCEPTS}_schema_release_id"):
        op.create_index(f"ix_{CONCEPTS}_schema_release_id", CONCEPTS, ["schema_release_id"])
    if not _has_index(CONCEPTS, "uq_mx_cfdi_sysc_approved"):
        op.create_index("uq_mx_cfdi_sysc_approved", CONCEPTS, ["schema_release_id", "concept_key"], unique=True,
                        postgresql_where=sa.text("status = 'APPROVED'"),
                        sqlite_where=sa.text("status = 'APPROVED'"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(CONCEPTS):
        op.drop_table(CONCEPTS)

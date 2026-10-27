"""mx_final_mile_m20: the Mexico decision register (final mile X1)

Revision ID: d3f8b2a6c1e9
Revises: c7d2e9a4f1b6
Create Date: 2026-10-27

Mexico final mile (MEXICO_FINAL_MILE_MASTER_PROMPT.md X1): ONE new table,
payroll_mx_decisions — the recorded answer to each open decision (DECISIONS_PENDING
D-01 …, gap register C4 / C5 / C12), four-eyes, versioned. Platform configuration: no
organisation_id and no worker column, so no row-level-security policy, like every
other platform table. User ids are plain integers (no foreign key to users), so the
revision takes no lock on any existing table: only its own CREATE TABLE.

Merging to main runs this in production, under SET LOCAL lock_timeout = '5s'.
Measured on PostgreSQL 17 in tests/test_mexico_final_mile_migrations.py. Guarded and
idempotent; downgrade drops only this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f8b2a6c1e9"
down_revision: Union[str, Sequence[str], None] = "c7d2e9a4f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DECISIONS = "payroll_mx_decisions"
NEW_TABLES = (DECISIONS,)


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s, t, j, dt = sa.Integer, sa.String, sa.Text, sa.JSON, sa.DateTime
    if not _has_table(DECISIONS):
        op.create_table(
            "payroll_mx_decisions",                 # literal: scripts/drift_pending_filter reads it
            sa.Column("id", i(), primary_key=True),
            sa.Column("code", s(10), nullable=False),
            sa.Column("version", i(), nullable=False),
            sa.Column("title", s(200), nullable=False),
            sa.Column("gates", j(), nullable=False),
            sa.Column("owner_role", s(60), nullable=True),
            sa.Column("question", t(), nullable=False),
            sa.Column("options", j(), nullable=False),
            sa.Column("question_sources", j(), nullable=False),
            sa.Column("block_codes", j(), nullable=False),
            sa.Column("content_keys", j(), nullable=False),
            sa.Column("answer_kind", s(20), nullable=False),
            sa.Column("allowed_values", j(), nullable=True),
            sa.Column("status", s(12), nullable=False),
            sa.Column("chosen_option", t(), nullable=True),
            sa.Column("rationale", t(), nullable=True),
            sa.Column("cited_sources", j(), nullable=True),
            sa.Column("content_hash", s(64), nullable=True),
            sa.Column("supersedes_id", i(), sa.ForeignKey(f"{DECISIONS}.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("proposed_by_id", i(), nullable=True),
            sa.Column("proposed_at", dt(timezone=True), nullable=True),
            sa.Column("approved_by_id", i(), nullable=True),
            sa.Column("approved_at", dt(timezone=True), nullable=True),
            sa.Column("transcribed_by_id", i(), nullable=True),
            sa.Column("transcribed_at", dt(timezone=True), nullable=True),
            sa.Column("transcription_ref", s(200), nullable=True),
            sa.Column("created_at", dt(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", dt(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('OPEN', 'PROPOSED', 'APPROVED', 'TRANSCRIBED', 'WITHDRAWN', 'SUPERSEDED')",
                               name="ck_mx_decision_status"),
            sa.CheckConstraint("answer_kind IN ('FREE_TEXT', 'ENUM', 'ROUNDING_RULE', 'PAY_PERIOD', 'AMOUNT')",
                               name="ck_mx_decision_answer_kind"),
            sa.UniqueConstraint("code", "version", name="uq_mx_decision_code_version"),
        )
    for column in ("id", "code"):
        if not _has_index(DECISIONS, f"ix_{DECISIONS}_{column}"):
            op.create_index(f"ix_{DECISIONS}_{column}", DECISIONS, [column])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(DECISIONS):
        op.drop_table(DECISIONS)

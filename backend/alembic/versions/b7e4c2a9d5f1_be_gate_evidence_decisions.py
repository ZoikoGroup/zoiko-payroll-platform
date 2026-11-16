"""be_gate_evidence_decisions: Belgium release-gate evidence and decision records

Revision ID: b7e4c2a9d5f1
Revises: cf348b09db2b
Create Date: 2026-11-16

ZP-BE-ENG-001 Block K2 / K3. Additive only: two new platform-level tables; nothing existing is touched.

  payroll_be_gate_evidence  evidence for a release gate G1-G7: gate, evidence type (the readiness tag it supports,
      or SUPPORTING), reference, note, optional source artifact, status PENDING / ACCEPTED / REJECTED; recorded by
      one Super Admin and decided by ANOTHER (four-eyes CHECK). Never edited after the decision.
  payroll_be_decisions      owner / specialist decision per gap key: proposal, sources, linked content keys,
      decided value, status PROPOSED / DECIDED / SUPERSEDED; decided by someone other than the proposer (four-eyes
      CHECK); a later decision supersedes (linked), never overwrites.

Neither table carries an organisation: no row-level-security policy (like payroll_source_artifacts). No statutory
value appears anywhere. Literal names, lock_timeout, idempotent both ways; the downgrade drops only these two.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4c2a9d5f1"
down_revision: Union[str, Sequence[str], None] = "cf348b09db2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVIDENCE = "payroll_be_gate_evidence"
DECISIONS = "payroll_be_decisions"
GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if not _has_table(EVIDENCE):
        op.create_table(
            "payroll_be_gate_evidence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("gate", sa.String(length=2), nullable=False),
            sa.Column("evidence_type", sa.String(length=50), nullable=False),
            sa.Column("reference", sa.String(length=300), nullable=False),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.Column("source_artifact_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="PENDING"),
            sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.String(length=300), nullable=True),
            sa.CheckConstraint(f"gate IN {_in(GATES)}", name="ck_be_gate_evidence_gate"),
            sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="ck_be_gate_evidence_status"),
            sa.CheckConstraint("status = 'PENDING' OR (decided_by_id IS NOT NULL AND decided_at IS NOT NULL AND "
                               "(recorded_by_id IS NULL OR decided_by_id <> recorded_by_id))",
                               name="ck_be_gate_evidence_four_eyes"),
        )
    if not _has_index(EVIDENCE, "ix_payroll_be_gate_evidence_id"):
        op.create_index("ix_payroll_be_gate_evidence_id", "payroll_be_gate_evidence", ["id"])
    if not _has_index(EVIDENCE, "ix_be_gate_evidence_gate"):
        op.create_index("ix_be_gate_evidence_gate", "payroll_be_gate_evidence", ["gate", "evidence_type"])

    if not _has_table(DECISIONS):
        op.create_table(
            "payroll_be_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("gap_key", sa.String(length=20), nullable=False),
            sa.Column("question", sa.String(length=300), nullable=True),
            sa.Column("proposal_text", sa.Text(), nullable=False),
            sa.Column("source_references", sa.Text(), nullable=True),
            sa.Column("content_keys", sa.JSON(), nullable=True),
            sa.Column("decided_value", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="PROPOSED"),
            sa.Column("proposed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.String(length=300), nullable=True),
            sa.Column("superseded_by_id", sa.Integer(),
                      sa.ForeignKey("payroll_be_decisions.id", ondelete="SET NULL"), nullable=True),
            sa.CheckConstraint("status IN ('PROPOSED', 'DECIDED', 'SUPERSEDED')", name="ck_be_decision_status"),
            sa.CheckConstraint("status = 'PROPOSED' OR (decided_value IS NOT NULL AND decided_by_id IS NOT NULL AND "
                               "decided_at IS NOT NULL AND (proposed_by_id IS NULL OR decided_by_id <> proposed_by_id))",
                               name="ck_be_decision_four_eyes"),
            sa.CheckConstraint("status <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
                               name="ck_be_decision_superseded"),
        )
    if not _has_index(DECISIONS, "ix_payroll_be_decisions_id"):
        op.create_index("ix_payroll_be_decisions_id", "payroll_be_decisions", ["id"])
    if not _has_index(DECISIONS, "ix_be_decision_gap"):
        op.create_index("ix_be_decision_gap", "payroll_be_decisions", ["gap_key", "status"])


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (DECISIONS, EVIDENCE):
        if _has_table(table):
            op.drop_table(table)

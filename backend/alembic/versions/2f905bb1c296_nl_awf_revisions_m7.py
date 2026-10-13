"""nl_awf_revisions_m7

Netherlands (ZP-NL-ENG-001) Phase 8 — AWf retrospective revision workflow
(NL-016). A detected statutory revision situation is recorded, reviewed by a
second person and applied as an append-only correction run; historical
payroll rows are never altered.

Revision ID: 2f905bb1c296
Revises: 2ad71ebff6b5
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2f905bb1c296"
down_revision: Union[str, Sequence[str], None] = "2ad71ebff6b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "payroll_nl_awf_revisions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("contract_version_id", sa.Integer, sa.ForeignKey("payroll_nl_contract_versions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("trigger_code", sa.String(40), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("detected_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("affected_periods", json_type, nullable=False),
        sa.Column("recomputed_delta", json_type, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DETECTED"),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.CheckConstraint("status IN ('DETECTED', 'REVIEWED', 'APPLIED', 'DISMISSED')", name="ck_nl_awf_revision_status"),
        sa.UniqueConstraint("organization_id", "employee_id", "contract_version_id", "tax_year", "trigger_code",
                            name="uq_nl_awf_revision_trigger"),
    )


def downgrade() -> None:
    op.drop_table("payroll_nl_awf_revisions")

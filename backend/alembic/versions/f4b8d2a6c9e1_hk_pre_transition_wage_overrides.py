"""hk pre-transition wage overrides: controlled four-eyes correction (HK-017, gap audit D-C)

Revision ID: f4b8d2a6c9e1
Revises: e3a9c1f7b2d4
Create Date: 2026-10-14

Additive only: one new table. No existing row is read or rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4b8d2a6c9e1"
down_revision = "e3a9c1f7b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_hk_pre_transition_wage_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id"), nullable=False),
        sa.Column("monthly_wage", sa.Numeric(12, 2), nullable=False),
        sa.Column("wage_basis", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="REQUESTED"),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for col in ("id", "organization_id", "employee_id"):
        op.create_index(f"ix_payroll_hk_pre_transition_wage_overrides_{col}",
                        "payroll_hk_pre_transition_wage_overrides", [col])


def downgrade() -> None:
    for col in ("employee_id", "organization_id", "id"):
        op.drop_index(f"ix_payroll_hk_pre_transition_wage_overrides_{col}",
                      table_name="payroll_hk_pre_transition_wage_overrides")
    op.drop_table("payroll_hk_pre_transition_wage_overrides")

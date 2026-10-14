"""hk launch readiness controls: MPF account reveal permission, contribution-day disruptions, privileged-access consent

Revision ID: 8b14824fb575
Revises: 2f905bb1c296
Create Date: 2026-10-13

Additive only (no existing column changes meaning; nothing is dropped):

1. payroll_user_permissions — explicit, revocable per-user permissions granted
   by an org admin on top of the role (first use: HK_MPF_ACCOUNT_REVEAL).
2. payroll_hk_contribution_day_disruptions — operator-recorded black-rainstorm
   / No. 8+ signal days the MPF contribution-day deferral skips.
3. assisted_access_sessions — consent / break-glass columns. Server defaults
   (access_mode CONSENT, approval_status APPROVED) keep every existing session
   exactly as it was.
"""

import sqlalchemy as sa
from alembic import op

revision = "8b14824fb575"
down_revision = "2f905bb1c296"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_user_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission", sa.String(60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_payroll_user_permissions_id", "payroll_user_permissions", ["id"])
    op.create_index("ix_payroll_user_permissions_organization_id", "payroll_user_permissions", ["organization_id"])
    op.create_index("ix_payroll_user_permissions_user_perm", "payroll_user_permissions", ["user_id", "permission"])

    op.create_table(
        "payroll_hk_contribution_day_disruptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("disruption_date", sa.Date(), nullable=False, unique=True),
        sa.Column("signal", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(300), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payroll_hk_contribution_day_disruptions_id", "payroll_hk_contribution_day_disruptions", ["id"])

    op.add_column("assisted_access_sessions", sa.Column("access_mode", sa.String(20), nullable=False, server_default="CONSENT"))
    op.add_column("assisted_access_sessions", sa.Column("approval_status", sa.String(20), nullable=False, server_default="APPROVED"))
    op.add_column("assisted_access_sessions", sa.Column("requested_minutes", sa.Integer(), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("request_expires_at", sa.DateTime(), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("activated_at", sa.DateTime(), nullable=True))
    op.add_column("assisted_access_sessions", sa.Column("tenant_notified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assisted_access_sessions") as b:
        for col in ("tenant_notified_at", "activated_at", "decision_reason", "approved_at", "approved_by_user_id",
                    "request_expires_at", "requested_minutes", "approval_status", "access_mode"):
            b.drop_column(col)
    op.drop_index("ix_payroll_hk_contribution_day_disruptions_id", table_name="payroll_hk_contribution_day_disruptions")
    op.drop_table("payroll_hk_contribution_day_disruptions")
    op.drop_index("ix_payroll_user_permissions_user_perm", table_name="payroll_user_permissions")
    op.drop_index("ix_payroll_user_permissions_organization_id", table_name="payroll_user_permissions")
    op.drop_index("ix_payroll_user_permissions_id", table_name="payroll_user_permissions")
    op.drop_table("payroll_user_permissions")

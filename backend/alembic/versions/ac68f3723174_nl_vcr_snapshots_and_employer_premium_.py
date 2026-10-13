"""NL VCR snapshots and employer premium decisions M2

Revision ID: ac68f3723174
Revises: 43662178315b
Create Date: 2026-10-12 16:51:53.457129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ac68f3723174'
down_revision: Union[str, Sequence[str], None] = '43662178315b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create payroll_nl_vcr_snapshots and payroll_nl_employer_premium_decisions tables."""
    # payroll_nl_vcr_snapshots (insert-only, NL-012/NL-046)
    op.create_table(
        "payroll_nl_vcr_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, nullable=True, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("family", sa.String(20), nullable=False),  # EI / ZVW_LEVY / ZVW_CONTRIB
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("payroll_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("payslip_item_id", sa.Integer, sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("period_count", sa.Integer, nullable=False, default=0),
        sa.Column("period_max_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("cumulative_wage", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("cumulative_max", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("cumulative_base", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("base_increment", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("previous_snapshot_id", sa.Integer, sa.ForeignKey("payroll_nl_vcr_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_pack_id", sa.Integer, sa.ForeignKey("payroll_jurisdiction_packs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_correction", sa.Boolean, nullable=False, default=False, server_default="false"),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("family IN ('EI', 'ZVW_LEVY', 'ZVW_CONTRIB')", name="ck_nl_vcr_family"),
    )
    # NL-013/NL-046: one VCR series per employer entity + employee + year +
    # family; the revision is the optimistic-concurrency token. The nullable
    # income_relationship_id is NOT part of the key (NULLs are distinct in a
    # unique constraint, which would let two stale commits through).
    op.create_unique_constraint(
        "uq_nl_vcr_snapshots_org_emp_year_family_rev",
        "payroll_nl_vcr_snapshots",
        ["organization_id", "employee_id", "tax_year", "family", "revision"],
    )
    op.create_index("ix_nl_vcr_snapshots_lookup", "payroll_nl_vcr_snapshots",
                    ["organization_id", "employee_id", "tax_year", "family", "revision"])

    # payroll_nl_employer_premium_decisions (NL-015, NL-017, NL-018)
    op.create_table(
        "payroll_nl_employer_premium_decisions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("aof_size_class", sa.String(10), nullable=False),  # SMALL / LARGE
        sa.Column("aof_basis_year", sa.SmallInteger, nullable=False),  # 2024 for 2026
        sa.Column("aof_basis_premium_wage", sa.Numeric(14, 2), nullable=False),
        sa.Column("whk_wga_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("whk_wga_employee_recoverable_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("whk_zw_flex_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("sector_code", sa.String(50), nullable=True),
        sa.Column("decision_reference", sa.String(100), nullable=False),
        sa.Column("decision_date", sa.Date, nullable=False),
        sa.Column("evidence_artifact_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT"),  # DRAFT/APPROVED/ACTIVE/SUPERSEDED
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("aof_size_class IN ('SMALL', 'LARGE')", name="ck_nl_emp_prem_aof_class"),
        sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'ACTIVE', 'SUPERSEDED')", name="ck_nl_emp_prem_status"),
    )
    op.create_index("ix_nl_emp_prem_decisions_active_lookup", "payroll_nl_employer_premium_decisions",
                    ["organization_id", "tax_year", "status"],
                    postgresql_where=sa.text("status = 'ACTIVE'"))


def downgrade() -> None:
    """Drop tables."""
    op.drop_index("ix_nl_emp_prem_decisions_active_lookup", table_name="payroll_nl_employer_premium_decisions")
    op.drop_table("payroll_nl_employer_premium_decisions")
    op.drop_constraint("uq_nl_vcr_snapshots_org_emp_year_family_rev", "payroll_nl_vcr_snapshots", type_="unique")
    op.drop_index("ix_nl_vcr_snapshots_lookup", table_name="payroll_nl_vcr_snapshots")
    op.drop_table("payroll_nl_vcr_snapshots")
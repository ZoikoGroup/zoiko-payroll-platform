"""nl_labour_pay_cao_pension_termination_m6

Revision ID: 2ad71ebff6b5
Revises: 1080702411b1
Create Date: 2026-10-13 12:25:29.281620

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2ad71ebff6b5'
down_revision: Union[str, Sequence[str], None] = '1080702411b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # payroll_nl_pension_schemes — platform catalog + org overrides
    op.create_table(
        "payroll_nl_pension_schemes",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("fund_name", sa.String(200), nullable=False),
        sa.Column("scheme_code", sa.String(50), nullable=False, index=True),
        sa.Column("mandatory_sector", sa.Boolean, nullable=False, default=False),
        sa.Column("collective_agreement_id", sa.Integer, sa.ForeignKey("payroll_collective_agreements.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("franchise_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("max_pensionable_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("employee_pct", sa.Numeric(7, 4), nullable=False, default=0),
        sa.Column("employer_pct", sa.Numeric(7, 4), nullable=False, default=0),
        sa.Column("basis_rule", sa.String(30), nullable=False, default="GROSS_MINUS_FRANCHISE"),  # GROSS_MINUS_FRANCHISE / CAPPED_PENSIONABLE
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),  # ACTIVE / SUPERSEDED / ARCHIVED
        sa.Column("evidence_artifact_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("basis_rule IN ('GROSS_MINUS_FRANCHISE', 'CAPPED_PENSIONABLE')", name="ck_nl_pension_basis_rule"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')", name="ck_nl_pension_status"),
    )
    op.create_index("ix_nl_pension_org_code_eff", "payroll_nl_pension_schemes", ["organization_id", "scheme_code", "effective_from"])
    op.create_unique_constraint("uq_nl_pension_org_code_eff_from", "payroll_nl_pension_schemes", ["organization_id", "scheme_code", "effective_from"])

    # payroll_nl_absence_pay_policies (sickness pay)
    op.create_table(
        "payroll_nl_absence_pay_policies",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("waiting_days", sa.SmallInteger, nullable=False, default=0),
        sa.Column("year1_pct", sa.Numeric(5, 2), nullable=False, default=70.00),
        sa.Column("year1_min_wage_floor", sa.Boolean, nullable=False, default=True),
        sa.Column("year2_pct", sa.Numeric(5, 2), nullable=False, default=70.00),
        sa.Column("cao_enhancements", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),  # {"year1_pct_topup": 10.00, "year2_pct_topup": 5.00, "max_duration_months": 24}
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_nl_absence_policy_org_eff", "payroll_nl_absence_pay_policies", ["organization_id", "effective_from"])

    # payroll_nl_sickness_events
    op.create_table(
        "payroll_nl_sickness_events",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("first_sick_day", sa.Date, nullable=False, index=True),
        sa.Column("recovery_date", sa.Date, nullable=True, index=True),
        sa.Column("policy_id", sa.Integer, sa.ForeignKey("payroll_nl_absence_pay_policies.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),  # ACTIVE / RECOVERED / TERMINATED
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'RECOVERED', 'TERMINATED')", name="ck_nl_sickness_status"),
    )
    op.create_index("ix_nl_sickness_org_emp_date", "payroll_nl_sickness_events", ["organization_id", "employee_id", "first_sick_day"])

    # payroll_nl_termination_settlements
    op.create_table(
        "payroll_nl_termination_settlements",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, sa.ForeignKey("payroll_nl_income_relationships.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("termination_date", sa.Date, nullable=False, index=True),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("initiated_by", sa.String(50), nullable=False),  # EMPLOYER / EMPLOYEE / MUTUAL
        sa.Column("transition_payment_eligible", sa.Boolean, nullable=False, default=True),
        sa.Column("service_months", sa.SmallInteger, nullable=False, default=0),
        sa.Column("monthly_salary_basis", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("transition_payment_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("cap_applied", sa.Boolean, nullable=False, default=False),
        sa.Column("unused_leave_hours", sa.Numeric(7, 2), nullable=False, default=0),
        sa.Column("leave_payout", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("vacation_allowance_payout", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("tax_treatment", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),  # {"transition_exempt": 89000, "transition_taxable": 0, "leave_exempt": 0, "leave_taxable": 0, "vacation_exempt": 0, "vacation_taxable": 0}
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT"),  # DRAFT / APPROVED / PAID
        sa.Column("prepared_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("initiated_by IN ('EMPLOYER', 'EMPLOYEE', 'MUTUAL')", name="ck_nl_term_initiated_by"),
        sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'PAID')", name="ck_nl_term_status"),
    )
    op.create_index("ix_nl_term_org_emp_date", "payroll_nl_termination_settlements", ["organization_id", "employee_id", "termination_date"])

    # Note: CAO data reuses existing payroll_collective_agreements table with country='NL'
    # Links:
    # - payroll_nl_pension_schemes.collective_agreement_id -> payroll_collective_agreements.id
    # - payroll_nl_employer_profiles.collective_agreement_id (already in M3)
    # - payroll_nl_absence_pay_policies.cao_enhancements (JSON) references CAO clauses


def downgrade() -> None:
    """Downgrade schema (children before the tables they reference)."""
    op.drop_index("ix_nl_term_org_emp_date", table_name="payroll_nl_termination_settlements")
    op.drop_table("payroll_nl_termination_settlements")
    op.drop_index("ix_nl_sickness_org_emp_date", table_name="payroll_nl_sickness_events")
    op.drop_table("payroll_nl_sickness_events")
    op.drop_index("ix_nl_absence_policy_org_eff", table_name="payroll_nl_absence_pay_policies")
    op.drop_table("payroll_nl_absence_pay_policies")
    op.drop_constraint("uq_nl_pension_org_code_eff_from", "payroll_nl_pension_schemes", type_="unique")
    op.drop_index("ix_nl_pension_org_code_eff", table_name="payroll_nl_pension_schemes")
    op.drop_table("payroll_nl_pension_schemes")

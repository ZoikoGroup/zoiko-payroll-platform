"""nl_earnings_classification_vacation_wkr_car_expat_m5

Revision ID: 1080702411b1
Revises: 972ecd8c1dba
Create Date: 2026-10-13 11:05:43.327874

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1080702411b1'
down_revision: Union[str, Sequence[str], None] = '972ecd8c1dba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # payroll_nl_earning_classifications — platform catalog + org overrides
    op.create_table(
        "payroll_nl_earning_classifications",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("earning_code", sa.String(50), nullable=False, index=True),
        sa.Column("remuneration_type", sa.String(20), nullable=False),  # REGULAR / SPECIAL
        sa.Column("wage_tax", sa.Boolean, nullable=False, default=True),
        sa.Column("employee_insurance_wage", sa.Boolean, nullable=False, default=True),
        sa.Column("zvw_wage", sa.Boolean, nullable=False, default=True),
        sa.Column("pensionable", sa.Boolean, nullable=False, default=True),
        sa.Column("wkr_treatment", sa.String(40), nullable=False, default="WAGE"),  # WAGE / TARGETED_EXEMPTION / ZERO_VALUATION / FINAL_LEVY_DESIGNATED / N_A
        sa.Column("vacation_allowance_basis", sa.Boolean, nullable=False, default=True),
        sa.Column("minimum_wage_reckonable", sa.Boolean, nullable=False, default=True),
        sa.Column("evidence_policy", sa.String(20), nullable=False, default="NONE"),  # NONE / RECEIPT / DECLARATION / BOTH
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),  # ACTIVE / SUPERSEDED / ARCHIVED
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("remuneration_type IN ('REGULAR', 'SPECIAL')", name="ck_nl_earn_rem_type"),
        sa.CheckConstraint("wkr_treatment IN ('WAGE', 'TARGETED_EXEMPTION', 'ZERO_VALUATION', 'FINAL_LEVY_DESIGNATED', 'N_A')", name="ck_nl_earn_wkr_treatment"),
        sa.CheckConstraint("evidence_policy IN ('NONE', 'RECEIPT', 'DECLARATION', 'BOTH')", name="ck_nl_earn_evidence"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')", name="ck_nl_earn_status"),
    )
    op.create_index("ix_nl_earn_org_code_eff", "payroll_nl_earning_classifications", ["organization_id", "earning_code", "effective_from"])
    op.create_unique_constraint("uq_nl_earn_org_code_eff_from", "payroll_nl_earning_classifications", ["organization_id", "earning_code", "effective_from"])

    # payroll_nl_vacation_allowance_ledger (insert-only)
    op.create_table(
        "payroll_nl_vacation_allowance_ledger",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, sa.ForeignKey("payroll_nl_income_relationships.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("accrual_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("period", sa.String(20), nullable=False),  # MONTH / FOUR_WEEK / WEEK / QUARTER
        sa.Column("entry_type", sa.String(20), nullable=False),  # ACCRUAL / PAYOUT / CORRECTION
        sa.Column("basis_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("pct", sa.Numeric(5, 2), nullable=False, default=8.00),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("payroll_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("payslip_item_id", sa.Integer, sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("entry_type IN ('ACCRUAL', 'PAYOUT', 'CORRECTION')", name="ck_nl_vac_entry_type"),
    )
    op.create_index("ix_nl_vac_org_emp_year", "payroll_nl_vacation_allowance_ledger", ["organization_id", "employee_id", "accrual_year"])

    # payroll_nl_wkr_accumulators (insert-only revisions)
    op.create_table(
        "payroll_nl_wkr_accumulators",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("concern_id", sa.Integer, nullable=True, index=True),  # NULL = standalone
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("fiscal_wage_cumulative", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("free_space_available", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("designated_wage_cumulative", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("targeted_exemptions_cumulative", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("excess_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("excess_levy_80", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("payroll_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_nl_wkr_acc_org_concern_year_rev", "payroll_nl_wkr_accumulators", ["organization_id", "concern_id", "tax_year", "revision"])
    # NULLs are distinct in the constraint above, so a standalone employer
    # (concern_id NULL) needs its own key or two stale commits could both land (NL-046).
    op.create_index("uq_nl_wkr_acc_standalone_year_rev", "payroll_nl_wkr_accumulators",
                    ["organization_id", "tax_year", "revision"], unique=True,
                    postgresql_where=sa.text("concern_id IS NULL"),
                    sqlite_where=sa.text("concern_id IS NULL"))

    # payroll_nl_wkr_concerns
    op.create_table(
        "payroll_nl_wkr_concerns",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("parent_organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("member_org_ids", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("eligibility_evidence_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),  # ACTIVE / DISSOLVED
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISSOLVED')", name="ck_nl_wkr_concern_status"),
    )
    op.create_unique_constraint("uq_nl_wkr_concern_parent_year", "payroll_nl_wkr_concerns", ["parent_organization_id", "tax_year"])

    # payroll_nl_wkr_settlements
    op.create_table(
        "payroll_nl_wkr_settlements",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("concern_id", sa.Integer, nullable=True, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("excess_levy_amount", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("target_return_period", sa.String(20), nullable=False),  # second period of next year
        # Plain integer until the loonaangifte return table exists (Phase 9).
        sa.Column("loonaangifte_return_id", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="PENDING"),  # PENDING / FILED / ASSESSED
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'FILED', 'ASSESSED')", name="ck_nl_wkr_settlement_status"),
    )

    # payroll_nl_company_cars
    op.create_table(
        "payroll_nl_company_cars",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("plate_masked", sa.String(20), nullable=True),  # masked for privacy
        sa.Column("catalog_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("first_admission_date", sa.Date, nullable=False),
        sa.Column("vehicle_class", sa.String(20), nullable=True),  # A / B / C / etc. or CO2 class
        sa.Column("co2_class", sa.String(20), nullable=True),
        sa.Column("addition_rate_window_key", sa.String(50), nullable=False, index=True),  # key into NL_CAR_ADDITION content
        sa.Column("private_use_status", sa.String(20), nullable=False, default="PRIVATE"),  # PRIVATE / NO_PRIVATE_USE_500KM
        sa.Column("no_private_use_evidence_ref", sa.String(200), nullable=True),
        sa.Column("employee_own_contribution", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),  # ACTIVE / RETURNED / SOLD
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("private_use_status IN ('PRIVATE', 'NO_PRIVATE_USE_500KM')", name="ck_nl_car_private_use"),
        sa.CheckConstraint("status IN ('ACTIVE', 'RETURNED', 'SOLD')", name="ck_nl_car_status"),
    )

    # payroll_nl_expat_decisions
    op.create_table(
        "payroll_nl_expat_decisions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("decision_reference", sa.String(100), nullable=False),
        sa.Column("decision_date", sa.Date, nullable=False),
        sa.Column("granted_from", sa.Date, nullable=False, index=True),
        sa.Column("granted_to", sa.Date, nullable=True, index=True),
        sa.Column("method", sa.String(30), nullable=False),  # FACILITY_30PCT / ACTUAL_ET_COSTS
        sa.Column("threshold_category", sa.String(30), nullable=False),  # STANDARD / UNDER30_MASTER / RESEARCH_MEDICAL
        sa.Column("allowance_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("evidence_artifact_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="PENDING"),  # PENDING / VERIFIED / REVOKED / EXPIRED
        sa.Column("verified_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("method IN ('FACILITY_30PCT', 'ACTUAL_ET_COSTS')", name="ck_nl_expat_method"),
        sa.CheckConstraint("threshold_category IN ('STANDARD', 'UNDER30_MASTER', 'RESEARCH_MEDICAL')", name="ck_nl_expat_threshold"),
        sa.CheckConstraint("status IN ('PENDING', 'VERIFIED', 'REVOKED', 'EXPIRED')", name="ck_nl_expat_status"),
    )
    op.create_unique_constraint("uq_nl_expat_org_emp_granted", "payroll_nl_expat_decisions", ["organization_id", "employee_id", "granted_from"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_nl_expat_org_emp_granted", "payroll_nl_expat_decisions", type_="unique")
    op.drop_table("payroll_nl_expat_decisions")
    op.drop_table("payroll_nl_company_cars")
    op.drop_table("payroll_nl_wkr_settlements")
    op.drop_constraint("uq_nl_wkr_concern_parent_year", "payroll_nl_wkr_concerns", type_="unique")
    op.drop_table("payroll_nl_wkr_concerns")
    op.drop_index("uq_nl_wkr_acc_standalone_year_rev", table_name="payroll_nl_wkr_accumulators")
    op.drop_constraint("uq_nl_wkr_acc_org_concern_year_rev", "payroll_nl_wkr_accumulators", type_="unique")
    op.drop_table("payroll_nl_wkr_accumulators")
    op.drop_table("payroll_nl_vacation_allowance_ledger")
    op.drop_constraint("uq_nl_earn_org_code_eff_from", "payroll_nl_earning_classifications", type_="unique")
    op.drop_index("ix_nl_earn_org_code_eff", table_name="payroll_nl_earning_classifications")
    op.drop_table("payroll_nl_earning_classifications")

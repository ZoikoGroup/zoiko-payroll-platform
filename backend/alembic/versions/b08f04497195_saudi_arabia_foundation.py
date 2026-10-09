"""saudi_arabia_foundation

Revision ID: b08f04497195
Revises: 6b5a4c3d2e1f
Create Date: 2026-10-08

Saudi Arabia (SA) jurisdiction foundation — one additive migration.
Adds sa_* columns to EmployeeStatutoryProfile, sa_calculation_snapshot and
employer_occupational_hazard to PayslipItem, and seven new SA-specific tables:
payroll_sa_employer_profiles, payroll_sa_contract_versions,
payroll_sa_gosi_liabilities, payroll_sa_wps_files, payroll_sa_wps_observations,
payroll_sa_final_settlements, payroll_sa_eos_ledger_entries.

All new columns/tables are nullable or have safe defaults — existing rows
are unaffected. The registry row in billing.JurisdictionServiceRegistry for
"SA" stays PLANNED; this migration only provides the schema.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b08f04497195"
down_revision = "6b5a4c3d2e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1) EmployeeStatutoryProfile: add ~20 sa_* columns ─────────────────
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_worker_class", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_cohort", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_cohort_evidence_ref", sa.String(200), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_cohort_source_document_id", sa.Integer, sa.ForeignKey("payroll_source_artifacts.id"), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_cohort_verified_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_cohort_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_identity_document_type", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_identity_token", sa.String(80), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_identity_expiry", sa.Date, nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_gosi_registration_status", sa.String(30), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_gosi_registration_date", sa.Date, nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_gosi_registration_token", sa.String(80), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_contributory_wage", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_contributory_wage_effective_from", sa.Date, nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_contributory_wage_gosi_ref", sa.String(100), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_in_kind_housing_value", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_contract_type", sa.String(30), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_occupation", sa.String(100), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_special_category", sa.String(50), nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_reduced_ramadan_hours", sa.Boolean, nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_service_start_date", sa.Date, nullable=True),
    )
    op.add_column(
        "payroll_employee_statutory_profiles",
        sa.Column("sa_eos_exclusions", sa.Text, nullable=True),
    )

    # ── 2) PayslipItem: sa_calculation_snapshot + employer_occupational_hazard ──
    op.add_column(
        "payslip_items",
        sa.Column("sa_calculation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "payslip_items",
        sa.Column("employer_occupational_hazard", sa.Numeric(12, 2), default=0, server_default="0"),
    )

    # ── 3) New SA-specific tables ───────────────────────────────────────────

    # 3a) payroll_sa_employer_profiles (versioned per org)
    op.create_table(
        "payroll_sa_employer_profiles",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("gosi_employer_code", sa.String(50), nullable=False),
        sa.Column("branch_code", sa.String(50), nullable=True),
        sa.Column("activity_code", sa.String(50), nullable=True),
        sa.Column("risk_category", sa.String(30), nullable=True),
        sa.Column("occupational_hazard_rate_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("saned_employer_rate_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("pension_employer_rate_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT", server_default="DRAFT"),
        sa.Column("authority_source_id", sa.Integer, sa.ForeignKey("payroll_source_artifacts.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("previous_version_id", sa.Integer, sa.ForeignKey("payroll_sa_employer_profiles.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_employer_profile_org_period", "payroll_sa_employer_profiles", ["organization_id", "effective_from"])
    op.create_index(
        "uq_sa_employer_profile_one_open",
        "payroll_sa_employer_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
        sqlite_where=sa.text("effective_to IS NULL"),
    )

    # 3b) payroll_sa_contract_versions (versioned per employee)
    op.create_table(
        "payroll_sa_contract_versions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("contract_type", sa.String(30), nullable=False),
        sa.Column("occupation", sa.String(100), nullable=True),
        sa.Column("basic_wage", sa.Numeric(14, 2), nullable=True),
        sa.Column("housing_allowance", sa.Numeric(14, 2), nullable=True),
        sa.Column("transport_allowance", sa.Numeric(14, 2), nullable=True),
        sa.Column("other_allowances", sa.Numeric(14, 2), nullable=True),
        sa.Column("in_kind_housing_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("probation_end_date", sa.Date, nullable=True),
        sa.Column("contract_end_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT", server_default="DRAFT"),
        sa.Column("authority_source_id", sa.Integer, sa.ForeignKey("payroll_source_artifacts.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("previous_version_id", sa.Integer, sa.ForeignKey("payroll_sa_contract_versions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_contract_version_emp_period", "payroll_sa_contract_versions", ["employee_id", "effective_from"])
    op.create_index(
        "uq_sa_contract_version_one_open",
        "payroll_sa_contract_versions",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
        sqlite_where=sa.text("effective_to IS NULL"),
    )

    # 3c) payroll_sa_gosi_liabilities (one row per employer per month)
    op.create_table(
        "payroll_sa_gosi_liabilities",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("contribution_month", sa.Date, nullable=False, index=True),
        sa.Column("total_wages", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("contributory_wages", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("pension_employee", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("pension_employer", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("saned_employee", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("saned_employer", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("occupational_hazard_employer", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("total_due", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT", server_default="DRAFT"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(100), nullable=True),
        sa.Column("source_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_gosi_liability_org_month", "payroll_sa_gosi_liabilities", ["organization_id", "contribution_month"], unique=True)

    # 3d) payroll_sa_wps_files (SIE file submissions)
    op.create_table(
        "payroll_sa_wps_files",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("payroll_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id"), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("employee_count", sa.Integer, default=0, server_default="0"),
        sa.Column("total_amount", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, default="UPLOADED", server_default="UPLOADED"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_wps_file_org_date", "payroll_sa_wps_files", ["organization_id", "created_at"])
    op.create_index("uq_sa_wps_file_sha256", "payroll_sa_wps_files", ["file_sha256"], unique=True)

    # 3e) payroll_sa_wps_observations (per-employee SIE observations)
    op.create_table(
        "payroll_sa_wps_observations",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("wps_file_id", sa.Integer, sa.ForeignKey("payroll_sa_wps_files.id"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id"), nullable=False, index=True),
        sa.Column("observation_code", sa.String(20), nullable=False),
        sa.Column("observation_description", sa.Text, nullable=True),
        sa.Column("expected_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("reported_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("resolved", sa.Boolean, default=False, server_default="0"),
        sa.Column("resolved_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sa_wps_obs_file_emp", "payroll_sa_wps_observations", ["wps_file_id", "employee_id"])

    # 3f) payroll_sa_final_settlements (termination/resignation settlement)
    op.create_table(
        "payroll_sa_final_settlements",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("termination_date", sa.Date, nullable=False),
        sa.Column("termination_type", sa.String(20), nullable=False),
        sa.Column("notice_given", sa.Boolean, default=False, server_default="0"),
        sa.Column("notice_period_days", sa.Integer, nullable=True),
        sa.Column("eos_award", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("unused_leave_days", sa.Integer, default=0, server_default="0"),
        sa.Column("unused_leave_pay", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("notice_pay", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("repatriation_pay", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("other_dues", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("total_due", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("deductions", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("net_payable", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("deadline_date", sa.Date, nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT", server_default="DRAFT"),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_final_settlement_emp", "payroll_sa_final_settlements", ["employee_id", "termination_date"])

    # 3g) payroll_sa_eos_ledger_entries (EOS accrual per employee per period)
    op.create_table(
        "payroll_sa_eos_ledger_entries",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("period_from", sa.Date, nullable=False, index=True),
        sa.Column("period_to", sa.Date, nullable=False),
        sa.Column("basic_wage", sa.Numeric(14, 2), nullable=False),
        sa.Column("housing_allowance", sa.Numeric(14, 2), default=0, server_default="0"),
        sa.Column("eos_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("days_worked", sa.Integer, nullable=False),
        sa.Column("accrual_months", sa.Numeric(6, 4), nullable=False),
        sa.Column("eos_award_accrued", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("cumulative_award", sa.Numeric(16, 2), default=0, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, default="ACCRUED", server_default="ACCRUED"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_sa_eos_ledger_emp_period", "payroll_sa_eos_ledger_entries", ["employee_id", "period_from", "period_to"], unique=True)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("payroll_sa_eos_ledger_entries")
    op.drop_table("payroll_sa_final_settlements")
    op.drop_table("payroll_sa_wps_observations")
    op.drop_table("payroll_sa_wps_files")
    op.drop_table("payroll_sa_gosi_liabilities")
    op.drop_table("payroll_sa_contract_versions")
    op.drop_table("payroll_sa_employer_profiles")

    # Drop PayslipItem columns
    op.drop_column("payslip_items", "employer_occupational_hazard")
    op.drop_column("payslip_items", "sa_calculation_snapshot")

    # Drop EmployeeStatutoryProfile columns
    op.drop_column("payroll_employee_statutory_profiles", "sa_eos_exclusions")
    op.drop_column("payroll_employee_statutory_profiles", "sa_service_start_date")
    op.drop_column("payroll_employee_statutory_profiles", "sa_reduced_ramadan_hours")
    op.drop_column("payroll_employee_statutory_profiles", "sa_special_category")
    op.drop_column("payroll_employee_statutory_profiles", "sa_occupation")
    op.drop_column("payroll_employee_statutory_profiles", "sa_contract_type")
    op.drop_column("payroll_employee_statutory_profiles", "sa_in_kind_housing_value")
    op.drop_column("payroll_employee_statutory_profiles", "sa_contributory_wage_gosi_ref")
    op.drop_column("payroll_employee_statutory_profiles", "sa_contributory_wage_effective_from")
    op.drop_column("payroll_employee_statutory_profiles", "sa_contributory_wage")
    op.drop_column("payroll_employee_statutory_profiles", "sa_gosi_registration_token")
    op.drop_column("payroll_employee_statutory_profiles", "sa_gosi_registration_date")
    op.drop_column("payroll_employee_statutory_profiles", "sa_gosi_registration_status")
    op.drop_column("payroll_employee_statutory_profiles", "sa_identity_expiry")
    op.drop_column("payroll_employee_statutory_profiles", "sa_identity_token")
    op.drop_column("payroll_employee_statutory_profiles", "sa_identity_document_type")
    op.drop_column("payroll_employee_statutory_profiles", "sa_cohort_verified_at")
    op.drop_column("payroll_employee_statutory_profiles", "sa_cohort_verified_by_id")
    op.drop_column("payroll_employee_statutory_profiles", "sa_cohort_source_document_id")
    op.drop_column("payroll_employee_statutory_profiles", "sa_cohort_evidence_ref")
    op.drop_column("payroll_employee_statutory_profiles", "sa_cohort")
    op.drop_column("payroll_employee_statutory_profiles", "sa_worker_class")
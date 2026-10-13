"""NL employer profiles, income relationships, tax credit instructions, contract versions M3

Revision ID: 774eeaf9b33c
Revises: ac68f3723174
Create Date: 2026-10-12 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '774eeaf9b33c'
down_revision: Union[str, Sequence[str], None] = 'ac68f3723174'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payroll_nl_employer_profiles (versioned, immutable, like ChEntityProfile)
    op.create_table(
        "payroll_nl_employer_profiles",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False, default=1),
        sa.Column("previous_version_id", sa.Integer, sa.ForeignKey("payroll_nl_employer_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("kvk_number", sa.String(20), nullable=True),
        sa.Column("rsin", sa.String(20), nullable=True),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("payroll_contact", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("loonheffingennummer", sa.String(50), nullable=True),
        sa.Column("loonheffingen_subnumber", sa.String(50), nullable=True),
        sa.Column("registration_letter_ref", sa.String(100), nullable=True),
        sa.Column("registration_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_verified_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("return_period", sa.String(20), nullable=False, default="MONTH"),  # MONTH / FOUR_WEEK
        sa.Column("payroll_schedule", sa.String(20), nullable=False, default="MONTH"),  # MONTH / FOUR_WEEK / WEEK
        sa.Column("standard_pay_day", sa.SmallInteger, nullable=True),  # 1-31
        sa.Column("bank_lead_days", sa.SmallInteger, nullable=False, default=2),
        sa.Column("bank_iban_token", sa.String(100), nullable=True),  # tokenized, not raw IBAN
        sa.Column("bank_bic", sa.String(20), nullable=True),
        sa.Column("pki_cert_ref", sa.String(200), nullable=True),  # reference only, no private key
        sa.Column("pki_cert_fingerprint", sa.String(100), nullable=True),
        sa.Column("pki_cert_issuer", sa.String(200), nullable=True),
        sa.Column("pki_cert_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("digipoort_channel", sa.String(50), nullable=True),
        sa.Column("digipoort_test_status", sa.String(20), nullable=True),
        sa.Column("digipoort_test_evidence_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cao_status", sa.String(20), nullable=False, default="NONE"),  # NONE / APPLICABLE / UNKNOWN
        sa.Column("collective_agreement_id", sa.Integer, sa.ForeignKey("payroll_collective_agreements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pension_status", sa.String(20), nullable=True),
        sa.Column("wkr_mode", sa.String(20), nullable=False, default="STANDALONE"),  # STANDALONE / CONCERN
        sa.Column("wkr_concern_id", sa.Integer, nullable=True),
        sa.Column("readiness_status", sa.String(20), nullable=False, default="INCOMPLETE"),
        sa.Column("readiness_evidence", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("return_period IN ('MONTH', 'FOUR_WEEK')", name="ck_nl_emp_return_period"),
        sa.CheckConstraint("payroll_schedule IN ('MONTH', 'FOUR_WEEK', 'WEEK')", name="ck_nl_emp_payroll_schedule"),
        sa.CheckConstraint("cao_status IN ('NONE', 'APPLICABLE', 'UNKNOWN')", name="ck_nl_emp_cao_status"),
        sa.CheckConstraint("wkr_mode IN ('STANDALONE', 'CONCERN')", name="ck_nl_emp_wkr_mode"),
        sa.CheckConstraint("standard_pay_day IS NULL OR (standard_pay_day >= 1 AND standard_pay_day <= 31)", name="ck_nl_emp_pay_day"),
    )
    # Only one open row per organization
    op.create_index(
        "ix_nl_employer_profiles_org_open",
        "payroll_nl_employer_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    # payroll_nl_income_relationships
    op.create_table(
        "payroll_nl_income_relationships",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ikv_number", sa.String(50), nullable=False),  # set once, never regenerated
        sa.Column("income_relation_code", sa.String(10), nullable=False),
        sa.Column("payroll_period", sa.String(20), nullable=False),  # MONTH / FOUR_WEEK / WEEK
        sa.Column("start_date", sa.Date, nullable=False, index=True),
        sa.Column("end_date", sa.Date, nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),
        sa.Column("closed_reason", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_nl_ikv_status"),
    )
    op.create_unique_constraint(
        "uq_nl_ikv_org_emp_ikv",
        "payroll_nl_income_relationships",
        ["organization_id", "employee_id", "ikv_number"],
    )

    # payroll_nl_tax_credit_instructions (insert-only)
    op.create_table(
        "payroll_nl_tax_credit_instructions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("apply_tax_credit", sa.Boolean, nullable=False, default=True),
        sa.Column("form_version", sa.String(50), nullable=False, default="Model opgaaf 2026-08"),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("signed_document_artifact_id", sa.Integer, sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("captured_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("superseded_by_id", sa.Integer, sa.ForeignKey("payroll_nl_tax_credit_instructions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_nl_tax_credit_org_emp_effective",
        "payroll_nl_tax_credit_instructions",
        ["organization_id", "employee_id", "effective_from"],
    )

    # payroll_nl_contract_versions
    op.create_table(
        "payroll_nl_contract_versions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, sa.ForeignKey("payroll_nl_income_relationships.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("previous_version_id", sa.Integer, sa.ForeignKey("payroll_nl_contract_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contract_term", sa.String(20), nullable=False),  # INDEFINITE / FIXED
        sa.Column("written_record", sa.Boolean, nullable=False, default=False),
        sa.Column("written_evidence_ref", sa.String(200), nullable=True),
        sa.Column("on_call", sa.Boolean, nullable=False, default=False),
        sa.Column("agreed_hours_per_week", sa.Numeric(5, 2), nullable=True),
        sa.Column("statutory_exception_code", sa.String(20), nullable=True),
        sa.Column("start_date", sa.Date, nullable=False, index=True),
        sa.Column("end_date", sa.Date, nullable=True, index=True),
        sa.Column("derived_awf_class", sa.String(10), nullable=True),  # LOW / HIGH
        sa.Column("awf_derivation_reason", sa.String(200), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("contract_term IN ('INDEFINITE', 'FIXED')", name="ck_nl_contract_term"),
        sa.CheckConstraint("derived_awf_class IS NULL OR derived_awf_class IN ('LOW', 'HIGH')", name="ck_nl_contract_awf_class"),
    )

    # payroll_nl_idempotency_records (for netherlands_http.py)
    op.create_table(
        "payroll_nl_idempotency_records",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.SmallInteger, nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # New columns on payroll_employee_statutory_profiles
    with op.batch_alter_table("payroll_employee_statutory_profiles") as batch:
        batch.add_column(sa.Column("nl_bsn_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("nl_identity_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("nl_residence_country", sa.String(2), nullable=True))
        batch.add_column(sa.Column("nl_residence_variant", sa.String(20), nullable=True))
        batch.add_column(sa.Column("nl_table_color", sa.String(10), nullable=True))
        batch.add_column(sa.Column("nl_zvw_path", sa.String(20), nullable=True))
        batch.add_column(sa.Column("nl_ei_insured", sa.Boolean, nullable=True))
        batch.add_column(sa.Column("nl_insurance_exception_code", sa.String(20), nullable=True))
        batch.add_column(sa.Column("nl_insurance_evidence_ref", sa.String(200), nullable=True))
        batch.add_column(sa.Column("nl_cross_border_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("nl_a1_reference", sa.String(100), nullable=True))
        # Plain integer: payroll_nl_pension_schemes is created later (M6).
        batch.add_column(sa.Column("nl_pension_scheme_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("nl_voluntary_extra_withholding", sa.Numeric(14, 2), nullable=True))
        batch.add_column(sa.Column("nl_vacation_allowance_pct", sa.Numeric(5, 2), nullable=True))
        batch.add_column(sa.Column("nl_contract_hours_per_week", sa.Numeric(5, 2), nullable=True))
        batch.add_column(sa.Column("nl_personnel_number", sa.String(50), nullable=True))


def downgrade() -> None:
    # Remove columns from payroll_employee_statutory_profiles
    with op.batch_alter_table("payroll_employee_statutory_profiles") as batch:
        batch.drop_column("nl_personnel_number")
        batch.drop_column("nl_contract_hours_per_week")
        batch.drop_column("nl_vacation_allowance_pct")
        batch.drop_column("nl_voluntary_extra_withholding")
        batch.drop_column("nl_pension_scheme_id")
        batch.drop_column("nl_a1_reference")
        batch.drop_column("nl_cross_border_status")
        batch.drop_column("nl_insurance_evidence_ref")
        batch.drop_column("nl_insurance_exception_code")
        batch.drop_column("nl_ei_insured")
        batch.drop_column("nl_zvw_path")
        batch.drop_column("nl_table_color")
        batch.drop_column("nl_residence_variant")
        batch.drop_column("nl_residence_country")
        batch.drop_column("nl_identity_status")
        batch.drop_column("nl_bsn_verified_at")

    # Drop tables
    op.drop_table("payroll_nl_idempotency_records")
    op.drop_table("payroll_nl_contract_versions")
    op.drop_table("payroll_nl_tax_credit_instructions")
    op.drop_table("payroll_nl_income_relationships")
    op.drop_table("payroll_nl_employer_profiles")
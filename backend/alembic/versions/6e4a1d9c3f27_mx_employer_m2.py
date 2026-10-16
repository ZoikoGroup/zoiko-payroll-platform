"""mx_employer_m2: Mexico employer onboarding — legal employers, establishments, IMSS registrations,
work-risk premiums, state ISN registrations, labour policies and credential references

Revision ID: 6e4a1d9c3f27
Revises: 5d2c8f1a7b3e
Create Date: 2026-10-16

ZP-MX-ENG-001 Phase 3 (spec §11 panels A–H; docs/mexico/MEXICO_PHASE_3_PLAN.md):
  - payroll_mx_employer_profiles   versioned legal employer (RFC chain), one open row per (org, RFC)
  - payroll_mx_imss_registrations  several per employer (MX-002), one open row per (org, Registro Patronal)
  - payroll_mx_establishments      workplaces; minimum-wage zone derived from content, not stored
  - payroll_mx_risk_premiums       registration-scoped premium per period (MX-024/MX-026)
  - payroll_mx_isn_registrations   state ISN registration, in-scope states only (MX-045)
  - payroll_mx_labor_policies      workweek + benefits, checked against statutory floors (MX-051)
  - payroll_mx_credential_refs     gcp-sm:// references + certificate metadata ONLY — never a secret (MX-035)

Partial unique indexes guard the open/ACTIVE row wherever effective_to or
status is nullable/historical (NULL != NULL in a plain UNIQUE), with
sqlite_where mirroring postgresql_where, as ContributionRate.

Additive only: seven new tables; no existing row or column is touched.
Idempotent: every create is skipped when its object exists, every drop when it is gone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6e4a1d9c3f27"
down_revision: Union[str, Sequence[str], None] = "5d2c8f1a7b3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("payroll_mx_credential_refs", "payroll_mx_labor_policies", "payroll_mx_isn_registrations",
           "payroll_mx_risk_premiums", "payroll_mx_establishments", "payroll_mx_imss_registrations",
           "payroll_mx_employer_profiles")


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False, where=None):
    if _has_index(table, name):
        return
    kw = {}
    if where is not None:
        kw = {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}
    op.create_index(name, table, cols, unique=unique, **kw)


def _stamps():
    return [sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    t = "payroll_mx_employer_profiles"
    if not _has_table("payroll_mx_employer_profiles"):
        op.create_table(
            "payroll_mx_employer_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("previous_version_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("taxpayer_type", sa.String(10), nullable=False),
            sa.Column("rfc", sa.String(13), nullable=False),
            sa.Column("legal_name", sa.String(300), nullable=False),
            sa.Column("fiscal_regime_code", sa.String(10), nullable=False),
            sa.Column("fiscal_postal_code", sa.String(5), nullable=False),
            sa.Column("fiscal_address", sa.JSON(), nullable=True),
            sa.Column("place_of_issue_postal_code", sa.String(5), nullable=False),
            sa.Column("withholding_obligation_active", sa.Boolean(), nullable=False),
            sa.Column("tax_contact", sa.JSON(), nullable=True),
            sa.Column("bank_contact", sa.JSON(), nullable=True),
            sa.Column("pac_provider", sa.String(100), nullable=True),
            sa.Column("pac_environment", sa.String(12), nullable=True),
            sa.Column("stamp_test_status", sa.String(12), nullable=False),
            sa.Column("stamp_test_uuid", sa.String(40), nullable=True),
            sa.Column("stamp_tested_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
            sa.CheckConstraint("taxpayer_type IN ('MORAL', 'FISICA')", name="ck_mx_employer_taxpayer"),
            sa.CheckConstraint("pac_environment IS NULL OR pac_environment IN ('SANDBOX', 'PRODUCTION')",
                               name="ck_mx_employer_pac_env"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_employer_window"),
            sa.UniqueConstraint("organization_id", "rfc", "effective_from", name="uq_mx_employer_org_rfc_from"),
        )
    _index(t, "ix_payroll_mx_employer_profiles_id", ["id"])
    _index(t, "ix_payroll_mx_employer_profiles_organization_id", ["organization_id"])
    _index(t, "uq_mx_employer_org_rfc_open", ["organization_id", "rfc"], unique=True, where="effective_to IS NULL")

    t = "payroll_mx_imss_registrations"
    if not _has_table("payroll_mx_imss_registrations"):
        op.create_table(
            "payroll_mx_imss_registrations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("registro_patronal", sa.String(11), nullable=False),
            sa.Column("risk_class", sa.String(10), nullable=False),
            sa.Column("fraction", sa.String(10), nullable=False),
            sa.Column("subdelegation_code", sa.String(20), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("infonavit_operating_model", sa.String(10), nullable=True),
            *_stamps(),
            sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_mx_imss_status"),
            sa.CheckConstraint("infonavit_operating_model IS NULL OR infonavit_operating_model IN ('SUA', 'SIPARE')",
                               name="ck_mx_imss_infonavit_model"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_imss_window"),
            sa.UniqueConstraint("organization_id", "registro_patronal", "effective_from", name="uq_mx_imss_org_rp_from"),
        )
    _index(t, "ix_payroll_mx_imss_registrations_id", ["id"])
    _index(t, "ix_payroll_mx_imss_registrations_organization_id", ["organization_id"])
    _index(t, "ix_payroll_mx_imss_registrations_employer_profile_id", ["employer_profile_id"])
    _index(t, "uq_mx_imss_org_rp_open", ["organization_id", "registro_patronal"], unique=True,
           where="effective_to IS NULL")

    t = "payroll_mx_establishments"
    if not _has_table("payroll_mx_establishments"):
        op.create_table(
            "payroll_mx_establishments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("state_code", sa.String(5), nullable=False),
            sa.Column("municipality", sa.String(200), nullable=False),
            sa.Column("municipality_code", sa.String(10), nullable=True),
            sa.Column("postal_code", sa.String(5), nullable=False),
            sa.Column("imss_registration_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_imss_registrations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            *_stamps(),
        )
    _index(t, "ix_payroll_mx_establishments_id", ["id"])
    _index(t, "ix_payroll_mx_establishments_organization_id", ["organization_id"])
    _index(t, "ix_payroll_mx_establishments_employer_profile_id", ["employer_profile_id"])
    _index(t, "ix_payroll_mx_establishments_imss_registration_id", ["imss_registration_id"])
    # Boolean literal differs by dialect, so this one index spells its two predicates.
    if not _has_index(t, "uq_mx_estab_profile_name_active"):
        op.create_index("uq_mx_estab_profile_name_active", t, ["employer_profile_id", "name"], unique=True,
                        postgresql_where=sa.text("is_active"), sqlite_where=sa.text("is_active = 1"))

    t = "payroll_mx_risk_premiums"
    if not _has_table("payroll_mx_risk_premiums"):
        op.create_table(
            "payroll_mx_risk_premiums",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("registration_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_imss_registrations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("determination_year", sa.Integer(), nullable=False),
            sa.Column("premium_rate_pct", sa.Numeric(9, 5), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("evidence_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_compliance_documents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_mx_riskprem_status"),
            sa.CheckConstraint("period_to >= period_from", name="ck_mx_riskprem_window"),
        )
    _index(t, "ix_payroll_mx_risk_premiums_id", ["id"])
    _index(t, "ix_payroll_mx_risk_premiums_registration_id", ["registration_id"])
    _index(t, "uq_mx_riskprem_reg_period_active", ["registration_id", "period_from"], unique=True,
           where="status = 'ACTIVE'")

    t = "payroll_mx_isn_registrations"
    if not _has_table("payroll_mx_isn_registrations"):
        op.create_table(
            "payroll_mx_isn_registrations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("state_code", sa.String(5), nullable=False),
            sa.Column("local_account_number", sa.String(40), nullable=False),
            sa.Column("jurisdiction_pack_id", sa.Integer(), sa.ForeignKey("payroll_jurisdiction_packs.id"), nullable=False),
            sa.Column("return_frequency", sa.String(12), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status", sa.String(8), nullable=False),
            *_stamps(),
            sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_mx_isn_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_isn_window"),
            sa.UniqueConstraint("employer_profile_id", "state_code", "effective_from", name="uq_mx_isn_profile_state_from"),
        )
    _index(t, "ix_payroll_mx_isn_registrations_id", ["id"])
    _index(t, "ix_payroll_mx_isn_registrations_organization_id", ["organization_id"])
    _index(t, "ix_payroll_mx_isn_registrations_employer_profile_id", ["employer_profile_id"])
    _index(t, "uq_mx_isn_profile_state_open", ["employer_profile_id", "state_code"], unique=True,
           where="effective_to IS NULL")

    t = "payroll_mx_labor_policies"
    if not _has_table("payroll_mx_labor_policies"):
        op.create_table(
            "payroll_mx_labor_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("collective_agreement_id", sa.Integer(),
                      sa.ForeignKey("payroll_collective_agreements.id", ondelete="SET NULL"), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("ordinary_weekly_hours", sa.Numeric(5, 2), nullable=False),
            sa.Column("weekly_schedule", sa.JSON(), nullable=True),
            sa.Column("aguinaldo_days", sa.Numeric(6, 2), nullable=False),
            sa.Column("vacation_policy", sa.JSON(), nullable=False),
            sa.Column("vacation_premium_pct", sa.Numeric(7, 3), nullable=False),
            sa.Column("sunday_premium_pct", sa.Numeric(7, 3), nullable=False),
            sa.Column("savings_fund", sa.JSON(), nullable=True),
            sa.Column("food_vouchers", sa.JSON(), nullable=True),
            sa.Column("other_benefits", sa.JSON(), nullable=True),
            sa.Column("time_record_dependency", sa.JSON(), nullable=True),
            sa.Column("floor_check_status", sa.String(16), nullable=False),
            sa.Column("floor_check_detail", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            *_stamps(),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_mx_laborpol_status"),
            sa.CheckConstraint("floor_check_status IN ('PASS', 'FAIL', 'BLOCKED_CONTENT')", name="ck_mx_laborpol_floor"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_laborpol_window"),
            sa.UniqueConstraint("employer_profile_id", "effective_from", "version", name="uq_mx_laborpol_profile_from"),
        )
    _index(t, "ix_payroll_mx_labor_policies_id", ["id"])
    _index(t, "ix_payroll_mx_labor_policies_organization_id", ["organization_id"])
    _index(t, "ix_payroll_mx_labor_policies_employer_profile_id", ["employer_profile_id"])
    _index(t, "uq_mx_laborpol_profile_open", ["employer_profile_id"], unique=True,
           where="effective_to IS NULL AND status = 'ACTIVE'")

    t = "payroll_mx_credential_refs"
    if not _has_table("payroll_mx_credential_refs"):
        op.create_table(
            "payroll_mx_credential_refs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("imss_registration_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_imss_registrations.id", ondelete="CASCADE"), nullable=True),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("secret_ref", sa.String(300), nullable=False),
            sa.Column("certificate_serial", sa.String(80), nullable=True),
            sa.Column("fingerprint_sha256", sa.String(64), nullable=True),
            sa.Column("subject_summary", sa.String(500), nullable=True),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(8), nullable=False),
            sa.Column("rotated_from_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_credential_refs.id", ondelete="SET NULL"), nullable=True),
            *_stamps(),
            sa.CheckConstraint("kind IN ('CSD', 'PAC', 'IDSE', 'SUA', 'BANK')", name="ck_mx_cred_kind"),
            sa.CheckConstraint("status IN ('ACTIVE', 'ROTATED', 'REVOKED')", name="ck_mx_cred_status"),
        )
    _index(t, "ix_payroll_mx_credential_refs_id", ["id"])
    _index(t, "ix_payroll_mx_credential_refs_organization_id", ["organization_id"])
    _index(t, "ix_payroll_mx_credential_refs_employer_profile_id", ["employer_profile_id"])
    _index(t, "ix_payroll_mx_credential_refs_imss_registration_id", ["imss_registration_id"])
    _index(t, "uq_mx_cred_profile_kind_active", ["employer_profile_id", "kind"], unique=True,
           where="status = 'ACTIVE' AND imss_registration_id IS NULL")
    _index(t, "uq_mx_cred_registration_kind_active", ["imss_registration_id", "kind"], unique=True,
           where="status = 'ACTIVE' AND imss_registration_id IS NOT NULL")


def downgrade() -> None:
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

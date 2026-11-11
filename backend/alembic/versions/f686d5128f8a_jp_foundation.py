"""jp_foundation: Japan employer/worker/SI/EI/resident-tax tables, My Number vault, snapshot columns

Revision ID: f686d5128f8a
Revises: c2e7a4f9b1d8 (written on 67c8d7454716; re-parented onto the main merge c2e7a4f9b1d8 when origin/main was merged into venu on 2026-10-30; never applied)
Create Date: 2026-10-30

ZP-JP-ENG-001 Phase 2 (database). Additive only: eight new payroll_jp_* tables
and two nullable shared columns; no existing row is touched.

  payroll_jp_employer_registrations        employer setup: NTA corporate number,
      withholding office/payer status, JPS pension/health workplace IDs, health
      insurer (Kyokai or society), SI deduction timing, labour/EI office and
      industry class, workers' comp class, municipality reporting; effective-
      dated, one ACTIVE open row per organisation (spec 7, JP-009).
  payroll_jp_my_number_vault               encrypted 12-digit My Number boundary:
      ciphertext only (never plaintext or last four), key version, keyed HMAC
      fingerprint for duplicate detection, purpose limitation, collection and
      deletion audit (spec 7 and 12).
  payroll_jp_my_number_access_events       append-only audit of create / reveal
      request / reveal approval / reveal / export / delete; a reveal needs a
      second approver and no row is ever updated or deleted.
  payroll_jp_worker_tax_profiles           effective-dated worker tax facts:
      residency, primary/secondary declaration, dependants, municipality and a
      token-only FK to the vault (spec 3, JP-003/004).
  payroll_jp_social_insurance_enrollments  effective-dated SI facts: eligibility,
      insurer, SMR health/pension grades and amount, SMR basis, actual
      remuneration kept beside (never over) the statutory SMR, care and child-
      support states, qualification/loss dates (spec 5, JP-009/010/011).
  payroll_jp_social_insurance_events       lifecycle events with payload, SBA
      amount, bonus date, reporting due date and submission status (spec 11).
  payroll_jp_employment_insurance_profiles effective-dated EI facts: insured
      flag, EI insured number, industry class, qualification/loss dates
      (spec 6, JP-009).
  payroll_jp_resident_tax_assessments      municipal resident-tax notices only:
      notice reference, fiscal year, version, exactly twelve monthly amounts,
      total, source hash and supersession; a change notice is a NEW version
      (spec 4, JP-007/008).

Shared tables (nullable columns only):
  payslip_items.jp_calculation_snapshot    frozen Japan inputs + result + trace.
  payroll_runs.jp_approval_fingerprint     approval bound to those snapshots.

Row-level security (ZP-PRIV d7f9b1c3e5a6 covers only tables that existed when
it ran): employer registrations get TENANT; the seven employee tables get the
WORKER "org" policy d7f9b1c3e5a6's classify() derives. PostgreSQL only;
tests/test_japan_migrations.py proves classify() agrees. Literal table and
column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f686d5128f8a"
down_revision: Union[str, Sequence[str], None] = "c2e7a4f9b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REGISTRATIONS = "payroll_jp_employer_registrations"
VAULT = "payroll_jp_my_number_vault"
ACCESS_EVENTS = "payroll_jp_my_number_access_events"
TAX_PROFILES = "payroll_jp_worker_tax_profiles"
ENROLLMENTS = "payroll_jp_social_insurance_enrollments"
SI_EVENTS = "payroll_jp_social_insurance_events"
EI_PROFILES = "payroll_jp_employment_insurance_profiles"
RESIDENT_TAX = "payroll_jp_resident_tax_assessments"

TENANT_TABLES = (REGISTRATIONS,)
WORKER_TABLES = (VAULT, ACCESS_EVENTS, TAX_PROFILES, ENROLLMENTS, SI_EVENTS, EI_PROFILES, RESIDENT_TAX)
_TABLES = (ACCESS_EVENTS, TAX_PROFILES, VAULT, SI_EVENTS, ENROLLMENTS, EI_PROFILES, RESIDENT_TAX, REGISTRATIONS)
PAYSLIPS, RUNS = "payslip_items", "payroll_runs"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False, where=None):
    if _has_index(table, name):
        return
    kw = {}
    if where is not None:
        kw = {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}
    op.create_index(name, table, cols, unique=unique, **kw)


def _common(table: str, with_updated: bool = True):
    """id / tenant / legal employer / evidence / version / approval / stamps."""
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legal_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_ref", sa.String(300), nullable=True),
        sa.Column("previous_version_id", sa.Integer(),
                  sa.ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]
    if with_updated:
        columns.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _effective():
    return [sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True)]


def _employee():
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give each table this revision creates the policy d7f9b1c3e5a6
    derives for it, on THESE tables only."""
    rls = _rls_module()
    policies = [(table, rls._TENANT_PREDICATE) for table in TENANT_TABLES]
    policies += [(table, rls._worker_predicate("org")) for table in WORKER_TABLES]
    for table, predicate in policies:
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # 1) Shared tables: nullable Japan columns only.
    if "jp_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("jp_calculation_snapshot", _json(), nullable=True))
    if "jp_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("jp_approval_fingerprint", _json(), nullable=True))

    # 2) payroll_jp_employer_registrations (TENANT)
    t = REGISTRATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_jp_employer_registrations",
            *_common(t),
            *_effective(),
            sa.Column("corporate_number", sa.String(13), nullable=True),
            sa.Column("withholding_tax_office", sa.String(100), nullable=True),
            sa.Column("withholding_payer_status", sa.String(30), nullable=False,
                      server_default="STANDARD"),
            sa.Column("jps_office_symbol", sa.String(30), nullable=True),
            sa.Column("jps_office_number", sa.String(10), nullable=True),
            sa.Column("health_insurer_type", sa.String(30), nullable=False),
            sa.Column("health_insurer_code", sa.String(20), nullable=True),
            sa.Column("health_insurer_prefecture", sa.String(2), nullable=True),
            sa.Column("si_deduction_timing", sa.String(20), nullable=True),
            sa.Column("labour_insurance_number", sa.String(14), nullable=True),
            sa.Column("ei_office_number", sa.String(20), nullable=True),
            sa.Column("ei_industry_class", sa.String(30), nullable=False),
            sa.Column("workers_comp_rate_class", sa.String(30), nullable=True),
            sa.Column("municipality_reporting_enabled", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_jp_registration_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_registration_dates"),
            sa.CheckConstraint("withholding_payer_status IN ('STANDARD', 'SMALL_EMPLOYER_SPECIAL')",
                               name="ck_jp_registration_payer_status"),
            sa.CheckConstraint("health_insurer_type IN ('KYOKAI_KENPO', 'HEALTH_INSURANCE_SOCIETY')",
                               name="ck_jp_registration_insurer_type"),
            sa.CheckConstraint("health_insurer_type <> 'KYOKAI_KENPO' OR health_insurer_prefecture IS NOT NULL",
                               name="ck_jp_registration_kyokai_prefecture"),
            sa.CheckConstraint("si_deduction_timing IS NULL OR si_deduction_timing IN "
                               "('CURRENT_MONTH', 'FOLLOWING_MONTH')",
                               name="ck_jp_registration_si_timing"),
            sa.CheckConstraint("ei_industry_class IN ('GENERAL', 'AGRICULTURE_SAKE', 'CONSTRUCTION')",
                               name="ck_jp_registration_ei_industry"),
        )
    _index(t, "ix_payroll_jp_employer_registrations_id", ["id"])
    _index(t, "ix_payroll_jp_employer_registrations_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_employer_registrations_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_jp_registration_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_jp_registration_one_active", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL")

    # 3) payroll_jp_my_number_vault (WORKER)
    t = VAULT
    if not _has_table(t):
        op.create_table(
            "payroll_jp_my_number_vault",
            *_common(t),
            _employee(),
            sa.Column("subject_type", sa.String(12), nullable=False),
            sa.Column("subject_ref", sa.String(64), nullable=False, server_default="self"),
            sa.Column("ciphertext", sa.Text(), nullable=True),
            sa.Column("key_version", sa.SmallInteger(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False, server_default="TAX_SOCIAL_INSURANCE"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("identity_verified_by", sa.String(30), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint("subject_type IN ('EMPLOYEE', 'DEPENDANT')", name="ck_jp_vault_subject_type"),
            sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_jp_vault_status"),
            sa.CheckConstraint("deleted_at IS NOT NULL OR ciphertext IS NOT NULL",
                               name="ck_jp_vault_ciphertext_or_deleted"),
        )
    _index(t, "ix_payroll_jp_my_number_vault_id", ["id"])
    _index(t, "ix_payroll_jp_my_number_vault_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_my_number_vault_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_my_number_vault_employee_id", ["employee_id"])
    _index(t, "uq_jp_vault_one_active", ["organization_id", "employee_id", "subject_type", "subject_ref"],
           unique=True, where="status = 'ACTIVE'")

    # 4) payroll_jp_my_number_access_events (WORKER, append-only; no updated_at)
    t = ACCESS_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_jp_my_number_access_events",
            *_common(t, with_updated=False),
            _employee(),
            sa.Column("vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.CheckConstraint("action IN ('CREATE', 'REVEAL_REQUESTED', 'REVEAL_APPROVED', 'REVEALED', "
                               "'EXPORTED', 'DELETED')", name="ck_jp_vault_event_action"),
        )
    _index(t, "ix_payroll_jp_my_number_access_events_id", ["id"])
    _index(t, "ix_payroll_jp_my_number_access_events_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_my_number_access_events_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_my_number_access_events_employee_id", ["employee_id"])

    # 5) payroll_jp_worker_tax_profiles (WORKER, effective-dated)
    t = TAX_PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_jp_worker_tax_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("residency_status", sa.String(20), nullable=True),
            sa.Column("declaration_class", sa.String(20), nullable=True),
            sa.Column("declaration_received_on", sa.Date(), nullable=True),
            sa.Column("dependants_count", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("dependant_facts", _json(), nullable=True),
            sa.Column("municipality_code", sa.String(6), nullable=True),
            sa.Column("residence_prefecture", sa.String(2), nullable=True),
            # SPECIAL = salary special collection from a municipality notice;
            # NOT_APPLICABLE = no notice applies (e.g. first year in Japan),
            # evidenced via evidence_ref. Only SPECIAL requires a notice.
            sa.Column("resident_tax_collection", sa.String(20), nullable=False, server_default="SPECIAL"),
            sa.Column("my_number_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("residency_status IS NULL OR residency_status IN ('RESIDENT', 'NON_RESIDENT')",
                               name="ck_jp_tax_profile_residency"),
            sa.CheckConstraint("declaration_class IS NULL OR declaration_class IN ('PRIMARY', 'SECONDARY')",
                               name="ck_jp_tax_profile_declaration"),
            sa.CheckConstraint("dependants_count >= 0", name="ck_jp_tax_profile_dependants"),
            sa.CheckConstraint("resident_tax_collection IN ('SPECIAL', 'NOT_APPLICABLE')",
                               name="ck_jp_tax_profile_resident_tax_collection"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_jp_tax_profile_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_tax_profile_dates"),
        )
    _index(t, "ix_payroll_jp_worker_tax_profiles_id", ["id"])
    _index(t, "ix_payroll_jp_worker_tax_profiles_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_worker_tax_profiles_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_worker_tax_profiles_employee_id", ["employee_id"])
    _index(t, "ix_jp_tax_profile_employee_period", ["employee_id", "effective_from"])

    # 6) payroll_jp_social_insurance_enrollments (WORKER, effective-dated)
    t = ENROLLMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_jp_social_insurance_enrollments",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("health_eligible", sa.Boolean(), nullable=False),
            sa.Column("pension_eligible", sa.Boolean(), nullable=False),
            sa.Column("health_insurer_code", sa.String(20), nullable=True),
            sa.Column("smr_health_grade", sa.SmallInteger(), nullable=True),
            sa.Column("smr_pension_grade", sa.SmallInteger(), nullable=True),
            # Health and pension SMR differ above the pension grade ceiling (JP-010).
            sa.Column("smr_health_amount", sa.Numeric(12, 0), nullable=True),
            sa.Column("smr_pension_amount", sa.Numeric(12, 0), nullable=True),
            sa.Column("smr_basis", sa.String(30), nullable=True),
            sa.Column("actual_remuneration", _json(), nullable=True),
            sa.Column("care_state", sa.String(20), nullable=True),
            sa.Column("child_support_state", sa.String(20), nullable=True),
            sa.Column("qualification_date", sa.Date(), nullable=True),
            sa.Column("loss_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("smr_basis IS NULL OR smr_basis IN ('QUALIFICATION', 'ANNUAL_DETERMINATION', "
                               "'ADHOC_REVISION', 'RETURN_TO_WORK', 'OTHER')",
                               name="ck_jp_si_enrollment_smr_basis"),
            sa.CheckConstraint("care_state IS NULL OR care_state IN ('NOT_COVERED', 'COVERED', 'EXEMPT')",
                               name="ck_jp_si_enrollment_care_state"),
            sa.CheckConstraint("child_support_state IS NULL OR child_support_state IN ('COVERED', 'EXEMPT')",
                               name="ck_jp_si_enrollment_child_support"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_jp_si_enrollment_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_si_enrollment_dates"),
        )
    _index(t, "ix_payroll_jp_social_insurance_enrollments_id", ["id"])
    _index(t, "ix_payroll_jp_social_insurance_enrollments_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_social_insurance_enrollments_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_social_insurance_enrollments_employee_id", ["employee_id"])
    _index(t, "ix_jp_si_enrollment_employee_period", ["employee_id", "effective_from"])

    # 7) payroll_jp_social_insurance_events (WORKER)
    t = SI_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_jp_social_insurance_events",
            *_common(t),
            _employee(),
            sa.Column("enrollment_id", sa.Integer(),
                      sa.ForeignKey(f"{ENROLLMENTS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_type", sa.String(30), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("payload", _json(), nullable=True),
            sa.Column("bonus_paid_on", sa.Date(), nullable=True),
            sa.Column("sba_amount", sa.Numeric(12, 0), nullable=True),
            sa.Column("report_due_on", sa.Date(), nullable=True),
            sa.Column("submission_status", sa.String(12), nullable=False, server_default="CREATED"),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.CheckConstraint("event_type IN ('QUALIFICATION', 'LOSS', 'ANNUAL_DETERMINATION', "
                               "'ADHOC_REVISION', 'BONUS', 'MATERNITY_EXEMPTION', 'CHILDCARE_EXEMPTION', "
                               "'RETURN_TO_WORK_REVISION')", name="ck_jp_si_event_type"),
            sa.CheckConstraint("submission_status IN ('CREATED', 'APPROVED', 'SUBMITTED', 'ACCEPTED', "
                               "'REJECTED', 'CORRECTED')", name="ck_jp_si_event_submission_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_si_event_dates"),
        )
    _index(t, "ix_payroll_jp_social_insurance_events_id", ["id"])
    _index(t, "ix_payroll_jp_social_insurance_events_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_social_insurance_events_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_social_insurance_events_employee_id", ["employee_id"])

    # 8) payroll_jp_employment_insurance_profiles (WORKER, effective-dated)
    t = EI_PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_jp_employment_insurance_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("insured", sa.Boolean(), nullable=False),
            sa.Column("ei_insured_number", sa.String(20), nullable=True),
            sa.Column("industry_class", sa.String(30), nullable=False),
            sa.Column("qualification_date", sa.Date(), nullable=True),
            sa.Column("loss_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("industry_class IN ('GENERAL', 'AGRICULTURE_SAKE', 'CONSTRUCTION')",
                               name="ck_jp_ei_profile_industry"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_jp_ei_profile_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_jp_ei_profile_dates"),
        )
    _index(t, "ix_payroll_jp_employment_insurance_profiles_id", ["id"])
    _index(t, "ix_payroll_jp_employment_insurance_profiles_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_employment_insurance_profiles_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_employment_insurance_profiles_employee_id", ["employee_id"])
    _index(t, "ix_jp_ei_profile_employee_period", ["employee_id", "effective_from"])

    # 9) payroll_jp_resident_tax_assessments (WORKER)
    t = RESIDENT_TAX
    if not _has_table(t):
        op.create_table(
            "payroll_jp_resident_tax_assessments",
            *_common(t),
            _employee(),
            sa.Column("municipality_code", sa.String(6), nullable=False),
            sa.Column("fiscal_notice_year", sa.SmallInteger(), nullable=False),
            sa.Column("notice_id", sa.String(50), nullable=False),
            sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("received_on", sa.Date(), nullable=False),
            sa.Column("first_deduction_month", sa.Date(), nullable=False),
            sa.Column("monthly_amounts", _json(), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 0), nullable=False),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column("replaces_id", sa.Integer(),
                      sa.ForeignKey(f"{RESIDENT_TAX}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="IMPORTED"),
            sa.CheckConstraint("status IN ('IMPORTED', 'APPROVED', 'SUPERSEDED', 'REJECTED')",
                               name="ck_jp_resident_tax_status"),
            sa.CheckConstraint("version >= 1", name="ck_jp_resident_tax_version"),
        )
    _index(t, "ix_payroll_jp_resident_tax_assessments_id", ["id"])
    _index(t, "ix_payroll_jp_resident_tax_assessments_organization_id", ["organization_id"])
    _index(t, "ix_payroll_jp_resident_tax_assessments_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_payroll_jp_resident_tax_assessments_employee_id", ["employee_id"])
    _index(t, "uq_jp_resident_tax_notice_version",
           ["organization_id", "employee_id", "municipality_code", "fiscal_notice_year", "version"],
           unique=True)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "jp_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "jp_approval_fingerprint")
    if "jp_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "jp_calculation_snapshot")

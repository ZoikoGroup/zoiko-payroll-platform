"""nz_foundation: New Zealand employer/employee statutory tables, IRD vault, ledger, snapshot columns

Revision ID: 0e697c2388bf
Revises: b8bd939fffca
Create Date: 2026-11-03

ZP-NZ-ENG-001 Phase 2 (database). Additive only: eight new payroll_nz_* tables
and three nullable shared columns; no existing row is touched.

  payroll_nz_employer_profiles          employer setup per legal employer
      (NZ-001): legal name, encrypted employer IRD number (vault ref), filing
      method, annual PAYE+ESCT basis, remittance class, connected-business
      group + evidence, ACC classification unit, timezone, bank-mandate and
      filing-credential REFERENCES (never secrets), verification state;
      effective-dated, one ACTIVE open row per (organisation, legal entity).
  payroll_nz_ird_vault                  encrypted IRD numbers (employee or
      employer): ciphertext only (no plaintext, no trailing digits), key
      version, keyed HMAC fingerprint (duplicate detection), purpose limit,
      collection/deletion audit (spec §13, NZ-023).
  payroll_nz_ird_access_events          append-only audit of create / reveal
      request / reveal approval / reveal / export / delete / key rotation.
  payroll_nz_employee_tax_profiles      effective-dated tax facts: IRD-number
      state, tax code and its source, declaration, residency, tailored-code
      certificate, student-loan certificate, minimum-wage category + evidence.
  payroll_nz_kiwisaver_elections        effective-dated KiwiSaver state:
      membership, rates, temporary reduction and savings suspension (each with
      evidence and dates, NZ-009), ESCT rate and basis, contribution treatment,
      settlement destination (NZ-007).
  payroll_nz_authority_deductions       immutable authority notices
      (NZ-010): type, notice id, issuer, received/effective dates, amount or
      rate, protected-earnings policy, reason code, file hash, version and
      supersession. No notice body is stored (NZ-025).
  payroll_nz_work_pattern_versions      effective-dated work pattern (fixed /
      rostered / variable), contracted hours and days, schedule, hours source.
  payroll_nz_accumulator_entries        append-only ledger behind the ACC cap
      and year-to-date values, keyed by employee + legal entity + tax year +
      obligation (NZ-013); a payslip posts each obligation once.

Shared tables (nullable columns only):
  payslip_items.nz_calculation_snapshot   frozen NZ inputs + result + trace.
  payroll_runs.nz_approval_fingerprint    approval bound to those snapshots.
  payroll_runs.nz_payment_kind            REGULAR / OUT_OF_CYCLE / LUMP_SUM /
      FINAL / HOLIDAY_PAY_ADVANCE / CORRECTION — per run, never per employee.

No statutory rate or threshold appears in any CHECK constraint (spec page 1):
the constraints enforce enumerations and date order only.

Row-level security (ZP-PRIV d7f9b1c3e5a6 covers only tables that existed when
it ran): employer profiles get TENANT; the seven employee tables get the
WORKER "org" policy d7f9b1c3e5a6's classify() derives. PostgreSQL only;
tests/test_nz_migrations.py proves classify() agrees. Literal table and
column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0e697c2388bf"
down_revision: Union[str, Sequence[str], None] = "b8bd939fffca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPLOYERS = "payroll_nz_employer_profiles"
VAULT = "payroll_nz_ird_vault"
ACCESS_EVENTS = "payroll_nz_ird_access_events"
TAX_PROFILES = "payroll_nz_employee_tax_profiles"
KIWISAVER = "payroll_nz_kiwisaver_elections"
NOTICES = "payroll_nz_authority_deductions"
WORK_PATTERNS = "payroll_nz_work_pattern_versions"
LEDGER = "payroll_nz_accumulator_entries"

TENANT_TABLES = (EMPLOYERS,)
WORKER_TABLES = (VAULT, ACCESS_EVENTS, TAX_PROFILES, KIWISAVER, NOTICES, WORK_PATTERNS, LEDGER)
_TABLES = (LEDGER, WORK_PATTERNS, NOTICES, KIWISAVER, TAX_PROFILES, ACCESS_EVENTS, EMPLOYERS, VAULT)
PAYSLIPS, RUNS = "payslip_items", "payroll_runs"

TAX_CODES = ("M", "ME", "M SL", "ME SL", "SB", "S", "SH", "ST", "SA",
             "SB SL", "S SL", "SH SL", "ST SL", "SA SL", "ND", "STC")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


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


def _employee(nullable=False):
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=nullable)


def _status(prefix):
    return [sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name=f"ck_nz_{prefix}_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name=f"ck_nz_{prefix}_dates")]


def _standard_indexes(table):
    _index(table, f"ix_{table}_id", ["id"])
    _index(table, f"ix_{table}_organization_id", ["organization_id"])
    _index(table, f"ix_{table}_legal_entity_id", ["legal_entity_id"])


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

    # 1) Shared tables: nullable New Zealand columns only.
    if "nz_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("nz_calculation_snapshot", _json(), nullable=True))
    if "nz_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("nz_approval_fingerprint", _json(), nullable=True))
    if "nz_payment_kind" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("nz_payment_kind", sa.String(20), nullable=True))

    # 2) payroll_nz_ird_vault (WORKER) — created first: employer profiles and
    # tax profiles reference it.
    t = VAULT
    if not _has_table(t):
        op.create_table(
            "payroll_nz_ird_vault",
            *_common(t),
            _employee(nullable=True),
            sa.Column("subject_type", sa.String(10), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=True),
            sa.Column("key_version", sa.SmallInteger(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False, server_default="PAYE_PAYDAY_FILING"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint("subject_type IN ('EMPLOYEE', 'EMPLOYER')", name="ck_nz_vault_subject_type"),
            sa.CheckConstraint("(subject_type = 'EMPLOYER' AND employee_id IS NULL) OR "
                               "(subject_type = 'EMPLOYEE' AND employee_id IS NOT NULL)",
                               name="ck_nz_vault_subject_employee"),
            sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_nz_vault_status"),
            sa.CheckConstraint("deleted_at IS NOT NULL OR ciphertext IS NOT NULL",
                               name="ck_nz_vault_ciphertext_or_deleted"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_ird_vault_employee_id", ["employee_id"])
    _index(t, "uq_nz_vault_one_active_employee", ["organization_id", "employee_id"], unique=True,
           where="status = 'ACTIVE' AND subject_type = 'EMPLOYEE'")
    _index(t, "uq_nz_vault_fingerprint", ["organization_id", "subject_type", "fingerprint"], unique=True,
           where="status = 'ACTIVE'")

    # 3) payroll_nz_employer_profiles (TENANT)
    t = EMPLOYERS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_employer_profiles",
            *_common(t),
            *_effective(),
            sa.Column("legal_name", sa.String(200), nullable=False),
            sa.Column("employer_ird_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("filing_method", sa.String(20), nullable=False),
            sa.Column("filing_method_evidence_ref", sa.String(300), nullable=True),
            sa.Column("annual_paye_esct_basis", sa.String(12), nullable=True),
            sa.Column("annual_paye_esct_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("remittance_class", sa.String(15), nullable=False),
            sa.Column("connected_business_group_ref", sa.String(100), nullable=True),
            sa.Column("connected_business_evidence_ref", sa.String(300), nullable=True),
            sa.Column("acc_classification_unit", sa.String(10), nullable=True),
            sa.Column("acc_metadata", _json(), nullable=True),
            sa.Column("timezone", sa.String(40), nullable=False, server_default="Pacific/Auckland"),
            sa.Column("bank_mandate_ref", sa.String(100), nullable=True),
            sa.Column("filing_credential_ref", sa.String(100), nullable=True),
            sa.Column("verification_state", sa.String(12), nullable=False, server_default="UNVERIFIED"),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            *_status("employer"),
            sa.CheckConstraint("filing_method IN ('PAYDAY_GATEWAY', 'MYIR_FILE_UPLOAD', 'MYIR_ONSCREEN', 'PAPER')",
                               name="ck_nz_employer_filing_method"),
            sa.CheckConstraint("annual_paye_esct_basis IS NULL OR annual_paye_esct_basis IN ('PRIOR_YEAR', 'ESTIMATE')",
                               name="ck_nz_employer_paye_esct_basis"),
            sa.CheckConstraint("remittance_class IN ('MONTHLY', 'TWICE_MONTHLY')",
                               name="ck_nz_employer_remittance_class"),
            sa.CheckConstraint("connected_business_group_ref IS NULL OR connected_business_evidence_ref IS NOT NULL",
                               name="ck_nz_employer_connected_evidence"),
            sa.CheckConstraint("timezone IN ('Pacific/Auckland', 'Pacific/Chatham')", name="ck_nz_employer_timezone"),
            sa.CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
                               name="ck_nz_employer_verification"),
        )
    _standard_indexes(t)
    _index(t, "ix_nz_employer_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_nz_employer_one_active_entity", ["organization_id", "legal_entity_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NOT NULL")
    _index(t, "uq_nz_employer_one_active_org", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NULL")

    # 4) payroll_nz_ird_access_events (WORKER, append-only; no updated_at)
    t = ACCESS_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_ird_access_events",
            *_common(t, with_updated=False),
            _employee(nullable=True),
            sa.Column("vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.CheckConstraint("action IN ('CREATE', 'REVEAL_REQUESTED', 'REVEAL_APPROVED', 'REVEALED', "
                               "'EXPORTED', 'DELETED', 'ROTATED')", name="ck_nz_vault_event_action"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_ird_access_events_employee_id", ["employee_id"])
    _index(t, "ix_payroll_nz_ird_access_events_vault_id", ["vault_id"])

    # 5) payroll_nz_employee_tax_profiles (WORKER, effective-dated)
    t = TAX_PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_nz_employee_tax_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("ird_number_state", sa.String(10), nullable=False),
            sa.Column("ird_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("tax_code", sa.String(8), nullable=False),
            sa.Column("tax_code_source", sa.String(20), nullable=False),
            sa.Column("declaration_received_on", sa.Date(), nullable=True),
            sa.Column("declaration_ref", sa.String(300), nullable=True),
            sa.Column("residency_status", sa.String(14), nullable=False, server_default="RESIDENT"),
            sa.Column("tailored_certificate_ref", sa.String(100), nullable=True),
            sa.Column("tailored_rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("tailored_valid_from", sa.Date(), nullable=True),
            sa.Column("tailored_valid_to", sa.Date(), nullable=True),
            sa.Column("sl_certificate_type", sa.String(24), nullable=True),
            sa.Column("sl_certificate_ref", sa.String(100), nullable=True),
            sa.Column("sl_certificate_rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("sl_certificate_valid_from", sa.Date(), nullable=True),
            sa.Column("sl_certificate_valid_to", sa.Date(), nullable=True),
            sa.Column("min_wage_category", sa.String(16), nullable=True),
            sa.Column("min_wage_evidence_ref", sa.String(300), nullable=True),
            *_status("tax_profile"),
            sa.CheckConstraint("ird_number_state IN ('VALID', 'PENDING', 'MISSING', 'INVALID')",
                               name="ck_nz_tax_profile_ird_state"),
            sa.CheckConstraint("ird_number_state <> 'VALID' OR ird_vault_id IS NOT NULL",
                               name="ck_nz_tax_profile_ird_vault"),
            sa.CheckConstraint(f"tax_code IN {_in(TAX_CODES)}", name="ck_nz_tax_profile_tax_code"),
            sa.CheckConstraint("tax_code_source IN ('IR330_DECLARATION', 'IRD_NOTICE', 'NO_NOTIFICATION')",
                               name="ck_nz_tax_profile_code_source"),
            sa.CheckConstraint("residency_status IN ('RESIDENT', 'NON_RESIDENT')", name="ck_nz_tax_profile_residency"),
            sa.CheckConstraint("tax_code <> 'STC' OR (tailored_certificate_ref IS NOT NULL AND "
                               "tailored_rate_pct IS NOT NULL AND tailored_valid_from IS NOT NULL)",
                               name="ck_nz_tax_profile_stc"),
            sa.CheckConstraint("sl_certificate_type IS NULL OR sl_certificate_type IN "
                               "('SPECIAL_DEDUCTION_RATE', 'NIL_DEDUCTION')", name="ck_nz_tax_profile_sl_cert_type"),
            sa.CheckConstraint("sl_certificate_type IS NULL OR (sl_certificate_ref IS NOT NULL AND "
                               "sl_certificate_valid_from IS NOT NULL)", name="ck_nz_tax_profile_sl_cert"),
            sa.CheckConstraint("sl_certificate_type IS NULL OR sl_certificate_type <> 'SPECIAL_DEDUCTION_RATE' OR "
                               "sl_certificate_rate_pct IS NOT NULL", name="ck_nz_tax_profile_sl_cert_rate"),
            sa.CheckConstraint("min_wage_category IS NULL OR min_wage_category IN "
                               "('ADULT', 'STARTING_OUT', 'TRAINING', 'EXEMPTION_PERMIT')",
                               name="ck_nz_tax_profile_min_wage_category"),
            sa.CheckConstraint("min_wage_category IS NULL OR min_wage_category = 'ADULT' OR "
                               "min_wage_evidence_ref IS NOT NULL", name="ck_nz_tax_profile_min_wage_evidence"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_employee_tax_profiles_employee_id", ["employee_id"])
    _index(t, "ix_nz_tax_profile_employee_period", ["employee_id", "effective_from"])

    # 6) payroll_nz_kiwisaver_elections (WORKER, effective-dated)
    t = KIWISAVER
    if not _has_table(t):
        op.create_table(
            "payroll_nz_kiwisaver_elections",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("membership_state", sa.String(22), nullable=False),
            sa.Column("enrolment_route", sa.String(16), nullable=True),
            sa.Column("opt_out_evidence_ref", sa.String(300), nullable=True),
            sa.Column("employee_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("employer_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("reduction_ref", sa.String(100), nullable=True),
            sa.Column("reduction_from", sa.Date(), nullable=True),
            sa.Column("reduction_to", sa.Date(), nullable=True),
            sa.Column("employer_matches_reduction", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("suspension_ref", sa.String(100), nullable=True),
            sa.Column("suspension_from", sa.Date(), nullable=True),
            sa.Column("suspension_to", sa.Date(), nullable=True),
            sa.Column("esct_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("esct_basis", sa.String(22), nullable=True),
            sa.Column("esct_basis_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("esct_tax_year", sa.String(7), nullable=True),
            sa.Column("employer_contribution_treatment", sa.String(16), nullable=False, server_default="ESCT"),
            sa.Column("settlement_destination", sa.String(16), nullable=False, server_default="INLAND_REVENUE"),
            sa.Column("complying_fund_ref", sa.String(100), nullable=True),
            *_status("kiwisaver"),
            sa.CheckConstraint("membership_state IN ('NOT_MEMBER', 'CONTRIBUTING', 'OPTED_OUT', "
                               "'SAVINGS_SUSPENSION', 'NOT_ELIGIBLE')", name="ck_nz_kiwisaver_membership"),
            sa.CheckConstraint("enrolment_route IS NULL OR enrolment_route IN "
                               "('AUTO_ENROLLED', 'OPT_IN', 'EXISTING_MEMBER')", name="ck_nz_kiwisaver_route"),
            sa.CheckConstraint("(reduction_ref IS NULL) = (reduction_from IS NULL)",
                               name="ck_nz_kiwisaver_reduction_evidence"),
            sa.CheckConstraint("(suspension_ref IS NULL) = (suspension_from IS NULL)",
                               name="ck_nz_kiwisaver_suspension_evidence"),
            sa.CheckConstraint("membership_state <> 'SAVINGS_SUSPENSION' OR suspension_ref IS NOT NULL",
                               name="ck_nz_kiwisaver_suspension_state"),
            sa.CheckConstraint("membership_state <> 'OPTED_OUT' OR opt_out_evidence_ref IS NOT NULL",
                               name="ck_nz_kiwisaver_opt_out_evidence"),
            sa.CheckConstraint("esct_basis IS NULL OR esct_basis IN ('PRIOR_YEAR', 'ESTIMATE', 'NEW_EMPLOYEE_ESTIMATE')",
                               name="ck_nz_kiwisaver_esct_basis"),
            sa.CheckConstraint("employer_contribution_treatment IN ('ESCT', 'PAYE_ALTERNATIVE')",
                               name="ck_nz_kiwisaver_treatment"),
            sa.CheckConstraint("settlement_destination IN ('INLAND_REVENUE', 'COMPLYING_FUND')",
                               name="ck_nz_kiwisaver_destination"),
            sa.CheckConstraint("settlement_destination <> 'COMPLYING_FUND' OR complying_fund_ref IS NOT NULL",
                               name="ck_nz_kiwisaver_fund_ref"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_kiwisaver_elections_employee_id", ["employee_id"])
    _index(t, "ix_nz_kiwisaver_employee_period", ["employee_id", "effective_from"])

    # 7) payroll_nz_authority_deductions (WORKER, immutable notices)
    t = NOTICES
    if not _has_table(t):
        op.create_table(
            "payroll_nz_authority_deductions",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("deduction_type", sa.String(24), nullable=False),
            sa.Column("notice_id", sa.String(60), nullable=False),
            sa.Column("issuer", sa.String(30), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("amount_per_payday", sa.Numeric(12, 2), nullable=True),
            sa.Column("rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("protected_earnings_policy", sa.String(24), nullable=False),
            sa.Column("protected_earnings_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("reason_code", sa.String(20), nullable=True),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("replaces_id", sa.Integer(),
                      sa.ForeignKey(f"{NOTICES}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="IMPORTED"),
            sa.CheckConstraint("deduction_type IN ('CHILD_SUPPORT', 'STUDENT_LOAN_EXTRA', 'IRD_DEDUCTION_NOTICE', "
                               "'COURT_ATTACHMENT')", name="ck_nz_notice_type"),
            sa.CheckConstraint("issuer IN ('INLAND_REVENUE', 'COURT', 'MSD', 'OTHER_AUTHORITY')",
                               name="ck_nz_notice_issuer"),
            sa.CheckConstraint("amount_per_payday IS NOT NULL OR rate_pct IS NOT NULL", name="ck_nz_notice_amount"),
            sa.CheckConstraint("protected_earnings_policy IN ('IRD_PROTECTED_NET', 'COURT_SPECIFIED', 'NONE')",
                               name="ck_nz_notice_protected_policy"),
            sa.CheckConstraint("protected_earnings_policy <> 'COURT_SPECIFIED' OR protected_earnings_amount IS NOT NULL",
                               name="ck_nz_notice_protected_amount"),
            sa.CheckConstraint("version >= 1", name="ck_nz_notice_version"),
            sa.CheckConstraint("status IN ('IMPORTED', 'APPROVED', 'SUPERSEDED', 'REVOKED', 'REJECTED')",
                               name="ck_nz_notice_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_nz_notice_dates"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_authority_deductions_employee_id", ["employee_id"])
    _index(t, "uq_nz_authority_notice_version",
           ["organization_id", "employee_id", "deduction_type", "notice_id", "version"], unique=True)

    # 8) payroll_nz_work_pattern_versions (WORKER, effective-dated)
    t = WORK_PATTERNS
    if not _has_table(t):
        op.create_table(
            "payroll_nz_work_pattern_versions",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("pattern_type", sa.String(10), nullable=False),
            sa.Column("contracted_hours_per_week", sa.Numeric(6, 2), nullable=True),
            sa.Column("contracted_days_per_week", sa.Numeric(3, 1), nullable=True),
            sa.Column("weekly_schedule", _json(), nullable=True),
            sa.Column("roster_cycle_weeks", sa.SmallInteger(), nullable=True),
            sa.Column("roster_schedule", _json(), nullable=True),
            sa.Column("hours_source", sa.String(10), nullable=False),
            *_status("work_pattern"),
            sa.CheckConstraint("pattern_type IN ('FIXED', 'ROSTERED', 'VARIABLE')", name="ck_nz_work_pattern_type"),
            sa.CheckConstraint("hours_source IN ('CONTRACT', 'TIMESHEET', 'ROSTER')",
                               name="ck_nz_work_pattern_hours_source"),
            sa.CheckConstraint("pattern_type <> 'FIXED' OR weekly_schedule IS NOT NULL",
                               name="ck_nz_work_pattern_fixed"),
            sa.CheckConstraint("pattern_type <> 'ROSTERED' OR (roster_cycle_weeks IS NOT NULL AND "
                               "roster_schedule IS NOT NULL)", name="ck_nz_work_pattern_roster"),
            sa.CheckConstraint("roster_cycle_weeks IS NULL OR roster_cycle_weeks >= 1",
                               name="ck_nz_work_pattern_cycle"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_work_pattern_versions_employee_id", ["employee_id"])
    _index(t, "ix_nz_work_pattern_employee_period", ["employee_id", "effective_from"])

    # 9) payroll_nz_accumulator_entries (WORKER, append-only ledger; no updated_at)
    t = LEDGER
    if not _has_table(t):
        op.create_table(
            "payroll_nz_accumulator_entries",
            *_common(t, with_updated=False),
            _employee(),
            sa.Column("tax_year", sa.String(7), nullable=False),
            sa.Column("obligation", sa.String(24), nullable=False),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("entry_kind", sa.String(16), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("result_hash", sa.String(64), nullable=True),
            sa.CheckConstraint("obligation IN ('ACC_LIABLE_EARNINGS', 'PAYE_GROSS', 'PAYE', 'ACC_LEVY', 'KS_GROSS', "
                               "'KS_EMPLOYEE', 'KS_EMPLOYER_GROSS', 'ESCT', 'STUDENT_LOAN', 'CHILD_SUPPORT')",
                               name="ck_nz_accum_obligation"),
            sa.CheckConstraint("entry_kind IN ('RUN', 'CORRECTION', 'OPENING_BALANCE')", name="ck_nz_accum_kind"),
            sa.CheckConstraint("entry_kind <> 'OPENING_BALANCE' OR (evidence_ref IS NOT NULL AND "
                               "approved_by_id IS NOT NULL)", name="ck_nz_accum_opening_evidence"),
            sa.CheckConstraint("entry_kind <> 'RUN' OR payslip_item_id IS NOT NULL", name="ck_nz_accum_run_payslip"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_nz_accumulator_entries_employee_id", ["employee_id"])
    _index(t, "ix_nz_accum_lookup", ["employee_id", "legal_entity_id", "tax_year", "obligation", "pay_date"])
    _index(t, "uq_nz_accum_payslip_obligation", ["payslip_item_id", "obligation"], unique=True,
           where="entry_kind = 'RUN'")

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "nz_payment_kind" in _columns(RUNS):
        op.drop_column(RUNS, "nz_payment_kind")
    if "nz_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "nz_approval_fingerprint")
    if "nz_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "nz_calculation_snapshot")

"""my_foundation: Malaysia employer/worker statutory tables, identifier vault, work assignments, tax declarations, ledger

Revision ID: 13574b996ccf
Revises: f3a9c1d7e2b4
Create Date: 2026-11-12

ZP-MY-ENG-001 Phase 2 (database). Written on e7ec6c1933b4 (Poland P9) and
re-parented, never applied, onto f3a9c1d7e2b4 (payslip templates) at the
2026-11-12 venu sync (single head). Additive only: seven new payroll_my_*
tables and two nullable shared columns; no existing row is touched.

  payroll_my_identifier_vault           encrypted MyKad/NRIC, TIN, EPF and
      SOCSO member numbers and work-pass numbers: ciphertext only, key
      version, keyed HMAC fingerprint (duplicate detection), purpose,
      collection/deletion audit (spec §15, MY-029).
  payroll_my_identifier_access_events   append-only audit of create / reveal
      request / reveal approval / reveal / export / delete / key rotation.
  payroll_my_employer_registrations     per legal employer (TENANT): HASiL
      employer number, EPF / PERKESO employer references, HRD category with
      its registration number, start date and evidence (MY-016 — never
      inferred from a live headcount), journal accounts, credential
      REFERENCES only, verification state; effective-dated, four-eyes.
  payroll_my_worker_profiles            effective-dated coverage facts (spec §4):
      contract type, pay frequency, citizenship, date of birth, REVIEWED tax
      residence with evidence and period (MY-007), work pass and validity, EPF
      member class and history date, SOCSO category, EIS state, manual-worker
      flag (NULL = not known -> the engine BLOCKS), normal hours, rest day,
      service start, vault references.
  payroll_my_work_assignments           effective-dated work location: labour
      territory (PENINSULAR_LABUAN / SABAH / SARAWAK) and holiday state
      (16 codes), transfer history (MY-001 / MY-003). No default territory.
  payroll_my_tax_declarations           TP1 / TP3 / CP38 / zakat / tax borne by
      employer / EPF voluntary excess: tax year, value, received and effective
      dates, evidence, supersession, four-eyes (MY-010).
  payroll_my_accumulator_entries        append-only year-to-date ledger (PCB
      accumulators, contributions, leave counters); TP3 prior-employer values
      are evidenced, four-eyes PRIOR_EMPLOYER entries.

No statutory number appears in any CHECK constraint. RLS (d7f9b1c3e5a6
classify): employer registrations TENANT; the six employee tables WORKER
"org". PostgreSQL only; literal names; lock_timeout; idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "13574b996ccf"
down_revision: Union[str, Sequence[str], None] = "f3a9c1d7e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VAULT = "payroll_my_identifier_vault"
ACCESS_EVENTS = "payroll_my_identifier_access_events"
EMPLOYERS = "payroll_my_employer_registrations"
PROFILES = "payroll_my_worker_profiles"
ASSIGNMENTS = "payroll_my_work_assignments"
DECLARATIONS = "payroll_my_tax_declarations"
LEDGER = "payroll_my_accumulator_entries"

TENANT_TABLES = (EMPLOYERS,)
WORKER_TABLES = (VAULT, ACCESS_EVENTS, PROFILES, ASSIGNMENTS, DECLARATIONS, LEDGER)
# Drop order (children first).
_TABLES = (LEDGER, DECLARATIONS, ASSIGNMENTS, PROFILES, EMPLOYERS, ACCESS_EVENTS, VAULT)
PAYSLIPS, RUNS = "payslip_items", "payroll_runs"

# Vocabularies (mirror engine/countries/malaysia_content.py; no values).
IDENTIFIER_TYPES = ("NRIC", "TIN", "EPF_NO", "SOCSO_NO", "WORK_PASS_NO")
CONTRACT_TYPES = ("CONTRACT_OF_SERVICE", "GIG_PLATFORM", "DOMESTIC", "PUBLIC_SECTOR", "OTHER")
PAY_FREQUENCIES = ("MONTHLY", "SEMI_MONTHLY", "WEEKLY", "OTHER")
CITIZENSHIP = ("CITIZEN", "PERMANENT_RESIDENT", "NON_CITIZEN")
TAX_RESIDENCE = ("RESIDENT", "NON_RESIDENT", "REVIEW_REQUIRED")
WORK_PASS_TYPES = ("NONE", "EMPLOYMENT_PASS", "VISIT_PASS_TEMP_EMPLOYMENT", "RESIDENCE_PASS_TALENT", "OTHER")
EPF_MEMBER_CLASSES = ("MY_PR_BELOW_60", "MY_60_PLUS", "PR_OR_PRE1998_NONMY_60_PLUS", "NONMY_POST_1998",
                      "NOT_COVERED")
SOCSO_CATEGORIES = ("EI_AND_INVALIDITY", "EI_ONLY", "FOREIGN_WORKER", "NOT_COVERED", "UNSUPPORTED_DOMESTIC")
EIS_STATES = ("COVERED", "EXEMPT_AGE", "EXEMPT_HISTORY", "FOREIGN_EXCLUDED")
HRD_CATEGORIES = ("COMPULSORY", "OPTIONAL_REGISTERED", "NOT_REGISTERED")
REST_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
TERRITORIES = ("PENINSULAR_LABUAN", "SABAH", "SARAWAK")
HOLIDAY_STATES = ("JHR", "KDH", "KTN", "MLK", "NSN", "PHG", "PRK", "PLS", "PNG", "SBH", "SWK", "SGR", "TRG",
                  "KUL", "LBN", "PJY")
ASSIGNMENT_REASONS = ("HIRE", "TRANSFER", "ASSIGNMENT", "CORRECTION")
DECLARATION_TYPES = ("TP1", "TP3", "CP38", "ZAKAT", "TAX_BORNE_BY_EMPLOYER", "EPF_VOLUNTARY_EXCESS")
ACCUMULATORS = ("PCB_GROSS_NORMAL", "PCB_GROSS_ADDITIONAL", "PCB_PAID", "PCB_EPF_RELIEF_USED", "ZAKAT_PAID",
                "CP38_PAID", "EPF_EE", "EPF_ER", "SOCSO_EE", "SOCSO_ER", "EIS_EE", "EIS_ER", "HRD_LEVY",
                "LEAVE_ANNUAL_DAYS", "LEAVE_SICK_DAYS")
TP3_ACCUMULATORS = ("PCB_GROSS_NORMAL", "PCB_GROSS_ADDITIONAL", "PCB_PAID", "PCB_EPF_RELIEF_USED", "ZAKAT_PAID")


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


def _common(table: str, with_updated: bool = True) -> list:
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


def _effective() -> list:
    return [sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True)]


def _employee(nullable: bool = False):
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=nullable)


def _vault_ref(name: str):
    return sa.Column(name, sa.Integer(), sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True)


def _status(prefix: str) -> list:
    return [sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name=f"ck_my_{prefix}_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name=f"ck_my_{prefix}_dates"),
            sa.CheckConstraint("status <> 'ACTIVE' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name=f"ck_my_{prefix}_four_eyes")]


def _standard_indexes(table: str) -> None:
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
    """Give each table this revision creates the policy d7f9b1c3e5a6 derives."""
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

    # 1) Shared tables: nullable Malaysia columns only.
    if "my_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("my_calculation_snapshot", _json(), nullable=True))
    if "my_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("my_approval_fingerprint", sa.String(64), nullable=True))

    # 2) payroll_my_identifier_vault (WORKER) — first: profiles reference it.
    t = VAULT
    if not _has_table(t):
        op.create_table(
            "payroll_my_identifier_vault",
            *_common(t),
            _employee(),
            sa.Column("identifier_type", sa.String(12), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=True),
            sa.Column("key_version", sa.SmallInteger(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False, server_default="PAYROLL_STATUTORY"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint(f"identifier_type IN {_in(IDENTIFIER_TYPES)}", name="ck_my_vault_identifier_type"),
            sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_my_vault_status"),
            sa.CheckConstraint("deleted_at IS NOT NULL OR ciphertext IS NOT NULL",
                               name="ck_my_vault_ciphertext_or_deleted"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_identifier_vault_employee_id", ["employee_id"])
    _index(t, "uq_my_vault_one_active_employee_identifier", ["organization_id", "employee_id", "identifier_type"],
           unique=True, where="status = 'ACTIVE'")
    _index(t, "uq_my_vault_fingerprint", ["organization_id", "identifier_type", "fingerprint"], unique=True,
           where="status = 'ACTIVE'")

    # 3) payroll_my_identifier_access_events (WORKER, append-only; no updated_at)
    t = ACCESS_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_my_identifier_access_events",
            *_common(t, with_updated=False),
            _employee(nullable=True),
            sa.Column("vault_id", sa.Integer(), sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.CheckConstraint("action IN ('CREATE', 'REVEAL_REQUESTED', 'REVEAL_APPROVED', 'REVEALED', "
                               "'EXPORTED', 'DELETED', 'ROTATED')", name="ck_my_vault_event_action"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_identifier_access_events_employee_id", ["employee_id"])
    _index(t, "ix_payroll_my_identifier_access_events_vault_id", ["vault_id"])

    # 4) payroll_my_employer_registrations (TENANT)
    t = EMPLOYERS
    if not _has_table(t):
        op.create_table(
            "payroll_my_employer_registrations",
            *_common(t),
            *_effective(),
            sa.Column("legal_name", sa.String(200), nullable=False),
            sa.Column("hasil_employer_no", sa.String(20), nullable=False),
            sa.Column("epf_employer_no", sa.String(20), nullable=True),
            sa.Column("perkeso_employer_code", sa.String(20), nullable=True),
            sa.Column("hrd_category", sa.String(20), nullable=False),
            sa.Column("hrd_registration_no", sa.String(20), nullable=True),
            sa.Column("hrd_category_from", sa.Date(), nullable=True),
            sa.Column("hrd_category_evidence_ref", sa.String(300), nullable=True),
            sa.Column("my_journal_accounts", _json(), nullable=True),
            sa.Column("bank_export_ref", sa.String(100), nullable=True),
            sa.Column("filing_credential_ref", sa.String(100), nullable=True),
            sa.Column("verification_state", sa.String(12), nullable=False, server_default="UNVERIFIED"),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            *_status("employer"),
            sa.CheckConstraint(f"hrd_category IN {_in(HRD_CATEGORIES)}", name="ck_my_employer_hrd_category"),
            sa.CheckConstraint("hrd_category = 'NOT_REGISTERED' OR (hrd_registration_no IS NOT NULL AND "
                               "hrd_category_from IS NOT NULL AND hrd_category_evidence_ref IS NOT NULL)",
                               name="ck_my_employer_hrd_evidence"),
            sa.CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
                               name="ck_my_employer_verification"),
        )
    _standard_indexes(t)
    _index(t, "ix_my_employer_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_my_employer_one_active_entity", ["organization_id", "legal_entity_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NOT NULL")
    _index(t, "uq_my_employer_one_active_org", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NULL")

    # 5) payroll_my_worker_profiles (WORKER, effective-dated)
    t = PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_my_worker_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("contract_type", sa.String(20), nullable=False),
            sa.Column("pay_frequency", sa.String(12), nullable=False),
            sa.Column("citizenship", sa.String(20), nullable=True),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.Column("tax_residence", sa.String(16), nullable=False, server_default="REVIEW_REQUIRED"),
            sa.Column("residence_evidence_ref", sa.String(300), nullable=True),
            sa.Column("residence_from", sa.Date(), nullable=True),
            sa.Column("residence_to", sa.Date(), nullable=True),
            sa.Column("work_pass_type", sa.String(28), nullable=True),
            sa.Column("work_pass_valid_from", sa.Date(), nullable=True),
            sa.Column("work_pass_valid_to", sa.Date(), nullable=True),
            sa.Column("epf_member_class", sa.String(28), nullable=True),
            sa.Column("epf_member_since", sa.Date(), nullable=True),
            sa.Column("socso_category", sa.String(22), nullable=True),
            sa.Column("eis_state", sa.String(18), nullable=True),
            sa.Column("manual_worker", sa.Boolean(), nullable=True),
            sa.Column("normal_hours_week", sa.Numeric(5, 2), nullable=True),
            sa.Column("rest_day", sa.String(3), nullable=True),
            sa.Column("service_start", sa.Date(), nullable=True),
            _vault_ref("nric_vault_id"),
            _vault_ref("tin_vault_id"),
            _vault_ref("epf_vault_id"),
            _vault_ref("socso_vault_id"),
            _vault_ref("work_pass_vault_id"),
            *_status("worker_profile"),
            sa.CheckConstraint(f"contract_type IN {_in(CONTRACT_TYPES)}", name="ck_my_worker_contract_type"),
            sa.CheckConstraint(f"pay_frequency IN {_in(PAY_FREQUENCIES)}", name="ck_my_worker_pay_frequency"),
            sa.CheckConstraint(f"citizenship IS NULL OR citizenship IN {_in(CITIZENSHIP)}",
                               name="ck_my_worker_citizenship"),
            sa.CheckConstraint(f"tax_residence IN {_in(TAX_RESIDENCE)}", name="ck_my_worker_tax_residence"),
            sa.CheckConstraint("tax_residence = 'REVIEW_REQUIRED' OR (residence_evidence_ref IS NOT NULL AND "
                               "residence_from IS NOT NULL)", name="ck_my_worker_residence_evidence"),
            sa.CheckConstraint("residence_to IS NULL OR residence_from IS NULL OR residence_to >= residence_from",
                               name="ck_my_worker_residence_dates"),
            sa.CheckConstraint(f"work_pass_type IS NULL OR work_pass_type IN {_in(WORK_PASS_TYPES)}",
                               name="ck_my_worker_work_pass_type"),
            sa.CheckConstraint("citizenship IS DISTINCT FROM 'NON_CITIZEN' OR (work_pass_type IS NOT NULL AND "
                               "work_pass_type <> 'NONE')", name="ck_my_worker_non_citizen_pass"),
            sa.CheckConstraint("work_pass_valid_to IS NULL OR work_pass_valid_from IS NULL OR "
                               "work_pass_valid_to >= work_pass_valid_from", name="ck_my_worker_pass_dates"),
            sa.CheckConstraint(f"epf_member_class IS NULL OR epf_member_class IN {_in(EPF_MEMBER_CLASSES)}",
                               name="ck_my_worker_epf_class"),
            sa.CheckConstraint(f"socso_category IS NULL OR socso_category IN {_in(SOCSO_CATEGORIES)}",
                               name="ck_my_worker_socso_category"),
            sa.CheckConstraint(f"eis_state IS NULL OR eis_state IN {_in(EIS_STATES)}", name="ck_my_worker_eis_state"),
            sa.CheckConstraint("normal_hours_week IS NULL OR normal_hours_week > 0", name="ck_my_worker_hours"),
            sa.CheckConstraint(f"rest_day IS NULL OR rest_day IN {_in(REST_DAYS)}", name="ck_my_worker_rest_day"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_worker_profiles_employee_id", ["employee_id"])
    _index(t, "ix_my_worker_profile_employee_period", ["employee_id", "effective_from"])

    # 6) payroll_my_work_assignments (WORKER, effective-dated; MY-001 / MY-003)
    t = ASSIGNMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_my_work_assignments",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("labour_territory", sa.String(20), nullable=False),
            sa.Column("holiday_state", sa.String(3), nullable=False),
            sa.Column("work_location_label", sa.String(200), nullable=True),
            sa.Column("remote", sa.Boolean(), nullable=True),
            sa.Column("assignment_reason", sa.String(12), nullable=False),
            *_status("assignment"),
            sa.CheckConstraint(f"labour_territory IN {_in(TERRITORIES)}", name="ck_my_assignment_territory"),
            sa.CheckConstraint(f"holiday_state IN {_in(HOLIDAY_STATES)}", name="ck_my_assignment_holiday_state"),
            sa.CheckConstraint(f"assignment_reason IN {_in(ASSIGNMENT_REASONS)}", name="ck_my_assignment_reason"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_work_assignments_employee_id", ["employee_id"])
    _index(t, "ix_my_assignment_employee_period", ["employee_id", "effective_from"])

    # 7) payroll_my_tax_declarations (WORKER; MY-010)
    t = DECLARATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_my_tax_declarations",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("declaration_type", sa.String(24), nullable=False),
            sa.Column("tax_year", sa.SmallInteger(), nullable=False),
            sa.Column("value", _json(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_channel", sa.String(16), nullable=False),
            sa.Column("superseded_by_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="RECEIVED"),
            sa.CheckConstraint(f"declaration_type IN {_in(DECLARATION_TYPES)}", name="ck_my_declaration_type"),
            sa.CheckConstraint("source_channel IN ('PAPER', 'ELECTRONIC', 'EMPLOYEE_PORTAL', 'AUTHORITY', 'IMPORT')",
                               name="ck_my_declaration_channel"),
            sa.CheckConstraint("status IN ('RECEIVED', 'APPROVED', 'WITHDRAWN', 'SUPERSEDED', 'REJECTED')",
                               name="ck_my_declaration_status"),
            sa.CheckConstraint("evidence_ref IS NOT NULL", name="ck_my_declaration_evidence"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_my_declaration_dates"),
            sa.CheckConstraint("status <> 'APPROVED' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_my_declaration_four_eyes"),
            sa.CheckConstraint("status <> 'WITHDRAWN' OR withdrawn_at IS NOT NULL", name="ck_my_declaration_withdrawn"),
            sa.CheckConstraint("status <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
                               name="ck_my_declaration_superseded"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_tax_declarations_employee_id", ["employee_id"])
    _index(t, "ix_my_declaration_lookup", ["employee_id", "declaration_type", "tax_year", "effective_from"])

    # 8) payroll_my_accumulator_entries (WORKER, append-only ledger; no updated_at)
    t = LEDGER
    if not _has_table(t):
        op.create_table(
            "payroll_my_accumulator_entries",
            *_common(t, with_updated=False),
            _employee(),
            sa.Column("year", sa.SmallInteger(), nullable=False),
            sa.Column("accumulator", sa.String(28), nullable=False),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("entry_kind", sa.String(16), nullable=False),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reverses_id", sa.Integer(), sa.ForeignKey(f"{LEDGER}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("declaration_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("result_hash", sa.String(64), nullable=True),
            sa.CheckConstraint(f"accumulator IN {_in(ACCUMULATORS)}", name="ck_my_accum_accumulator"),
            sa.CheckConstraint("entry_kind IN ('RUN', 'CORRECTION', 'PRIOR_EMPLOYER', 'OPENING_BALANCE')",
                               name="ck_my_accum_kind"),
            sa.CheckConstraint("entry_kind NOT IN ('PRIOR_EMPLOYER', 'OPENING_BALANCE') OR "
                               "(evidence_ref IS NOT NULL AND approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_my_accum_evidence_four_eyes"),
            sa.CheckConstraint(f"entry_kind <> 'PRIOR_EMPLOYER' OR accumulator IN {_in(TP3_ACCUMULATORS)}",
                               name="ck_my_accum_prior_employer_tp3_only"),
            sa.CheckConstraint("entry_kind <> 'RUN' OR payslip_item_id IS NOT NULL", name="ck_my_accum_run_payslip"),
            sa.CheckConstraint("entry_kind <> 'CORRECTION' OR reverses_id IS NOT NULL OR run_id IS NOT NULL",
                               name="ck_my_accum_correction_link"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_my_accumulator_entries_employee_id", ["employee_id"])
    _index(t, "ix_my_accum_lookup", ["employee_id", "legal_entity_id", "year", "accumulator", "pay_date"])
    _index(t, "uq_my_accum_payslip_accumulator", ["payslip_item_id", "accumulator"], unique=True,
           where="entry_kind = 'RUN'")

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "my_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "my_approval_fingerprint")
    if "my_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "my_calculation_snapshot")

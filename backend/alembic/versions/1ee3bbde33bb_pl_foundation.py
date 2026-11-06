"""pl_foundation: Poland employer/worker statutory tables, identifier vault, declarations, PPK, ledger

Revision ID: 1ee3bbde33bb
Revises: a8cde2482ef0
Create Date: 2026-11-05

ZP-PL-ENG-001 Phase 2 (database). Additive only: seven new payroll_pl_* tables
and two nullable shared columns; no existing row is touched.

  payroll_pl_identifier_vault           encrypted PESEL / employee NIP (subject
      EMPLOYEE) and the employer's ZUS contribution account NRS (subject
      EMPLOYER): ciphertext only, key version, keyed HMAC fingerprint
      (duplicate detection), purpose, collection/deletion audit (spec §13,
      PL-025).
  payroll_pl_identifier_access_events   append-only audit of create / reveal
      request / reveal approval / reveal / export / delete / key rotation.
  payroll_pl_employer_registrations     per legal employer (PL-001): legal
      name, NIP / REGON / KRS (public registers), NRS (vault reference),
      tax-office code, ZUS deadline class, accident rate + its source and
      contribution-year window, small-payer flag, PPK institution and the
      employer's additional PPK rate, FP/FS and FGSP applicability, journal
      accounts, credential REFERENCES (never secrets), verification state;
      effective-dated, one ACTIVE open row per (organisation, legal entity).
  payroll_pl_worker_profiles            effective-dated coverage facts (spec §3):
      contract type, ZUS insurance title code, pension / disability / sickness /
      accident / health applicability (three-state: NULL = not known -> the
      engine BLOCKS), FTE, working-time system, residency, student / pensioner,
      other insurance titles + evidence, A1 certificate, FEP qualification +
      evidence + window, named fund exemption, service credit, vault refs.
  payroll_pl_declarations               PL-005: every PIT / PPK / cap statement
      with received_at, effective_from/to, evidence, source channel,
      superseded_by and actor; four-eyes approval; never edited in place.
  payroll_pl_ppk_participations         PPK state machine (spec §7): state,
      enrolment date, notice state, opt-out declaration, next re-enrolment
      checkpoint. Rates come from declarations and the employer row.
  payroll_pl_accumulator_entries        append-only ledger behind cumulative
      PIT, costs, PIT-0 exempt income per relief, the 30x pension/disability
      cap bases, employer sick days and PPK totals (spec §11 Accumulator);
      prior-employer cap evidence and opening balances need evidence and a
      second approver (PL-010); corrections are linked compensating entries.

Shared tables (nullable columns only):
  payslip_items.pl_calculation_snapshot   frozen PL inputs + result + trace.
  payroll_runs.pl_approval_fingerprint    approval bound to those snapshots.

No statutory rate, threshold or cap appears in any CHECK constraint (spec
page 1): the constraints enforce enumerations, evidence and date order only.

Row-level security (ZP-PRIV d7f9b1c3e5a6 covers only tables that existed when
it ran): employer registrations get TENANT; the six worker tables get the
WORKER "org" policy d7f9b1c3e5a6's classify() derives. PostgreSQL only;
tests/test_poland_migrations.py proves classify() agrees. Literal table and
column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1ee3bbde33bb"
down_revision: Union[str, Sequence[str], None] = "a8cde2482ef0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VAULT = "payroll_pl_identifier_vault"
ACCESS_EVENTS = "payroll_pl_identifier_access_events"
EMPLOYERS = "payroll_pl_employer_registrations"
PROFILES = "payroll_pl_worker_profiles"
DECLARATIONS = "payroll_pl_declarations"
PPK = "payroll_pl_ppk_participations"
LEDGER = "payroll_pl_accumulator_entries"

TENANT_TABLES = (EMPLOYERS,)
WORKER_TABLES = (VAULT, ACCESS_EVENTS, PROFILES, DECLARATIONS, PPK, LEDGER)
# Drop order (children first).
_TABLES = (LEDGER, PPK, DECLARATIONS, PROFILES, EMPLOYERS, ACCESS_EVENTS, VAULT)
PAYSLIPS, RUNS = "payslip_items", "payroll_runs"

# Vocabularies (mirror engine/countries/poland_content.py; no values).
CONTRACT_TYPES = ("UMOWA_O_PRACE", "UMOWA_ZLECENIE", "UMOWA_O_DZIELO", "MANAGEMENT_CONTRACT", "BOARD_REMUNERATION")
DECLARATION_TYPES = ("PIT2", "COSTS_COMMUTER", "COSTS_MULTIPLE", "PIT0_UNDER26", "PIT0_RETURN", "PIT0_FAMILY4",
                     "PIT0_SENIOR", "PIT0_WAIVER", "HIGHER_RATE_REQUEST", "PPK_OPT_OUT", "PPK_REDUCED_RATE",
                     "PPK_ADDITIONAL", "PRIOR_EMPLOYER_CAP")
PPK_STATES = ("NOT_ELIGIBLE", "ELIGIBLE_NOT_ENROLLED", "ENROLLED", "OPTED_OUT", "SUSPENDED_BY_LAW", "ENDED")
ACCUMULATORS = ("PIT_TAXABLE_INCOME", "PIT_ADVANCE", "PIT_COSTS_USED", "PIT0_EXEMPT_UNDER26", "PIT0_EXEMPT_RETURN",
                "PIT0_EXEMPT_FAMILY4", "PIT0_EXEMPT_SENIOR", "ZUS_CAP_PENSION_BASE", "ZUS_CAP_DISABILITY_BASE",
                "SICK_DAYS_EMPLOYER", "PPK_EMPLOYEE", "PPK_EMPLOYER")


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
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name=f"ck_pl_{prefix}_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name=f"ck_pl_{prefix}_dates"),
            sa.CheckConstraint("status <> 'ACTIVE' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name=f"ck_pl_{prefix}_four_eyes")]


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

    # 1) Shared tables: nullable Poland columns only.
    if "pl_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("pl_calculation_snapshot", _json(), nullable=True))
    if "pl_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("pl_approval_fingerprint", _json(), nullable=True))

    # 2) payroll_pl_identifier_vault (WORKER) — first: employer and worker rows reference it.
    t = VAULT
    if not _has_table(t):
        op.create_table(
            "payroll_pl_identifier_vault",
            *_common(t),
            _employee(nullable=True),
            sa.Column("subject_type", sa.String(10), nullable=False),
            sa.Column("identifier_type", sa.String(8), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=True),
            sa.Column("key_version", sa.SmallInteger(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False, server_default="PAYROLL_STATUTORY"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint("subject_type IN ('EMPLOYEE', 'EMPLOYER')", name="ck_pl_vault_subject_type"),
            sa.CheckConstraint("(subject_type = 'EMPLOYEE' AND employee_id IS NOT NULL AND "
                               "identifier_type IN ('PESEL', 'NIP')) OR "
                               "(subject_type = 'EMPLOYER' AND employee_id IS NULL AND identifier_type = 'NRS')",
                               name="ck_pl_vault_subject_identifier"),
            sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_pl_vault_status"),
            sa.CheckConstraint("deleted_at IS NOT NULL OR ciphertext IS NOT NULL",
                               name="ck_pl_vault_ciphertext_or_deleted"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_identifier_vault_employee_id", ["employee_id"])
    _index(t, "uq_pl_vault_one_active_employee_identifier", ["organization_id", "employee_id", "identifier_type"],
           unique=True, where="status = 'ACTIVE' AND subject_type = 'EMPLOYEE'")
    _index(t, "uq_pl_vault_fingerprint", ["organization_id", "identifier_type", "fingerprint"], unique=True,
           where="status = 'ACTIVE'")

    # 3) payroll_pl_identifier_access_events (WORKER, append-only; no updated_at)
    t = ACCESS_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_identifier_access_events",
            *_common(t, with_updated=False),
            _employee(nullable=True),
            sa.Column("vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.CheckConstraint("action IN ('CREATE', 'REVEAL_REQUESTED', 'REVEAL_APPROVED', 'REVEALED', "
                               "'EXPORTED', 'DELETED', 'ROTATED')", name="ck_pl_vault_event_action"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_identifier_access_events_employee_id", ["employee_id"])
    _index(t, "ix_payroll_pl_identifier_access_events_vault_id", ["vault_id"])

    # 4) payroll_pl_employer_registrations (TENANT)
    t = EMPLOYERS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_employer_registrations",
            *_common(t),
            *_effective(),
            sa.Column("legal_name", sa.String(200), nullable=False),
            sa.Column("nip", sa.String(10), nullable=False),
            sa.Column("regon", sa.String(14), nullable=True),
            sa.Column("krs", sa.String(10), nullable=True),
            sa.Column("nrs_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("tax_office_code", sa.String(10), nullable=True),
            sa.Column("zus_deadline_class", sa.String(6), nullable=False),
            sa.Column("zus_deadline_evidence_ref", sa.String(300), nullable=True),
            sa.Column("accident_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("accident_rate_source", sa.String(20), nullable=True),
            sa.Column("accident_rate_from", sa.Date(), nullable=True),
            sa.Column("accident_rate_to", sa.Date(), nullable=True),
            sa.Column("accident_rate_evidence_ref", sa.String(300), nullable=True),
            sa.Column("small_payer", sa.Boolean(), nullable=True),
            sa.Column("ppk_institution", sa.String(200), nullable=True),
            sa.Column("ppk_agreement_ref", sa.String(100), nullable=True),
            sa.Column("ppk_employer_additional_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("fp_fs_applicable", sa.Boolean(), nullable=True),
            sa.Column("fgsp_applicable", sa.Boolean(), nullable=True),
            sa.Column("pl_journal_accounts", _json(), nullable=True),
            sa.Column("bank_export_ref", sa.String(100), nullable=True),
            sa.Column("filing_credential_ref", sa.String(100), nullable=True),
            sa.Column("verification_state", sa.String(12), nullable=False, server_default="UNVERIFIED"),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            *_status("employer"),
            sa.CheckConstraint("zus_deadline_class IN ('DAY_5', 'DAY_15', 'DAY_20')",
                               name="ck_pl_employer_deadline_class"),
            sa.CheckConstraint("(accident_rate_pct IS NULL) = (accident_rate_source IS NULL)",
                               name="ck_pl_employer_accident_source"),
            sa.CheckConstraint("accident_rate_source IS NULL OR accident_rate_source IN "
                               "('ZUS_NOTICE', 'SELF_DETERMINED', 'SMALL_PAYER_DEFAULT')",
                               name="ck_pl_employer_accident_source_enum"),
            sa.CheckConstraint("accident_rate_pct IS NULL OR (accident_rate_from IS NOT NULL AND "
                               "accident_rate_evidence_ref IS NOT NULL)", name="ck_pl_employer_accident_window"),
            sa.CheckConstraint("accident_rate_to IS NULL OR accident_rate_to >= accident_rate_from",
                               name="ck_pl_employer_accident_dates"),
            sa.CheckConstraint("accident_rate_pct IS NULL OR accident_rate_pct > 0",
                               name="ck_pl_employer_accident_positive"),
            sa.CheckConstraint("ppk_employer_additional_pct IS NULL OR ppk_employer_additional_pct >= 0",
                               name="ck_pl_employer_ppk_additional"),
            sa.CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
                               name="ck_pl_employer_verification"),
        )
    _standard_indexes(t)
    _index(t, "ix_pl_employer_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_pl_employer_one_active_entity", ["organization_id", "legal_entity_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NOT NULL")
    _index(t, "uq_pl_employer_one_active_org", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NULL")

    # 5) payroll_pl_worker_profiles (WORKER, effective-dated)
    t = PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_pl_worker_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("contract_type", sa.String(20), nullable=False),
            sa.Column("insurance_title_code", sa.String(6), nullable=True),
            sa.Column("cov_pension", sa.Boolean(), nullable=True),
            sa.Column("cov_disability", sa.Boolean(), nullable=True),
            sa.Column("cov_sickness", sa.Boolean(), nullable=True),
            sa.Column("cov_accident", sa.Boolean(), nullable=True),
            sa.Column("cov_health", sa.Boolean(), nullable=True),
            sa.Column("fte_numerator", sa.SmallInteger(), nullable=True),
            sa.Column("fte_denominator", sa.SmallInteger(), nullable=True),
            sa.Column("working_time_system", sa.String(30), nullable=True),
            sa.Column("pay_frequency", sa.String(12), nullable=False, server_default="MONTHLY"),
            sa.Column("tax_residency", sa.String(14), nullable=False, server_default="RESIDENT"),
            sa.Column("is_student", sa.Boolean(), nullable=True),
            sa.Column("is_pensioner", sa.Boolean(), nullable=True),
            sa.Column("other_titles_declared", sa.Boolean(), nullable=True),
            sa.Column("other_titles_evidence_ref", sa.String(300), nullable=True),
            sa.Column("a1_certificate", sa.Boolean(), nullable=True),
            sa.Column("fep_qualifying", sa.Boolean(), nullable=True),
            sa.Column("fep_evidence_ref", sa.String(300), nullable=True),
            sa.Column("fep_from", sa.Date(), nullable=True),
            sa.Column("fep_to", sa.Date(), nullable=True),
            sa.Column("fund_exemption_code", sa.String(40), nullable=True),
            sa.Column("fund_exemption_evidence_ref", sa.String(300), nullable=True),
            sa.Column("service_credit_months", sa.Integer(), nullable=True),
            sa.Column("pesel_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("nip_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            *_status("worker_profile"),
            sa.CheckConstraint(f"contract_type IN {_in(CONTRACT_TYPES)}", name="ck_pl_worker_contract_type"),
            sa.CheckConstraint("insurance_title_code IS NULL OR length(insurance_title_code) = 6",
                               name="ck_pl_worker_title_code"),
            sa.CheckConstraint("(fte_numerator IS NULL) = (fte_denominator IS NULL)", name="ck_pl_worker_fte_pair"),
            sa.CheckConstraint("fte_denominator IS NULL OR (fte_denominator > 0 AND fte_numerator > 0 AND "
                               "fte_numerator <= fte_denominator)", name="ck_pl_worker_fte_range"),
            sa.CheckConstraint("pay_frequency IN ('MONTHLY', 'WEEKLY', 'FORTNIGHTLY', 'OTHER')",
                               name="ck_pl_worker_pay_frequency"),
            sa.CheckConstraint("tax_residency IN ('RESIDENT', 'NON_RESIDENT')", name="ck_pl_worker_residency"),
            sa.CheckConstraint("other_titles_declared IS NOT TRUE OR other_titles_evidence_ref IS NOT NULL",
                               name="ck_pl_worker_other_titles_evidence"),
            sa.CheckConstraint("fep_qualifying IS NOT TRUE OR (fep_evidence_ref IS NOT NULL AND fep_from IS NOT NULL)",
                               name="ck_pl_worker_fep_evidence"),
            sa.CheckConstraint("fep_to IS NULL OR fep_from IS NULL OR fep_to >= fep_from", name="ck_pl_worker_fep_dates"),
            sa.CheckConstraint("fund_exemption_code IS NULL OR fund_exemption_evidence_ref IS NOT NULL",
                               name="ck_pl_worker_exemption_evidence"),
            sa.CheckConstraint("service_credit_months IS NULL OR service_credit_months >= 0",
                               name="ck_pl_worker_service_credit"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_worker_profiles_employee_id", ["employee_id"])
    _index(t, "ix_pl_worker_profile_employee_period", ["employee_id", "effective_from"])

    # 6) payroll_pl_declarations (WORKER, PL-005)
    t = DECLARATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_declarations",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("declaration_type", sa.String(24), nullable=False),
            sa.Column("value", _json(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_channel", sa.String(16), nullable=False),
            sa.Column("superseded_by_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="RECEIVED"),
            sa.CheckConstraint(f"declaration_type IN {_in(DECLARATION_TYPES)}", name="ck_pl_declaration_type"),
            sa.CheckConstraint("source_channel IN ('PAPER', 'ELECTRONIC', 'EMPLOYEE_PORTAL', 'IMPORT')",
                               name="ck_pl_declaration_channel"),
            sa.CheckConstraint("status IN ('RECEIVED', 'APPROVED', 'WITHDRAWN', 'SUPERSEDED', 'REJECTED')",
                               name="ck_pl_declaration_status"),
            sa.CheckConstraint("evidence_ref IS NOT NULL", name="ck_pl_declaration_evidence"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_pl_declaration_dates"),
            sa.CheckConstraint("status <> 'APPROVED' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_pl_declaration_four_eyes"),
            sa.CheckConstraint("status <> 'WITHDRAWN' OR withdrawn_at IS NOT NULL", name="ck_pl_declaration_withdrawn"),
            sa.CheckConstraint("status <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
                               name="ck_pl_declaration_superseded"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_declarations_employee_id", ["employee_id"])
    _index(t, "ix_pl_declaration_lookup", ["employee_id", "declaration_type", "effective_from"])

    # 7) payroll_pl_ppk_participations (WORKER, effective-dated state machine)
    t = PPK
    if not _has_table(t):
        op.create_table(
            "payroll_pl_ppk_participations",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("state", sa.String(22), nullable=False),
            sa.Column("enrolment_date", sa.Date(), nullable=True),
            sa.Column("notice_state", sa.String(14), nullable=True),
            sa.Column("opt_out_declaration_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("next_reenrolment_date", sa.Date(), nullable=True),
            *_status("ppk"),
            sa.CheckConstraint(f"state IN {_in(PPK_STATES)}", name="ck_pl_ppk_state"),
            sa.CheckConstraint("notice_state IS NULL OR notice_state IN ('NOT_SENT', 'SENT', 'ACKNOWLEDGED')",
                               name="ck_pl_ppk_notice_state"),
            sa.CheckConstraint("state <> 'ENROLLED' OR enrolment_date IS NOT NULL", name="ck_pl_ppk_enrolled_date"),
            sa.CheckConstraint("state <> 'OPTED_OUT' OR opt_out_declaration_id IS NOT NULL",
                               name="ck_pl_ppk_opt_out_declaration"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_ppk_participations_employee_id", ["employee_id"])
    _index(t, "ix_pl_ppk_employee_period", ["employee_id", "effective_from"])

    # 8) payroll_pl_accumulator_entries (WORKER, append-only ledger; no updated_at)
    t = LEDGER
    if not _has_table(t):
        op.create_table(
            "payroll_pl_accumulator_entries",
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
            sa.Column("reverses_id", sa.Integer(),
                      sa.ForeignKey(f"{LEDGER}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("declaration_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("result_hash", sa.String(64), nullable=True),
            sa.CheckConstraint(f"accumulator IN {_in(ACCUMULATORS)}", name="ck_pl_accum_accumulator"),
            sa.CheckConstraint("entry_kind IN ('RUN', 'CORRECTION', 'PRIOR_EMPLOYER', 'OPENING_BALANCE')",
                               name="ck_pl_accum_kind"),
            sa.CheckConstraint("entry_kind NOT IN ('PRIOR_EMPLOYER', 'OPENING_BALANCE') OR "
                               "(evidence_ref IS NOT NULL AND approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_pl_accum_evidence_four_eyes"),
            sa.CheckConstraint("entry_kind <> 'PRIOR_EMPLOYER' OR accumulator IN "
                               "('ZUS_CAP_PENSION_BASE', 'ZUS_CAP_DISABILITY_BASE')",
                               name="ck_pl_accum_prior_employer_cap_only"),
            sa.CheckConstraint("entry_kind <> 'RUN' OR payslip_item_id IS NOT NULL", name="ck_pl_accum_run_payslip"),
            sa.CheckConstraint("entry_kind <> 'CORRECTION' OR reverses_id IS NOT NULL OR run_id IS NOT NULL",
                               name="ck_pl_accum_correction_link"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_pl_accumulator_entries_employee_id", ["employee_id"])
    _index(t, "ix_pl_accum_lookup", ["employee_id", "legal_entity_id", "year", "accumulator", "pay_date"])
    _index(t, "uq_pl_accum_payslip_accumulator", ["payslip_item_id", "accumulator"], unique=True,
           where="entry_kind = 'RUN'")

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "pl_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "pl_approval_fingerprint")
    if "pl_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "pl_calculation_snapshot")

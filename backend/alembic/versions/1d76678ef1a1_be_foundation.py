"""be_foundation: Belgium employer/worker statutory tables, identifier vault, schedules, classifications, ledger

Revision ID: 1d76678ef1a1
Revises: f3a9c1d7e2b4 (re-chained from efc56f3235e2 when origin/main, which added
f3a9c1d7e2b4 payslip templates, was merged into nikhil; never applied anywhere before)
Create Date: 2026-11-11

ZP-BE-ENG-001 Phase 2 (database). Additive only: nine new payroll_be_* tables
and two nullable shared columns; no existing row is touched. No be_* column is
added to payroll_employees or payroll_employee_statutory_profiles (D2).

  payroll_be_identifier_vault           encrypted NISS / INSZ or BIS number
      (subject EMPLOYEE) and the employer's ONSS number (subject EMPLOYER):
      ciphertext only, key version, keyed HMAC fingerprint (duplicate
      detection), purpose, collection/deletion audit (spec §15, BE-040). One
      ACTIVE identifier per employee per type. The enterprise number is a
      public register number and is NOT a vault type.
  payroll_be_identifier_access_events   append-only audit of create / reveal
      request / reveal approval / reveal / export / delete / key rotation.
  payroll_be_employer_registrations     per legal employer (BE-001, BE-038):
      legal name, enterprise number (plain, public register), ONSS number
      (vault reference), ONSS employer category (NULL = not decided -> the
      resolver BLOCKS), professional-withholding declaration frequency
      (BE-013: never assumed), holiday fund reference, legal language
      (NL / FR / DE), mandate and filing credential REFERENCES (never secrets),
      verification state, source document; effective-dated, one ACTIVE open
      row per (organisation, legal entity).
  payroll_be_establishment_units        establishment units of a registration
      (BE-001, BE-038): unit number, name, address, region; effective-dated,
      one ACTIVE open row per (registration, unit number).
  payroll_be_worker_profiles            effective-dated worker statutory profile
      (BE-002): worker category separate from the contract, ONSS worker code,
      tax status, residency, special status (unsupported -> BLOCK, D6), NISS
      vault reference; one ACTIVE open row per employee.
  payroll_be_work_schedules             explicit work-schedule objects (BE-022):
      EFFECTIVE / AVERAGE regime, weekly hours, day pattern, reference period.
  payroll_be_employment_classifications effective-dated classification (BE-003,
      BE-020): employment line, establishment unit, Joint Committee /
      sub-committee, CBA pack (payroll_collective_agreements, D3), function
      class, seniority, governing schedule; one ACTIVE open row per
      (employee, employment line).
  payroll_be_declarations               every payroll-affecting worker statement
      (spec §5 stages 1 and 5, BE-012) with received_at, effective_from/to,
      evidence, source channel, superseded_by and actor; four-eyes approval;
      never edited in place.
  payroll_be_accumulator_entries        append-only ledger (BE-017) keyed by
      employee + legal entity + employment line + year + accumulator, with the
      ONSS quarter and the source period the remuneration relates to (BE-009);
      regular and exceptional withholding accumulate separately (BE-011);
      year = calendar year except HOLIDAY_PAY_BASE = holiday service year
      (BE-024); employer totals are aggregated, never stored. PRIOR_EMPLOYER
      entries are blocked; opening balances need evidence and a second
      approver; corrections are linked compensating entries.

Shared tables (nullable columns only):
  payslip_items.be_calculation_snapshot   frozen BE inputs + result + trace.
  payroll_runs.be_approval_fingerprint    approval bound to those snapshots.

No statutory rate, threshold, band or date appears in any CHECK constraint
(ZP-BE-ENG-001 §3): the constraints enforce enumerations, evidence, date
order and four-eyes only.

Row-level security (ZP-PRIV d7f9b1c3e5a6 covers only tables that existed when
it ran): employer registrations and establishment units get TENANT; the seven
worker tables get the WORKER "org" policy d7f9b1c3e5a6's classify() derives.
PostgreSQL only; tests/test_belgium_migrations.py proves classify() agrees.
Literal table and column names so scripts/drift_pending_filter explains every
change. PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1d76678ef1a1"
down_revision: Union[str, Sequence[str], None] = "f3a9c1d7e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VAULT = "payroll_be_identifier_vault"
ACCESS_EVENTS = "payroll_be_identifier_access_events"
EMPLOYERS = "payroll_be_employer_registrations"
UNITS = "payroll_be_establishment_units"
PROFILES = "payroll_be_worker_profiles"
SCHEDULES = "payroll_be_work_schedules"
CLASSIFICATIONS = "payroll_be_employment_classifications"
DECLARATIONS = "payroll_be_declarations"
LEDGER = "payroll_be_accumulator_entries"

TENANT_TABLES = (EMPLOYERS, UNITS)
WORKER_TABLES = (VAULT, ACCESS_EVENTS, PROFILES, SCHEDULES, CLASSIFICATIONS, DECLARATIONS, LEDGER)
# Drop order (children first).
_TABLES = (LEDGER, DECLARATIONS, CLASSIFICATIONS, SCHEDULES, PROFILES, UNITS, EMPLOYERS, ACCESS_EVENTS, VAULT)
PAYSLIPS, RUNS = "payslip_items", "payroll_runs"

# Vocabularies (mirror models._BE_*; no statutory values).
WORKER_CATEGORIES = ("MANUAL", "EMPLOYEE", "APPRENTICE", "STUDENT", "FLEXI", "OCCASIONAL", "OTHER")
DECLARATION_TYPES = ("FAMILY_SITUATION", "DEPENDANTS", "NON_RESIDENT_STATUS", "WORK_BONUS_FISCAL_ELECTION")
ACCUMULATORS = ("WITHHOLDING_TAXABLE", "WITHHOLDING", "WITHHOLDING_EXCEPTIONAL_TAXABLE", "WITHHOLDING_EXCEPTIONAL",
                "ONSS_EMPLOYEE_BASE", "ONSS_EMPLOYEE", "ONSS_EMPLOYER_BASE", "ONSS_MANUAL_108_BASE",
                "WORK_BONUS_SOCIAL", "WORK_BONUS_FISCAL", "HOLIDAY_PAY_BASE")
SCHEDULE_REGIMES = ("EFFECTIVE", "AVERAGE")

_ACTIVE_OPEN = "status = 'ACTIVE' AND effective_to IS NULL"


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
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name=f"ck_be_{prefix}_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name=f"ck_be_{prefix}_dates"),
            sa.CheckConstraint("status <> 'ACTIVE' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name=f"ck_be_{prefix}_four_eyes")]


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

    # 1) Shared tables: nullable Belgium columns only.
    if "be_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("be_calculation_snapshot", _json(), nullable=True))
    if "be_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("be_approval_fingerprint", _json(), nullable=True))

    # 2) payroll_be_identifier_vault (WORKER) — first: employer and worker rows reference it.
    t = VAULT
    if not _has_table(t):
        op.create_table(
            "payroll_be_identifier_vault",
            *_common(t),
            _employee(nullable=True),
            sa.Column("subject_type", sa.String(10), nullable=False),
            sa.Column("identifier_type", sa.String(10), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=True),
            sa.Column("key_version", sa.SmallInteger(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False, server_default="PAYROLL_STATUTORY"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
            sa.CheckConstraint("subject_type IN ('EMPLOYEE', 'EMPLOYER')", name="ck_be_vault_subject_type"),
            sa.CheckConstraint("(subject_type = 'EMPLOYEE' AND employee_id IS NOT NULL AND "
                               "identifier_type IN ('NISS', 'BIS')) OR "
                               "(subject_type = 'EMPLOYER' AND employee_id IS NULL AND identifier_type = 'ONSS')",
                               name="ck_be_vault_subject_identifier"),
            sa.CheckConstraint("status IN ('ACTIVE', 'DELETED')", name="ck_be_vault_status"),
            sa.CheckConstraint("deleted_at IS NOT NULL OR ciphertext IS NOT NULL",
                               name="ck_be_vault_ciphertext_or_deleted"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_identifier_vault_employee_id", ["employee_id"])
    _index(t, "uq_be_vault_one_active_employee_identifier", ["organization_id", "employee_id", "identifier_type"],
           unique=True, where="status = 'ACTIVE' AND subject_type = 'EMPLOYEE'")
    _index(t, "uq_be_vault_fingerprint", ["organization_id", "identifier_type", "fingerprint"], unique=True,
           where="status = 'ACTIVE'")

    # 3) payroll_be_identifier_access_events (WORKER, append-only; no updated_at)
    t = ACCESS_EVENTS
    if not _has_table(t):
        op.create_table(
            "payroll_be_identifier_access_events",
            *_common(t, with_updated=False),
            _employee(nullable=True),
            sa.Column("vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=True),
            sa.Column("reason", sa.String(300), nullable=True),
            sa.CheckConstraint("action IN ('CREATE', 'REVEAL_REQUESTED', 'REVEAL_APPROVED', 'REVEALED', "
                               "'EXPORTED', 'DELETED', 'ROTATED')", name="ck_be_vault_event_action"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_identifier_access_events_employee_id", ["employee_id"])
    _index(t, "ix_payroll_be_identifier_access_events_vault_id", ["vault_id"])

    # 4) payroll_be_employer_registrations (TENANT)
    t = EMPLOYERS
    if not _has_table(t):
        op.create_table(
            "payroll_be_employer_registrations",
            *_common(t),
            *_effective(),
            sa.Column("legal_name", sa.String(200), nullable=False),
            sa.Column("enterprise_number", sa.String(12), nullable=False),
            sa.Column("onss_number_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("employer_category_code", sa.String(10), nullable=True),
            sa.Column("withholding_declaration_frequency", sa.String(20), nullable=True),
            sa.Column("holiday_fund_ref", sa.String(100), nullable=True),
            sa.Column("legal_language", sa.String(2), nullable=True),
            sa.Column("mandate_refs", _json(), nullable=True),
            sa.Column("filing_credential_ref", sa.String(100), nullable=True),
            sa.Column("verification_state", sa.String(12), nullable=False, server_default="UNVERIFIED"),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            *_status("employer"),
            sa.CheckConstraint("legal_language IS NULL OR legal_language IN ('NL', 'FR', 'DE')",
                               name="ck_be_employer_legal_language"),
            sa.CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
                               name="ck_be_employer_verification"),
        )
    _standard_indexes(t)
    _index(t, "ix_be_employer_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_be_employer_one_active_entity", ["organization_id", "legal_entity_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NOT NULL")
    _index(t, "uq_be_employer_one_active_org", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL AND legal_entity_id IS NULL")

    # 5) payroll_be_establishment_units (TENANT)
    t = UNITS
    if not _has_table(t):
        op.create_table(
            "payroll_be_establishment_units",
            *_common(t),
            sa.Column("registration_id", sa.Integer(),
                      sa.ForeignKey(f"{EMPLOYERS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("unit_number", sa.String(20), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("address", _json(), nullable=True),
            sa.Column("region", sa.String(40), nullable=True),
            *_effective(),
            *_status("unit"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_establishment_units_registration_id", ["registration_id"])
    _index(t, "uq_be_unit_one_active", ["registration_id", "unit_number"], unique=True, where=_ACTIVE_OPEN)

    # 6) payroll_be_worker_profiles (WORKER, effective-dated)
    t = PROFILES
    if not _has_table(t):
        op.create_table(
            "payroll_be_worker_profiles",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("worker_category", sa.String(12), nullable=False),
            sa.Column("onss_worker_code", sa.String(4), nullable=True),
            sa.Column("tax_status", sa.String(30), nullable=True),
            sa.Column("residency", sa.String(14), nullable=True),
            sa.Column("special_status", sa.String(30), nullable=True),
            sa.Column("niss_vault_id", sa.Integer(),
                      sa.ForeignKey(f"{VAULT}.id", ondelete="SET NULL"), nullable=True),
            *_status("worker_profile"),
            sa.CheckConstraint(f"worker_category IN {_in(WORKER_CATEGORIES)}", name="ck_be_worker_category"),
            sa.CheckConstraint("residency IS NULL OR residency IN ('RESIDENT', 'NON_RESIDENT')",
                               name="ck_be_worker_residency"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_worker_profiles_employee_id", ["employee_id"])
    _index(t, "ix_be_worker_profile_employee_period", ["employee_id", "effective_from"])
    _index(t, "uq_be_worker_profile_one_active", ["organization_id", "employee_id"], unique=True, where=_ACTIVE_OPEN)

    # 7) payroll_be_work_schedules (WORKER, effective-dated)
    t = SCHEDULES
    if not _has_table(t):
        op.create_table(
            "payroll_be_work_schedules",
            *_common(t),
            _employee(),
            sa.Column("regime", sa.String(10), nullable=False),
            sa.Column("weekly_hours", sa.Numeric(5, 2), nullable=False),
            sa.Column("days_pattern", _json(), nullable=True),
            sa.Column("reference_period", sa.String(20), nullable=True),
            *_effective(),
            *_status("schedule"),
            sa.CheckConstraint(f"regime IN {_in(SCHEDULE_REGIMES)}", name="ck_be_schedule_regime"),
            sa.CheckConstraint("weekly_hours > 0", name="ck_be_schedule_hours_positive"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_work_schedules_employee_id", ["employee_id"])
    _index(t, "ix_be_schedule_employee_period", ["employee_id", "effective_from"])

    # 8) payroll_be_employment_classifications (WORKER, effective-dated)
    t = CLASSIFICATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_be_employment_classifications",
            *_common(t),
            _employee(),
            sa.Column("employment_line", sa.String(40), nullable=False),
            sa.Column("establishment_unit_id", sa.Integer(),
                      sa.ForeignKey(f"{UNITS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("joint_committee", sa.String(10), nullable=True),
            sa.Column("sub_committee", sa.String(10), nullable=True),
            sa.Column("collective_agreement_id", sa.Integer(),
                      sa.ForeignKey("payroll_collective_agreements.id", ondelete="SET NULL"), nullable=True),
            sa.Column("function_class", sa.String(40), nullable=True),
            sa.Column("seniority_months", sa.Integer(), nullable=True),
            sa.Column("work_schedule_id", sa.Integer(),
                      sa.ForeignKey(f"{SCHEDULES}.id", ondelete="SET NULL"), nullable=True),
            *_effective(),
            *_status("classification"),
            sa.CheckConstraint("seniority_months IS NULL OR seniority_months >= 0",
                               name="ck_be_classification_seniority"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_employment_classifications_employee_id", ["employee_id"])
    _index(t, "ix_be_classification_employee_period", ["employee_id", "effective_from"])
    _index(t, "uq_be_classification_one_active_line", ["organization_id", "employee_id", "employment_line"],
           unique=True, where=_ACTIVE_OPEN)

    # 9) payroll_be_declarations (WORKER)
    t = DECLARATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_be_declarations",
            *_common(t),
            _employee(),
            *_effective(),
            sa.Column("declaration_type", sa.String(32), nullable=False),
            sa.Column("value", _json(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_channel", sa.String(16), nullable=False),
            sa.Column("superseded_by_id", sa.Integer(),
                      sa.ForeignKey(f"{DECLARATIONS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="RECEIVED"),
            sa.CheckConstraint(f"declaration_type IN {_in(DECLARATION_TYPES)}", name="ck_be_declaration_type"),
            sa.CheckConstraint("source_channel IN ('PAPER', 'ELECTRONIC', 'EMPLOYEE_PORTAL', 'IMPORT')",
                               name="ck_be_declaration_channel"),
            sa.CheckConstraint("status IN ('RECEIVED', 'APPROVED', 'WITHDRAWN', 'SUPERSEDED', 'REJECTED')",
                               name="ck_be_declaration_status"),
            sa.CheckConstraint("evidence_ref IS NOT NULL", name="ck_be_declaration_evidence"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_be_declaration_dates"),
            sa.CheckConstraint("status <> 'APPROVED' OR (approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_be_declaration_four_eyes"),
            sa.CheckConstraint("status <> 'WITHDRAWN' OR withdrawn_at IS NOT NULL", name="ck_be_declaration_withdrawn"),
            sa.CheckConstraint("status <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
                               name="ck_be_declaration_superseded"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_declarations_employee_id", ["employee_id"])
    _index(t, "ix_be_declaration_lookup", ["employee_id", "declaration_type", "effective_from"])

    # 10) payroll_be_accumulator_entries (WORKER, append-only ledger; no updated_at)
    t = LEDGER
    if not _has_table(t):
        op.create_table(
            "payroll_be_accumulator_entries",
            *_common(t, with_updated=False),
            _employee(),
            sa.Column("employment_line", sa.String(40), nullable=True),
            sa.Column("year", sa.SmallInteger(), nullable=False),
            sa.Column("quarter", sa.SmallInteger(), nullable=True),
            sa.Column("accumulator", sa.String(32), nullable=False),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("source_period_start", sa.Date(), nullable=True),
            sa.Column("source_period_end", sa.Date(), nullable=True),
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
            sa.CheckConstraint(f"accumulator IN {_in(ACCUMULATORS)}", name="ck_be_accum_accumulator"),
            sa.CheckConstraint("entry_kind IN ('RUN', 'CORRECTION', 'PRIOR_EMPLOYER', 'OPENING_BALANCE')",
                               name="ck_be_accum_kind"),
            # Blocked for Belgium; a later migration may allow it per accumulator
            # once signed content needs it.
            sa.CheckConstraint("entry_kind <> 'PRIOR_EMPLOYER'", name="ck_be_accum_no_prior_employer"),
            sa.CheckConstraint("entry_kind <> 'OPENING_BALANCE' OR "
                               "(evidence_ref IS NOT NULL AND approved_by_id IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_be_accum_evidence_four_eyes"),
            sa.CheckConstraint("entry_kind <> 'RUN' OR payslip_item_id IS NOT NULL", name="ck_be_accum_run_payslip"),
            sa.CheckConstraint("entry_kind <> 'CORRECTION' OR reverses_id IS NOT NULL OR run_id IS NOT NULL",
                               name="ck_be_accum_correction_link"),
            sa.CheckConstraint("quarter IS NULL OR quarter BETWEEN 1 AND 4", name="ck_be_accum_quarter"),
            sa.CheckConstraint("(source_period_start IS NULL) = (source_period_end IS NULL)",
                               name="ck_be_accum_source_period_pair"),
            sa.CheckConstraint("source_period_end IS NULL OR source_period_start IS NULL OR "
                               "source_period_end >= source_period_start", name="ck_be_accum_source_period_order"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_accumulator_entries_employee_id", ["employee_id"])
    _index(t, "ix_be_accum_lookup",
           ["employee_id", "legal_entity_id", "employment_line", "year", "accumulator", "pay_date"])
    _index(t, "uq_be_accum_payslip_accumulator", ["payslip_item_id", "accumulator"], unique=True,
           where="entry_kind = 'RUN'")

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "be_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "be_approval_fingerprint")
    if "be_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "be_calculation_snapshot")

"""za_foundation: South Africa statutory-profile columns, snapshot/fingerprint, four ZA tables

Revision ID: 447f57564983
Revises: b9f3d5a1c7e2 (re-parented from 8f90dde5f7b5 at the 2026-10-26 merge of main; never applied)
Create Date: 2026-10-26

ZP-ZA-ENG-001 Phase 2 (database). "ZA" is South Africa ("SA" is Saudi Arabia).

  payroll_employee_statutory_profiles  + 13 nullable za_* columns — the
      effective-dated employee tax facts the engine resolves before it
      calculates (ZA-005): employment type, residency, director, medical
      scheme membership / dependants, travel business use, UIF exclusion,
      ETI eligibility, SEZ flag, voluntary additional PAYE, evidence. Identity
      and tax numbers are NOT here — they live in compliance_fields (masked).
  payslip_items.za_calculation_snapshot   frozen ZA inputs + result + trace (ZA-009)
  payroll_runs.za_approval_fingerprint    approval bound to inputs + pack (ZA-016)
  payroll_za_employer_registrations  PAYE / UIF / SDL / COIDA references, SDL
      liability and ETI registration, effective-dated per organisation (ZA-011)
  payroll_za_tax_directives          SARS tax directives with evidence and
      approval; never generalised into a rule (ZA-007)
  payroll_za_eti_ledger              ETI per employee per claim month, the
      qualifying-month history (spec §4)
  payroll_za_sars_artifacts          EMP201 / EMP501 / IRP5 / IT3(a) artefacts:
      BRS version, payload + SHA-256, validation, receipt, supersession —
      a rejected payload is never overwritten (ZA-015, ZA-019, ZA-020)

Additive only: nullable columns and new tables; no existing row is touched.
Row-level security (ZP-PRIV d7f9b1c3e5a6 covers only tables that existed when
it ran): each new table gets the policy d7f9b1c3e5a6's classify() derives —
TENANT for employer registrations and SARS artefacts, WORKER/"org" for tax
directives and the ETI ledger (they carry employee_id) — PostgreSQL only;
tests/test_south_africa_migrations.py proves classify() agrees. Literal table
and column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "447f57564983"
down_revision: Union[str, Sequence[str], None] = "b9f3d5a1c7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE, PAYSLIPS, RUNS = "payroll_employee_statutory_profiles", "payslip_items", "payroll_runs"
REGISTRATIONS = "payroll_za_employer_registrations"
DIRECTIVES = "payroll_za_tax_directives"
ETI = "payroll_za_eti_ledger"
ARTIFACTS = "payroll_za_sars_artifacts"
_TABLES = (ARTIFACTS, ETI, DIRECTIVES, REGISTRATIONS)

_PROFILE_COLUMNS = (
    ("za_employment_type", sa.String(20)),
    ("za_tax_residency", sa.String(20)),
    ("za_is_director", sa.Boolean()),
    ("za_medical_scheme_member", sa.Boolean()),
    ("za_medical_dependants", sa.SmallInteger()),
    ("za_travel_business_use_80", sa.Boolean()),
    ("za_uif_excluded", sa.Boolean()),
    ("za_uif_exclusion_reason", sa.String(100)),
    ("za_eti_eligible", sa.Boolean()),
    ("za_eti_first_qualifying_month", sa.Date()),
    ("za_sez_employee", sa.Boolean()),
    ("za_voluntary_additional_paye", sa.Numeric(12, 2)),
    ("za_evidence_ref", sa.String(300)),
)


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


def _stamps():
    return [sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)]


def _org():
    return sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                     nullable=False)


def _employee():
    return sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                     nullable=False)


def _user(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give each table this revision creates the policy d7f9b1c3e5a6
    derives for it (tests/test_south_africa_migrations.py proves classify()
    agrees), on THESE tables only, as br_employer_m2."""
    rls = _rls_module()
    for table, predicate in ((REGISTRATIONS, rls._TENANT_PREDICATE), (ARTIFACTS, rls._TENANT_PREDICATE),
                             (DIRECTIVES, rls._worker_predicate("org")), (ETI, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # ── 1) Shared tables: nullable ZA columns only ────────────────────────
    # One literal op.add_column per column: scripts/drift_pending_filter reads
    # these sources as text and must see every table/column name.
    present = _columns(PROFILE)
    if "za_employment_type" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_employment_type", sa.String(20), nullable=True))
    if "za_tax_residency" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_tax_residency", sa.String(20), nullable=True))
    if "za_is_director" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_is_director", sa.Boolean(), nullable=True))
    if "za_medical_scheme_member" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_medical_scheme_member", sa.Boolean(), nullable=True))
    if "za_medical_dependants" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_medical_dependants", sa.SmallInteger(), nullable=True))
    if "za_travel_business_use_80" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_travel_business_use_80", sa.Boolean(), nullable=True))
    if "za_uif_excluded" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_uif_excluded", sa.Boolean(), nullable=True))
    if "za_uif_exclusion_reason" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_uif_exclusion_reason", sa.String(100), nullable=True))
    if "za_eti_eligible" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_eti_eligible", sa.Boolean(), nullable=True))
    if "za_eti_first_qualifying_month" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_eti_first_qualifying_month", sa.Date(), nullable=True))
    if "za_sez_employee" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_sez_employee", sa.Boolean(), nullable=True))
    if "za_voluntary_additional_paye" not in present:
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("za_voluntary_additional_paye", sa.Numeric(12, 2), nullable=True))
    if "za_evidence_ref" not in present:
        op.add_column("payroll_employee_statutory_profiles", sa.Column("za_evidence_ref", sa.String(300), nullable=True))
    if "za_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("za_calculation_snapshot", _json(), nullable=True))
    if "za_approval_fingerprint" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("za_approval_fingerprint", _json(), nullable=True))

    # ── 2) payroll_za_employer_registrations (TENANT) ─────────────────────
    t = REGISTRATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_za_employer_registrations",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("paye_reference", sa.String(20), nullable=False),
            sa.Column("uif_reference", sa.String(20), nullable=True),
            sa.Column("sdl_reference", sa.String(20), nullable=True),
            sa.Column("coida_reference", sa.String(30), nullable=True),
            sa.Column("sdl_liable", sa.Boolean(), nullable=False),
            sa.Column("sdl_exemption_reason", sa.String(200), nullable=True),
            sa.Column("eti_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sector_code", sa.String(50), nullable=True),
            sa.Column("bargaining_council", sa.String(200), nullable=True),
            sa.Column("evidence_ref", sa.String(300), nullable=True),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("previous_version_id", sa.Integer(),
                      sa.ForeignKey("payroll_za_employer_registrations.id", ondelete="SET NULL"), nullable=True),
            *_stamps(),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_za_registration_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_za_registration_dates"),
            sa.CheckConstraint("sdl_liable OR sdl_exemption_reason IS NOT NULL",
                               name="ck_za_registration_sdl_exemption"),
        )
    _index(t, "ix_payroll_za_employer_registrations_id", ["id"])
    _index(t, "ix_payroll_za_employer_registrations_organization_id", ["organization_id"])
    _index(t, "ix_za_registration_org_period", ["organization_id", "effective_from"])
    _index(t, "uq_za_registration_one_active", ["organization_id"], unique=True,
           where="status = 'ACTIVE' AND effective_to IS NULL")

    # ── 3) payroll_za_tax_directives (WORKER / org) ───────────────────────
    t = DIRECTIVES
    if not _has_table(t):
        op.create_table(
            "payroll_za_tax_directives",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            _employee(),
            sa.Column("directive_number", sa.String(30), nullable=False),
            sa.Column("directive_type", sa.String(20), nullable=False),
            sa.Column("rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("tax_year", sa.String(10), nullable=False),
            sa.Column("issue_date", sa.Date(), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("instruction", sa.String(500), nullable=True),
            sa.Column("evidence_artifact_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("evidence_sha256", sa.String(64), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="CAPTURED"),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_payslip_item_id", sa.Integer(),
                      sa.ForeignKey("payslip_items.id", ondelete="SET NULL"), nullable=True),
            *_stamps(),
            sa.CheckConstraint("directive_type IN ('FIXED_PERCENTAGE', 'FIXED_AMOUNT', 'LUMP_SUM', 'OTHER')",
                               name="ck_za_directive_type"),
            sa.CheckConstraint("status IN ('CAPTURED', 'APPROVED', 'APPLIED', 'EXPIRED', 'REVOKED')",
                               name="ck_za_directive_status"),
            sa.CheckConstraint("rate_pct IS NOT NULL OR amount IS NOT NULL", name="ck_za_directive_value"),
            sa.CheckConstraint("rate_pct IS NULL OR (rate_pct >= 0 AND rate_pct <= 100)",
                               name="ck_za_directive_rate"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_za_directive_dates"),
        )
    _index(t, "ix_payroll_za_tax_directives_id", ["id"])
    _index(t, "ix_payroll_za_tax_directives_organization_id", ["organization_id"])
    _index(t, "ix_payroll_za_tax_directives_employee_id", ["employee_id"])
    _index(t, "uq_za_directive_number", ["organization_id", "directive_number"], unique=True)

    # ── 4) payroll_za_eti_ledger (WORKER / org) ───────────────────────────
    t = ETI
    if not _has_table(t):
        op.create_table(
            "payroll_za_eti_ledger",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            _employee(),
            sa.Column("claim_month", sa.Date(), nullable=False),
            sa.Column("qualifying_month_no", sa.SmallInteger(), nullable=False),
            sa.Column("paid_hours", sa.Numeric(7, 2), nullable=False),
            sa.Column("remuneration", sa.Numeric(14, 2), nullable=False),
            sa.Column("normalised_remuneration", sa.Numeric(14, 2), nullable=False),
            sa.Column("eti_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="CALCULATED"),
            sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("reverses_id", sa.Integer(), sa.ForeignKey("payroll_za_eti_ledger.id", ondelete="SET NULL"),
                      nullable=True),
            *_stamps(),
            sa.CheckConstraint("status IN ('CALCULATED', 'CLAIMED', 'REVERSED')", name="ck_za_eti_status"),
            sa.CheckConstraint("qualifying_month_no >= 1", name="ck_za_eti_month_no"),
            sa.CheckConstraint("eti_amount >= 0 AND paid_hours >= 0 AND remuneration >= 0",
                               name="ck_za_eti_amounts"),
        )
    _index(t, "ix_payroll_za_eti_ledger_id", ["id"])
    _index(t, "ix_payroll_za_eti_ledger_organization_id", ["organization_id"])
    _index(t, "ix_payroll_za_eti_ledger_employee_id", ["employee_id"])
    _index(t, "uq_za_eti_employee_month", ["employee_id", "claim_month"], unique=True,
           where="status <> 'REVERSED'")

    # ── 5) payroll_za_sars_artifacts (TENANT) ─────────────────────────────
    t = ARTIFACTS
    if not _has_table(t):
        op.create_table(
            "payroll_za_sars_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            _org(),
            sa.Column("artifact_type", sa.String(20), nullable=False),
            sa.Column("period_key", sa.String(20), nullable=False),
            sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("brs_version", sa.String(20), nullable=True),
            sa.Column("payload", _json(), nullable=True),
            sa.Column("payload_sha256", sa.String(64), nullable=False),
            sa.Column("validation_status", sa.String(12), nullable=False, server_default="PENDING"),
            sa.Column("validation_errors", _json(), nullable=True),
            sa.Column("submission_channel", sa.String(20), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.Column("external_response", _json(), nullable=True),
            sa.Column("source_run_ids", _json(), nullable=True),
            sa.Column("supersedes_id", sa.Integer(),
                      sa.ForeignKey("payroll_za_sars_artifacts.id", ondelete="SET NULL"), nullable=True),
            _user("approved_by_id"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
            sa.CheckConstraint("artifact_type IN ('EMP201', 'EMP501_INTERIM', 'EMP501_ANNUAL', 'IRP5', 'IT3A', "
                               "'CANCELLATION')", name="ck_za_artifact_type"),
            sa.CheckConstraint("status IN ('DRAFT', 'VALIDATED', 'APPROVED', 'SUBMITTED', 'ACCEPTED', 'REJECTED', "
                               "'SUPERSEDED')", name="ck_za_artifact_status"),
            sa.CheckConstraint("validation_status IN ('PENDING', 'PASSED', 'FAILED')",
                               name="ck_za_artifact_validation"),
            sa.CheckConstraint("submission_channel IS NULL OR submission_channel IN ('EASYFILE', 'EFILING')",
                               name="ck_za_artifact_channel"),
            sa.CheckConstraint("version >= 1", name="ck_za_artifact_version"),
        )
    _index(t, "ix_payroll_za_sars_artifacts_id", ["id"])
    _index(t, "ix_payroll_za_sars_artifacts_organization_id", ["organization_id"])
    _index(t, "uq_za_artifact_version", ["organization_id", "artifact_type", "period_key", "version"], unique=True)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if "za_approval_fingerprint" in _columns(RUNS):
        op.drop_column(RUNS, "za_approval_fingerprint")
    if "za_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "za_calculation_snapshot")
    present = _columns(PROFILE)
    for name, _type in reversed(_PROFILE_COLUMNS):
        if name in present:
            op.drop_column(PROFILE, name)

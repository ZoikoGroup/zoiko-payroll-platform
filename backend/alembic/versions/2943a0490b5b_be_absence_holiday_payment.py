"""be_absence_holiday_payment: Belgium absence episodes, holiday certificates, payment batches, component mappings

Revision ID: 2943a0490b5b
Revises: 1d76678ef1a1
Create Date: 2026-11-12

ZP-BE-ENG-001 Block B (the block's single migration). Additive only: five new
payroll_be_* tables, nullable / defaulted columns on three Phase 2 Belgium
tables and six more ledger accumulators. No shared (non-Belgium) table is
touched.

New tables
  payroll_be_absence_episodes       (WORKER) kind, start / end, worker category
      at start, cause_link_id (relapse), different_cause flag, day-band
      responsibility JSON, certificate REFERENCE, evidence; NO diagnosis or
      medical field (spec §9, BE-029 .. BE-032); four-eyes; cancellation keeps
      the row with its reason.
  payroll_be_holiday_certificates   (WORKER) direction IN / OUT, service year,
      amounts, prior employer reference; four-eyes; immutable after approval
      (enforced in belgium_service; a correction is a new version).
  payroll_be_payment_batches        (TENANT) mirror of payroll_nl_payment_batches
      (D13) plus a four-eyes approval before submission.
  payroll_be_payment_items          (WORKER) mirror of payroll_nl_payment_items
      (tokenised IBAN only) plus organization_id and the payslip link.
  payroll_be_component_mappings     (TENANT) G-28: organisation mapping of a
      platform pay component to a Belgian component code; versioned, four-eyes,
      one ACTIVE open row per (organisation, source, key).

Columns on existing Belgium tables (Block B decisions)
  payroll_be_worker_profiles.pay_basis                     G-22 (NULL blocks)
  payroll_be_employment_classifications.contract_type,
      contract_start_date, contract_end_date               G-23 (NULL type blocks)
  payroll_be_employer_registrations.onss_special_160_status
      (default UNKNOWN, which blocks), special_160_evidence_ref     G-25

Ledger: ck_be_accum_accumulator gains OVERTIME_HOURS, COMPENSATORY_REST_HOURS,
HOLIDAY_SIMPLE_PAID, HOLIDAY_DOUBLE_PAID, ADDITIONAL_HOLIDAY_ADVANCE,
GUARANTEED_SALARY_DAYS. PostgreSQL replaces the constraint; SQLite cannot alter
a CHECK constraint without rebuilding the table (and would lose the partial
unique index), so on SQLite the old constraint stays (tests build their schema
from the models, which carry the new list).

No statutory rate, threshold, band or date appears in any CHECK constraint
(ZP-BE-ENG-001 §3). Row-level security: the policy d7f9b1c3e5a6's classify()
derives, on the new tables only (PostgreSQL). Literal names, lock_timeout,
idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2943a0490b5b"
down_revision: Union[str, Sequence[str], None] = "1d76678ef1a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EPISODES = "payroll_be_absence_episodes"
CERTIFICATES = "payroll_be_holiday_certificates"
BATCHES = "payroll_be_payment_batches"
ITEMS = "payroll_be_payment_items"
MAPPINGS = "payroll_be_component_mappings"
EMPLOYERS = "payroll_be_employer_registrations"
PROFILES = "payroll_be_worker_profiles"
CLASSIFICATIONS = "payroll_be_employment_classifications"
LEDGER = "payroll_be_accumulator_entries"

TENANT_TABLES = (BATCHES, MAPPINGS)
WORKER_TABLES = (EPISODES, CERTIFICATES, ITEMS)
_TABLES = (ITEMS, BATCHES, MAPPINGS, CERTIFICATES, EPISODES)          # drop order (children first)

# Vocabularies (mirror models._BE_*; no statutory values).
WORKER_CATEGORIES = ("MANUAL", "EMPLOYEE", "APPRENTICE", "STUDENT", "FLEXI", "OCCASIONAL", "OTHER")
PAY_BASES = ("SALARIED", "HOURLY")
CONTRACT_TYPES = ("INDEFINITE", "FIXED_TERM", "SPECIFIC_WORK", "REPLACEMENT", "STUDENT", "FLEXI", "OCCASIONAL",
                  "APPRENTICESHIP", "NOT_SUPPORTED")
SPECIAL_160_STATUSES = ("APPLIES", "NOT_APPLICABLE", "UNKNOWN")
ABSENCE_KINDS = ("SICKNESS", "WORK_ACCIDENT", "OCCUPATIONAL_DISEASE", "MATERNITY", "BIRTH_LEAVE", "OTHER_LEAVE")
COMPONENTS = ("SALARY", "HOURLY_PAY", "OVERTIME_PREMIUM", "SUNDAY_HOLIDAY_PREMIUM", "SECTOR_PREMIUM", "BONUS",
              "THIRTEENTH_MONTH", "HOLIDAY_PAY_SIMPLE", "HOLIDAY_PAY_DOUBLE", "DEPARTURE_HOLIDAY_PAY",
              "GUARANTEED_SALARY", "BIRTH_LEAVE_PAY", "BENEFIT_IN_KIND", "MEAL_VOUCHER_EMPLOYER", "ECOCHEQUE",
              "REIMBURSEMENT", "ARREARS", "PROFIT_SHARING")
COMPONENT_SOURCES = ("PLATFORM_FIELD", "POLICY_ALLOWANCE")
OLD_ACCUMULATORS = ("WITHHOLDING_TAXABLE", "WITHHOLDING", "WITHHOLDING_EXCEPTIONAL_TAXABLE", "WITHHOLDING_EXCEPTIONAL",
                    "ONSS_EMPLOYEE_BASE", "ONSS_EMPLOYEE", "ONSS_EMPLOYER_BASE", "ONSS_MANUAL_108_BASE",
                    "WORK_BONUS_SOCIAL", "WORK_BONUS_FISCAL", "HOLIDAY_PAY_BASE")
NEW_ACCUMULATORS = OLD_ACCUMULATORS + ("OVERTIME_HOURS", "COMPENSATORY_REST_HOURS", "HOLIDAY_SIMPLE_PAID",
                                       "HOLIDAY_DOUBLE_PAID", "ADDITIONAL_HOLIDAY_ADVANCE", "GUARANTEED_SALARY_DAYS")

_ACTIVE_OPEN = "status = 'ACTIVE' AND effective_to IS NULL"
_FOUR_EYES = "(approved_by_id IS NOT NULL AND (created_by_id IS NULL OR approved_by_id <> created_by_id))"


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


def _common(table: str):
    """id / tenant / legal employer / evidence / version / approval / stamps."""
    return [
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _employee(nullable=False):
    return sa.Column("employee_id", sa.Integer(),
                     sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=nullable)


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

    # 1) Decision columns on Phase 2 Belgium tables. Literal op.add_column calls
    #    (scripts/drift_pending_filter explains them); column CHECKs travel with
    #    the column on both dialects; the two-column contract date check is a
    #    table constraint on PostgreSQL and inline on SQLite.
    if "pay_basis" not in _columns(PROFILES):
        op.add_column("payroll_be_worker_profiles", sa.Column(
            "pay_basis", sa.String(10),
            sa.CheckConstraint(f"pay_basis IS NULL OR pay_basis IN {_in(PAY_BASES)}", name="ck_be_worker_pay_basis"),
            nullable=True))
    if "contract_type" not in _columns(CLASSIFICATIONS):
        op.add_column("payroll_be_employment_classifications", sa.Column(
            "contract_type", sa.String(16),
            sa.CheckConstraint(f"contract_type IS NULL OR contract_type IN {_in(CONTRACT_TYPES)}",
                               name="ck_be_classification_contract_type"), nullable=True))
    if "contract_start_date" not in _columns(CLASSIFICATIONS):
        op.add_column("payroll_be_employment_classifications", sa.Column("contract_start_date", sa.Date(),
                                                                         nullable=True))
    dates_check = ("contract_end_date IS NULL OR contract_start_date IS NULL OR "
                   "contract_end_date >= contract_start_date")
    if "contract_end_date" not in _columns(CLASSIFICATIONS):
        if _postgres():
            op.add_column("payroll_be_employment_classifications", sa.Column("contract_end_date", sa.Date(),
                                                                             nullable=True))
            op.create_check_constraint("ck_be_classification_contract_dates", CLASSIFICATIONS, dates_check)
        else:
            op.add_column("payroll_be_employment_classifications", sa.Column(
                "contract_end_date", sa.Date(),
                sa.CheckConstraint(dates_check, name="ck_be_classification_contract_dates"), nullable=True))
    if "onss_special_160_status" not in _columns(EMPLOYERS):
        op.add_column("payroll_be_employer_registrations", sa.Column(
            "onss_special_160_status", sa.String(16),
            sa.CheckConstraint(f"onss_special_160_status IN {_in(SPECIAL_160_STATUSES)}",
                               name="ck_be_employer_special_160_status"),
            nullable=False, server_default="UNKNOWN"))
    if "special_160_evidence_ref" not in _columns(EMPLOYERS):
        op.add_column("payroll_be_employer_registrations", sa.Column("special_160_evidence_ref", sa.String(300),
                                                                     nullable=True))

    # 2) Ledger accumulators (PostgreSQL; see the docstring for SQLite).
    if _postgres():
        op.execute(sa.text(f'ALTER TABLE "{LEDGER}" DROP CONSTRAINT IF EXISTS ck_be_accum_accumulator'))
        op.create_check_constraint("ck_be_accum_accumulator", LEDGER, f"accumulator IN {_in(NEW_ACCUMULATORS)}")

    # 3) payroll_be_absence_episodes (WORKER)
    t = EPISODES
    if not _has_table(t):
        op.create_table(
            "payroll_be_absence_episodes",
            *_common(t),
            _employee(),
            sa.Column("employment_line", sa.String(40), nullable=True),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("worker_category_at_start", sa.String(12), nullable=False),
            sa.Column("cause_link_id", sa.Integer(), sa.ForeignKey(f"{EPISODES}.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("different_cause", sa.Boolean(), nullable=True),
            sa.Column("day_band_responsibility", _json(), nullable=True),
            sa.Column("certificate_ref", sa.String(100), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("cancelled_reason", sa.String(300), nullable=True),
            sa.CheckConstraint(f"kind IN {_in(ABSENCE_KINDS)}", name="ck_be_absence_kind"),
            sa.CheckConstraint(f"worker_category_at_start IN {_in(WORKER_CATEGORIES)}",
                               name="ck_be_absence_worker_category"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'CANCELLED')", name="ck_be_absence_status"),
            sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_be_absence_dates"),
            sa.CheckConstraint(f"status <> 'ACTIVE' OR {_FOUR_EYES}", name="ck_be_absence_four_eyes"),
            sa.CheckConstraint("status <> 'CANCELLED' OR cancelled_reason IS NOT NULL", name="ck_be_absence_cancelled"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_absence_episodes_employee_id", ["employee_id"])
    _index(t, "ix_be_absence_employee_start", ["employee_id", "start_date"])

    # 4) payroll_be_holiday_certificates (WORKER)
    t = CERTIFICATES
    if not _has_table(t):
        op.create_table(
            "payroll_be_holiday_certificates",
            *_common(t),
            _employee(),
            sa.Column("direction", sa.String(3), nullable=False),
            sa.Column("service_year", sa.SmallInteger(), nullable=False),
            sa.Column("issued_on", sa.Date(), nullable=True),
            sa.Column("gross_base_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("simple_pay_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("double_pay_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("days_paid", sa.Numeric(6, 2), nullable=True),
            sa.Column("prior_employer_ref", sa.String(200), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("direction IN ('IN', 'OUT')", name="ck_be_holiday_cert_direction"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')", name="ck_be_holiday_cert_status"),
            sa.CheckConstraint(f"status = 'DRAFT' OR {_FOUR_EYES}", name="ck_be_holiday_cert_four_eyes"),
            sa.CheckConstraint("direction <> 'IN' OR prior_employer_ref IS NOT NULL", name="ck_be_holiday_cert_prior"),
            sa.CheckConstraint("(gross_base_amount IS NULL OR gross_base_amount >= 0) AND "
                               "(simple_pay_amount IS NULL OR simple_pay_amount >= 0) AND "
                               "(double_pay_amount IS NULL OR double_pay_amount >= 0) AND "
                               "(days_paid IS NULL OR days_paid >= 0)", name="ck_be_holiday_cert_amounts"),
        )
    _standard_indexes(t)
    _index(t, "ix_payroll_be_holiday_certificates_employee_id", ["employee_id"])
    _index(t, "ix_be_holiday_cert_employee_year", ["employee_id", "service_year"])

    # 5) payroll_be_payment_batches (TENANT; mirror of payroll_nl_payment_batches + approval)
    t = BATCHES
    if not _has_table(t):
        op.create_table(
            "payroll_be_payment_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("pain001_sha256", sa.String(64), nullable=False),
            sa.Column("message_id", sa.String(100), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
            sa.Column("pain001_xml", sa.Text(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=True),
            sa.Column("batch_kind", sa.String(20), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("idempotency_key", sa.String(100), nullable=False),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUBMITTED', 'ACCEPTED', 'SETTLED', 'REJECTED', "
                               "'RETURNED', 'UNKNOWN')", name="ck_be_payment_batch_status"),
            sa.CheckConstraint(f"status = 'DRAFT' OR {_FOUR_EYES}", name="ck_be_payment_batch_four_eyes"),
        )
    _index(t, "ix_payroll_be_payment_batches_id", ["id"])
    _index(t, "ix_payroll_be_payment_batches_organization_id", ["organization_id"])
    _index(t, "ix_payroll_be_payment_batches_payroll_run_id", ["payroll_run_id"])
    _index(t, "ix_payroll_be_payment_batches_pain001_sha256", ["pain001_sha256"], unique=True)
    _index(t, "ix_payroll_be_payment_batches_message_id", ["message_id"])
    _index(t, "ix_payroll_be_payment_batches_idempotency_key", ["idempotency_key"], unique=True)
    _index(t, "ix_be_payment_batch_org_run", ["organization_id", "payroll_run_id"])

    # 6) payroll_be_payment_items (WORKER; mirror of payroll_nl_payment_items)
    t = ITEMS
    if not _has_table(t):
        op.create_table(
            "payroll_be_payment_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey(f"{BATCHES}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=True),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("iban_token", sa.String(200), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("end_to_end_id", sa.String(100), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("return_reason", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("status IN ('PENDING', 'SENT', 'SETTLED', 'RETURNED', 'REJECTED')",
                               name="ck_be_payment_item_status"),
            sa.CheckConstraint("amount > 0", name="ck_be_payment_item_amount"),
        )
    _index(t, "ix_payroll_be_payment_items_id", ["id"])
    _index(t, "ix_payroll_be_payment_items_organization_id", ["organization_id"])
    _index(t, "ix_payroll_be_payment_items_batch_id", ["batch_id"])
    _index(t, "ix_payroll_be_payment_items_employee_id", ["employee_id"])
    _index(t, "ix_be_payment_item_batch_emp", ["batch_id", "employee_id"])

    # 7) payroll_be_component_mappings (TENANT, G-28)
    t = MAPPINGS
    if not _has_table(t):
        op.create_table(
            "payroll_be_component_mappings",
            *_common(t),
            sa.Column("platform_component_source", sa.String(20), nullable=False),
            sa.Column("platform_component_key", sa.String(50), nullable=False),
            sa.Column("be_component", sa.String(32), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')", name="ck_be_component_mapping_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_be_component_mapping_dates"),
            sa.CheckConstraint(f"status <> 'ACTIVE' OR {_FOUR_EYES}", name="ck_be_component_mapping_four_eyes"),
            sa.CheckConstraint(f"platform_component_source IN {_in(COMPONENT_SOURCES)}",
                               name="ck_be_component_mapping_source"),
            sa.CheckConstraint(f"be_component IN {_in(COMPONENTS)}", name="ck_be_component_mapping_component"),
        )
    _standard_indexes(t)
    _index(t, "uq_be_component_mapping_one_active",
           ["organization_id", "platform_component_source", "platform_component_key"], unique=True,
           where=_ACTIVE_OPEN)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
    if _postgres():
        op.execute(sa.text(f'DELETE FROM "{LEDGER}" WHERE accumulator NOT IN {_in(OLD_ACCUMULATORS)}'))
        op.execute(sa.text(f'ALTER TABLE "{LEDGER}" DROP CONSTRAINT IF EXISTS ck_be_accum_accumulator'))
        op.create_check_constraint("ck_be_accum_accumulator", LEDGER, f"accumulator IN {_in(OLD_ACCUMULATORS)}")
        op.execute(sa.text(f'ALTER TABLE "{CLASSIFICATIONS}" DROP CONSTRAINT IF EXISTS '
                           "ck_be_classification_contract_dates"))
    # (table, columns, the named CHECKs on those columns — SQLite's table rebuild
    # would otherwise carry a reflected CHECK that names a dropped column).
    drops = ((EMPLOYERS, ("special_160_evidence_ref", "onss_special_160_status"),
              ("ck_be_employer_special_160_status",)),
             (CLASSIFICATIONS, ("contract_end_date", "contract_start_date", "contract_type"),
              ("ck_be_classification_contract_dates", "ck_be_classification_contract_type")),
             (PROFILES, ("pay_basis",), ("ck_be_worker_pay_basis",)))
    for table, columns, checks in drops:
        present = [c for c in columns if c in _columns(table)]
        if not present:
            continue
        if _postgres():
            for column in present:
                op.drop_column(table, column)
        else:
            reflected = {c.get("name") for c in sa.inspect(op.get_bind()).get_check_constraints(table)}
            with op.batch_alter_table(table) as batch:
                for name in checks:
                    if name in reflected:
                        batch.drop_constraint(name, type_="check")
                for column in present:
                    batch.drop_column(column)

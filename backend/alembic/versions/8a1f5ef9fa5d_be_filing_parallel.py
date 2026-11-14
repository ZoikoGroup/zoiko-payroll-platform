"""be_filing_parallel: Belgium filings, obligations, reconciliation variances, parallel cycles

Revision ID: 8a1f5ef9fa5d
Revises: 2943a0490b5b
Create Date: 2026-11-12

ZP-BE-ENG-001 Block C (the block's single migration). Additive only: five new
payroll_be_* tables; nothing existing is touched.

  payroll_be_filings                  (TENANT) Dimona / DmfA (ONSS), Finprof /
      Belcotax 281.10 (SPF Finance): period, subject, ORIGINAL / CORRECTION /
      CANCELLATION with corrects_id lineage, version, schema version, payload +
      payload hash + readable rendition, validation note, UNIQUE idempotency
      key (no personal data), due date, status DRAFT / VALIDATED / APPROVED /
      TRANSMITTED / ACCEPTED / REJECTED / SETTLED / SUPERSEDED, submission and
      receipt references, response, rejection, actor and mandate reference,
      timestamps; four-eyes before approval (BE-033 .. BE-037).
  payroll_be_obligations              (TENANT) ONSS quarter, each ONSS advance
      on its own (BE-018), withholding, holiday fund; acceptance tracked apart
      from settlement (BE-036).
  payroll_be_reconciliation_variances (TENANT) four-eyes resolution.
  payroll_be_parallel_imports         (TENANT) clone of the Poland table.
  payroll_be_parallel_differences     (WORKER) clone of the Poland table.

No statutory rate, threshold, date or schema version appears in a CHECK
(ZP-BE-ENG-001 §3). RLS as d7f9b1c3e5a6's classify() derives, on these
tables only (PostgreSQL). Literal names, lock_timeout, idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8a1f5ef9fa5d"
down_revision: Union[str, Sequence[str], None] = "2943a0490b5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILINGS = "payroll_be_filings"
OBLIGATIONS = "payroll_be_obligations"
VARIANCES = "payroll_be_reconciliation_variances"
IMPORTS = "payroll_be_parallel_imports"
DIFFERENCES = "payroll_be_parallel_differences"
TENANT_TABLES = (FILINGS, OBLIGATIONS, VARIANCES, IMPORTS)
WORKER_TABLES = (DIFFERENCES,)
_TABLES = (DIFFERENCES, IMPORTS, VARIANCES, OBLIGATIONS, FILINGS)          # drop order

# Vocabularies (mirror models._BE_*; no statutory values).
AUTHORITIES = ("ONSS", "SPF_FINANCE")
FORMS = ("DIMONA", "DMFA", "FINPROF", "BELCOTAX")
KINDS = ("ORIGINAL", "CORRECTION", "CANCELLATION")
FILING_STATUSES = ("DRAFT", "VALIDATED", "APPROVED", "TRANSMITTED", "ACCEPTED", "REJECTED", "SETTLED", "SUPERSEDED")
OBLIGATION_TYPES = ("ONSS_QUARTER", "ONSS_ADVANCE", "WITHHOLDING", "HOLIDAY_FUND")
OBLIGATION_STATUSES = ("DUE", "PART_PAID", "PAID", "OVERPAID", "RECONCILED")
ACCEPTANCE_STATES = ("NOT_FILED", "FILED", "ACCEPTED", "REJECTED")
VARIANCE_KINDS = ("UNDERPAID", "OVERPAID", "CHANGED_AFTER_PAYMENT", "DECLARED_DIFFERS")
CONCEPTS = ("gross", "withholding", "onss_employee", "work_bonus_social", "net", "employer_onss")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


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


def _tenant():
    return [sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("legal_entity_id", sa.Integer(), sa.ForeignKey("legal_entities.id", ondelete="SET NULL"),
                      nullable=True)]


def _common(table: str):
    """The _BeCommon columns (id / tenant / evidence / version / approval / stamps)."""
    return _tenant() + [
        sa.Column("evidence_ref", sa.String(300), nullable=True),
        sa.Column("previous_version_id", sa.Integer(), sa.ForeignKey(f"{table}.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _base_indexes(table, employee=False):
    _index(table, f"ix_{table}_id", ["id"])
    _index(table, f"ix_{table}_organization_id", ["organization_id"])
    _index(table, f"ix_{table}_legal_entity_id", ["legal_entity_id"])
    if employee:
        _index(table, f"ix_{table}_employee_id", ["employee_id"])


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

    # 1) payroll_be_filings (TENANT)
    t = FILINGS
    if not _has_table(t):
        op.create_table(
            "payroll_be_filings",
            *_tenant(),
            sa.Column("authority", sa.String(12), nullable=False),
            sa.Column("form_code", sa.String(10), nullable=False),
            sa.Column("period_key", sa.String(10), nullable=False),
            sa.Column("subject_key", sa.String(40), nullable=True),
            sa.Column("kind", sa.String(12), nullable=False, server_default="ORIGINAL"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("schema_version", sa.String(20), nullable=True),
            sa.Column("run_ids", _json(), nullable=True),
            sa.Column("payload", _json(), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("rendition", sa.Text(), nullable=True),
            sa.Column("validation_note", sa.String(300), nullable=True),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("corrects_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("previous_version_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("submission_ref", sa.String(100), nullable=True),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.Column("response", _json(), nullable=True),
            sa.Column("rejection", _json(), nullable=True),
            sa.Column("mandate_ref", sa.String(100), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transmitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("transmitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"authority IN {_in(AUTHORITIES)}", name="ck_be_filing_authority"),
            sa.CheckConstraint(f"form_code IN {_in(FORMS)}", name="ck_be_filing_form"),
            sa.CheckConstraint(f"kind IN {_in(KINDS)}", name="ck_be_filing_kind"),
            sa.CheckConstraint(f"status IN {_in(FILING_STATUSES)}", name="ck_be_filing_status"),
            sa.CheckConstraint("kind = 'ORIGINAL' OR corrects_id IS NOT NULL", name="ck_be_filing_correction"),
            sa.CheckConstraint("status IN ('DRAFT', 'VALIDATED', 'SUPERSEDED') OR (approved_by_id IS NOT NULL AND "
                               "schema_version IS NOT NULL AND (created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_be_filing_four_eyes"),
            sa.CheckConstraint("status NOT IN ('TRANSMITTED', 'ACCEPTED', 'REJECTED', 'SETTLED') OR "
                               "submission_ref IS NOT NULL", name="ck_be_filing_submission"),
        )
    _base_indexes(t)
    _index(t, "ix_be_filing_period", ["organization_id", "form_code", "period_key"])
    _index(t, "uq_be_filing_idempotency", ["idempotency_key"], unique=True)

    # 2) payroll_be_obligations (TENANT)
    t = OBLIGATIONS
    if not _has_table(t):
        op.create_table(
            "payroll_be_obligations",
            *_tenant(),
            sa.Column("obligation_type", sa.String(16), nullable=False),
            sa.Column("period_key", sa.String(10), nullable=False),
            sa.Column("obligation_key", sa.String(80), nullable=False),
            sa.Column("filing_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("acceptance_status", sa.String(10), nullable=False, server_default="NOT_FILED"),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("amount_due", sa.Numeric(14, 2), nullable=False),
            sa.Column("paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("payments", _json(), nullable=True),
            sa.Column("run_ids", _json(), nullable=True),
            sa.Column("components", _json(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="DUE"),
            sa.Column("reconciled_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"obligation_type IN {_in(OBLIGATION_TYPES)}", name="ck_be_obligation_type"),
            sa.CheckConstraint(f"status IN {_in(OBLIGATION_STATUSES)}", name="ck_be_obligation_status"),
            sa.CheckConstraint(f"acceptance_status IN {_in(ACCEPTANCE_STATES)}", name="ck_be_obligation_acceptance"),
            sa.CheckConstraint("amount_due >= 0 AND paid_amount >= 0", name="ck_be_obligation_amounts"),
            sa.CheckConstraint("status <> 'RECONCILED' OR reconciled_by_id IS NOT NULL",
                               name="ck_be_obligation_reconciled"),
        )
    _base_indexes(t)
    _index(t, "uq_be_obligation_key", ["obligation_key"], unique=True)

    # 3) payroll_be_reconciliation_variances (TENANT)
    t = VARIANCES
    if not _has_table(t):
        op.create_table(
            "payroll_be_reconciliation_variances",
            *_tenant(),
            sa.Column("obligation_id", sa.Integer(), sa.ForeignKey(f"{OBLIGATIONS}.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("variance_kind", sa.String(24), nullable=False),
            sa.Column("expected_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("actual_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("difference", sa.Numeric(14, 2), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("resolution", sa.String(300), nullable=True),
            sa.Column("raised_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint(f"variance_kind IN {_in(VARIANCE_KINDS)}", name="ck_be_variance_kind"),
            sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_be_variance_status"),
            sa.CheckConstraint("status <> 'RESOLVED' OR (resolved_by_id IS NOT NULL AND resolution IS NOT NULL "
                               "AND (raised_by_id IS NULL OR resolved_by_id <> raised_by_id))",
                               name="ck_be_variance_four_eyes"),
        )
    _base_indexes(t)
    _index(t, f"ix_{t}_obligation_id", ["obligation_id"])

    # 4) payroll_be_parallel_imports (TENANT)
    t = IMPORTS
    if not _has_table(t):
        op.create_table(
            "payroll_be_parallel_imports",
            *_common(t),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("cycle_month", sa.Date(), nullable=False),
            sa.Column("source_name", sa.String(100), nullable=False),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("column_map", _json(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("withdrawn_reason", sa.String(300), nullable=True),
            sa.CheckConstraint("row_count >= 0 AND matched_count >= 0 AND unmatched_count >= 0",
                               name="ck_be_parallel_import_counts"),
            sa.CheckConstraint("status IN ('OPEN', 'ACCEPTED', 'WITHDRAWN')", name="ck_be_parallel_import_status"),
            sa.CheckConstraint("status <> 'ACCEPTED' OR (approved_by_id IS NOT NULL AND approved_by_id <> created_by_id)",
                               name="ck_be_parallel_import_four_eyes"),
        )
    _base_indexes(t)
    _index(t, "ix_be_parallel_import_cycle", ["status", "cycle_month"])
    _index(t, "uq_be_parallel_import_file", ["organization_id", "run_id", "file_hash"], unique=True,
           where="status <> 'WITHDRAWN'")

    # 5) payroll_be_parallel_differences (WORKER)
    t = DIFFERENCES
    if not _has_table(t):
        op.create_table(
            "payroll_be_parallel_differences",
            *_common(t),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey(f"{IMPORTS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("concept", sa.String(24), nullable=False),
            sa.Column("incumbent_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("zoiko_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("difference", sa.Numeric(14, 2), nullable=False),
            sa.Column("explanation", sa.String(300), nullable=True),
            sa.Column("explained_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.CheckConstraint(f"concept IN {_in(CONCEPTS)}", name="ck_be_parallel_difference_concept"),
            sa.CheckConstraint("status IN ('OPEN', 'EXPLAINED', 'ACCEPTED')", name="ck_be_parallel_difference_status"),
            sa.CheckConstraint("status = 'OPEN' OR explanation IS NOT NULL", name="ck_be_parallel_difference_explained"),
            sa.CheckConstraint("status <> 'ACCEPTED' OR (approved_by_id IS NOT NULL AND approved_by_id <> explained_by_id)",
                               name="ck_be_parallel_difference_four_eyes"),
        )
    _base_indexes(t, employee=True)
    _index(t, "ix_be_parallel_difference_import", ["import_id"])
    _index(t, "uq_be_parallel_difference", ["import_id", "employee_id", "concept"], unique=True)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

"""pl_filing_settlement: Poland filing records, settlements and reconciliation variances

Revision ID: e75b9219e1f8
Revises: e11c2c36df17
Create Date: 2026-11-06

ZP-PL-ENG-001 Phase 8 (spec §10; PL-019 versioned form catalogue, PL-020
idempotent filing / payment, PL-021 no live transport). Additive only.

  payroll_pl_filings                 one record per legal employer, form and
      period (ZUS DRA / RCA / RSA monthly, ZUA / ZZA / ZWUA registration events,
      PIT-11 / PIT-4R / PIT-8AR annual) with version and kind (ORIGINAL /
      CORRECTION). The payload is CANONICAL (schema-neutral) and generated only
      from frozen PAID payslips, the ledger or approved records; identifiers
      appear as vault id + masked form only. idempotency_key is unique: the
      same payload is never stored twice (PL-020). The authority schema
      version stays NULL while the catalogue holds no archived schema, and
      approval is refused until it does (PL-019).
  payroll_pl_settlements             one row per legal employer, liability (ZUS /
      PIT / PPK) and month: amount due from the PAID payslips, the payments
      recorded against it (each with its own reference, idempotent), due date.
      Filing acceptance never marks a liability paid.
  payroll_pl_reconciliation_variances  an unexplained difference between what is
      due and what was paid; resolved only by a second person with a reason.

No statutory number appears in any CHECK constraint (spec page 1).
RLS (d7f9b1c3e5a6 classify): all three tables TENANT (no employee column; the
payload carries the masked identifiers only). PostgreSQL only; literal names;
lock_timeout; idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e75b9219e1f8"
down_revision: Union[str, Sequence[str], None] = "e11c2c36df17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILINGS = "payroll_pl_filings"
SETTLEMENTS = "payroll_pl_settlements"
VARIANCES = "payroll_pl_reconciliation_variances"

TENANT_TABLES = (FILINGS, SETTLEMENTS, VARIANCES)
_TABLES = (VARIANCES, SETTLEMENTS, FILINGS)
FORMS = ("DRA", "RCA", "RSA", "RPA", "ZUA", "ZZA", "ZWUA", "PIT11", "PIT4R", "PIT8AR")
FILING_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED", "SUBMITTED", "ACCEPTED", "REJECTED", "CORRECTED")
LIABILITIES = ("ZUS", "PIT", "PPK")
SETTLEMENT_STATUSES = ("DUE", "PART_PAID", "PAID", "OVERPAID", "RECONCILED")
VARIANCE_KINDS = ("UNDERPAID", "OVERPAID", "CHANGED_AFTER_PAYMENT")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False):
    if not _has_index(table, name):
        op.create_index(name, table, cols, unique=unique)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    for table in TENANT_TABLES:
        predicate = rls._TENANT_PREDICATE
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    t = FILINGS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_filings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("legal_entity_id", sa.Integer(),
                      sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("authority", sa.String(8), nullable=False),
            sa.Column("form_code", sa.String(8), nullable=False),
            sa.Column("period_key", sa.String(10), nullable=False),
            sa.Column("subject_key", sa.String(40), nullable=True),
            sa.Column("kind", sa.String(12), nullable=False, server_default="ORIGINAL"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("schema_version", sa.String(20), nullable=True),
            sa.Column("run_ids", _json(), nullable=True),
            sa.Column("payload", _json(), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("corrects_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("previous_version_id", sa.Integer(), sa.ForeignKey(f"{FILINGS}.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("submission_ref", sa.String(100), nullable=True),
            sa.Column("receipt_ref", sa.String(100), nullable=True),
            sa.Column("rejection", _json(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("authority IN ('ZUS', 'KAS')", name="ck_pl_filing_authority"),
            sa.CheckConstraint(f"form_code IN {_in(FORMS)}", name="ck_pl_filing_form"),
            sa.CheckConstraint("kind IN ('ORIGINAL', 'CORRECTION')", name="ck_pl_filing_kind"),
            sa.CheckConstraint(f"status IN {_in(FILING_STATUSES)}", name="ck_pl_filing_status"),
            sa.CheckConstraint("kind <> 'CORRECTION' OR corrects_id IS NOT NULL", name="ck_pl_filing_correction"),
            sa.CheckConstraint("status IN ('DRAFT', 'SUPERSEDED') OR (approved_by_id IS NOT NULL AND "
                               "schema_version IS NOT NULL AND "
                               "(created_by_id IS NULL OR approved_by_id <> created_by_id))",
                               name="ck_pl_filing_four_eyes"),
            sa.CheckConstraint("status NOT IN ('SUBMITTED', 'ACCEPTED', 'REJECTED', 'CORRECTED') OR "
                               "submission_ref IS NOT NULL", name="ck_pl_filing_submission"),
        )
    _index(t, f"ix_{t}_id", ["id"])
    _index(t, f"ix_{t}_organization_id", ["organization_id"])
    _index(t, f"ix_{t}_legal_entity_id", ["legal_entity_id"])
    _index(t, "ix_pl_filing_period", ["organization_id", "form_code", "period_key"])
    _index(t, "uq_pl_filing_idempotency", ["idempotency_key"], unique=True)

    t = SETTLEMENTS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_settlements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("legal_entity_id", sa.Integer(),
                      sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("liability_type", sa.String(4), nullable=False),
            sa.Column("period_key", sa.String(7), nullable=False),
            sa.Column("settlement_key", sa.String(80), nullable=False),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("amount_due", sa.Numeric(14, 2), nullable=False),
            sa.Column("paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("payments", _json(), nullable=True),
            sa.Column("run_ids", _json(), nullable=True),
            sa.Column("components", _json(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="DUE"),
            sa.Column("reconciled_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(f"liability_type IN {_in(LIABILITIES)}", name="ck_pl_settlement_liability"),
            sa.CheckConstraint(f"status IN {_in(SETTLEMENT_STATUSES)}", name="ck_pl_settlement_status"),
            sa.CheckConstraint("amount_due >= 0 AND paid_amount >= 0", name="ck_pl_settlement_amounts"),
            sa.CheckConstraint("status <> 'RECONCILED' OR reconciled_by_id IS NOT NULL",
                               name="ck_pl_settlement_reconciled"),
        )
    _index(t, f"ix_{t}_id", ["id"])
    _index(t, f"ix_{t}_organization_id", ["organization_id"])
    _index(t, f"ix_{t}_legal_entity_id", ["legal_entity_id"])
    _index(t, "uq_pl_settlement_key", ["settlement_key"], unique=True)

    t = VARIANCES
    if not _has_table(t):
        op.create_table(
            "payroll_pl_reconciliation_variances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("legal_entity_id", sa.Integer(),
                      sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
            sa.Column("settlement_id", sa.Integer(),
                      sa.ForeignKey(f"{SETTLEMENTS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("variance_kind", sa.String(24), nullable=False),
            sa.Column("expected_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("actual_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("difference", sa.Numeric(14, 2), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("resolution", sa.String(300), nullable=True),
            sa.Column("raised_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint(f"variance_kind IN {_in(VARIANCE_KINDS)}", name="ck_pl_variance_kind"),
            sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_pl_variance_status"),
            sa.CheckConstraint("status <> 'RESOLVED' OR (resolved_by_id IS NOT NULL AND resolution IS NOT NULL "
                               "AND (raised_by_id IS NULL OR resolved_by_id <> raised_by_id))",
                               name="ck_pl_variance_four_eyes"),
        )
    _index(t, f"ix_{t}_id", ["id"])
    _index(t, f"ix_{t}_organization_id", ["organization_id"])
    _index(t, f"ix_{t}_legal_entity_id", ["legal_entity_id"])
    _index(t, f"ix_{t}_settlement_id", ["settlement_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)

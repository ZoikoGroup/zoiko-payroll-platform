"""mx_cfdi_m5: Mexico CFDI 4.0 + Nómina 1.2 lifecycle (documents, outbox, events)

Revision ID: d8b3e5f1a2c7
Revises: c4f7a2d9e6b1
Create Date: 2026-10-17

ZP-MX-ENG-001 Phase 7 (docs/mexico/MEXICO_PHASE_7_PLAN.md §3): three NEW tables only —
payroll_mx_cfdi_documents, payroll_mx_cfdi_outbox_items, payroll_mx_cfdi_events.
No column is added to any shared table.

Merging to main runs this in production. Creating the FKs to payslip_items /
payroll_runs / payroll_employees takes a brief SHARE ROW EXCLUSIVE lock on each
(reads continue; writes wait) that alembic/env.py holds until the upgrade
transaction commits — so the whole revision runs under SET LOCAL lock_timeout =
'5s' (fail fast instead of queueing payroll writes), and is small (three CREATE
TABLE + indexes). The hold time is measured on PostgreSQL 17 in
tests/test_mexico_cfdi_migrations.py. Guarded and idempotent; downgrade drops only
these tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8b3e5f1a2c7"
down_revision: Union[str, Sequence[str], None] = "c4f7a2d9e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOCS, OUTBOX, EVENTS = "payroll_mx_cfdi_documents", "payroll_mx_cfdi_outbox_items", "payroll_mx_cfdi_events"
NEW_TABLES = (DOCS, OUTBOX, EVENTS)
_LIVE = "status NOT IN ('CANCELLED', 'REPLACED', 'VOIDED', 'REJECTED')"


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def _fk(target, ondelete):
    return sa.ForeignKey(f"{target}.id", ondelete=ondelete)


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _index(name, table, cols, **kw):
    if not _has_index(table, name):
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s = sa.Integer, sa.String
    if not _has_table(DOCS):
        op.create_table(
            "payroll_mx_cfdi_documents",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("series", s(25), nullable=True),
            sa.Column("folio", s(40), nullable=False),
            sa.Column("schema_release_id", i(), _fk("payroll_mx_cfdi_schema_releases", "RESTRICT"), nullable=False),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("xml_storage_ref", s(500), nullable=True),
            sa.Column("status", s(20), nullable=False),
            sa.Column("unknown_action", s(10), nullable=True),
            _ts("unknown_since"),
            sa.Column("uuid", s(40), nullable=True),
            _ts("stamped_at"),
            sa.Column("sat_certificate_number", s(30), nullable=True),
            sa.Column("pac_provider", s(60), nullable=True),
            sa.Column("pac_environment", s(12), nullable=True),
            sa.Column("pac_response_code", s(40), nullable=True),
            sa.Column("pac_message", s(500), nullable=True),
            sa.Column("cancellation_reason_code", s(10), nullable=True),
            _ts("cancel_requested_at"),
            _ts("cancelled_at"),
            sa.Column("replaces_document_id", i(), _fk("payroll_mx_cfdi_documents", "RESTRICT"), nullable=True),
            sa.Column("replaces_uuid", s(40), nullable=True),
            sa.Column("replaced_by_uuid", s(40), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False, unique=True),
            sa.Column("created_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint(
                "status IN ('GENERATED', 'SIGNED', 'SUBMITTED', 'STAMPED', 'REJECTED', 'UNKNOWN', "
                "'CANCEL_REQUESTED', 'CANCELLED', 'REPLACED', 'VOIDED')", name="ck_mx_cfdi_doc_status"),
            sa.UniqueConstraint("organization_id", "series", "folio", name="uq_mx_cfdi_doc_folio"),
        )
    for col in ("id", "organization_id", "payroll_run_id", "payslip_item_id", "employee_id"):
        _index(f"ix_{DOCS}_{col}", DOCS, [col])
    _index("uq_mx_cfdi_doc_live_per_item", DOCS, ["payslip_item_id"], unique=True,
           postgresql_where=sa.text(_LIVE), sqlite_where=sa.text(_LIVE))
    _index("uq_mx_cfdi_doc_uuid", DOCS, ["uuid"], unique=True,
           postgresql_where=sa.text("uuid IS NOT NULL"), sqlite_where=sa.text("uuid IS NOT NULL"))

    if not _has_table(OUTBOX):
        op.create_table(
            "payroll_mx_cfdi_outbox_items",
            sa.Column("id", i(), primary_key=True),
            sa.Column("document_id", i(), _fk("payroll_mx_cfdi_documents", "RESTRICT"), nullable=False),
            sa.Column("action", s(20), nullable=False),
            sa.Column("attempt_no", i(), nullable=False),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False),
            sa.Column("status", s(12), nullable=False),
            sa.Column("last_error", s(500), nullable=True),
            sa.Column("operator_confirmed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("sent_at"),
            _ts("acknowledged_at"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("action IN ('STAMP', 'CANCEL', 'STATUS_QUERY', 'CANCEL_STATUS_QUERY')",
                               name="ck_mx_cfdi_outbox_action"),
            sa.CheckConstraint("status IN ('PENDING', 'SENT', 'ACKNOWLEDGED', 'FAILED', 'UNKNOWN')",
                               name="ck_mx_cfdi_outbox_status"),
            sa.UniqueConstraint("document_id", "action", "attempt_no", name="uq_mx_cfdi_outbox_attempt"),
        )
    for col in ("id", "document_id", "idempotency_key"):
        _index(f"ix_{OUTBOX}_{col}", OUTBOX, [col])

    if not _has_table(EVENTS):
        op.create_table(
            "payroll_mx_cfdi_events",
            sa.Column("id", i(), primary_key=True),
            sa.Column("document_id", i(), _fk("payroll_mx_cfdi_documents", "RESTRICT"), nullable=False),
            sa.Column("event_type", s(40), nullable=False),
            sa.Column("from_status", s(20), nullable=True),
            sa.Column("to_status", s(20), nullable=True),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("actor_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    for col in ("id", "document_id"):
        _index(f"ix_{EVENTS}_{col}", EVENTS, [col])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for name in (EVENTS, OUTBOX, DOCS):
        if _has_table(name):
            op.drop_table(name)

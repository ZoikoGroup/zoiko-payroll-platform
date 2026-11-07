"""mx_cfdi_lifecycle: CFDI document lifecycle, envelope and access log

Revision ID: b5e1c7d9a3f2
Revises: a8cde2482ef0
Create Date: 2026-11-06

Mexico CFDI lifecycle L1-L4 (docs/mexico/MEXICO_CFDI_LIFECYCLE_REPORT.md).
Additive only — nothing existing is changed or backfilled:

  payroll_mx_cfdi_documents  + event_key (the pay-event idempotency hash; a
      partial unique index among LIVE documents, the same predicate as
      uq_mx_cfdi_doc_live_per_item), document_subtype, the envelope columns
      (employer_profile_id, state_code, snapshot_hash, ruleset_version,
      issuing_cert_token, document_locale) and the recorded outcomes
      (published_at, delivery_status, cancel_outcome). All nullable: a row
      from before this revision keeps NULL and its envelope is derived on read.
  payroll_mx_cfdi_schema_releases  + effective_from / effective_to (the
      official validity window; NULL = not recorded).
  payroll_mx_document_access_events  new, append-only (MX24-PAY-009 /
      MX24-AUD-002): publish, delivery, view and download events — actor,
      time, channel, artifact; never an identifier. PostgreSQL: a trigger
      refuses UPDATE and DELETE, and the WORKER "org" row-level-security
      policy (employee_id) that d7f9b1c3e5a6's classify() derives.

PostgreSQL: lock_timeout fail-fast (every step takes at most a brief lock on
a small table). Idempotent both ways. Literal names so
scripts/drift_pending_filter explains every change.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5e1c7d9a3f2"
down_revision: Union[str, Sequence[str], None] = "a8cde2482ef0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOCS = "payroll_mx_cfdi_documents"
RELEASES = "payroll_mx_cfdi_schema_releases"
ACCESS = "payroll_mx_document_access_events"
LIVE = "status NOT IN ('CANCELLED', 'REPLACED', 'VOIDED', 'REJECTED')"
DOC_COLUMNS = (
    ("event_key", sa.String(64)), ("document_subtype", sa.String(40)), ("state_code", sa.String(10)),
    ("snapshot_hash", sa.String(64)), ("ruleset_version", sa.String(80)), ("issuing_cert_token", sa.String(64)),
    ("document_locale", sa.String(10)), ("published_at", sa.DateTime(timezone=True)),
    ("delivery_status", sa.String(16)), ("cancel_outcome", sa.String(16)),
)


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_column(table, name):
    return _has_table(table) and name in {c["name"] for c in _insp().get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def _has_check(table, name):
    return _has_table(table) and name in {c["name"] for c in _insp().get_check_constraints(table)}


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # Literal table / column names: scripts/drift_pending_filter reads them from this source.
    if not _has_column(DOCS, "event_key"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("event_key", sa.String(64), nullable=True))
    if not _has_column(DOCS, "document_subtype"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("document_subtype", sa.String(40), nullable=True))
    if not _has_column(DOCS, "state_code"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("state_code", sa.String(10), nullable=True))
    if not _has_column(DOCS, "snapshot_hash"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("snapshot_hash", sa.String(64), nullable=True))
    if not _has_column(DOCS, "ruleset_version"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("ruleset_version", sa.String(80), nullable=True))
    if not _has_column(DOCS, "issuing_cert_token"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("issuing_cert_token", sa.String(64), nullable=True))
    if not _has_column(DOCS, "document_locale"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("document_locale", sa.String(10), nullable=True))
    if not _has_column(DOCS, "published_at"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(DOCS, "delivery_status"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("delivery_status", sa.String(16), nullable=True))
    if not _has_column(DOCS, "cancel_outcome"):
        op.add_column("payroll_mx_cfdi_documents", sa.Column("cancel_outcome", sa.String(16), nullable=True))
    if not _has_column(DOCS, "employer_profile_id"):
        with op.batch_alter_table("payroll_mx_cfdi_documents") as batch:   # SQLite: an FK column needs batch mode
            batch.add_column(sa.Column("employer_profile_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_mx_cfdi_doc_employer_profile", "payroll_mx_employer_profiles",
                                     ["employer_profile_id"], ["id"], ondelete="RESTRICT")
    if _postgres():
        for name, expr in (("ck_mx_cfdi_doc_delivery",
                            "delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'DELIVERY_FAILED')"),
                           ("ck_mx_cfdi_doc_cancel_outcome",
                            "cancel_outcome IS NULL OR cancel_outcome IN ('CANCEL_ACCEPTED', 'CANCEL_REJECTED')")):
            if not _has_check(DOCS, name):
                op.create_check_constraint(name, DOCS, expr)
    if not _has_index(DOCS, "uq_mx_cfdi_doc_live_event"):
        op.create_index("uq_mx_cfdi_doc_live_event", DOCS, ["event_key"], unique=True,
                        postgresql_where=sa.text(f"event_key IS NOT NULL AND {LIVE}"),
                        sqlite_where=sa.text(f"event_key IS NOT NULL AND {LIVE}"))

    if not _has_column(RELEASES, "effective_from"):
        op.add_column("payroll_mx_cfdi_schema_releases", sa.Column("effective_from", sa.Date(), nullable=True))
    if not _has_column(RELEASES, "effective_to"):
        op.add_column("payroll_mx_cfdi_schema_releases", sa.Column("effective_to", sa.Date(), nullable=True))

    if not _has_table(ACCESS):
        op.create_table(
            "payroll_mx_document_access_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="RESTRICT"),
                      nullable=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("payroll_mx_cfdi_documents.id", ondelete="RESTRICT"),
                      nullable=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="RESTRICT"),
                      nullable=True),
            sa.Column("event_type", sa.String(24), nullable=False),
            sa.Column("artifact", sa.String(24), nullable=False),
            sa.Column("channel", sa.String(16), nullable=False),
            sa.Column("renderer_version", sa.String(40), nullable=True),
            sa.Column("proof_reference", sa.String(120), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("event_type IN ('PUBLISHED', 'DELIVERED', 'DELIVERY_FAILED', 'VIEWED', 'DOWNLOADED')",
                               name="ck_mx_doc_access_event_type"),
        )
    for name, cols in (("ix_payroll_mx_document_access_events_id", ["id"]),
                       ("ix_payroll_mx_document_access_events_organization_id", ["organization_id"]),
                       ("ix_payroll_mx_document_access_events_payslip_item_id", ["payslip_item_id"]),
                       ("ix_payroll_mx_document_access_events_document_id", ["document_id"]),
                       ("ix_payroll_mx_document_access_events_employee_id", ["employee_id"])):
        if not _has_index(ACCESS, name):
            op.create_index(name, ACCESS, cols)

    if _postgres():
        bind = op.get_bind()
        bind.execute(sa.text(
            "CREATE OR REPLACE FUNCTION mx_doc_access_append_only() RETURNS trigger AS $$ BEGIN "
            "RAISE EXCEPTION 'payroll_mx_document_access_events is append-only'; END; $$ LANGUAGE plpgsql"))
        bind.execute(sa.text(f'DROP TRIGGER IF EXISTS trg_mx_doc_access_append_only ON "{ACCESS}"'))
        bind.execute(sa.text(f'CREATE TRIGGER trg_mx_doc_access_append_only BEFORE UPDATE OR DELETE ON "{ACCESS}" '
                             "FOR EACH ROW EXECUTE FUNCTION mx_doc_access_append_only()"))
        rls = _rls_module()
        predicate = rls._worker_predicate("org")
        rls._sql(bind, f'ALTER TABLE "{ACCESS}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{ACCESS}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{ACCESS}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{ACCESS}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text(f'DROP TRIGGER IF EXISTS trg_mx_doc_access_append_only ON "{ACCESS}"'))
        op.execute(sa.text("DROP FUNCTION IF EXISTS mx_doc_access_append_only()"))
    if _has_table(ACCESS):
        op.drop_table(ACCESS)
    for name in ("effective_to", "effective_from"):
        if _has_column(RELEASES, name):
            op.drop_column(RELEASES, name)
    if _has_index(DOCS, "uq_mx_cfdi_doc_live_event"):
        op.drop_index("uq_mx_cfdi_doc_live_event", table_name=DOCS)
    checks = [n for n in ("ck_mx_cfdi_doc_cancel_outcome", "ck_mx_cfdi_doc_delivery") if _has_check(DOCS, n)]
    columns = [n for n in ("employer_profile_id", *[n for n, _ in DOC_COLUMNS][::-1]) if _has_column(DOCS, n)]
    if checks or columns:
        # One batch: on SQLite the table is rebuilt once, without the checks
        # that name the dropped columns; on PostgreSQL these are plain ALTERs.
        with op.batch_alter_table(DOCS) as batch:
            for name in checks:
                batch.drop_constraint(name, type_="check")
            for name in columns:
                batch.drop_column(name)

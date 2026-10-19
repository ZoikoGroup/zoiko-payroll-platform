"""mx_authorities_m6: Mexico authorities — IMSS movements, liability ledger, SUA, ISN returns

Revision ID: e3b9c2d7f4a1
Revises: d8b3e5f1a2c7
Create Date: 2026-10-19

ZP-MX-ENG-001 Phase 8 (docs/mexico/MEXICO_PHASE_8_PLAN.md §3): seven NEW tables only —
payroll_mx_imss_movements, payroll_mx_authority_liabilities,
payroll_mx_authority_liability_sources, payroll_mx_sua_periods,
payroll_mx_sua_differences, payroll_mx_isn_returns, payroll_mx_authority_events.
No column is added to any shared table.

Merging to main runs this in production. Creating the FKs to payroll_runs /
payslip_items / payroll_employees takes a brief SHARE ROW EXCLUSIVE lock on each
(reads continue; writes wait) that alembic/env.py holds until the upgrade
transaction commits — so the whole revision runs under SET LOCAL lock_timeout =
'5s' (fail fast instead of queueing payroll writes). The hold time is measured on
PostgreSQL 17 in tests/test_mexico_authorities_migrations.py. Guarded and
idempotent; downgrade drops only these tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b9c2d7f4a1"
down_revision: Union[str, Sequence[str], None] = "d8b3e5f1a2c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MOVES, LIABS, SOURCES = "payroll_mx_imss_movements", "payroll_mx_authority_liabilities", "payroll_mx_authority_liability_sources"
SUA, DIFFS, ISN, EVENTS = ("payroll_mx_sua_periods", "payroll_mx_sua_differences", "payroll_mx_isn_returns",
                           "payroll_mx_authority_events")
NEW_TABLES = (MOVES, LIABS, SOURCES, SUA, DIFFS, ISN, EVENTS)
_LIVE_MOVE = "status NOT IN ('VOIDED', 'REJECTED')"


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


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _user(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id"), nullable=True)


def _index(name, table, cols, **kw):
    if not _has_index(table, name):
        op.create_index(name, table, cols, **kw)


def _indexes(table, cols):
    for col in cols:
        _index(f"ix_{table}_{col}", table, [col])


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s, n = sa.Integer, sa.String, sa.Numeric
    if not _has_table(MOVES):
        op.create_table(
            "payroll_mx_imss_movements",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("registration_id", i(), _fk("payroll_mx_imss_registrations", "RESTRICT"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=True),
            sa.Column("source_kind", s(20), nullable=False),
            sa.Column("source_key", s(120), nullable=False),
            sa.Column("movement_type", s(14), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("sbc", n(14, 4), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("due_rule_ref", s(80), nullable=True),
            sa.Column("status", s(12), nullable=False),
            _ts("unknown_since"),
            sa.Column("export_batch_ref", s(60), nullable=True),
            _ts("exported_at"),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False, unique=True),
            sa.Column("authority_reference", s(120), nullable=True),
            sa.Column("evidence_ref", s(200), nullable=True),
            _user("outcome_recorded_by_id"),
            _user("accepted_by_id"),
            sa.Column("withdrawn_reason", s(300), nullable=True),
            sa.Column("replaces_movement_id", i(), _fk("payroll_mx_imss_movements", "RESTRICT"), nullable=True),
            _user("created_by_id"),
            _created(),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('PENDING', 'EXPORTED', 'FILED', 'ACCEPTED', 'REJECTED', 'UNKNOWN', "
                               "'WITHDRAWN', 'VOIDED')", name="ck_mx_imss_movement_status"),
            sa.CheckConstraint("movement_type IN ('ALTA', 'BAJA', 'MODIFICACION')", name="ck_mx_imss_movement_type"),
        )
    _indexes(MOVES, ("id", "organization_id", "registration_id", "employee_id", "payroll_run_id"))
    _index("uq_mx_imss_movement_live_source", MOVES, ["source_key"], unique=True,
           postgresql_where=sa.text(_LIVE_MOVE), sqlite_where=sa.text(_LIVE_MOVE))

    if not _has_table(LIABS):
        op.create_table(
            "payroll_mx_authority_liabilities",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("authority", s(10), nullable=False),
            sa.Column("registration_id", i(), _fk("payroll_mx_imss_registrations", "RESTRICT"), nullable=True),
            sa.Column("state_code", s(5), nullable=True),
            sa.Column("scope_key", s(30), nullable=False),
            sa.Column("period_key", s(7), nullable=False),
            sa.Column("sequence", i(), nullable=False),
            sa.Column("amount", n(14, 4), nullable=False),
            sa.Column("components", sa.JSON(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("due_rule_ref", s(80), nullable=True),
            sa.Column("status", s(12), nullable=False),
            _ts("unknown_since"),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False, unique=True),
            sa.Column("declaration_reference", s(120), nullable=True),
            sa.Column("payment_reference", s(120), nullable=True),
            sa.Column("evidence_ref", s(200), nullable=True),
            _user("filed_by_id"),
            _user("paid_by_id"),
            _user("reconciled_by_id"),
            _created(),
            _ts("updated_at"),
            sa.CheckConstraint("authority IN ('SAT_ISR', 'IMSS', 'INFONAVIT', 'ISN')", name="ck_mx_liability_authority"),
            sa.CheckConstraint("status IN ('ACCRUED', 'FILED', 'PAID', 'RECONCILED', 'UNKNOWN', 'WITHDRAWN')",
                               name="ck_mx_liability_status"),
            sa.UniqueConstraint("organization_id", "authority", "scope_key", "period_key", "sequence",
                                name="uq_mx_liability_scope_period"),
        )
    _indexes(LIABS, ("id", "organization_id", "registration_id"))

    if not _has_table(SOURCES):
        op.create_table(
            "payroll_mx_authority_liability_sources",
            sa.Column("id", i(), primary_key=True),
            sa.Column("liability_id", i(), _fk("payroll_mx_authority_liabilities", "RESTRICT"), nullable=False),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("source_table", s(40), nullable=False),
            sa.Column("source_row_id", i(), nullable=False),
            sa.Column("branch_code", s(30), nullable=False),
            sa.Column("side", s(10), nullable=True),
            sa.Column("base_amount", n(14, 4), nullable=True),
            sa.Column("amount", n(14, 4), nullable=False),
            _created(),
            sa.UniqueConstraint("source_table", "source_row_id", name="uq_mx_liability_source_row"),
        )
    _indexes(SOURCES, ("id", "liability_id", "organization_id", "payroll_run_id", "payslip_item_id", "employee_id"))

    if not _has_table(SUA):
        op.create_table(
            "payroll_mx_sua_periods",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("registration_id", i(), _fk("payroll_mx_imss_registrations", "RESTRICT"), nullable=False),
            sa.Column("period_key", s(7), nullable=False),
            sa.Column("sua_version", s(20), nullable=True),
            sa.Column("zoiko_totals", sa.JSON(), nullable=True),
            sa.Column("sua_totals", sa.JSON(), nullable=True),
            sa.Column("difference_total", n(14, 4), nullable=True),
            sa.Column("status", s(12), nullable=False),
            _ts("unknown_since"),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False, unique=True),
            _user("figures_entered_by_id"),
            _ts("figures_entered_at"),
            _user("reconciled_by_id"),
            _ts("reconciled_at"),
            sa.Column("capture_line", s(60), nullable=True),
            sa.Column("payment_reference", s(120), nullable=True),
            sa.Column("evidence_ref", s(200), nullable=True),
            _user("created_by_id"),
            _created(),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'RECONCILED', 'PAID', 'UNKNOWN', 'WITHDRAWN')",
                               name="ck_mx_sua_period_status"),
            sa.UniqueConstraint("organization_id", "registration_id", "period_key", name="uq_mx_sua_period"),
        )
    _indexes(SUA, ("id", "organization_id", "registration_id"))

    if not _has_table(DIFFS):
        op.create_table(
            "payroll_mx_sua_differences",
            sa.Column("id", i(), primary_key=True),
            sa.Column("sua_period_id", i(), _fk("payroll_mx_sua_periods", "RESTRICT"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("branch_code", s(30), nullable=False),
            sa.Column("zoiko_amount", n(14, 4), nullable=False),
            sa.Column("sua_amount", n(14, 4), nullable=False),
            sa.Column("difference", n(14, 4), nullable=False),
            sa.Column("explanation_code", s(20), nullable=True),
            sa.Column("explanation", s(500), nullable=True),
            _user("explained_by_id"),
            _user("approved_by_id"),
            sa.Column("status", s(10), nullable=False),
            _created(),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('OPEN', 'EXPLAINED', 'APPROVED')", name="ck_mx_sua_difference_status"),
            sa.UniqueConstraint("sua_period_id", "employee_id", "branch_code", name="uq_mx_sua_difference"),
        )
    _indexes(DIFFS, ("id", "sua_period_id", "employee_id"))

    if not _has_table(ISN):
        op.create_table(
            "payroll_mx_isn_returns",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("isn_registration_id", i(), _fk("payroll_mx_isn_registrations", "RESTRICT"), nullable=False),
            sa.Column("liability_id", i(), _fk("payroll_mx_authority_liabilities", "RESTRICT"), nullable=False),
            sa.Column("state_code", s(5), nullable=False),
            sa.Column("period_key", s(7), nullable=False),
            sa.Column("sequence", i(), nullable=False),
            sa.Column("base_total", n(14, 4), nullable=False),
            sa.Column("amount", n(14, 4), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("due_rule_ref", s(80), nullable=True),
            sa.Column("status", s(12), nullable=False),
            _ts("unknown_since"),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("idempotency_key", s(100), nullable=False, unique=True),
            sa.Column("filing_reference", s(120), nullable=True),
            sa.Column("payment_reference", s(120), nullable=True),
            sa.Column("evidence_ref", s(200), nullable=True),
            sa.Column("amendment_of_id", i(), _fk("payroll_mx_isn_returns", "RESTRICT"), nullable=True),
            _user("filed_by_id"),
            _user("outcome_by_id"),
            _user("created_by_id"),
            _created(),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'FILED', 'ACCEPTED', 'REJECTED', 'UNKNOWN', 'WITHDRAWN')",
                               name="ck_mx_isn_return_status"),
            sa.UniqueConstraint("organization_id", "state_code", "period_key", "sequence",
                                name="uq_mx_isn_return_period"),
        )
    _indexes(ISN, ("id", "organization_id", "isn_registration_id", "liability_id"))

    if not _has_table(EVENTS):
        op.create_table(
            "payroll_mx_authority_events",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("entity_type", s(20), nullable=False),
            sa.Column("entity_id", i(), nullable=False),
            sa.Column("event_type", s(40), nullable=False),
            sa.Column("from_status", s(12), nullable=True),
            sa.Column("to_status", s(12), nullable=True),
            sa.Column("payload_hash", s(64), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            _user("actor_id"),
            sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    _indexes(EVENTS, ("id", "organization_id"))
    _index("ix_mx_authority_events_entity", EVENTS, ["entity_type", "entity_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for name in (EVENTS, ISN, DIFFS, SUA, SOURCES, LIABS, MOVES):
        if _has_table(name):
            op.drop_table(name)

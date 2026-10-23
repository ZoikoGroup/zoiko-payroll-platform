"""nl_sepa_file_storage_and_payment_channel: store the pain.001 file, batch lifecycle, run payment channel

Revision ID: 8f90dde5f7b5
Revises: 135dbbeb9818
Create Date: 2026-10-23

Phase 4.2 (bank files). The Dutch SEPA salary batch only kept the file's
SHA-256, so there was no file to give the bank; an authority item used
employee_id=0 against a NOT NULL foreign key; and nothing stopped one run being
paid twice through the generic bank file AND a SEPA batch.

  payroll_nl_payment_batches
      + pain001_xml           TEXT       the exact file bytes (download = these bytes)
      + created_at_utc        TIMESTAMPTZ the file's CreDtTm (a rebuild repeats it)
      + batch_kind            VARCHAR(20) SALARY | AUTHORITY
      + authority_payment_id  INTEGER    -> payroll_nl_authority_payments (SET NULL)
      status CHECK gains DRAFT (lifecycle DRAFT -> SUBMITTED -> ACCEPTED /
      REJECTED / UNKNOWN -> SETTLED)
  payroll_nl_payment_items.employee_id  NULLABLE (authority payments have no employee)
  payroll_runs
      + payment_channel       VARCHAR(20) GENERIC_FILE | SEPA — the first channel
      used for a run; the other is refused (no double payment)

Additive and nullable — no table rewrite, no data change. payroll_runs is
read by every country, so its column must exist before the model ships.
Literal table/column names in upgrade() so scripts/drift_pending_filter
explains every added column. PostgreSQL: lock_timeout fail-fast. Idempotent both ways. On SQLite (tests
build the schema from the models) the CHECK and nullability changes are
skipped — SQLite cannot alter them in place.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8f90dde5f7b5"
down_revision: Union[str, Sequence[str], None] = "135dbbeb9818"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCHES, ITEMS, RUNS = "payroll_nl_payment_batches", "payroll_nl_payment_items", "payroll_runs"
STATUS_CHECK = "ck_nl_payment_batch_status"
NEW_STATUSES = "('DRAFT', 'SUBMITTED', 'ACCEPTED', 'SETTLED', 'REJECTED', 'RETURNED', 'UNKNOWN')"
OLD_STATUSES = "('SUBMITTED', 'ACCEPTED', 'SETTLED', 'REJECTED', 'RETURNED', 'UNKNOWN')"


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        op.execute("SET LOCAL lock_timeout = '5s'")
    batch_cols = _columns(BATCHES)
    if "pain001_xml" not in batch_cols:
        op.add_column("payroll_nl_payment_batches", sa.Column("pain001_xml", sa.Text(), nullable=True))
    if "created_at_utc" not in batch_cols:
        op.add_column("payroll_nl_payment_batches", sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=True))
    if "batch_kind" not in batch_cols:
        op.add_column("payroll_nl_payment_batches", sa.Column("batch_kind", sa.String(20), nullable=True))
    if "authority_payment_id" not in batch_cols:
        op.add_column("payroll_nl_payment_batches", sa.Column("authority_payment_id", sa.Integer(), nullable=True))
        if _postgres():
            op.create_foreign_key("fk_nl_payment_batch_authority_payment", BATCHES,
                                  "payroll_nl_authority_payments", ["authority_payment_id"], ["id"],
                                  ondelete="SET NULL")
    if "payment_channel" not in _columns(RUNS):
        op.add_column("payroll_runs", sa.Column("payment_channel", sa.String(20), nullable=True))
    if _postgres():
        op.execute(f"ALTER TABLE {BATCHES} DROP CONSTRAINT IF EXISTS {STATUS_CHECK}")
        op.execute(f"ALTER TABLE {BATCHES} ADD CONSTRAINT {STATUS_CHECK} CHECK (status IN {NEW_STATUSES})")
        op.alter_column(ITEMS, "employee_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    if _postgres():
        op.execute("SET LOCAL lock_timeout = '5s'")
        # A DRAFT batch or an authority item (employee_id NULL) cannot survive
        # the old constraints — remove them first.
        op.execute(f"ALTER TABLE {BATCHES} DROP CONSTRAINT IF EXISTS {STATUS_CHECK}")
        op.execute(f"ALTER TABLE {BATCHES} ADD CONSTRAINT {STATUS_CHECK} CHECK (status IN {OLD_STATUSES})")
        op.alter_column(ITEMS, "employee_id", existing_type=sa.Integer(), nullable=False)
        op.execute(f"ALTER TABLE {BATCHES} DROP CONSTRAINT IF EXISTS fk_nl_payment_batch_authority_payment")
    if "payment_channel" in _columns(RUNS):
        op.drop_column(RUNS, "payment_channel")
    batch_cols = _columns(BATCHES)
    for name in ("authority_payment_id", "batch_kind", "created_at_utc", "pain001_xml"):
        if name in batch_cols:
            op.drop_column(BATCHES, name)

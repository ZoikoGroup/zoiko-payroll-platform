"""ae_foundation: United Arab Emirates payslip calculation breakdown column

Revision ID: ad01fc67ce44
Revises: cf348b09db2b
Create Date: 2026-11-18

ZP-AE-ENG-001 (docs/uae). Additive only, one nullable column:

  payslip_items.ae_calculation_snapshot   the UAE calculation breakdown —
      inputs, pension / gratuity / savings / overtime lines and the pack
      values used — so payslips, run totals and reports show the same figures
      and an old payslip can always be explained. NULL for non-AE payslips.

Every UAE statutory value lives in the canonical jurisdiction pack
(payroll_jurisdiction_packs / payroll_contribution_rates); every UAE
employee fact lives in payroll_employees (salary split, date_of_joining,
date_of_leaving, work_state, compliance_fields). No new table is needed.

Literal names so scripts/drift_pending_filter explains the change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ad01fc67ce44"
down_revision: Union[str, Sequence[str], None] = "cf348b09db2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAYSLIPS = "payslip_items"


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "ae_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("ae_calculation_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "ae_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "ae_calculation_snapshot")

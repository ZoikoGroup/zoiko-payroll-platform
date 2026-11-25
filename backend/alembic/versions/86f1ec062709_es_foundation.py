"""es_foundation: Spain payslip calculation breakdown column

Revision ID: 86f1ec062709
Revises: b5f3e8a1c6d9
Create Date: 2026-11-24

ZP-ES-ENG-001 (docs/spain). Additive only, one nullable column:

  payslip_items.es_calculation_snapshot   the Spanish calculation breakdown —
      inputs, contribution bases, Social Security families, solidarity
      tranches, IRPF algorithm version and rate, and the pack values used — so
      payslips, run totals and reports show the same figures and an old
      payslip can always be explained. NULL for non-ES payslips.

Every Spanish statutory value lives in the canonical jurisdiction pack
(payroll_jurisdiction_packs / payroll_contribution_rates); every Spanish
employee fact lives in payroll_employees (salary split, date_of_joining,
date_of_leaving, work_state, compliance_fields). No new table is needed.

Literal names so scripts/drift_pending_filter explains the change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "86f1ec062709"
down_revision: Union[str, Sequence[str], None] = "b5f3e8a1c6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAYSLIPS = "payslip_items"


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "es_calculation_snapshot" not in _columns(PAYSLIPS):
        op.add_column("payslip_items", sa.Column("es_calculation_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "es_calculation_snapshot" in _columns(PAYSLIPS):
        op.drop_column(PAYSLIPS, "es_calculation_snapshot")

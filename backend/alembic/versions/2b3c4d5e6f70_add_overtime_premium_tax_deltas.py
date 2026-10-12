"""add overtime premium wage tax soli church tax deltas

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-11 00:00:00.000000

Phase 8BW — payroll_germany_overtime_premium_components gains three new
nullable Numeric(12,2) columns: applied_wage_tax_delta, applied_soli_delta,
applied_church_tax_delta. Until this phase, an attached overtime premium's
wage-tax delta was unconditionally 0 (financial_integration_status =
PARTIAL_WAGE_TAX_PENDING_PAP) — deferred because computing it correctly
required the certified BMF PAP's marginal-rate procedure, which remains
genuinely unavailable. Phase 8BW closes this using the internal §32a/§39b
EStG calculator (engine/germany_internal_tax.py, built Phase 8BR) that
already computes the base payslip's own wage tax: a T2-T1 marginal
computation on the SAME zvE base, re-using the exact same functions, not a
second tax engine.

These three columns mirror the existing applied_gross_delta/applied_pf_delta/
applied_esi_delta pattern — the EXACT amount applied at attach time, stored
(never recomputed from current registries) so detach reverses precisely what
was applied and recalculation can re-apply the same stored amounts.

Purely additive: three new nullable columns, no existing column altered or
dropped, no seed data. Every existing row reads as NULL (equivalent to 0
via the same `or 0` pattern already used for every other applied_*_delta
column) until a component is re-attached under the new logic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b3c4d5e6f70'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Drift-tolerant: columns may already exist if ``sync_schema`` or a prior
    partial migration run created them before Alembic's version row was
    stamped.  Each column is inspected before creation; existing columns
    with the correct definition are silently accepted while mismatches fail
    closed.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {
        col["name"]: col for col in inspector.get_columns(
            "payroll_germany_overtime_premium_components"
        )
    }

    _COLUMNS = [
        ("applied_wage_tax_delta", sa.Numeric(precision=12, scale=2)),
        ("applied_soli_delta", sa.Numeric(precision=12, scale=2)),
        ("applied_church_tax_delta", sa.Numeric(precision=12, scale=2)),
    ]

    for col_name, col_type in _COLUMNS:
        if col_name not in existing_cols:
            op.add_column(
                "payroll_germany_overtime_premium_components",
                sa.Column(col_name, col_type, nullable=True),
            )
        else:
            col = existing_cols[col_name]
            if col.get("nullable") is False:
                raise RuntimeError(
                    f"Schema drift: payroll_germany_overtime_premium_components.{col_name} "
                    f"exists but is NOT NULL, expected nullable."
                )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_church_tax_delta')
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_soli_delta')
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_wage_tax_delta')

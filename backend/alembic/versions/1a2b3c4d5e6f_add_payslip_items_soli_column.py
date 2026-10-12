"""add payslip_items soli column

Revision ID: 1a2b3c4d5e6f
Revises: f5a6b7c8d9e0
Create Date: 2026-09-10 00:00:00.000000

Phase 8BN — payslip_items.soli: persists the monthly Solidaritätszuschlag
(Soli) a real BMF PAP run returns (germany_pap adapter's SOLZLZZ output).
PURELY informational on the backing row: Germany `tds` already folds
Lohnsteuer + Soli together (engine/countries/germany.py), so this column is
never summed into total_deductions/net_pay — same convention the
cpp_base_amount/cpp_first_additional_amount columns document for Canada.

This is the one genuinely necessary schema change of the Phase 8BN
implementation program (PayslipItem has no per-Soli column today, so the
summary report can only say "UNAVAILABLE"). Purely additive: one new
nullable Numeric(12,2) column defaulting to 0, no existing table/column
altered or dropped, no seed data. Every existing row reads as 0 until a
real PUBLISHED PapAlgorithmAsset is released and executed — honest, never
fabricated.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('soli', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'soli')
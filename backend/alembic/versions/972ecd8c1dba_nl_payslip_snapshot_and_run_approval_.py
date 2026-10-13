"""nl_payslip_snapshot_and_run_approval_fingerprint

Revision ID: 972ecd8c1dba
Revises: 774eeaf9b33c
Create Date: 2026-10-13 10:26:05.091645

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '972ecd8c1dba'
down_revision: Union[str, Sequence[str], None] = '774eeaf9b33c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """NL payslip calculation snapshot + run approval fingerprint (ZP-NL-ENG-001 §12).

    payslip_items.nl_calculation_snapshot holds the frozen NL context + nl_result
    exactly as computed (replayed by corrections, never reconstructed);
    payroll_runs.nl_approval_fingerprint holds the approval binding
    {fingerprint, approvedBy, approvedAt} (NL-034), same shape as SA's.
    """
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
    op.add_column("payslip_items", sa.Column("nl_calculation_snapshot", json_type, nullable=True))
    op.add_column("payroll_runs", sa.Column("nl_approval_fingerprint", json_type, nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_runs", "nl_approval_fingerprint")
    op.drop_column("payslip_items", "nl_calculation_snapshot")

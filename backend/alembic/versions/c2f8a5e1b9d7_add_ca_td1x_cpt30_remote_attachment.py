"""add payroll_employees CA TD1X/CPT30/remote-attachment columns

Revision ID: c2f8a5e1b9d7
Revises: b7e4a9c1d3f6
Create Date: 2026-09-02 00:00:00.000000

Additive only: six new nullable/defaulted columns on payroll_employees.

td1_additional_tax / cpp_qpp_election_status / cpp_election_effective_date
promote Canada's TD1X additional-withholding request and CPT30 CPP/QPP
election out of nothing (these were never collectible before this
migration, backend or frontend) into real, engine-read columns.

remote_work_agreement / remote_attachment_province /
remote_agreement_effective_from support the "reasonable attachment"
branch of the Province-of-Employment resolver (ZP-TAX-CA-2026-001 §5
step 4) for a full-time remote worker — NOT the multi-establishment
time-weighting branch (steps 2-3), which needs real establishment
records this schema doesn't have for any country and is a separate,
larger decision.

No existing column/table semantics change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f8a5e1b9d7'
down_revision: Union[str, Sequence[str], None] = 'b7e4a9c1d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('td1_additional_tax', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('payroll_employees', sa.Column('cpp_qpp_election_status', sa.String(length=20), nullable=True))
    op.add_column('payroll_employees', sa.Column('cpp_election_effective_date', sa.Date(), nullable=True))
    op.add_column('payroll_employees', sa.Column('remote_work_agreement', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('payroll_employees', sa.Column('remote_attachment_province', sa.String(length=10), nullable=True))
    op.add_column('payroll_employees', sa.Column('remote_agreement_effective_from', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'remote_agreement_effective_from')
    op.drop_column('payroll_employees', 'remote_attachment_province')
    op.drop_column('payroll_employees', 'remote_work_agreement')
    op.drop_column('payroll_employees', 'cpp_election_effective_date')
    op.drop_column('payroll_employees', 'cpp_qpp_election_status')
    op.drop_column('payroll_employees', 'td1_additional_tax')

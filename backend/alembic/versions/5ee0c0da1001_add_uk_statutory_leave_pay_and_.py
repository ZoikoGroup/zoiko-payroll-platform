"""add UK statutory leave pay columns and connected_group_code

Revision ID: 5ee0c0da1001
Revises: 1a6f89e93080
Create Date: 2026-09-09 07:00:00.000000

ZP-TAX-UK-2026-27-001 §11/§12/§14 gap-closure Part 7: statutory family
pay snapshot fields on payroll_leave_requests (Part 7A), and a
connected_group_code column on organizations for shared Employment
Allowance allocation (Part 7B). All nullable/additive, NULL for every
existing row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ee0c0da1001'
down_revision: Union[str, Sequence[str], None] = '1a6f89e93080'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_leave_requests', sa.Column('statutory_pay_type', sa.String(length=10), nullable=True))
    op.add_column('payroll_leave_requests', sa.Column('statutory_awe_snapshot', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('payroll_leave_requests', sa.Column('statutory_pay_total_amount', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('payroll_leave_requests', sa.Column('statutory_pay_note', sa.String(length=255), nullable=True))
    op.add_column('organizations', sa.Column('connected_group_code', sa.String(length=50), nullable=True))
    op.create_index('ix_organizations_connected_group_code', 'organizations', ['connected_group_code'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_organizations_connected_group_code', table_name='organizations')
    op.drop_column('organizations', 'connected_group_code')
    op.drop_column('payroll_leave_requests', 'statutory_pay_note')
    op.drop_column('payroll_leave_requests', 'statutory_pay_total_amount')
    op.drop_column('payroll_leave_requests', 'statutory_awe_snapshot')
    op.drop_column('payroll_leave_requests', 'statutory_pay_type')

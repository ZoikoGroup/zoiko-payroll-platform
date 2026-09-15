"""add payroll_new_hire_reports table

Revision ID: 14a7f3dd4c96
Revises: 2b8cb41dfbed
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14a7f3dd4c96'
down_revision: Union[str, Sequence[str], None] = '2b8cb41dfbed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_new_hire_reports',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('work_state', sa.String(100), nullable=True),
        sa.Column('hire_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),
        sa.Column('filed_date', sa.Date(), nullable=True),
        sa.Column('filed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payroll_new_hire_reports')

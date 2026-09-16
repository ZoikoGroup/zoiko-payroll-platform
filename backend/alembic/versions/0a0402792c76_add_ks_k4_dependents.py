"""add ks_k4_dependents

Revision ID: 0a0402792c76
Revises: 737e7bfa2d77
Create Date: 2026-09-16

Kansas Form K-4 certified dependent count (Production-Readiness Plan
Phase 4). See models.PayrollEmployee.ks_k4_dependents' own docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a0402792c76'
down_revision: Union[str, Sequence[str], None] = '737e7bfa2d77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('ks_k4_dependents', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'ks_k4_dependents')

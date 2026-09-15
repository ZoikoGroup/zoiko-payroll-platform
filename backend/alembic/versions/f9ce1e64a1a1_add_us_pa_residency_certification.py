"""add payroll_employees PA residency certification fields

Revision ID: f9ce1e64a1a1
Revises: ffe310357ab2
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9ce1e64a1a1'
down_revision: Union[str, Sequence[str], None] = 'ffe310357ab2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('residency_certification_on_file', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('payroll_employees', sa.Column('residency_certification_date', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'residency_certification_date')
    op.drop_column('payroll_employees', 'residency_certification_on_file')

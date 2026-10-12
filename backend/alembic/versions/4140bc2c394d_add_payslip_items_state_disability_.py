"""add payslip_items state_disability_insurance column

Revision ID: 4140bc2c394d
Revises: 048c9fc1d64f
Create Date: 2026-08-31 17:04:09.115439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4140bc2c394d'
down_revision: Union[str, Sequence[str], None] = '048c9fc1d64f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('state_disability_insurance', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'state_disability_insurance')

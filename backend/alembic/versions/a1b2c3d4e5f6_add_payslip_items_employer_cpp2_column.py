"""add payslip_items employer_cpp2 column

Revision ID: a1b2c3d4e5f6
Revises: de3521c74a64
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'de3521c74a64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('employer_cpp2', sa.Numeric(precision=12, scale=2), server_default='0', nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'employer_cpp2')

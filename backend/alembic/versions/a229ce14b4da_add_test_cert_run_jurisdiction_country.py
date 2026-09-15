"""add payroll_test_certification_runs jurisdiction_country column

Revision ID: a229ce14b4da
Revises: fcee2fcdc8c0
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a229ce14b4da'
down_revision: Union[str, Sequence[str], None] = 'fcee2fcdc8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_test_certification_runs',
        sa.Column('jurisdiction_country', sa.String(10), nullable=False, server_default='UK'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_test_certification_runs', 'jurisdiction_country')

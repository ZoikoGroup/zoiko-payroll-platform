"""add payroll_source_artifacts created_by_id column

Revision ID: 6125d07f78f9
Revises: f9ce1e64a1a1
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6125d07f78f9'
down_revision: Union[str, Sequence[str], None] = 'f9ce1e64a1a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_source_artifacts',
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_source_artifacts', 'created_by_id')

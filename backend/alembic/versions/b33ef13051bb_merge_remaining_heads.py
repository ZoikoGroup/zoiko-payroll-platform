"""Merge remaining heads

Revision ID: b33ef13051bb
Revises: 0a0402792c76, 4b296dbd4181
Create Date: 2026-09-16 16:04:07.295231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b33ef13051bb'
down_revision: Union[str, Sequence[str], None] = ('0a0402792c76', '4b296dbd4181')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

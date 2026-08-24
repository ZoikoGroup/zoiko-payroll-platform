"""merge public assist mode and token supersession heads

Revision ID: 7f92c2c49457
Revises: 96233c0e18d4, 3e8a1c47d5f2
Create Date: 2026-08-24 13:10:09.060069

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f92c2c49457'
down_revision: Union[str, Sequence[str], None] = ('96233c0e18d4', '3e8a1c47d5f2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

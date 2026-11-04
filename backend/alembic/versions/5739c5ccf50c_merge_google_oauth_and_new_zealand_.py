"""merge Google OAuth and New Zealand leave pay heads

Revision ID: 5739c5ccf50c
Revises: 7a3c9e1f2b4d, c6ea8c6c35ce
Create Date: 2026-11-04 19:07:05.597277

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5739c5ccf50c'
down_revision: Union[str, Sequence[str], None] = ('7a3c9e1f2b4d', 'c6ea8c6c35ce')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

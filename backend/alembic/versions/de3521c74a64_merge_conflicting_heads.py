"""merge conflicting heads

Revision ID: de3521c74a64
Revises: c2f8a5e1b9d7
Create Date: 2026-09-02 18:51:01.227356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de3521c74a64'
down_revision: Union[str, Sequence[str], None] = 'c2f8a5e1b9d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""merge country entitlement and main migrations

Revision ID: d4c8f1a7b2e9
Revises: b4d6f8a0c2e3, 3880223bfaa0
Create Date: 2026-10-29 16:45:16.804899

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4c8f1a7b2e9'
down_revision: Union[str, Sequence[str], None] = ('b4d6f8a0c2e3', '3880223bfaa0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

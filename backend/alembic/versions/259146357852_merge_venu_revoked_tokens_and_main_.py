"""merge venu (revoked_tokens) and main (Germany 2026 + Commercial Billing) heads

Revision ID: 259146357852
Revises: 767a807fc98e, 3a1b4cff7f0e
Create Date: 2026-09-18 19:13:35.498498

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '259146357852'
down_revision: Union[str, Sequence[str], None] = ('767a807fc98e', '3a1b4cff7f0e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

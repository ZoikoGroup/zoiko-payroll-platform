"""merge venu and main heads

Revision ID: 493a6e23cea1
Revises: 2b3c4d5e6f70, 941d9ec5ef7e
Create Date: 2026-09-15 16:10:50.022065

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '493a6e23cea1'
down_revision: Union[str, Sequence[str], None] = ('2b3c4d5e6f70', '941d9ec5ef7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

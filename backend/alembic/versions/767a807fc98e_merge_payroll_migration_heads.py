"""merge payroll migration heads

Revision ID: 767a807fc98e
Revises: 799b28d80edd, f6c8b1a4e9d3
Create Date: 2026-09-18 15:16:24.304000

No-op bookkeeping merge uniting the Germany 2026 all-Länder jurisdiction
head (799b28d80edd) and the Commercial Billing & Subscription Standard
head (f6c8b1a4e9d3). Both lines of work operate on orthogonal database
tables and require no schema reconciliation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '767a807fc98e'
down_revision: Union[str, Sequence[str], None] = ('799b28d80edd', 'f6c8b1a4e9d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

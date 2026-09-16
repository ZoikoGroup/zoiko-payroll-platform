"""merge venu and main heads

Revision ID: 493a6e23cea1
Revises: c1f5a9d22e10, 941d9ec5ef7e
Create Date: 2026-09-15 16:10:50.022065

Corrected 2026-09-16: originally merged against '2b3c4d5e6f70' (an ancestor
BEFORE main's billing chain even starts), not main's own true current tip.
That happened because this file was created before the 3 intervening
main-only migrations (38263fcf0a1d/76e050fd5ffd/c1f5a9d22e10 — workspace_type
+ billing tables + billing grace period) had been copied into this branch's
own alembic/versions/ at all, so alembic could only see 2b3c4d5e6f70 as
main's nearest known head. No-op either way (empty upgrade/downgrade) — the
live DB's actual schema already has every table/column from BOTH chains
(confirmed by direct inspection: payroll_new_hire_reports and
payroll_locality_rates.bracket_schedule already exist, likely created by
app/database.py's own create_all bootstrap on a fresh DB, independent of
Alembic's bookkeeping). This merge only fixes that bookkeeping.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '493a6e23cea1'
down_revision: Union[str, Sequence[str], None] = ('c1f5a9d22e10', '941d9ec5ef7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

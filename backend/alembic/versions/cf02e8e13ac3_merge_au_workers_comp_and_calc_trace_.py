"""merge au workers-comp/charity-exempt branch with au calculation-trace branch

Revision ID: cf02e8e13ac3
Revises: e11dfee2e48c, a905d1c2074c
Create Date: 2026-09-17

Australia 2026-27 statutory build — no-op bookkeeping merge, fixing a
self-inflicted fork on the AU migration chain (found during the
2026-09-17 alembic-head-reconciliation pass, independent of the
b33ef13051bb/f1b78410d568 conflict Rugvedh's team already fixed on
`main` — see fbfe6d7eeb2e).

`40efec6cf8b7` (add au_payroll_tax_charity_exempt) ended up with TWO
children: `518b8d4a5e46` (widen tax_slabs.filing_status, chained to
`40efec6cf8b7` when it was still the head at the time) and
`a905d1c2074c` (add au_calculation_trace, created later in the same
session without checking whether `40efec6cf8b7` already had a
descendant). This left `e11dfee2e48c` (the tip of the
518b8d4a5e46 -> 1aa5f3e80f3a -> e11dfee2e48c VARCHAR/NUMERIC-widening
branch) as an orphaned, unreferenced head alongside `a905d1c2074c`. No
schema change here — purely reconciles the Alembic graph.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf02e8e13ac3'
down_revision: Union[str, Sequence[str], None] = ('e11dfee2e48c', 'a905d1c2074c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "Cannot safely downgrade a merge point without selecting a branch."
    )

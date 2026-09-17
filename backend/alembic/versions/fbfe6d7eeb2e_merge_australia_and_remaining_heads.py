"""merge australia and remaining heads

Revision ID: fbfe6d7eeb2e
Revises: b33ef13051bb, f1b78410d568
Create Date: 2026-09-17 00:00:00.000000

Phase 8CR — no-op bookkeeping merge, landing the fix independently
designed and validated in a disposable worktree by Phase 8CO.
`f1b78410d568` (Australia 2026-27 statutory build, PR #47/venu, `add
payslip_items au_statutory_deductions_total column`) was authored on a
branch that forked from a point already containing `4b296dbd4181` but
before `b33ef13051bb` (`Merge remaining Alembic heads (0a0402792c76,
4b296dbd4181) into a single head`, commit `cae9d53`, ~2h49m earlier the
same day) had reconciled that lineage with the separate `0a0402792c76`
branch. When PR #47 was merged into `main`, git's file-level merge
succeeded cleanly (no path conflict — different migration files), but no
Alembic-level merge migration was run afterward, leaving two parallel
heads. Independently re-verified in Phase 8CR (not merely re-read from
Phase 8CO's report): both heads share 107 common ancestors, neither is an
ancestor of the other, nearest common ancestor `4b296dbd4181`. This
migration only unifies the Alembic graph bookkeeping into a single head;
it changes nothing in the database schema.

`downgrade()` deliberately raises rather than silently no-oping: a merge
point has two parents, and there is no single unambiguous branch to
revert to without an explicit operator choice — see the function body for
detail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbfe6d7eeb2e'
down_revision: Union[str, Sequence[str], None] = ('b33ef13051bb', 'f1b78410d568')
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

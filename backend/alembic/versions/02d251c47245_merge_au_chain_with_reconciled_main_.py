"""merge au migration chain with reconciled main head

Revision ID: 02d251c47245
Revises: cf02e8e13ac3, fbfe6d7eeb2e
Create Date: 2026-09-17

Final step of the 2026-09-17 alembic-head-reconciliation pass. `main`'s
own head `fbfe6d7eeb2e` (from PR #48, ZoikoGroup/fix/main-alembic-head-
repair) already reconciled `b33ef13051bb` (billing branch) with
`f1b78410d568` (the AU chain as it stood when PR #47/venu was merged —
just the early au_statutory_deductions_total column). Since then, the
`venu` branch continued the AU chain locally with 8 further migrations
(d356014e3357 through a905d1c2074c, unified at `cf02e8e13ac3` above),
diverging from `f1b78410d568` independently of `fbfe6d7eeb2e`. This
migration reconciles the two remaining heads into one. No schema
change — purely reconciles the Alembic graph.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02d251c47245'
down_revision: Union[str, Sequence[str], None] = ('cf02e8e13ac3', 'fbfe6d7eeb2e')
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

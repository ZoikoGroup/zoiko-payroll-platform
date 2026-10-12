"""merge main's Hong Kong convergence with venu's Italy/CH/attendance chain

Revision ID: f898189cb4e3
Revises: 2d0cdeeeecc4, c5981cbcbe13
Create Date: 2026-10-06 00:00:00.000000

Both chains grow from cd62503afe26 (Hong Kong statutory foundation): main's
2d0cdeeeecc4 (hkg_* -> payroll_hk_* / hk_* renames + HK workflow uniqueness)
and venu's c9d8e7f6a5b4 -> d7e6f5a4b3c2 (Italy F24 causale / LUL content) ->
3baddbaa011a -> 376bb8637603 (Switzerland) -> c5981cbcbe13 (attendance gate).
They touch disjoint tables and columns, so this is a pure graph merge with no
schema change of its own (same shape as 66072e2d80a9).
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'f898189cb4e3'
down_revision: Union[str, Sequence[str], None] = ('2d0cdeeeecc4', 'c5981cbcbe13')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

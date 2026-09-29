"""merge main's Singapore chain with venu's Ireland/France/performance chain

Revision ID: 66072e2d80a9
Revises: 445abd6a9083, c4d5e6f7a8b9
Create Date: 2026-09-29 00:00:00.000000

Both chains grow from 998877665544: main's Singapore revisions
(c3d9e1f4a7b2 ... 445abd6a9083, all sgp_* tables and payroll_employees /
payslip_items SG columns) and venu's (7c3e1a9d5f20 IE/FR column restore,
b3c4d5e6f7a8 attendance index, c4d5e6f7a8b9 Ireland Revenue tables). They
touch disjoint tables and columns, so this is a pure graph merge with no
schema change of its own.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '66072e2d80a9'
down_revision: Union[str, Sequence[str], None] = ('445abd6a9083', 'c4d5e6f7a8b9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

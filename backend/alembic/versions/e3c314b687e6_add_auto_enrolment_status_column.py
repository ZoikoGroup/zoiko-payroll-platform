"""add payslip_items.auto_enrolment_status column

Revision ID: e3c314b687e6
Revises: bc2d64432eaa
Create Date: 2026-09-09 05:00:00.000000

ZP-TAX-UK-2026-27-001 §13/Layer 5 gap-closure Part 3: a real Automatic
Enrolment assessment (ELIGIBLE_JOBHOLDER/NON_ELIGIBLE_JOBHOLDER/
ENTITLED_WORKER) computed from age + qualifying earnings, purely
informational — never changes the employee_pension/employer_pension
columns' own calculation. NULL for every existing payslip.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3c314b687e6'
down_revision: Union[str, Sequence[str], None] = 'bc2d64432eaa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('auto_enrolment_status', sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'auto_enrolment_status')

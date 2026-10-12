"""add payroll_source_artifacts file storage columns

Revision ID: 2b8cb41dfbed
Revises: 6125d07f78f9
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b8cb41dfbed'
down_revision: Union[str, Sequence[str], None] = '6125d07f78f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_source_artifacts', sa.Column('file_path', sa.String(500), nullable=True))
    op.add_column('payroll_source_artifacts', sa.Column('original_filename', sa.String(255), nullable=True))
    op.add_column('payroll_source_artifacts', sa.Column('content_type', sa.String(100), nullable=True))
    op.add_column('payroll_source_artifacts', sa.Column('file_size_bytes', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_source_artifacts', 'file_size_bytes')
    op.drop_column('payroll_source_artifacts', 'content_type')
    op.drop_column('payroll_source_artifacts', 'original_filename')
    op.drop_column('payroll_source_artifacts', 'file_path')

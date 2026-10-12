"""add rti submission schema version column

Revision ID: 8849ac83b135
Revises: d356014e3357
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Phase 9 —
closes AU-AC23/AU-AC24 by adding a generic, platform-wide
payroll_rti_submissions.schema_version column (independent of the
tax-rule package version already tracked on GeneratedReport), reused for
Australia's STP/SuperStream submissions rather than a second, AU-only
version-tracking mechanism. See models.RtiSubmission's own docstring.

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
d356014e3357 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision; this file is not applied to any
database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8849ac83b135'
down_revision: Union[str, Sequence[str], None] = 'd356014e3357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_rti_submissions', sa.Column('schema_version', sa.String(30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_rti_submissions', 'schema_version')

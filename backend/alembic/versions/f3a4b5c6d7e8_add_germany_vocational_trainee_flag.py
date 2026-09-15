"""add germany vocational trainee flag

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-03 00:00:00.000000

Phase 8L (docs/PHASE_8L_GERMANY_STATUTORY_EDGE_CASE_COMPLETION_REPORT.md).

Additive only: one new nullable Boolean column,
payroll_employee_statutory_profiles.de_vocational_trainee. Confirmed live
this phase (§20 Abs. 2a Satz 9 SGB IV, gesetze-im-internet.de) that an
employee engaged "zu ihrer Berufsausbildung" (Ausbildungsvertrag,
Praktikum zur Berufsausbildung, duales Studium) is excluded from the
Übergangsbereich/Midijob regime regardless of earnings — a narrow, well-
evidenced statutory condition distinct from any existing field, so a new
column was added rather than overloading de_employment_classification or
inventing an unrelated boolean. NULL for every existing row (correctly
interpreted as "not a vocational trainee" by
validate_classification_against_vocational_training, matching this
column's own nullable default semantics).

No existing column/table altered. No data backfilled — no row in any
environment currently sets this (the field did not exist before).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employee_statutory_profiles',
        sa.Column('de_vocational_trainee', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employee_statutory_profiles', 'de_vocational_trainee')

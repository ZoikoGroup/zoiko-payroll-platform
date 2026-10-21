"""nl_expat_recorded_by — who recorded a 30% facility decision (four-eyes, NL-026)

A tenant now records AND verifies its own 30% decisions (ZP-PRIV moved them out
of Super Admin), so verification must be done by a second person. Without the
recorder on the row that cannot be enforced. Nullable: rows recorded before this
column exist have no recorder and can no longer be verified — they must be
recorded again (the service fails closed).

Revision ID: f84626be0cb1
Revises: e7a2c4f9b1d6
Create Date: 2026-10-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f84626be0cb1"
down_revision: Union[str, Sequence[str], None] = "e7a2c4f9b1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_nl_expat_decisions",
                  sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                            nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_nl_expat_decisions", "recorded_by")

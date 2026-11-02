"""organization_timezone: store the timezone chosen at registration

Revision ID: 668472e4eb72
Revises: f686d5128f8a
Create Date: 2026-10-30

The registration form has always sent an IANA timezone (e.g. "Asia/Kolkata")
but nothing stored it. Adds one nullable column, organizations.timezone;
organisations created before this keep NULL (unknown - never guessed).
Additive only, idempotent both ways, lock_timeout fail-fast on PostgreSQL.
A literal op.add_column so scripts/drift_pending_filter explains it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "668472e4eb72"
down_revision: Union[str, Sequence[str], None] = "f686d5128f8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "timezone" not in _columns("organizations"):
        op.add_column("organizations", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "timezone" in _columns("organizations"):
        op.drop_column("organizations", "timezone")

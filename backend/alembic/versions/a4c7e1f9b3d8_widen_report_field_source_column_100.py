"""widen_report_field_source_column_100: payroll_report_template_component_fields.source_column -> VARCHAR(100)

Revision ID: a4c7e1f9b3d8
Revises: e9c4b7a2d6f3
Create Date: 2026-11-17

Schema-drift fix. c4a91e7bd026 created source_column as VARCHAR(50) and models.py said String(50), but the
production column is already VARCHAR(100) (widened by hand, never by a migration). This revision records the
100-character width so every database converges on it and the model can rely on it.

Upgrade is idempotent: it reads the column's current length and only ALTERs when it is shorter than 100, so on
production (already 100) it changes nothing. PostgreSQL widening a VARCHAR never rewrites the table.

SQLite does not enforce VARCHAR length and a batch ALTER would rebuild the table, so it is skipped there.

Downgrade narrows back to 50, but REFUSES (raises) if any row's source_column is longer than 50 characters —
it never truncates a stored field path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e1f9b3d8"
down_revision: Union[str, Sequence[str], None] = "e9c4b7a2d6f3"   # be_onss_rate_table (Block M-ECWC)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_report_template_component_fields"
COLUMN = "source_column"
WIDE = 100
NARROW = 50


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _current_length():
    """The column's declared character length, or None if the table/column is absent."""
    row = op.get_bind().execute(sa.text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
    ), {"t": TABLE, "c": COLUMN}).first()
    return None if row is None else row[0]


def upgrade() -> None:
    if not _postgres():
        return
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    length = _current_length()
    if length is None or length >= WIDE:
        return  # absent, or already VARCHAR(100) (production) — nothing to do
    op.alter_column(TABLE, COLUMN, existing_type=sa.String(length=length), type_=sa.String(length=WIDE),
                    existing_nullable=False)


def downgrade() -> None:
    if not _postgres():
        return
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    length = _current_length()
    if length is None or length <= NARROW:
        return
    too_long = op.get_bind().execute(sa.text(
        f"SELECT count(*) FROM {TABLE} WHERE char_length({COLUMN}) > {NARROW}")).scalar()
    if too_long:
        raise RuntimeError(
            f"Refusing to narrow {TABLE}.{COLUMN} to VARCHAR({NARROW}): {too_long} row(s) hold a longer "
            f"field path. Remove or shorten those report fields first; this downgrade never truncates.")
    op.alter_column(TABLE, COLUMN, existing_type=sa.String(length=length), type_=sa.String(length=NARROW),
                    existing_nullable=False)

"""widen_tax_slabs_tax_regime_40: payroll_tax_slabs.tax_regime -> VARCHAR(40)

Revision ID: c3e8a1d5f7b2
Revises: a4c7e1f9b3d8
Create Date: 2026-11-18

Production defect (2026-11-18): Super Admin > Belgium > "Create the Draft pack" returned 500. The governed seed
writes the 180 Belgian earning-classification rows into payroll_tax_slabs with the obligation code in tax_regime,
and one obligation code (WITHHOLDING_EXCEPTIONAL) is 23 characters; tax_regime was VARCHAR(20), so PostgreSQL
raised StringDataRightTruncation and the whole seed rolled back (nothing was written). SQLite does not enforce
VARCHAR length, which is why no SQLite test saw it. Reproduced on PostgreSQL 17 with the real seed; with this
column at 40 the seed completes (tests/test_belgium_seed_postgres.py).

Upgrade is idempotent: it reads the column's current length and only ALTERs when it is shorter than 40.
PostgreSQL widening a VARCHAR never rewrites the table. SQLite is skipped (no length enforcement; a batch ALTER would
rebuild the table).

Downgrade narrows back to 20 but REFUSES (raises) if any row's tax_regime is longer than 20 characters — it never
truncates a stored value.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8a1d5f7b2"
down_revision: Union[str, Sequence[str], None] = "a4c7e1f9b3d8"   # report-field source_column VARCHAR(100)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_tax_slabs"
COLUMN = "tax_regime"
WIDE = 40
NARROW = 20


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
        return  # absent, or already at least VARCHAR(40) — nothing to do
    op.alter_column(TABLE, COLUMN, existing_type=sa.String(length=length), type_=sa.String(length=WIDE),
                    existing_nullable=True)


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
            f"Refusing to narrow {TABLE}.{COLUMN} to VARCHAR({NARROW}): {too_long} row(s) hold a longer value "
            f"(e.g. Belgian earning-class obligations). Remove those rows first; this downgrade never truncates.")
    op.alter_column(TABLE, COLUMN, existing_type=sa.String(length=length), type_=sa.String(length=NARROW),
                    existing_nullable=True)

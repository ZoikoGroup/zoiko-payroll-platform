"""Italy LUL registered content + authorized method (§20, IT-058/IT-059/IT-060)

Revision ID: d7e6f5a4b3c2
Revises: c9d8e7f6a5b4
Create Date: 2026-10-05 00:00:00.000000

ZP-IT-ENG-001 section 20, phase 3C. Four additive columns on
payroll_it_lul_entries, no new tables:

  payload
      The registration migration 917a54ed2347 gave ItalyLulEntry a
      `content_hash` but nowhere to put the CONTENT it hashes. A hash with no
      content cannot discharge IT-058 ("an auditable statutory record, not a PDF
      theme") or IT-060 (export/archival controls for employer or authorized
      consultant custody): you can prove bytes have not moved, but you cannot
      show what was filed, so nobody can verify the record they are obliged to
      keep for five years. Hashing without storing was the gap.

      Nullable, because the pre-3C rows cannot be back-filled and inventing
      their content would be worse than admitting it is unknown.

  event_kind
      The statutory event (an assunzione, a cessazione, a monthly pay
      communication, ...). Deliberately NOT validated against a closed
      vocabulary: spec source S10 (the official LUL catalog) is not yet
      available, and inventing the list is precisely what IT-043 forbids for F24
      causali. It is recorded as governed data so that whoever holds the real
      catalog supplies it, and so that inventing one here is a visible act.

  method
      The authorized employer method (WEB / software / intermediary) in force at
      registration. Snapshot, not a live join: if the employer switches method
      next year, last year's registrations must still show the method they were
      actually made under. §17G.

  registered_reference
      The reference month the registration covers, denormalized from
      reference_month only for the index that answers "what is still retained"
      during the retention sweep. Nullable for the same reason as payload.

Retention semantics are NOT changed by this revision, but they are worth
stating because they are easy to get backwards: the spec sets retention at
"five years from the LAST registration", so the horizon ADVANCES with each new
registration rather than being fixed per entry. That logic lives in the service
(build_italy_lul_entries); this revision only makes the content auditable.

Every operation is guarded (skipped when its column already exists), matching
the pattern adopted after the 2026-09-29 deploy failed on a table an unmerged
branch had already created.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e6f5a4b3c2'
down_revision: Union[str, Sequence[str], None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENTRY_TABLE = 'payroll_it_lul_entries'
NEW_COLUMNS = ('payload', 'event_kind', 'method', 'registered_reference')


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns():
    if not _has_table(ENTRY_TABLE):
        return set()
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(ENTRY_TABLE)}


def _add_column(name, column):
    if name in _existing_columns():
        return
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table(ENTRY_TABLE) as batch:
            batch.add_column(column)
    else:
        op.add_column(ENTRY_TABLE, column)


def upgrade() -> None:
    # The table name is literal rather than interpolated from ENTRY_TABLE:
    # tests/test_model_tables_have_migrations.py and the column guard below both
    # discover schema by textual scan, and a hidden name is indistinguishable
    # from one that was never migrated.
    _add_column('payload', sa.Column('payload', sa.JSON(), nullable=True))
    _add_column('event_kind', sa.Column('event_kind', sa.String(40), nullable=True))
    _add_column('method', sa.Column('method', sa.String(30), nullable=True))
    _add_column('registered_reference',
                sa.Column('registered_reference', sa.String(7), nullable=True, index=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == 'sqlite':
        for name in ('registered_reference', 'method', 'event_kind', 'payload'):
            if name in _existing_columns():
                with op.batch_alter_table(ENTRY_TABLE) as batch:
                    batch.drop_column(name)
    else:
        for name in ('registered_reference', 'method', 'event_kind', 'payload'):
            if name in _existing_columns():
                op.drop_column(ENTRY_TABLE, name)

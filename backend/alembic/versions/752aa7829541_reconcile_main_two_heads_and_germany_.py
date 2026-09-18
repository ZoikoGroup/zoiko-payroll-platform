"""reconcile main two heads and germany 2026 lineage (Phase 8DT)

Revision ID: 752aa7829541
Revises: 1dc04f15a9b7, a3f5c9d1b2e4, abaca1105dbb
Create Date: 2026-09-18 10:27:28.677873

No-op, additive-only merge (changes nothing in the database schema) that
unifies three independently-evolved Alembic tips discovered during the
Germany 2026 / main reconciliation (Phases 8DR/8DS/8DT):

  - `1dc04f15a9b7` (add_au_sapto_category_column) — `main`'s own head,
    and the exact revision production's `alembic_version` was observed
    stamped at during read-only forensics (Phases 8DR/8DS). A legitimate,
    unrelated Australia SAPTO migration, confirmed via full repository
    history search to exist nowhere outside `main`'s own lineage.
  - `a3f5c9d1b2e4` (create_legal_entities_table) — `main`'s OTHER,
    previously unreconciled head, which had never been merged with the
    one above. Both were proven fully connected to the same underlying
    history (confirmed via a full backward-reachability walk of every
    revision file on `main`) — this was a genuine, pre-existing two-heads
    split on `main` itself, unrelated to Germany.
  - `abaca1105dbb` (nikhil's Germany 2026 head — `add_jurisdiction_pack_id_
    to_germany_*`) — the tip of the Germany Compliance Pack schema work
    (`13ce5f1cf7a1`/`abaca1105dbb`), reconciled onto `main`'s canonical
    Alembic IDs for the 4 previously-collided rename pairs (see
    `65bc3ca96fd6`, `0800e995078f`, `185332840016`, `b4241285b6dd`, and
    `b7c8d9e0f2a3`'s own updated docstring) before this merge.

Every schema object either side of this merge represents was already
created by its own respective migration; this revision itself performs
zero DDL. Mirrors this repository's own long-established no-op merge
precedent (e.g. `de3521c74a64`, `65bc3ca96fd6`, `b5c6d7e8f9a2`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '752aa7829541'
down_revision: Union[str, Sequence[str], None] = ('1dc04f15a9b7', 'a3f5c9d1b2e4', 'abaca1105dbb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

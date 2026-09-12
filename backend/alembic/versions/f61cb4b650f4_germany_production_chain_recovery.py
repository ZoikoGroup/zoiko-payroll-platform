"""germany production chain recovery graft

Revision ID: f61cb4b650f4
Revises: c7d8e9f0a1b2
Create Date: 2026-09-12 00:00:00.000000

Purpose
-------
Production Alembic bookkeeping repair. The production PostgreSQL database's
``alembic_version`` table records revision ``f61cb4b650f4``, but no migration
file with that revision id has ever existed in this repository (verified
across every branch, tag, reflog and unreachable object). Every other alembic
command therefore fails with::

    Can't locate revision identified by 'f61cb4b650f4'

A read-only structural audit of the live production database (table /
column / index / constraint presence, compared against every migration in
this chain from its base ``0b624a4a7481`` upward) proves the production
schema already contains **every** object created by every migration through
revision ``c7d8e9f0a1b2`` and contains **none** of the objects created by
``d3e4f5a6b7c8`` or any later revision. The production database therefore
sits exactly at the schema state that revision ``c7d8e9f0a1b2`` represents,
even though its recorded version id comes from an older, untracked migration
lineage that is not present in this repository.

This revision is a deliberate "orphan graft": it records that the unknown
production lineage corresponds to the schema state of ``c7d8e9f0a1b2`` so
that ``alembic upgrade head`` can resolve the recorded version and continue
through the real migration chain (``d3e4f5a6b7c8``, ``e4f5a6b7c8d9``,
``f5a6b7c8d9e0``, ``1a2b3c4d5e6f``, ``2b3c4d5e6f70``), all of whose created
objects are currently absent from production and will be applied normally.

It is deliberately a no-op ("merge"-style bookkeeping revision, exactly like
the existing merge migrations in this same directory): the schema this
revision "represents" already exists in the target database, so running its
``upgrade()`` must not change anything. Its ``downgrade()`` is likewise a
no-op because there is no historical schema change it can reverse; the
recorded id predates this repository entirely.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f61cb4b650f4'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
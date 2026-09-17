"""germany production chain recovery graft

Revision ID: b7c8d9e0f2a3
Revises: a6b7c8d9e0f2
Create Date: 2026-09-12 00:00:00.000000

Purpose
-------
Production Alembic bookkeeping repair. At the time this revision was
originally authored (as `f61cb4b650f4`, commit `f8174a5`, 2026-09-12), the
production PostgreSQL database's ``alembic_version`` table was observed,
read-only, to record revision ``f61cb4b650f4`` — a value that did not match
any migration file anywhere in this repository at that time. A read-only
structural audit of the live production database (table/column/index/
constraint presence, compared against every migration in this chain from its
base ``0b624a4a7481`` upward) proved the production schema at that time
already contained **every** object created by every migration through
revision ``c7d8e9f0a1b2`` (this revision's original `down_revision`) and
contained **none** of the objects created by ``d3e4f5a6b7c8`` or any later
revision.

This revision was therefore a deliberate "orphan graft": it recorded that the
then-unresolvable production lineage corresponded to the schema state of
``c7d8e9f0a1b2`` so that ``alembic upgrade head`` could resolve the recorded
version and continue through the real migration chain (``d3e4f5a6b7c8``,
``e4f5a6b7c8d9``, ``f5a6b7c8d9e0``, ``1a2b3c4d5e6f``, ``2b3c4d5e6f70``).

It is deliberately a no-op ("merge"-style bookkeeping revision): the schema
this revision "represents" already existed in the target database at
authoring time, so its ``upgrade()``/``downgrade()`` are both no-ops.

Phase 8CG renumbering note (supersedes nothing above — historical record
preserved verbatim): this revision was originally `f61cb4b650f4`.
`origin/main` independently authored a real, unrelated schema migration
(`add_us_w4_step2_checkbox`) under the same 12-hex id on 2026-09-15 — three
days after this file was authored here — unaware of this usage, since
`nikhil`'s graft was never merged onto `main`. Per
`docs/GERMANY_2026_RECONCILIATION_IMPLEMENTATION_REPORT.md`'s own findings:
(1) three independent, separately-timed read-only production reads
(Phases 8CC/8CD) confirm today's production `alembic_version`
(`493a6e23cea1`) never passes through this graft at all — production instead
advanced along `origin/main`'s own, separately-evolving deployment history,
most likely explaining the once-orphaned reading this graft was built to fix
as `nikhil`'s local clone simply lagging behind `origin/main`'s latest state,
not a truly external migration lineage; (2) no non-production database, test
fixture, CI configuration, or documentation-external reference to this
revision's `nikhil` meaning was found anywhere in this repository. This
graft is therefore renamed (not deleted, preserving its documentary/forensic
value per `docs/GERMANY_2026_REPOSITORY_RECONCILIATION_DESIGN.md` §9) to
`b7c8d9e0f2a3`, and its `down_revision` is updated from `c7d8e9f0a1b2` to
`a6b7c8d9e0f2` (that revision's own Phase 8CG renumbering — see
`a6b7c8d9e0f2_merge_main_and_germany_production_heads_2.py`). Only the
`revision`/`down_revision` ids and this note changed; `upgrade()`/
`downgrade()` and every other line are unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f2a3'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
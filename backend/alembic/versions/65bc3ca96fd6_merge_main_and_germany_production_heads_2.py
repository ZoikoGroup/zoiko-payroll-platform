"""merge main and germany production heads 2

Revision ID: 65bc3ca96fd6
Revises: b5c6d7e8f9a2, b6c7d8e9f0a1
Create Date: 2026-09-08 00:00:00.000000

Phase 8BK follow-up — reconciles the two heads that appeared after
`origin/main` advanced past the point (`9f7c230`) the first merge
(`b5c6d7e8f9a2`) was based on: `b6c7d8e9f0a1` (main's own further India/
UK work — employer NPS, tax residency status, gender, director fields,
date of leaving, LWF, EPS/EDLI, apprenticeship levy, employee
establishments, contribution-rate precision). No-op, additive-only merge
point — changes nothing in the database schema itself, only unifies the
migration graph bookkeeping into a single head.

Phase 8CG renumbering note: this revision was originally authored as
`c7d8e9f0a1b2` (commit `f807e3b2`, 2026-09-08). `origin/main` independently
authored a real, unrelated schema migration
(`add_payroll_ytd_accumulators_table_widen_tax_year`) under the same 12-hex
id two days later, and later renamed *its own* copy to `65bc3ca96fd6` for
exactly this collision class. `origin/main`'s copy of `c7d8e9f0a1b2` is the
one that reached production (confirmed via three independent read-only
production reads across Phases 8CC/8CD, all `alembic_version` values found
downstream of it) and is therefore left untouched — see
`docs/GERMANY_2026_ALEMBIC_493A6E_FORENSIC_REPORT.md` and
`docs/GERMANY_2026_DEPLOYMENT_LINEAGE_FORENSIC_REPORT.md`. This `nikhil`-only
copy is the one renamed instead, to `a6b7c8d9e0f2`, per
`docs/GERMANY_2026_RECONCILIATION_IMPLEMENTATION_REPORT.md`'s rename map.
Only the `revision` id and this note changed; `down_revision`,
`upgrade()`/`downgrade()`, and every other line are unchanged.

Phase 8DT reconciliation note: `nikhil` had independently renamed its own
copy of this same original `c7d8e9f0a1b2` to `a6b7c8d9e0f2` (byte-identical
content, same down_revision tuple). Reconciled onto this file (`main`'s
canonical `65bc3ca96fd6`); `a6b7c8d9e0f2` was dropped as a redundant
duplicate, and `nikhil`'s downstream `b7c8d9e0f2a3` (the Germany production
chain recovery graft, which has no `main` equivalent) was re-parented onto
this revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65bc3ca96fd6'  # was c7d8e9f0a1b2 on main; renumbered — collided with an unrelated venu-branch migration id
down_revision: Union[str, Sequence[str], None] = ('b5c6d7e8f9a2', 'b6c7d8e9f0a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
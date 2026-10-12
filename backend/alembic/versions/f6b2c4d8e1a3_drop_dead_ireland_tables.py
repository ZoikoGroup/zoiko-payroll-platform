"""drop dead Ireland tables (7 IE tables -> 4 before the YTD merge)

Revision ID: f6b2c4d8e1a3
Revises: e5a1c7b9d204

ZP-IE-ENG-001, 2026-09-28. Drops three of the six tables shipped in
b1c2d3e4f5a6, all of which had no reader, no writer and no test anywhere in the
codebase. They are pure schema weight that a real deployment would carry
forever:

  payroll_ie_employer_profiles
      Was imported by service.py and nothing else. Every field it was meant to
      hold (ROS/remitter/bank/PRSI scope) is either already on the existing
      effective-dated payroll_employee_statutory_profiles table as an Ireland
      column block, or belongs on company settings. A second 1:1 Ireland
      employer table was the duplication, not the fix.

  payroll_ie_revenue_submissions
      ROS line-item submission queue. There is no ROS writer anywhere, and a
      submission table with no submission path is an empty table plus a
      false promise. It returns with Phase 3, when the ROS transport exists
      to write it, and not before — the alternative is shipping a half-built
      compliance surface nobody can operate.

  payroll_ie_revenue_monthly_returns
      Versioned ROS statement + reconciliation. Same reasoning, and it depends
      on the submissions table above.

Kept deliberately (see the sibling migration 2c7d9e0f3a5b): the RPN snapshot and
MyFutureFund status tables both have working readers, and the statutory sick
leave ledger is a statutory record Ireland requires.

Why this is a hard drop and not a rename/soft-delete: these tables were never
populated by any code path, so there is no data to preserve, and a deprecation
period for an empty table only postpones the cleanup. upgrade() therefore
asserts emptiness before dropping rather than silently discarding rows if some
out-of-band process did write to them — that is the one way this migration
could lose real data, and it refuses to do it.
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'f6b2c4d8e1a3'
down_revision: str = 'e5a1c7b9d204'
branch_labels = None
depends_on = None

# (table, index) pairs, dropped child-first: payroll_ie_revenue_submissions
# holds an FK to payroll_ie_rpn_snapshots, and while we are not dropping the
# latter, dropping in this order keeps the graph honest.
_DEAD_TABLES = (
    ("payroll_ie_revenue_monthly_returns", "ix_ie_monthly_return_org_period"),
    ("payroll_ie_revenue_submissions", "ix_ie_revsub_org_period"),
    ("payroll_ie_employer_profiles", None),
)


def _existing_tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes(table: str) -> set:
    """Index names on `table`, tolerating backends/inspectors that report
    differently. An index dropped by hand (or never created on a squashed
    history) must not turn a cleanup migration into a hard failure."""
    try:
        return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
    except (sa.exc.NoSuchTableError, NotImplementedError):
        return set()


def upgrade():
    present = _existing_tables()
    for table, index in _DEAD_TABLES:
        if table not in present:
            # Already absent (fresh install from a squashed history, or a
            # partially-applied run). Nothing to drop; do not fail the upgrade.
            continue
        count = op.get_bind().execute(
            sa.text("SELECT COUNT(*) FROM %s" % table)
        ).scalar() or 0
        if count:
            # Refuse to destroy data rather than drop it. No code path has ever
            # written these tables, so a non-zero count means something outside
            # this application owns them and the refactor needs a human.
            raise RuntimeError(
                "Cannot drop %s: it holds %d row(s). No Zoiko code path has ever "
                "written this table, so any row here was written out of band "
                "and needs to be migrated by hand before the table can be "
                "removed." % (table, count)
            )
        if index is not None and index in _existing_indexes(table):
            op.drop_index(index, table_name=table)
        op.drop_table(table)


def downgrade():
    # Re-creating the columns is deliberately NOT attempted: a downgrade that
    # invents a schema shape nobody has ever run is worse than one that says
    # plainly that the data is gone. These tables were always empty, so there
    # is nothing to lose but also nothing worth rebuilding automatically.
    raise RuntimeError(
        "Irreversible: payroll_ie_employer_profiles, "
        "payroll_ie_revenue_submissions and payroll_ie_revenue_monthly_returns "
        "were dropped empty and their schema shape is not reconstructed by this "
        "downgrade. Roll forward, or restore from a backup if a pre-migration "
        "database is genuinely required."
    )

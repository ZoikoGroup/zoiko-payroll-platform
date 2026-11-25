"""merge Spain foundation (86f1ec062709) with certification runs tied to a pack (e4b7c2a9d1f3)

Revision ID: c8d2f6a4e1b9
Revises: 86f1ec062709, e4b7c2a9d1f3
Create Date: 2026-11-25

Both revisions grow from merge b5f3e8a1c6d9:

  b5f3e8a1c6d9 -> 86f1ec062709 (Spain foundation: payslip_items.es_calculation_snapshot, main)
  b5f3e8a1c6d9 -> e4b7c2a9d1f3 (payroll_test_certification_runs.jurisdiction_pack_id + content_fingerprint, nikhil)

Merging main into nikhil left two heads, and the PR checks failed ("Expected exactly 1 head"). A merge
revision (rather than re-parenting either one) leaves both authors' files untouched, the same way
b5f3e8a1c6d9 joined the previous pair.

Nothing to do on upgrade or downgrade: the two revisions touch different tables (payslip_items vs
payroll_test_certification_runs) and neither depends on the other.
"""

revision = "c8d2f6a4e1b9"
down_revision = ("86f1ec062709", "e4b7c2a9d1f3")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

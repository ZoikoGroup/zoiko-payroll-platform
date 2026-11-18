"""merge UAE foundation (ad01fc67ce44) with report-template content editor (d7a3f1c9e5b2)

Revision ID: b5f3e8a1c6d9
Revises: ad01fc67ce44, d7a3f1c9e5b2
Create Date: 2026-11-18

Both revisions grow from c3e8a1d5f7b2 (payroll_tax_slabs.tax_regime VARCHAR(40)):

  c3e8a1d5f7b2 -> ad01fc67ce44 (United Arab Emirates foundation: payslip_items.ae_calculation_snapshot, venu, PR #178)
  c3e8a1d5f7b2 -> d7a3f1c9e5b2 (payroll_report_templates.content_editor_id, four-eyes, nikhil, PR #177)

PR #179 merged both into main, leaving two heads: its deploy (run 44283027705) failed at the test stage
(privacy-isolation: "Expected exactly 1 head, found 2"), and the deploy job (needs: test, privacy-isolation)
never ran, so neither revision is applied anywhere. A merge revision (rather than re-parenting either one)
leaves both authors' files untouched.

Nothing to do on upgrade or downgrade: the two revisions touch different tables (payroll_payslip_items vs
payroll_report_templates) and neither depends on the other.
"""

revision = "b5f3e8a1c6d9"
down_revision = ("ad01fc67ce44", "d7a3f1c9e5b2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

"""Merge the UAE breakdown-column head with the report-template content-editor head.

Both ad01fc67ce44 (payslip_items.ae_calculation_snapshot) and d7a3f1c9e5b2
(payroll_report_templates.content_editor_id) grow from c3e8a1d5f7b2. This joins them
into a single head. No schema change.

Revision ID: 2855a70a9ed6
Revises: ad01fc67ce44, d7a3f1c9e5b2
Create Date: 2026-11-18
"""

revision = "2855a70a9ed6"
down_revision = ("ad01fc67ce44", "d7a3f1c9e5b2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

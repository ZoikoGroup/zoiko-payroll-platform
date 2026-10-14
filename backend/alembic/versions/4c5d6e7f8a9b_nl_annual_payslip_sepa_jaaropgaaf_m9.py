"""nl_annual_payslip_sepa_jaaropgaaf_m9

Netherlands (ZP-NL-ENG-001) Phase 10 — Annual statements (jaaropgaaf),
SEPA payment batches (pain.001), and payment items.

Revision ID: 4c5d6e7f8a9b
Revises: 3b4e5c6d7e8f
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4c5d6e7f8a9b'
down_revision: Union[str, Sequence[str], None] = '3b4e5c6d7e8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # payroll_nl_annual_statements — Jaaropgaaf (annual wage/tax statement)
    # Generated from committed year-to-date totals only, never from current employee record (NL-048)
    op.create_table(
        "payroll_nl_annual_statements",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, sa.ForeignKey("payroll_nl_income_relationships.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("version", sa.SmallInteger, nullable=False, default=1),
        sa.Column("supersedes_id", sa.Integer, sa.ForeignKey("payroll_nl_annual_statements.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("fiscal_wage", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("wage_tax_withheld", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("applied_employment_credit", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("tax_credit_applied", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("zvw_wage", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("zvw_contribution", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("source_ledger_sha256", sa.String(64), nullable=False),
        sa.Column("document_ref", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="DRAFT"),  # DRAFT / ISSUED / AMENDED
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_channel", sa.String(50), nullable=True),  # PORTAL / EMAIL / DIGIPOORT
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'ISSUED', 'AMENDED')", name="ck_nl_annual_status"),
        sa.UniqueConstraint("organization_id", "employee_id", "tax_year", "version", name="uq_nl_annual_org_emp_year_ver"),
    )
    op.create_index("ix_nl_annual_org_year", "payroll_nl_annual_statements", ["organization_id", "tax_year"])

    # payroll_nl_payment_batches — SEPA payment batch (pain.001)
    op.create_table(
        "payroll_nl_payment_batches",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("payroll_run_id", sa.Integer, sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("pain001_sha256", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("message_id", sa.String(100), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="SUBMITTED"),  # SUBMITTED / ACCEPTED / SETTLED / REJECTED / RETURNED / UNKNOWN
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('SUBMITTED', 'ACCEPTED', 'SETTLED', 'REJECTED', 'RETURNED', 'UNKNOWN')", name="ck_nl_payment_batch_status"),
    )
    op.create_index("ix_nl_payment_batch_org_run", "payroll_nl_payment_batches", ["organization_id", "payroll_run_id"])

    # payroll_nl_payment_items — Individual payment items in a batch
    op.create_table(
        "payroll_nl_payment_items",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("payroll_nl_payment_batches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("iban_token", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("end_to_end_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="PENDING"),  # PENDING / SENT / SETTLED / RETURNED / REJECTED
        sa.Column("return_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'SENT', 'SETTLED', 'RETURNED', 'REJECTED')", name="ck_nl_payment_item_status"),
    )
    op.create_index("ix_nl_payment_item_batch_emp", "payroll_nl_payment_items", ["batch_id", "employee_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_nl_payment_item_batch_emp", table_name="payroll_nl_payment_items")
    op.drop_table("payroll_nl_payment_items")

    op.drop_index("ix_nl_payment_batch_org_run", table_name="payroll_nl_payment_batches")
    op.drop_table("payroll_nl_payment_batches")

    op.drop_constraint("uq_nl_annual_org_emp_year_ver", "payroll_nl_annual_statements", type_="unique")
    op.drop_index("ix_nl_annual_org_year", table_name="payroll_nl_annual_statements")
    op.drop_table("payroll_nl_annual_statements")
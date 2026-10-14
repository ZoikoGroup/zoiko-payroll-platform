"""nl_loonaangifte_sbr_digipoort_payment_m8

Revision ID: 3b4e5c6d7e8f
Revises: 8b14824fb575
Create Date: 2026-10-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3b4e5c6d7e8f'
down_revision: Union[str, Sequence[str], None] = '8b14824fb575'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # payroll_nl_loonaangifte_returns — Loonaangifte return header
    op.create_table(
        "payroll_nl_loonaangifte_returns",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employer_profile_id", sa.Integer, sa.ForeignKey("payroll_nl_employer_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("loonheffingennummer", sa.String(20), nullable=False, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("period_code", sa.String(10), nullable=False),  # e.g., 202601, 202602, 2026Q1
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("payment_due_date", sa.Date, nullable=False),
        sa.Column("version", sa.SmallInteger, nullable=False, default=1),
        sa.Column("return_type", sa.String(20), nullable=False, default="REGULAR"),  # REGULAR / NIL / ZERO / RESEND / CORRECTION
        sa.Column("correction_of_id", sa.Integer, sa.ForeignKey("payroll_nl_loonaangifte_returns.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, default="OPEN"),  # OPEN / READY / FILED / ACCEPTED / CORRECTED / REJECTED
        sa.Column("total_wage_tax", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_awf", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_aof", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_whk", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_wko", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_zvw_employer", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_zvw_employee", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_final_levies", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("total_payable", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("spec_version", sa.String(20), nullable=False, default="2026.1"),
        sa.Column("payload_xml", sa.Text, nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=True),
        sa.Column("journal_reconciled", sa.Boolean, nullable=False, default=False),
        sa.Column("reconciliation_report", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("statutory_filing_id", sa.Integer, nullable=True, index=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.CheckConstraint("return_type IN ('REGULAR', 'NIL', 'ZERO', 'RESEND', 'CORRECTION')", name="ck_nl_loonaangifte_return_type"),
        sa.CheckConstraint("status IN ('OPEN', 'READY', 'FILED', 'ACCEPTED', 'CORRECTED', 'REJECTED')", name="ck_nl_loonaangifte_status"),
    )
    op.create_index("ix_nl_loonaangifte_org_year_period", "payroll_nl_loonaangifte_returns", ["organization_id", "tax_year", "period_code"])
    op.create_index("ix_nl_loonaangifte_emp_profile_period", "payroll_nl_loonaangifte_returns", ["employer_profile_id", "tax_year", "period_code"])

    # payroll_nl_loonaangifte_lines — employee-level line items
    op.create_table(
        "payroll_nl_loonaangifte_lines",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("return_id", sa.Integer, sa.ForeignKey("payroll_nl_loonaangifte_returns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("income_relationship_id", sa.Integer, sa.ForeignKey("payroll_nl_income_relationships.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("personnel_number", sa.String(50), nullable=False),
        sa.Column("line_type", sa.String(20), nullable=False, default="ORIGINAL"),  # ORIGINAL / CORRECTION
        sa.Column("correction_of_line_id", sa.Integer, sa.ForeignKey("payroll_nl_loonaangifte_lines.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("wage_lb_phf", sa.Numeric(14, 2), nullable=False, default=0),  # loonbelasting/premievolksverzekeringen
        sa.Column("wage_sv", sa.Numeric(14, 2), nullable=False, default=0),      # socialeverzekeringen (AWf, Aof, Whk, Wko)
        sa.Column("wage_zvw", sa.Numeric(14, 2), nullable=False, default=0),      # ZVW
        sa.Column("hours", sa.Numeric(7, 2), nullable=False, default=0),
        sa.Column("contract_flags", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),  # {"is_director": true, "is_fixed_term": false, ...}
        sa.Column("awf_class", sa.String(10), nullable=True),  # LOW / HIGH
        sa.Column("premium_amounts", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),  # {"awf": 137.00, "aof": 313.50, "whk": 100.00, "wko": 25.00, "zvw_employer": 305.00, "zvw_employee": 242.50}
        sa.Column("wage_tax", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("zvw", sa.Numeric(14, 2), nullable=False, default=0),
        sa.Column("official_codes", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),  # Belastingdienst field codes per Gegevensspecificaties
        sa.Column("line_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("line_type IN ('ORIGINAL', 'CORRECTION')", name="ck_nl_loonaangifte_line_type"),
    )
    op.create_index("ix_nl_loonaangifte_lines_return_emp", "payroll_nl_loonaangifte_lines", ["return_id", "employee_id"])

    # payroll_nl_digipoort_submissions — Digipoort transport tracking (NL-038, NL-052)
    op.create_table(
        "payroll_nl_digipoort_submissions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("return_id", sa.Integer, sa.ForeignKey("payroll_nl_loonaangifte_returns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attempt_no", sa.SmallInteger, nullable=False, default=1),
        sa.Column("channel", sa.String(20), nullable=False, default="DIGIPOORT"),  # DIGIPOORT / SBR / VALIDATION_SERVICE
        sa.Column("cert_fingerprint", sa.String(64), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transport_status", sa.String(20), nullable=False, default="PREPARED"),  # PREPARED / SENT / ACK / REJECTED / UNKNOWN
        sa.Column("digipoort_reference", sa.String(100), nullable=True),
        sa.Column("ack_payload", sa.Text, nullable=True),
        sa.Column("error_codes", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("transport_status IN ('PREPARED', 'SENT', 'ACK', 'REJECTED', 'UNKNOWN')", name="ck_nl_digipoort_transport_status"),
        sa.CheckConstraint("channel IN ('DIGIPOORT', 'SBR', 'VALIDATION_SERVICE')", name="ck_nl_digipoort_channel"),
    )
    op.create_index("ix_nl_digipoort_return_attempt", "payroll_nl_digipoort_submissions", ["return_id", "attempt_no"])

    # payroll_nl_authority_payments — authority payment tracking (NL-038)
    op.create_table(
        "payroll_nl_authority_payments",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("return_id", sa.Integer, sa.ForeignKey("payroll_nl_loonaangifte_returns.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_reference", sa.String(100), nullable=False, index=True),
        sa.Column("bank_reference", sa.String(100), nullable=True),
        sa.Column("value_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="PREPARED"),  # PREPARED / RELEASED / SETTLED / FAILED / UNKNOWN
        sa.Column("settlement_evidence", sa.Text, nullable=True),
        sa.Column("prepared_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("released_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PREPARED', 'RELEASED', 'SETTLED', 'FAILED', 'UNKNOWN')", name="ck_nl_auth_payment_status"),
    )
    op.create_index("ix_nl_auth_payment_org_return", "payroll_nl_authority_payments", ["organization_id", "return_id"])


def downgrade() -> None:
    """Downgrade schema (children before the tables they reference)."""
    op.drop_index("ix_nl_auth_payment_org_return", table_name="payroll_nl_authority_payments")
    op.drop_table("payroll_nl_authority_payments")

    op.drop_index("ix_nl_digipoort_return_attempt", table_name="payroll_nl_digipoort_submissions")
    op.drop_table("payroll_nl_digipoort_submissions")

    op.drop_index("ix_nl_loonaangifte_lines_return_emp", table_name="payroll_nl_loonaangifte_lines")
    op.drop_table("payroll_nl_loonaangifte_lines")

    op.drop_index("ix_nl_loonaangifte_emp_profile_period", table_name="payroll_nl_loonaangifte_returns")
    op.drop_index("ix_nl_loonaangifte_org_year_period", table_name="payroll_nl_loonaangifte_returns")
    op.drop_table("payroll_nl_loonaangifte_returns")
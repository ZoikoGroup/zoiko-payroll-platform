"""NL wage tax tables M1

Revision ID: 43662178315b
Revises: c7d3e8f1a2b4
Create Date: 2026-10-12 16:14:51.731461

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '43662178315b'
down_revision: Union[str, Sequence[str], None] = 'c7d3e8f1a2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create payroll_nl_tax_table_files and payroll_nl_tax_table_rows tables."""
    op.create_table(
        "payroll_nl_tax_table_files",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("jurisdiction_pack_id", sa.Integer, sa.ForeignKey("payroll_jurisdiction_packs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tax_year", sa.SmallInteger, nullable=False, index=True),
        sa.Column("table_color", sa.String(10), nullable=False),  # WHITE / GREEN
        sa.Column("table_kind", sa.String(30), nullable=False),   # PERIOD / SPECIAL_REMUNERATION
        sa.Column("period", sa.String(20), nullable=True),         # DAY, WEEK, FOUR_WEEK, MONTH, QUARTER, YEAR (NULL for special-remuneration)
        sa.Column("residence_variant", sa.String(20), nullable=False),  # NL or derivation code
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("row_count", sa.Integer, nullable=False, default=0),
        sa.Column("status", sa.String(20), nullable=False, default="IMPORTED"),  # IMPORTED/VALIDATED/APPROVED/ACTIVE/SUPERSEDED/REJECTED
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("imported_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("validated_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activated_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("superseded_by_id", sa.Integer, sa.ForeignKey("payroll_nl_tax_table_files.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("table_color IN ('WHITE', 'GREEN')", name="ck_nl_tax_table_color"),
        sa.CheckConstraint("table_kind IN ('PERIOD', 'SPECIAL_REMUNERATION')", name="ck_nl_tax_table_kind"),
        sa.CheckConstraint("period IN ('DAY', 'WEEK', 'FOUR_WEEK', 'MONTH', 'QUARTER', 'YEAR')", name="ck_nl_tax_table_period"),
        sa.CheckConstraint("status IN ('IMPORTED', 'VALIDATED', 'APPROVED', 'ACTIVE', 'SUPERSEDED', 'REJECTED')", name="ck_nl_tax_table_status"),
    )
    op.create_index("ix_nl_tax_table_files_pack_color_kind_period_residence", "payroll_nl_tax_table_files",
                    ["jurisdiction_pack_id", "table_color", "table_kind", "period", "residence_variant"])
    op.create_index("ix_nl_tax_table_files_active_lookup", "payroll_nl_tax_table_files",
                    ["tax_year", "table_color", "table_kind", "period", "residence_variant", "status"],
                    postgresql_where=sa.text("status = 'ACTIVE'"))

    op.create_table(
        "payroll_nl_tax_table_rows",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("file_id", sa.Integer, sa.ForeignKey("payroll_nl_tax_table_files.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("row_no", sa.Integer, nullable=False),
        sa.Column("wage_from", sa.Numeric(12, 2), nullable=False),
        sa.Column("wage_to", sa.Numeric(12, 2), nullable=True),  # NULL = open-ended top bracket
        sa.Column("aow_cohort", sa.String(20), nullable=False),  # BELOW_AOW / AOW_AGE
        sa.Column("with_tax_credit", sa.Boolean, nullable=False, default=True),
        sa.Column("withholding_amount", sa.Numeric(12, 2), nullable=True),  # for PERIOD tables
        sa.Column("percentage", sa.Numeric(7, 4), nullable=True),  # for SPECIAL_REMUNERATION table
        sa.Column("row_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("aow_cohort IN ('BELOW_AOW', 'AOW_AGE')", name="ck_nl_tax_row_aow_cohort"),
    )
    op.create_index("ix_nl_tax_table_rows_file_wage", "payroll_nl_tax_table_rows", ["file_id", "wage_from", "wage_to"])
    op.create_unique_constraint("uq_nl_tax_table_rows_file_row", "payroll_nl_tax_table_rows", ["file_id", "row_no"])


def downgrade() -> None:
    """Drop payroll_nl_tax_table_rows and payroll_nl_tax_table_files tables."""
    op.drop_constraint("uq_nl_tax_table_rows_file_row", "payroll_nl_tax_table_rows", type_="unique")
    op.drop_index("ix_nl_tax_table_rows_file_wage", table_name="payroll_nl_tax_table_rows")
    op.drop_table("payroll_nl_tax_table_rows")
    op.drop_index("ix_nl_tax_table_files_active_lookup", table_name="payroll_nl_tax_table_files")
    op.drop_index("ix_nl_tax_table_files_pack_color_kind_period_residence", table_name="payroll_nl_tax_table_files")
    op.drop_table("payroll_nl_tax_table_files")
"""add payroll_ytd_accumulators table (never migrated); widen tax_year columns

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-09-09 00:00:00.000000

`payroll_ytd_accumulators` (PayrollYtdAccumulator in models.py) has existed
in the ORM since the Canada CPP/CPP2/EI YTD-accumulator work, but no
migration ever created it — confirmed by walking every migration in this
history and finding zero references to the table name. It has only ever
been created in tests (which build schema straight from Base.metadata,
bypassing Alembic entirely) and would not exist on any real deployed
database. This was harmless while `_YTD_ACCUMULATOR_ENABLED_COUNTRIES`
(engine/countries/shared.py) was empty for every country, but the UK
2026-27 gap-closure Phase 3 (2026-09-09) added "UK" to that set — the very
next real UK director payslip would raise "relation
payroll_ytd_accumulators does not exist".

Also widens both this table's and organization_ytd_accumulators' existing
`tax_year` column from VARCHAR(10) to VARCHAR(20): "US-CY-2026"/
"CA-CY-2026" fit 10 chars, but service.py's `_uk_tax_year()` produces
"UK-TY-2026-27" (13 chars) — inserting that into a VARCHAR(10) column
raises a hard Postgres "value too long for type character varying(10)"
error, another crash the same Phase 3 switch would have caused on its
first real write to organization_ytd_accumulators (that table DOES exist
in production via e5f6a7b8c9d0, so this half of the bug was reachable on
a real database, not just a dormant-table issue).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_ytd_accumulators',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
        sa.Column('tax_year', sa.String(length=20), nullable=False),
        sa.Column('tax_component', sa.String(length=30), nullable=False),
        sa.Column('ytd_taxable_wages', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('ytd_tax_withheld', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('last_updated_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('employee_id', 'tax_year', 'tax_component', name='uq_ytd_accumulator_employee_year_component'),
    )
    op.alter_column(
        'organization_ytd_accumulators', 'tax_year',
        existing_type=sa.String(length=10), type_=sa.String(length=20), existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'organization_ytd_accumulators', 'tax_year',
        existing_type=sa.String(length=20), type_=sa.String(length=10), existing_nullable=False,
    )
    op.drop_table('payroll_ytd_accumulators')

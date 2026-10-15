"""hk contractual overtime: profile overtime rate + verified overtime hours (gap audit D-A)

Revision ID: e3a9c1f7b2d4
Revises: d1e5a7c3b9f2
Create Date: 2026-10-14

Additive only: two nullable columns, no default, no backfill (catalog-only on
PostgreSQL 11+; no table rewrite, no scan).
"""

import sqlalchemy as sa
from alembic import op

revision = "e3a9c1f7b2d4"
down_revision = "d1e5a7c3b9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_employee_statutory_profiles",
                  sa.Column("hk_contractual_overtime_hourly_rate", sa.Numeric(10, 2), nullable=True))
    op.add_column("payroll_hk_work_hours", sa.Column("overtime_hours", sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("payroll_hk_work_hours") as b:
        b.drop_column("overtime_hours")
    with op.batch_alter_table("payroll_employee_statutory_profiles") as b:
        b.drop_column("hk_contractual_overtime_hourly_rate")

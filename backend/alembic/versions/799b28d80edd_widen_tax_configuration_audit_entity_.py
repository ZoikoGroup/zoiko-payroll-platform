"""widen tax configuration audit entity_type to 50

Revision ID: 799b28d80edd
Revises: 00a912d5306c
Create Date: 2026-09-18 12:06:18.525513

Schema drift found while publishing the real Germany 2026 registries:
TaxConfigurationAudit.entity_type is String(30), but several existing
Germany audit call sites in service.py already pass literals longer than
that — e.g. "germany_earning_taxability_rule" (31), "germany_minijob_
midijob_parameter" (33), "germany_overtime_premium_component" (34),
"germany_accident_insurance_profile" (34). These raised
StringDataRightTruncation the first time any of them actually ran a
status-change audit against Postgres (SQLite does not enforce VARCHAR
length by default, so this went uncaught in tests until now). Widened to
50 — comfortably above the current longest literal (34) with headroom for
future entity types, and purely additive (never truncates/rejects an
existing row).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '799b28d80edd'
down_revision: Union[str, Sequence[str], None] = '00a912d5306c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "payroll_tax_configuration_audit", "entity_type",
        existing_type=sa.String(length=30), type_=sa.String(length=50), existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "payroll_tax_configuration_audit", "entity_type",
        existing_type=sa.String(length=50), type_=sa.String(length=30), existing_nullable=False,
    )

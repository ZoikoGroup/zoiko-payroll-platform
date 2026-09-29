"""add payroll_employees.sgp_wp_sector / sgp_wp_skill_level / sgp_wp_levy_tier

Revision ID: a7c2e9f4b1d6
Revises: f6a1b4c8d3e5
Create Date: 2026-09-24

Singapore Work Permit levy (Phase 5 S1, approved in principle 2026-09-24).
MOM prices the Work Permit levy by the worker's sector, skill level
(Higher-skilled R1 / Basic-skilled R2) and levy tier — the quota tier
(services, manufacturing), the source category (construction, process) —
and MOM itself allocates the tier on the levy bill, so none of the three
is derivable from existing payroll data (the company-level `industry`
free text cannot carry a per-worker sector/account; `sgp_work_pass_type`
only says WORK_PERMIT). Engine-read facts are real columns (the resolver
never passes compliance_fields to the calculator), same convention as the
other sgp_* columns. Three nullable String columns, no index, no FK;
every existing row keeps NULL (a Work Permit levy without them BLOCKS, as
before). Idempotent (inspector-guarded), same shape as e5f9a3b7c2d4.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c2e9f4b1d6'
down_revision: Union[str, Sequence[str], None] = 'f6a1b4c8d3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# sgp_wp_levy_tier is 20 (Phase 6.0 F1): "MYS_NAS_PRC" is 11 characters and
# String(10) failed on PostgreSQL. Widened in place — this revision had not
# been committed or applied to any shared database.
_COLUMNS = (("sgp_wp_sector", 30), ("sgp_wp_skill_level", 10), ("sgp_wp_levy_tier", 20))


def _existing_columns() -> set:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns("payroll_employees")}


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_columns()
    for name, length in _COLUMNS:
        if name not in existing:
            op.add_column('payroll_employees', sa.Column(name, sa.String(length), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    existing = _existing_columns()
    for name, _length in reversed(_COLUMNS):
        if name in existing:
            op.drop_column('payroll_employees', name)

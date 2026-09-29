"""add singapore cpf employee columns

Revision ID: c3d9e1f4a7b2
Revises: 998877665544
Create Date: 2026-09-23

Singapore statutory build (ZP-SG-ENG-001), Phase 1 — the CPF cohort facts
engine/countries/singapore.py derives the CPF contribution table from
(payroll_employees.sgp_*). Additive and nullable only: no existing row or
column is touched, and every non-SG employee keeps NULL. Idempotent (skips
a column that already exists, e.g. on a dev DB synced via create_all),
same inspector-guarded shape as 0a0402792c76_add_ks_k4_dependents.
See models.PayrollEmployee's own comment on these columns.

Parent re-pointed (2026-09-29, R2) from a5f6e7d8c9b0 to 998877665544, the
head of origin/main: main's f0b1c2d3e4f5 DROPS these sgp_* columns, and as a
parallel branch from a5f6e7d8c9b0 it could run AFTER this revision and
silently remove them (rehearsed: 0/11 columns left). Parenting on main's
head makes the chain linear, so the Singapore columns are always added last.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9e1f4a7b2'
down_revision: Union[str, Sequence[str], None] = '998877665544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = (
    ("sgp_cpf_residency_status", sa.String(10)),
    ("sgp_spr_effective_date", sa.Date()),
    ("sgp_cpf_contribution_arrangement", sa.String(5)),
    ("sgp_work_pass_type", sa.String(20)),
    ("sgp_shg_funds", sa.String(50)),
)


def _existing_columns() -> set:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns("payroll_employees")}


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_columns()
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column('payroll_employees', sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    existing = _existing_columns()
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column('payroll_employees', name)

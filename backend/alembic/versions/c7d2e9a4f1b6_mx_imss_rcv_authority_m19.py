"""mx_imss_rcv_authority_m19: the IMSS retirement branches get their own authority liability (gap A18)

Revision ID: c7d2e9a4f1b6
Revises: b9f3d5a1c7e2
Create Date: 2026-10-27

Mexico completion programme, gap register A18: LSS Art. 39 (S10, PDF p. 14) makes the
IMSS quotas monthly, while LSS Transitorio VIGÉSIMO SÉPTIMO (S10, PDF p. 111) keeps
retiro, cesantía en edad avanzada y vejez (RCV) bimonthly. One IMSS liability per
registration and month could not be dated by either rule, so the RCV branches move to
their own authority, IMSS_RCV. This revision only widens the CHECK constraint
ck_mx_liability_authority on payroll_mx_authority_liabilities to admit 'IMSS_RCV'.
No table or column is created; no RLS policy changes (the policy names no column).

Merging to main runs this in production. DROP / ADD CONSTRAINT takes a brief ACCESS
EXCLUSIVE lock on payroll_mx_authority_liabilities only (a Mexico table, empty in
production: Mexico is dormant), held until the upgrade transaction commits — so the
revision runs under SET LOCAL lock_timeout = '5s'. The new constraint is added NOT
VALID and then VALIDATEd (no row can violate it: it only widens the set).
Guarded and idempotent. Downgrade refuses while any IMSS_RCV liability exists.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d2e9a4f1b6"
down_revision: Union[str, Sequence[str], None] = "b9f3d5a1c7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_mx_authority_liabilities"
CONSTRAINT = "ck_mx_liability_authority"
OLD = "authority IN ('SAT_ISR', 'IMSS', 'INFONAVIT', 'ISN')"
NEW = "authority IN ('SAT_ISR', 'IMSS', 'IMSS_RCV', 'INFONAVIT', 'ISN')"
NEW_COLUMNS = ()


def _definition():
    """The constraint's SQL text as the database holds it, or None."""
    insp = sa.inspect(op.get_bind())
    if TABLE not in insp.get_table_names():
        return None
    for c in insp.get_check_constraints(TABLE):
        if c.get("name") == CONSTRAINT:
            return c.get("sqltext") or ""
    return None


def _swap(condition: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
        op.execute(sa.text(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({condition}) NOT VALID"))
        op.execute(sa.text(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CONSTRAINT}"))
        return
    with op.batch_alter_table(TABLE, recreate="always") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, condition)


def upgrade() -> None:
    definition = _definition()
    if definition is None or "IMSS_RCV" in definition:
        return                                                     # no table yet, or already widened
    _swap(NEW)


def downgrade() -> None:
    definition = _definition()
    if definition is None or "IMSS_RCV" not in definition:
        return
    count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE} WHERE authority = 'IMSS_RCV'")).scalar()
    if count:
        raise RuntimeError(f"{count} IMSS_RCV liabilities exist — move or withdraw them before downgrading")
    _swap(OLD)

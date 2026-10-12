"""add organization commercial ledger fields

Revision ID: b7e1f4a9c3d2
Revises: a3f5c9d1b2e4
Create Date: 2026-09-18 00:00:00.000000

Commercial Billing & Subscription Operating Standard §A1/§A2 (blockers
#12, #13). Adds billing_classification, charge_enabled,
commercial_account_id, service_commencement_at, commercial_route to
Organization.

Blocker #13 is explicit: existing orgs must NOT be defaulted to
chargeable. Every pre-existing row is backfilled to
billing_classification="NON_CHARGEABLE", charge_enabled=False — a human
must explicitly review and flip real customers to COMMERCIAL_ACTIVE.
Purely additive: new columns only, nothing altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e1f4a9c3d2'
down_revision: Union[str, Sequence[str], None] = 'a3f5c9d1b2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("organizations")}

    if "billing_classification" not in existing_columns:
        op.add_column(
            "organizations",
            sa.Column("billing_classification", sa.String(length=30), nullable=False, server_default="NON_CHARGEABLE"),
        )
    if "charge_enabled" not in existing_columns:
        op.add_column(
            "organizations",
            sa.Column("charge_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "commercial_account_id" not in existing_columns:
        op.add_column("organizations", sa.Column("commercial_account_id", sa.String(length=50), nullable=True))
        op.create_index(op.f("ix_organizations_commercial_account_id"), "organizations", ["commercial_account_id"], unique=True)
    if "service_commencement_at" not in existing_columns:
        op.add_column("organizations", sa.Column("service_commencement_at", sa.DateTime(), nullable=True))
    if "commercial_route" not in existing_columns:
        op.add_column("organizations", sa.Column("commercial_route", sa.String(length=30), nullable=True))

    # Explicit backfill (blocker #13) — belt-and-suspenders alongside the
    # server_default above, so this reads as a deliberate data decision,
    # not an implicit side effect of adding a column with a default.
    op.execute(
        "UPDATE organizations SET billing_classification = 'NON_CHARGEABLE' "
        "WHERE billing_classification IS NULL"
    )
    op.execute(
        "UPDATE organizations SET charge_enabled = false "
        "WHERE charge_enabled IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("organizations")}

    if "commercial_account_id" in existing_columns:
        op.drop_index(op.f("ix_organizations_commercial_account_id"), table_name="organizations")
    for col in ("commercial_route", "service_commencement_at", "commercial_account_id", "charge_enabled", "billing_classification"):
        if col in existing_columns:
            op.drop_column("organizations", col)

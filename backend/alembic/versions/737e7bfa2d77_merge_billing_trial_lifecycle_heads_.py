"""merge billing trial lifecycle heads (catch-up: grace_period_ends_at)

Revision ID: 737e7bfa2d77
Revises: 493a6e23cea1, c1f5a9d22e10
Create Date: 2026-09-16 09:52:52.677648

Joins the billing trial-lifecycle branch (organizations.workspace_type ->
billing tables -> billing_subscriptions.grace_period_ends_at) back onto the
main migration spine. Both ancestors are replayed normally; this revision's
upgrade() is a defensive catch-up so an environment that was bootstrapped via
Base.metadata.create_all (app/database.py imports billing models and
workspace_type now) still ends up with grace_period_ends_at present even if
the c1f5a9d22e10 ancestor was skipped or stamped rather than run. The column
(and its index) are created only when missing, so the merge is a no-op on any
database that already applied the sibling branch.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '737e7bfa2d77'
down_revision: Union[str, Sequence[str], None] = ('493a6e23cea1', 'c1f5a9d22e10')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: ensure billing_subscriptions.grace_period_ends_at exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'billing_subscriptions' not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("billing_subscriptions")}
    if "grace_period_ends_at" not in existing_columns:
        op.add_column(
            "billing_subscriptions",
            sa.Column("grace_period_ends_at", sa.DateTime(), nullable=True),
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("billing_subscriptions")}
    if "ix_billing_subscriptions_grace_period_ends_at" not in existing_indexes:
        op.create_index(
            op.f("ix_billing_subscriptions_grace_period_ends_at"),
            "billing_subscriptions",
            ["grace_period_ends_at"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema: drop the catch-up column/index only."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'billing_subscriptions' not in inspector.get_table_names():
        return

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("billing_subscriptions")}
    if "ix_billing_subscriptions_grace_period_ends_at" in existing_indexes:
        op.drop_index(op.f("ix_billing_subscriptions_grace_period_ends_at"), table_name="billing_subscriptions")

    existing_columns = {col["name"] for col in inspector.get_columns("billing_subscriptions")}
    if "grace_period_ends_at" in existing_columns:
        op.drop_column("billing_subscriptions", "grace_period_ends_at")

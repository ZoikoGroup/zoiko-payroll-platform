"""add billing_subscriptions.grace_period_ends_at column

Revision ID: c1f5a9d22e10
Revises: 76e050fd5ffd
Create Date: 2026-09-15 00:00:00.000000

Prompt 5 — day-30 expiry sweep. The trial lifecycle derives its state from
BillingSubscription rows instead of new Organization columns:

  - "ACTIVE"          status == TRIALING and current_period_end in the future
  - "GRACE_READONLY"  status == TRIALING and current_period_end in the past but
                      within grace_period_ends_at (grace window)
  - "CLOSED"          past grace_period_ends_at → Organization.is_active=False

grace_period_ends_at is set the FIRST time the sweep observes an expired
trial (current_period_end + timedelta(days=TRIAL_GRACE_DAYS)), so it starts
NULL. Purely additive: one nullable indexed column, nothing altered/dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1f5a9d22e10'
down_revision: Union[str, Sequence[str], None] = '76e050fd5ffd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add the nullable grace_period_ends_at column."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("billing_subscriptions")}

    if "grace_period_ends_at" not in existing_columns:
        op.add_column(
            "billing_subscriptions",
            sa.Column("grace_period_ends_at", sa.DateTime(), nullable=True),
        )
    op.create_index(
        op.f("ix_billing_subscriptions_grace_period_ends_at"),
        "billing_subscriptions",
        ["grace_period_ends_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema: drop the column (and its index)."""
    op.drop_index(op.f("ix_billing_subscriptions_grace_period_ends_at"), table_name="billing_subscriptions")
    op.drop_column("billing_subscriptions", "grace_period_ends_at")
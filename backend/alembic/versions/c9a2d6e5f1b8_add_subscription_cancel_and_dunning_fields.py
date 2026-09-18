"""add billing_subscriptions cancel_requested_at

Revision ID: c9a2d6e5f1b8
Revises: b7e1f4a9c3d2
Create Date: 2026-09-18 00:00:01.000000

Commercial Billing & Subscription Operating Standard Part 8 (blocker #10).
Adds cancel_requested_at to billing_subscriptions. Purely additive.

Dunning state (blocker #17) deliberately does NOT get new columns here —
this codebase already has a dedicated billing_dunning_state table
(BillingDunningState, one row per org) and a DunningStage enum
(RETRY/RESTRICT_EXPANSION/RESTRICT_NEW_RUN/READ_ONLY), both pre-existing
and previously unused. Part 9's dunning.py builds on that table directly
instead of duplicating it as parallel columns on BillingSubscription.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9a2d6e5f1b8'
down_revision: Union[str, Sequence[str], None] = 'b7e1f4a9c3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("billing_subscriptions")}

    if "cancel_requested_at" not in existing_columns:
        op.add_column("billing_subscriptions", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("billing_subscriptions")}
    if "cancel_requested_at" in existing_columns:
        op.drop_column("billing_subscriptions", "cancel_requested_at")

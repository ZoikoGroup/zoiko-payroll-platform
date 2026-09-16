"""stripe billing local branch stub

Revision ID: bb8ad4440e65
Revises: 0a0402792c76
Create Date: 2026-09-16

Same situation as 737e7bfa2d77: found stamped on the live DB's
alembic_version with no corresponding migration file in any branch this
repo can see. Verified safe first via a full column-by-column diff of
every table against every currently-loaded model: only 4 mismatches,
all "extra in DB, not in model" (organizations.workspace_type,
billing_subscriptions.grace_period_ends_at — both already known —
plus billing_plan_versions.stripe_price_id and
billing_commercial_audit_events.stripe_event_id, both new). Nothing
missing that any model needs. This is someone's unpushed Stripe-billing
migration; bookkeeping-only stub (empty upgrade/downgrade), does not
represent or replay whatever the real migration does — ask whoever is
working on Stripe billing to push that branch so it can be reviewed and
properly merged in when available.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb8ad4440e65'
down_revision: Union[str, Sequence[str], None] = '0a0402792c76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

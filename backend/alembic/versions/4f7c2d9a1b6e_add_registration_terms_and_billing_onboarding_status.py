"""add registration terms and billing onboarding state

Revision ID: 4f7c2d9a1b6e
Revises: 259146357852
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f7c2d9a1b6e"
down_revision: Union[str, Sequence[str], None] = "259146357852"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("organizations")}

    if "billing_onboarding_status" not in columns:
        op.add_column(
            "organizations",
            sa.Column(
                "billing_onboarding_status",
                sa.String(length=30),
                nullable=False,
                server_default="PENDING_CHECKOUT",
            ),
        )

    if "terms_accepted_at" not in columns:
        op.add_column("organizations", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("organizations")}

    if "terms_accepted_at" in columns:
        op.drop_column("organizations", "terms_accepted_at")
    if "billing_onboarding_status" in columns:
        op.drop_column("organizations", "billing_onboarding_status")

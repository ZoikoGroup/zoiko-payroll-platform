"""add google_pending table for Google sign-up flow

Revision ID: 7a3c9e1f2b4d_google_pending_table
Revises: 9f1e2d3c4b5a_google_oauth_user_columns
Create Date: 2026-11-04

Holds a Google profile under a single-use, short-lived token between the
OAuth callback and the registration page, so a new Google user finishes org
signup instead of being auto-created.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7a3c9e1f2b4d_google_pending_table"
down_revision: Union[str, Sequence[str], None] = "9f1e2d3c4b5a_google_oauth_user_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "google_pending" not in tables:
        op.create_table(
            "google_pending",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("token", sa.String(length=64), nullable=False, unique=True, index=True),
            sa.Column("email", sa.String(length=200), nullable=False, index=True),
            sa.Column("google_id", sa.String(length=255), nullable=False),
            sa.Column("given_name", sa.String(length=120), nullable=True),
            sa.Column("family_name", sa.String(length=120), nullable=True),
            sa.Column("picture", sa.String(length=500), nullable=True),
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="register"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "google_pending" in tables:
        op.drop_table("google_pending")

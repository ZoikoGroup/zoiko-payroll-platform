"""add google_oauth columns to users

Revision ID: 9f1e2d3c4b5a
Revises: b8bd939fffca
Create Date: 2026-11-04

Add sign-in-provider tracking and Google OAuth identity columns to the
users table so users can sign in with Google instead of (or in addition to)
email/password.

  auth_provider    "email" (default) or "google"
  google_id        Google subject identifier, unique when set
  avatar_url       profile picture URL from Google
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f1e2d3c4b5a"
down_revision: Union[str, Sequence[str], None] = "b8bd939fffca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_columns():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    columns = _user_columns()

    if "auth_provider" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "auth_provider",
                sa.String(length=20),
                nullable=False,
                server_default="email",
            ),
        )
    if "google_id" not in columns:
        op.add_column(
            "users",
            sa.Column("google_id", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)
    if "avatar_url" not in columns:
        op.add_column(
            "users",
            sa.Column("avatar_url", sa.String(length=500), nullable=True),
        )


def downgrade() -> None:
    columns = _user_columns()

    if "avatar_url" in columns:
        op.drop_column("users", "avatar_url")
    if "google_id" in columns:
        op.drop_index("ix_users_google_id", table_name="users")
        op.drop_column("users", "google_id")
    if "auth_provider" in columns:
        op.drop_column("users", "auth_provider")

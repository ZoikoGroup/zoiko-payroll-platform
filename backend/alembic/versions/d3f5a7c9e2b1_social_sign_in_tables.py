"""add Microsoft / Apple sign-in and Company SSO domain tables

Revision ID: d3f5a7c9e2b1
Revises: c8d2f6a4e1b9
Create Date: 2026-11-27

* user_oauth_identities — Microsoft / Apple identities linked to a user
  (Google keeps users.google_id).
* oauth_pending — single-use hold for a new Microsoft / Apple profile between
  the provider callback and the registration page (like google_pending).
* organization_sso_domains — email domains whose users sign in through their
  organization's own identity provider ("Continue with Company SSO").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d3f5a7c9e2b1"
down_revision: Union[str, Sequence[str], None] = "c8d2f6a4e1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()

    if "user_oauth_identities" not in tables:
        op.create_table(
            "user_oauth_identities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("provider_email", sa.String(200), nullable=True),
            sa.Column("is_private_relay", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "subject", name="uq_user_oauth_identity_provider_subject"),
        )
        op.create_index("ix_user_oauth_identities_id", "user_oauth_identities", ["id"])
        op.create_index("ix_user_oauth_identities_user_id", "user_oauth_identities", ["user_id"])

    if "oauth_pending" not in tables:
        op.create_table(
            "oauth_pending",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("email", sa.String(200), nullable=False),
            sa.Column("given_name", sa.String(120), nullable=True),
            sa.Column("family_name", sa.String(120), nullable=True),
            sa.Column("is_private_relay", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("mode", sa.String(20), nullable=False, server_default="register"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_oauth_pending_id", "oauth_pending", ["id"])
        op.create_index("ix_oauth_pending_token", "oauth_pending", ["token"], unique=True)
        op.create_index("ix_oauth_pending_email", "oauth_pending", ["email"])

    if "organization_sso_domains" not in tables:
        op.create_table(
            "organization_sso_domains",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("domain", sa.String(253), nullable=False),
            sa.Column("login_url", sa.String(500), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_organization_sso_domains_id", "organization_sso_domains", ["id"])
        op.create_index("ix_organization_sso_domains_organization_id", "organization_sso_domains", ["organization_id"])
        op.create_index("ix_organization_sso_domains_domain", "organization_sso_domains", ["domain"], unique=True)


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    for table in ("organization_sso_domains", "oauth_pending", "user_oauth_identities"):
        if table in tables:
            op.drop_table(table)

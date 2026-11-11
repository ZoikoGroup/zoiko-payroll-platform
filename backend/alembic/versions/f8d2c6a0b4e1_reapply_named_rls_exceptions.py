"""Reapply named RLS exceptions after country-entitlement migrations.

Revision ID: f8d2c6a0b4e1
Revises: d4c8f1a7b2e9
Create Date: 2026-10-29

The immutable organization-jurisdictions migration reruns the generic RLS
installer. Reinstall the named exceptions after both migration heads merge so
that tenant release policies retain their reviewed predicates.
"""

from alembic import op


revision = "f8d2c6a0b4e1"
down_revision = "d4c8f1a7b2e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.authz.rls_exceptions import reapply_named_exceptions

    reapply_named_exceptions(op.get_bind())


def downgrade() -> None:
    # The reapplication restores the intended security policy and has no
    # independent downgrade state to reverse.
    pass

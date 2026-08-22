"""Add supersession + idempotency columns to security_action_tokens.

§04 (Event/State/Audit Model): a new password-reset (or invite) request must
supersede any prior still-valid token for the same recipient, and every send
carries an idempotency key composed from tenant + event + recipient +
template + material version.

Revision ID: 3e8a1c47d5f2
Revises: dde9b427b6bf
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3e8a1c47d5f2"
down_revision = "dde9b427b6bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_action_tokens",
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "security_action_tokens",
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
    )
    op.create_index(
        op.f("ix_security_action_tokens_idempotency_key"),
        "security_action_tokens",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_security_action_tokens_idempotency_key"),
        table_name="security_action_tokens",
    )
    op.drop_column("security_action_tokens", "idempotency_key")
    op.drop_column("security_action_tokens", "superseded_at")

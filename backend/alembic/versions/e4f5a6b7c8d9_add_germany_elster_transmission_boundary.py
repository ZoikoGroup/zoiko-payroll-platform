"""add germany elster transmission boundary tables

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-09 00:00:00.000000

Phase 8BF — engineering scaffold for the ELSTER transmission boundary (see
engine/germany_elster.py's own module docstring). Purely additive: two new
tables, no existing column/table altered or dropped, both start empty in
every environment.

1. payroll_germany_elster_certificate_configs — per-organization record of
   whether a real ELSTER certificate REFERENCE has been configured. Never
   holds certificate/key material itself (certificate_reference is an
   external key-vault pointer, not a secret) — see the model's own
   docstring for why this is a deliberate security-boundary design choice,
   not an oversight.

2. payroll_germany_elster_transmissions — one attempt to prepare/transmit
   an ELSTER-shaped filing. The status vocabulary includes states
   (TRANSMITTED/ACKNOWLEDGED/REJECTED/QUEUED) that no code path in this
   phase ever sets — only DRAFT/VALIDATED/BLOCKED_EXTERNAL are reachable
   today, since resolve_elster_transmitter() unconditionally returns a
   fail-closed transmitter (no real ELSTER connector is implemented or
   authorized).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payroll_germany_elster_certificate_configs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, unique=True, index=True),
        sa.Column('is_configured', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('certificate_reference', sa.String(200), nullable=True),
        sa.Column('reference_description', sa.Text(), nullable=True),
        sa.Column('configured_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('configured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'payroll_germany_elster_transmissions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('transmission_type', sa.String(50), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('payload_summary', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('validation_errors', sa.JSON(), nullable=True),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_germany_elster_transmission_org_period', 'payroll_germany_elster_transmissions',
        ['organization_id', 'period_start'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_germany_elster_transmission_org_period', table_name='payroll_germany_elster_transmissions')
    op.drop_table('payroll_germany_elster_transmissions')
    op.drop_table('payroll_germany_elster_certificate_configs')

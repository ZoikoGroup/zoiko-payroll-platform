"""ch versioned entity profile and idempotency records

Revision ID: 376bb8637603
Revises: 3baddbaa011a
Create Date: 2026-10-06 00:00:00.000000

CH Step 5 (employer schemes / entity profile / earning classification).

1. payroll_ch_entity_profiles becomes VERSIONED. 3baddbaa011a declared
   organization_id UNIQUE, which contradicts that table's own contract ("a
   revised profile is a NEW effective-dated row chained by
   previous_version_id"). The single-column unique index is replaced by a
   plain index plus UNIQUE (organization_id, effective_from); the service keeps
   versions non-overlapping, so exactly one profile still governs any date.

2. payroll_ch_idempotency_records — Idempotency-Key replay store for CH write
   routes (scope_key + idempotency_key UNIQUE).

Guarded like 3baddbaa011a: every step is skipped when its object is already in
the target shape. Chains directly off 3baddbaa011a (single head).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '376bb8637603'
down_revision: Union[str, Sequence[str], None] = '3baddbaa011a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENTITY_TABLE = 'payroll_ch_entity_profiles'
ORG_INDEX = 'ix_payroll_ch_entity_profiles_organization_id'
VERSION_INDEX = 'uq_ch_entity_profile_org_effective_from'


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table):
    return {i['name']: i for i in sa.inspect(op.get_bind()).get_indexes(table)} if _has_table(table) else {}


def _set_org_index(unique: bool):
    existing = _indexes(ENTITY_TABLE).get(ORG_INDEX)
    if existing is not None and bool(existing.get('unique')) == unique:
        return
    if existing is not None:
        op.drop_index(ORG_INDEX, table_name=ENTITY_TABLE)
    op.create_index(ORG_INDEX, ENTITY_TABLE, ['organization_id'], unique=unique)


def upgrade() -> None:
    if _has_table(ENTITY_TABLE):
        _set_org_index(unique=False)
        if VERSION_INDEX not in _indexes(ENTITY_TABLE):
            op.create_index(VERSION_INDEX, ENTITY_TABLE, ['organization_id', 'effective_from'], unique=True)

    if not _has_table('payroll_ch_idempotency_records'):
        op.create_table(
            'payroll_ch_idempotency_records',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('scope_key', sa.String(40), nullable=False),
            sa.Column('idempotency_key', sa.String(100), nullable=False),
            sa.Column('operation', sa.String(100), nullable=False),
            sa.Column('request_sha256', sa.String(64), nullable=False),
            sa.Column('response_body', sa.JSON(), nullable=True),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('correlation_id', sa.String(64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('scope_key', 'idempotency_key', name='uq_ch_idempotency_scope_key'),
        )


def downgrade() -> None:
    """Mirrors upgrade(). Restoring the one-per-organization unique index fails
    if an organization already has more than one profile version — by design:
    collapsing versions would destroy history, so that is a manual decision."""
    if _has_table('payroll_ch_idempotency_records'):
        op.drop_table('payroll_ch_idempotency_records')
    if _has_table(ENTITY_TABLE):
        if VERSION_INDEX in _indexes(ENTITY_TABLE):
            op.drop_index(VERSION_INDEX, table_name=ENTITY_TABLE)
        _set_org_index(unique=True)

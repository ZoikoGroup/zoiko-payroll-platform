"""create legal_entities table

Revision ID: a3f5c9d1b2e4
Revises: fbfe6d7eeb2e
Create Date: 2026-09-17 00:00:00.000000

Adds the `legal_entities` table (organizations/models.py's LegalEntity) —
the first-class concept billing's MAX_ENTITIES entitlement limit checks
against. Before this, there was no way to represent "how many legal
entities does this org have" anywhere in the schema. Purely additive: one
new table, nothing altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f5c9d1b2e4'
down_revision: Union[str, Sequence[str], None] = 'fbfe6d7eeb2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'legal_entities' not in existing_tables:
        op.create_table(
            'legal_entities',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('registration_number', sa.String(length=100), nullable=True),
            sa.Column('country', sa.String(length=100), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index(op.f('ix_legal_entities_id'), 'legal_entities', ['id'], unique=False)
        op.create_index(op.f('ix_legal_entities_organization_id'), 'legal_entities', ['organization_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'legal_entities' in set(inspector.get_table_names()):
        op.drop_index(op.f('ix_legal_entities_organization_id'), table_name='legal_entities')
        op.drop_index(op.f('ix_legal_entities_id'), table_name='legal_entities')
        op.drop_table('legal_entities')

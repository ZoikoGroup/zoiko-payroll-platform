"""create jurisdiction_service_registry and enterprise_order_forms tables

Revision ID: d4f8a2c7e6b1
Revises: c9a2d6e5f1b8
Create Date: 2026-09-18 00:00:02.000000

Commercial Billing & Subscription Operating Standard Parts 4/12
(blockers #5, #11, #12). Purely additive: two new tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f8a2c7e6b1'
down_revision: Union[str, Sequence[str], None] = 'c9a2d6e5f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'jurisdiction_service_registry' not in existing_tables:
        op.create_table(
            'jurisdiction_service_registry',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('country', sa.String(length=100), nullable=False, unique=True),
            sa.Column('availability', sa.String(length=30), nullable=False),
            sa.Column('payment_execution_responsibility', sa.String(length=30), nullable=True),
            sa.Column('filing_responsibility', sa.String(length=30), nullable=True),
            sa.Column('remittance_responsibility', sa.String(length=30), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index(op.f('ix_jurisdiction_service_registry_id'), 'jurisdiction_service_registry', ['id'], unique=False)

    if 'enterprise_order_forms' not in existing_tables:
        op.create_table(
            'enterprise_order_forms',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('contract_reference', sa.String(length=100), nullable=False),
            sa.Column('negotiated_scale_limits', sa.JSON(), nullable=False),
            sa.Column('negotiated_price_terms', sa.JSON(), nullable=False),
            sa.Column('term_start', sa.Date(), nullable=False),
            sa.Column('term_end', sa.Date(), nullable=True),
            sa.Column('signed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index(op.f('ix_enterprise_order_forms_id'), 'enterprise_order_forms', ['id'], unique=False)
        op.create_index(op.f('ix_enterprise_order_forms_organization_id'), 'enterprise_order_forms', ['organization_id'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'enterprise_order_forms' in existing_tables:
        op.drop_table('enterprise_order_forms')
    if 'jurisdiction_service_registry' in existing_tables:
        op.drop_table('jurisdiction_service_registry')

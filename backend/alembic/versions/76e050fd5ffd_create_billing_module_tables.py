"""create billing module tables

Revision ID: 76e050fd5ffd
Revises: 38263fcf0a1d
Create Date: 2026-09-15 00:00:00.000000

Prompt 2 — the Commercial Layer (billing) schema. The billing module was
merged (commit "billing module created") with models only and NO Alembic
migration, and the live database has zero billing tables: the module stayed
invisible to Alembic/create_all-on-startup because app/database.py never
imported app.modules.billing.models (only migrations/create_all/create_all.py
did). This revision closes that gap so register_trial can persist a
BillingSubscription + BillingCommercialAuditEvent next to the org row.

All table/column/constraint definitions mirror modules/billing/models.py
exactly (JSON, DateTime-without-tz, python-side defaults only — no
server_default, matching the models), so `alembic check` stays drift-free.
Native orders that need collision-free row-creation order:
  billing_plans -> billing_plan_versions -> billing_entitlement_flags
  billing_price_catalog_items -> billing_subscriptions -> billing_subscription_items
  organizations/users/payroll_employees FKs resolve against pre-existing tables.
Purely additive: 13 new tables, nothing altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '76e050fd5ffd'
down_revision: Union[str, Sequence[str], None] = '38263fcf0a1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'billing_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=30), nullable=False, unique=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_billing_plans_id'), 'billing_plans', ['id'], unique=False)

    op.create_table(
        'billing_plan_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('feature_set', sa.JSON(), nullable=True),
        sa.Column('scale_limits', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['billing_plans.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('plan_id', 'version', name='uq_billing_plan_version_plan_version'),
    )
    op.create_index(op.f('ix_billing_plan_versions_id'), 'billing_plan_versions', ['id'], unique=False)
    op.create_index(op.f('ix_billing_plan_versions_plan_id'), 'billing_plan_versions', ['plan_id'], unique=False)

    op.create_table(
        'billing_entitlement_flags',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_version_id', sa.Integer(), nullable=False),
        sa.Column('feature_key', sa.String(length=100), nullable=False),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['plan_version_id'], ['billing_plan_versions.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('plan_version_id', 'feature_key', name='uq_billing_entitlement_flag_version_key'),
    )
    op.create_index(op.f('ix_billing_entitlement_flags_id'), 'billing_entitlement_flags', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_entitlement_flags_plan_version_id'), 'billing_entitlement_flags', ['plan_version_id'], unique=False
    )
    op.create_index(op.f('ix_billing_entitlement_flags_feature_key'), 'billing_entitlement_flags', ['feature_key'], unique=False)

    op.create_table(
        'billing_entitlement_overrides',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('feature_key', sa.String(length=100), nullable=False),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('granted_by_user_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by_user_id'], ['users.id']),
    )
    op.create_index(op.f('ix_billing_entitlement_overrides_id'), 'billing_entitlement_overrides', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_entitlement_overrides_organization_id'), 'billing_entitlement_overrides', ['organization_id'], unique=False
    )
    op.create_index(op.f('ix_billing_entitlement_overrides_feature_key'), 'billing_entitlement_overrides', ['feature_key'], unique=False)
    op.create_index(
        op.f('ix_billing_entitlement_overrides_granted_by_user_id'), 'billing_entitlement_overrides', ['granted_by_user_id'], unique=False
    )
    op.create_index(op.f('ix_billing_entitlement_overrides_expires_at'), 'billing_entitlement_overrides', ['expires_at'], unique=False)

    op.create_table(
        'billing_price_catalog_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('catalog_version', sa.String(length=30), nullable=False),
        sa.Column('component_type', sa.String(length=50), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('unit_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_billing_price_catalog_items_id'), 'billing_price_catalog_items', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_price_catalog_items_catalog_version'), 'billing_price_catalog_items', ['catalog_version'], unique=False
    )

    op.create_table(
        'billing_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('plan_version_id', sa.Integer(), nullable=False),
        sa.Column('billing_authority', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('current_period_start', sa.DateTime(), nullable=False),
        sa.Column('current_period_end', sa.DateTime(), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_version_id'], ['billing_plan_versions.id']),
    )
    op.create_index(op.f('ix_billing_subscriptions_id'), 'billing_subscriptions', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_subscriptions_organization_id'), 'billing_subscriptions', ['organization_id'], unique=True
    )
    op.create_index(op.f('ix_billing_subscriptions_plan_version_id'), 'billing_subscriptions', ['plan_version_id'], unique=False)
    op.create_index(op.f('ix_billing_subscriptions_status'), 'billing_subscriptions', ['status'], unique=False)
    op.create_index(
        op.f('ix_billing_subscriptions_stripe_subscription_id'), 'billing_subscriptions', ['stripe_subscription_id'], unique=False
    )

    op.create_table(
        'billing_subscription_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('component_type', sa.String(length=50), nullable=False),
        sa.Column('unit_price_catalog_ref', sa.Integer(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['billing_subscriptions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_price_catalog_ref'], ['billing_price_catalog_items.id']),
    )
    op.create_index(op.f('ix_billing_subscription_items_id'), 'billing_subscription_items', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_subscription_items_subscription_id'), 'billing_subscription_items', ['subscription_id'], unique=False
    )
    op.create_index(
        op.f('ix_billing_subscription_items_unit_price_catalog_ref'), 'billing_subscription_items', ['unit_price_catalog_ref'], unique=False
    )

    op.create_table(
        'billing_worker_month_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('employer_entity_id', sa.Integer(), nullable=True),
        sa.Column('payroll_employee_id', sa.Integer(), nullable=False),
        sa.Column('billing_month', sa.Date(), nullable=False),
        sa.Column('counted', sa.Boolean(), nullable=False),
        sa.Column('reason_code', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payroll_employee_id'], ['payroll_employees.id']),
        sa.UniqueConstraint(
            'organization_id', 'payroll_employee_id', 'billing_month', name='uq_billing_bwm_org_employee_month'
        ),
    )
    op.create_index(op.f('ix_billing_worker_month_records_id'), 'billing_worker_month_records', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_worker_month_records_organization_id'), 'billing_worker_month_records', ['organization_id'], unique=False
    )
    op.create_index(
        op.f('ix_billing_worker_month_records_payroll_employee_id'), 'billing_worker_month_records', ['payroll_employee_id'], unique=False
    )

    op.create_table(
        'billing_invoices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=True),
        sa.Column('stripe_invoice_id', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_id'], ['billing_subscriptions.id']),
    )
    op.create_index(op.f('ix_billing_invoices_id'), 'billing_invoices', ['id'], unique=False)
    op.create_index(op.f('ix_billing_invoices_organization_id'), 'billing_invoices', ['organization_id'], unique=False)
    op.create_index(op.f('ix_billing_invoices_subscription_id'), 'billing_invoices', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_billing_invoices_stripe_invoice_id'), 'billing_invoices', ['stripe_invoice_id'], unique=False)

    op.create_table(
        'billing_invoice_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('component_type', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('line_total', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_billing_invoice_lines_id'), 'billing_invoice_lines', ['id'], unique=False)
    op.create_index(op.f('ix_billing_invoice_lines_invoice_id'), 'billing_invoice_lines', ['invoice_id'], unique=False)

    op.create_table(
        'billing_credit_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id']),
    )
    op.create_index(op.f('ix_billing_credit_notes_id'), 'billing_credit_notes', ['id'], unique=False)
    op.create_index(op.f('ix_billing_credit_notes_invoice_id'), 'billing_credit_notes', ['invoice_id'], unique=False)

    op.create_table(
        'billing_dunning_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=30), nullable=False),
        sa.Column('entered_at', sa.DateTime(), nullable=False),
        sa.Column('in_flight_run_guard', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_billing_dunning_state_id'), 'billing_dunning_state', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_dunning_state_organization_id'), 'billing_dunning_state', ['organization_id'], unique=True
    )

    op.create_table(
        'billing_commercial_audit_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
    )
    op.create_index(op.f('ix_billing_commercial_audit_events_id'), 'billing_commercial_audit_events', ['id'], unique=False)
    op.create_index(
        op.f('ix_billing_commercial_audit_events_organization_id'), 'billing_commercial_audit_events', ['organization_id'], unique=False
    )
    op.create_index(
        op.f('ix_billing_commercial_audit_events_event_type'), 'billing_commercial_audit_events', ['event_type'], unique=False
    )
    op.create_index(
        op.f('ix_billing_commercial_audit_events_created_at'), 'billing_commercial_audit_events', ['created_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_billing_commercial_audit_events_created_at'), table_name='billing_commercial_audit_events')
    op.drop_index(op.f('ix_billing_commercial_audit_events_event_type'), table_name='billing_commercial_audit_events')
    op.drop_index(op.f('ix_billing_commercial_audit_events_organization_id'), table_name='billing_commercial_audit_events')
    op.drop_index(op.f('ix_billing_commercial_audit_events_id'), table_name='billing_commercial_audit_events')
    op.drop_table('billing_commercial_audit_events')

    op.drop_index(op.f('ix_billing_dunning_state_organization_id'), table_name='billing_dunning_state')
    op.drop_index(op.f('ix_billing_dunning_state_id'), table_name='billing_dunning_state')
    op.drop_table('billing_dunning_state')

    op.drop_index(op.f('ix_billing_credit_notes_invoice_id'), table_name='billing_credit_notes')
    op.drop_index(op.f('ix_billing_credit_notes_id'), table_name='billing_credit_notes')
    op.drop_table('billing_credit_notes')

    op.drop_index(op.f('ix_billing_invoice_lines_invoice_id'), table_name='billing_invoice_lines')
    op.drop_index(op.f('ix_billing_invoice_lines_id'), table_name='billing_invoice_lines')
    op.drop_table('billing_invoice_lines')

    op.drop_index(op.f('ix_billing_invoices_stripe_invoice_id'), table_name='billing_invoices')
    op.drop_index(op.f('ix_billing_invoices_subscription_id'), table_name='billing_invoices')
    op.drop_index(op.f('ix_billing_invoices_organization_id'), table_name='billing_invoices')
    op.drop_index(op.f('ix_billing_invoices_id'), table_name='billing_invoices')
    op.drop_table('billing_invoices')

    op.drop_index(op.f('ix_billing_worker_month_records_payroll_employee_id'), table_name='billing_worker_month_records')
    op.drop_index(op.f('ix_billing_worker_month_records_organization_id'), table_name='billing_worker_month_records')
    op.drop_index(op.f('ix_billing_worker_month_records_id'), table_name='billing_worker_month_records')
    op.drop_table('billing_worker_month_records')

    op.drop_index(op.f('ix_billing_subscription_items_unit_price_catalog_ref'), table_name='billing_subscription_items')
    op.drop_index(op.f('ix_billing_subscription_items_subscription_id'), table_name='billing_subscription_items')
    op.drop_index(op.f('ix_billing_subscription_items_id'), table_name='billing_subscription_items')
    op.drop_table('billing_subscription_items')

    op.drop_index(op.f('ix_billing_subscriptions_stripe_subscription_id'), table_name='billing_subscriptions')
    op.drop_index(op.f('ix_billing_subscriptions_status'), table_name='billing_subscriptions')
    op.drop_index(op.f('ix_billing_subscriptions_plan_version_id'), table_name='billing_subscriptions')
    op.drop_index(op.f('ix_billing_subscriptions_organization_id'), table_name='billing_subscriptions')
    op.drop_index(op.f('ix_billing_subscriptions_id'), table_name='billing_subscriptions')
    op.drop_table('billing_subscriptions')

    op.drop_index(op.f('ix_billing_price_catalog_items_catalog_version'), table_name='billing_price_catalog_items')
    op.drop_index(op.f('ix_billing_price_catalog_items_id'), table_name='billing_price_catalog_items')
    op.drop_table('billing_price_catalog_items')

    op.drop_index(op.f('ix_billing_entitlement_overrides_expires_at'), table_name='billing_entitlement_overrides')
    op.drop_index(op.f('ix_billing_entitlement_overrides_granted_by_user_id'), table_name='billing_entitlement_overrides')
    op.drop_index(op.f('ix_billing_entitlement_overrides_feature_key'), table_name='billing_entitlement_overrides')
    op.drop_index(op.f('ix_billing_entitlement_overrides_organization_id'), table_name='billing_entitlement_overrides')
    op.drop_index(op.f('ix_billing_entitlement_overrides_id'), table_name='billing_entitlement_overrides')
    op.drop_table('billing_entitlement_overrides')

    op.drop_index(op.f('ix_billing_entitlement_flags_feature_key'), table_name='billing_entitlement_flags')
    op.drop_index(op.f('ix_billing_entitlement_flags_plan_version_id'), table_name='billing_entitlement_flags')
    op.drop_index(op.f('ix_billing_entitlement_flags_id'), table_name='billing_entitlement_flags')
    op.drop_table('billing_entitlement_flags')

    op.drop_index(op.f('ix_billing_plan_versions_plan_id'), table_name='billing_plan_versions')
    op.drop_index(op.f('ix_billing_plan_versions_id'), table_name='billing_plan_versions')
    op.drop_table('billing_plan_versions')

    op.drop_index(op.f('ix_billing_plans_id'), table_name='billing_plans')
    op.drop_table('billing_plans')
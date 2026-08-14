"""add assist tables

Revision ID: 8f3a2c9b6de1
Revises: 0b624a4a7481
Create Date: 2026-08-13 10:00:00.000000

Zoiko Payroll Assist's tables (backend/app/modules/assist/models.py) have
existed and been created via Base.metadata.create_all() at app startup since
before Alembic was introduced to this project, so they were never captured
in migration history. Autogenerate against the live database confirms these
28 tables already match the models exactly (zero diff reported for any of
them) — this migration exists purely to bring history in line with reality;
it is applied via `alembic stamp` on databases where the tables already
exist, and via `alembic upgrade` on any database where they don't yet.

assist_evidence_sets.response_id and assist_responses.evidence_set_id are
mutually referencing (both nullable) — assist_evidence_sets is created
first without that one FK, and it's added via a separate
op.create_foreign_key once assist_responses exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f3a2c9b6de1'
down_revision: Union[str, Sequence[str], None] = '0b624a4a7481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'assist_notices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notice_version', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('required', sa.Integer(), server_default='0', nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_notices_id'), 'assist_notices', ['id'], unique=False)
    op.create_index(op.f('ix_assist_notices_notice_version'), 'assist_notices', ['notice_version'], unique=True)

    op.create_table(
        'assist_notice_acknowledgments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('notice_version', sa.String(length=40), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', 'notice_version', name='uq_assist_notice_ack_user_version'),
    )
    op.create_index(op.f('ix_assist_notice_acknowledgments_id'), 'assist_notice_acknowledgments', ['id'], unique=False)
    op.create_index(op.f('ix_assist_notice_acknowledgments_organization_id'), 'assist_notice_acknowledgments', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_notice_acknowledgments_user_id'), 'assist_notice_acknowledgments', ['user_id'], unique=False)

    op.create_table(
        'assist_capabilities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('capability_id', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('risk_tier', sa.String(length=8), nullable=False),
        sa.Column('requires_confirmation', sa.Integer(), server_default='0', nullable=False),
        sa.Column('enabled', sa.Integer(), server_default='1', nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_capabilities_id'), 'assist_capabilities', ['id'], unique=False)
    op.create_index(op.f('ix_assist_capabilities_capability_id'), 'assist_capabilities', ['capability_id'], unique=True)

    op.create_table(
        'assist_suggestions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('intent_id', sa.String(length=80), nullable=False),
        sa.Column('context_type', sa.String(length=40), nullable=False),
        sa.Column('prompt', sa.String(length=300), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('locales', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('enabled', sa.Integer(), server_default='1', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_suggestions_id'), 'assist_suggestions', ['id'], unique=False)

    op.create_table(
        'assist_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('locale', sa.String(length=20), nullable=False),
        sa.Column('time_zone', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('retention_class', sa.String(length=40), nullable=False),
        sa.Column('context_object_type', sa.String(length=40), nullable=True),
        sa.Column('context_object_id', sa.String(length=80), nullable=True),
        sa.Column('context_object_version', sa.Integer(), nullable=True),
        sa.Column('jurisdiction_codes', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('context_hash', sa.String(length=64), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('case_link', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_sessions_id'), 'assist_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_assist_sessions_organization_id'), 'assist_sessions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_sessions_user_id'), 'assist_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_assist_sessions_status'), 'assist_sessions', ['status'], unique=False)
    op.create_index('ix_assist_sessions_org_user', 'assist_sessions', ['organization_id', 'user_id'], unique=False)
    op.create_index('ix_assist_sessions_org_created', 'assist_sessions', ['organization_id', 'created_at'], unique=False)

    op.create_table(
        'assist_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('classification', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_messages_id'), 'assist_messages', ['id'], unique=False)
    op.create_index(op.f('ix_assist_messages_session_id'), 'assist_messages', ['session_id'], unique=False)
    op.create_index(op.f('ix_assist_messages_organization_id'), 'assist_messages', ['organization_id'], unique=False)
    op.create_index('ix_assist_messages_session_created', 'assist_messages', ['session_id', 'created_at'], unique=False)

    op.create_table(
        'assist_kb_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('source_type', sa.String(length=40), nullable=True),
        sa.Column('authority_tier', sa.String(length=40), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('owner', sa.String(length=120), nullable=True),
        sa.Column('url', sa.String(length=300), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_kb_sources_id'), 'assist_kb_sources', ['id'], unique=False)
    op.create_index(op.f('ix_assist_kb_sources_organization_id'), 'assist_kb_sources', ['organization_id'], unique=False)

    op.create_table(
        'assist_kb_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('content_type', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=False),
        sa.Column('jurisdiction_codes', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('authority', sa.String(length=40), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('supersedes_item_id', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_review_at', sa.Date(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['source_id'], ['assist_kb_sources.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_kb_items_id'), 'assist_kb_items', ['id'], unique=False)
    op.create_index(op.f('ix_assist_kb_items_organization_id'), 'assist_kb_items', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_kb_items_state'), 'assist_kb_items', ['state'], unique=False)
    op.create_index('ix_assist_kb_org_state', 'assist_kb_items', ['organization_id', 'state'], unique=False)

    # assist_evidence_sets.response_id -> assist_responses.id is added after
    # assist_responses exists (see the deferred create_foreign_key below) —
    # the two tables mutually reference each other and both FKs are nullable.
    op.create_table(
        'assist_evidence_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('response_id', sa.Integer(), nullable=True),
        sa.Column('scope_hash', sa.String(length=64), nullable=True),
        sa.Column('entity_count', sa.Integer(), nullable=False),
        sa.Column('confidence_state', sa.String(length=20), nullable=False),
        sa.Column('reason_codes', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('freshness_state', sa.String(length=20), nullable=False),
        sa.Column('freshness_evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('conflict_state', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_evidence_sets_id'), 'assist_evidence_sets', ['id'], unique=False)
    op.create_index(op.f('ix_assist_evidence_sets_organization_id'), 'assist_evidence_sets', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_evidence_sets_session_id'), 'assist_evidence_sets', ['session_id'], unique=False)

    op.create_table(
        'assist_responses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('intent_id', sa.String(length=80), nullable=True),
        sa.Column('risk_tier', sa.String(length=8), nullable=True),
        sa.Column('engine', sa.String(length=30), nullable=False),
        sa.Column('model_route', sa.String(length=80), nullable=True),
        sa.Column('prompt_version', sa.String(length=40), nullable=True),
        sa.Column('policy_version', sa.String(length=40), nullable=True),
        sa.Column('evidence_set_id', sa.Integer(), nullable=True),
        sa.Column('validation_result', sa.JSON(), nullable=True),
        sa.Column('rendered_hash', sa.String(length=64), nullable=True),
        sa.Column('safety_state', sa.String(length=40), nullable=False),
        sa.Column('error_code', sa.String(length=60), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['evidence_set_id'], ['assist_evidence_sets.id']),
        sa.ForeignKeyConstraint(['message_id'], ['assist_messages.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_responses_id'), 'assist_responses', ['id'], unique=False)
    op.create_index(op.f('ix_assist_responses_session_id'), 'assist_responses', ['session_id'], unique=False)
    op.create_index(op.f('ix_assist_responses_organization_id'), 'assist_responses', ['organization_id'], unique=False)
    op.create_index('ix_assist_responses_session_created', 'assist_responses', ['session_id', 'created_at'], unique=False)

    op.create_foreign_key(
        'assist_evidence_sets_response_id_fkey',
        'assist_evidence_sets', 'assist_responses', ['response_id'], ['id'],
    )

    op.create_table(
        'assist_response_blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('response_id', sa.Integer(), nullable=False),
        sa.Column('block_type', sa.String(length=30), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['response_id'], ['assist_responses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_response_blocks_id'), 'assist_response_blocks', ['id'], unique=False)
    op.create_index(op.f('ix_assist_response_blocks_response_id'), 'assist_response_blocks', ['response_id'], unique=False)

    op.create_table(
        'assist_evidence_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('evidence_set_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=40), nullable=False),
        sa.Column('source_id', sa.String(length=120), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('effective_at', sa.Date(), nullable=True),
        sa.Column('freshness_state', sa.String(length=20), nullable=True),
        sa.Column('authority', sa.String(length=40), nullable=True),
        sa.Column('access_uri', sa.String(length=300), nullable=True),
        sa.Column('extra', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['evidence_set_id'], ['assist_evidence_sets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_evidence_items_id'), 'assist_evidence_items', ['id'], unique=False)
    op.create_index(op.f('ix_assist_evidence_items_evidence_set_id'), 'assist_evidence_items', ['evidence_set_id'], unique=False)

    op.create_table(
        'assist_retrieval_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('query_hash', sa.String(length=64), nullable=True),
        sa.Column('scope', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('candidate_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_retrieval_runs_id'), 'assist_retrieval_runs', ['id'], unique=False)
    op.create_index(op.f('ix_assist_retrieval_runs_organization_id'), 'assist_retrieval_runs', ['organization_id'], unique=False)

    op.create_table(
        'assist_retrieval_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('retrieval_run_id', sa.Integer(), nullable=False),
        sa.Column('kb_item_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['kb_item_id'], ['assist_kb_items.id']),
        sa.ForeignKeyConstraint(['retrieval_run_id'], ['assist_retrieval_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_retrieval_candidates_id'), 'assist_retrieval_candidates', ['id'], unique=False)
    op.create_index(op.f('ix_assist_retrieval_candidates_retrieval_run_id'), 'assist_retrieval_candidates', ['retrieval_run_id'], unique=False)

    op.create_table(
        'assist_intent_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('intent_id', sa.String(length=80), nullable=False),
        sa.Column('risk_tier', sa.String(length=8), nullable=False),
        sa.Column('confidence', sa.String(length=20), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['assist_messages.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_intent_decisions_id'), 'assist_intent_decisions', ['id'], unique=False)
    op.create_index(op.f('ix_assist_intent_decisions_session_id'), 'assist_intent_decisions', ['session_id'], unique=False)
    op.create_index(op.f('ix_assist_intent_decisions_organization_id'), 'assist_intent_decisions', ['organization_id'], unique=False)

    op.create_table(
        'assist_policy_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('resource_kind', sa.String(length=40), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('reason_code', sa.String(length=80), nullable=True),
        sa.Column('policy_version', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_policy_decisions_id'), 'assist_policy_decisions', ['id'], unique=False)
    op.create_index(op.f('ix_assist_policy_decisions_session_id'), 'assist_policy_decisions', ['session_id'], unique=False)
    op.create_index(op.f('ix_assist_policy_decisions_organization_id'), 'assist_policy_decisions', ['organization_id'], unique=False)

    op.create_table(
        'assist_model_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('response_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('model_route', sa.String(length=80), nullable=True),
        sa.Column('prompt_version', sa.String(length=40), nullable=True),
        sa.Column('provider', sa.String(length=40), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_code', sa.String(length=60), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['response_id'], ['assist_responses.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_model_executions_id'), 'assist_model_executions', ['id'], unique=False)
    op.create_index(op.f('ix_assist_model_executions_response_id'), 'assist_model_executions', ['response_id'], unique=False)
    op.create_index(op.f('ix_assist_model_executions_organization_id'), 'assist_model_executions', ['organization_id'], unique=False)

    op.create_table(
        'assist_exception_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('exception_key', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('assignee_role', sa.String(length=60), nullable=True),
        sa.Column('assignee_user_id', sa.Integer(), nullable=True),
        sa.Column('object_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'run_id', 'exception_key', name='uq_assist_exception_org_run_key'),
    )
    op.create_index(op.f('ix_assist_exception_snapshots_id'), 'assist_exception_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_assist_exception_snapshots_organization_id'), 'assist_exception_snapshots', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_exception_snapshots_run_id'), 'assist_exception_snapshots', ['run_id'], unique=False)

    op.create_table(
        'assist_action_previews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('action_id', sa.String(length=80), nullable=False),
        sa.Column('risk_tier', sa.String(length=8), nullable=False),
        sa.Column('target_type', sa.String(length=40), nullable=False),
        sa.Column('target_id', sa.String(length=80), nullable=False),
        sa.Column('target_version', sa.Integer(), nullable=True),
        sa.Column('before_data', sa.JSON(), nullable=True),
        sa.Column('after_data', sa.JSON(), nullable=True),
        sa.Column('confirmation_label', sa.String(length=120), nullable=True),
        sa.Column('step_up_required', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.String(length=30), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_action_previews_id'), 'assist_action_previews', ['id'], unique=False)
    op.create_index(op.f('ix_assist_action_previews_organization_id'), 'assist_action_previews', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_action_previews_user_id'), 'assist_action_previews', ['user_id'], unique=False)
    op.create_index(op.f('ix_assist_action_previews_session_id'), 'assist_action_previews', ['session_id'], unique=False)

    op.create_table(
        'assist_action_confirmations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('preview_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=80), nullable=True),
        sa.Column('confirmation_token', sa.String(length=64), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['preview_id'], ['assist_action_previews.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('preview_id'),
    )
    op.create_index(op.f('ix_assist_action_confirmations_id'), 'assist_action_confirmations', ['id'], unique=False)
    op.create_index(op.f('ix_assist_action_confirmations_preview_id'), 'assist_action_confirmations', ['preview_id'], unique=True)

    op.create_table(
        'assist_action_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('preview_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('action_id', sa.String(length=80), nullable=False),
        sa.Column('target_type', sa.String(length=40), nullable=False),
        sa.Column('target_id', sa.String(length=80), nullable=False),
        sa.Column('target_version', sa.Integer(), nullable=True),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('audit_id', sa.Integer(), nullable=True),
        sa.Column('committed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['preview_id'], ['assist_action_previews.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('preview_id'),
    )
    op.create_index(op.f('ix_assist_action_receipts_id'), 'assist_action_receipts', ['id'], unique=False)
    op.create_index(op.f('ix_assist_action_receipts_organization_id'), 'assist_action_receipts', ['organization_id'], unique=False)

    op.create_table(
        'assist_drafts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('draft_type', sa.String(length=40), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_drafts_id'), 'assist_drafts', ['id'], unique=False)
    op.create_index(op.f('ix_assist_drafts_organization_id'), 'assist_drafts', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_drafts_user_id'), 'assist_drafts', ['user_id'], unique=False)

    op.create_table(
        'assist_handoff_previews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('destination', sa.String(length=60), nullable=False),
        sa.Column('reason_code', sa.String(length=80), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('evidence_ids', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('excluded_data_classes', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_handoff_previews_id'), 'assist_handoff_previews', ['id'], unique=False)
    op.create_index(op.f('ix_assist_handoff_previews_organization_id'), 'assist_handoff_previews', ['organization_id'], unique=False)

    op.create_table(
        'assist_handoffs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('preview_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('destination', sa.String(length=60), nullable=False),
        sa.Column('reason_code', sa.String(length=80), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=True),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('sla_reference', sa.String(length=80), nullable=True),
        sa.Column('audit_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['preview_id'], ['assist_handoff_previews.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('preview_id'),
    )
    op.create_index(op.f('ix_assist_handoffs_id'), 'assist_handoffs', ['id'], unique=False)
    op.create_index(op.f('ix_assist_handoffs_organization_id'), 'assist_handoffs', ['organization_id'], unique=False)

    op.create_table(
        'assist_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('response_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('rating', sa.String(length=30), nullable=False),
        sa.Column('reason_code', sa.String(length=60), nullable=True),
        sa.Column('comment_redacted', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['response_id'], ['assist_responses.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_feedback_id'), 'assist_feedback', ['id'], unique=False)
    op.create_index(op.f('ix_assist_feedback_organization_id'), 'assist_feedback', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assist_feedback_response_id'), 'assist_feedback', ['response_id'], unique=False)

    op.create_table(
        'assist_idempotency_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=60), nullable=False),
        sa.Column('idempotency_key', sa.String(length=80), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('response_body', sa.JSON(), nullable=True),
        sa.Column('resource_type', sa.String(length=40), nullable=True),
        sa.Column('resource_id', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'scope', 'idempotency_key', name='uq_assist_idem_org_scope_key'),
    )
    op.create_index(op.f('ix_assist_idempotency_records_id'), 'assist_idempotency_records', ['id'], unique=False)
    op.create_index(op.f('ix_assist_idempotency_records_organization_id'), 'assist_idempotency_records', ['organization_id'], unique=False)

    op.create_table(
        'assist_audit_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['session_id'], ['assist_sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_audit_events_id'), 'assist_audit_events', ['id'], unique=False)
    op.create_index(op.f('ix_assist_audit_events_organization_id'), 'assist_audit_events', ['organization_id'], unique=False)
    op.create_index('ix_assist_audit_org_created', 'assist_audit_events', ['organization_id', 'recorded_at'], unique=False)

    op.create_table(
        'assist_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('job_type', sa.String(length=60), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('response_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['response_id'], ['assist_responses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assist_jobs_id'), 'assist_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_assist_jobs_organization_id'), 'assist_jobs', ['organization_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('assist_jobs')
    op.drop_table('assist_audit_events')
    op.drop_table('assist_idempotency_records')
    op.drop_table('assist_feedback')
    op.drop_table('assist_handoffs')
    op.drop_table('assist_handoff_previews')
    op.drop_table('assist_drafts')
    op.drop_table('assist_action_receipts')
    op.drop_table('assist_action_confirmations')
    op.drop_table('assist_action_previews')
    op.drop_table('assist_exception_snapshots')
    op.drop_table('assist_model_executions')
    op.drop_table('assist_policy_decisions')
    op.drop_table('assist_intent_decisions')
    op.drop_table('assist_retrieval_candidates')
    op.drop_table('assist_retrieval_runs')
    op.drop_constraint('assist_evidence_sets_response_id_fkey', 'assist_evidence_sets', type_='foreignkey')
    op.drop_table('assist_evidence_items')
    op.drop_table('assist_response_blocks')
    op.drop_table('assist_responses')
    op.drop_table('assist_evidence_sets')
    op.drop_table('assist_kb_items')
    op.drop_table('assist_kb_sources')
    op.drop_table('assist_messages')
    op.drop_table('assist_sessions')
    op.drop_table('assist_suggestions')
    op.drop_table('assist_capabilities')
    op.drop_table('assist_notice_acknowledgments')
    op.drop_table('assist_notices')

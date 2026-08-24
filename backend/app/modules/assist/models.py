"""
modules/assist/models.py
------------------------
SQLAlchemy ORM models for the Zoiko Payroll Assist feature.

These tables are Assist-owned. They persist typed references, governed
conversation/response records, evidence sets, action previews/receipts,
handoffs, drafts, feedback, notices, idempotency records and the governed
knowledge base. The authoritative payroll domain tables (payroll_runs,
payroll_employees, ...) are never modified by these models — Assist stores
typed references and approved minimum snapshots only, and retrieves current
domain data through the tool adapter layer at answer time.
"""

import enum

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ── Shared enums ─────────────────────────────────────────────────────────

class AssistSessionState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    EXPIRED = "EXPIRED"


class AssistMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AssistResponseState(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class EvidenceConfidenceState(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessState(str, enum.Enum):
    CURRENT = "CURRENT"
    REVIEW_DUE = "REVIEW_DUE"
    OVERDUE = "OVERDUE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


class ConflictState(str, enum.Enum):
    NONE = "NONE"
    POTENTIAL = "POTENTIAL"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"


class ActionRiskTier(str, enum.Enum):
    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"


class ActionPreviewState(str, enum.Enum):
    READY_FOR_CONFIRMATION = "READY_FOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    CONFLICTED = "CONFLICTED"
    POLICY_DENIED = "POLICY_DENIED"


class ReceiptOutcome(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CONFLICTED = "CONFLICTED"
    POLICY_DENIED = "POLICY_DENIED"


class DraftState(str, enum.Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DELETED = "DELETED"


class HandoffState(str, enum.Enum):
    PREVIEWED = "PREVIEWED"
    CONFIRMED = "CONFIRMED"
    CREATED = "CREATED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"


class FeedbackRating(str, enum.Enum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not-helpful"
    WRONG = "wrong"
    UNSAFE = "unsafe"
    OUTDATED = "outdated"
    INCOMPLETE = "incomplete"
    ACTION_FAILED = "action-failed"


class KnowledgeState(str, enum.Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SCHEDULED = "SCHEDULED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    QUARANTINED = "QUARANTINED"


class KnowledgeSourceState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class AuthorityTier(str, enum.Enum):
    TIER_1_OPERATIONAL = "TIER_1_OPERATIONAL"
    TIER_2_APPROVED_PRIMARY = "TIER_2_APPROVED_PRIMARY"
    TIER_3_APPROVED_SECONDARY = "TIER_3_APPROVED_SECONDARY"
    TIER_4_TENANT = "TIER_4_TENANT"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"


class JobState(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


# ── Notices and acknowledgments ─────────────────────────────────────────

class AssistNotice(Base):
    __tablename__ = "assist_notices"

    id = Column(Integer, primary_key=True, index=True)
    notice_version = Column(String(40), nullable=False, unique=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    required = Column(Integer, nullable=False, server_default="0")
    effective_from = Column(DateTime(timezone=True), server_default=func.now())
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssistNoticeAcknowledgment(Base):
    __tablename__ = "assist_notice_acknowledgments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    notice_version = Column(String(40), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "notice_version", name="uq_assist_notice_ack_user_version"),
    )


# ── Capabilities and suggestions ────────────────────────────────────────

class AssistCapability(Base):
    __tablename__ = "assist_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    capability_id = Column(String(80), nullable=False, unique=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    risk_tier = Column(String(8), default=ActionRiskTier.A1.value, nullable=False)
    requires_confirmation = Column(Integer, nullable=False, server_default="0")
    enabled = Column(Integer, nullable=False, server_default="1")
    order_index = Column(Integer, default=0, nullable=False)


class AssistSuggestion(Base):
    __tablename__ = "assist_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    intent_id = Column(String(80), nullable=False)
    context_type = Column(String(40), default="GLOBAL", nullable=False)
    prompt = Column(String(300), nullable=False)
    position = Column(Integer, default=0, nullable=False)
    locales = Column(JSON, default=list, nullable=False, server_default="[]")
    enabled = Column(Integer, nullable=False, server_default="1")


# ── Sessions ────────────────────────────────────────────────────────────

class AssistSession(Base):
    __tablename__ = "assist_sessions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(20), default="WEB", nullable=False)
    locale = Column(String(20), default="en", nullable=False)
    time_zone = Column(String(40), default="UTC", nullable=False)
    status = Column(String(20), default=AssistSessionState.ACTIVE.value, nullable=False, index=True)
    retention_class = Column(String(40), default="STANDARD", nullable=False)

    # Bound context (optional) — derived server-side from the entry point.
    context_object_type = Column(String(40), nullable=True)
    context_object_id = Column(String(80), nullable=True)
    context_object_version = Column(Integer, nullable=True)
    jurisdiction_codes = Column(JSON, default=list, nullable=False, server_default="[]")
    context_hash = Column(String(64), nullable=True)

    title = Column(String(255), nullable=True)
    case_link = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    archived_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    messages = relationship("AssistMessage", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_assist_sessions_org_user", "organization_id", "user_id"),
        Index("ix_assist_sessions_org_created", "organization_id", "created_at"),
    )


# ── Messages ────────────────────────────────────────────────────────────

class AssistMessage(Base):
    __tablename__ = "assist_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    role = Column(String(20), default=AssistMessageRole.USER.value, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True)
    classification = Column(String(40), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("AssistSession", back_populates="messages")
    response = relationship("AssistResponse", back_populates="message", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_assist_messages_session_created", "session_id", "created_at"),
    )

    @property
    def response_id(self):
        """The assistant's reply is stored as its own AssistResponse row, not
        a second AssistMessage — expose the link so history/resume can find
        it without a second lookup per message."""
        return self.response.id if self.response else None


# ── Responses ───────────────────────────────────────────────────────────

class AssistResponse(Base):
    __tablename__ = "assist_responses"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("assist_messages.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    state = Column(String(20), default=AssistResponseState.ACCEPTED.value, nullable=False)
    intent_id = Column(String(80), nullable=True)
    risk_tier = Column(String(8), nullable=True)
    engine = Column(String(30), default="deterministic", nullable=False)
    model_route = Column(String(80), nullable=True)
    prompt_version = Column(String(40), nullable=True)
    policy_version = Column(String(40), nullable=True)
    evidence_set_id = Column(Integer, ForeignKey("assist_evidence_sets.id"), nullable=True)
    validation_result = Column(JSON, nullable=True)
    rendered_hash = Column(String(64), nullable=True)
    safety_state = Column(String(40), default="SAFE", nullable=False)
    error_code = Column(String(60), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    message = relationship("AssistMessage", back_populates="response")
    blocks = relationship("AssistResponseBlock", back_populates="response", cascade="all, delete-orphan")
    feedback = relationship("AssistFeedback", back_populates="response", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_assist_responses_session_created", "session_id", "created_at"),
    )


class AssistResponseBlock(Base):
    __tablename__ = "assist_response_blocks"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("assist_responses.id"), nullable=False, index=True)
    block_type = Column(String(30), default="text", nullable=False)
    content = Column(Text, nullable=True)
    sequence = Column(Integer, default=0, nullable=False)
    data = Column(JSON, nullable=True)

    response = relationship("AssistResponse", back_populates="blocks")


# ── Evidence ────────────────────────────────────────────────────────────

class AssistEvidenceSet(Base):
    __tablename__ = "assist_evidence_sets"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True, index=True)
    response_id = Column(Integer, ForeignKey("assist_responses.id"), nullable=True)

    scope_hash = Column(String(64), nullable=True)
    entity_count = Column(Integer, default=0, nullable=False)
    confidence_state = Column(String(20), default=EvidenceConfidenceState.MEDIUM.value, nullable=False)
    reason_codes = Column(JSON, default=list, nullable=False, server_default="[]")
    freshness_state = Column(String(20), default=FreshnessState.CURRENT.value, nullable=False)
    freshness_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    conflict_state = Column(String(20), default=ConflictState.NONE.value, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship("AssistEvidenceItem", back_populates="evidence_set", cascade="all, delete-orphan")


class AssistEvidenceItem(Base):
    __tablename__ = "assist_evidence_items"

    id = Column(Integer, primary_key=True, index=True)
    evidence_set_id = Column(Integer, ForeignKey("assist_evidence_sets.id"), nullable=False, index=True)
    source_type = Column(String(40), nullable=False)
    source_id = Column(String(120), nullable=True)
    title = Column(String(300), nullable=False)
    effective_at = Column(Date, nullable=True)
    freshness_state = Column(String(20), nullable=True)
    authority = Column(String(40), nullable=True)
    access_uri = Column(String(300), nullable=True)
    extra = Column(JSON, nullable=True)

    evidence_set = relationship("AssistEvidenceSet", back_populates="items")


# ── Retrieval tracking ──────────────────────────────────────────────────

class AssistRetrievalRun(Base):
    __tablename__ = "assist_retrieval_runs"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True)
    query_hash = Column(String(64), nullable=True)
    scope = Column(JSON, default=dict, nullable=False, server_default="{}")
    candidate_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    candidates = relationship("AssistRetrievalCandidate", back_populates="retrieval_run", cascade="all, delete-orphan")


class AssistRetrievalCandidate(Base):
    __tablename__ = "assist_retrieval_candidates"

    id = Column(Integer, primary_key=True, index=True)
    retrieval_run_id = Column(Integer, ForeignKey("assist_retrieval_runs.id"), nullable=False, index=True)
    kb_item_id = Column(Integer, ForeignKey("assist_kb_items.id"), nullable=False)
    score = Column(Integer, default=0, nullable=False)
    rank = Column(Integer, default=0, nullable=False)
    reason = Column(String(120), nullable=True)

    retrieval_run = relationship("AssistRetrievalRun", back_populates="candidates")


# ── Execution / orchestration records ───────────────────────────────────

class AssistIntentDecision(Base):
    __tablename__ = "assist_intent_decisions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("assist_messages.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    intent_id = Column(String(80), nullable=False)
    risk_tier = Column(String(8), nullable=False)
    confidence = Column(String(20), default="HIGH", nullable=False)
    method = Column(String(20), default="deterministic", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssistPolicyDecision(Base):
    __tablename__ = "assist_policy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    resource_kind = Column(String(40), nullable=False)
    decision = Column(String(20), nullable=False)  # allow / deny / confirm / route
    reason_code = Column(String(80), nullable=True)
    policy_version = Column(String(40), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssistModelExecution(Base):
    __tablename__ = "assist_model_executions"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("assist_responses.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    model_route = Column(String(80), nullable=True)
    prompt_version = Column(String(40), nullable=True)
    provider = Column(String(40), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)
    error_code = Column(String(60), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── A3 action previews / confirmations / receipts ───────────────────────

class AssistExceptionSnapshot(Base):
    """Assist-owned snapshot of derived payroll exceptions (readiness blockers).

    Derived deterministically from authoritative payroll runs at retrieval
    time; assigning an owner mutates this snapshot (with before/after, receipt
    and audit). This is an approved minimum snapshot — never a replacement for
    payroll domain records.
    """
    __tablename__ = "assist_exception_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    exception_key = Column(String(80), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="MEDIUM", nullable=False)
    state = Column(String(20), default="OPEN", nullable=False)
    assignee_role = Column(String(60), nullable=True)
    assignee_user_id = Column(Integer, nullable=True)
    object_version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "run_id", "exception_key", name="uq_assist_exception_org_run_key"),
    )


class AssistActionPreview(Base):
    __tablename__ = "assist_action_previews"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True, index=True)

    action_id = Column(String(80), nullable=False)
    risk_tier = Column(String(8), nullable=False)
    target_type = Column(String(40), nullable=False)
    target_id = Column(String(80), nullable=False)
    target_version = Column(Integer, nullable=True)
    before_data = Column(JSON, nullable=True)
    after_data = Column(JSON, nullable=True)
    confirmation_label = Column(String(120), nullable=True)
    step_up_required = Column(Integer, nullable=False, server_default="0")
    state = Column(String(30), default=ActionPreviewState.READY_FOR_CONFIRMATION.value, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    confirmation = relationship("AssistActionConfirmation", back_populates="preview", uselist=False, cascade="all, delete-orphan")
    receipt = relationship("AssistActionReceipt", back_populates="preview", uselist=False)


class AssistActionConfirmation(Base):
    __tablename__ = "assist_action_confirmations"

    id = Column(Integer, primary_key=True, index=True)
    preview_id = Column(Integer, ForeignKey("assist_action_previews.id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(80), nullable=True)
    confirmation_token = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), server_default=func.now())

    preview = relationship("AssistActionPreview", back_populates="confirmation")


class AssistActionReceipt(Base):
    __tablename__ = "assist_action_receipts"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    preview_id = Column(Integer, ForeignKey("assist_action_previews.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_id = Column(String(80), nullable=False)
    target_type = Column(String(40), nullable=False)
    target_id = Column(String(80), nullable=False)
    target_version = Column(Integer, nullable=True)
    outcome = Column(String(20), default=ReceiptOutcome.SUCCEEDED.value, nullable=False)
    audit_id = Column(Integer, nullable=True)
    committed_at = Column(DateTime(timezone=True), server_default=func.now())

    preview = relationship("AssistActionPreview", back_populates="receipt")


# ── Drafts ──────────────────────────────────────────────────────────────

class AssistDraft(Base):
    __tablename__ = "assist_drafts"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True)
    draft_type = Column(String(40), nullable=False)
    content = Column(Text, nullable=False)
    state = Column(String(20), default=DraftState.DRAFT.value, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ── Handoffs ────────────────────────────────────────────────────────────

class AssistHandoffPreview(Base):
    __tablename__ = "assist_handoff_previews"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True)
    destination = Column(String(60), nullable=False)
    reason_code = Column(String(80), nullable=False)
    summary = Column(Text, nullable=False)
    evidence_ids = Column(JSON, default=list, nullable=False, server_default="[]")
    excluded_data_classes = Column(JSON, default=list, nullable=False, server_default="[]")
    state = Column(String(20), default=HandoffState.PREVIEWED.value, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    handoff = relationship("AssistHandoff", back_populates="preview", uselist=False)


class AssistHandoff(Base):
    __tablename__ = "assist_handoffs"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    preview_id = Column(Integer, ForeignKey("assist_handoff_previews.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    destination = Column(String(60), nullable=False)
    reason_code = Column(String(80), nullable=False)
    summary = Column(Text, nullable=False)
    case_id = Column(String(80), nullable=True)
    state = Column(String(20), default=HandoffState.CREATED.value, nullable=False)
    sla_reference = Column(String(80), nullable=True)
    audit_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    preview = relationship("AssistHandoffPreview", back_populates="handoff")


# ── Feedback ────────────────────────────────────────────────────────────

class AssistFeedback(Base):
    __tablename__ = "assist_feedback"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    response_id = Column(Integer, ForeignKey("assist_responses.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rating = Column(String(30), nullable=False)
    reason_code = Column(String(60), nullable=True)
    comment_redacted = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    response = relationship("AssistResponse", back_populates="feedback")


# ── Idempotency / audit / jobs ──────────────────────────────────────────

class AssistIdempotencyRecord(Base):
    __tablename__ = "assist_idempotency_records"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    scope = Column(String(60), nullable=False)
    idempotency_key = Column(String(80), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_body = Column(JSON, nullable=True)
    resource_type = Column(String(40), nullable=True)
    resource_id = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "scope", "idempotency_key", name="uq_assist_idem_org_scope_key"),
    )


class AssistAuditEvent(Base):
    __tablename__ = "assist_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    session_id = Column(Integer, ForeignKey("assist_sessions.id"), nullable=True)
    event_type = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_assist_audit_org_created", "organization_id", "recorded_at"),
    )


class AssistJob(Base):
    __tablename__ = "assist_jobs"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    job_type = Column(String(60), nullable=False)
    state = Column(String(20), default=JobState.PENDING.value, nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    response_id = Column(Integer, ForeignKey("assist_responses.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)


# ── Governed knowledge base ─────────────────────────────────────────────

class AssistKbSource(Base):
    __tablename__ = "assist_kb_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    source_type = Column(String(40), nullable=True)
    authority_tier = Column(String(40), default=AuthorityTier.TIER_3_APPROVED_SECONDARY.value, nullable=False)
    state = Column(String(20), default=KnowledgeSourceState.ACTIVE.value, nullable=False)
    owner = Column(String(120), nullable=True)
    url = Column(String(300), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssistKbItem(Base):
    __tablename__ = "assist_kb_items"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("assist_kb_sources.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    content_type = Column(String(40), default="HOW_TO", nullable=False)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    summary = Column(String(500), nullable=True)
    language = Column(String(10), default="en", nullable=False)
    jurisdiction_codes = Column(JSON, default=list, nullable=False, server_default="[]")
    state = Column(String(20), default=KnowledgeState.DRAFT.value, nullable=False, index=True)
    # Reason/evidence retained for REJECTED, WITHDRAWN, QUARANTINED and
    # CORRECTION_REQUIRED transitions (KB governance spec §12/§14 — every
    # non-routine exit from PUBLISHED must record why).
    state_reason = Column(Text, nullable=True)
    authority = Column(String(40), default=AuthorityTier.TIER_3_APPROVED_SECONDARY.value, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    supersedes_item_id = Column(Integer, ForeignKey("assist_kb_items.id"), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    next_review_at = Column(Date, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_assist_kb_org_state", "organization_id", "state"),
    )


# ── Public (unauthenticated) website widget ─────────────────────────────
# Deliberately separate from AssistSession/AssistMessage rather than making
# organization_id/user_id nullable there — anonymous marketing-site traffic
# has no organization or user at all, and keeping it in its own tables means
# it can never end up entangled with real customer session data even by
# accident. No context binding, no jurisdiction codes, no retention class:
# this surface only ever answers from the global (organization_id IS NULL)
# knowledge base, so none of that authenticated-session machinery applies.

class AssistPublicSession(Base):
    __tablename__ = "assist_public_sessions"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), nullable=True)
    locale = Column(String(20), default="en", nullable=False)
    message_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    messages = relationship("AssistPublicMessage", back_populates="session", cascade="all, delete-orphan")


class AssistPublicMessage(Base):
    __tablename__ = "assist_public_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assist_public_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("AssistPublicSession", back_populates="messages")

    __table_args__ = (
        Index("ix_assist_public_messages_session", "session_id", "created_at"),
    )

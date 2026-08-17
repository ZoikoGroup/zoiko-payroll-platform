"""
modules/assist/schemas.py
-------------------------
Pydantic schemas for the Zoiko Payroll Assist API.

Field shapes mirror the approved API wireframe (ZP-AST-API-001):
sessions, capabilities, suggestions, notices, messages, responses, evidence,
drafts, handoffs, controlled actions, feedback and service status.
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SuccessResponse(BaseModel):
    message: str
    success: bool = True


# ── Context helpers ─────────────────────────────────────────────────────

class ContextObjectRef(BaseModel):
    type: str = Field(..., description="e.g. PAYROLL_RUN / PAYROLL_EXCEPTION / EMPLOYEE")
    id: str = Field(..., description="object reference id")
    version: Optional[int] = None


class ClientInfo(BaseModel):
    channel: str = "WEB"
    locale: str = "en"
    time_zone: str = "UTC"


class AssistContext(BaseModel):
    object: Optional[ContextObjectRef] = None
    jurisdiction_codes: list[str] = Field(default_factory=list)


# ── Sessions ────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    channel: str = "WEB"
    locale: str = "en"
    time_zone: str = "UTC"
    context: Optional[AssistContext] = None
    title: Optional[str] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None
    context: Optional[AssistContext] = None
    case_link: Optional[str] = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: Optional[int] = None
    status: str
    channel: str
    locale: str
    time_zone: str
    context_object_type: Optional[str] = None
    context_object_id: Optional[str] = None
    context_object_version: Optional[int] = None
    jurisdiction_codes: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    case_link: Optional[str] = None
    retention_class: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


# ── Capabilities / suggestions / notices ───────────────────────────────

class CapabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    capability_id: str
    name: str
    description: Optional[str] = None
    risk_tier: str
    requires_confirmation: bool = False
    enabled: bool = True


class CapabilitiesResponse(BaseModel):
    capabilities: list[CapabilityResponse]


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    intent_id: str
    context_type: str
    prompt: str
    position: int


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionResponse]


class NoticeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notice_version: str
    title: str
    content: str
    required: bool = False
    effective_from: Optional[datetime] = None
    acknowledged: bool = False


class NoticeAckResponse(BaseModel):
    notice_version: str
    acknowledged: bool = True
    acknowledged_at: datetime


# ── Messages ────────────────────────────────────────────────────────────

class MessageContent(BaseModel):
    type: str = "TEXT"
    text: str = Field(..., max_length=8000)


class MessageSubmitRequest(BaseModel):
    content: MessageContent
    context: Optional[AssistContext] = None
    client: Optional[ClientInfo] = None


class MessageSubmitResponse(BaseModel):
    message_id: int
    response_id: int
    state: str
    events_uri: str
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    classification: Optional[str] = None
    created_at: datetime
    response_id: Optional[int] = None


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


# ── Responses / blocks ──────────────────────────────────────────────────

class ResponseBlockSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_type: str
    content: Optional[str] = None
    sequence: int
    data: Optional[dict[str, Any]] = None


class SourceRefSchema(BaseModel):
    evidence_id: int
    source_type: str
    title: str
    effective_at: Optional[date] = None
    freshness_state: Optional[str] = None
    authority: Optional[str] = None
    access_uri: Optional[str] = None


class ResponseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    message_id: Optional[int] = None
    state: str
    intent_id: Optional[str] = None
    risk_tier: Optional[str] = None
    engine: Optional[str] = None
    model_route: Optional[str] = None
    prompt_version: Optional[str] = None
    evidence_set_id: Optional[int] = None
    safety_state: Optional[str] = None
    error_code: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    blocks: list[ResponseBlockSchema] = Field(default_factory=list)
    sources: list[SourceRefSchema] = Field(default_factory=list)


class ResponseEventSchema(BaseModel):
    event_type: str
    sequence: int
    data: Optional[dict[str, Any]] = None
    at: datetime


class ResponseEventsResponse(BaseModel):
    response_id: int
    state: str
    events: list[ResponseEventSchema]


class ResponseStatusResponse(BaseModel):
    response_id: int
    state: str
    intent_id: Optional[str] = None
    progress: Optional[int] = None
    completed_at: Optional[datetime] = None
    error_code: Optional[str] = None


class StopResponse(BaseModel):
    response_id: int
    state: str


# ── Evidence ────────────────────────────────────────────────────────────

class EvidenceScopeSchema(BaseModel):
    entity_count: int = 0
    jurisdiction_codes: list[str] = Field(default_factory=list)


class EvidenceConfidenceSchema(BaseModel):
    state: str
    reason_codes: list[str] = Field(default_factory=list)


class EvidenceFreshnessSchema(BaseModel):
    state: str
    evaluated_at: Optional[datetime] = None


class EvidenceConflictSchema(BaseModel):
    state: str


class EvidenceSetResponse(BaseModel):
    evidence_set_id: int
    scope: EvidenceScopeSchema = Field(default_factory=EvidenceScopeSchema)
    confidence: EvidenceConfidenceSchema = Field(default_factory=EvidenceConfidenceSchema)
    freshness: EvidenceFreshnessSchema = Field(default_factory=EvidenceFreshnessSchema)
    conflict: EvidenceConflictSchema = Field(default_factory=EvidenceConflictSchema)
    sources: list[SourceRefSchema] = Field(default_factory=list)


class EvidenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: int
    source_type: str
    title: str
    effective_at: Optional[date] = None
    freshness_state: Optional[str] = None
    authority: Optional[str] = None
    access_uri: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class SourcesResponse(BaseModel):
    response_id: int
    sources: list[SourceRefSchema]


# ── Feedback ────────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    rating: str = Field(..., description="helpful / not-helpful / wrong / unsafe / outdated / incomplete / action-failed")
    reason_code: Optional[str] = None
    comment: Optional[str] = Field(None, max_length=2000)


class AuditReferenceResponse(BaseModel):
    audit_id: int
    event_type: str
    recorded_at: datetime


# ── Drafts ──────────────────────────────────────────────────────────────

class DraftCreate(BaseModel):
    draft_type: str = Field(..., description="e.g. note / case_summary / email")
    content: str = Field(..., max_length=20000)
    session_id: Optional[int] = None


class DraftUpdate(BaseModel):
    content: Optional[str] = Field(None, max_length=20000)
    state: Optional[str] = None


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    draft_type: str
    content: str
    state: str
    revision: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class DraftListResponse(BaseModel):
    drafts: list[DraftResponse]
    total: int


# ── Handoffs ────────────────────────────────────────────────────────────

class HandoffPreviewCreate(BaseModel):
    destination: str = Field(..., description="e.g. COMPLIANCE_LOCAL_PAYROLL / PAYROLL_SUPPORT")
    reason_code: str
    summary: str = Field(..., max_length=4000)
    included_evidence_ids: list[int] = Field(default_factory=list)
    excluded_data_classes: list[str] = Field(default_factory=list)
    source_response_id: Optional[int] = None


class HandoffPreviewResponse(BaseModel):
    preview_id: int
    destination: str
    reason_code: str
    summary: str
    included_evidence_ids: list[int] = Field(default_factory=list)
    excluded_data_classes: list[str] = Field(default_factory=list)
    state: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class HandoffCreateResponse(BaseModel):
    handoff_id: int
    case_id: Optional[str] = None
    destination: str
    reason_code: str
    state: str
    assigned_owner: Optional[str] = None
    sla_reference: Optional[str] = None
    audit_id: Optional[int] = None
    created_at: datetime


class HandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    destination: str
    reason_code: str
    summary: str
    case_id: Optional[str] = None
    state: str
    sla_reference: Optional[str] = None
    audit_id: Optional[int] = None
    created_at: datetime


# ── Controlled actions ──────────────────────────────────────────────────

class ActionTarget(BaseModel):
    type: str
    id: str
    version: Optional[int] = None


class ActionPreviewCreate(BaseModel):
    action_id: str
    target: ActionTarget
    arguments: dict[str, Any] = Field(default_factory=dict)
    source_response_id: Optional[int] = None


class ActionConfirmationSchema(BaseModel):
    label: Optional[str] = None
    step_up_required: bool = False


class ActionPreviewResponse(BaseModel):
    preview_id: int
    risk_tier: str
    state: str
    action_id: str
    target: ActionTarget
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    confirmation: ActionConfirmationSchema = Field(default_factory=ActionConfirmationSchema)
    expires_at: Optional[datetime] = None
    etag: Optional[str] = None


class ActionConfirmRequest(BaseModel):
    confirmation_token: Optional[str] = None


class ActionReceiptResponse(BaseModel):
    receipt_id: int
    outcome: str
    action_id: str
    target: ActionTarget
    committed_at: datetime
    audit_id: Optional[int] = None


class AllowedActionResponse(BaseModel):
    action_id: str
    risk_tier: str
    description: str = ""
    allowed: bool
    requires_confirmation: bool = False


class AllowedActionsResponse(BaseModel):
    actions: list[AllowedActionResponse]


# ── Service status ──────────────────────────────────────────────────────

class ServiceStatusResponse(BaseModel):
    status: str
    engine: str
    model_configured: bool
    knowledge_available: bool
    version: str


# ── Knowledge base (governed content) ───────────────────────────────────

class KbSourceCreate(BaseModel):
    name: str
    source_type: Optional[str] = None
    authority_tier: str = "TIER_3_APPROVED_SECONDARY"
    url: Optional[str] = None


class KbSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: Optional[str] = None
    authority_tier: str
    state: str
    url: Optional[str] = None


class KbItemCreate(BaseModel):
    title: str
    body: str = Field(..., max_length=20000)
    content_type: str = "HOW_TO"
    summary: Optional[str] = None
    jurisdiction_codes: list[str] = Field(default_factory=list)
    language: str = "en"
    authority: str = "TIER_3_APPROVED_SECONDARY"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    next_review_at: Optional[date] = None
    source_id: Optional[int] = None


class KbItemUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    content_type: Optional[str] = None
    summary: Optional[str] = None
    jurisdiction_codes: Optional[list[str]] = None
    language: Optional[str] = None
    authority: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    next_review_at: Optional[date] = None
    state: Optional[str] = None


class KbItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: Optional[int] = None
    organization_id: Optional[int] = None
    content_type: str
    title: str
    body: str
    summary: Optional[str] = None
    language: str
    jurisdiction_codes: list[str] = Field(default_factory=list)
    state: str
    authority: str
    version: int
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    supersedes_item_id: Optional[int] = None
    state_reason: Optional[str] = None
    published_at: Optional[datetime] = None
    next_review_at: Optional[date] = None
    created_at: datetime


class KbPublishRequest(BaseModel):
    reviewer_notes: Optional[str] = None


class KbReasonRequest(BaseModel):
    reason: str = Field(..., max_length=2000)


class KbSupersedeRequest(BaseModel):
    new_item_id: int
    reason: str = Field(..., max_length=2000)


class KbExpirySweepResponse(BaseModel):
    expired: int
    item_ids: list[int] = Field(default_factory=list)


# ── Audit / retention (admin) ───────────────────────────────────────────

class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: Optional[int] = None
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    event_type: str
    payload: Optional[dict[str, Any]] = None
    recorded_at: datetime


class AuditListResponse(BaseModel):
    events: list[AuditEventResponse]
    total: int


class AdminSessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


class RetentionSummaryResponse(BaseModel):
    total_sessions: int
    retention_class_counts: dict[str, int]
    status_counts: dict[str, int]
    expired_sessions: int
    oldest_session_at: Optional[datetime] = None
    retention_policy: str


class RetentionRunResponse(BaseModel):
    archived: int
    scanned: int
    expired_remaining: int


class ModelExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    response_id: Optional[int] = None
    session_id: Optional[int] = None
    organization_id: Optional[int] = None
    model_route: Optional[str] = None
    prompt_version: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    status: str
    error_code: Optional[str] = None
    created_at: datetime


class ModelExecutionListResponse(BaseModel):
    executions: list[ModelExecutionResponse]
    total: int

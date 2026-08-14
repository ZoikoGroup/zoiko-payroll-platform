"""
modules/assist/router.py
------------------------
HTTP endpoints for Zoiko Payroll Assist.

Paths below are relative to this router's prefix ("/assist"). The frontend
calls them under "/api/assist/...", so make sure your app mounts this router
with an "/api" prefix at the top level, e.g.:

    app.include_router(assist_router, prefix="/api")

  Sessions
    POST   /assist/sessions                         → Create an Assist session
    GET    /assist/sessions                         → List my sessions
    GET    /assist/sessions/{session_id}            → Get a session
    PATCH  /assist/sessions/{session_id}            → Update a session
    POST   /assist/sessions/{session_id}/archive    → Archive a session

  Capabilities / suggestions / notices
    GET    /assist/capabilities                     → What Assist can do
    GET    /assist/suggestions                      → Suggested prompts
    GET    /assist/notices/current                  → Current required notice
    POST   /assist/notices/{notice_version}/acknowledge

  Messages
    POST   /assist/sessions/{session_id}/messages   → Submit a message (Idempotency-Key)
    GET    /assist/sessions/{session_id}/messages   → Message history
    GET    /assist/messages/{message_id}            → Single message

  Responses
    GET    /assist/responses/{response_id}          → Response + blocks + sources
    GET    /assist/responses/{response_id}/events
    GET    /assist/responses/{response_id}/status
    POST   /assist/responses/{response_id}/stop
    GET    /assist/responses/{response_id}/sources
    POST   /assist/responses/{response_id}/feedback
    GET    /assist/responses/{response_id}/audit-reference

  Evidence
    GET    /assist/evidence-sets/{evidence_set_id}
    GET    /assist/evidence-items/{evidence_id}

  Drafts
    POST   /assist/drafts
    GET    /assist/drafts/{draft_id}
    PATCH  /assist/drafts/{draft_id}
    DELETE /assist/drafts/{draft_id}

  Handoffs
    POST   /assist/handoff-previews
    GET    /assist/handoff-previews/{preview_id}
    POST   /assist/handoff-previews/{preview_id}/confirm
    POST   /assist/handoff-previews/{preview_id}/cancel
    GET    /assist/handoffs/{handoff_id}

  Controlled actions (A3)
    GET    /assist/actions/allowed
    POST   /assist/action-previews
    GET    /assist/action-previews/{preview_id}
    POST   /assist/action-previews/{preview_id}/confirm
    POST   /assist/action-previews/{preview_id}/cancel
    GET    /assist/action-receipts/{receipt_id}

  Service status
    GET    /assist/status

  Governed knowledge base
    GET    /assist/knowledge/items
    POST   /assist/knowledge/items
    GET    /assist/knowledge/items/{item_id}
    PATCH  /assist/knowledge/items/{item_id}
    POST   /assist/knowledge/items/{item_id}/publish
    POST   /assist/knowledge/items/{item_id}/request-correction
    POST   /assist/knowledge/items/{item_id}/reject
    POST   /assist/knowledge/items/{item_id}/withdraw
    POST   /assist/knowledge/items/{item_id}/quarantine
    POST   /assist/knowledge/items/{item_id}/supersede
    GET    /assist/knowledge/sources
    POST   /assist/knowledge/sources
    POST   /assist/knowledge/sources/{source_id}/quarantine
    POST   /assist/knowledge/sources/{source_id}/reactivate
    POST   /assist/admin/knowledge/expiry-run
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_user, get_current_payroll_operator, get_organization_id
from app.core.exceptions import NotFoundException
from app.modules.assist import service
from app.modules.assist.models import (
    AssistEvidenceItem,
    AssistNoticeAcknowledgment,
)
from app.modules.assist.schemas import (
    ActionConfirmRequest,
    ActionPreviewCreate,
    ActionPreviewResponse,
    ActionReceiptResponse,
    AllowedActionsResponse,
    AuditListResponse,
    AuditReferenceResponse,
    CapabilitiesResponse,
    AdminSessionListResponse,
    DraftCreate,
    DraftListResponse,
    DraftResponse,
    DraftUpdate,
    EvidenceItemResponse,
    EvidenceSetResponse,
    FeedbackCreate,
    HandoffCreateResponse,
    HandoffPreviewCreate,
    HandoffPreviewResponse,
    HandoffResponse,
    KbItemCreate,
    KbItemResponse,
    KbItemUpdate,
    KbExpirySweepResponse,
    KbPublishRequest,
    KbReasonRequest,
    KbSourceCreate,
    KbSourceResponse,
    KbSupersedeRequest,
    MessageListResponse,
    MessageResponse,
    MessageSubmitRequest,
    MessageSubmitResponse,
    ModelExecutionListResponse,
    NoticeAckResponse,
    NoticeResponse,
    ResponseEventsResponse,
    ResponseResponse,
    ResponseStatusResponse,
    RetentionRunResponse,
    RetentionSummaryResponse,
    ServiceStatusResponse,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    SessionUpdate,
    SourcesResponse,
    StopResponse,
    SuggestionsResponse,
    SuccessResponse,
)

assist_router = APIRouter(
    prefix="/assist",
    tags=["Assist"],
)


# ── Serialization helpers ───────────────────────────────────────────────

def _source_ref(item) -> dict:
    return {
        "evidence_id": item.id,
        "source_type": item.source_type,
        "title": item.title,
        "effective_at": item.effective_at,
        "freshness_state": item.freshness_state,
        "authority": item.authority,
        "access_uri": item.access_uri,
    }


def _response_payload(db: Session, response) -> dict:
    blocks = [
        {
            "block_type": block.block_type,
            "content": block.content,
            "sequence": block.sequence,
            "data": block.data,
        }
        for block in sorted(response.blocks, key=lambda b: b.sequence)
    ]
    sources = []
    if response.evidence_set_id:
        items = (
            db.query(AssistEvidenceItem)
            .filter(AssistEvidenceItem.evidence_set_id == response.evidence_set_id)
            .all()
        )
        sources = [_source_ref(item) for item in items]
    return {
        "id": response.id,
        "session_id": response.session_id,
        "message_id": response.message_id,
        "state": response.state,
        "intent_id": response.intent_id,
        "risk_tier": response.risk_tier,
        "engine": response.engine,
        "model_route": response.model_route,
        "prompt_version": response.prompt_version,
        "evidence_set_id": response.evidence_set_id,
        "safety_state": response.safety_state,
        "error_code": response.error_code,
        "created_at": response.created_at,
        "completed_at": response.completed_at,
        "blocks": blocks,
        "sources": sources,
    }


def _handoff_preview_payload(preview) -> dict:
    return {
        "preview_id": preview.id,
        "destination": preview.destination,
        "reason_code": preview.reason_code,
        "summary": preview.summary,
        "included_evidence_ids": preview.evidence_ids or [],
        "excluded_data_classes": preview.excluded_data_classes or [],
        "state": preview.state,
        "created_at": preview.created_at,
        "expires_at": preview.expires_at,
    }


def _action_preview_payload(preview) -> dict:
    return {
        "preview_id": preview.id,
        "risk_tier": preview.risk_tier,
        "state": preview.state,
        "action_id": preview.action_id,
        "target": {
            "type": preview.target_type,
            "id": preview.target_id,
            "version": preview.target_version,
        },
        "before": preview.before_data,
        "after": preview.after_data,
        "confirmation": {
            "label": preview.confirmation_label or "Confirm action",
            "step_up_required": bool(preview.step_up_required),
        },
        "expires_at": preview.expires_at,
        "etag": f'"{preview.id}-v{preview.target_version or 1}"',
    }


def _receipt_payload(receipt) -> dict:
    return {
        "receipt_id": receipt.id,
        "outcome": receipt.outcome,
        "action_id": receipt.action_id,
        "target": {
            "type": receipt.target_type,
            "id": receipt.target_id,
            "version": receipt.target_version,
        },
        "committed_at": receipt.committed_at.isoformat() if receipt.committed_at else datetime.now().isoformat(),
        "audit_id": receipt.audit_id,
    }


# ── Sessions ────────────────────────────────────────────────────────────

@assist_router.post(
    "/sessions", response_model=SessionResponse, summary="Create an Assist session"
)
def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.create_session(db, current_user, org_id, payload.model_dump())


@assist_router.get(
    "/sessions", response_model=SessionListResponse, summary="List my Assist sessions"
)
def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    sessions, total = service.list_sessions(db, org_id, current_user, skip, limit, status)
    return {"sessions": sessions, "total": total}


@assist_router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Get an Assist session",
)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_session(db, org_id, current_user, session_id)


@assist_router.patch(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Update an Assist session",
)
def update_session(
    session_id: int,
    payload: SessionUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.update_session(db, org_id, current_user, session_id, payload.model_dump(exclude_unset=True))


@assist_router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionResponse,
    summary="Archive an Assist session",
)
def archive_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.archive_session(db, org_id, current_user, session_id)


# ── Capabilities / suggestions / notices ───────────────────────────────

@assist_router.get(
    "/capabilities", response_model=CapabilitiesResponse, summary="List Assist capabilities"
)
def list_capabilities(db: Session = Depends(get_db)):
    return {"capabilities": service.list_capabilities(db)}


@assist_router.get(
    "/suggestions", response_model=SuggestionsResponse, summary="List suggested prompts"
)
def list_suggestions(db: Session = Depends(get_db)):
    return {"suggestions": service.list_suggestions(db)}


@assist_router.get(
    "/notices/current", response_model=NoticeResponse, summary="Get the current Assist notice"
)
def get_current_notice(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    notice = service.get_current_notice(db, org_id, current_user)
    if notice is None:
        raise NotFoundException("Assist notice", "current")
    acknowledged = (
        db.query(AssistNoticeAcknowledgment)
        .filter(
            AssistNoticeAcknowledgment.organization_id == org_id,
            AssistNoticeAcknowledgment.user_id == current_user.id,
            AssistNoticeAcknowledgment.notice_version == notice.notice_version,
        )
        .first()
        is not None
    )
    return {
        "notice_version": notice.notice_version,
        "title": notice.title,
        "content": notice.content,
        "required": bool(notice.required),
        "effective_from": notice.effective_from,
        "acknowledged": acknowledged,
    }


@assist_router.post(
    "/notices/{notice_version}/acknowledge",
    response_model=NoticeAckResponse,
    summary="Acknowledge the current Assist notice",
)
def acknowledge_notice(
    notice_version: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    ack = service.acknowledge_notice(db, org_id, current_user, notice_version)
    return {
        "notice_version": notice_version,
        "acknowledged": True,
        "acknowledged_at": ack.acknowledged_at,
    }


# ── Messages ────────────────────────────────────────────────────────────

@assist_router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageSubmitResponse,
    summary="Submit a message to an Assist session",
)
def submit_message(
    session_id: int,
    payload: MessageSubmitRequest,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    session = service.get_session(db, org_id, current_user, session_id)
    return service.submit_message(
        db, org_id, current_user, session, payload.model_dump(), idempotency_key=idempotency_key
    )


@assist_router.get(
    "/sessions/{session_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in an Assist session",
)
def list_messages(
    session_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    messages, total = service.list_messages(db, org_id, current_user, session_id, skip, limit)
    return {"messages": messages, "total": total}


@assist_router.get(
    "/messages/{message_id}", response_model=MessageResponse, summary="Get a single message"
)
def get_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_message(db, org_id, current_user, message_id)


# ── Responses ───────────────────────────────────────────────────────────

@assist_router.get(
    "/responses/{response_id}",
    response_model=ResponseResponse,
    summary="Get an Assist response with blocks and sources",
)
def get_response(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    response = service.get_response(db, org_id, current_user, response_id)
    return _response_payload(db, response)


@assist_router.get(
    "/responses/{response_id}/events",
    response_model=ResponseEventsResponse,
    summary="Get response generation events",
)
def get_response_events(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    response = service.get_response(db, org_id, current_user, response_id)
    return {
        "response_id": response_id,
        "state": response.state,
        "events": service.get_response_events(db, org_id, current_user, response_id),
    }


@assist_router.get(
    "/responses/{response_id}/events/stream",
    summary="Stream response generation events (Server-Sent Events)",
)
def stream_response_events(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    events = service.get_response_events(db, org_id, current_user, response_id)

    def _generator():
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@assist_router.get(
    "/responses/{response_id}/status",
    response_model=ResponseStatusResponse,
    summary="Get response generation status",
)
def get_response_status(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_response_status(db, org_id, current_user, response_id)


@assist_router.post(
    "/responses/{response_id}/stop",
    response_model=StopResponse,
    summary="Stop an in-flight response",
)
def stop_response(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    response = service.stop_response(db, org_id, current_user, response_id)
    return {"response_id": response.id, "state": response.state}


@assist_router.get(
    "/responses/{response_id}/sources",
    response_model=SourcesResponse,
    summary="List sources cited by a response",
)
def get_response_sources(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    items = service.get_response_sources(db, org_id, current_user, response_id)
    return {"response_id": response_id, "sources": [_source_ref(item) for item in items]}


@assist_router.post(
    "/responses/{response_id}/feedback",
    response_model=SuccessResponse,
    summary="Submit feedback for a response",
)
def submit_feedback(
    response_id: int,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    service.submit_feedback(db, org_id, current_user, response_id, payload.model_dump())
    return {"message": "Feedback recorded.", "success": True}


@assist_router.get(
    "/responses/{response_id}/audit-reference",
    response_model=AuditReferenceResponse,
    summary="Get the audit reference for a response",
)
def get_audit_reference(
    response_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_audit_reference(db, org_id, current_user, response_id)


# ── Evidence ────────────────────────────────────────────────────────────

@assist_router.get(
    "/evidence-sets/{evidence_set_id}",
    response_model=EvidenceSetResponse,
    summary="Get an evidence set",
)
def get_evidence_set(
    evidence_set_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    evidence_set = service.get_evidence_set(db, org_id, current_user, evidence_set_id)
    items = (
        db.query(AssistEvidenceItem)
        .filter(AssistEvidenceItem.evidence_set_id == evidence_set.id)
        .all()
    )
    return {
        "evidence_set_id": evidence_set.id,
        "scope": {
            "entity_count": evidence_set.entity_count,
            "jurisdiction_codes": [],
        },
        "confidence": {
            "state": evidence_set.confidence_state,
            "reason_codes": evidence_set.reason_codes or [],
        },
        "freshness": {
            "state": evidence_set.freshness_state,
            "evaluated_at": evidence_set.freshness_evaluated_at,
        },
        "conflict": {"state": evidence_set.conflict_state},
        "sources": [_source_ref(item) for item in items],
    }


@assist_router.get(
    "/evidence-items/{evidence_id}",
    response_model=EvidenceItemResponse,
    summary="Get a single evidence item",
)
def get_evidence_item(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    item = service.get_evidence_item(db, org_id, current_user, evidence_id)
    return {
        "evidence_id": item.id,
        "source_type": item.source_type,
        "title": item.title,
        "effective_at": item.effective_at,
        "freshness_state": item.freshness_state,
        "authority": item.authority,
        "access_uri": item.access_uri,
        "extra": item.extra,
    }


# ── Drafts ──────────────────────────────────────────────────────────────

@assist_router.post("/drafts", response_model=DraftResponse, summary="Create a draft")
def create_draft(
    payload: DraftCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.create_draft(db, org_id, current_user, payload.model_dump())


@assist_router.get("/drafts", response_model=DraftListResponse, summary="List my drafts")
def list_drafts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    state: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    drafts, total = service.list_drafts(db, org_id, current_user, skip, limit, state=state)
    return {"drafts": drafts, "total": total}


@assist_router.get(
    "/drafts/{draft_id}", response_model=DraftResponse, summary="Get a draft"
)
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_draft(db, org_id, current_user, draft_id)


@assist_router.patch(
    "/drafts/{draft_id}", response_model=DraftResponse, summary="Update a draft"
)
def update_draft(
    draft_id: int,
    payload: DraftUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.update_draft(db, org_id, current_user, draft_id, payload.model_dump(exclude_unset=True))


@assist_router.delete(
    "/drafts/{draft_id}",
    response_model=SuccessResponse,
    summary="Delete a draft",
)
def delete_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    service.delete_draft(db, org_id, current_user, draft_id)
    return {"message": "Draft deleted.", "success": True}


# ── Handoffs ────────────────────────────────────────────────────────────

@assist_router.post(
    "/handoff-previews",
    response_model=HandoffPreviewResponse,
    summary="Create a handoff preview",
)
def create_handoff_preview(
    payload: HandoffPreviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    service_payload = payload.model_dump()
    service_payload["source_session_id"] = payload.source_response_id
    return _handoff_preview_payload(service.create_handoff_preview(db, org_id, current_user, service_payload))


@assist_router.get(
    "/handoff-previews/{preview_id}",
    response_model=HandoffPreviewResponse,
    summary="Get a handoff preview",
)
def get_handoff_preview(
    preview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return _handoff_preview_payload(service.get_handoff_preview(db, org_id, current_user, preview_id))


@assist_router.post(
    "/handoff-previews/{preview_id}/confirm",
    response_model=HandoffCreateResponse,
    summary="Confirm a handoff preview",
)
def confirm_handoff(
    preview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    handoff = service.confirm_handoff(db, org_id, current_user, preview_id)
    return {
        "handoff_id": handoff.id,
        "case_id": handoff.case_id,
        "destination": handoff.destination,
        "reason_code": handoff.reason_code,
        "state": handoff.state,
        "assigned_owner": None,
        "sla_reference": handoff.sla_reference,
        "audit_id": handoff.audit_id,
        "created_at": handoff.created_at,
    }


@assist_router.post(
    "/handoff-previews/{preview_id}/cancel",
    response_model=HandoffPreviewResponse,
    summary="Cancel a handoff preview",
)
def cancel_handoff(
    preview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return _handoff_preview_payload(service.cancel_handoff(db, org_id, current_user, preview_id))


@assist_router.get(
    "/handoffs/{handoff_id}", response_model=HandoffResponse, summary="Get a handoff"
)
def get_handoff(
    handoff_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return service.get_handoff(db, org_id, current_user, handoff_id)


# ── Controlled actions (A3) ─────────────────────────────────────────────

@assist_router.get(
    "/actions/allowed",
    response_model=AllowedActionsResponse,
    summary="List actions Assist is allowed to perform",
)
def get_allowed_actions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return {"actions": service.get_allowed_actions(db, org_id, current_user)}


@assist_router.post(
    "/action-previews",
    response_model=ActionPreviewResponse,
    summary="Preview a controlled action before execution",
)
def create_action_preview(
    payload: ActionPreviewCreate,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    service_payload = payload.model_dump()
    service_payload["source_session_id"] = payload.source_response_id
    return service.create_action_preview(db, org_id, current_user, service_payload, idempotency_key=idempotency_key)


@assist_router.get(
    "/action-previews/{preview_id}",
    response_model=ActionPreviewResponse,
    summary="Get an action preview",
)
def get_action_preview(
    preview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return _action_preview_payload(service.get_action_preview(db, org_id, current_user, preview_id))


@assist_router.post(
    "/action-previews/{preview_id}/confirm",
    response_model=ActionReceiptResponse,
    summary="Confirm and execute a controlled action",
)
def confirm_action(
    preview_id: int,
    payload: ActionConfirmRequest = None,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    if_match: str = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    body = payload.model_dump() if payload else {}
    return service.confirm_action(
        db, org_id, current_user, preview_id, body, idempotency_key=idempotency_key, if_match=if_match
    )


@assist_router.post(
    "/action-previews/{preview_id}/cancel",
    response_model=ActionPreviewResponse,
    summary="Cancel an action preview",
)
def cancel_action(
    preview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return _action_preview_payload(service.cancel_action(db, org_id, current_user, preview_id))


@assist_router.get(
    "/action-receipts/{receipt_id}",
    response_model=ActionReceiptResponse,
    summary="Get an action receipt",
)
def get_action_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    org_id: int = Depends(get_organization_id),
):
    return _receipt_payload(service.get_action_receipt(db, org_id, current_user, receipt_id))


# ── Service status ──────────────────────────────────────────────────────

@assist_router.get(
    "/status", response_model=ServiceStatusResponse, summary="Assist service status"
)
def get_status(db: Session = Depends(get_db)):
    return service.get_status(db)


# ── Governed knowledge base ─────────────────────────────────────────────

@assist_router.get(
    "/knowledge/items",
    response_model=list[KbItemResponse],
    summary="List knowledge base items",
)
def list_kb_items(
    state: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.list_kb_items(db, org_id, state=state)


@assist_router.post(
    "/knowledge/items", response_model=KbItemResponse, summary="Create a knowledge item"
)
def create_kb_item(
    payload: KbItemCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.create_kb_item(db, org_id, current_user, payload.model_dump(), tenant=True)


@assist_router.get(
    "/knowledge/items/{item_id}",
    response_model=KbItemResponse,
    summary="Get a knowledge item",
)
def get_kb_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.get_kb_item(db, org_id, item_id)


@assist_router.patch(
    "/knowledge/items/{item_id}",
    response_model=KbItemResponse,
    summary="Update a knowledge item",
)
def update_kb_item(
    item_id: int,
    payload: KbItemUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.update_kb_item(db, org_id, current_user, item_id, payload.model_dump(exclude_unset=True))


@assist_router.post(
    "/knowledge/items/{item_id}/publish",
    response_model=KbItemResponse,
    summary="Publish an approved knowledge item",
)
def publish_kb_item(
    item_id: int,
    payload: KbPublishRequest = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    body = payload.model_dump() if payload else {}
    return service.publish_kb_item(db, org_id, current_user, item_id, body)


@assist_router.post(
    "/knowledge/items/{item_id}/request-correction",
    response_model=KbItemResponse,
    summary="Send a knowledge item back to its author for correction",
)
def request_kb_correction(
    item_id: int,
    payload: KbReasonRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.request_kb_correction(db, org_id, current_user, item_id, payload.reason)


@assist_router.post(
    "/knowledge/items/{item_id}/reject",
    response_model=KbItemResponse,
    summary="Reject a knowledge item",
)
def reject_kb_item(
    item_id: int,
    payload: KbReasonRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.reject_kb_item(db, org_id, current_user, item_id, payload.reason)


@assist_router.post(
    "/knowledge/items/{item_id}/withdraw",
    response_model=KbItemResponse,
    summary="Withdraw a published knowledge item",
)
def withdraw_kb_item(
    item_id: int,
    payload: KbReasonRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.withdraw_kb_item(db, org_id, current_user, item_id, payload.reason)


@assist_router.post(
    "/knowledge/items/{item_id}/quarantine",
    response_model=KbItemResponse,
    summary="Quarantine a knowledge item (incident kill switch)",
)
def quarantine_kb_item(
    item_id: int,
    payload: KbReasonRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.quarantine_kb_item(db, org_id, current_user, item_id, payload.reason)


@assist_router.post(
    "/knowledge/items/{item_id}/supersede",
    response_model=KbItemResponse,
    summary="Mark a knowledge item as superseded by a successor item",
)
def supersede_kb_item(
    item_id: int,
    payload: KbSupersedeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.supersede_kb_item(db, org_id, current_user, item_id, payload.new_item_id, payload.reason)


@assist_router.get(
    "/knowledge/sources",
    response_model=list[KbSourceResponse],
    summary="List knowledge base sources",
)
def list_kb_sources(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.list_kb_sources(db)


@assist_router.post(
    "/knowledge/sources",
    response_model=KbSourceResponse,
    summary="Create a knowledge base source",
)
def create_kb_source(
    payload: KbSourceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.create_kb_source(db, payload.model_dump())


@assist_router.post(
    "/knowledge/sources/{source_id}/quarantine",
    response_model=KbSourceResponse,
    summary="Quarantine a knowledge source (cascades to its items)",
)
def quarantine_kb_source(
    source_id: int,
    payload: KbReasonRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.quarantine_kb_source(db, org_id, current_user, source_id, payload.reason)


@assist_router.post(
    "/knowledge/sources/{source_id}/reactivate",
    response_model=KbSourceResponse,
    summary="Reactivate a quarantined knowledge source",
)
def reactivate_kb_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.reactivate_kb_source(db, org_id, current_user, source_id)


# ── Audit / retention (admin) ───────────────────────────────────────────

@assist_router.get(
    "/admin/audit-events",
    response_model=AuditListResponse,
    summary="List organization audit events",
)
def list_audit_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: str = Query(None),
    session_id: int = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    events, total = service.list_audit_events(db, org_id, skip, limit, event_type=event_type, session_id=session_id)
    return {"events": events, "total": total}


@assist_router.get(
    "/admin/sessions",
    response_model=AdminSessionListResponse,
    summary="List all organization sessions",
)
def list_admin_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    sessions, total = service.list_admin_sessions(db, org_id, skip, limit, status=status)
    return {"sessions": sessions, "total": total}


@assist_router.get(
    "/admin/retention",
    response_model=RetentionSummaryResponse,
    summary="Get retention summary",
)
def get_retention_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.get_retention_summary(db, org_id)


@assist_router.post(
    "/admin/retention/run",
    response_model=RetentionRunResponse,
    summary="Run retention cleanup (archive expired sessions)",
)
def run_retention_cleanup(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.run_retention_cleanup(db, org_id, current_user)


@assist_router.post(
    "/admin/knowledge/expiry-run",
    response_model=KbExpirySweepResponse,
    summary="Run KB expiry sweep (move past-effective_to items to EXPIRED)",
)
def run_kb_expiry_sweep(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    return service.run_kb_expiry_sweep(db, org_id)


@assist_router.get(
    "/admin/model-executions",
    response_model=ModelExecutionListResponse,
    summary="List model execution records",
)
def list_model_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    response_id: int = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
    org_id: int = Depends(get_organization_id),
):
    rows, total = service.list_model_executions(db, org_id, skip, limit, response_id=response_id)
    return {"executions": rows, "total": total}

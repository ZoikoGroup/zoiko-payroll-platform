"""
modules/assist/service.py
-------------------------
Orchestration layer for Zoiko Payroll Assist.

Submit-message flow:
  validate session/notice → persist user message → classify intent → policy
  decision → gather evidence (read tools + governed knowledge) → build
  evidence set → generate grounded structured answer (deterministic or LLM)
  → validate with guardrails → persist response + blocks → audit.

A3 actions use a preview → confirm lifecycle; no A4/A5 tool is registered.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException, ZoikoException
from app.modules.assist import gateway, guardrails, intents, knowledge as knowledge_module
from app.modules.assist.models import (
    AssistActionConfirmation,
    AssistActionPreview,
    AssistActionReceipt,
    AssistAuditEvent,
    AssistCapability,
    AssistDraft,
    AssistEvidenceItem,
    AssistEvidenceSet,
    AssistFeedback,
    AssistHandoff,
    AssistHandoffPreview,
    AssistIdempotencyRecord,
    AssistIntentDecision,
    AssistKbItem,
    AssistKbSource,
    AssistMessage,
    AssistModelExecution,
    AssistNotice,
    AssistNoticeAcknowledgment,
    AssistPolicyDecision,
    AssistResponse,
    AssistResponseBlock,
    AssistSession,
    AssistSuggestion,
    AssistSessionState,
    KnowledgeSourceState,
    KnowledgeState,
)
from app.core.dependencies import role_value
from app.modules.assist.tools import get_action_tool, get_live_target_version, invoke_read_tool

logger = logging.getLogger("zoiko_payroll.assist.service")

DEFAULT_ACTION_PREVIEW_MINUTES = 10
DEFAULT_HANDOFF_PREVIEW_MINUTES = 15

# Read tools resolvable purely from an intent's tool_id (run-wide + employee
# self-service). Kept as one set so both evidence-gathering call sites agree
# on what's routable, and so adding a tool only means updating this list.
KNOWN_READ_TOOL_IDS = {
    "payroll.getRunSummary",
    "payroll.getRunReadiness",
    "payroll.listExceptions",
    "payroll.getApprovalStatus",
    "payroll.comparePeriods",
    "payroll.getMyProfile",
    "payroll.getMyPayslips",
    "payroll.getEmployeeCount",
    "payroll.getActiveRunCount",
}


# ── Datetime helpers ────────────────────────────────────────────────────
# Postgres (DateTime(timezone=True)) returns tz-aware datetimes on read;
# SQLite (used in tests) silently drops tzinfo on round-trip and returns
# naive ones. Comparing a fetched value against a hardcoded naive-or-aware
# "now" therefore breaks on one dialect or the other — normalize whatever
# comes back from the DB to UTC-aware before comparing.

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ── Platform-wide incident kill-switch ──────────────────────────────────
# One flag for the whole platform (PlatformSetting.key is globally unique,
# not per-org), so this is deliberately a Super Admin action, not something
# an individual org can flip for themselves.

_KILL_SWITCH_KEY = "assist_kill_switch_enabled"


def is_assist_kill_switch_enabled(db: Session) -> bool:
    from app.modules.super_admin.models import PlatformSetting

    row = db.query(PlatformSetting).filter(PlatformSetting.key == _KILL_SWITCH_KEY).first()
    if row is None or row.value is None:
        return settings.ASSIST_KILL_SWITCH_ENABLED
    return str(row.value).strip().lower() in ("1", "true", "yes")


def set_assist_kill_switch(db: Session, enabled: bool, user) -> bool:
    from app.modules.super_admin.models import PlatformSetting

    row = db.query(PlatformSetting).filter(PlatformSetting.key == _KILL_SWITCH_KEY).first()
    if row is None:
        row = PlatformSetting(
            key=_KILL_SWITCH_KEY,
            description="Platform-wide incident kill-switch for Zoiko Payroll Assist.",
        )
        db.add(row)
    row.value = "true" if enabled else "false"
    db.commit()
    # AssistAuditEvent.organization_id is NOT NULL and this action isn't
    # scoped to any one org, so it can't go through the usual per-org _audit
    # helper — a platform-level action gets a platform-level (plain) log line.
    logger.info("[assist] Kill switch %s by user_id=%s", "ENABLED" if enabled else "DISABLED", user.id if user else None)
    return enabled


def require_assist_enabled(db: Session) -> None:
    if is_assist_kill_switch_enabled(db):
        raise ZoikoException(
            503,
            "ASSIST_DISABLED",
            "Zoiko Payroll Assist is temporarily disabled. Please try again later or contact support.",
        )


# ── ID helpers ──────────────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _request_hash(payload) -> str:
    import json

    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _audit(db: Session, org_id, user, session_id, event_type, payload=None):
    event = AssistAuditEvent(
        organization_id=org_id,
        user_id=user.id if user else None,
        session_id=session_id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    db.flush()
    return event


def _idempotent(db, org_id, scope, key, request_body, result_builder):
    """Return (result, reused) honoring an Idempotency-Key header."""
    if not key:
        return result_builder(), False
    record = (
        db.query(AssistIdempotencyRecord)
        .filter(
            AssistIdempotencyRecord.organization_id == org_id,
            AssistIdempotencyRecord.scope == scope,
            AssistIdempotencyRecord.idempotency_key == key,
        )
        .first()
    )
    current_hash = _request_hash(request_body)
    if record:
        if record.request_hash != current_hash:
            raise BadRequestException("Idempotency-Key was reused with a different request body.")
        return record.response_body, True
    result = result_builder()
    db.add(
        AssistIdempotencyRecord(
            organization_id=org_id,
            scope=scope,
            idempotency_key=key,
            request_hash=current_hash,
            response_body=result,
        )
    )
    db.commit()
    return result, False


# ── Sessions ────────────────────────────────────────────────────────────

def create_session(db, user, org_id, payload: dict) -> AssistSession:
    require_assist_enabled(db)
    context = payload.get("context") or {}
    obj = context.get("object") or {}
    session = AssistSession(
        organization_id=org_id,
        user_id=user.id,
        channel=payload.get("channel", "WEB"),
        locale=payload.get("locale", "en"),
        time_zone=payload.get("time_zone", "UTC"),
        status=AssistSessionState.ACTIVE.value,
        context_object_type=obj.get("type") if obj else None,
        context_object_id=str(obj.get("id")) if obj and obj.get("id") is not None else None,
        context_object_version=obj.get("version") if obj else None,
        jurisdiction_codes=context.get("jurisdiction_codes") or [],
        title=payload.get("title"),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    _audit(db, org_id, user, session.id, "assist.session_created", {"session_id": session.id})
    db.commit()
    return session


def list_sessions(db, org_id, user, skip, limit, status=None):
    query = db.query(AssistSession).filter(AssistSession.organization_id == org_id, AssistSession.user_id == user.id)
    if status:
        query = query.filter(AssistSession.status == status)
    total = query.count()
    sessions = query.order_by(AssistSession.created_at.desc()).offset(skip).limit(limit).all()
    return sessions, total


def get_session(db, org_id, user, session_id) -> AssistSession:
    session = (
        db.query(AssistSession)
        .filter(AssistSession.id == session_id, AssistSession.organization_id == org_id)
        .first()
    )
    if session is None:
        raise NotFoundException("Assist session", session_id)
    if session.user_id != user.id:
        raise ForbiddenException("You can only access your own Assist sessions.")
    return session


def update_session(db, org_id, user, session_id, payload: dict) -> AssistSession:
    session = get_session(db, org_id, user, session_id)
    if session.status == AssistSessionState.ARCHIVED.value:
        raise BadRequestException("Cannot update an archived session.")
    if "title" in payload:
        session.title = payload["title"]
    if "case_link" in payload:
        session.case_link = payload["case_link"]
    if payload.get("context"):
        obj = payload["context"].get("object") or {}
        session.context_object_type = obj.get("type") if obj else None
        session.context_object_id = str(obj.get("id")) if obj and obj.get("id") is not None else None
        session.context_object_version = obj.get("version") if obj else None
        session.jurisdiction_codes = payload["context"].get("jurisdiction_codes") or session.jurisdiction_codes
    db.commit()
    db.refresh(session)
    return session


def archive_session(db, org_id, user, session_id) -> AssistSession:
    session = get_session(db, org_id, user, session_id)
    session.status = AssistSessionState.ARCHIVED.value
    session.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


# ── Capabilities / suggestions / notices ───────────────────────────────

def list_capabilities(db) -> list[AssistCapability]:
    return db.query(AssistCapability).order_by(AssistCapability.order_index).all()


def list_suggestions(db) -> list[AssistSuggestion]:
    return db.query(AssistSuggestion).filter(AssistSuggestion.enabled == 1).order_by(AssistSuggestion.position).all()


def get_current_notice(db, org_id, user) -> AssistNotice | None:
    now = datetime.now(timezone.utc)
    notice = (
        db.query(AssistNotice)
        .filter(
            AssistNotice.effective_from <= now,
            (AssistNotice.effective_to.is_(None)) | (AssistNotice.effective_to >= now),
        )
        .order_by(AssistNotice.effective_from.desc())
        .first()
    )
    return notice


def acknowledge_notice(db, org_id, user, notice_version) -> AssistNoticeAcknowledgment:
    notice = db.query(AssistNotice).filter(AssistNotice.notice_version == notice_version).first()
    if notice is None:
        raise NotFoundException("Assist notice", notice_version)
    ack = (
        db.query(AssistNoticeAcknowledgment)
        .filter(
            AssistNoticeAcknowledgment.organization_id == org_id,
            AssistNoticeAcknowledgment.user_id == user.id,
            AssistNoticeAcknowledgment.notice_version == notice_version,
        )
        .first()
    )
    if ack is None:
        ack = AssistNoticeAcknowledgment(
            organization_id=org_id,
            user_id=user.id,
            notice_version=notice_version,
        )
        db.add(ack)
        db.commit()
        db.refresh(ack)
    return ack


def _notice_completed(db, org_id, user) -> bool:
    notice = get_current_notice(db, org_id, user)
    if notice is None or not notice.required:
        return True
    ack = (
        db.query(AssistNoticeAcknowledgment)
        .filter(
            AssistNoticeAcknowledgment.organization_id == org_id,
            AssistNoticeAcknowledgment.user_id == user.id,
            AssistNoticeAcknowledgment.notice_version == notice.notice_version,
        )
        .first()
    )
    return ack is not None


# ── Messages / responses ────────────────────────────────────────────────

def _resolve_run_id(context) -> int | None:
    if not context:
        return None
    obj = context.get("object") or {}
    if obj.get("type") == "PAYROLL_RUN" and obj.get("id") is not None:
        try:
            return int(obj["id"])
        except (TypeError, ValueError):
            return None
    return None


def submit_message(db, org_id, user, session, payload: dict, idempotency_key: str = None) -> dict:
    require_assist_enabled(db)
    context = payload.get("context") or {}
    content = payload.get("content") or {}
    text = content.get("text", "").strip()
    if not text:
        raise BadRequestException("Message text is required.")

    if session.status != AssistSessionState.ACTIVE.value:
        raise BadRequestException("This session cannot accept messages.")

    if not _notice_completed(db, org_id, user):
        from app.core.exceptions import ZoikoException

        raise ZoikoException(403, "NOTICE_REQUIRED", "Required notice not completed. Please acknowledge the current notice first.")

    def _build():
        message = AssistMessage(
            session_id=session.id,
            organization_id=org_id,
            role="user",
            content=text,
            content_hash=_content_hash(text),
        )
        db.add(message)
        db.flush()

        decision = intents.classify_intent(text)
        intent_decision = AssistIntentDecision(
            session_id=session.id,
            message_id=message.id,
            organization_id=org_id,
            intent_id=decision["intent_id"],
            risk_tier=decision["risk_tier"],
            confidence=decision["confidence"],
            method=decision["method"],
        )
        db.add(intent_decision)

        policy = AssistPolicyDecision(
            session_id=session.id,
            organization_id=org_id,
            resource_kind=f"intent:{decision['intent_id']}",
            decision="deny" if decision.get("blocked") else "allow",
            reason_code="PROHIBITED_ACT" if decision.get("blocked") else None,
            policy_version=settings.ASSIST_POLICY_VERSION,
        )
        db.add(policy)
        # Neither row's id is read before commit — deferring their flush lets
        # them ride along with evidence_set's own (required) flush just below
        # instead of paying for two extra network round-trips to the DB.

        evidence_set, tool_result = _build_evidence_set(
            db, org_id, session, decision, context, message.id, user, text
        )
        response = _build_response(
            db, org_id, user, session, message, decision, evidence_set, text, context, tool_result
        )
        db.commit()

        result = {
            "message_id": message.id,
            "response_id": response.id,
            "state": response.state,
            "events_uri": f"/api/assist/responses/{response.id}/events",
            "created_at": message.created_at.isoformat() if message.created_at else datetime.now().isoformat(),
        }
        return result

    return _idempotent(db, org_id, "messages", idempotency_key, payload, _build)[0]


def _build_evidence_set(db, org_id, session, decision, context, message_id, user, text):
    evidence_set = AssistEvidenceSet(
        organization_id=org_id,
        session_id=session.id,
        confidence_state="MEDIUM",
        reason_codes=[],
        freshness_state="CURRENT",
        freshness_evaluated_at=datetime.now(),
        conflict_state="NONE",
    )
    db.add(evidence_set)
    db.flush()

    if decision["intent_id"] in intents.SMALLTALK_INTENT_IDS:
        # Small talk needs no evidence — skip the KB search entirely so a
        # bare "hi" or "thank you" never drags in unrelated knowledge
        # articles as sources.
        evidence_set.confidence_state = "UNAVAILABLE"
        return evidence_set, None

    tool_id = decision.get("tool_id")
    run_id = _resolve_run_id(context) or _resolve_run_id({"object": {"type": "PAYROLL_RUN", "id": session.context_object_id}})

    tool_result = None
    if tool_id and tool_id in KNOWN_READ_TOOL_IDS:
        tool_result = invoke_read_tool(db, org_id, tool_id, run_id=run_id, context_object=context.get("object"), user=user, text=text)
    elif decision["intent_id"] in ("find.object", "explain.status") and run_id:
        tool_result = invoke_read_tool(db, org_id, "payroll.getRunSummary", run_id=run_id, context_object=context.get("object"), user=user, text=text)

    tool_found = bool(tool_result and tool_result.get("found"))
    if tool_found:
        run = tool_result.get("run")
        if run:
            db.add(
                AssistEvidenceItem(
                    evidence_set_id=evidence_set.id,
                    source_type="PAYROLL_RUN",
                    source_id=str(run.get("run_id")),
                    title=f"{run.get('period')} payroll run",
                    effective_at=datetime.now().date(),
                    freshness_state="CURRENT",
                    authority="TIER_1_OPERATIONAL",
                )
            )
            evidence_set.entity_count += 1
        elif "profile" in tool_result:
            db.add(
                AssistEvidenceItem(
                    evidence_set_id=evidence_set.id,
                    source_type="EMPLOYEE_PROFILE",
                    title="Your payroll profile",
                    effective_at=datetime.now().date(),
                    freshness_state="CURRENT",
                    authority="TIER_1_OPERATIONAL",
                )
            )
            evidence_set.entity_count += 1
        elif "payslips" in tool_result:
            db.add(
                AssistEvidenceItem(
                    evidence_set_id=evidence_set.id,
                    source_type="PAYSLIP",
                    title="Your payslips",
                    effective_at=datetime.now().date(),
                    freshness_state="CURRENT",
                    authority="TIER_1_OPERATIONAL",
                )
            )
            evidence_set.entity_count += 1
        elif "total_employees" in tool_result:
            db.add(
                AssistEvidenceItem(
                    evidence_set_id=evidence_set.id,
                    source_type="EMPLOYEE_ROSTER",
                    title="Organization employee roster",
                    effective_at=datetime.now().date(),
                    freshness_state="CURRENT",
                    authority="TIER_1_OPERATIONAL",
                )
            )
            evidence_set.entity_count += 1
        elif "active_runs" in tool_result:
            db.add(
                AssistEvidenceItem(
                    evidence_set_id=evidence_set.id,
                    source_type="PAYROLL_RUN_LIST",
                    title="Organization payroll runs",
                    effective_at=datetime.now().date(),
                    freshness_state="CURRENT",
                    authority="TIER_1_OPERATIONAL",
                )
            )
            evidence_set.entity_count += 1

    jurisdiction_codes = context.get("jurisdiction_codes") or session.jurisdiction_codes or []

    # A jurisdiction named in the message but not one of the org's assigned
    # tax jurisdictions gets its own fallback (KB-GOV unsupported-jurisdiction
    # handling) instead of whatever a generic lexical KB search happens to
    # rank highest — substituting a neighboring/unrelated jurisdiction's
    # guidance would be worse than admitting no coverage.
    unsupported_country = None
    if tool_result is None and decision["intent_id"] in ("explain.field", "kb.answer"):
        mentioned_country = knowledge_module.find_mentioned_country(text)
        if mentioned_country and not knowledge_module.is_jurisdiction_supported(db, org_id, mentioned_country):
            unsupported_country = mentioned_country

    kb_candidates = (
        []
        if unsupported_country
        else knowledge_module.search_kb(db, org_id, text, jurisdiction_codes=jurisdiction_codes, limit=3)
    )
    for _score, item in kb_candidates:
        db.add(
            AssistEvidenceItem(
                evidence_set_id=evidence_set.id,
                source_type="KNOWLEDGE",
                source_id=str(item.id),
                title=item.title,
                effective_at=item.effective_from,
                freshness_state="CURRENT",
                authority=item.authority,
                # AssistEvidenceItem has no summary/body columns of its own —
                # stash the content _build_response needs to actually pass to
                # the answer generator here rather than re-querying AssistKbItem.
                extra={"summary": item.summary, "body": item.body},
            )
        )
        evidence_set.entity_count += 1

    kb_found = bool(kb_candidates)

    # Confidence reflects how much of the expected evidence actually showed
    # up, not just "something was found, therefore HIGH" as before.
    if unsupported_country:
        evidence_set.confidence_state = "LOW"
        evidence_set.reason_codes = ["UNSUPPORTED_JURISDICTION"]
        tool_result = {"unsupported_jurisdiction": unsupported_country}
    elif tool_found and kb_found:
        evidence_set.confidence_state = "HIGH"
        evidence_set.reason_codes = ["AUTHORITATIVE_RECORDS", "APPROVED_KNOWLEDGE"]
    elif tool_found or kb_found:
        evidence_set.confidence_state = "MEDIUM"
        evidence_set.reason_codes = ["AUTHORITATIVE_RECORDS"] if tool_found else ["APPROVED_KNOWLEDGE"]
    else:
        evidence_set.confidence_state = "LOW"
        evidence_set.reason_codes = ["NO_MATERIAL_EVIDENCE"]

    # Conflict heuristic: two same-search-pass KB candidates scoring within
    # 1 point of each other but carrying different authority tiers is the
    # ambiguous case CONFLICT exists to flag — true semantic conflict
    # detection needs embeddings (tracked as a later, larger change).
    if len(kb_candidates) >= 2:
        top_score, top_item = kb_candidates[0]
        for score, item in kb_candidates[1:]:
            if abs(score - top_score) <= 1 and item.authority != top_item.authority:
                evidence_set.conflict_state = "POTENTIAL"
                evidence_set.reason_codes = list(evidence_set.reason_codes) + ["AUTHORITY_TIER_DIVERGENCE"]
                break

    # SessionLocal runs with autoflush=False, so the AssistEvidenceItem rows
    # just added above are not visible to _build_response's own query for
    # them (evidence/knowledge would silently be empty there) without an
    # explicit flush here.
    db.flush()
    return evidence_set, tool_result


def _normalize_answer_sources(answer: dict, evidence: list[dict]) -> None:
    """Ground the answer's source references in the authorized evidence set.

    Placeholder or fabricated evidence ids (0, unknown) are dropped; a
    deterministic answer with no cited sources is backfilled from the actual
    evidence items so the guardrail never fails on missing references.
    """
    by_id = {}
    for item in evidence:
        if item.get("evidence_id") is None:
            continue
        by_id.setdefault(int(item["evidence_id"]), item)

    grounded = []
    for src in answer.get("sources") or []:
        eid = src.get("evidence_id")
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            continue
        if eid_int in by_id:
            grounded.append(src)

    if not grounded and by_id:
        grounded = [
            {
                "evidence_id": item["evidence_id"],
                "source_type": item["source_type"],
                "title": item["title"],
                "effective_at": item["effective_at"].isoformat() if item.get("effective_at") else None,
                "authority": item["authority"],
            }
            for item in by_id.values()
        ]
    answer["sources"] = grounded


def _build_response(db, org_id, user, session, message, decision, evidence_set, text, context, tool_result):
    jurisdiction_codes = context.get("jurisdiction_codes") or session.jurisdiction_codes or []
    evidence_items = db.query(AssistEvidenceItem).filter(AssistEvidenceItem.evidence_set_id == evidence_set.id).all()
    evidence = [
        {
            "evidence_id": item.id,
            "source_type": item.source_type,
            "title": item.title,
            "effective_at": item.effective_at,
            "authority": item.authority,
        }
        for item in evidence_items
    ]
    knowledge = [
        {
            "title": item.title,
            "summary": (item.extra or {}).get("summary") or "",
            "body": (item.extra or {}).get("body") or "",
            "authority": item.authority,
        }
        for item in evidence_items
        if item.source_type == "KNOWLEDGE"
    ]
    # tool_result is computed once by _build_evidence_set and passed in here —
    # re-running invoke_read_tool a second time with identical arguments was
    # pure duplicate DB work (and, for find.object/explain.status, this
    # function's own copy of the call was missing the getRunSummary fallback
    # _build_evidence_set already had, so those two intents never actually
    # saw the run data they were credited with in the evidence set).

    engine = "deterministic"
    execution_error = None
    latency_ms = None
    started = datetime.now()
    injection_markers = guardrails.detect_prompt_injection(text)
    if injection_markers:
        logger.warning("Prompt injection markers detected, forcing deterministic engine: %s", injection_markers)
        _audit(
            db, org_id, user, session.id, "assist.injection_suspected",
            {"message_id": message.id, "markers": injection_markers},
        )
    if (
        gateway.model_configured()
        and not decision.get("blocked")
        and not injection_markers
        and decision["intent_id"] not in intents.SMALLTALK_INTENT_IDS
        and not (tool_result and tool_result.get("unsupported_jurisdiction"))
    ):
        try:
            answer = gateway.generate_llm_answer(
                text,
                evidence=evidence,
                knowledge=knowledge,
                intent_id=decision["intent_id"],
                jurisdiction_codes=jurisdiction_codes,
                tool_result=tool_result,
            )
            engine = "llm"
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM gateway failed; falling back to deterministic: %s", exc)
            execution_error = exc
            answer = gateway.deterministic_answer(decision["intent_id"], text, tool_result, knowledge, decision.get("refusal"))
            engine = "deterministic"
    elif injection_markers and not decision.get("blocked"):
        # A blocked A5 intent already gets its own specific, correct refusal
        # below regardless of injection markers (an "ignore instructions and
        # approve this" message should still say it can't approve payroll,
        # not a generic boundary line). This branch only covers the case
        # where classify_intent's keyword matcher landed on an unrelated,
        # possibly-misleading intent (e.g. "show me your system prompt"
        # matching find.object's "show" keyword) — replace that with an
        # explicit, safe boundary answer instead of the accidental match.
        answer = guardrails.injection_boundary_response()
    else:
        answer = gateway.deterministic_answer(decision["intent_id"], text, tool_result, knowledge, decision.get("refusal"))
    latency_ms = int((datetime.now() - started).total_seconds() * 1000)

    allowed_evidence_ids = {item["evidence_id"] for item in evidence}
    _normalize_answer_sources(answer, evidence)
    validation = guardrails.validate_grounded_response(answer, allowed_evidence_ids, tool_result, decision["intent_id"])
    if not validation["passed"] and answer.get("safety_state") != "REFUSED":
        answer = guardrails.safe_fallback_response("; ".join(validation["issues"][:2]))
        answer["safety_state"] = "SAFE_FALLBACK"

    response = AssistResponse(
        session_id=session.id,
        message_id=message.id,
        organization_id=org_id,
        state="COMPLETED",
        intent_id=decision["intent_id"],
        risk_tier=decision["risk_tier"],
        engine=engine,
        model_route=settings.ASSIST_MODEL_NAME if engine == "llm" else None,
        prompt_version="assist-aig-001-v1" if engine == "llm" else None,
        policy_version=settings.ASSIST_POLICY_VERSION,
        evidence_set_id=evidence_set.id,
        validation_result=validation,
        rendered_hash=_content_hash(answer.get("answer") or ""),
        safety_state=answer.get("safety_state", "SAFE"),
        created_at=datetime.now(),
        completed_at=datetime.now(),
    )
    db.add(response)
    db.flush()

    db.add(
        AssistModelExecution(
            response_id=response.id,
            session_id=session.id,
            organization_id=org_id,
            model_route=settings.ASSIST_MODEL_NAME if engine == "llm" else None,
            prompt_version="assist-aig-001-v1" if engine == "llm" else None,
            provider="openai-compatible" if engine == "llm" else "deterministic",
            latency_ms=latency_ms,
            status="failed" if execution_error else "ok",
            error_code=(
                (getattr(execution_error, "error_code", None) or type(execution_error).__name__)
                if execution_error
                else None
            ),
        )
    )

    db.add(
        AssistResponseBlock(
            response_id=response.id,
            block_type="text",
            content=answer.get("answer", ""),
            sequence=1,
        )
    )
    if answer.get("sources"):
        db.add(
            AssistResponseBlock(
                response_id=response.id,
                block_type="sources",
                content=None,
                sequence=2,
                data={"sources": answer.get("sources")},
            )
        )

    if decision.get("risk_tier") == "A3" and decision.get("tool_id"):
        action_block = _auto_action_preview(db, org_id, user, session, decision, text)
        if action_block is not None:
            db.add(
                AssistResponseBlock(
                    response_id=response.id,
                    block_type="action",
                    content=None,
                    sequence=3,
                    data=action_block,
                )
            )

    if decision["intent_id"] == "prepare.note":
        draft_block = _auto_prepare_draft(db, org_id, user, session, tool_result, knowledge, text)
        if draft_block is not None:
            db.add(
                AssistResponseBlock(
                    response_id=response.id,
                    block_type="draft",
                    content=None,
                    sequence=3,
                    data=draft_block,
                )
            )

    _audit(
        db, org_id, user, session.id, "assist.message_submitted",
        {"message_id": message.id, "response_id": response.id, "intent_id": decision["intent_id"]},
    )
    return response


_NOTE_TRIGGER_RE = re.compile(
    r"add a note|add note|add comment|note on the run|comment on run|add an exception note|please|pls",
    re.IGNORECASE,
)


def _extract_note_text(text: str) -> str | None:
    cleaned = _NOTE_TRIGGER_RE.sub(" ", text)
    cleaned = re.sub(r"[^A-Za-z0-9 .,:;!?-]", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:2000] or None


def _auto_prepare_draft(db, org_id, user, session, tool_result, knowledge, text) -> dict | None:
    """Compose an AssistDraft from the same evidence already gathered for the
    'prepare.note' turn, and attach it as a 'draft' response block — no
    separate round trip to POST /assist/drafts.
    """
    lines = []
    run = (tool_result or {}).get("run") or {}
    if run:
        lines.append(f"{run.get('period')} payroll run — status {run.get('status')}.")
    blockers = (tool_result or {}).get("blockers") or []
    if blockers:
        lines.append("Open blockers:")
        lines.extend(f"  - {b['description']} ({b['severity']})" for b in blockers)
    elif tool_result:
        lines.append("No open blockers.")
    if knowledge:
        top = knowledge[0]
        lines.append(f"Related policy: {top.get('title')} — {top.get('summary')}")
    user_note = _extract_note_text(text)
    if user_note:
        lines.append(f"Note: {user_note}")

    if not lines:
        return None

    draft = create_draft(
        db, org_id, user,
        {"draft_type": "note", "content": "\n".join(lines), "session_id": session.id},
    )
    return {"draft_id": draft.id, "draft_type": draft.draft_type, "content": draft.content}


def _auto_action_preview(db, org_id, user, session, decision, text) -> dict | None:
    """Auto-prepare an A3 action preview for the session's bound target.

    The preview is attached to the response as an 'action' block so the chat
    UI can render a confirm/cancel card without a separate round trip. If the
    preview cannot be prepared, an `available: false` block carries the reason.
    """
    action_id = decision.get("tool_id")
    tool = get_action_tool(action_id)
    if tool is None:
        return None
    target = None
    if session.context_object_type and session.context_object_id:
        target = {"type": session.context_object_type, "id": session.context_object_id}
    if target is None:
        return {"action_id": action_id, "available": False, "reason": "No target object is bound to this session."}

    arguments = {}
    if action_id == "payroll.addExceptionNote":
        note = _extract_note_text(text)
        arguments["note"] = note or "Note added from Assist."
    elif action_id == "case.createHandoff":
        arguments = {"destination": "PAYROLL_SUPPORT", "reason_code": "USER_REQUESTED"}

    try:
        preview = create_action_preview(
            db,
            org_id,
            user,
            {
                "action_id": action_id,
                "target": target,
                "arguments": arguments,
                "source_session_id": session.id,
                "source_response_id": None,
            },
            idempotency_key=None,
        )
        return preview
    except Exception as exc:  # noqa: BLE001
        return {"action_id": action_id, "available": False, "reason": str(exc)}


def list_messages(db, org_id, user, session_id, skip, limit):
    get_session(db, org_id, user, session_id)
    query = db.query(AssistMessage).filter(AssistMessage.session_id == session_id, AssistMessage.organization_id == org_id)
    total = query.count()
    messages = query.order_by(AssistMessage.created_at.asc()).offset(skip).limit(limit).all()
    return messages, total


def get_message(db, org_id, user, message_id) -> AssistMessage:
    message = db.query(AssistMessage).filter(AssistMessage.id == message_id, AssistMessage.organization_id == org_id).first()
    if message is None:
        raise NotFoundException("Assist message", message_id)
    session = db.query(AssistSession).filter(AssistSession.id == message.session_id).first()
    if session and session.user_id != user.id:
        raise ForbiddenException("You can only access messages from your own sessions.")
    return message


def _get_response(db, org_id, user, response_id) -> AssistResponse:
    response = db.query(AssistResponse).filter(AssistResponse.id == response_id, AssistResponse.organization_id == org_id).first()
    if response is None:
        raise NotFoundException("Assist response", response_id)
    session = db.query(AssistSession).filter(AssistSession.id == response.session_id).first()
    if session and session.user_id != user.id:
        raise ForbiddenException("You can only access responses from your own sessions.")
    return response


def get_response(db, org_id, user, response_id) -> AssistResponse:
    return _get_response(db, org_id, user, response_id)


def get_response_sources(db, org_id, user, response_id) -> list[AssistEvidenceItem]:
    response = _get_response(db, org_id, user, response_id)
    if not response.evidence_set_id:
        return []
    return db.query(AssistEvidenceItem).filter(AssistEvidenceItem.evidence_set_id == response.evidence_set_id).all()


def get_response_events(db, org_id, user, response_id) -> list[dict]:
    response = _get_response(db, org_id, user, response_id)
    events = [
        {
            "event_type": "assistant_response_started",
            "sequence": 1,
            "data": {"intent_id": response.intent_id},
            "at": response.created_at.isoformat() if response.created_at else None,
        }
    ]
    for block in sorted(response.blocks, key=lambda b: b.sequence):
        events.append(
            {
                "event_type": "assistant_response_block",
                "sequence": block.sequence + 1,
                "data": {"block_type": block.block_type, "content": block.content},
                "at": response.completed_at.isoformat() if response.completed_at else None,
            }
        )
    events.append(
        {
            "event_type": "assistant_response_completed",
            "sequence": len(events) + 1,
            "data": {"state": response.state},
            "at": (response.completed_at or response.created_at).isoformat(),
        }
    )
    return events


def get_response_status(db, org_id, user, response_id) -> dict:
    response = _get_response(db, org_id, user, response_id)
    return {
        "response_id": response.id,
        "state": response.state,
        "intent_id": response.intent_id,
        "progress": 100 if response.state in ("COMPLETED", "FAILED") else 50,
        "completed_at": response.completed_at,
        "error_code": response.error_code,
    }


def stop_response(db, org_id, user, response_id) -> AssistResponse:
    response = _get_response(db, org_id, user, response_id)
    if response.state not in ("ACCEPTED", "PROCESSING"):
        response.state = response.state
    else:
        response.state = "STOPPED"
    db.commit()
    db.refresh(response)
    return response


def get_evidence_set(db, org_id, user, evidence_set_id) -> AssistEvidenceSet:
    evidence_set = db.query(AssistEvidenceSet).filter(AssistEvidenceSet.id == evidence_set_id, AssistEvidenceSet.organization_id == org_id).first()
    if evidence_set is None:
        raise NotFoundException("Evidence set", evidence_set_id)
    return evidence_set


def get_evidence_item(db, org_id, user, evidence_id) -> AssistEvidenceItem:
    item = db.query(AssistEvidenceItem).filter(AssistEvidenceItem.id == evidence_id).first()
    if item is None:
        raise NotFoundException("Evidence item", evidence_id)
    evidence_set = db.query(AssistEvidenceSet).filter(AssistEvidenceSet.id == item.evidence_set_id).first()
    if evidence_set is None or evidence_set.organization_id != org_id:
        raise ForbiddenException("You can only access evidence from your own organization.")
    return item


def submit_feedback(db, org_id, user, response_id, payload: dict) -> AssistFeedback:
    response = _get_response(db, org_id, user, response_id)
    feedback = AssistFeedback(
        organization_id=org_id,
        response_id=response.id,
        user_id=user.id,
        rating=payload["rating"],
        reason_code=payload.get("reason_code"),
        comment_redacted=payload.get("comment"),
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def get_audit_reference(db, org_id, user, response_id) -> dict:
    response = _get_response(db, org_id, user, response_id)
    event = (
        db.query(AssistAuditEvent)
        .filter(AssistAuditEvent.organization_id == org_id, AssistAuditEvent.session_id == response.session_id)
        .order_by(AssistAuditEvent.recorded_at.desc())
        .first()
    )
    if event is None:
        raise NotFoundException("Audit reference", response_id)
    return {"audit_id": event.id, "event_type": event.event_type, "recorded_at": event.recorded_at}


# ── Drafts ──────────────────────────────────────────────────────────────

def create_draft(db, org_id, user, payload: dict) -> AssistDraft:
    draft = AssistDraft(
        organization_id=org_id,
        user_id=user.id,
        session_id=payload.get("session_id"),
        draft_type=payload["draft_type"],
        content=payload["content"],
        state="DRAFT",
        revision=1,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def list_drafts(db, org_id, user, skip: int = 0, limit: int = 50, state: str = None):
    query = db.query(AssistDraft).filter(AssistDraft.organization_id == org_id, AssistDraft.user_id == user.id)
    if state:
        query = query.filter(AssistDraft.state == state)
    total = query.count()
    drafts = query.order_by(AssistDraft.updated_at.desc().nullslast(), AssistDraft.created_at.desc()).offset(skip).limit(limit).all()
    return drafts, total


def get_draft(db, org_id, user, draft_id) -> AssistDraft:
    draft = db.query(AssistDraft).filter(AssistDraft.id == draft_id, AssistDraft.organization_id == org_id).first()
    if draft is None:
        raise NotFoundException("Assist draft", draft_id)
    if draft.user_id != user.id:
        raise ForbiddenException("You can only access your own drafts.")
    return draft


def update_draft(db, org_id, user, draft_id, payload: dict) -> AssistDraft:
    draft = get_draft(db, org_id, user, draft_id)
    if "content" in payload:
        draft.content = payload["content"]
        draft.revision += 1
    if "state" in payload:
        draft.state = payload["state"]
    db.commit()
    db.refresh(draft)
    return draft


def delete_draft(db, org_id, user, draft_id) -> None:
    draft = get_draft(db, org_id, user, draft_id)
    db.delete(draft)
    db.commit()


# ── Handoffs ────────────────────────────────────────────────────────────

# One support notification per user per org per rolling 24h window — the
# repeat-escalation path had no dedup at all: every confirmed handoff
# unconditionally created a new case and sent both emails regardless of how
# recently the same user had already escalated, so an accidental double-
# request (or a genuine but still-unresolved repeat) generated a fresh case
# and a fresh email storm every time. Enterprise support tooling (Zendesk,
# Freshdesk, ServiceNow) treats "same requester, still within the window" as
# a duplicate to surface against the existing case, not a new one.
HANDOFF_COOLDOWN_HOURS = 24


def _resolve_source_session_id(db, org_id, payload: dict):
    """A preview can be attached to a session either directly
    (source_session_id — e.g. "escalate this conversation") or via a specific
    response (source_response_id), in which case we resolve that response's
    own session_id rather than ever treating a response id as a session id —
    the two are different tables with different id sequences, so passing one
    where the other is expected either violates the session_id foreign key or,
    worse, silently attaches the record to an unrelated session that happens
    to share the same numeric id."""
    session_id = payload.get("source_session_id")
    if session_id is not None:
        return session_id
    response_id = payload.get("source_response_id")
    if response_id is None:
        return None
    response = (
        db.query(AssistResponse)
        .filter(AssistResponse.id == response_id, AssistResponse.organization_id == org_id)
        .first()
    )
    if response is None:
        raise BadRequestException(f"source_response_id {response_id} does not refer to a valid response.")
    return response.session_id


def _recent_handoff(db, org_id, user_id) -> AssistHandoff | None:
    """Most recent handoff this user raised in this org, if within the
    cooldown window — None once 24h have passed, so a genuinely new request
    goes through normally."""
    cutoff = _utcnow() - timedelta(hours=HANDOFF_COOLDOWN_HOURS)
    return (
        db.query(AssistHandoff)
        .filter(
            AssistHandoff.organization_id == org_id,
            AssistHandoff.user_id == user_id,
            AssistHandoff.created_at > cutoff,
        )
        .order_by(AssistHandoff.created_at.desc())
        .first()
    )


def _handoff_cooldown_message(handoff: AssistHandoff) -> str:
    available_at = _as_aware(handoff.created_at) + timedelta(hours=HANDOFF_COOLDOWN_HOURS)
    return (
        f"A support request was already sent to the support team for case {handoff.case_id}. "
        f"Only one support email is sent every {HANDOFF_COOLDOWN_HOURS} hours — "
        f"you can send another after {available_at.strftime('%Y-%m-%d %H:%M UTC')}."
    )


def create_handoff_preview(db, org_id, user, payload: dict) -> AssistHandoffPreview:
    existing = _recent_handoff(db, org_id, user.id)
    if existing is not None:
        raise BadRequestException(_handoff_cooldown_message(existing))
    preview = AssistHandoffPreview(
        organization_id=org_id,
        user_id=user.id,
        session_id=_resolve_source_session_id(db, org_id, payload),
        destination=payload["destination"],
        reason_code=payload["reason_code"],
        summary=payload["summary"],
        evidence_ids=payload.get("included_evidence_ids") or [],
        excluded_data_classes=payload.get("excluded_data_classes") or [],
        state="PREVIEWED",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_HANDOFF_PREVIEW_MINUTES),
    )
    db.add(preview)
    db.commit()
    db.refresh(preview)
    return preview


def get_handoff_preview(db, org_id, user, preview_id) -> AssistHandoffPreview:
    preview = db.query(AssistHandoffPreview).filter(AssistHandoffPreview.id == preview_id, AssistHandoffPreview.organization_id == org_id).first()
    if preview is None:
        raise NotFoundException("Handoff preview", preview_id)
    if preview.user_id != user.id:
        raise ForbiddenException("You can only access your own handoff previews.")
    return preview


def confirm_handoff(db, org_id, user, preview_id) -> AssistHandoff:
    preview = get_handoff_preview(db, org_id, user, preview_id)
    if preview.state != "PREVIEWED":
        raise BadRequestException(f"Handoff preview is in state {preview.state}.")
    # Authoritative re-check, not just belt-and-suspenders: create_handoff_preview
    # already blocks new previews during the cooldown, but a preview created
    # just before another request's confirm landed could otherwise slip
    # through — this is the actual point emails get sent, so it's the check
    # that must never be skippable.
    existing = _recent_handoff(db, org_id, user.id)
    if existing is not None:
        raise BadRequestException(_handoff_cooldown_message(existing))
    if preview.expires_at and _as_aware(preview.expires_at) < _utcnow():
        preview.state = "EXPIRED"
        db.commit()
        raise BadRequestException("Handoff preview has expired.")
    case_id = f"case_{org_id}_{int(datetime.now().timestamp())}"
    handoff = AssistHandoff(
        organization_id=org_id,
        preview_id=preview.id,
        user_id=user.id,
        destination=preview.destination,
        reason_code=preview.reason_code,
        summary=preview.summary,
        case_id=case_id,
        state="CREATED",
        sla_reference="ZOIKO-PAYROLL-SLA-24H",
    )
    db.add(handoff)
    preview.state = "CONFIRMED"
    db.flush()
    audit = _audit(
        db, org_id, user, preview.session_id, "assist.handoff_created",
        {"handoff_id": handoff.id, "case_id": case_id, "destination": preview.destination},
    )
    handoff.audit_id = audit.id
    db.commit()
    db.refresh(handoff)
    _notify_handoff_created(db, org_id, user, handoff)
    return handoff


def _notify_handoff_created(db, org_id, user, handoff: AssistHandoff) -> None:
    """Best-effort email notification — a delivery failure must never
    block the handoff itself, which is already committed by this point."""
    requester_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
    try:
        from app.services.email_service import send_handoff_confirmation_email

        send_handoff_confirmation_email(
            user.email, requester_name, handoff.case_id, handoff.summary, handoff.destination,
            sla_reference=handoff.sla_reference or "", organization_id=org_id, db=db,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[assist] Handoff confirmation email failed for case {handoff.case_id}: {exc}")
    try:
        from app.services.email_service import send_handoff_support_notification_email

        send_handoff_support_notification_email(
            requester_name, user.email, handoff.case_id, handoff.summary, handoff.destination,
            handoff.reason_code, organization_id=org_id, db=db,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[assist] Handoff support notification email failed for case {handoff.case_id}: {exc}")


def cancel_handoff(db, org_id, user, preview_id) -> AssistHandoffPreview:
    preview = get_handoff_preview(db, org_id, user, preview_id)
    if preview.state != "PREVIEWED":
        raise BadRequestException(f"Handoff preview is in state {preview.state}.")
    preview.state = "CANCELED"
    db.commit()
    db.refresh(preview)
    return preview


def get_handoff(db, org_id, user, handoff_id) -> AssistHandoff:
    handoff = db.query(AssistHandoff).filter(AssistHandoff.id == handoff_id, AssistHandoff.organization_id == org_id).first()
    if handoff is None:
        raise NotFoundException("Handoff", handoff_id)
    if handoff.user_id != user.id:
        raise ForbiddenException("You can only access your own handoffs.")
    return handoff


# ── Controlled actions (A3) ─────────────────────────────────────────────

def get_allowed_actions(db, org_id, user) -> list[dict]:
    allowed = []
    for spec in intents.ALLOWED_A3_TOOL_IDS:
        tool = get_action_tool(spec)
        if tool:
            allowed.append(
                {
                    "action_id": spec,
                    "risk_tier": tool["risk_tier"],
                    "description": tool["description"],
                    "allowed": True,
                    "requires_confirmation": tool.get("requires_confirmation", True),
                }
            )
    return allowed


def _check_action_role(tool: dict, user) -> None:
    """Re-check the acting user's live role against what this action requires.

    Called at both preview creation (early feedback) and confirmation (the
    real gate — role can change between the two, e.g. a demotion, so the
    check at preview time alone is not sufficient).
    """
    required_roles = tool.get("required_roles")
    if required_roles and role_value(user) not in required_roles:
        raise ForbiddenException(
            f"This action requires one of the following roles: {', '.join(required_roles)}."
        )


def create_action_preview(db, org_id, user, payload: dict, idempotency_key: str = None) -> dict:
    action_id = payload["action_id"]
    tool = get_action_tool(action_id)
    if tool is None:
        raise BadRequestException(f"Action '{action_id}' is not an allowed Assist action.")
    if tool["risk_tier"] in ("A4", "A5"):
        raise BadRequestException(f"Action '{action_id}' cannot be executed by Assist.")
    _check_action_role(tool, user)
    if payload.get("target", {}).get("type") in ("PAYROLL_RUN", "PAYROLL_EXCEPTION") and tool["risk_tier"] == "A3":
        pass

    resolved_session_id = _resolve_source_session_id(db, org_id, payload)

    def _build():
        target = payload["target"]
        preview_result = tool["preview"](
            db, org_id, resolved_session_id, user, target, payload.get("arguments") or {}
        )
        if "error" in preview_result:
            raise BadRequestException(preview_result["error"])
        preview = AssistActionPreview(
            organization_id=org_id,
            user_id=user.id,
            session_id=resolved_session_id,
            action_id=action_id,
            risk_tier=tool["risk_tier"],
            target_type=preview_result["target"]["type"],
            target_id=str(preview_result["target"]["id"]),
            target_version=preview_result["target"].get("version"),
            before_data=preview_result.get("before"),
            after_data=preview_result.get("after"),
            confirmation_label=preview_result.get("confirmation_label"),
            step_up_required=1 if preview_result.get("step_up_required") else 0,
            state="READY_FOR_CONFIRMATION",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=preview_result.get("expires_minutes", DEFAULT_ACTION_PREVIEW_MINUTES)),
        )
        db.add(preview)
        db.flush()
        _audit(
            db, org_id, user, resolved_session_id, "assist.action_previewed",
            {"preview_id": preview.id, "action_id": action_id},
        )
        db.commit()
        return _action_preview_dict(preview)

    return _idempotent(db, org_id, "action_previews", idempotency_key, payload, _build)[0]


def _action_preview_dict(preview: AssistActionPreview) -> dict:
    return {
        "preview_id": preview.id,
        "risk_tier": preview.risk_tier,
        "state": preview.state,
        "action_id": preview.action_id,
        "target": {"type": preview.target_type, "id": preview.target_id, "version": preview.target_version},
        "before": preview.before_data,
        "after": preview.after_data,
        "confirmation": {
            "label": preview.confirmation_label or "Confirm action",
            "step_up_required": bool(preview.step_up_required),
        },
        "expires_at": preview.expires_at.isoformat() if preview.expires_at else None,
        "etag": f'"{preview.id}-v{preview.target_version or 1}"',
    }


def get_action_preview(db, org_id, user, preview_id) -> AssistActionPreview:
    preview = db.query(AssistActionPreview).filter(AssistActionPreview.id == preview_id, AssistActionPreview.organization_id == org_id).first()
    if preview is None:
        raise NotFoundException("Action preview", preview_id)
    if preview.user_id != user.id:
        raise ForbiddenException("You can only access your own action previews.")
    return preview


def confirm_action(db, org_id, user, preview_id, payload: dict, idempotency_key: str = None, if_match: str = None) -> dict:
    preview = get_action_preview(db, org_id, user, preview_id)
    if preview.state != "READY_FOR_CONFIRMATION":
        raise BadRequestException(f"Action preview is in state {preview.state}.")
    if preview.expires_at and _as_aware(preview.expires_at) < _utcnow():
        preview.state = "EXPIRED"
        db.commit()
        raise BadRequestException("Action preview has expired.")

    tool = get_action_tool(preview.action_id)
    if tool is None:
        raise BadRequestException("The registered action is no longer available.")
    # Re-check the acting user's *current* role — it may have changed since
    # the preview was created (e.g. a demotion between preview and confirm).
    _check_action_role(tool, user)

    # If the client sent an If-Match header, reject a confirm against a
    # target that has moved on since the preview was generated. Only
    # AssistExceptionSnapshot targets carry a real version counter today;
    # other target types fall back to the version recorded on the preview.
    if if_match:
        live_version = get_live_target_version(db, org_id, preview.target_type, preview.target_id)
        current_version = live_version if live_version is not None else (preview.target_version or 1)
        current_etag = f'"{preview.id}-v{current_version}"'
        if if_match != current_etag:
            raise ZoikoException(
                409,
                "RESOURCE_VERSION_CONFLICT",
                "The target has changed since this preview was created. Fetch a new preview and try again.",
            )

    def _build():
        preview.state = "CONFIRMED"
        confirmation = AssistActionConfirmation(
            preview_id=preview.id,
            user_id=user.id,
            idempotency_key=idempotency_key,
            confirmation_token=payload.get("confirmation_token"),
        )
        db.add(confirmation)
        db.flush()

        execution = tool["execute"](db, org_id, preview.session_id, user, preview)
        if execution.get("outcome") == "SUCCEEDED":
            preview.state = "SUCCEEDED"
        else:
            preview.state = "FAILED"

        if preview.action_id == "case.createHandoff" and execution.get("outcome") == "SUCCEEDED" and execution.get("handoff_id"):
            created_handoff = db.query(AssistHandoff).filter(AssistHandoff.id == execution["handoff_id"]).first()
            if created_handoff is not None:
                _notify_handoff_created(db, org_id, user, created_handoff)

        receipt = AssistActionReceipt(
            organization_id=org_id,
            preview_id=preview.id,
            user_id=user.id,
            action_id=preview.action_id,
            target_type=preview.target_type,
            target_id=preview.target_id,
            target_version=execution.get("target_version", preview.target_version),
            outcome=execution.get("outcome", "FAILED"),
            audit_id=execution.get("audit_id"),
        )
        db.add(receipt)
        db.flush()
        _audit(
            db, org_id, user, preview.session_id, "assist.action_confirmed",
            {"preview_id": preview.id, "action_id": preview.action_id, "outcome": receipt.outcome},
        )
        db.commit()
        return _receipt_dict(receipt, preview)

    return _idempotent(db, org_id, "action_confirmations", idempotency_key, payload, _build)[0]


def _receipt_dict(receipt: AssistActionReceipt, preview: AssistActionPreview) -> dict:
    return {
        "receipt_id": receipt.id,
        "outcome": receipt.outcome,
        "action_id": receipt.action_id,
        "target": {"type": receipt.target_type, "id": receipt.target_id, "version": receipt.target_version},
        "committed_at": receipt.committed_at.isoformat() if receipt.committed_at else datetime.now().isoformat(),
        "audit_id": receipt.audit_id,
    }


def cancel_action(db, org_id, user, preview_id) -> AssistActionPreview:
    preview = get_action_preview(db, org_id, user, preview_id)
    if preview.state != "READY_FOR_CONFIRMATION":
        raise BadRequestException(f"Action preview is in state {preview.state}.")
    preview.state = "CANCELED"
    db.commit()
    db.refresh(preview)
    return preview


def get_action_receipt(db, org_id, user, receipt_id) -> AssistActionReceipt:
    receipt = db.query(AssistActionReceipt).filter(AssistActionReceipt.id == receipt_id, AssistActionReceipt.organization_id == org_id).first()
    if receipt is None:
        raise NotFoundException("Action receipt", receipt_id)
    if receipt.user_id != user.id:
        raise ForbiddenException("You can only access your own action receipts.")
    return receipt


# ── Service status ──────────────────────────────────────────────────────

def get_status(db) -> dict:
    from app.modules.assist.models import AssistKbItem, KnowledgeState

    kb_available = (
        db.query(AssistKbItem).filter(AssistKbItem.state == KnowledgeState.PUBLISHED.value).count() > 0
    )
    return {
        "status": "ok",
        "engine": gateway.active_engine(),
        "model_configured": gateway.model_configured(),
        "knowledge_available": kb_available,
        "version": settings.APP_VERSION,
    }


# ── Knowledge base management ───────────────────────────────────────────

def list_kb_items(db, org_id, state=None):
    query = db.query(AssistKbItem).filter(
        (AssistKbItem.organization_id.is_(None)) | (AssistKbItem.organization_id == org_id)
    )
    if state:
        query = query.filter(AssistKbItem.state == state)
    return query.order_by(AssistKbItem.updated_at.desc()).all()


def create_kb_item(db, org_id, user, payload: dict, tenant: bool = False) -> AssistKbItem:
    item = AssistKbItem(
        source_id=payload.get("source_id"),
        organization_id=org_id if tenant else None,
        content_type=payload.get("content_type", "HOW_TO"),
        title=payload["title"],
        body=payload["body"],
        summary=payload.get("summary"),
        language=payload.get("language", "en"),
        jurisdiction_codes=payload.get("jurisdiction_codes") or [],
        state="DRAFT",
        authority=payload.get("authority", "TIER_3_APPROVED_SECONDARY"),
        version=1,
        effective_from=payload.get("effective_from"),
        effective_to=payload.get("effective_to"),
        next_review_at=payload.get("next_review_at"),
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_kb_item(db, org_id, item_id) -> AssistKbItem:
    item = db.query(AssistKbItem).filter(AssistKbItem.id == item_id).first()
    if item is None:
        raise NotFoundException("Knowledge item", item_id)
    if item.organization_id is not None and item.organization_id != org_id:
        raise ForbiddenException("You can only access knowledge from your own organization.")
    return item


def update_kb_item(db, org_id, user, item_id, payload: dict) -> AssistKbItem:
    item = get_kb_item(db, org_id, item_id)
    if item.state in (KnowledgeState.PUBLISHED.value, KnowledgeState.APPROVED.value) and "state" not in payload:
        raise BadRequestException("Published knowledge cannot be edited directly; create a new version instead.")
    for field in ("title", "body", "content_type", "summary", "language", "authority", "next_review_at", "effective_from", "effective_to"):
        if field in payload and payload[field] is not None:
            setattr(item, field, payload[field])
    if "jurisdiction_codes" in payload:
        item.jurisdiction_codes = payload["jurisdiction_codes"] or []
    if "state" in payload and payload["state"] == KnowledgeState.IN_REVIEW.value:
        # Submitting for review carries no four-eyes requirement — that
        # only applies to the APPROVED/PUBLISHED step below.
        item.state = payload["state"]
        item.version += 1
    elif "state" in payload and payload["state"] in (KnowledgeState.PUBLISHED.value, KnowledgeState.APPROVED.value):
        # Four-eyes applies to any transition into APPROVED or PUBLISHED,
        # not just the APPROVED step — otherwise a direct DRAFT->PUBLISHED
        # edit would bypass the same-author restriction entirely.
        if item.created_by is not None and user.id == item.created_by:
            raise ForbiddenException(
                "Four-eyes review required: a knowledge item cannot be approved or published by the same user "
                "who authored it."
            )
        item.state = payload["state"]
        item.reviewed_by = user.id
        if payload["state"] == KnowledgeState.PUBLISHED.value:
            item.published_at = datetime.now()
        item.version += 1
    db.commit()
    db.refresh(item)
    return item


def publish_kb_item(db, org_id, user, item_id, payload: dict) -> AssistKbItem:
    item = get_kb_item(db, org_id, item_id)
    if item.state != KnowledgeState.APPROVED.value:
        raise BadRequestException("Only APPROVED knowledge can be published.")
    if item.reviewed_by is None or (item.created_by is not None and item.reviewed_by == item.created_by):
        raise ForbiddenException(
            "Four-eyes review required: this item has no independent reviewer on record and cannot be published."
        )
    item.state = KnowledgeState.PUBLISHED.value
    item.published_at = datetime.now()
    item.version += 1
    db.commit()
    db.refresh(item)
    return item


# States a KB item can still move out of before publication (draft/review
# lifecycle, per KB governance spec §12).
_PRE_PUBLISH_STATES = {
    KnowledgeState.DRAFT.value,
    KnowledgeState.IN_REVIEW.value,
    KnowledgeState.APPROVED.value,
    KnowledgeState.CORRECTION_REQUIRED.value,
    KnowledgeState.SCHEDULED.value,
}
# States that are already a terminal/historical exit — nothing further
# should move an item out of these via the transitions below.
_TERMINAL_KB_STATES = {
    KnowledgeState.REJECTED.value,
    KnowledgeState.SUPERSEDED.value,
    KnowledgeState.EXPIRED.value,
    KnowledgeState.WITHDRAWN.value,
    KnowledgeState.QUARANTINED.value,
}


def request_kb_correction(db, org_id, user, item_id, reason: str) -> AssistKbItem:
    """Reviewer sends a defect back to the author (spec §12: "reviewer
    identifies defect; returns to author") — distinct from a hard REJECTED."""
    item = get_kb_item(db, org_id, item_id)
    if item.state not in (KnowledgeState.IN_REVIEW.value, KnowledgeState.APPROVED.value):
        raise BadRequestException(f"Cannot request correction from state {item.state}.")
    item.state = KnowledgeState.CORRECTION_REQUIRED.value
    item.state_reason = reason
    item.version += 1
    db.commit()
    db.refresh(item)
    return item


def reject_kb_item(db, org_id, user, item_id, reason: str) -> AssistKbItem:
    """Review fails outright; reason and evidence retained (spec §12)."""
    item = get_kb_item(db, org_id, item_id)
    if item.state not in _PRE_PUBLISH_STATES:
        raise BadRequestException(f"Cannot reject from state {item.state}.")
    item.state = KnowledgeState.REJECTED.value
    item.state_reason = reason
    item.version += 1
    db.commit()
    db.refresh(item)
    return item


def withdraw_kb_item(db, org_id, user, item_id, reason: str) -> AssistKbItem:
    """Owner-driven removal for business/legal/content reasons — immediate
    current-index exclusion, reason retained (spec §14)."""
    item = get_kb_item(db, org_id, item_id)
    if item.state not in (KnowledgeState.PUBLISHED.value, KnowledgeState.SCHEDULED.value):
        raise BadRequestException(f"Cannot withdraw from state {item.state}.")
    item.state = KnowledgeState.WITHDRAWN.value
    item.state_reason = reason
    item.version += 1
    db.commit()
    db.refresh(item)
    return item


def quarantine_kb_item(db, org_id, user, item_id, reason: str) -> AssistKbItem:
    """Immediate kill switch for a security/integrity/accuracy incident — no
    user-facing disclosure beyond the safe fallback (spec §14)."""
    item = get_kb_item(db, org_id, item_id)
    if item.state in _TERMINAL_KB_STATES:
        raise BadRequestException(f"Cannot quarantine from state {item.state}.")
    item.state = KnowledgeState.QUARANTINED.value
    item.state_reason = reason
    item.version += 1
    db.commit()
    db.refresh(item)
    _audit(db, org_id, user, None, "assist.kb_item_quarantined", {"item_id": item.id, "reason": reason})
    return item


def supersede_kb_item(db, org_id, user, old_item_id, new_item_id, reason: str) -> AssistKbItem:
    """Explicit successor link — the predecessor drops out of retrieval
    indexes but its row (and any past citations of it) remain resolvable
    (spec §14: "preserve old version; publish corrected version")."""
    old_item = get_kb_item(db, org_id, old_item_id)
    new_item = get_kb_item(db, org_id, new_item_id)
    if old_item.state != KnowledgeState.PUBLISHED.value:
        raise BadRequestException(f"Cannot supersede from state {old_item.state}; only a PUBLISHED item can be superseded.")
    if new_item.id == old_item.id:
        raise BadRequestException("A knowledge item cannot supersede itself.")
    old_item.state = KnowledgeState.SUPERSEDED.value
    old_item.state_reason = reason
    old_item.supersedes_item_id = new_item.id
    old_item.version += 1
    db.commit()
    db.refresh(old_item)
    return old_item


def run_kb_expiry_sweep(db, org_id) -> dict:
    """Move PUBLISHED/SCHEDULED items whose effective_to has passed to
    EXPIRED (spec §12: "effective_to or expiry/review policy reached").
    Manual-trigger admin action, mirroring run_retention_cleanup — no
    background worker exists yet, consistent with the rest of this batch.
    """
    today = date.today()
    rows = (
        db.query(AssistKbItem)
        .filter(
            (AssistKbItem.organization_id.is_(None)) | (AssistKbItem.organization_id == org_id),
            AssistKbItem.state.in_([KnowledgeState.PUBLISHED.value, KnowledgeState.SCHEDULED.value]),
            AssistKbItem.effective_to.isnot(None),
            AssistKbItem.effective_to < today,
        )
        .all()
    )
    for item in rows:
        item.state = KnowledgeState.EXPIRED.value
        item.version += 1
    if rows:
        db.commit()
    return {"expired": len(rows), "item_ids": [i.id for i in rows]}


def list_kb_sources(db):
    return db.query(AssistKbSource).order_by(AssistKbSource.created_at.asc()).all()


def create_kb_source(db, payload: dict) -> AssistKbSource:
    source = AssistKbSource(
        name=payload["name"],
        source_type=payload.get("source_type"),
        authority_tier=payload.get("authority_tier", "TIER_3_APPROVED_SECONDARY"),
        state=KnowledgeSourceState.ACTIVE.value,
        url=payload.get("url"),
        owner="Platform",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def quarantine_kb_source(db, org_id, user, source_id, reason: str) -> AssistKbSource:
    """Security/integrity incident at the source level — cascades to every
    item drawn from that source via knowledge.py's retrieval-eligibility
    check (spec §14 ties quarantine to sources as well as items)."""
    source = db.query(AssistKbSource).filter(AssistKbSource.id == source_id).first()
    if source is None:
        raise NotFoundException("Knowledge source", source_id)
    source.state = KnowledgeSourceState.QUARANTINED.value
    db.commit()
    db.refresh(source)
    _audit(db, org_id, user, None, "assist.kb_source_quarantined", {"source_id": source.id, "reason": reason})
    return source


def reactivate_kb_source(db, org_id, user, source_id) -> AssistKbSource:
    source = db.query(AssistKbSource).filter(AssistKbSource.id == source_id).first()
    if source is None:
        raise NotFoundException("Knowledge source", source_id)
    source.state = KnowledgeSourceState.ACTIVE.value
    db.commit()
    db.refresh(source)
    return source


# ── Audit / retention (admin) ───────────────────────────────────────────

def list_audit_events(db, org_id, skip, limit, event_type=None, session_id=None):
    from app.modules.assist.models import AssistAuditEvent

    query = db.query(AssistAuditEvent).filter(AssistAuditEvent.organization_id == org_id)
    if event_type:
        query = query.filter(AssistAuditEvent.event_type == event_type)
    if session_id:
        query = query.filter(AssistAuditEvent.session_id == session_id)
    total = query.count()
    events = query.order_by(AssistAuditEvent.recorded_at.desc()).offset(skip).limit(limit).all()
    return events, total


def list_admin_sessions(db, org_id, skip, limit, status=None):
    query = db.query(AssistSession).filter(AssistSession.organization_id == org_id)
    if status:
        query = query.filter(AssistSession.status == status)
    total = query.count()
    sessions = query.order_by(AssistSession.created_at.desc()).offset(skip).limit(limit).all()
    return sessions, total


def list_model_executions(db, org_id, skip, limit, response_id=None):
    query = db.query(AssistModelExecution).filter(AssistModelExecution.organization_id == org_id)
    if response_id:
        query = query.filter(AssistModelExecution.response_id == response_id)
    total = query.count()
    rows = query.order_by(AssistModelExecution.created_at.desc()).offset(skip).limit(limit).all()
    return rows, total


def get_retention_summary(db, org_id) -> dict:
    from app.modules.assist.models import AssistSession

    now = datetime.now(timezone.utc)
    rows = db.query(AssistSession).filter(AssistSession.organization_id == org_id).all()
    by_class = {}
    by_status = {}
    expired = 0
    oldest = None
    for s in rows:
        by_class[s.retention_class or "STANDARD"] = by_class.get(s.retention_class or "STANDARD", 0) + 1
        by_status[s.status] = by_status.get(s.status, 0) + 1
        if s.expires_at and _as_aware(s.expires_at) < now:
            expired += 1
        if oldest is None or (s.created_at and s.created_at < oldest):
            oldest = s.created_at
    return {
        "total_sessions": len(rows),
        "retention_class_counts": by_class,
        "status_counts": by_status,
        "expired_sessions": expired,
        "oldest_session_at": oldest.isoformat() if oldest else None,
        "retention_policy": settings.ASSIST_POLICY_VERSION,
    }


def run_retention_cleanup(db, org_id, user) -> dict:
    """Archive sessions whose retention window has expired.

    Expiry never deletes authoritative payroll records — it archives the
    Assist session (and its messages/responses are retained for audit) while
    recording an audit event for governance review.
    """
    from app.modules.assist.models import AssistSession

    now = _utcnow()

    def _candidates():
        return (
            db.query(AssistSession)
            .filter(
                AssistSession.organization_id == org_id,
                AssistSession.expires_at.isnot(None),
                AssistSession.status != AssistSessionState.ARCHIVED.value,
            )
            .all()
        )

    # Expiry compares a fetched column value against "now" in Python (not a
    # SQL filter) because DateTime(timezone=True) round-trips tz-aware on
    # Postgres but naive on SQLite — a single hardcoded bind parameter would
    # silently mis-filter on one dialect or the other.
    rows = [s for s in _candidates() if _as_aware(s.expires_at) < now]
    archived = 0
    for s in rows:
        s.status = AssistSessionState.ARCHIVED.value
        s.archived_at = s.archived_at or now
        archived += 1
        _audit(
            db, org_id, user, s.id, "assist.session_expired_by_retention",
            {"session_id": s.id, "expires_at": s.expires_at.isoformat(), "retention_class": s.retention_class},
        )
    if archived:
        db.commit()
    expired_remaining = sum(1 for s in _candidates() if _as_aware(s.expires_at) < now)
    return {
        "archived": archived,
        "scanned": len(rows),
        "expired_remaining": expired_remaining,
    }

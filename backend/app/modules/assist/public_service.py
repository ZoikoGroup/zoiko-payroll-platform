"""
modules/assist/public_service.py
---------------------------------
Unauthenticated, public-website mode for Zoiko Payroll Assist.

Deliberately isolated from service.py rather than adding "if anonymous"
branches to the authenticated flow: this module never imports tools.py, so
there is no code path here that can reach payroll read/action tools at all
— not "refused by a prompt," genuinely unreachable. It only ever answers
from the global (organization_id IS NULL) governed knowledge base via
knowledge.search_kb, reusing the same guardrails and LLM gateway as the
authenticated assistant.
"""

from __future__ import annotations

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.assist import gateway, guardrails, intents
from app.modules.assist import knowledge as knowledge_module
from app.modules.assist.models import AssistPublicMessage, AssistPublicSession

# Never a real organization id (real ids start at 1) — passing this to
# search_kb's `organization_id == organization_id` branch can never match a
# tenant's items, so only global items (organization_id IS NULL) come back.
PUBLIC_KB_ORG_SENTINEL = 0

MAX_MESSAGE_LENGTH = 500
MAX_MESSAGES_PER_SESSION = 20

# Intents that are pure conversational/knowledge lookups — everything else
# (run status, exceptions, payslips, any A2/A3/A5 action) implies an account
# this visitor doesn't have, so it's redirected before ever touching the KB.
_ALLOWED_PUBLIC_INTENTS = {"kb.answer", "explain.field", "chat.greeting", "chat.acknowledgment"}

SIGN_IN_REDIRECT = (
    "I can help with general payroll questions here. To access your organization's "
    "payroll information or take any action, please sign in to Zoiko Payroll."
)
NO_MATCH_FALLBACK = (
    "I don't have public information on that yet. I can answer general payroll questions here — "
    "for anything about your own account or organization, please sign in to Zoiko Payroll."
)


def create_public_session(db, ip_address: str | None, locale: str = "en") -> AssistPublicSession:
    session = AssistPublicSession(ip_address=ip_address, locale=locale or "en")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _get_public_session(db, session_id: int) -> AssistPublicSession:
    session = db.query(AssistPublicSession).filter(AssistPublicSession.id == session_id).first()
    if session is None:
        raise NotFoundException("Public session", session_id)
    return session


def list_public_messages(db, session_id: int) -> list[AssistPublicMessage]:
    session = _get_public_session(db, session_id)
    return (
        db.query(AssistPublicMessage)
        .filter(AssistPublicMessage.session_id == session.id)
        .order_by(AssistPublicMessage.created_at.asc())
        .all()
    )


def submit_public_message(db, session_id: int, text: str) -> dict:
    session = _get_public_session(db, session_id)

    text = (text or "").strip()
    if not text:
        raise BadRequestException("Message text is required.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise BadRequestException(f"Message is too long (max {MAX_MESSAGE_LENGTH} characters).")
    if session.message_count >= MAX_MESSAGES_PER_SESSION:
        raise BadRequestException("This conversation has reached its message limit. Please start a new session.")

    db.add(AssistPublicMessage(session_id=session.id, role="user", content=text))
    session.message_count += 1
    db.flush()

    decision = intents.classify_intent(text)
    intent_id = decision["intent_id"]

    if intent_id == "chat.greeting":
        answer_text = gateway.deterministic_answer("chat.greeting", text, None, [])["answer"]
        sources: list[dict] = []
    elif intent_id == "chat.acknowledgment":
        answer_text = gateway.deterministic_answer("chat.acknowledgment", text, None, [])["answer"]
        sources = []
    elif intent_id not in _ALLOWED_PUBLIC_INTENTS:
        # Anything account/action-shaped (run status, my payslip, approve
        # payroll, ...) — redirected without ever touching the knowledge
        # base or the LLM, since there is genuinely nothing here to answer
        # it with.
        answer_text = SIGN_IN_REDIRECT
        sources = []
    else:
        injection_markers = guardrails.detect_prompt_injection(text)
        if injection_markers:
            answer_text = guardrails.injection_boundary_response()["answer"]
            sources = []
        else:
            kb_candidates = knowledge_module.search_kb(db, PUBLIC_KB_ORG_SENTINEL, text, limit=3, record_run=False)
            knowledge_items = [
                {"title": item.title, "summary": item.summary, "body": item.body, "authority": item.authority}
                for _score, item in kb_candidates
            ]
            if not knowledge_items:
                answer_text = NO_MATCH_FALLBACK
                sources = []
            elif gateway.model_configured() and not injection_markers:
                try:
                    llm_answer = gateway.generate_llm_answer(
                        text, evidence=[], knowledge=knowledge_items, intent_id=intent_id, jurisdiction_codes=[],
                    )
                    allowed_ids = set()  # public knowledge carries no evidence ids to cite
                    validation = guardrails.validate_grounded_response(llm_answer, allowed_ids)
                    if validation["passed"]:
                        answer_text = llm_answer.get("answer") or NO_MATCH_FALLBACK
                    else:
                        top = kb_candidates[0][1]
                        answer_text = f"{top.summary}\n\n{top.body}"
                except Exception:  # noqa: BLE001 — gateway failure falls back to the deterministic KB text below
                    top = kb_candidates[0][1]
                    answer_text = f"{top.summary}\n\n{top.body}"
            else:
                top = kb_candidates[0][1]
                answer_text = f"{top.summary}\n\n{top.body}"
            sources = [{"title": item.title, "authority": item.authority} for _score, item in kb_candidates]

    db.add(AssistPublicMessage(session_id=session.id, role="assistant", content=answer_text))
    db.commit()

    return {"session_id": session.id, "intent_id": intent_id, "answer": answer_text, "sources": sources}

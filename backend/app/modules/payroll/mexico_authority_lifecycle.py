"""
modules/payroll/mexico_authority_lifecycle.py
---------------------------------------------
The state machines, append-only events and the UNKNOWN rule shared by every
Mexico Phase 8 object (docs/mexico/MEXICO_PHASE_8_PLAN.md §4, B7):

  MOVEMENT    PENDING -> EXPORTED -> FILED -> ACCEPTED | REJECTED
  LIABILITY   ACCRUED -> FILED -> PAID -> RECONCILED
  ISN_RETURN  DRAFT -> FILED -> ACCEPTED | REJECTED
  SUA_PERIOD  DRAFT -> RECONCILED -> PAID

Each object has ONE transmission step — the moment something leaves Zoiko
(the operator uploads the worklist / submits the declaration or return / pays
through SIPARE). If its outcome is not known the object is UNKNOWN, never
FAILED (MX-043). The way out (Phase 7 §4.2 rule, file-export mode D1):

  1. record a status check — FOUND (with the authority's reference: the
     object moves on) or NOT_FOUND (recorded, nothing moves);
  2. after a NOT_FOUND, an admin confirms a retry with a reason: the SAME
     row, payload hash and idempotency key go back to the pre-transmission
     state (RETRY_READY);
  3. a late FOUND while the retry is still unsent adopts the reference —
     nothing is transmitted twice.

"Definitively not found" needs channel config with no default
(mexico_content.MX_AUTHORITY_RETRY_CONFIG, empty), so nothing ever retries
automatically.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries import mexico_content as _content
from app.modules.payroll.engine.countries.mexico import MXBlock

_SPECS = {
    "MOVEMENT": {
        "model": "PayrollMxImssMovement", "label": "IMSS movement", "channel": "IDSE",
        "transitions": {"PENDING": {"EXPORTED", "WITHDRAWN", "VOIDED", "FILED"},
                        "EXPORTED": {"FILED", "REJECTED", "UNKNOWN"},
                        "FILED": {"ACCEPTED", "REJECTED"},
                        "UNKNOWN": {"FILED", "REJECTED", "PENDING"}},
        "sent_from": "EXPORTED", "found_to": "FILED", "retry_to": "PENDING", "ref_field": "authority_reference"},
    "LIABILITY": {
        "model": "PayrollMxAuthorityLiability", "label": "authority liability", "channel": "DECLARATION",
        "transitions": {"ACCRUED": {"FILED", "UNKNOWN", "WITHDRAWN"},
                        "FILED": {"PAID"},
                        "PAID": {"RECONCILED"},
                        "UNKNOWN": {"FILED", "ACCRUED"},
                        "WITHDRAWN": {"ACCRUED"}},          # only if never sent (re-commit after a reset)
        "sent_from": "ACCRUED", "found_to": "FILED", "retry_to": "ACCRUED", "ref_field": "declaration_reference"},
    "ISN_RETURN": {
        "model": "PayrollMxIsnReturn", "label": "ISN return", "channel": "ISN",
        "transitions": {"DRAFT": {"FILED", "UNKNOWN", "WITHDRAWN"},
                        "FILED": {"ACCEPTED", "REJECTED"},
                        "UNKNOWN": {"FILED", "DRAFT"},
                        "WITHDRAWN": {"DRAFT"}},
        "sent_from": "DRAFT", "found_to": "FILED", "retry_to": "DRAFT", "ref_field": "filing_reference"},
    "SUA_PERIOD": {
        "model": "PayrollMxSuaPeriod", "label": "SUA period", "channel": "SIPARE",
        "transitions": {"DRAFT": {"RECONCILED", "WITHDRAWN"},
                        "RECONCILED": {"PAID", "UNKNOWN"},
                        "UNKNOWN": {"PAID", "RECONCILED"},
                        "WITHDRAWN": {"DRAFT"}},
        "sent_from": "RECONCILED", "found_to": "PAID", "retry_to": "RECONCILED", "ref_field": "payment_reference"},
    "SUA_DIFFERENCE": {
        "model": "PayrollMxSuaDifference", "label": "SUA difference", "channel": None,
        "transitions": {"OPEN": {"EXPLAINED"}, "EXPLAINED": {"APPROVED", "OPEN"}}},
}
ENTITY_TYPES = tuple(k for k in _SPECS if k != "SUA_DIFFERENCE")


def now():
    return datetime.now(timezone.utc)


def models():
    from app.modules.payroll import models as m

    return m


def spec(entity_type: str) -> dict:
    if entity_type not in _SPECS:
        raise BadRequestException(f"Unknown Mexico authority object type {entity_type!r}")
    return _SPECS[entity_type]


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=_json_default).encode()).hexdigest()


def idempotency_key(prefix: str, *parts) -> str:
    return f"{prefix}-" + hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:56]


def load(db: Session, entity_type: str, org_id: int, entity_id: int):
    m = models()
    model = getattr(m, spec(entity_type)["model"])
    obj = db.get(model, entity_id)
    if obj is None:
        raise NotFoundException(f"{spec(entity_type)['label'].capitalize()} {entity_id} not found")
    owner = (db.get(m.PayrollMxSuaPeriod, obj.sua_period_id).organization_id if entity_type == "SUA_DIFFERENCE"
             else obj.organization_id)
    if owner != org_id:
        raise NotFoundException(f"{spec(entity_type)['label'].capitalize()} {entity_id} not found")
    return obj


def event(db: Session, org_id: int, entity_type: str, obj, event_type: str, actor_id=None, detail=None,
          from_status=None, to_status=None):
    m = models()
    db.add(m.PayrollMxAuthorityEvent(organization_id=org_id, entity_type=entity_type, entity_id=obj.id,
                                     event_type=event_type, from_status=from_status, to_status=to_status,
                                     payload_hash=getattr(obj, "payload_hash", None), detail=detail,
                                     actor_id=actor_id))


def transition(db: Session, org_id: int, entity_type: str, obj, to: str, event_type: str, actor_id=None,
               detail=None):
    frm = obj.status
    if to not in spec(entity_type)["transitions"].get(frm, set()):
        raise MXBlock("MX_AUTHORITY_ILLEGAL_TRANSITION",
                      f"a {spec(entity_type)['label']} cannot go from {frm} to {to}", org_id)
    obj.status = to
    if hasattr(obj, "unknown_since"):
        if to == "UNKNOWN":
            obj.unknown_since = now()
        elif frm == "UNKNOWN":
            obj.unknown_since = None
    event(db, org_id, entity_type, obj, event_type, actor_id, detail, frm, to)


def events(db: Session, entity_type: str, obj) -> list:
    m = models()
    E = m.PayrollMxAuthorityEvent
    db.flush()                                    # autoflush is off: include events added in this transaction
    return (db.query(E).filter(E.entity_type == entity_type, E.entity_id == obj.id).order_by(E.id).all())


def event_views(db: Session, entity_type: str, obj) -> list:
    return [{"id": e.id, "type": e.event_type, "from": e.from_status, "to": e.to_status, "detail": e.detail,
             "actorId": e.actor_id, "at": e.occurred_at.isoformat() if e.occurred_at else None}
            for e in events(db, entity_type, obj)]


def require_different(actor_id, other_id, what: str, org_id=None) -> None:
    """Four-eyes (D6): the checker is not the maker."""
    if actor_id is not None and other_id is not None and actor_id == other_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", f"{what} must be done by a different person", org_id)


def require_reference(reference: Optional[str], what: str) -> str:
    ref = (reference or "").strip()
    if not ref:
        raise BadRequestException(f"{what} needs the authority's reference (acuse / folio / payment reference)")
    return ref[:120]


# ── the UNKNOWN rule (B7) ───────────────────────────────────────────────────

def _since_unknown(db: Session, entity_type: str, obj) -> list:
    evs = events(db, entity_type, obj)
    start = 0
    for i, e in enumerate(evs):
        if e.to_status == "UNKNOWN":
            start = i
    return evs[start:]


def _retry_pending(db: Session, entity_type: str, obj) -> bool:
    """A confirmed retry not yet re-sent: the last event is RETRY_READY."""
    evs = events(db, entity_type, obj)
    return bool(evs) and evs[-1].event_type == "RETRY_READY"


def mark_unknown(db: Session, org_id: int, entity_type: str, obj, actor_id, note: Optional[str] = None) -> None:
    """The transmission step happened but its outcome is not known."""
    sp = spec(entity_type)
    if obj.status != sp["sent_from"]:
        raise BadRequestException(f"Only a {sp['label']} in {sp['sent_from']} can be recorded as UNKNOWN")
    freeze(entity_type, obj)
    transition(db, org_id, entity_type, obj, "UNKNOWN", "UNKNOWN_RECORDED", actor_id,
               {"note": (note or "").strip()[:300] or None})


def record_status_check(db: Session, org_id: int, entity_type: str, obj, found: bool, reference: Optional[str],
                        actor_id, evidence_ref: Optional[str] = None) -> None:
    sp = spec(entity_type)
    late = obj.status == sp["retry_to"] and _retry_pending(db, entity_type, obj)
    if obj.status != "UNKNOWN" and not late:
        raise BadRequestException(f"A status check applies only to an UNKNOWN {sp['label']} (or one whose "
                                  "confirmed retry has not been sent yet)")
    if not found:
        if late:
            raise BadRequestException("A retry is already confirmed; only a FOUND answer can still be recorded")
        event(db, org_id, entity_type, obj, "STATUS_NOT_FOUND", actor_id,
              {"evidenceRef": (evidence_ref or "")[:200] or None})
        return
    ref = require_reference(reference, "A FOUND answer")
    setattr(obj, sp["ref_field"], ref)
    if evidence_ref and hasattr(obj, "evidence_ref"):
        obj.evidence_ref = evidence_ref[:200]
    transition(db, org_id, entity_type, obj, sp["found_to"], "LATE_FOUND" if late else "STATUS_FOUND", actor_id,
               {"reference": ref})
    if entity_type == "ISN_RETURN":
        from app.modules.payroll import mexico_filing_service

        mexico_filing_service._file_isn_liabilities(db, org_id, obj, ref, actor_id)   # as a normal filing does


def not_found_checks(db: Session, entity_type: str, obj) -> int:
    return sum(1 for e in _since_unknown(db, entity_type, obj) if e.event_type == "STATUS_NOT_FOUND")


def definitively_not_found(db: Session, entity_type: str, obj, channel: Optional[str] = None) -> bool:
    """Never true without channel config (no default) — see the module doc."""
    cfg = _content.MX_AUTHORITY_RETRY_CONFIG.get(channel or spec(entity_type)["channel"])
    if not cfg or int(cfg.get("min_not_found_checks") or 0) < 2 or int(cfg.get("min_wait_seconds") or 0) <= 0:
        return False
    if obj.status != "UNKNOWN" or obj.unknown_since is None:
        return False
    since = obj.unknown_since if obj.unknown_since.tzinfo else obj.unknown_since.replace(tzinfo=timezone.utc)
    return (not_found_checks(db, entity_type, obj) >= int(cfg["min_not_found_checks"])
            and (now() - since).total_seconds() >= int(cfg["min_wait_seconds"]))


def confirm_retry(db: Session, org_id: int, entity_type: str, obj, actor_id, reason: str) -> None:
    sp = spec(entity_type)
    if obj.status != "UNKNOWN":
        raise BadRequestException(f"Only an UNKNOWN {sp['label']} can be retried")
    if not_found_checks(db, entity_type, obj) < 1:
        raise MXBlock("MX_AUTHORITY_STATUS_CHECK_REQUIRED",
                      "record a status check first — a retry is never sent blind (MX-043)", org_id)
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A confirmed retry needs a reason")
    event(db, org_id, entity_type, obj, "OPERATOR_RETRY_CONFIRMED", actor_id,
          {"reason": text[:300], "definitive": definitively_not_found(db, entity_type, obj)})
    # Same row, same payload hash, same idempotency key — nothing is regenerated.
    transition(db, org_id, entity_type, obj, sp["retry_to"], "RETRY_READY", actor_id)


def freeze(entity_type: str, obj) -> None:
    """Record the payload hash of what leaves Zoiko the first time; a retry
    must send exactly the same facts."""
    current = payload_hash(payload_of(entity_type, obj))
    if obj.payload_hash is None:
        obj.payload_hash = current
    elif obj.payload_hash != current:
        raise MXBlock("MX_AUTHORITY_PAYLOAD_CHANGED",
                      f"this {spec(entity_type)['label']} was already transmitted with different figures — "
                      "a retry must resend the same payload", getattr(obj, "organization_id", None))


def payload_of(entity_type: str, obj) -> dict:
    if entity_type == "MOVEMENT":
        return {"type": obj.movement_type, "registration": obj.registration_id, "employee": obj.employee_id,
                "eventDate": obj.event_date, "sbc": obj.sbc, "key": obj.idempotency_key}
    if entity_type == "LIABILITY":
        return {"authority": obj.authority, "scope": obj.scope_key, "period": obj.period_key,
                "sequence": obj.sequence, "amount": obj.amount, "key": obj.idempotency_key}
    if entity_type == "ISN_RETURN":
        return {"state": obj.state_code, "period": obj.period_key, "sequence": obj.sequence,
                "base": obj.base_total, "amount": obj.amount, "key": obj.idempotency_key}
    if entity_type == "SUA_PERIOD":
        return {"registration": obj.registration_id, "period": obj.period_key, "zoiko": obj.zoiko_totals,
                "key": obj.idempotency_key}
    raise BadRequestException(f"{entity_type} has no transmission payload")


def unknown_view(db: Session, entity_type: str, obj) -> Optional[dict]:
    if obj.status != "UNKNOWN" and not (obj.status == spec(entity_type).get("retry_to")
                                        and _retry_pending(db, entity_type, obj)):
        return None
    return {"notFoundChecks": not_found_checks(db, entity_type, obj) if obj.status == "UNKNOWN" else None,
            "retryPending": obj.status != "UNKNOWN",
            "channelConfig": bool(_content.MX_AUTHORITY_RETRY_CONFIG.get(spec(entity_type)["channel"])),
            "definitive": definitively_not_found(db, entity_type, obj)}

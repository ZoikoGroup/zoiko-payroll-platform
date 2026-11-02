"""
japan_lifecycle.py — Japan social-insurance lifecycle events (ZP-JP-ENG-001
§5, §11; JP-010, JP-011; Phase 4).

  * record_event         a CREATED event (qualification, loss, annual
                         determination, ad hoc revision, bonus, exemption,
                         return-to-work revision); an exemption needs evidence;
  * approve_event        four-eyes: the approver is never the creator;
  * apply_approved_event an APPROVED SMR revision becomes a NEW enrolment
                         version from the event date; the old version keeps
                         its history and is end-dated, never edited in place;
  * record_bonus_obligation the JPS bonus report obligation (SBA, payment date,
                         due date) taken from a calculated jp_result.

Nothing here calculates: SMR proposals come from
engine/jurisdictions/japan/smr_lifecycle.py, the SBA and due date from the
engine's bonus path. No route calls this module yet (Phase 5).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

EVENT_TYPES = ("QUALIFICATION", "LOSS", "ANNUAL_DETERMINATION", "ADHOC_REVISION", "BONUS",
               "MATERNITY_EXEMPTION", "CHILDCARE_EXEMPTION", "RETURN_TO_WORK_REVISION")
EXEMPTION_EVENTS = ("MATERNITY_EXEMPTION", "CHILDCARE_EXEMPTION")
# Event type -> the enrolment smr_basis it produces when applied.
SMR_REVISION_BASIS = {
    "ANNUAL_DETERMINATION": "ANNUAL_DETERMINATION",
    "ADHOC_REVISION": "ADHOC_REVISION",
    "RETURN_TO_WORK_REVISION": "RETURN_TO_WORK",
}
_SMR_FIELDS = ("smr_health_grade", "smr_health_amount", "smr_pension_grade", "smr_pension_amount")
_COPIED_FIELDS = ("legal_entity_id", "health_eligible", "pension_eligible", "health_insurer_code",
                  "smr_health_grade", "smr_pension_grade", "smr_health_amount", "smr_pension_amount",
                  "care_state", "child_support_state", "qualification_date", "loss_date")
ENTITY = "jp_social_insurance_event"


def _models():
    from app.modules.payroll import models

    return models


def _audit(db, actor_id, action, entity_id, old=None, new=None, reason=None):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=ENTITY, entity_id=entity_id,
                     old_value=old, new_value=new, reason=reason, auto_commit=False)


def _as_date(value, field):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _event(db, organization_id, event_id):
    m = _models()
    event = (db.query(m.PayrollJpSocialInsuranceEvent)
             .filter(m.PayrollJpSocialInsuranceEvent.id == event_id,
                     m.PayrollJpSocialInsuranceEvent.organization_id == organization_id)
             .first())
    if event is None:
        raise NotFoundException("Japan social-insurance event not found.")
    return event


def _snapshot(event):
    return {"event_type": event.event_type, "effective_from": event.effective_from.isoformat(),
            "effective_to": event.effective_to.isoformat() if event.effective_to else None,
            "submission_status": event.submission_status, "employee_id": event.employee_id}


def record_event(db: Session, *, organization_id: int, employee_id: int, event_type: str,
                 effective_from, actor_id: Optional[int], effective_to=None,
                 payload: Optional[dict] = None, evidence_ref: Optional[str] = None,
                 enrollment_id: Optional[int] = None):
    """Record a CREATED lifecycle event. An SMR revision carries the proposed
    grades / amounts in ``payload``; an exemption needs an evidence reference
    (JP-011)."""
    m = _models()
    kind = str(event_type or "").strip().upper()
    if kind not in EVENT_TYPES:
        raise BadRequestException(f"event_type must be one of {', '.join(EVENT_TYPES)}.")
    start = _as_date(effective_from, "effective_from")
    end = _as_date(effective_to, "effective_to") if effective_to else None
    if end is not None and end < start:
        raise BadRequestException("effective_to must not be before effective_from.")
    if kind in EXEMPTION_EVENTS and not (evidence_ref or "").strip():
        raise BadRequestException("An exemption event needs an evidence reference (JP-011).")
    if kind == "BONUS":
        raise BadRequestException("A bonus event is recorded from a calculated bonus "
                                  "(record_bonus_obligation), never typed.")
    data = dict(payload or {})
    if kind in SMR_REVISION_BASIS:
        data.update({key: str(value) if isinstance(value, Decimal) else value
                     for key, value in _smr_payload(data).items()})
    event = m.PayrollJpSocialInsuranceEvent(
        organization_id=organization_id, employee_id=employee_id, enrollment_id=enrollment_id,
        event_type=kind, effective_from=start, effective_to=end, payload=data or None,
        evidence_ref=(evidence_ref or None), created_by_id=actor_id, submission_status="CREATED")
    db.add(event)
    db.flush()
    _audit(db, actor_id, "created", event.id, new=_snapshot(event))
    return event


def _smr_payload(data: dict) -> dict:
    """An SMR revision names at least one scheme, each with grade AND amount."""
    out = {}
    for scheme in ("health", "pension"):
        grade, amount = data.get(f"smr_{scheme}_grade"), data.get(f"smr_{scheme}_amount")
        if grade is None and amount is None:
            continue
        if grade is None or amount is None:
            raise BadRequestException(f"An SMR revision needs both smr_{scheme}_grade and "
                                      f"smr_{scheme}_amount.")
        try:
            grade_value = int(grade)
            amount_value = Decimal(str(amount))
        except (TypeError, ValueError, InvalidOperation):
            raise BadRequestException(f"smr_{scheme}_grade must be whole and smr_{scheme}_amount "
                                      "a decimal amount.")
        if grade_value < 1 or amount_value <= 0 or amount_value != amount_value.to_integral_value():
            raise BadRequestException(f"smr_{scheme}_grade / smr_{scheme}_amount are out of range.")
        out[f"smr_{scheme}_grade"] = grade_value
        out[f"smr_{scheme}_amount"] = amount_value
    if not out:
        raise BadRequestException("An SMR revision needs a health or pension grade and amount.")
    return out


def approve_event(db: Session, *, organization_id: int, event_id: int, actor_id: Optional[int]):
    """CREATED -> APPROVED by a second person (four-eyes)."""
    from app.modules.payroll.service import require_four_eyes

    event = _event(db, organization_id, event_id)
    if event.submission_status != "CREATED":
        raise BadRequestException(f"Only a CREATED event can be approved (this one is "
                                  f"{event.submission_status}).")
    require_four_eyes(event.created_by_id, actor_id, "Approving a Japan social-insurance event",
                      db=db, entity_type=ENTITY, entity_id=event.id,
                      current_status=event.submission_status)
    if event.event_type in EXEMPTION_EVENTS and not (event.evidence_ref or "").strip():
        raise BadRequestException("An exemption event needs an evidence reference (JP-011).")
    before = _snapshot(event)
    event.submission_status = "APPROVED"
    event.approved_by_id = actor_id
    event.approved_at = datetime.now(timezone.utc)
    db.flush()
    _audit(db, actor_id, "approved", event.id, old=before, new=_snapshot(event))
    return event


def apply_approved_event(db: Session, *, organization_id: int, event_id: int,
                         actor_id: Optional[int]):
    """Apply an APPROVED SMR revision: a new ACTIVE enrolment version from the
    event date with the revised SMR; the version in force before it is
    end-dated the day before (its own months keep their SMR). Applying the
    same event twice is refused."""
    m = _models()
    Enrollment = m.PayrollJpSocialInsuranceEnrollment
    event = _event(db, organization_id, event_id)
    if event.event_type not in SMR_REVISION_BASIS:
        raise BadRequestException(f"A {event.event_type} event does not revise the enrolment.")
    if event.submission_status != "APPROVED":
        raise BadRequestException("Only an APPROVED event can be applied.")
    payload = dict(event.payload or {})
    if payload.get("applied_enrollment_id"):
        raise BadRequestException("This event has already been applied.")
    revised = _smr_payload(payload)
    start = event.effective_from

    current = (db.query(Enrollment)
               .filter(Enrollment.organization_id == organization_id,
                       Enrollment.employee_id == event.employee_id,
                       Enrollment.status == "ACTIVE",
                       Enrollment.effective_from <= start,
                       (Enrollment.effective_to.is_(None)) | (Enrollment.effective_to >= start))
               .all())
    if len(current) != 1:
        raise BadRequestException(f"{len(current)} ACTIVE enrolments are in force on {start}; "
                                  "exactly one is required.")
    old = current[0]
    later = (db.query(Enrollment)
             .filter(Enrollment.organization_id == organization_id,
                     Enrollment.employee_id == event.employee_id,
                     Enrollment.status == "ACTIVE",
                     Enrollment.effective_from > start)
             .count())
    if later:
        raise BadRequestException("A later enrolment version exists; apply revisions in date order.")
    if old.effective_from >= start:
        raise BadRequestException("The revision must start after the enrolment it revises.")

    new = Enrollment(organization_id=organization_id, employee_id=event.employee_id,
                     effective_from=start, effective_to=old.effective_to,
                     previous_version_id=old.id, created_by_id=event.created_by_id,
                     approved_by_id=event.approved_by_id, approved_at=event.approved_at,
                     evidence_ref=event.evidence_ref or old.evidence_ref,
                     smr_basis=SMR_REVISION_BASIS[event.event_type], status="ACTIVE")
    for field in _COPIED_FIELDS:
        setattr(new, field, getattr(old, field))
    for field, value in revised.items():
        setattr(new, field, value)
    old_before = {"effective_to": old.effective_to.isoformat() if old.effective_to else None}
    old.effective_to = start - timedelta(days=1)
    db.add(new)
    db.flush()

    payload["applied_enrollment_id"] = new.id
    event.payload = payload
    event.enrollment_id = new.id
    db.flush()
    _audit(db, actor_id, "applied", event.id, old=old_before,
           new={"enrollment_id": new.id, "previous_version_id": old.id,
                "effective_from": start.isoformat(),
                **{k: str(v) for k, v in revised.items()}})
    return new


def record_bonus_obligation(db: Session, *, organization_id: int, employee_id: int,
                            jp_result: dict, paid_on, actor_id: Optional[int]):
    """The JPS bonus payment report obligation from a calculated bonus
    (jp_result["jp_bonus"]): SBA, payment date, due date. One per employee
    and payment date; a second call with the same figures returns it, with
    different figures it is refused."""
    m = _models()
    Event = m.PayrollJpSocialInsuranceEvent
    bonus = (jp_result or {}).get("jp_bonus")
    if not bonus:
        raise BadRequestException("The calculation has no bonus.")
    if not bonus.get("jp_bonus_report_due"):
        raise BadRequestException("The bonus has no JPS report obligation (the employee is not insured).")
    paid = _as_date(paid_on, "paid_on")
    sba = Decimal(str(bonus["jp_bonus_sba"]))
    due = _as_date(bonus["jp_bonus_report_due"], "jp_bonus_report_due")
    if due < paid:
        raise BadRequestException("The bonus report due date is before the payment date.")
    existing = (db.query(Event)
                .filter(Event.organization_id == organization_id, Event.employee_id == employee_id,
                        Event.event_type == "BONUS", Event.bonus_paid_on == paid,
                        Event.submission_status != "REJECTED")
                .first())
    if existing is not None:
        if Decimal(existing.sba_amount) == sba and existing.report_due_on == due:
            return existing
        raise BadRequestException("A different bonus obligation is already recorded for this payment "
                                  "date; correct it instead of recording a second one.")
    event = Event(organization_id=organization_id, employee_id=employee_id, event_type="BONUS",
                  effective_from=paid, bonus_paid_on=paid, sba_amount=sba, report_due_on=due,
                  payload={"healthSbaBase": bonus.get("jp_bonus_health_sba_base"),
                           "pensionSbaBase": bonus.get("jp_bonus_pension_sba_base")},
                  created_by_id=actor_id, submission_status="CREATED")
    db.add(event)
    db.flush()
    _audit(db, actor_id, "created", event.id, new=_snapshot(event))
    return event

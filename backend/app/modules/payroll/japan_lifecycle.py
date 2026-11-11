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

import json
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
                        Event.submission_status.notin_(("REJECTED", "CORRECTED")))
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


# ── Phase 8: run exceptions (four-eyes) ─────────────────────────────────────
# Each exception is computed from the run's frozen snapshots; an approval is a
# payroll_jp_run_exceptions row bound to the run's payload fingerprint at the
# time, so a later change to the payslips needs a fresh approval.
JP_RUN_EXCEPTION_CODES = (
    "FIRST_OR_LAST_PAYROLL", "BONUS_PAYMENT", "YEA_DIFFERENCE_APPLIED",
    "RESIDENT_NOTICE_CHANGED_AFTER_CALC", "ATTENDANCE_APPROVAL_STALE",
    "BANK_CHANGE_HISTORY_UNAVAILABLE", "PAYLOAD_CHANGED_AFTER_APPROVAL",
)
_OPEN_RUN_STATUSES = ("Draft", "Review")
_COMMITTED_RUN_STATUSES = ("Paid", "Closed")
JP_CORRECTION_MARKER = "[JP-CORRECTION]"
# Inputs a correction may restate in the frozen context.
JP_CORRECTABLE_INPUTS = frozenset({"gross", "basic", "overtime", "jp_components"})


def _audit_as(db, entity_type, actor_id, action, entity_id, old=None, new=None):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     old_value=old, new_value=new, auto_commit=False)


def _run_status(run) -> str:
    return str(getattr(run.status, "value", run.status))


def _run_or_404(db: Session, organization_id: int, run_id: int):
    from app.modules.payroll.models import PayrollRun

    run = (db.query(PayrollRun)
           .filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise NotFoundException("Payroll run not found.")
    return run


def _jp_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == "JP")
            .order_by(PayslipItem.id).all())


def jp_run_exceptions(db: Session, run) -> list:
    """[{code, employeeId, key, detail, approved}] for one run."""
    from app.modules.payroll import japan_service as svc
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    m = _models()
    found = []

    def add(code, employee_id, detail):
        found.append({"code": code, "employeeId": employee_id, "detail": detail,
                      "key": f"{code}:{employee_id or 'RUN'}"})

    items = _jp_items(db, run)
    for item in items:
        snap = item.jp_calculation_snapshot or {}
        frozen = snap.get("frozenContext") or {}
        earlier = (db.query(PayslipItem.id).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
                   .filter(PayslipItem.employee_id == item.employee_id, PayslipItem.country_code == "JP",
                           PayslipItem.payroll_run_id != run.id,
                           PayrollRun.status.in_(_COMMITTED_RUN_STATUSES),
                           PayrollRun.pay_date < run.pay_date).first())
        leaving = getattr(db.get(PayrollEmployee, item.employee_id), "date_of_leaving", None)
        if earlier is None:
            add("FIRST_OR_LAST_PAYROLL", item.employee_id, "first committed Japan payroll for the employee")
        elif leaving is not None and run.period_start and run.period_end \
                and run.period_start <= leaving <= run.period_end:
            add("FIRST_OR_LAST_PAYROLL", item.employee_id, f"last payroll (leaving {leaving.isoformat()})")
        if snap.get("jp_bonus"):
            add("BONUS_PAYMENT", item.employee_id,
                f"bonus {snap['jp_bonus'].get('jp_bonus')} with withholding {snap['jp_bonus'].get('jp_bonus_wht')}")
        if snap.get("jp_yea_difference") is not None:
            add("YEA_DIFFERENCE_APPLIED", item.employee_id,
                f"year-end adjustment difference {snap['jp_yea_difference']} settled in this payment")
        frozen_notices = sorted(int(r["id"]) for r in frozen.get("residentTaxAssessments") or []
                                if r and r.get("id") is not None)
        live_notices = sorted(r.id for r in db.query(m.PayrollJpResidentTaxAssessment.id).filter(
            m.PayrollJpResidentTaxAssessment.organization_id == run.organization_id,
            m.PayrollJpResidentTaxAssessment.employee_id == item.employee_id,
            m.PayrollJpResidentTaxAssessment.status.in_(("APPROVED", "SUPERSEDED"))).all())
        if frozen and frozen_notices != live_notices:
            add("RESIDENT_NOTICE_CHANGED_AFTER_CALC", item.employee_id,
                "a resident-tax notice was approved or replaced after this payslip was calculated")
        attendance = frozen.get("attendance") or {}
        if attendance.get("approved") and run.period_start and run.period_end and not svc._jp_hours_approved(
                db, run.organization_id, item.employee_id, run.period_start, run.period_end):
            add("ATTENDANCE_APPROVAL_STALE", item.employee_id,
                "the attendance changed after its approval; the calculated hours are no longer approved facts")
    if items:
        add("BANK_CHANGE_HISTORY_UNAVAILABLE", None,
            "the platform records no bank-detail change history, so a change near pay day cannot be ruled "
            "out: confirm the bank details independently")
    current = svc.jp_approval_fingerprint(db, run)
    stored = getattr(run, "jp_approval_fingerprint", None)
    if stored and current and stored != current:
        add("PAYLOAD_CHANGED_AFTER_APPROVAL", None,
            f"the payslips changed since the approval of {stored[:12]} (now {current[:12]})")
    approvals = {row.exception_key: row for row in db.query(m.PayrollJpRunException).filter(
        m.PayrollJpRunException.run_id == run.id,
        m.PayrollJpRunException.payload_fingerprint == (current or ""))}
    for e in found:
        assert e["code"] in JP_RUN_EXCEPTION_CODES, e["code"]
        row = approvals.get(e["key"])
        e["approved"] = None if row is None else {
            "approvedById": row.approved_by_id, "approvedAt": row.approved_at.isoformat(), "note": row.note}
    return found


def list_jp_run_exceptions(db: Session, organization_id: int, run_id: int) -> list:
    return jp_run_exceptions(db, _run_or_404(db, organization_id, run_id))


def approve_jp_run_exception(db: Session, *, organization_id: int, run_id: int, key: str,
                             approver_id: Optional[int], note: Optional[str] = None) -> dict:
    """A second person's approval of one exception of an open run. The run's
    preparer can never approve its own run's exceptions."""
    from app.modules.payroll import japan_service as svc

    m = _models()
    run = _run_or_404(db, organization_id, run_id)
    if _run_status(run).upper() not in {s.upper() for s in _OPEN_RUN_STATUSES}:
        raise BadRequestException("Exceptions are approved before the run is approved.")
    if approver_id is None or approver_id == run.created_by:
        raise BadRequestException("The run's preparer cannot approve its exceptions; a second person must.")
    match = next((e for e in jp_run_exceptions(db, run) if e["key"] == key), None)
    if match is None:
        raise NotFoundException("Japan run exception not found.")
    if match["approved"]:
        return match
    row = m.PayrollJpRunException(
        organization_id=organization_id, run_id=run.id, exception_key=key, code=match["code"],
        employee_id=match["employeeId"], detail=match["detail"][:2000],
        payload_fingerprint=svc.jp_approval_fingerprint(db, run) or "",
        note=(note or "").strip()[:500] or None, approved_by_id=approver_id,
        approved_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    _audit_as(db, "jp_run_exception", approver_id, "approved", row.id, new={"runId": run.id, "key": key})
    return {**match, "approved": {"approvedById": approver_id, "approvedAt": row.approved_at.isoformat(),
                                  "note": row.note}}


# ── Phase 8: corrections (JP-006) ───────────────────────────────────────────
def _correction_chain(db: Session, original) -> list:
    from app.modules.payroll.models import PayslipItem

    return [i for i in db.query(PayslipItem).filter(PayslipItem.employee_id == original.employee_id,
                                                    PayslipItem.country_code == "JP").order_by(PayslipItem.id)
            if ((i.jp_calculation_snapshot or {}).get("correction") or {}).get("originalPayslipId") == original.id]


def _correction_policy(frozen: dict) -> str:
    row = (frozen.get("rateMap") or {}).get("jp_correction_policy") or {}
    return str(row.get("text_value") or "").strip().upper()


def _totals(result) -> dict:
    jp = getattr(result, "jp_result", None) or {}
    return {"tds": Decimal(str(getattr(result, "tds", 0) or 0)),
            "employee": Decimal(str(jp.get("jp_employee_total") or 0)),
            "employer": Decimal(str(jp.get("jp_employer_total") or 0))}


def create_jp_correction(db: Session, *, organization_id: int, payslip_item_id: int, reason: str,
                         changes: dict, actor_id: Optional[int]) -> dict:
    """Append-only correction of a committed Japan payslip (JP-006): BLOCKS
    while jp_correction_policy is not signed as DELTA_PAYSLIP. Otherwise the
    frozen context is replayed (and must reproduce the original), the declared
    inputs are restated, and the difference is booked as a delta payslip in a
    linked PAID correction run. The original is never edited; its bonus report
    event is marked CORRECTED and a new one recorded."""
    from app.modules.payroll import japan_service as svc
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem, PayslipStatus

    if not (reason or "").strip():
        raise BadRequestException("A correction needs a reason.")
    changes = dict(changes or {})
    if not changes:
        raise BadRequestException("Declare at least one corrected input.")
    undeclared = sorted(set(changes) - JP_CORRECTABLE_INPUTS)
    if undeclared:
        raise BadRequestException(f"not correctable: {undeclared} (allowed: {sorted(JP_CORRECTABLE_INPUTS)})")
    item = (db.query(PayslipItem)
            .filter(PayslipItem.id == payslip_item_id, PayslipItem.organization_id == organization_id).first())
    if item is None or (item.country_code or "").upper() != "JP":
        raise NotFoundException("Japan payslip not found.")
    snapshot = item.jp_calculation_snapshot or {}
    if snapshot.get("correction"):
        raise BadRequestException("Correct the original payslip, not a correction delta.")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).one()
    if _run_status(run).upper() not in {s.upper() for s in _COMMITTED_RUN_STATUSES}:
        raise BadRequestException("Only a committed (Paid) payslip is corrected; recalculate an open run instead.")
    frozen = snapshot.get("frozenContext")
    if not frozen:
        raise BadRequestException("This payslip has no frozen calculation context, so it cannot be replayed.")
    policy = _correction_policy(frozen)
    if policy != "DELTA_PAYSLIP":
        raise BadRequestException(f"Corrections are blocked: jp_correction_policy is {policy or 'not configured'} "
                                  "(JP-006, signed at G2).")
    original = svc.jp_replay(frozen)
    if Decimal(str(original.tds or 0)) != Decimal(str(item.tds or 0)):
        raise BadRequestException("Replaying the frozen context does not reproduce the original payslip; "
                                  "refusing to correct on a drifted basis.")

    chain = _correction_chain(db, item)
    last = (chain[-1].jp_calculation_snapshot or {}) if chain else snapshot
    basis = last.get("frozenContext") or frozen
    new_frozen = json.loads(json.dumps(basis))
    for key, value in changes.items():
        new_frozen["ctx"][key] = svc._json_safe(value)
    result = svc.jp_replay(new_frozen)
    effective = _totals(svc.jp_replay(basis))
    new_totals = _totals(result)
    deltas = {k: new_totals[k] - effective[k] for k in new_totals}
    gross_delta = (Decimal(str(new_frozen["ctx"].get("gross") or 0))
                   - Decimal(str(basis["ctx"].get("gross") or 0)))
    if not any(deltas.values()) and gross_delta == 0:
        raise BadRequestException("The corrected inputs produce no change; nothing to correct.")
    deduction_delta = deltas["tds"] + deltas["employee"]

    corr_run = PayrollRun(
        organization_id=organization_id, period_label=run.period_label, period_start=run.period_start,
        period_end=run.period_end, pay_date=run.pay_date, status=PayrollStatus.PAID.value,
        notes=f"{JP_CORRECTION_MARKER} corrects run {run.id} payslip {item.id}: {reason.strip()}"[:2000],
        created_by=actor_id)
    db.add(corr_run)
    db.flush()
    jp_result = dict(getattr(result, "jp_result", None) or {})
    new_item = PayslipItem(
        organization_id=organization_id, payroll_run_id=corr_run.id, employee_id=item.employee_id,
        employee_name=item.employee_name, country_code="JP", gross_pay=gross_delta, tds=deltas["tds"],
        total_deductions=deduction_delta, net_pay=gross_delta - deduction_delta,
        status=PayslipStatus.PAID.value, notes=f"Correction delta of payslip {item.id}",
        jp_calculation_snapshot=svc._json_safe({
            **jp_result,
            "correction": {"originalPayslipId": item.id, "originalRunId": run.id,
                           "correctionRunId": corr_run.id, "sequence": len(chain) + 1,
                           "reason": reason.strip(), "changes": changes,
                           "deltas": {k: str(v) for k, v in deltas.items()}, "grossDelta": str(gross_delta),
                           "actorId": actor_id},
            "frozenContext": new_frozen}))
    db.add(new_item)
    db.flush()

    bonus_action = None
    if (last.get("jp_bonus") or {}) != (jp_result.get("jp_bonus") or {}) and run.pay_date:
        m = _models()
        old = (db.query(m.PayrollJpSocialInsuranceEvent)
               .filter(m.PayrollJpSocialInsuranceEvent.organization_id == organization_id,
                       m.PayrollJpSocialInsuranceEvent.employee_id == item.employee_id,
                       m.PayrollJpSocialInsuranceEvent.event_type == "BONUS",
                       m.PayrollJpSocialInsuranceEvent.bonus_paid_on == run.pay_date,
                       m.PayrollJpSocialInsuranceEvent.submission_status.notin_(("REJECTED", "CORRECTED")))
               .first())
        if old is not None:
            old.submission_status = "CORRECTED"
            db.flush()
        new_event = None
        if jp_result.get("jp_bonus"):
            new_event = record_bonus_obligation(db, organization_id=organization_id, employee_id=item.employee_id,
                                                jp_result=jp_result, paid_on=run.pay_date, actor_id=actor_id)
        bonus_action = {"correctedEventId": getattr(old, "id", None), "newEventId": getattr(new_event, "id", None)}
    _audit_as(db, "jp_payslip_correction", actor_id, "corrected", item.id,
           new={"correctionRunId": corr_run.id, "payslipId": new_item.id,
                "deltas": {k: str(v) for k, v in deltas.items()}})
    return {"correctionRunId": corr_run.id, "payslipId": new_item.id, "originalPayslipId": item.id,
            "sequence": len(chain) + 1, "deltas": {k: str(v) for k, v in deltas.items()},
            "grossDelta": str(gross_delta), "bonus": bonus_action}

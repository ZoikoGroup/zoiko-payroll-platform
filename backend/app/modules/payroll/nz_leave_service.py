"""New Zealand Holidays Act — entitlements and leave records (ZP-NZ-ENG-001
Phase 5; spec §8, §10, NZ-016, NZ-023).

  employments            one instance per employment; the anniversary anchor
                         (a rehire is a NEW instance unless continuity is
                         evidenced), four-eyes approval.
  vest_entitlements      idempotent vesting of annual (weeks), sick and family-
                         violence (days) entitlements from the signed pack.
  leave events           the generic leave request, once approved, becomes an
                         NZ leave event consuming the legal entitlement (FIFO);
                         an insufficient entitlement refuses the approval.
  public holidays        per-employee otherwise-working-day decisions, hours on
                         the holiday (midnight crossing) and the alternative
                         holiday they earn (one entitlement per decision).
  gross-earnings ledger  Holidays Act gross earnings per PAID payslip.
  family violence        no reason text is ever accepted or stored; events are
                         restricted, visible only with NZ_FAMILY_VIOLENCE_VIEW
                         and every restricted read is access-logged.

Pay for leave and public holidays is Phase 6. The generic allocation JSON is a
planning view only — never the legal entitlement for New Zealand.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs

NZ = "NZ"
NZ_FAMILY_VIOLENCE_VIEW = "NZ_FAMILY_VIOLENCE_VIEW"
RESTRICTED_LEAVE_LABEL = "restricted"
FAMILY_VIOLENCE_REQUEST = "nz_family_violence"
# Generic leave_type (payroll_leave_requests.leave_type) -> Holidays Act type.
NZ_REQUEST_TYPES = {"annual": "ANNUAL", "sick": "SICK", "nz_bereavement_close": "BEREAVEMENT_CLOSE",
                    "nz_bereavement_other": "BEREAVEMENT_OTHER", FAMILY_VIOLENCE_REQUEST: "FAMILY_VIOLENCE",
                    "nz_alternative": "ALTERNATIVE"}
# Generic leave types that are not Holidays Act leave and pass through untouched.
NZ_PASSTHROUGH_TYPES = ("unpaid",)
# Operational lookback for the otherwise-working-day history test; a mixed or
# empty history is UNDETERMINED and needs an evidenced operator decision.
HISTORY_LOOKBACK_WEEKS = 13
ACCESS_PURPOSE = "NZ_FAMILY_VIOLENCE_LEAVE"
EMPLOYMENT_FIELDS = ("start_date", "continuity_rule", "prior_employment_id", "payg_eligible", "payg_basis",
                     "payg_agreement_ref", "legal_entity_id", "evidence_ref")
DECISION_FIELDS = ("otherwise_working_day", "owd_evidence_ref", "worked", "shift_start", "shift_end", "timezone")
_QTY = Decimal("0.0001")


def _engine():
    from app.modules.payroll.engine.jurisdictions.new_zealand import holidays_act

    return holidays_act


def _conflict(message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"New Zealand: {message}")


def _iso(value):
    return value.isoformat() if value is not None else None


def _num(value) -> Optional[str]:
    return None if value is None else format(Decimal(str(value)).normalize(), "f")


def public_leave_type(leave_type) -> Optional[str]:
    """The leave type any shared surface (attendance, allocation, logs, email)
    may show: family-violence leave is never named outside the restricted
    NZ records (NZ-023)."""
    return RESTRICTED_LEAVE_LABEL if leave_type == FAMILY_VIOLENCE_REQUEST else leave_type


def is_nz_employee(db: Session, organization_id: int, employee) -> bool:
    from app.modules.payroll.service import _resolve_employee_country

    if employee is None:
        return False
    try:
        return _resolve_employee_country(db, organization_id, getattr(employee, "country_code", None)) == NZ
    except Exception:  # an org with no jurisdiction configured yet is not New Zealand
        return False


# ── employments (spec §10) ──────────────────────────────────────────────────
def _employment(db: Session, organization_id: int, row_id: int):
    m = nzs._nz_models()
    row = (db.query(m.PayrollNzEmployment)
           .filter(m.PayrollNzEmployment.id == row_id, m.PayrollNzEmployment.organization_id == organization_id)
           .first())
    if row is None:
        raise NotFoundException("New Zealand employment")
    return row


def employment_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "legalEntityId": row.legal_entity_id,
            "startDate": _iso(row.start_date), "endDate": _iso(row.end_date),
            "continuityRule": row.continuity_rule, "priorEmploymentId": row.prior_employment_id,
            "terminationReason": row.termination_reason, "paygEligible": row.payg_eligible,
            "paygBasis": row.payg_basis, "paygAgreementRef": row.payg_agreement_ref,
            "evidenceRef": row.evidence_ref, "status": row.status, "createdById": row.created_by_id,
            "approvedById": row.approved_by_id, "approvedAt": _iso(row.approved_at)}


def list_nz_employments(db: Session, organization_id: int, employee_id: int) -> list:
    m = nzs._nz_models()
    nzs._nz_employee(db, organization_id, employee_id)
    return (db.query(m.PayrollNzEmployment)
            .filter(m.PayrollNzEmployment.organization_id == organization_id,
                    m.PayrollNzEmployment.employee_id == employee_id)
            .order_by(m.PayrollNzEmployment.start_date, m.PayrollNzEmployment.id).all())


def record_nz_employment(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    nzs._nz_employee(db, organization_id, employee_id)
    if not isinstance(payload, dict):
        raise BadRequestException("The request body must be an object.")
    unknown = sorted(set(payload) - set(EMPLOYMENT_FIELDS))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    if not payload.get("start_date"):
        raise BadRequestException("required field(s): start_date")
    data = {"start_date": nzs._as_date(payload["start_date"], "start_date"),
            "continuity_rule": str(payload.get("continuity_rule") or "NEW_INSTANCE").strip().upper(),
            "payg_eligible": nzs._nz_bool(payload.get("payg_eligible") or False, "payg_eligible")}
    for key in ("payg_basis", "payg_agreement_ref", "evidence_ref"):
        value = payload.get(key)
        data[key] = str(value).strip() if value not in (None, "") else None
    for key in ("prior_employment_id", "legal_entity_id"):
        value = payload.get(key)
        try:
            data[key] = int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            raise BadRequestException(f"{key} must be a whole number.")
    if data["continuity_rule"] not in ("NEW_INSTANCE", "CONTINUOUS"):
        raise BadRequestException("continuity_rule must be one of: NEW_INSTANCE, CONTINUOUS.")
    if data["continuity_rule"] == "CONTINUOUS":
        if not (data["evidence_ref"] and data["prior_employment_id"]):
            raise BadRequestException("Continuous employment needs the prior employment and evidence (spec §10).")
        prior = _employment(db, organization_id, data["prior_employment_id"])
        if prior.employee_id != employee_id:
            raise BadRequestException("The prior employment belongs to another employee.")
    if data["payg_basis"] is not None:
        data["payg_basis"] = data["payg_basis"].upper()
        if data["payg_basis"] not in ("FIXED_TERM_UNDER_12_MONTHS", "IRREGULAR_INTERMITTENT"):
            raise BadRequestException("payg_basis must be FIXED_TERM_UNDER_12_MONTHS or IRREGULAR_INTERMITTENT.")
    if data["payg_eligible"] and not (data["payg_basis"] and data["payg_agreement_ref"]):
        raise BadRequestException("Pay-as-you-go holiday pay needs its basis and the written agreement reference.")
    nzs._nz_legal_entity(db, organization_id, data["legal_entity_id"])
    row = m.PayrollNzEmployment(organization_id=organization_id, employee_id=employee_id, status="DRAFT",
                                created_by_id=actor_id, **data)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "created", "nz_employment", row.id,
                  new={"start_date": data["start_date"].isoformat(), "continuity_rule": data["continuity_rule"]},
                  reason=reason)
    return row


def approve_nz_employment(db: Session, organization_id: int, row_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    m = nzs._nz_models()
    row = _employment(db, organization_id, row_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT New Zealand employment can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand employment", db=db,
                      entity_type="nz_employment", entity_id=row.id, current_status=row.status)
    other = (db.query(m.PayrollNzEmployment.id)
             .filter(m.PayrollNzEmployment.organization_id == organization_id,
                     m.PayrollNzEmployment.employee_id == row.employee_id,
                     m.PayrollNzEmployment.status == "ACTIVE").first())
    if other is not None:
        raise BadRequestException("The employee already has an ACTIVE New Zealand employment; end it first.")
    row.status, row.approved_by_id, row.approved_at = "ACTIVE", actor_id, datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "approved", "nz_employment", row.id, old={"status": "DRAFT"},
                  new={"status": "ACTIVE"})
    return row


def end_nz_employment(db: Session, organization_id: int, row_id: int, end_date, termination_reason, actor_id,
                      reason=None):
    reason = nzs._nz_reason(reason)
    row = _employment(db, organization_id, row_id)
    if row.status != "ACTIVE":
        raise BadRequestException("Only an ACTIVE New Zealand employment can be ended.")
    end = nzs._as_date(end_date, "end_date")
    if end < row.start_date:
        raise BadRequestException("end_date cannot be before the start date.")
    row.end_date, row.status = end, "ENDED"
    row.termination_reason = (str(termination_reason).strip()[:30] or None) if termination_reason else None
    db.flush()
    nzs._nz_audit(db, actor_id, "ended", "nz_employment", row.id, old={"status": "ACTIVE"},
                  new={"status": "ENDED", "end_date": end.isoformat()}, reason=reason)
    return row


def active_employment(db: Session, organization_id: int, employee_id: int, on: Optional[date] = None):
    m = nzs._nz_models()
    E = m.PayrollNzEmployment
    query = db.query(E).filter(E.organization_id == organization_id, E.employee_id == employee_id,
                               E.status == "ACTIVE")
    if on is not None:
        query = query.filter(E.start_date <= on)
    return query.first()


def anchor_date(db: Session, employment) -> date:
    """The anniversary anchor: a CONTINUOUS instance keeps the start date of
    the employment it continues (spec §10); a NEW_INSTANCE starts afresh."""
    seen, row = set(), employment
    while row.continuity_rule == "CONTINUOUS" and row.prior_employment_id and row.id not in seen:
        seen.add(row.id)
        prior = db.get(type(row), row.prior_employment_id)
        if prior is None:
            break
        row = prior
    return row.start_date


# ── the pack (fail-closed) ──────────────────────────────────────────────────
def _pack(db: Session, organization_id: int, on: date):
    from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack

    rate_map, slabs, pack = nzs._nz_pack_in_force(db, on)
    if pack is None:
        _conflict(f"no rule pack is in force on {on.isoformat()}.")
    return NzPack(rate_map, slabs, organization_id, on)


def _blocked(fn, *args, **kwargs):
    from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError

    try:
        return fn(*args, **kwargs)
    except NZCalculationBlockedError as exc:
        _conflict(f"blocked ({exc.key}): {exc.reason}")


def _pack_hash(pack) -> str:
    return hashlib.sha256(json.dumps(pack.used(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ── vesting (NZ-016) ────────────────────────────────────────────────────────
def _entitlements(db: Session, organization_id: int, employment_id: int, leave_type: str) -> list:
    m = nzs._nz_models()
    L = m.PayrollNzLeaveEntitlement
    return (db.query(L).filter(L.organization_id == organization_id, L.employment_id == employment_id,
                               L.leave_type == leave_type)
            .order_by(L.entitlement_date, L.id).all())


def vest_entitlements(db: Session, organization_id: int, as_of, *, employee_id=None, actor_id=None) -> dict:
    """Vest every annual / sick / family-violence entitlement due up to
    `as_of` for ACTIVE employments. Safe to re-run (nothing vests twice)."""
    m = nzs._nz_models()
    ha = _engine()
    as_of = nzs._as_date(as_of, "asOf")
    pack = _pack(db, organization_id, as_of)
    E = m.PayrollNzEmployment
    query = db.query(E).filter(E.organization_id == organization_id, E.status == "ACTIVE", E.start_date <= as_of)
    if employee_id is not None:
        nzs._nz_employee(db, organization_id, employee_id)
        query = query.filter(E.employee_id == employee_id)
    vested, employees = 0, set()
    for employment in query.order_by(E.id).all():
        anchor = anchor_date(db, employment)
        annual = _entitlements(db, organization_id, employment.id, "ANNUAL")
        sick = _entitlements(db, organization_id, employment.id, "SICK")
        violence = _entitlements(db, organization_id, employment.id, "FAMILY_VIOLENCE")
        vests = _blocked(ha.annual_vests, anchor, as_of, [r.entitlement_date for r in annual], pack)
        sick_new = _blocked(ha.sick_vests, anchor, as_of, sick, pack)
        vests += sick_new
        vests += _blocked(ha.family_violence_vests, anchor, as_of, [r.entitlement_date for r in violence], pack)
        if not vests:
            continue
        pack_hash = _pack_hash(pack)
        if sick_new:
            # the previous year's remainder now sits in the new year's carried_in
            first_new = min(v.entitlement_date for v in sick_new)
            for old in sick:
                if old.status == "ACTIVE" and old.entitlement_date < first_new:
                    old.status = "SUPERSEDED"
        for vest in vests:
            db.add(m.PayrollNzLeaveEntitlement(
                organization_id=organization_id, legal_entity_id=employment.legal_entity_id,
                employee_id=employment.employee_id, employment_id=employment.id, leave_type=vest.leave_type,
                qualifying_date=vest.qualifying_date, entitlement_date=vest.entitlement_date, unit=vest.unit,
                quantity=vest.quantity, carried_in=vest.carried_in, source="HOLIDAYS_ACT_2003",
                pack_hash=pack_hash, expires_on=vest.expires_on, status="ACTIVE", created_by_id=actor_id))
            vested += 1
        db.flush()
        employees.add(employment.employee_id)
    if vested:
        nzs._nz_audit(db, actor_id, "vested", "nz_leave_entitlement", 0,
                      new={"asOf": as_of.isoformat(), "vested": vested, "employees": len(employees)})
    return {"vested": vested, "employees": len(employees), "asOf": as_of.isoformat()}


def entitlement_view(row) -> dict:
    ha = _engine()
    return {"id": row.id, "employmentId": row.employment_id, "leaveType": row.leave_type,
            "qualifyingDate": _iso(row.qualifying_date), "entitlementDate": _iso(row.entitlement_date),
            "unit": row.unit, "quantity": _num(row.quantity), "carriedIn": _num(row.carried_in),
            "taken": _num(row.taken), "paidOut": _num(row.paid_out), "balance": _num(ha.balance(row)),
            "source": row.source, "sourceDecisionId": row.source_decision_id, "expiresOn": _iso(row.expires_on),
            "status": row.status}


# ── generic leave requests -> NZ leave events ───────────────────────────────
def _request_value(data, camel: str, snake: str):
    return getattr(data, camel) if hasattr(data, camel) else getattr(data, snake, None)


def guard_generic_request(db: Session, data, organization_id: int) -> None:
    """Called before a generic leave request is stored. Family-violence leave
    never records a reason (refused, not stored-then-blanked); an NZ employee
    may only use the NZ leave types."""
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    leave_type = _request_value(data, "leaveType", "leave_type")
    employee_id = _request_value(data, "employeeId", "employee_id")
    employee = (organization_scoped(db, PayrollEmployee, organization_id)
                .filter(PayrollEmployee.id == employee_id).first() if organization_id else None)
    nz_employee = is_nz_employee(db, organization_id, employee)
    if leave_type == FAMILY_VIOLENCE_REQUEST and (_request_value(data, "reason", "reason") or "").strip():
        raise BadRequestException("Family violence leave never records a reason; remove it and submit again.")
    if not nz_employee:
        if str(leave_type).startswith("nz_"):
            raise BadRequestException("This leave type exists only for New Zealand employees.")
        return
    if leave_type not in NZ_REQUEST_TYPES and leave_type not in NZ_PASSTHROUGH_TYPES:
        allowed = ", ".join(list(NZ_REQUEST_TYPES) + list(NZ_PASSTHROUGH_TYPES))
        raise BadRequestException(f"New Zealand leave type must be one of: {allowed}.")


def _pattern_on(db: Session, organization_id: int, employee_id: int, on: date):
    m = nzs._nz_models()
    return nzs._nz_one_active(db, m.PayrollNzWorkPatternVersion, organization_id, employee_id, on, "work pattern")


def _days_per_week(pattern) -> Optional[Decimal]:
    if pattern is None:
        return None
    if pattern.contracted_days_per_week:
        return Decimal(str(pattern.contracted_days_per_week))
    schedule = pattern.weekly_schedule if isinstance(pattern.weekly_schedule, dict) else None
    if schedule:
        days = sum(1 for hours in schedule.values() if Decimal(str(hours or 0)) > 0)
        return Decimal(days) if days else None
    return None


def _working_days(db: Session, organization_id: int, employee_id: int, start: date, end: date,
                  fallback: int) -> Decimal:
    """Working days in [start, end] by the work pattern in force each day; a
    VARIABLE / missing pattern falls back to the request's own day count."""
    ha = _engine()
    total, day = 0, start
    while day <= end:
        pattern = _pattern_on(db, organization_id, employee_id, day)
        if pattern is None or pattern.pattern_type not in ("FIXED", "ROSTERED"):
            return Decimal(fallback)
        decision, _basis, _steps = ha.otherwise_working_day(day, pattern)
        total += decision == ha.OWD_YES
        day += timedelta(days=1)
    return Decimal(total)


def _consume(db: Session, organization_id: int, employment, nz_type: str, quantity: Decimal, on: date,
             actor_id):
    m = nzs._nz_models()
    ha = _engine()
    if nz_type in ("BEREAVEMENT_CLOSE", "BEREAVEMENT_OTHER"):
        # per event: the entitlement vests at the event
        pack = _pack(db, organization_id, on)
        kind = "CLOSE" if nz_type == "BEREAVEMENT_CLOSE" else "OTHER"
        days, _steps = _blocked(ha.bereavement_quantity, kind, anchor_date(db, employment), on, pack)
        if days <= 0:
            _conflict("bereavement leave is not yet available (qualifying period not met).")
        existing = [r for r in _entitlements(db, organization_id, employment.id, nz_type) if r.entitlement_date == on]
        if not existing:
            row = m.PayrollNzLeaveEntitlement(
                organization_id=organization_id, legal_entity_id=employment.legal_entity_id,
                employee_id=employment.employee_id, employment_id=employment.id, leave_type=nz_type,
                qualifying_date=on, entitlement_date=on, unit="DAYS", quantity=days, source="HOLIDAYS_ACT_2003",
                pack_hash=_pack_hash(pack), status="ACTIVE", created_by_id=actor_id)
            db.add(row)
            db.flush()
            existing = [row]
        candidates = existing
    else:
        candidates = [r for r in _entitlements(db, organization_id, employment.id, nz_type) if r.status == "ACTIVE"]
    for row in candidates:
        if ha.balance(row) >= quantity:
            row.taken = Decimal(str(row.taken or 0)) + quantity
            if ha.balance(row) <= 0:
                row.status = "EXHAUSTED"
            return row
    _conflict("insufficient leave entitlement for this request." if nz_type == "FAMILY_VIOLENCE"
              else f"insufficient {nz_type.replace('_', ' ').lower()} entitlement for this request.")


def record_leave_event_from_request(db: Session, request, organization_id: int, actor_id):
    """Called when a generic leave request is approved. For an NZ employee the
    request becomes a leave event against the legal entitlement; when the
    entitlement is insufficient the approval itself is refused (409)."""
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    employee = db.get(PayrollEmployee, request.employee_id)
    if not is_nz_employee(db, organization_id, employee) or request.leave_type in NZ_PASSTHROUGH_TYPES:
        return None
    nz_type = NZ_REQUEST_TYPES.get(request.leave_type)
    if nz_type is None:
        raise BadRequestException("This leave type is not a New Zealand leave type.")
    employment = active_employment(db, organization_id, employee.id, request.start_date)
    if employment is None:
        _conflict("no active employment covers the leave start date.")
    days = _working_days(db, organization_id, employee.id, request.start_date, request.end_date,
                         request.days or 1)
    if days <= 0:
        _conflict("the leave covers no working day.")
    if nz_type == "ANNUAL":
        per_week = _days_per_week(_pattern_on(db, organization_id, employee.id, request.start_date))
        if not per_week:
            _conflict("annual holidays are in weeks: an ACTIVE work pattern with working days per week is needed.")
        quantity, unit = (days / per_week).quantize(_QTY, rounding=ROUND_HALF_UP), "WEEKS"
    else:
        quantity, unit = days, "DAYS"
    entitlement = _consume(db, organization_id, employment, nz_type, quantity, request.start_date, actor_id)
    restricted = nz_type == "FAMILY_VIOLENCE"
    event = m.PayrollNzLeaveEvent(
        organization_id=organization_id, legal_entity_id=employment.legal_entity_id, employee_id=employee.id,
        employment_id=employment.id, entitlement_id=entitlement.id, leave_type=nz_type,
        start_date=request.start_date, end_date=request.end_date, quantity=quantity, unit=unit,
        source_request_id=request.id, restricted=restricted, status="APPROVED", created_by_id=actor_id,
        approved_by_id=actor_id, approved_at=datetime.utcnow())
    db.add(event)
    db.flush()
    nzs._nz_audit(db, actor_id, "approved", "nz_leave_event", event.id,
                  new={"status": "APPROVED", "restricted": True} if restricted
                  else {"status": "APPROVED", "leave_type": nz_type, "quantity": str(quantity), "unit": unit})
    return event


def cancel_leave_event(db: Session, organization_id: int, event_id: int, actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    event = (db.query(m.PayrollNzLeaveEvent)
             .filter(m.PayrollNzLeaveEvent.id == event_id, m.PayrollNzLeaveEvent.organization_id == organization_id)
             .first())
    if event is None:
        raise NotFoundException("New Zealand leave event")
    if event.status == "PAID":
        raise BadRequestException("Paid leave cannot be cancelled here; it needs a pay correction (Phase 6).")
    if event.status != "APPROVED":
        raise BadRequestException("Only an APPROVED leave event can be cancelled.")
    entitlement = db.get(m.PayrollNzLeaveEntitlement, event.entitlement_id) if event.entitlement_id else None
    if entitlement is not None:
        entitlement.taken = max(Decimal("0"), Decimal(str(entitlement.taken or 0)) - Decimal(str(event.quantity)))
        if entitlement.status == "EXHAUSTED":
            entitlement.status = "ACTIVE"
    event.status = "CANCELLED"
    db.flush()
    nzs._nz_audit(db, actor_id, "cancelled", "nz_leave_event", event.id, old={"status": "APPROVED"},
                  new={"status": "CANCELLED"}, reason=None if event.restricted else reason)
    return event


def cancel_events_for_request(db: Session, request, organization_id: int, actor_id) -> int:
    """A generic request rejected after approval releases its NZ leave event."""
    m = nzs._nz_models()
    V = m.PayrollNzLeaveEvent
    count = 0
    for event in db.query(V).filter(V.organization_id == organization_id, V.source_request_id == request.id,
                                    V.status == "APPROVED").all():
        cancel_leave_event(db, organization_id, event.id, actor_id, reason="Leave request rejected after approval")
        count += 1
    return count


def event_view(row) -> dict:
    return {"id": row.id, "employmentId": row.employment_id, "entitlementId": row.entitlement_id,
            "leaveType": row.leave_type, "startDate": _iso(row.start_date), "endDate": _iso(row.end_date),
            "quantity": _num(row.quantity), "unit": row.unit, "sourceRequestId": row.source_request_id,
            "restricted": row.restricted, "status": row.status,
            "leavePayCalculationId": row.leave_pay_calculation_id}


# ── family-violence restricted access (NZ-023) ──────────────────────────────
def can_view_family_violence(db: Session, organization_id: int, user_id) -> bool:
    from app.modules.payroll.hong_kong_service import _active_permission

    return _active_permission(db, organization_id, user_id, NZ_FAMILY_VIOLENCE_VIEW) is not None


def grant_family_violence_view(db: Session, organization_id: int, actor_id, user_id: int, reason):
    from app.modules.payroll.hong_kong_service import _active_permission, _require_real_org_admin, _tenant_user
    from app.modules.payroll.models import PayrollUserPermission

    _require_real_org_admin(db, organization_id, actor_id)
    if user_id == actor_id:
        raise BadRequestException("A permission cannot be granted to yourself — another org admin must grant it.")
    grantee = _tenant_user(db, organization_id, user_id)
    reason = nzs._nz_reason(reason)
    if _active_permission(db, organization_id, grantee.id, NZ_FAMILY_VIOLENCE_VIEW):
        raise BadRequestException("This user already holds family violence leave access.")
    row = PayrollUserPermission(organization_id=organization_id, user_id=grantee.id,
                                permission=NZ_FAMILY_VIOLENCE_VIEW, reason=reason, granted_by_id=actor_id,
                                granted_at=datetime.utcnow())
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "grant", "user_permission", row.id,
                  new={"permission": NZ_FAMILY_VIOLENCE_VIEW, "userId": grantee.id}, reason=reason)
    return row


def revoke_family_violence_view(db: Session, organization_id: int, actor_id, user_id: int, reason):
    from app.modules.payroll.hong_kong_service import _active_permission, _require_real_org_admin

    _require_real_org_admin(db, organization_id, actor_id)
    reason = nzs._nz_reason(reason)
    row = _active_permission(db, organization_id, user_id, NZ_FAMILY_VIOLENCE_VIEW)
    if row is None:
        raise NotFoundException("Permission")
    row.revoked_at, row.revoked_by_id = datetime.utcnow(), actor_id
    db.flush()
    nzs._nz_audit(db, actor_id, "revoke", "user_permission", row.id,
                  old={"permission": NZ_FAMILY_VIOLENCE_VIEW, "userId": user_id}, new={"revoked": True},
                  reason=reason)
    return row


def family_violence_view_holders(db: Session, organization_id: int) -> list:
    from app.modules.payroll.models import PayrollUserPermission as P

    return [{"id": p.id, "userId": p.user_id, "grantedById": p.granted_by_id, "grantedAt": _iso(p.granted_at),
             "revokedAt": _iso(p.revoked_at)}
            for p in db.query(P).filter(P.organization_id == organization_id,
                                        P.permission == NZ_FAMILY_VIOLENCE_VIEW).order_by(P.id)]


def _log_restricted_read(db: Session, organization_id: int, viewer_id, resource_type: str, resource_id,
                         employee_id) -> None:
    from app.modules.payroll import retention_service

    retention_service.record_access(db, NZ, organization_id, viewer_id, "VIEW_RESTRICTED_LEAVE", resource_type,
                                    resource_id, employee_id=employee_id, purpose=ACCESS_PURPOSE)


def visible_events(db: Session, organization_id: int, viewer_id, employee_id: int) -> list:
    """Leave events of one employee; restricted ones only with the permission,
    and each restricted read is in the personal-data access log."""
    m = nzs._nz_models()
    nzs._nz_employee(db, organization_id, employee_id)
    rows = (db.query(m.PayrollNzLeaveEvent)
            .filter(m.PayrollNzLeaveEvent.organization_id == organization_id,
                    m.PayrollNzLeaveEvent.employee_id == employee_id)
            .order_by(m.PayrollNzLeaveEvent.start_date, m.PayrollNzLeaveEvent.id).all())
    allowed = can_view_family_violence(db, organization_id, viewer_id)
    out = []
    for row in rows:
        if row.restricted:
            if not allowed:
                continue
            _log_restricted_read(db, organization_id, viewer_id, "nz_leave_event", row.id, employee_id)
        out.append(event_view(row))
    db.flush()
    return out


def balances(db: Session, organization_id: int, viewer_id, employee_id: int) -> dict:
    """The LEGAL entitlement by type (weeks for annual, days otherwise).
    Family-violence leave only with the permission (access-logged). The
    generic allocation JSON is returned separately as a planning view."""
    from app.modules.payroll.models import PayrollLeaveAllocation

    m = nzs._nz_models()
    ha = _engine()
    nzs._nz_employee(db, organization_id, employee_id)
    L = m.PayrollNzLeaveEntitlement
    rows = (db.query(L).filter(L.organization_id == organization_id, L.employee_id == employee_id)
            .order_by(L.entitlement_date, L.id).all())
    allowed = can_view_family_violence(db, organization_id, viewer_id)
    groups = {"annual": ("ANNUAL",), "sick": ("SICK",), "bereavement": ("BEREAVEMENT_CLOSE", "BEREAVEMENT_OTHER"),
              "alternative": ("ALTERNATIVE",)}
    if allowed:
        groups["familyViolence"] = ("FAMILY_VIOLENCE",)
    out = {"legalEntitlement": True}
    for name, types in groups.items():
        chosen = [r for r in rows if r.leave_type in types]
        active = [r for r in chosen if r.status in ("ACTIVE", "EXHAUSTED")]
        out[name] = {"unit": "WEEKS" if name == "annual" else "DAYS",
                     "balance": _num(sum((ha.balance(r) for r in active), Decimal("0"))),
                     "entitlements": [entitlement_view(r) for r in chosen]}
    if allowed and any(r.leave_type == "FAMILY_VIOLENCE" for r in rows):
        _log_restricted_read(db, organization_id, viewer_id, "nz_leave_entitlement", None, employee_id)
        db.flush()
    alloc = (db.query(PayrollLeaveAllocation)
             .filter(PayrollLeaveAllocation.organization_id == organization_id,
                     PayrollLeaveAllocation.employee_id == employee_id).first())
    planning = dict((alloc.leave_balances or {}) if alloc else {})
    planning.pop(RESTRICTED_LEAVE_LABEL, None)
    out["planningView"] = {"label": "Planning view - not the legal New Zealand entitlement",
                           "balances": planning}
    return out


def hide_restricted_requests(db: Session, organization_id: int, viewer_id, rows: list) -> list:
    """Generic leave-request rows minus family-violence requests, unless the
    viewer holds the permission (NZ-023)."""
    if not any(getattr(r, "leave_type", None) == FAMILY_VIOLENCE_REQUEST for r in rows):
        return rows
    if viewer_id is not None and can_view_family_violence(db, organization_id, viewer_id):
        return rows
    return [r for r in rows if getattr(r, "leave_type", None) != FAMILY_VIOLENCE_REQUEST]


# ── public holidays (spec §8) ───────────────────────────────────────────────
def _region(employee) -> Optional[str]:
    content = nzs._content()
    value = (getattr(employee, "work_state", None) or "").strip()
    if not value:
        return None
    for code, name in content.NZ_REGIONS:
        if value.upper() in (code, f"NZ-{code}") or value.lower() == name.lower():
            return code
    return None


def _holiday_pack(db: Session, organization_id: int, year: int):
    from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack

    slabs, seen = [], set()
    for on in (date(year, 1, 1), date(year, 12, 31)):
        _rate_map, rows, pack = nzs._nz_pack_in_force(db, on)
        for row in rows or []:
            if row.id not in seen:
                seen.add(row.id)
                slabs.append(row)
    if not slabs:
        _conflict(f"no rule pack is in force in {year}.")
    return NzPack({}, slabs, organization_id, None)


def _history(db: Session, organization_id: int, employee_id: int, holiday: date) -> list:
    from app.modules.payroll.models import PayrollAttendanceRecord as Att

    days = [holiday - timedelta(weeks=k) for k in range(1, HISTORY_LOOKBACK_WEEKS + 1)]
    rows = (db.query(Att.date, Att.status)
            .filter(Att.organization_id == organization_id, Att.employee_id == employee_id, Att.date.in_(days))
            .all())
    return [(status or "").lower() not in ("absent", "leave") for _day, status in rows]


def decision_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "employmentId": row.employment_id,
            "holidayDate": _iso(row.holiday_date), "holidayName": row.holiday_name, "region": row.region,
            "otherwiseWorkingDay": row.otherwise_working_day, "owdBasis": row.owd_basis,
            "owdEvidenceRef": row.owd_evidence_ref, "worked": row.worked, "shiftStart": _iso(row.shift_start),
            "shiftEnd": _iso(row.shift_end), "timezone": row.timezone,
            "hoursOnHoliday": _num(row.hours_on_holiday), "alternativeHolidayDue": row.alternative_holiday_due,
            "status": row.status, "createdById": row.created_by_id, "approvedById": row.approved_by_id}


def propose_public_holiday_decisions(db: Session, organization_id: int, year, *, employee_id=None,
                                     actor_id=None) -> list:
    """DRAFT decisions for every holiday of `year` (national + the employee's
    region) for each ACTIVE employment, once per employee and date."""
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    ha = _engine()
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise BadRequestException("year must be a whole number.")
    pack = _holiday_pack(db, organization_id, year)
    D, Emp = m.PayrollNzPublicHolidayDecision, m.PayrollNzEmployment
    query = db.query(Emp).filter(Emp.organization_id == organization_id, Emp.status == "ACTIVE")
    if employee_id is not None:
        nzs._nz_employee(db, organization_id, employee_id)
        query = query.filter(Emp.employee_id == employee_id)
    created = []
    for employment in query.order_by(Emp.id).all():
        employee = db.get(PayrollEmployee, employment.employee_id)
        region = _region(employee)
        for holiday in _blocked(ha.holidays_for, pack, year, region):
            day = holiday["date"]
            if day < employment.start_date or (employment.end_date and day > employment.end_date):
                continue
            exists = (db.query(D.id).filter(D.organization_id == organization_id,
                                            D.employee_id == employment.employee_id, D.holiday_date == day,
                                            D.status.in_(("DRAFT", "APPROVED"))).first())
            if exists:
                continue
            pattern = _pattern_on(db, organization_id, employment.employee_id, day)
            decision, basis, _steps = ha.otherwise_working_day(
                day, pattern, _history(db, organization_id, employment.employee_id, day))
            row = D(organization_id=organization_id, legal_entity_id=employment.legal_entity_id,
                    employee_id=employment.employee_id, employment_id=employment.id, holiday_date=day,
                    holiday_name=holiday["name"][:80], region=holiday["region"],
                    otherwise_working_day=decision, owd_basis=basis, worked=False, status="DRAFT",
                    created_by_id=actor_id)
            db.add(row)
            created.append(row)
    db.flush()
    if created:
        nzs._nz_audit(db, actor_id, "proposed", "nz_public_holiday_decision", 0,
                      new={"year": year, "created": len(created)})
    return created


def _decision(db: Session, organization_id: int, decision_id: int):
    m = nzs._nz_models()
    D = m.PayrollNzPublicHolidayDecision
    row = db.query(D).filter(D.id == decision_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("New Zealand public holiday decision")
    return row


def list_public_holiday_decisions(db: Session, organization_id: int, employee_id: int) -> list:
    m = nzs._nz_models()
    D = m.PayrollNzPublicHolidayDecision
    nzs._nz_employee(db, organization_id, employee_id)
    return (db.query(D).filter(D.organization_id == organization_id, D.employee_id == employee_id)
            .order_by(D.holiday_date, D.id).all())


def update_public_holiday_decision(db: Session, organization_id: int, decision_id: int, payload: dict, actor_id,
                                   reason=None):
    ha = _engine()
    reason = nzs._nz_reason(reason)
    row = _decision(db, organization_id, decision_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT public holiday decision can be changed.")
    if not isinstance(payload, dict):
        raise BadRequestException("The request body must be an object.")
    unknown = sorted(set(payload) - set(DECISION_FIELDS))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    old = {"otherwise_working_day": row.otherwise_working_day, "worked": row.worked}
    if "otherwise_working_day" in payload:
        decision = str(payload["otherwise_working_day"] or "").strip().upper()
        if decision not in (ha.OWD_YES, ha.OWD_NO):
            raise BadRequestException("otherwise_working_day must be YES or NO.")
        evidence = (payload.get("owd_evidence_ref") or "").strip()
        if not evidence:
            raise BadRequestException("An operator's otherwise-working-day decision needs evidence.")
        row.otherwise_working_day, row.owd_basis, row.owd_evidence_ref = decision, "OPERATOR_DECISION", evidence
    if "timezone" in payload:
        if payload["timezone"] not in ha.TIMEZONES:
            raise BadRequestException(f"timezone must be one of: {', '.join(ha.TIMEZONES)}.")
        row.timezone = payload["timezone"]
    if "worked" in payload:
        row.worked = nzs._nz_bool(payload["worked"], "worked")
    for key in ("shift_start", "shift_end"):
        if key in payload:
            setattr(row, key, nzs._as_datetime(payload[key], key) if payload[key] else None)
    if row.worked:
        if row.shift_start is None or row.shift_end is None or row.shift_end <= row.shift_start:
            raise BadRequestException("A worked public holiday needs a shift start before its end.")
        row.hours_on_holiday = ha.hours_on_holiday(row.shift_start, row.shift_end, row.holiday_date, row.timezone)
    else:
        row.shift_start = row.shift_end = row.hours_on_holiday = None
    row.alternative_holiday_due = ha.alternative_holiday_due(row.worked, row.otherwise_working_day)
    row.updated_at = datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "updated", "nz_public_holiday_decision", row.id, old=old,
                  new={"otherwise_working_day": row.otherwise_working_day, "worked": row.worked}, reason=reason)
    return row


def approve_public_holiday_decision(db: Session, organization_id: int, decision_id: int, actor_id):
    """Four-eyes. UNDETERMINED is refused. An alternative holiday due creates
    exactly one ALTERNATIVE entitlement (one whole day) for this decision."""
    from app.modules.payroll.service import require_four_eyes

    m = nzs._nz_models()
    ha = _engine()
    row = _decision(db, organization_id, decision_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT public holiday decision can be approved.")
    if row.otherwise_working_day == ha.OWD_UNDETERMINED:
        raise BadRequestException("The otherwise-working-day test is UNDETERMINED: record an evidenced YES/NO "
                                  "decision first.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand public holiday decision", db=db,
                      entity_type="nz_public_holiday_decision", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    if row.alternative_holiday_due:
        L = m.PayrollNzLeaveEntitlement
        exists = db.query(L.id).filter(L.source_decision_id == row.id, L.leave_type == "ALTERNATIVE").first()
        if exists is None:
            facts = json.dumps({"decision": row.id, "holiday": row.holiday_date.isoformat(),
                                "owd": row.otherwise_working_day, "worked": row.worked}, sort_keys=True)
            db.add(L(organization_id=organization_id, legal_entity_id=row.legal_entity_id,
                     employee_id=row.employee_id, employment_id=row.employment_id, leave_type="ALTERNATIVE",
                     qualifying_date=row.holiday_date, entitlement_date=row.holiday_date, unit="DAYS",
                     quantity=Decimal("1"), source="PUBLIC_HOLIDAY_WORKED", source_decision_id=row.id,
                     pack_hash=hashlib.sha256(facts.encode()).hexdigest(), status="ACTIVE",
                     created_by_id=actor_id, approved_by_id=actor_id, approved_at=datetime.utcnow()))
            db.flush()
    nzs._nz_audit(db, actor_id, "approved", "nz_public_holiday_decision", row.id, old={"status": "DRAFT"},
                  new={"status": "APPROVED", "alternative_holiday_due": row.alternative_holiday_due})
    return row


# ── gross-earnings ledger (written at PAID) ─────────────────────────────────
def _days_worked(db: Session, organization_id: int, employee_id: int, start, end) -> Optional[Decimal]:
    from app.modules.payroll.models import PayrollAttendanceRecord as Att

    if start is None or end is None:
        return None
    rows = (db.query(Att.status).filter(Att.organization_id == organization_id, Att.employee_id == employee_id,
                                        Att.date >= start, Att.date <= end).all())
    if rows:
        return Decimal(sum(1 for (status,) in rows if (status or "").lower() not in ("absent", "leave")))
    ha = _engine()
    total, day = 0, start
    while day <= end:
        pattern = _pattern_on(db, organization_id, employee_id, day)
        if pattern is None or pattern.pattern_type not in ("FIXED", "ROSTERED"):
            return None
        total += ha.otherwise_working_day(day, pattern)[0] == ha.OWD_YES
        day += timedelta(days=1)
    return Decimal(total)


def write_gross_earnings(db: Session, run, actor_id) -> int:
    """One ledger row per PAID NZ payslip and HOLIDAY_GROSS component, from the
    frozen snapshot. Idempotent per (payslip, component)."""
    m = nzs._nz_models()
    G = m.PayrollNzGrossEarningsLedger
    added = 0
    for item in nzs._nz_run_items(db, run):
        snapshot = item.nz_calculation_snapshot or {}
        lines = (snapshot.get("baseLines") or {}).get("HOLIDAY_GROSS") or []
        if not lines:
            continue
        employment = active_employment(db, run.organization_id, item.employee_id, run.pay_date)
        days = _days_worked(db, run.organization_id, item.employee_id, run.period_start, run.period_end)
        pack_hash = (snapshot.get("hashes") or {}).get("packHash")
        for line in lines:
            component, treatment = line.get("component"), line.get("treatment")
            if db.query(G.id).filter(G.payslip_item_id == item.id, G.component == component).first():
                continue
            db.add(G(organization_id=run.organization_id,
                     legal_entity_id=getattr(employment, "legal_entity_id", None), employee_id=item.employee_id,
                     employment_id=getattr(employment, "id", None), run_id=run.id, payslip_item_id=item.id,
                     pay_date=run.pay_date, period_start=run.period_start, period_end=run.period_end,
                     component=component, amount=Decimal(str(line.get("amount") or 0)),
                     included=treatment == "INCLUDED", treatment=treatment,
                     reason=f"HOLIDAY_GROSS:{component} {treatment}", days_worked=days, pack_hash=pack_hash,
                     created_by_id=actor_id))
            added += 1
    db.flush()
    return added


def gross_earnings_view(row) -> dict:
    return {"id": row.id, "employmentId": row.employment_id, "runId": row.run_id,
            "payslipItemId": row.payslip_item_id, "payDate": _iso(row.pay_date),
            "periodStart": _iso(row.period_start), "periodEnd": _iso(row.period_end), "component": row.component,
            "amount": _num(row.amount), "included": row.included, "treatment": row.treatment,
            "reason": row.reason, "daysWorked": _num(row.days_worked)}


def list_gross_earnings(db: Session, organization_id: int, employee_id: int) -> list:
    m = nzs._nz_models()
    G = m.PayrollNzGrossEarningsLedger
    nzs._nz_employee(db, organization_id, employee_id)
    return (db.query(G).filter(G.organization_id == organization_id, G.employee_id == employee_id)
            .order_by(G.pay_date, G.id).all())

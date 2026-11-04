"""New Zealand leave pay (ZP-NZ-ENG-001 Phase 6; spec "Holidays Act", NZ-017).

Builds the engine inputs from the gross-earnings ledger and the employment
agreement, records every calculation with both candidates and the statutory
reason (append-only), feeds calculated lines into the run that covers them,
runs the annual-holiday cash-up workflow and marks everything PAID exactly
once when the run is paid.

Leave pay replaces the ordinary pay it displaces: each calculation records
`displaced_amount` (the agreement's pay for the same units) so the engine can
move it from SALARY to HOLIDAY_PAY; any top-up must be in the run's gross.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_service as lv

PURPOSE_BY_LEAVE = {"ANNUAL": "ANNUAL_LEAVE", "SICK": "SICK", "BEREAVEMENT_CLOSE": "BEREAVEMENT",
                    "BEREAVEMENT_OTHER": "BEREAVEMENT", "FAMILY_VIOLENCE": "FAMILY_VIOLENCE",
                    "ALTERNATIVE": "ALTERNATIVE_HOLIDAY"}
RESTRICTED_LINE = "RESTRICTED_LEAVE"
# Calendar weeks in one pay period (calendar arithmetic, not statutory content).
WEEKS_PER_PERIOD = {"WEEKLY": Decimal(1), "FORTNIGHTLY": Decimal(2), "FOUR_WEEKLY": Decimal(4),
                    "MONTHLY": Decimal(52) / Decimal(12)}
_CENT = Decimal("0.01")


def _engine():
    from app.modules.payroll.engine.jurisdictions.new_zealand import leave_pay

    return leave_pay


def _cents(value) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


# ── inputs ──────────────────────────────────────────────────────────────────
def _employment_chain(db: Session, employment) -> list:
    """This instance plus the instances it continues (CONTINUOUS links)."""
    ids, row, seen = [employment.id], employment, {employment.id}
    while row.continuity_rule == "CONTINUOUS" and row.prior_employment_id and row.prior_employment_id not in seen:
        row = db.get(type(row), row.prior_employment_id)
        if row is None:
            break
        seen.add(row.id)
        ids.append(row.id)
    return ids


def ledger_for(db: Session, organization_id: int, employee_id: int, employment) -> list:
    m = nzs._nz_models()
    G = m.PayrollNzGrossEarningsLedger
    rows = (db.query(G).filter(G.organization_id == organization_id, G.employee_id == employee_id,
                               G.employment_id.in_(_employment_chain(db, employment)))
            .order_by(G.pay_date, G.id).all())
    return [{"id": r.id, "payDate": r.pay_date, "periodStart": r.period_start, "periodEnd": r.period_end,
             "component": r.component, "amount": r.amount, "included": r.included, "treatment": r.treatment,
             "daysWorked": r.days_worked} for r in rows]


def _last_period_end(ledger: list, before: date) -> date:
    ends = [r["periodEnd"] for r in ledger if r["periodEnd"] < before]
    return max(ends) if ends else before - timedelta(days=1)


def agreement_rates(db: Session, organization_id: int, employee, on: date, override: Optional[dict] = None) -> dict:
    """Agreement-based weekly / daily / hourly pay. An explicit override (the
    operator's figures from the employment agreement) wins; otherwise a FIXED
    or ROSTERED work pattern with the employee's per-period salary. A
    VARIABLE or missing pattern gives none and marks daily pay as varying."""
    override = dict(override or {})
    if override:
        def num(key):
            value = override.get(key)
            return None if value in (None, "") else Decimal(str(value))
        return {"weekly": num("weekly"), "daily": num("daily"), "hourly": num("hourly"),
                "varies": bool(override.get("dailyPayVaries")), "source": "OPERATOR_AGREEMENT"}
    pattern = lv._pattern_on(db, organization_id, employee.id, on)
    frequency = _frequency(employee)
    basic = Decimal(str(employee.basic or 0))
    if pattern is None or pattern.pattern_type not in ("FIXED", "ROSTERED") or basic <= 0 or frequency is None:
        return {"weekly": None, "daily": None, "hourly": None, "varies": True, "source": "NONE"}
    weekly = basic / WEEKS_PER_PERIOD[frequency]
    days = lv._days_per_week(pattern)
    hours = Decimal(str(pattern.contracted_hours_per_week)) if pattern.contracted_hours_per_week else None
    return {"weekly": weekly, "daily": weekly / days if days else None, "hourly": weekly / hours if hours else None,
            "varies": False, "source": f"WORK_PATTERN:{pattern.id}"}


def _frequency(employee) -> Optional[str]:
    from app.modules.payroll.engine.jurisdictions.new_zealand.pack import normalise_frequency

    return normalise_frequency(getattr(employee, "pay_frequency", None)) or None


def _json(value):
    return nzs._json_safe(value)


# ── calculations ────────────────────────────────────────────────────────────
def _write(db: Session, organization_id: int, employment, line, pay_on: date, pack, inputs: dict, actor_id, *,
           displaced=Decimal("0"), leave_event_id=None, decision_id=None, case_id=None, entitlement_id=None,
           purpose=None):
    m = nzs._nz_models()
    purpose = purpose or line.purpose
    row = m.PayrollNzLeavePayCalculation(
        organization_id=organization_id, legal_entity_id=employment.legal_entity_id,
        employee_id=employment.employee_id, employment_id=employment.id, leave_event_id=leave_event_id,
        public_holiday_decision_id=decision_id, final_pay_case_id=case_id,
        entitlement_id=entitlement_id or line.entitlement_id, pay_on=pay_on, purpose=purpose,
        method_pair=line.method_pair,
        candidate_a_name=line.a.name if line.a else None,
        candidate_a_amount=line.a.rate if line.a else None,
        candidate_b_name=line.b.name if line.b else None,
        candidate_b_amount=line.b.rate if line.b else None,
        chosen=line.chosen, statutory_reason=line.reason[:200], units=line.units, unit=line.unit,
        rate_amount=line.rate, amount=line.amount, displaced_amount=_cents(min(displaced, line.amount)),
        restricted=purpose == "FAMILY_VIOLENCE", inputs=_json({**inputs, "calculation": line.as_dict()}),
        pack_hash=lv._pack_hash(pack), status="CALCULATED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "calculated", "nz_leave_pay_calculation", row.id,
                  new={"restricted": True} if row.restricted
                  else {"purpose": purpose, "chosen": line.chosen, "amount": str(line.amount)})
    return row


def calculate_for_event(db: Session, organization_id: int, event_id: int, actor_id, agreement=None):
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    lp = _engine()
    V = m.PayrollNzLeaveEvent
    event = db.query(V).filter(V.id == event_id, V.organization_id == organization_id).first()
    if event is None:
        raise NotFoundException("New Zealand leave event")
    if event.status != "APPROVED":
        raise BadRequestException("Only an APPROVED leave event can be calculated.")
    if event.leave_pay_calculation_id:
        raise BadRequestException("This leave event already has a leave-pay calculation.")
    employment = db.get(m.PayrollNzEmployment, event.employment_id)
    employee = db.get(PayrollEmployee, event.employee_id)
    pack = lv._pack(db, organization_id, event.start_date)
    ledger = ledger_for(db, organization_id, employee.id, employment)
    end = _last_period_end(ledger, event.start_date)
    rates = agreement_rates(db, organization_id, employee, event.start_date, agreement)
    purpose = PURPOSE_BY_LEAVE[event.leave_type]
    if event.leave_type == "ANNUAL":
        line = lv._blocked(lp.annual_leave_pay, event.quantity, rates["weekly"], ledger, end, pack)
        displaced = Decimal(str(event.quantity)) * rates["weekly"] if rates["weekly"] is not None else Decimal("0")
    else:
        line = lv._blocked(lp.daily_leave_pay, purpose, event.quantity, rates["daily"], rates["varies"], ledger,
                           end, pack)
        displaced = Decimal(str(event.quantity)) * rates["daily"] \
            if rates["daily"] is not None and not rates["varies"] else Decimal("0")
    row = _write(db, organization_id, employment, line, event.start_date, pack,
                 {"agreement": rates, "lastPeriodEnd": end, "ledgerRowIds": [r["id"] for r in ledger]}, actor_id,
                 displaced=displaced, leave_event_id=event.id, entitlement_id=event.entitlement_id, purpose=purpose)
    event.leave_pay_calculation_id = row.id
    db.flush()
    return row


def calculate_for_public_holiday(db: Session, organization_id: int, decision_id: int, actor_id, agreement=None):
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    lp = _engine()
    decision = lv._decision(db, organization_id, decision_id)
    if decision.status != "APPROVED":
        raise BadRequestException("Only an APPROVED public holiday decision can be calculated.")
    C = m.PayrollNzLeavePayCalculation
    if db.query(C.id).filter(C.public_holiday_decision_id == decision.id, C.status != "VOID").first():
        raise BadRequestException("This public holiday decision already has a pay calculation.")
    employment = db.get(m.PayrollNzEmployment, decision.employment_id)
    employee = db.get(PayrollEmployee, decision.employee_id)
    pack = lv._pack(db, organization_id, decision.holiday_date)
    ledger = ledger_for(db, organization_id, employee.id, employment)
    end = _last_period_end(ledger, decision.holiday_date)
    rates = agreement_rates(db, organization_id, employee, decision.holiday_date, agreement)
    owd_yes = decision.otherwise_working_day == "YES"
    if decision.worked:
        line = lv._blocked(lp.public_holiday_worked_pay, decision.hours_on_holiday, rates["hourly"], pack)
        displaced = Decimal(str(decision.hours_on_holiday)) * rates["hourly"] \
            if owd_yes and rates["hourly"] is not None else Decimal("0")
    elif owd_yes:
        line = lv._blocked(lp.daily_leave_pay, "PUBLIC_HOLIDAY_NOT_WORKED", 1, rates["daily"], rates["varies"],
                           ledger, end, pack)
        displaced = rates["daily"] if rates["daily"] is not None and not rates["varies"] else Decimal("0")
    else:
        raise BadRequestException("Nothing is payable: the holiday was not worked and is not an otherwise "
                                  "working day.")
    return _write(db, organization_id, employment, line, decision.holiday_date, pack,
                  {"agreement": rates, "lastPeriodEnd": end, "ledgerRowIds": [r["id"] for r in ledger]}, actor_id,
                  displaced=displaced, decision_id=decision.id)


def calculation_view(row) -> dict:
    return {"id": row.id, "employmentId": row.employment_id, "leaveEventId": row.leave_event_id,
            "publicHolidayDecisionId": row.public_holiday_decision_id, "finalPayCaseId": row.final_pay_case_id,
            "payOn": lv._iso(row.pay_on), "purpose": row.purpose, "methodPair": row.method_pair,
            "candidateA": {"name": row.candidate_a_name, "rate": lv._num(row.candidate_a_amount)},
            "candidateB": {"name": row.candidate_b_name, "rate": lv._num(row.candidate_b_amount)},
            "chosen": row.chosen, "statutoryReason": row.statutory_reason, "units": lv._num(row.units),
            "unit": row.unit, "rate": lv._num(row.rate_amount), "amount": lv._num(row.amount),
            "displaced": lv._num(row.displaced_amount), "restricted": row.restricted, "status": row.status,
            "runId": row.run_id, "payslipItemId": row.payslip_item_id}


def list_calculations(db: Session, organization_id: int, viewer_id, employee_id: int) -> list:
    m = nzs._nz_models()
    C = m.PayrollNzLeavePayCalculation
    nzs._nz_employee(db, organization_id, employee_id)
    allowed = lv.can_view_family_violence(db, organization_id, viewer_id)
    out = []
    for row in (db.query(C).filter(C.organization_id == organization_id, C.employee_id == employee_id)
                .order_by(C.pay_on, C.id)):
        if row.restricted:
            if not allowed:
                continue
            lv._log_restricted_read(db, organization_id, viewer_id, "nz_leave_pay_calculation", row.id, employee_id)
        out.append(calculation_view(row))
    db.flush()
    return out


def leave_lines_for_run(db: Session, run, employee) -> list:
    """CALCULATED leave-pay rows dated inside the run's period, not yet paid
    and not part of a final-pay case. Restricted purposes are masked."""
    m = nzs._nz_models()
    C = m.PayrollNzLeavePayCalculation
    start, end = getattr(run, "period_start", None), getattr(run, "period_end", None)
    if start is None or end is None:
        return []
    rows = (db.query(C).filter(C.organization_id == employee.organization_id, C.employee_id == employee.id,
                               C.status == "CALCULATED", C.final_pay_case_id.is_(None),
                               C.pay_on >= start, C.pay_on <= end)
            .order_by(C.pay_on, C.id).all())
    return [{"calculationId": r.id, "purpose": RESTRICTED_LINE if r.restricted else r.purpose,
             "amount": str(r.amount), "displaced": str(r.displaced_amount)} for r in rows]


# ── cash-up (spec §8) ───────────────────────────────────────────────────────
def _cash_up(db: Session, organization_id: int, request_id: int):
    m = nzs._nz_models()
    Q = m.PayrollNzCashUpRequest
    row = db.query(Q).filter(Q.id == request_id, Q.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("New Zealand cash-up request")
    return row


def request_cash_up(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    nzs._nz_employee(db, organization_id, employee_id)
    payload = dict(payload or {})
    ref = (payload.get("written_request_ref") or "").strip()
    if not ref:
        raise BadRequestException("A cash-up needs the employee's written request (its reference).")
    try:
        entitlement_id, weeks = int(payload.get("entitlement_id")), Decimal(str(payload.get("weeks")))
    except Exception:
        raise BadRequestException("entitlement_id and weeks are required.")
    L = m.PayrollNzLeaveEntitlement
    ent = db.query(L).filter(L.id == entitlement_id, L.organization_id == organization_id,
                             L.employee_id == employee_id).first()
    if ent is None or ent.leave_type != "ANNUAL" or ent.status != "ACTIVE":
        raise BadRequestException("A cash-up is taken from an ACTIVE annual holiday entitlement.")
    if weeks <= 0:
        raise BadRequestException("weeks must be above zero.")
    requested = nzs._as_date(payload.get("requested_on") or date.today(), "requested_on")
    row = m.PayrollNzCashUpRequest(organization_id=organization_id, legal_entity_id=ent.legal_entity_id,
                                   employee_id=employee_id, employment_id=ent.employment_id, entitlement_id=ent.id,
                                   requested_on=requested, written_request_ref=ref[:300], weeks=weeks,
                                   status="REQUESTED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "requested", "nz_cash_up", row.id, new={"weeks": str(weeks)}, reason=reason)
    return row


def approve_cash_up(db: Session, organization_id: int, request_id: int, actor_id, agreement=None):
    """Four-eyes; the cash-up is paid at the annual-holiday rate (greater of
    OWP and AWE) within the signed limit and the remaining balance."""
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.payroll.service import require_four_eyes

    m = nzs._nz_models()
    lp, ha = _engine(), lv._engine()
    row = _cash_up(db, organization_id, request_id)
    if row.status != "REQUESTED":
        raise BadRequestException("Only a REQUESTED cash-up can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand cash-up", db=db,
                      entity_type="nz_cash_up", entity_id=row.id, current_status=row.status)
    ent = db.get(m.PayrollNzLeaveEntitlement, row.entitlement_id)
    employment = db.get(m.PayrollNzEmployment, row.employment_id)
    employee = db.get(PayrollEmployee, row.employee_id)
    pack = lv._pack(db, organization_id, row.requested_on)
    ledger = ledger_for(db, organization_id, employee.id, employment)
    end = _last_period_end(ledger, row.requested_on)
    rates = agreement_rates(db, organization_id, employee, row.requested_on, agreement)
    line = lv._blocked(lp.cash_up_pay, row.weeks, ha.balance(ent), rates["weekly"], ledger, end, pack)
    calc = _write(db, organization_id, employment, line, row.requested_on, pack,
                  {"agreement": rates, "lastPeriodEnd": end, "ledgerRowIds": [r["id"] for r in ledger],
                   "cashUpRequestId": row.id}, actor_id, entitlement_id=ent.id)
    row.status, row.leave_pay_calculation_id = "APPROVED", calc.id
    row.approved_by_id, row.approved_at = actor_id, datetime.utcnow()
    db.flush()
    return row


def reject_cash_up(db: Session, organization_id: int, request_id: int, actor_id, reason=None):
    reason = nzs._nz_reason(reason)
    row = _cash_up(db, organization_id, request_id)
    if row.status != "REQUESTED":
        raise BadRequestException("Only a REQUESTED cash-up can be rejected.")
    row.status = "REJECTED"
    db.flush()
    nzs._nz_audit(db, actor_id, "rejected", "nz_cash_up", row.id, new={"status": "REJECTED"}, reason=reason)
    return row


def cash_up_view(row) -> dict:
    return {"id": row.id, "entitlementId": row.entitlement_id, "requestedOn": lv._iso(row.requested_on),
            "writtenRequestRef": row.written_request_ref, "weeks": lv._num(row.weeks),
            "leavePayCalculationId": row.leave_pay_calculation_id, "status": row.status}


# ── PAID ────────────────────────────────────────────────────────────────────
def mark_paid(db: Session, run) -> int:
    """At PAID: every leave-pay line the run's snapshots carried becomes PAID
    (run + payslip), its leave event PAID, and a cash-up PAID with the weeks
    added to the entitlement's paid_out. Idempotent."""
    m = nzs._nz_models()
    C, V, Q, L = (m.PayrollNzLeavePayCalculation, m.PayrollNzLeaveEvent, m.PayrollNzCashUpRequest,
                  m.PayrollNzLeaveEntitlement)
    ha = lv._engine()
    paid = 0
    for item in nzs._nz_run_items(db, run):
        snapshot = item.nz_calculation_snapshot or {}
        for line in (snapshot.get("leavePay") or []) + (snapshot.get("finalPay") or []):
            calc = db.get(C, line.get("calculationId"))
            if calc is None or calc.employee_id != item.employee_id or calc.status != "CALCULATED":
                continue
            calc.status, calc.run_id, calc.payslip_item_id = "PAID", run.id, item.id
            paid += 1
            if calc.leave_event_id:
                event = db.get(V, calc.leave_event_id)
                if event is not None and event.status == "APPROVED":
                    event.status = "PAID"
            cash_up = db.query(Q).filter(Q.leave_pay_calculation_id == calc.id, Q.status == "APPROVED").first()
            if cash_up is not None:
                cash_up.status = "PAID"
                ent = db.get(L, cash_up.entitlement_id)
                ent.paid_out = Decimal(str(ent.paid_out or 0)) + Decimal(str(cash_up.weeks))
                if ha.balance(ent) <= 0:
                    ent.status = "PAID_OUT"
    db.flush()
    return paid

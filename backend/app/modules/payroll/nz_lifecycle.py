"""New Zealand payment lifecycle (ZP-NZ-ENG-001 Phase 6; spec §10, NZ-006,
NZ-021): final-pay cases, out-of-cycle / lump-sum / holiday-advance / final
runs, compensating corrections and rehire.

  final pay     one case per employment. Calculating it vests everything due
                up to the termination date first, then resolves EVERY
                entitlement: annual and alternative balances are paid, holiday
                pay on the unvested period is paid (unless pay-as-you-go),
                sick / bereavement / family-violence are listed as not
                payable. When the FINAL run is PAID the employment ends and
                the entitlements are closed with their history kept (never
                zeroed).
  corrections   refused while the signed correction policy is pending. The
                original PAID payslip is never touched: its frozen context is
                replayed with the corrected inputs and a CORRECTION payslip
                carries only the deltas; its year-to-date entries post as
                CORRECTION.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_pay_service as lps
from app.modules.payroll import nz_leave_service as lv

SPECIAL_RUN_KINDS = ("OUT_OF_CYCLE", "LUMP_SUM", "HOLIDAY_PAY_ADVANCE", "FINAL")
CORRECTION_POLICY = "COMPENSATING_DELTA"
CORRECTABLE_INPUTS = ("gross", "basic", "overtime", "additional_compensation", "nz_components", "nz_hours")
OPTION_KEYS = ("holidayAdvanceMethod", "advancePeriods", "lumpSumComponent", "finalPayCaseId")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"New Zealand ({code}): {message}")


# ── final pay (spec §10, NZ-021) ────────────────────────────────────────────
def _case(db: Session, organization_id: int, case_id: int):
    m = nzs._nz_models()
    F = m.PayrollNzFinalPayCase
    row = db.query(F).filter(F.id == case_id, F.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("New Zealand final pay case")
    return row


def open_final_pay_case(db: Session, organization_id: int, employee_id: int, termination_date, termination_reason,
                        actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    nzs._nz_employee(db, organization_id, employee_id)
    end = nzs._as_date(termination_date, "termination_date")
    employment = lv.active_employment(db, organization_id, employee_id)
    if employment is None:
        raise BadRequestException("The employee has no ACTIVE New Zealand employment.")
    if end < employment.start_date:
        raise BadRequestException("termination_date cannot be before the employment start date.")
    F = m.PayrollNzFinalPayCase
    if db.query(F.id).filter(F.employment_id == employment.id, F.status != "CANCELLED").first():
        raise BadRequestException("This employment already has a final pay case.")
    label = (str(termination_reason or "").strip() or "UNSPECIFIED")[:30]
    row = F(organization_id=organization_id, legal_entity_id=employment.legal_entity_id, employee_id=employee_id,
            employment_id=employment.id, termination_date=end, termination_reason=label, status="OPEN",
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "opened", "nz_final_pay_case", row.id, new={"termination_date": end.isoformat()},
                  reason=reason)
    return row


def _last_anniversary(anchor: date, end: date) -> Optional[date]:
    ha = lv._engine()
    last, k = None, 1
    while True:
        on = ha.add_months(anchor, 12 * k)
        if on > end:
            return last
        last, k = on, k + 1


def _advance_paid(db: Session, employee_id: int, since: date) -> Decimal:
    """Holiday pay already paid in advance (PAID HOLIDAY_PAY_ADVANCE runs)."""
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    rows = (db.query(PayslipItem.gross_pay).join(PayrollRun, PayrollRun.id == PayslipItem.payroll_run_id)
            .filter(PayslipItem.employee_id == employee_id, PayrollRun.nz_payment_kind == "HOLIDAY_PAY_ADVANCE",
                    PayrollRun.status.in_((PayrollStatus.PAID, PayrollStatus.CLOSED)), PayrollRun.pay_date >= since)
            .all())
    return sum((Decimal(str(g or 0)) for (g,) in rows), Decimal("0"))


def calculate_final_pay(db: Session, organization_id: int, case_id: int, actor_id, agreement=None):
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    lp, ha = lps._engine(), lv._engine()
    case = _case(db, organization_id, case_id)
    if case.status not in ("OPEN", "CALCULATED"):
        raise BadRequestException("Only an OPEN or CALCULATED final pay case can be (re)calculated.")
    C, L = m.PayrollNzLeavePayCalculation, m.PayrollNzLeaveEntitlement
    for old in db.query(C).filter(C.final_pay_case_id == case.id, C.status == "CALCULATED"):
        old.status = "VOID"
    db.flush()
    end = case.termination_date
    lv.vest_entitlements(db, organization_id, end, employee_id=case.employee_id, actor_id=actor_id)
    employment = db.get(m.PayrollNzEmployment, case.employment_id)
    employee = db.get(PayrollEmployee, case.employee_id)
    anchor = lv.anchor_date(db, employment)
    last = _last_anniversary(anchor, end)
    since = last or anchor
    entitlements = (db.query(L).filter(L.employment_id == employment.id, L.status.in_(("ACTIVE", "EXHAUSTED")))
                    .order_by(L.entitlement_date, L.id).all())
    facts = [{"id": e.id, "leave_type": e.leave_type, "unit": e.unit, "balance": ha.balance(e)} for e in entitlements]
    pack = lv._pack(db, organization_id, end)
    ledger = lps.ledger_for(db, organization_id, employee.id, employment)
    period_end = lps._last_period_end(ledger, end + timedelta(days=1))
    rates = lps.agreement_rates(db, organization_id, employee, end, agreement)
    advance = _advance_paid(db, employee.id, since)
    lines = lv._blocked(lp.final_pay, facts, payg_eligible=employment.payg_eligible, since=since,
                        termination_date=end, ledger=ledger, agreement_weekly=rates["weekly"],
                        agreement_daily=rates["daily"], daily_pay_varies=rates["varies"], advance_paid=advance,
                        last_period_end=period_end, pack=pack)
    outstanding = []
    for line in lines:
        entry = {"entitlementId": line.entitlement_id, "purpose": line.purpose, "units": str(line.units),
                 "unit": line.unit, "amount": str(line.amount), "reason": line.reason}
        if line.method_pair != "NONE":
            calc = lps._write(db, organization_id, employment, line, end, pack,
                              {"agreement": rates, "since": since, "advancePaid": advance,
                               "ledgerRowIds": [r["id"] for r in ledger]}, actor_id, case_id=case.id)
            entry["calculationId"] = calc.id
        outstanding.append(entry)
    case.outstanding, case.last_anniversary, case.status = nzs._json_safe(outstanding), last, "CALCULATED"
    case.updated_at = datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "calculated", "nz_final_pay_case", case.id,
                  new={"lines": len(outstanding), "since": since.isoformat()})
    return case


def approve_final_pay(db: Session, organization_id: int, case_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    case = _case(db, organization_id, case_id)
    if case.status != "CALCULATED":
        raise BadRequestException("Only a CALCULATED final pay case can be approved.")
    require_four_eyes(case.created_by_id, actor_id, "Approving a New Zealand final pay", db=db,
                      entity_type="nz_final_pay_case", entity_id=case.id, current_status=case.status)
    case.status, case.approved_by_id, case.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    nzs._nz_audit(db, actor_id, "approved", "nz_final_pay_case", case.id, old={"status": "CALCULATED"},
                  new={"status": "APPROVED"})
    return case


def cancel_final_pay(db: Session, organization_id: int, case_id: int, actor_id, reason=None):
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    case = _case(db, organization_id, case_id)
    if case.status in ("PAID", "CANCELLED"):
        raise BadRequestException("A PAID or CANCELLED final pay case cannot be cancelled.")
    C = m.PayrollNzLeavePayCalculation
    for calc in db.query(C).filter(C.final_pay_case_id == case.id, C.status == "CALCULATED"):
        calc.status = "VOID"
    case.status = "CANCELLED"
    db.flush()
    nzs._nz_audit(db, actor_id, "cancelled", "nz_final_pay_case", case.id, new={"status": "CANCELLED"},
                  reason=reason)
    return case


def final_case_view(case) -> dict:
    return {"id": case.id, "employeeId": case.employee_id, "employmentId": case.employment_id,
            "terminationDate": lv._iso(case.termination_date), "terminationReason": case.termination_reason,
            "lastAnniversary": lv._iso(case.last_anniversary), "outstanding": case.outstanding or [],
            "runId": case.run_id, "status": case.status}


def final_pay_lines_for_run(db: Session, run, employee) -> list:
    """The APPROVED case this FINAL run carries (run options finalPayCaseId)."""
    m = nzs._nz_models()
    options = getattr(run, "nz_run_options", None) or {}
    if (getattr(run, "nz_payment_kind", None) or "").upper() != "FINAL" or not options.get("finalPayCaseId"):
        return []
    case = db.get(m.PayrollNzFinalPayCase, int(options["finalPayCaseId"]))
    if case is None or case.employee_id != employee.id or case.status != "APPROVED":
        return []
    C = m.PayrollNzLeavePayCalculation
    return [{"calculationId": c.id, "purpose": c.purpose, "amount": str(c.amount)}
            for c in db.query(C).filter(C.final_pay_case_id == case.id, C.status == "CALCULATED").order_by(C.id)]


def on_final_run_paid(db: Session, run) -> None:
    """The FINAL run is PAID: close the case, end the employment and close the
    entitlements with their history kept (NZ-021)."""
    m = nzs._nz_models()
    options = getattr(run, "nz_run_options", None) or {}
    if (getattr(run, "nz_payment_kind", None) or "").upper() != "FINAL" or not options.get("finalPayCaseId"):
        return
    case = db.get(m.PayrollNzFinalPayCase, int(options["finalPayCaseId"]))
    if case is None or case.status != "APPROVED":
        return
    C, L, E = m.PayrollNzLeavePayCalculation, m.PayrollNzLeaveEntitlement, m.PayrollNzEmployment
    for calc in db.query(C).filter(C.final_pay_case_id == case.id, C.status == "PAID"):
        if calc.entitlement_id and calc.unit in ("WEEKS", "DAYS"):
            ent = db.get(L, calc.entitlement_id)
            ent.paid_out = Decimal(str(ent.paid_out or 0)) + Decimal(str(calc.units))
            ent.status = "PAID_OUT"
    for entry in case.outstanding or []:
        if entry.get("calculationId") is None and entry.get("entitlementId"):
            ent = db.get(L, entry["entitlementId"])
            ent.expires_on = case.termination_date           # not payable: kept, expired - never zeroed
    employment = db.get(E, case.employment_id)
    employment.status, employment.end_date = "ENDED", case.termination_date
    employment.termination_reason = case.termination_reason
    case.status, case.run_id = "PAID", run.id
    db.flush()


# ── special runs (spec §10) ─────────────────────────────────────────────────
def create_special_run(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    """An OUT_OF_CYCLE / LUMP_SUM / HOLIDAY_PAY_ADVANCE / FINAL run. It may
    overlap a regular run's period (it is a separate payment)."""
    from app.core.code_generation import generate_business_code
    from app.modules.payroll.models import PayrollRun, PayrollStatus
    from app.modules.payroll.service import generate_payslips_for_run

    reason = nzs._nz_reason(reason)
    payload = dict(payload or {})
    kind = str(payload.get("kind") or "").strip().upper()
    if kind not in SPECIAL_RUN_KINDS:
        raise BadRequestException(f"kind must be one of: {', '.join(SPECIAL_RUN_KINDS)}.")
    pay_date = nzs._as_date(payload.get("payDate"), "payDate")
    start = nzs._as_date(payload.get("periodStart") or pay_date, "periodStart")
    end = nzs._as_date(payload.get("periodEnd") or pay_date, "periodEnd")
    if end < start:
        raise BadRequestException("periodEnd cannot be before periodStart.")
    employee_ids = [int(e) for e in payload.get("employeeIds") or []]
    if not employee_ids:
        raise BadRequestException("A special run names its employees.")
    for employee_id in employee_ids:
        nzs._nz_employee(db, organization_id, employee_id)
    options = {k: v for k, v in dict(payload.get("options") or {}).items() if k in OPTION_KEYS}
    case = None
    if kind == "FINAL":
        if len(employee_ids) != 1 or not options.get("finalPayCaseId"):
            raise BadRequestException("A FINAL run is for one employee and names its final pay case.")
        case = _case(db, organization_id, int(options["finalPayCaseId"]))
        if case.employee_id != employee_ids[0] or case.status != "APPROVED":
            raise BadRequestException("The final pay case must be APPROVED and belong to the employee.")
    run = PayrollRun(organization_id=organization_id, created_by=actor_id, calculation_mode="standard",
                     period_label=f"NZ {kind.replace('_', ' ').title()} {pay_date.isoformat()}", period_start=start,
                     period_end=end, pay_date=pay_date, status=PayrollStatus.DRAFT, nz_payment_kind=kind,
                     nz_run_options=options or None, notes=reason)
    run.run_code = generate_business_code(db, organization_id, "PY", PayrollRun, "run_code", "%Y%m")
    db.add(run)
    db.flush()
    if case is not None:
        case.run_id = run.id
    nzs._nz_audit(db, actor_id, "created", "nz_special_run", run.id, new={"kind": kind}, reason=reason)
    db.commit()
    return generate_payslips_for_run(db, run, organization_id, employee_ids=employee_ids)


# ── corrections (NZ-006) ────────────────────────────────────────────────────
def _correction(db: Session, organization_id: int, correction_id: int):
    m = nzs._nz_models()
    K = m.PayrollNzCorrection
    row = db.query(K).filter(K.id == correction_id, K.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("New Zealand correction")
    return row


def _policy_signed(db: Session, on: date) -> bool:
    rate_map, _slabs, _pack = nzs._nz_pack_in_force(db, on)
    row = (rate_map or {}).get("nz_correction_policy")
    if row is None or "[PENDING G1]" in (row.label or ""):
        return False
    return (row.text_value or "").strip().upper() == CORRECTION_POLICY


def _delta(after: dict, before: dict) -> dict:
    keys = sorted(set(after) | set(before))
    return {k: str(Decimal(str(after.get(k) or 0)) - Decimal(str(before.get(k) or 0))) for k in keys}


def create_correction(db: Session, organization_id: int, original_item_id: int, input_delta: dict, actor_id,
                      reason=None):
    from app.modules.payroll.engine.countries import new_zealand as engine
    from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    item = db.query(PayslipItem).filter(PayslipItem.id == original_item_id,
                                        PayslipItem.organization_id == organization_id).first()
    if item is None or item.country_code != nzs.NZ:
        raise NotFoundException("New Zealand payslip")
    run = db.get(PayrollRun, item.payroll_run_id)
    if run.status not in (PayrollStatus.PAID, PayrollStatus.CLOSED):
        raise BadRequestException("Only a PAID payslip is corrected; an unpaid run is recalculated instead.")
    if not _policy_signed(db, run.pay_date):
        _conflict("NZ_CORRECTION_POLICY_PENDING", "the retro-pay and correction policy is not signed (NZ-006).")
    snapshot = item.nz_calculation_snapshot or {}
    frozen = snapshot.get("frozenContext")
    if not frozen:
        raise BadRequestException("The payslip has no frozen New Zealand calculation to correct from.")
    delta = dict(input_delta or {})
    unknown = sorted(set(delta) - set(CORRECTABLE_INPUTS))
    if not delta or unknown:
        raise BadRequestException(f"input_delta may change only: {', '.join(CORRECTABLE_INPUTS)}.")
    ctx = nzs.nz_thaw_context(frozen)
    for key, value in delta.items():
        setattr(ctx, key, value if key == "nz_components" else Decimal(str(value)))
    try:
        corrected = engine.calculate(ctx)["nz_result"]
    except NZCalculationBlockedError as exc:
        _conflict(exc.key, exc.reason)
    gross_before = Decimal(str((frozen.get("ctx") or {}).get("gross") or 0))
    result_delta = {
        "gross": str(Decimal(str(getattr(ctx, "gross"))) - gross_before),
        "netPay": str(Decimal(corrected["netPay"]) - Decimal(str(snapshot.get("netPay") or 0))),
        "obligations": _delta(corrected["obligations"], snapshot.get("obligations") or {}),
        "accumulatorDeltas": _delta(corrected["accumulatorDeltas"], snapshot.get("accumulatorDeltas") or {}),
        "correctedHashes": corrected.get("hashes"),
    }
    row = m.PayrollNzCorrection(organization_id=organization_id, employee_id=item.employee_id,
                                original_payslip_item_id=item.id, reason=reason,
                                input_delta=nzs._json_safe(delta), result_delta=result_delta, status="DRAFT",
                                created_by_id=actor_id)
    db.add(row)
    db.flush()
    nzs._nz_audit(db, actor_id, "created", "nz_correction", row.id, new={"original": item.id}, reason=reason)
    return row


def approve_correction(db: Session, organization_id: int, correction_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _correction(db, organization_id, correction_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT correction can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand correction", db=db,
                      entity_type="nz_correction", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    return row


def apply_correction(db: Session, organization_id: int, correction_id: int, pay_date, actor_id):
    """A CORRECTION run whose payslip carries only the deltas; the original is
    untouched. At PAID its year-to-date entries post as CORRECTION."""
    from app.core.code_generation import generate_business_code
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    row = _correction(db, organization_id, correction_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED correction can be applied.")
    original = db.get(PayslipItem, row.original_payslip_item_id)
    source_run = db.get(PayrollRun, original.payroll_run_id)
    on = nzs._as_date(pay_date, "payDate")
    run = PayrollRun(organization_id=organization_id, created_by=actor_id, calculation_mode="standard",
                     period_label=f"NZ Correction {on.isoformat()}", period_start=source_run.period_start,
                     period_end=source_run.period_end, pay_date=on, status=PayrollStatus.REVIEW,
                     nz_payment_kind="CORRECTION", nz_run_options={"correctionId": row.id})
    run.run_code = generate_business_code(db, organization_id, "PY", PayrollRun, "run_code", "%Y%m")
    db.add(run)
    db.flush()
    delta = row.result_delta or {}
    obligations = delta.get("obligations") or {}
    snapshot = {"paymentKind": "CORRECTION", "correctionOf": original.id, "correctionId": row.id,
                "deltas": delta, "netPay": delta.get("netPay"), "obligations": obligations,
                "accumulatorDeltas": delta.get("accumulatorDeltas") or {}, "exceptions": []}
    snapshot["hashes"] = {"resultHash": hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    deductions = sum((Decimal(obligations.get(k) or 0) for k in ("studentLoan", "ksEmployee", "childSupport")),
                     Decimal("0"))
    item = PayslipItem(payroll_run_id=run.id, employee_id=original.employee_id, organization_id=organization_id,
                       employee_name=original.employee_name, country_code=nzs.NZ,
                       gross_pay=Decimal(delta.get("gross") or 0), tds=Decimal(obligations.get("payeTotal") or 0),
                       total_deductions=deductions, net_pay=Decimal(delta.get("netPay") or 0),
                       nz_correction_of_id=original.id, nz_calculation_snapshot=snapshot)
    db.add(item)
    db.flush()
    row.status, row.correction_run_id, row.correction_payslip_item_id = "APPLIED", run.id, item.id
    db.flush()
    nzs._nz_audit(db, actor_id, "applied", "nz_correction", row.id, new={"run": run.id})
    return row


def void_correction(db: Session, organization_id: int, correction_id: int, actor_id, reason=None):
    reason = nzs._nz_reason(reason)
    row = _correction(db, organization_id, correction_id)
    if row.status not in ("DRAFT", "APPROVED"):
        raise BadRequestException("Only a DRAFT or APPROVED correction can be voided.")
    row.status = "VOID"
    db.flush()
    nzs._nz_audit(db, actor_id, "voided", "nz_correction", row.id, new={"status": "VOID"}, reason=reason)
    return row


def correction_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "originalPayslipItemId": row.original_payslip_item_id,
            "correctionRunId": row.correction_run_id, "correctionPayslipItemId": row.correction_payslip_item_id,
            "reason": row.reason, "inputDelta": row.input_delta, "resultDelta": row.result_delta,
            "status": row.status}


# ── rehire (spec §10) ───────────────────────────────────────────────────────
def rehire(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id, reason=None):
    """A new employment instance after the previous one ENDED: NEW_INSTANCE
    (new anniversaries) unless continuity is evidenced."""
    m = nzs._nz_models()
    E = m.PayrollNzEmployment
    if lv.active_employment(db, organization_id, employee_id) is not None:
        raise BadRequestException("The employee still has an ACTIVE New Zealand employment.")
    previous = (db.query(E).filter(E.organization_id == organization_id, E.employee_id == employee_id,
                                   E.status == "ENDED").order_by(E.end_date.desc(), E.id.desc()).first())
    if previous is None:
        raise BadRequestException("A rehire follows an ENDED employment.")
    payload = dict(payload or {})
    if str(payload.get("continuity_rule") or "").upper() == "CONTINUOUS":
        payload["prior_employment_id"] = previous.id
    return lv.record_nz_employment(db, organization_id, employee_id, payload, actor_id, reason)

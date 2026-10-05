"""
modules/payroll/hk_corrections.py
---------------------------------
Linked corrections of COMMITTED Hong Kong payroll (ZP-HK-ENG-001 §12
"CORRECTED_BY_LINKED_ADJUSTMENT"; gap-closure D-14, Option B — HK-specific).

Design (the Singapore append-only pattern, HK-owned, no shared-table change):

* The original payslip, its run and its frozen trace are NEVER modified.
* A correction is a DELTA payslip in its own correction run (notes start with
  ``[HK-CORRECTION]``), booked to the ORIGINAL wage period, so every period-based
  aggregation (MPF / eMPF month, IR56B year of assessment, the 12-month average
  wage) attributes it to the period it corrects.
* The corrected figures are recalculated on the original payslip's own frozen
  statutory snapshot (pinned pack + tax_rule_snapshot) from the employee's
  current facts — the delta is (recalculated − original − earlier approved deltas).
* Maker-checker: the requester can never approve (enforced when the correction
  run moves to APPROVED through the shared run lifecycle). Approval and every
  statutory consequence are written in ONE transaction.
* Consequences are recorded on the correction: IRD amendment cases for filed
  returns, invalidation of unfiled returns, eMPF supersede / supplementary batch,
  IR56G hold treatment, average-wage and termination results to review, stale
  generated reports, employee copies to re-deliver.
* Fail-closed refusals: an MPF period still accruing under the 60-day rule or
  already caught up by a later payslip, a change of MPF coverage status, any
  income-tax withholding (HK never withholds), a duplicate open correction.

Every query is tenant-scoped by the caller's organization_id.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import hk_service
from app.modules.payroll.engine.jurisdictions.hong_kong import ird as hk_ird, tax_clearance as hk_tc
from app.modules.payroll.engine.jurisdictions.hong_kong.common import ZERO, canonical_hash, dec, year_of_assessment
from app.modules.payroll.models import (
    GeneratedReport, HkgAverageWageSnapshot, HkgEmpfSubmission, HkgIrdReportingCase, HkgPayslipCorrection,
    HkgTaxClearanceHold, HkgTerminationResult, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem, PayslipStatus,
)

MARKER = "[HK-CORRECTION]"
LEGAL_REFERENCE = "ZP-HK-ENG-001 §12 (linked adjustment, D-14)"
DELTA_COLUMNS = ("basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
                 "attendance_deduction", "employee_pension", "employer_pension", "total_deductions", "net_pay")
SUBMITTED_EMPF_STATES = ("SUBMITTED", "ACCEPTED", "PARTIAL", "PAID", "RECONCILED")
HK_REPORT_TYPES = ("HK_BIR56A", "HK_IR56B", "HK_IR56E", "HK_IR56F", "HK_IR56G", "HK_EMPF_REMITTANCE",
                   "HK_MPF_CONTRIBUTION_RECORD", "HK_TERMINATION_STATEMENT")


def is_correction_run(run) -> bool:
    return bool(run is not None and (run.notes or "").startswith(MARKER))


def is_delta(item) -> bool:
    return bool((getattr(item, "hkg_calculation_trace", None) or {}).get("correction"))


def correction_for_run(db: Session, run: PayrollRun) -> Optional[HkgPayslipCorrection]:
    return (db.query(HkgPayslipCorrection)
            .filter(HkgPayslipCorrection.correction_run_id == run.id,
                    HkgPayslipCorrection.organization_id == run.organization_id).first())


def _correction(db: Session, organization_id: int, correction_id: int) -> HkgPayslipCorrection:
    row = (db.query(HkgPayslipCorrection)
           .filter(HkgPayslipCorrection.id == correction_id, HkgPayslipCorrection.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Hong Kong payroll correction", correction_id)
    return row


def _conflict(detail: str):
    return HTTPException(http_status.HTTP_409_CONFLICT, detail=detail)


# ── additive statutory quantities of a trace ────────────────────────────

def metrics(trace: dict) -> dict:
    """Every additive quantity of an HK payslip trace, as Decimals — the basis
    of before / after / delta. Non-additive facts (coverage status, rules)
    are not metrics."""
    t = trace or {}
    out: dict = {}

    def put(key, value):
        out[key] = out.get(key, ZERO) + dec(value)

    for obligation, block in (t.get("classification") or {}).items():
        for part in ("included", "excluded", "review"):
            put(f"cls:{obligation}:{part}", block.get(part))
        for line in block.get("lines") or []:
            put(f"line:{obligation}:{line.get('component')}:{line.get('treatment')}", line.get("amount"))
    mpf = t.get("mpf") or {}
    put("mpf:relevantIncome", (mpf.get("currentPeriod") or {}).get("relevantIncome"))
    put("mpf:employer", mpf.get("employer"))
    put("mpf:employee", mpf.get("employee"))
    for field, amount in ((t.get("ird") or {}).get("reportable") or {}).items():
        put(f"ird:{field}", amount)
    put("smw:countableWages", (t.get("minimumWage") or {}).get("countableWages"))
    for key in ("gross", "mpfEmployee", "mpfEmployer", "netPay", "employerCost"):
        put(f"result:{key}", (t.get("result") or {}).get(key))
    return out


def _fmt(values: dict) -> dict:
    return {k: str(v) for k, v in sorted(values.items())}


def _delta_trace(original: dict, after: dict, delta: dict, meta: dict) -> dict:
    """An HK trace whose amounts are the DELTA, in the same shape every HK
    aggregation reads (classification / mpf / ird / minimumWage / result)."""
    a = after or {}
    classification = {}
    for obligation in sorted({k.split(":")[1] for k in delta if k.startswith(("cls:", "line:"))}):
        lines = []
        for key, value in sorted(delta.items()):
            if key.startswith(f"line:{obligation}:") and value:
                _p, _o, component, treatment = key.split(":", 3)
                lines.append({"component": component, "amount": str(value), "treatment": treatment})
        classification[obligation] = {part: str(delta.get(f"cls:{obligation}:{part}", ZERO))
                                      for part in ("included", "excluded", "review")}
        classification[obligation]["lines"] = lines
    after_mpf = a.get("mpf") or {}
    return {
        "engine": a.get("engine") or original.get("engine"), "country": "HK",
        "period": original.get("period"), "profileId": a.get("profileId"),
        "classification": classification,
        "mpf": {"coverage": after_mpf.get("coverage"),
                "currentPeriod": {"relevantIncome": str(delta.get("mpf:relevantIncome", ZERO)),
                                  "employer": str(delta.get("mpf:employer", ZERO)),
                                  "employee": str(delta.get("mpf:employee", ZERO))},
                "catchUp": [], "employer": str(delta.get("mpf:employer", ZERO)),
                "employee": str(delta.get("mpf:employee", ZERO)),
                "contributionDay": after_mpf.get("contributionDay"),
                "rounding": after_mpf.get("rounding"),
                "basis": f"correction delta of payslip {meta['originalPayslipId']} (booked to its wage period)"},
        "minimumWage": {"countableWages": str(delta.get("smw:countableWages", ZERO)),
                        "status": (a.get("minimumWage") or {}).get("status")},
        "ird": {"yearOfAssessment": (original.get("ird") or {}).get("yearOfAssessment"),
                "reportable": {k.split(":", 1)[1]: str(v) for k, v in sorted(delta.items()) if k.startswith("ird:") and v},
                "basis": "correction delta — accumulated into the original payment's year of assessment"},
        "salariesTax": original.get("salariesTax") or {"withholding": "NONE"},
        "result": {k.split(":", 1)[1]: str(delta.get(k, ZERO))
                   for k in ("result:gross", "result:mpfEmployee", "result:mpfEmployer", "result:netPay",
                             "result:employerCost")},
        "correction": meta,
    }


def _update_run_totals(db: Session, run: PayrollRun) -> None:
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    run.employee_count = len(items)
    run.total_gross = sum((dec(i.gross_pay) for i in items), ZERO)
    run.total_deductions = sum((dec(i.total_deductions) for i in items), ZERO)
    run.total_employer_contribution = sum((dec(i.employer_pension) for i in items), ZERO)
    run.total_net = sum((dec(i.net_pay) for i in items), ZERO)


# ── request (maker) ─────────────────────────────────────────────────────

def request_correction(db: Session, organization_id: int, payslip_id: int, reason: str,
                       actor_id: Optional[int]) -> HkgPayslipCorrection:
    from app.modules.payroll import service

    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("a Hong Kong payroll correction needs a reason")
    item = (db.query(PayslipItem)
            .filter(PayslipItem.id == payslip_id, PayslipItem.organization_id == organization_id).first())
    if item is None:
        raise NotFoundException("Payslip", payslip_id)
    if (item.country_code or "").upper() != hk_service.HK or not item.hkg_calculation_trace:
        raise BadRequestException("linked corrections here are for Hong Kong payslips only")
    if is_delta(item):
        raise BadRequestException("correct the original payslip, not a correction delta")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).with_for_update().one()
    if run.status not in hk_service.COMMITTED_RUN_STATUSES:
        raise BadRequestException("only a committed (approved) payslip is corrected by a linked adjustment — "
                                  "recalculate a Draft / Review payslip in place")
    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == item.employee_id, PayrollEmployee.organization_id == organization_id)
                .with_for_update().one())
    from app.modules.payroll.service import _normalize_country

    if _normalize_country(employee.country_code or "") != hk_service.HK:
        raise _conflict("the employee is no longer a Hong Kong employee — recalculating would use another country's "
                        "rules; a cross-jurisdiction change is not a linked adjustment")
    open_row = (db.query(HkgPayslipCorrection)
                .filter(HkgPayslipCorrection.organization_id == organization_id,
                        HkgPayslipCorrection.original_payslip_id == item.id,
                        HkgPayslipCorrection.status == "REQUESTED").first())
    if open_row is not None:
        raise _conflict(f"correction #{open_row.id} of payslip {item.id} is still awaiting approval — approve or "
                        "reject it before requesting another")
    trace = item.hkg_calculation_trace
    coverage = ((trace.get("mpf") or {}).get("coverage") or {}).get("status")
    if coverage == "PENDING_60_DAY":
        raise _conflict("this payslip's MPF was accruing under the 60-day rule and is caught up by a later payslip — "
                        "correcting a pending period needs Hong Kong specialist review (G1); not automated")
    for later in (db.query(PayslipItem)
                  .filter(PayslipItem.organization_id == organization_id, PayslipItem.employee_id == employee.id,
                          PayslipItem.id != item.id, PayslipItem.hkg_calculation_trace.isnot(None)).all()):
        caught = {c.get("payslipId") for c in ((later.hkg_calculation_trace or {}).get("mpf") or {}).get("catchUp") or []}
        if item.id in caught:
            raise _conflict(f"payslip {later.id} caught up this period's MPF — correcting it would leave that catch-up "
                            "stale; needs Hong Kong specialist review (G1); not automated")

    chain = [(c, db.get(PayslipItem, c.delta_payslip_id)) for c in
             db.query(HkgPayslipCorrection).filter(HkgPayslipCorrection.original_payslip_id == item.id,
                                                   HkgPayslipCorrection.status == "APPROVED")
             .order_by(HkgPayslipCorrection.sequence).all()]
    effective = metrics(trace)
    effective_cols = {c: dec(getattr(item, c, None)) for c in DELTA_COLUMNS}
    for _c, delta_item in chain:
        for key, value in metrics(delta_item.hkg_calculation_trace).items():
            effective[key] = effective.get(key, ZERO) + value
        for col in DELTA_COLUMNS:
            effective_cols[col] += dec(getattr(delta_item, col, None))

    after_values = service._hk_frozen_recompute(db, run, employee, item, organization_id)
    after_trace = after_values.get("hkg_calculation_trace") or {}
    if dec(after_values.get("tds")) != ZERO:
        raise _conflict("the recalculation shows income-tax withholding — Hong Kong payroll never withholds Salaries Tax")
    after_coverage = ((after_trace.get("mpf") or {}).get("coverage") or {}).get("status")
    if after_coverage != coverage:
        raise _conflict(f"the recalculation changes MPF coverage from {coverage} to {after_coverage} — a coverage change "
                        "is not a linked adjustment; needs Hong Kong specialist review (G1)")
    after = metrics(after_trace)
    keys = sorted(set(effective) | set(after))
    delta = {k: after.get(k, ZERO) - effective.get(k, ZERO) for k in keys}
    col_delta = {c: dec(after_values.get(c)) - effective_cols[c] for c in DELTA_COLUMNS}
    if not any(delta.values()) and not any(col_delta.values()):
        raise BadRequestException("the recalculation produces no change — nothing to correct")

    warnings = [{"code": "CURRENT_FACTS_USED",
                 "message": "recalculated on the original payslip's frozen statutory pack from the employee's CURRENT pay "
                            "structure, attendance, hours and statutory profile — the checker confirms these are the "
                            f"values that applied to {run.period_label}"}]
    if col_delta["net_pay"] < 0:
        warnings.append({"code": "EMPLOYEE_OVERPAID", "message": f"net pay falls by HK${-col_delta['net_pay']}: the delta is "
                         "NOT paid and is not deducted automatically; any recovery from the employee is a separate step "
                         "(Employment Ordinance deduction rules — Hong Kong specialist, G1)"})
    if col_delta["net_pay"] > 0:
        warnings.append({"code": "WAGES_PAID_AFTER_DUE_DATE", "message": f"HK${col_delta['net_pay']} of wages for "
                         f"{run.period_label} is paid after its original pay date ({run.pay_date})"})
    if delta.get("mpf:employer", ZERO) < 0 or delta.get("mpf:employee", ZERO) < 0:
        warnings.append({"code": "MPF_OVER_CONTRIBUTED", "message": "mandatory contributions fall — an over-contribution "
                         "is not corrected by a negative eMPF row; settle it with the MPF trustee (G1 / G2)"})
    hold = _open_hold(db, organization_id, employee.id)
    if hold is not None:
        warnings.append({"code": "IR56G_CASE_OPEN", "message": f"IR56G case #{hold.id} is {hold.state}: a positive delta "
                         "is withheld (legal hold), never paid out"})

    sequence = db.query(HkgPayslipCorrection).filter(HkgPayslipCorrection.original_payslip_id == item.id).count() + 1
    now = datetime.utcnow().replace(microsecond=0)
    correction = HkgPayslipCorrection(
        organization_id=organization_id, employee_id=employee.id, original_payslip_id=item.id, original_run_id=run.id,
        sequence=sequence, status="REQUESTED", reason=reason, original_trace_hash=canonical_hash(trace),
        before={**_fmt(effective), **{f"col:{c}": str(v) for c, v in effective_cols.items()}},
        after={**_fmt(after), **{f"col:{c}": str(dec(after_values.get(c))) for c in DELTA_COLUMNS}},
        delta={**_fmt(delta), **{f"col:{c}": str(v) for c, v in col_delta.items()}},
        warnings=warnings, requested_by_id=actor_id, requested_at=now)
    db.add(correction)
    db.flush()
    meta = {"correctionId": correction.id, "originalPayslipId": item.id, "originalRunId": run.id, "sequence": sequence,
            "reason": reason, "requestedById": actor_id, "requestedAt": now.isoformat()}
    corr_run = PayrollRun(
        organization_id=organization_id, period_label=f"Correction {sequence} of {run.period_label}"[:50],
        period_start=run.period_start, period_end=run.period_end, pay_date=run.pay_date,
        notes=f"{MARKER} correction #{correction.id} of payslip {item.id} (run {run.id}): {reason}"[:2000],
        created_by=actor_id, calculation_mode=run.calculation_mode)
    db.add(corr_run)
    db.flush()
    delta_item = PayslipItem(
        payroll_run_id=corr_run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name=item.employee_name, department=item.department, designation=item.designation,
        date_of_joining=item.date_of_joining, bank_name=getattr(employee, "bank_name", None),
        bank_account=getattr(employee, "bank_account", None), country_code="HK", status=PayslipStatus.PENDING,
        compliance_fields=item.compliance_fields, tax_policy_pack_id=item.tax_policy_pack_id,
        tax_policy_version=item.tax_policy_version, tax_rule_snapshot=item.tax_rule_snapshot,
        employee_statutory_profile_id=item.employee_statutory_profile_id,
        hkg_calculation_trace=_delta_trace(trace, after_trace, delta, meta),
        notes=f"Correction delta of payslip {item.id} (Hong Kong correction #{correction.id})", tds=ZERO,
        **col_delta)
    db.add(delta_item)
    db.flush()
    correction.correction_run_id, correction.delta_payslip_id = corr_run.id, delta_item.id
    _update_run_totals(db, corr_run)
    hk_service._audit(db, actor_id, "create", "hkg_payslip_correction", correction.id,
                      old={"originalPayslipId": item.id, "before": correction.before},
                      new={"after": correction.after, "delta": correction.delta, "correctionRunId": corr_run.id},
                      reason=reason, commit=False)
    db.commit()
    db.refresh(correction)
    return correction


def _open_hold(db: Session, organization_id: int, employee_id: int) -> Optional[HkgTaxClearanceHold]:
    return (db.query(HkgTaxClearanceHold)
            .filter(HkgTaxClearanceHold.organization_id == organization_id, HkgTaxClearanceHold.employee_id == employee_id,
                    HkgTaxClearanceHold.state.notin_(("INACTIVE", "CASE_CLOSED")))
            .order_by(HkgTaxClearanceHold.id.desc()).first())


# ── approval (checker) — called from the shared run lifecycle ───────────

def before_run_transition(db: Session, run: PayrollRun, next_status, actor_id: Optional[int]) -> None:
    """The HK correction run may only move forward while its correction is
    REQUESTED (to APPROVED) or once it is APPROVED (to the payment states).
    Reaching APPROVED needs a different person from the requester, an
    unchanged original, and applies every statutory consequence in the SAME
    transaction as the approval (nothing here commits)."""
    correction = correction_for_run(db, run)
    if correction is None:
        raise _conflict("this Hong Kong correction run has no correction record — it cannot be advanced")
    if next_status in (PayrollStatus.REVIEW, PayrollStatus.APPROVED) and correction.status != "REQUESTED":
        raise _conflict(f"correction #{correction.id} is {correction.status}")
    if next_status not in (PayrollStatus.REVIEW, PayrollStatus.APPROVED) and correction.status != "APPROVED":
        raise _conflict(f"correction #{correction.id} is not approved")
    if next_status != PayrollStatus.APPROVED:
        return
    hk_service._four_eyes(correction.requested_by_id, actor_id, "Approving a Hong Kong payroll correction")
    original = db.get(PayslipItem, correction.original_payslip_id)
    if original is None or canonical_hash(original.hkg_calculation_trace) != correction.original_trace_hash:
        raise _conflict("the original payslip changed after the correction was requested — reject and request it again")
    correction.status, correction.approved_by_id = "APPROVED", actor_id
    correction.approved_at = datetime.utcnow().replace(microsecond=0)
    correction.consequences = apply_consequences(db, correction, actor_id)
    hk_service._audit(db, actor_id, "status_change", "hkg_payslip_correction", correction.id,
                      old={"status": "REQUESTED"}, new={"status": "APPROVED", "consequences": correction.consequences},
                      reason=correction.reason, commit=False)


def apply_consequences(db: Session, correction: HkgPayslipCorrection, actor_id: Optional[int]) -> dict:
    """Every Hong Kong statutory consequence of an approved correction. Filed
    evidence is never edited: a filed return gets a linked AMENDMENT case; an
    unfiled one is sent back for regeneration; an unsubmitted eMPF batch is
    superseded; results built on the period are listed for review."""
    org = correction.organization_id
    original = db.get(PayslipItem, correction.original_payslip_id)
    ot = original.hkg_calculation_trace or {}
    run = db.get(PayrollRun, correction.original_run_id)
    delta = {k: dec(v) for k, v in (correction.delta or {}).items()}
    period = ot.get("period") or {}
    period_start, period_end = period.get("start"), period.get("end")
    ya = (ot.get("ird") or {}).get("yearOfAssessment") or year_of_assessment(run.pay_date)
    note = f"Hong Kong payroll correction #{correction.id} of payslip {original.id}"
    out = {"ird": [], "empf": [], "taxClearance": [], "averageWage": [], "termination": [], "reports": [],
           "employeeCopies": [], "payment": []}

    ird_changed = any(v for k, v in delta.items() if k.startswith("ird:"))
    if ird_changed:
        cases = (db.query(HkgIrdReportingCase)
                 .filter(HkgIrdReportingCase.organization_id == org, HkgIrdReportingCase.year_of_assessment == ya,
                         HkgIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
                 .filter((HkgIrdReportingCase.employee_id == correction.employee_id)
                         | (HkgIrdReportingCase.form_type == "BIR56A")).all())
        for case in cases:
            if case.form_type == "IR56E":
                continue                                   # commencement: reports no income
            entry = {"caseId": case.id, "form": case.form_type, "yearOfAssessment": ya}
            if case.status in hk_ird.FILED_STATES:
                if case.form_type == "BIR56A":
                    out["ird"].append({**entry, "action": "COVER_ALREADY_FILED",
                                       "note": "submit the amended IR56B under the IRD's amendment procedure (G2)"})
                    continue
                amendment = hk_service.amend_ird_case(db, org, case.id, note, actor_id, commit=False)
                out["ird"].append({**entry, "action": "AMENDMENT_CREATED", "amendmentCaseId": amendment.id})
                if case.employee_copy_delivered_at:
                    out["employeeCopies"].append({"caseId": case.id, "form": case.form_type,
                                                  "action": "DELIVER_AMENDED_COPY", "amendmentCaseId": amendment.id})
            elif case.status in ("DUE", "PREPARED", "VALIDATED", "REJECTED"):
                previous = case.status
                if previous in ("VALIDATED", "REJECTED"):
                    case.status = "PREPARED"
                if case.form_type in ("IR56B", "BIR56A"):
                    case.validation_errors = list(case.validation_errors or []) + [
                        f"{note} changed reported income — prepare the annual return again before filing"]
                out["ird"].append({**entry, "action": "REGENERATE_BEFORE_FILING", "previousStatus": previous})
            elif case.status == "SUPPRESSED":
                out["ird"].append({**entry, "action": "SUPPRESSED_NO_CHANGE"})

    mpf_changed = any(delta.get(k, ZERO) for k in ("mpf:relevantIncome", "mpf:employer", "mpf:employee"))
    if mpf_changed and period_end:
        month = str(period_end)[:7]
        subs = (db.query(HkgEmpfSubmission)
                .filter(HkgEmpfSubmission.organization_id == org, HkgEmpfSubmission.contribution_period == month,
                        HkgEmpfSubmission.status != "AMENDED").all())
        submitted = [s.id for s in subs if s.status in SUBMITTED_EMPF_STATES]
        for sub in subs:
            if sub.status in SUBMITTED_EMPF_STATES:
                continue
            previous = sub.status
            sub.status = "AMENDED"
            sub.validation_errors = list(sub.validation_errors or []) + [f"superseded by {note} — prepare {month} again"]
            hk_service._audit(db, actor_id, "status_change", "hkg_empf_submission", sub.id, old={"status": previous},
                              new={"status": "AMENDED", "supersededBy": f"hkg_payslip_correction:{correction.id}"},
                              commit=False)
            out["empf"].append({"submissionId": sub.id, "action": "SUPERSEDED_UNSUBMITTED", "previousStatus": previous})
        out["empf"].append({"period": month,
                            "action": "SUPPLEMENTARY_BATCH_REQUIRED" if submitted else "PREPARE_PERIOD",
                            "submittedBatchIds": submitted})

    hold = _open_hold(db, org, correction.employee_id)
    if hold is not None:
        if hold.state in hk_tc.HOLDING_STATES:
            out["taxClearance"].append({"holdId": hold.id, "state": hold.state, "action": "DELTA_HELD_UNDER_IR56G"})
        elif hold.state in hk_tc.FINAL_PAY_BLOCKING_STATES:
            out["taxClearance"].append({"holdId": hold.id, "state": hold.state, "action": "PAYMENT_BLOCKED_UNTIL_IR56G_FILED"})

    net = delta.get("col:net_pay", ZERO)
    out["payment"].append({"action": "PAY_DELTA" if net > 0 else ("NOT_PAID_RECOVERY_IS_SEPARATE" if net < 0 else "NO_PAYMENT"),
                           "netDelta": str(net)})

    if period_start and period_end:
        for snap in (db.query(HkgAverageWageSnapshot)
                     .filter(HkgAverageWageSnapshot.organization_id == org,
                             HkgAverageWageSnapshot.employee_id == correction.employee_id).all()):
            if str(snap.lookback_start) <= str(period_end) and str(snap.lookback_end) >= str(period_start):
                out["averageWage"].append({"snapshotId": snap.id, "benefit": snap.benefit_type,
                                           "action": "RECALCULATE_AVERAGE_WAGE"})
    for result in (db.query(HkgTerminationResult)
                   .filter(HkgTerminationResult.organization_id == org,
                           HkgTerminationResult.employee_id == correction.employee_id,
                           HkgTerminationResult.status.in_(("CALCULATED", "APPROVED"))).all()):
        out["termination"].append({"resultId": result.id, "status": result.status, "action": "REVIEW_TERMINATION_WAGES"})
    years = {ya, str(period_end or run.pay_date)[:4]}
    for report in (db.query(GeneratedReport)
                   .filter(GeneratedReport.organization_id == org, GeneratedReport.report_type.in_(HK_REPORT_TYPES),
                           GeneratedReport.reporting_year.in_(tuple(years)))
                   .filter((GeneratedReport.employee_id == correction.employee_id) | (GeneratedReport.employee_id.is_(None)))
                   .all()):
        out["reports"].append({"generatedReportId": report.id, "reportType": report.report_type,
                               "action": "REGENERATE_REPORT"})
    return out


def approve_correction(db: Session, organization_id: int, correction_id: int, actor_id: Optional[int]) -> HkgPayslipCorrection:
    """Moves the correction run through the SHARED lifecycle to APPROVED (the
    four-eyes check and the consequences run in its HK hook)."""
    from app.modules.payroll import service

    correction = _correction(db, organization_id, correction_id)
    if correction.status != "REQUESTED":
        raise _conflict(f"correction #{correction.id} is {correction.status}")
    hk_service._four_eyes(correction.requested_by_id, actor_id, "Approving a Hong Kong payroll correction")
    run = db.get(PayrollRun, correction.correction_run_id)
    while run.status != PayrollStatus.APPROVED:
        run = service.advance_payroll_run_status(db, run.id, actor_id, organization_id)
    db.refresh(correction)
    return correction


def reject_correction(db: Session, organization_id: int, correction_id: int, reason: str,
                      actor_id: Optional[int]) -> HkgPayslipCorrection:
    """Rejects (checker) or withdraws (maker) a REQUESTED correction. Its draft
    correction run and delta payslip were never committed and are discarded;
    the correction record (before / after / delta, reason) is kept."""
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("a rejection needs a reason")
    correction = _correction(db, organization_id, correction_id)
    if correction.status != "REQUESTED":
        raise _conflict(f"correction #{correction.id} is {correction.status}")
    run = db.get(PayrollRun, correction.correction_run_id) if correction.correction_run_id else None
    if run is not None and run.status not in (PayrollStatus.DRAFT, PayrollStatus.REVIEW):
        raise _conflict("the correction run has already moved past Review")
    discarded = {"correctionRunId": correction.correction_run_id, "deltaPayslipId": correction.delta_payslip_id}
    delta_id = correction.delta_payslip_id
    correction.correction_run_id, correction.delta_payslip_id = None, None
    correction.status, correction.rejected_by_id, correction.rejected_reason = "REJECTED", actor_id, reason
    correction.consequences = {"discarded": discarded}
    db.flush()
    if delta_id:
        db.query(PayslipItem).filter(PayslipItem.id == delta_id).delete(synchronize_session=False)
    if run is not None:
        db.delete(run)
    hk_service._audit(db, actor_id, "status_change", "hkg_payslip_correction", correction.id,
                      old={"status": "REQUESTED"}, new={"status": "REJECTED", "discarded": discarded},
                      reason=reason, commit=False)
    db.commit()
    db.refresh(correction)
    return correction


def list_corrections(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    q = db.query(HkgPayslipCorrection).filter(HkgPayslipCorrection.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(HkgPayslipCorrection.employee_id == employee_id)
    return [serialize(c) for c in q.order_by(HkgPayslipCorrection.id.desc()).all()]


def serialize(c: HkgPayslipCorrection) -> dict:
    delta = c.delta or {}
    return {"id": c.id, "employeeId": c.employee_id, "originalPayslipId": c.original_payslip_id,
            "originalRunId": c.original_run_id, "correctionRunId": c.correction_run_id,
            "deltaPayslipId": c.delta_payslip_id, "sequence": c.sequence, "status": c.status, "reason": c.reason,
            "netPayDelta": delta.get("col:net_pay"), "grossPayDelta": delta.get("col:gross_pay"),
            "employeeMpfDelta": delta.get("col:employee_pension"), "employerMpfDelta": delta.get("col:employer_pension"),
            "delta": delta, "before": c.before, "after": c.after, "warnings": c.warnings or [],
            "consequences": c.consequences, "requestedById": c.requested_by_id,
            "requestedAt": hk_service._iso(c.requested_at), "approvedById": c.approved_by_id,
            "approvedAt": hk_service._iso(c.approved_at), "rejectedById": c.rejected_by_id,
            "rejectedReason": c.rejected_reason}


def correction_preflight(db: Session, run: PayrollRun) -> dict:
    """Preflight of a correction run: the correction's own state and warnings
    (an ordinary payroll preflight would dry-run every employee)."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    correction = correction_for_run(db, run)
    checks = []
    if correction is None:
        checks.append(pf.check("HK_CORRECTION_RECORD_MISSING", pf.BLOCK, "this correction run has no correction record"))
    else:
        if correction.status == "REQUESTED":
            checks.append(pf.check("HK_CORRECTION_AWAITING_APPROVAL", pf.INFO,
                                   f"correction #{correction.id} of payslip {correction.original_payslip_id} needs approval "
                                   "by a different operator", action="Approve or reject the correction"))
        for w in correction.warnings or []:
            checks.append(pf.check(f"HK_CORRECTION:{w['code']}", pf.WARN, w["message"]))
    out = pf.summarize(checks)
    out.update({"runId": run.id, "correctionId": correction.id if correction else None,
                "payDate": run.pay_date.isoformat() if run.pay_date else None, "pack": None,
                "employeeCount": 1 if correction else 0, "calculated": 1 if correction else 0, "correction": True})
    return out


def effective_payment_date(db: Session, run: PayrollRun):
    """The date money in a run is actually released: a correction is paid when
    it is approved, not on the original pay date it is booked to."""
    if is_correction_run(run):
        correction = correction_for_run(db, run)
        if correction is not None and correction.approved_at is not None:
            return correction.approved_at.date()
        return datetime.utcnow().date()
    return run.pay_date

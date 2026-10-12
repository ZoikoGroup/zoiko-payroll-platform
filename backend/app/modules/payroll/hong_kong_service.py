"""
modules/payroll/hong_kong_service.py
------------------------------------
Hong Kong statutory workflows (ZP-HK-ENG-001) — the ONLY Hong Kong service
module, on the shared platform the same way Italy's italy_service.py is:

* worker facts on the shared statutory profile, verified hours, the
  calculation inputs the HK engine reads from the pinned pack;
* IRD employer reporting: BIR56A / IR56B annual return, IR56E / IR56F / IR56G
  cases, filing, rejection, amendment (replacement) lifecycle;
* the IR56G tax-clearance hold, average wages, statutory entitlements,
  severance / long-service payment, the Salaries Tax estimate;
* eMPF remittance batches and the eMPF configuration register, the IRD
  software-approval register, IRD XML-schema registration;
* append-only payslip corrections (delta payslips);
* the HK statutory configuration editor, pack golden check, activation
  readiness, report-template coverage and the Super Admin readiness views.

Platform capabilities it USES rather than re-implements: configuration
packs / lifecycle / approvals / audit (service.py), the shared report
template + GeneratedReport pipeline, governed source evidence, the shared
retention_service (access log, legal holds, retention policies) and the
service-registry transition. The platform reaches this module only through
jurisdiction_hooks (registered at the end of this file), never by import, so
the dependency direction is: shared platform <- hong_kong_service <- engine.
"""

import copy
import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException, ZoikoException
from app.modules.payroll import jurisdiction_hooks, retention_service, service
from app.modules.payroll.employee_validation import mask_identifier
from app.modules.payroll.engine.jurisdictions.hong_kong import (
    average_wage as hk_average_wage,
    continuous_contract as hk_cc,
    entitlements as hk_entitlements,
    ird as hk_ird,
    mpf as hk_mpf,
    salaries_tax as hk_salaries_tax,
    tax_clearance as hk_tc,
    termination as hk_termination,
)
from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    add_months,
    canonical_hash,
    cents,
    dec,
    HongKongCalculationBlockedError,
    resolve_timing,
    rule_segments,
    year_of_assessment,
    year_of_assessment_bounds,
    ZERO,
)
from app.modules.payroll.models import (
    CompanyComplianceDetails,
    ContributionRate,
    EmployeeStatus,
    EmployeeStatutoryProfile,
    GeneratedReport,
    HongKongAverageWageSnapshot,
    HongKongEmpfConfiguration,
    HongKongEmpfSubmission,
    HongKongIrdReportingCase,
    HongKongIrdSoftwareApproval,
    HongKongPayslipCorrection,
    HongKongTaxClearanceHold,
    HongKongTaxClearanceHoldLine,
    HongKongTerminationResult,
    HongKongWorkHours,
    JurisdictionPack,
    PayrollEmployee,
    PayrollRun,
    PayrollStatus,
    PayslipItem,
    PayslipStatus,
    ReportTemplate,
    ReportTemplateComponent,
    ReportTemplateComponentField,
    SourceArtifact,
    TaxSlab,
)


# ══════════════════════════════════════════════════════════════════════════
# (was hk_service.py)
# ══════════════════════════════════════════════════════════════════════════

HK = "HK"
SPEC = "ZP-HK-ENG-001 v1.0"
COMMITTED_RUN_STATUSES = (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID, PayrollStatus.CLOSED)
HOURS_SOURCES = ("TIME_ATTENDANCE", "VERIFIED_TIMESHEET", "MANUAL_VERIFIED")
HK_GATES = {
    "G1": "Statutory content — Hong Kong specialist signs wage, MPF, Employment Ordinance and IRD mappings",
    "G2": "Authority conformance — current IRD XML schemas / test files and eMPF workflows pass end-to-end",
    "G3": "Parallel payroll — two representative parallel cycles with no unexplained material variance",
    "G4": "Edge cases — 60-day MPF, contribution holiday, non-monthly, 468 rule, SMW crossover, departure hold, SP/LSP",
    "G5": "Security / privacy — PDPO / HR privacy review, privileged access, retention, encryption, audit",
    "G6": "Operations — filing / payment responsibilities, maker-checker, reconciliation, runbooks approved",
    "G7": "Launch authority — Product, Engineering, QA, Payroll Ops, Security/Privacy, local reviewer approve",
}


def _concurrent_conflict(what: str) -> ZoikoException:
    """409 for a duplicate the database refused (the partial unique indexes of
    migration 2d0cdeeeecc4): a concurrent request created the same row first."""
    return ZoikoException(status_code=409, error_code="CONFLICT",
                          message=f"{what} was created by a concurrent request — reload and retry.")


def _audit(db, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None, commit=True):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     legal_reference=SPEC, old_value=old, new_value=new, reason=reason, auto_commit=commit)


def _employee(db, employee_id: int, organization_id: int) -> PayrollEmployee:
    from app.modules.payroll.service import _normalize_country, get_employee_by_id

    employee = get_employee_by_id(db, employee_id, organization_id)      # 404s outside the tenant
    if _normalize_country(employee.country_code or "") != HK:
        raise BadRequestException(f"employee #{employee_id} is not a Hong Kong employee")
    return employee


def _blocked(exc: HongKongCalculationBlockedError):
    return BadRequestException(f"Hong Kong: {exc.reason} ({exc.key})")


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


# ── Worker facts (HKWorkerProfile on the shared statutory profile) ──────

HK_PROFILE_COLUMNS = tuple(c.name for c in EmployeeStatutoryProfile.__table__.columns if c.name.startswith("hk_"))
# Never copied into a payroll trace (HK-022: privileged identity data).
_TRACE_EXCLUDED = ("hk_identity_token",)


IDENTITY_TOKEN_VERSION = "v2"


def identity_token(value) -> Optional[str]:
    """Pseudonymous, KEYED and versioned token for an HKID / passport number
    (gap-closure D-19). HMAC-SHA256 under HK_IDENTITY_TOKEN_KEY, or — when that
    is unset — under a key derived from PAYROLL_SECRET_KEY with a fixed domain
    label. The HKID value space is small enough that an unkeyed SHA-256 (the
    legacy "v1" token, a bare 64-hex digest) can be reversed by enumeration;
    legacy values stay readable and nothing looks a worker up by this token.
    The raw identifier is never returned."""
    import hashlib
    import hmac

    if value is None or str(value).strip() == "":
        return None
    from app.config import settings

    key = (settings.HK_IDENTITY_TOKEN_KEY or hmac.new(settings.PAYROLL_SECRET_KEY.encode(),
                                                      b"zoiko-hk-identity-token-v2", hashlib.sha256).hexdigest())
    digest = hmac.new(key.encode(), str(value).strip().upper().encode(), hashlib.sha256).hexdigest()
    return f"{IDENTITY_TOKEN_VERSION}:{digest}"


def identity_token_version(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return token.split(":", 1)[0] if ":" in token else "v1"


def _camel(column: str) -> str:
    head, *rest = column[len("hk_"):].split("_")
    return head + "".join(p.title() for p in rest)


def profile_facts(profile: EmployeeStatutoryProfile) -> dict:
    facts = {"profileId": profile.id, "profileEffectiveFrom": profile.effective_from.isoformat()}
    for col in HK_PROFILE_COLUMNS:
        if col in _TRACE_EXCLUDED:
            continue
        value = getattr(profile, col)
        if value is not None:
            facts[_camel(col)] = str(value) if isinstance(value, Decimal) else _iso(value)
    return facts


def worker_facts(db: Session, employee: PayrollEmployee, as_of: date) -> Optional[dict]:
    """The HK statutory-profile version in force on `as_of` (never today's
    by default) plus the employee's own employment dates."""
    from app.modules.payroll.service import resolve_employee_statutory_profile

    profile = resolve_employee_statutory_profile(db, employee.id, employee.organization_id, as_of)
    if profile is None or profile.country_code != HK:
        return None
    facts = profile_facts(profile)
    if getattr(employee, "date_of_birth", None):
        facts["dateOfBirth"] = employee.date_of_birth.isoformat()
    if getattr(employee, "date_of_joining", None):
        facts["dateOfJoining"] = employee.date_of_joining.isoformat()
    if not facts.get("terminationDate") and getattr(employee, "date_of_leaving", None):
        facts["terminationDate"] = employee.date_of_leaving.isoformat()
    return facts


# ── Verified hours (HK-016) ─────────────────────────────────────────────

def record_work_hours(db: Session, organization_id: int, employee_id: int, entries: list,
                      actor_id: Optional[int], reason: Optional[str] = None) -> list:
    """Append verified daily hours. A day that already has an active record
    is SUPERSEDED (never edited): the correction needs a reason, and the old
    row stays for replay."""
    _employee(db, employee_id, organization_id)
    created = []
    for entry in entries or []:
        day = date.fromisoformat(str(entry["date"]))
        hours = dec(entry["hours"])
        source = entry.get("source") or "VERIFIED_TIMESHEET"
        if hours < ZERO or hours > Decimal("24"):
            raise BadRequestException(f"hours on {day} must be between 0 and 24")
        if source not in HOURS_SOURCES:
            raise BadRequestException(f"hours source must be one of {', '.join(HOURS_SOURCES)}")
        current = (db.query(HongKongWorkHours)
                   .filter(HongKongWorkHours.organization_id == organization_id, HongKongWorkHours.employee_id == employee_id,
                           HongKongWorkHours.work_date == day, HongKongWorkHours.superseded_by_id.is_(None)).first())
        if current is not None and not reason:
            raise BadRequestException(f"{day} already has verified hours — a correction needs a reason")
        row = HongKongWorkHours(organization_id=organization_id, employee_id=employee_id, work_date=day, hours=hours,
                           source=source, evidence_ref=entry.get("evidenceRef"), recorded_by_id=actor_id)
        db.add(row)
        db.flush()
        if current is not None:
            current.superseded_by_id, current.supersede_reason = row.id, reason
        created.append(row)
        _audit(db, actor_id, "create", "payroll_hk_work_hours", row.id,
               old={"supersedes": current.id, "hours": str(current.hours)} if current else None,
               new={"employeeId": employee_id, "date": day.isoformat(), "hours": str(hours), "source": source},
               reason=reason, commit=False)
    db.commit()
    return created


def hours_map(db: Session, employee_id: int, start: date, end: date, organization_id: int = None) -> dict:
    q = db.query(HongKongWorkHours).filter(HongKongWorkHours.employee_id == employee_id, HongKongWorkHours.work_date >= start,
                                      HongKongWorkHours.work_date <= end, HongKongWorkHours.superseded_by_id.is_(None))
    if organization_id is not None:
        q = q.filter(HongKongWorkHours.organization_id == organization_id)
    return {r.work_date.isoformat(): str(r.hours) for r in q.all()}


def hours_input(db: Session, employee: PayrollEmployee, start: date, end: date, facts: dict) -> dict:
    days = hours_map(db, employee.id, start, end, employee.organization_id)
    if not days:
        return {"days": {}, "complete": False}
    first = max(start, date.fromisoformat(facts.get("employmentContinuityStart") or facts.get("dateOfJoining") or start.isoformat()))
    last = min(end, date.fromisoformat(facts["terminationDate"])) if facts.get("terminationDate") else end
    expected = {(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)}
    return {"days": days, "complete": expected <= set(days)}


# ── Payroll calculation inputs (called from service._compute_payslip_values) ─

def _trace_order_key(item: PayslipItem, run: PayrollRun):
    return (run.period_end or run.pay_date, run.id)


def prior_periods(db: Session, employee: PayrollEmployee, current_run: PayrollRun) -> list:
    """Earlier HK payslips of this employee, from their frozen traces — for
    the 60-day catch-up. A PENDING period already caught up by a later
    payslip's catch-up is marked so it is never booked twice."""
    rows = (db.query(PayslipItem, PayrollRun).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
            .filter(PayslipItem.employee_id == employee.id, PayrollRun.organization_id == employee.organization_id,
                    PayslipItem.hk_calculation_trace.isnot(None), PayrollRun.id != current_run.id).all())
    current_key = (current_run.period_end or current_run.pay_date, current_run.id)
    earlier = [(i, r) for i, r in rows if _trace_order_key(i, r) < current_key]
    caught = {c.get("payslipId") for i, _r in earlier for c in ((i.hk_calculation_trace or {}).get("mpf") or {}).get("catchUp") or []}
    out = []
    for item, _run in sorted(earlier, key=lambda p: _trace_order_key(*p)):
        trace = item.hk_calculation_trace or {}
        if trace.get("correction"):
            continue        # a linked-correction delta is not a wage period of its own (D-14)
        mpf = trace.get("mpf") or {}
        out.append({"payslipId": item.id, "periodStart": trace["period"]["start"], "periodEnd": trace["period"]["end"],
                    "payFrequency": trace["period"].get("payFrequency"),
                    "relevantIncome": (mpf.get("currentPeriod") or {}).get("relevantIncome", "0"),
                    "coverageStatus": (mpf.get("coverage") or {}).get("status"), "caughtUp": item.id in caught})
    return out


def calc_inputs(db: Session, run: PayrollRun, employee: PayrollEmployee, resolved_pack) -> dict:
    """PayrollContext kwargs for one HK payslip. The pack is the one the
    numbers came from (resolved_pack, pinned) — period segments are read from
    ITS rows, never from "the latest" configuration."""
    pack = resolved_pack[2] if resolved_pack is not None else None
    if pack is None:
        from app.modules.payroll.engine.tax_resolver import find_active_tax_pack

        pack = find_active_tax_pack(db, HK, as_of=run.pay_date)
    if pack is None:
        raise HongKongCalculationBlockedError("active statutory pack", "no Active Hong Kong rule pack for this payroll date")
    start = run.period_start or run.pay_date.replace(day=1)
    end = run.period_end or run.pay_date
    facts = worker_facts(db, employee, end) or {}
    facts["priorPeriods"] = prior_periods(db, employee, run)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.organization_id.is_(None)).all()
    return dict(hk_worker_facts=facts, hk_hours=hours_input(db, employee, start, end, facts),
                hk_rule_segments=rule_segments(rows, start, end))


# ── IR56G tax-clearance hold (§8) ───────────────────────────────────────

def _hold(db, organization_id, hold_id) -> HongKongTaxClearanceHold:
    row = db.query(HongKongTaxClearanceHold).filter(HongKongTaxClearanceHold.id == hold_id,
                                               HongKongTaxClearanceHold.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Hong Kong tax-clearance case", hold_id)
    return row


def _hold_view(hold: HongKongTaxClearanceHold) -> dict:
    return {"state": hold.state, "expectedDepartureDate": _iso(hold.expected_departure_date),
            "filingDeadline": _iso(hold.filing_deadline), "filedDate": _iso(hold.filed_date),
            "statutoryHoldExpiry": _iso(hold.statutory_hold_expiry), "releaseBasis": hold.release_basis,
            "releasedAmount": None if hold.released_amount is None else str(hold.released_amount)}


def _transition(db, hold, target, actor_id, reason=None):
    if not hk_tc.can_transition(hold.state, target):
        raise BadRequestException(f"IR56G case cannot move from {hold.state} to {target}")
    old = _hold_view(hold)
    hold.state = target
    _audit(db, actor_id, "status_change", "hk_tax_clearance_hold", hold.id, old=old, new=_hold_view(hold),
           reason=reason, commit=False)


def identify_departure(db: Session, organization_id: int, employee_id: int, expected_departure: date,
                       actor_id: Optional[int], identified_on: Optional[date] = None,
                       return_date: Optional[date] = None) -> HongKongTaxClearanceHold:
    employee = _employee(db, employee_id, organization_id)
    identified_on = identified_on or date.today()
    facts = worker_facts(db, employee, identified_on) or {}
    timing = reporting_timing(db, identified_on)
    need = hk_ird.tax_clearance_required(timing, expected_departure, return_date,
                                          bool(facts.get("frequentTravelExempt")),
                                          facts.get("likelyChargeable") is not False)
    if not need["required"]:
        raise BadRequestException(f"IR56G / tax clearance is not required: {need['reason']}")
    open_case = (db.query(HongKongTaxClearanceHold)
                 .filter(HongKongTaxClearanceHold.organization_id == organization_id, HongKongTaxClearanceHold.employee_id == employee_id,
                         HongKongTaxClearanceHold.state != "CASE_CLOSED").first())
    if open_case is not None:
        raise BadRequestException(f"an open IR56G case (#{open_case.id}, {open_case.state}) already exists — change it instead")
    hold = HongKongTaxClearanceHold(organization_id=organization_id, employee_id=employee_id,
                               expected_departure_date=expected_departure, identified_on=identified_on,
                               filing_deadline=hk_tc.filing_deadline(expected_departure, timing),
                               state=hk_tc.initial_state(identified_on, expected_departure, timing), prepared_by_id=actor_id)
    db.add(hold)
    try:
        db.flush()                       # uq_payroll_hk_tax_clearance_hold_open: one open IR56G case per employee
    except IntegrityError:
        db.rollback()
        raise _concurrent_conflict("An open IR56G case for this employee")
    case = HongKongIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type="IR56G",
                               year_of_assessment=year_of_assessment(expected_departure),
                               event_date=expected_departure, due_date=hold.filing_deadline, status="DUE",
                               prepared_by_id=actor_id)
    db.add(case)
    db.flush()
    hold.ird_case_id = case.id
    _audit(db, actor_id, "create", "hk_tax_clearance_hold", hold.id, new=_hold_view(hold),
           reason=f"Departure identified; IR56G due by {hold.filing_deadline}", commit=False)
    db.commit()
    return hold


def record_ir56g_filed(db: Session, organization_id: int, hold_id: int, filed_on: date, filing_reference: str,
                       actor_id: Optional[int]) -> HongKongTaxClearanceHold:
    """The operator filed IR56G through IRD's own channel: the hold becomes
    ACTIVE from the filing date (withhold all moneys payable)."""
    hold = _hold(db, organization_id, hold_id)
    if not filing_reference:
        raise BadRequestException("the IR56G filing reference is required")
    hold.filed_date = filed_on
    hold.statutory_hold_expiry = hk_tc.statutory_hold_expiry(filed_on, reporting_timing(db, filed_on))
    _transition(db, hold, "IR56G_FILED_HOLD_ACTIVE", actor_id, reason=f"IR56G filed {filed_on} ref {filing_reference}")
    case = db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.id == hold.ird_case_id).first()
    if case is not None and case.status not in hk_ird.FILED_STATES:
        case.status, case.filing_reference, case.filed_at = "FILED", filing_reference, datetime.utcnow()
    refresh_hold_lines(db, hold)
    db.commit()
    return hold


def _holding_payslips(db, hold) -> list:
    """Payslips whose money is withheld: every COMMITTED payslip of the
    employee paid on/after the filing date while the hold is in force. A
    Draft run's payslips are not yet payable (and may still be regenerated),
    so they only join the ledger once the run is committed."""
    q = (db.query(PayslipItem).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
         .filter(PayslipItem.employee_id == hold.employee_id, PayrollRun.organization_id == hold.organization_id,
                 PayrollRun.pay_date >= hold.filed_date, PayrollRun.status.in_(COMMITTED_RUN_STATUSES)))
    items = [i for i in q.all() if not (i.hk_calculation_trace or {}).get("correction")]
    # A linked correction is booked to its ORIGINAL wage period but its money is
    # released when the correction is approved (D-14): it is held when THAT date
    # falls on / after the IR56G filing.
    from app.modules.payroll.models import HongKongPayslipCorrection

    for corr in (db.query(HongKongPayslipCorrection)
                 .filter(HongKongPayslipCorrection.organization_id == hold.organization_id,
                         HongKongPayslipCorrection.employee_id == hold.employee_id,
                         HongKongPayslipCorrection.status == "APPROVED", HongKongPayslipCorrection.delta_payslip_id.isnot(None)).all()):
        if corr.approved_at is not None and corr.approved_at.date() >= hold.filed_date:
            delta = db.get(PayslipItem, corr.delta_payslip_id)
            if delta is not None and dec(delta.net_pay) > ZERO:
                items.append(delta)
    return items


def refresh_hold_lines(db: Session, hold: HongKongTaxClearanceHold) -> None:
    """Append a held-ledger line for every covered payslip not yet held.
    Lines are never deleted; a payslip's net pay stays owed (HK-013)."""
    if hold.state not in hk_tc.HOLDING_STATES or hold.filed_date is None:
        return
    held = {line.payslip_item_id for line in db.query(HongKongTaxClearanceHoldLine).filter(HongKongTaxClearanceHoldLine.hold_id == hold.id)}
    for item in _holding_payslips(db, hold):
        if item.id not in held:
            db.add(HongKongTaxClearanceHoldLine(hold_id=hold.id, organization_id=hold.organization_id,
                                           payslip_item_id=item.id, amount=dec(item.net_pay)))
    db.flush()


def held_total(db: Session, hold: HongKongTaxClearanceHold) -> Decimal:
    refresh_hold_lines(db, hold)          # the held ledger is always current
    return cents(sum((dec(l.amount) for l in db.query(HongKongTaxClearanceHoldLine)
                      .filter(HongKongTaxClearanceHoldLine.hold_id == hold.id, HongKongTaxClearanceHoldLine.status == "HELD")), ZERO))


def request_hold_release(db: Session, organization_id: int, hold_id: int, basis: str, reference: Optional[str],
                         evidence_ref: str, actor_id: Optional[int]) -> HongKongTaxClearanceHold:
    hold = _hold(db, organization_id, hold_id)
    if hold.state not in hk_tc.HOLDING_STATES:
        raise BadRequestException(f"no active hold to release (state {hold.state})")
    if basis not in hk_tc.RELEASE_BASES or not evidence_ref:
        raise BadRequestException(f"release needs a basis ({', '.join(hk_tc.RELEASE_BASES)}) and evidence")
    hold.release_basis, hold.release_reference, hold.release_evidence_ref = basis, reference, evidence_ref
    hold.release_requested_by_id = actor_id
    _audit(db, actor_id, "update", "hk_tax_clearance_hold", hold.id, new={"releaseRequested": basis, "evidence": evidence_ref})
    return hold


def approve_hold_release(db: Session, organization_id: int, hold_id: int, actor_id: Optional[int],
                         on: Optional[date] = None) -> HongKongTaxClearanceHold:
    """Four-eyes release: the approver must differ from the requester; the
    statute's conditions are re-checked here (never trusted from the request)."""
    hold = _hold(db, organization_id, hold_id)
    refresh_hold_lines(db, hold)
    refusal = hk_tc.release_refusal(hold.state, hold.release_basis, hold.release_reference, hold.release_evidence_ref,
                                    hold.filed_date, on or date.today(), hold.release_requested_by_id, actor_id,
                                    timing=reporting_timing(db, on or date.today()))
    if refusal:
        _audit(db, actor_id, "refused", "hk_tax_clearance_hold", hold.id, new={"attempted": "release"}, reason=refusal)
        raise BadRequestException(refusal)
    amount = held_total(db, hold)
    now = datetime.utcnow()
    for line in db.query(HongKongTaxClearanceHoldLine).filter(HongKongTaxClearanceHoldLine.hold_id == hold.id,
                                                          HongKongTaxClearanceHoldLine.status == "HELD"):
        line.status, line.released_at = "RELEASED", now
    hold.released_amount, hold.released_by_id, hold.released_at = amount, actor_id, now
    _transition(db, hold, "LETTER_OF_RELEASE_RECEIVED", actor_id,
                reason=f"released on {hold.release_basis} ({hold.release_reference or hold.release_evidence_ref})")
    db.commit()
    return hold


def change_departure(db: Session, organization_id: int, hold_id: int, reason: str, evidence_ref: str,
                     actor_id: Optional[int], new_departure: Optional[date] = None) -> HongKongTaxClearanceHold:
    """Cancelled / changed departure: evidence required; an ACTIVE hold keeps
    holding until a release is approved (never silently cleared)."""
    hold = _hold(db, organization_id, hold_id)
    if not reason or not evidence_ref:
        raise BadRequestException("a changed or cancelled departure needs a reason and evidence")
    hold.change_reason, hold.change_evidence_ref = reason, evidence_ref
    if new_departure:
        hold.expected_departure_date = new_departure
        hold.filing_deadline = hk_tc.filing_deadline(new_departure, reporting_timing(db, new_departure))
    _transition(db, hold, "DEPARTURE_CANCELLED_OR_CHANGED", actor_id, reason=reason)
    db.commit()
    return hold


def close_hold(db: Session, organization_id: int, hold_id: int, actor_id: Optional[int]) -> HongKongTaxClearanceHold:
    hold = _hold(db, organization_id, hold_id)
    if hold.state == "DEPARTURE_CANCELLED_OR_CHANGED" and hold.filed_date is not None and held_total(db, hold) > ZERO:
        raise BadRequestException("the case still holds money — approve a release before closing it")
    _transition(db, hold, "CASE_CLOSED", actor_id)
    db.commit()
    return hold


def serialize_hold(db: Session, hold: HongKongTaxClearanceHold) -> dict:
    lines = db.query(HongKongTaxClearanceHoldLine).filter(HongKongTaxClearanceHoldLine.hold_id == hold.id).all()
    return {"id": hold.id, "employeeId": hold.employee_id, "irdCaseId": hold.ird_case_id, **_hold_view(hold),
            "identifiedOn": _iso(hold.identified_on), "releaseReference": hold.release_reference,
            "releaseEvidenceRef": hold.release_evidence_ref, "releaseRequestedById": hold.release_requested_by_id,
            "releasedById": hold.released_by_id, "changeReason": hold.change_reason,
            "heldTotal": str(held_total(db, hold)),
            "lines": [{"payslipId": l.payslip_item_id, "amount": str(l.amount), "status": l.status} for l in lines],
            "treatment": "LEGAL_HOLD — held money remains owed to the employee; not a deduction"}


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """{payslip_id: (treatment, reason)} for the bank export. HELD while an
    IR56G hold is in force; FINAL_PAY_BLOCKED when the employee's final pay
    falls due while the IR56G filing is still unresolved (§8 IR56G_DUE)."""
    hk_items = [i for i in items if (i.country_code or "").upper() == HK]
    if not hk_items:
        return {}
    holds = {h.employee_id: h for h in db.query(HongKongTaxClearanceHold)
             .filter(HongKongTaxClearanceHold.organization_id == organization_id, HongKongTaxClearanceHold.state != "CASE_CLOSED")}

    correction_run = is_correction_run(run)
    paid_on = effective_payment_date(db, run)
    out = {}
    for item in hk_items:
        if correction_run and dec(item.net_pay) < ZERO:
            # An overpayment found by a correction is never a negative bank
            # payment; recovering it from the employee is a separate step (D-14).
            out[item.id] = ("RECOVERY_NOT_PAID", "negative correction delta — not paid; recovery is a separate step")
            continue
        hold = holds.get(item.employee_id)
        if hold is None:
            continue
        if correction_run and hold.state in hk_tc.FINAL_PAY_BLOCKING_STATES:
            out[item.id] = ("FINAL_PAY_BLOCKED", f"IR56G for case #{hold.id} is not yet filed")
            continue
        if hold.state in hk_tc.HOLDING_STATES and hold.filed_date and paid_on >= hold.filed_date:
            refresh_hold_lines(db, hold)
            out[item.id] = ("HELD", f"IR56G tax-clearance hold #{hold.id}")
        elif hold.state in hk_tc.FINAL_PAY_BLOCKING_STATES:
            employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == item.employee_id).first()
            leaving = getattr(employee, "date_of_leaving", None)
            if leaving and (run.period_start or run.pay_date) <= leaving <= (run.period_end or run.pay_date):
                out[item.id] = ("FINAL_PAY_BLOCKED", f"IR56G for case #{hold.id} is not yet filed")
    db.flush()
    return out


# ── IRD reporting (§7) ──────────────────────────────────────────────────

def _case(db, organization_id, case_id) -> HongKongIrdReportingCase:
    row = db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.id == case_id,
                                               HongKongIrdReportingCase.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Hong Kong IRD reporting case", case_id)
    return row


def _committed_hk_payslips(db, organization_id, start: date, end: date, employee_id: int = None) -> list:
    # country_code == "HK" is a REAL filter, not implied by the trace check: an
    # Organization can run several jurisdictions, and every caller of this
    # function groups payslips by employee across a whole period (the annual
    # return) or contribution month (the eMPF batch). Without the country filter
    # a same-month US or Singapore payslip for the same employee would be swept
    # into Hong Kong's IRD reconciliation and its eMPF remittance. The trace
    # check stays as a second, independent "was this really calculated under the
    # HK engine" condition.
    q = (db.query(PayslipItem, PayrollRun).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
         .filter(PayrollRun.organization_id == organization_id, PayrollRun.status.in_(COMMITTED_RUN_STATUSES),
                 PayslipItem.country_code == HK,
                 PayslipItem.hk_calculation_trace.isnot(None),
                 PayrollRun.pay_date >= start, PayrollRun.pay_date <= end))
    if employee_id is not None:
        q = q.filter(PayslipItem.employee_id == employee_id)
    return q.all()


def create_event_cases(db: Session, organization_id: int, employee_id: int, actor_id: Optional[int]) -> list:
    """IR56E / IR56F from the effective profile facts (IR56G is created by
    identify_departure). Idempotent per (form, event date) — also under
    concurrency: uq_payroll_hk_ird_event_case refuses the second insert, and the run is
    repeated once, finding the concurrent request's rows."""
    try:
        return _create_event_cases(db, organization_id, employee_id, actor_id)
    except IntegrityError:
        db.rollback()
        return _create_event_cases(db, organization_id, employee_id, actor_id)


def _create_event_cases(db: Session, organization_id: int, employee_id: int, actor_id: Optional[int]) -> list:
    employee = _employee(db, employee_id, organization_id)
    facts = worker_facts(db, employee, date.today()) or {}
    created = []

    def ensure(form, event):
        existing = (db.query(HongKongIrdReportingCase)
                    .filter(HongKongIrdReportingCase.organization_id == organization_id,
                            HongKongIrdReportingCase.employee_id == employee_id, HongKongIrdReportingCase.form_type == form,
                            HongKongIrdReportingCase.event_date == event).first())
        if existing is not None:
            return
        row = HongKongIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type=form,
year_of_assessment=year_of_assessment(event), event_date=event,
                                   due_date=hk_ird.due_date(form, reporting_timing(db, event), event_date=event),
                                   status="DUE", prepared_by_id=actor_id)
        db.add(row)
        db.flush()
        created.append(row)
        _audit(db, actor_id, "create", "hk_ird_reporting_case", row.id, new={"form": form, "event": event.isoformat()},
               commit=False)

    if employee.date_of_joining and facts.get("likelyChargeable"):
        ensure("IR56E", employee.date_of_joining)
    termination = facts.get("terminationDate")
    if termination and not facts.get("expectedDepartureDate"):
        ensure("IR56F", date.fromisoformat(termination))
    db.commit()
    return created


def generate_annual_return(db: Session, organization_id: int, ya: str, actor_id: Optional[int]) -> dict:
    """The year's BIR56A cover + per-employee IR56B cases (see
    _generate_annual_return). Two concurrent runs for the same year cannot both
    create an original case: uq_payroll_hk_ird_annual_ir56b / _bir56a refuse the
    second, which is rolled back and answered 409 (re-running is idempotent)."""
    try:
        return _generate_annual_return(db, organization_id, ya, actor_id)
    except IntegrityError:
        db.rollback()
        raise _concurrent_conflict(f"The {ya} annual return")


def _generate_annual_return(db: Session, organization_id: int, ya: str, actor_id: Optional[int]) -> dict:
    """BIR56A + one IR56B per reportable employee for the year of assessment
    ending 31 March — from COMMITTED payroll only, reconciled exactly (HK-011),
    with IR56F/IR56G duplicate suppression. An already-FILED IR56B is never
    regenerated (duplicate suppression / immutable evidence)."""
    start, end = year_of_assessment_bounds(ya)
    by_employee = {}
    for item, run in _committed_hk_payslips(db, organization_id, start, end):
        by_employee.setdefault(item.employee_id, []).append((item, run))
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    identifiers = (company.tax_identifiers or {}) if company else {}
    results, grand_total, payroll_total = [], ZERO, ZERO
    cover_filed = (db.query(HongKongIrdReportingCase.id)
                   .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.form_type == "BIR56A",
                           HongKongIrdReportingCase.year_of_assessment == ya,
                           HongKongIrdReportingCase.status.in_(hk_ird.FILED_STATES)).first() is not None)
    for employee_id, pairs in sorted(by_employee.items()):
        employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == employee_id).first()
        fields, gross = {}, ZERO
        for item, _run in pairs:
            # Paid gross: the unpaid-day deduction is not remuneration.
            gross += dec(item.gross_pay) - dec(getattr(item, "attendance_deduction", None))
            for field, amount in ((item.hk_calculation_trace or {}).get("ird") or {}).get("reportable", {}).items():
                fields[field] = fields.get(field, ZERO) + dec(amount)
        reported = sum(fields.values(), ZERO)
        payroll_total += gross
        period = hk_ird.employee_period_in_year(ya, employee.date_of_joining or start, employee.date_of_leaving)
        # An IR56F / IR56G reports income from the start of the year (or of
        # the employment) to the cessation / departure (its event date).
        prior = [{"id": c.id, "formType": c.form_type, "status": c.status,
                  "incomePeriodStart": _iso(c.income_period_start or period[0]),
                  "incomePeriodEnd": _iso(c.income_period_end or c.event_date)}
                 for c in db.query(HongKongIrdReportingCase).filter(
                     HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.employee_id == employee_id,
                     HongKongIrdReportingCase.year_of_assessment == ya,
                     HongKongIrdReportingCase.form_type.in_(("IR56F", "IR56G")))]
        decision = hk_ird.ir56b_suppression(ya, period, prior)
        existing = (db.query(HongKongIrdReportingCase)
                    .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.employee_id == employee_id,
                            HongKongIrdReportingCase.form_type == "IR56B", HongKongIrdReportingCase.year_of_assessment == ya,
                            HongKongIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
                    .order_by(HongKongIrdReportingCase.id.desc()).first())
        if existing is not None and existing.status in hk_ird.FILED_STATES + ("SUPPRESSED",):
            results.append({"employeeId": employee_id, "caseId": existing.id, "status": existing.status,
                            "message": "already filed — never regenerated (amend instead)"})
            grand_total += reported if existing.status != "SUPPRESSED" else ZERO
            continue
        if existing is not None and existing.status == "REJECTED":
            # The rejected return keeps its filed evidence until an operator
            # explicitly chooses "Prepare again" (an audited transition).
            results.append({"employeeId": employee_id, "caseId": existing.id, "status": existing.status,
                            "message": "rejected by the IRD — choose Prepare again before regenerating"})
            grand_total += reported
            continue
        errors = []
        cf = (employee.compliance_fields or {}) if employee else {}
        if not (cf.get("hkid") or cf.get("passport_number")):
            errors.append("HKID or passport number is required on IR56B")
        if fields.get("UNMAPPED_REQUIRES_CLASSIFICATION") or fields.get("UNMAPPED"):
            errors.append("some remuneration has no certified IR56B field (UNMAPPED) — classify before filing")
        recon = hk_ird.reconcile(reported, gross - _excluded_ird(pairs))
        if not recon["reconciled"]:
            errors.append(f"reported {recon['reported']} does not reconcile to committed payroll {recon['payroll']}")
        payload = {"schemaVersion": hk_ird.INTERNAL_SCHEMA_VERSION, "form": "IR56B", "yearOfAssessment": ya,
                   "employeeId": employee_id, "employmentPeriod": [period[0].isoformat(), period[1].isoformat()],
                   "fields": {k: str(cents(v)) for k, v in sorted(fields.items())}, "total": str(cents(reported))}
        row = existing or HongKongIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type="IR56B",
                                              year_of_assessment=ya, prepared_by_id=actor_id)
        if existing is None:
            # An IR56B first prepared after the BIR56A cover was filed is an
            # ADDITIONAL return (submitted under the IRD's additional procedure).
            row.amendment_type = "ADDITIONAL" if cover_filed else "ORIGINAL"
            db.add(row)
        row.income_period_start, row.income_period_end = period
        row.due_date = hk_ird.due_date("IR56B", reporting_timing(db, end), ya=ya)
        row.schema_version, row.schema_hash = hk_ird.INTERNAL_SCHEMA_VERSION, None
        row.payload, row.payload_hash = payload, canonical_hash(payload)
        row.source_payroll_hash = canonical_hash([(i.id, str(i.gross_pay), canonical_hash(i.hk_calculation_trace)) for i, _r in pairs])
        row.reported_income = payload["fields"]
        if decision["action"] == "SUPPRESS":
            row.status, row.suppression_reason, row.validation_errors = "SUPPRESSED", decision["message"], []
        else:
            if decision["action"] == "RESOLVE":
                errors.append(decision["message"])
            row.status, row.validation_errors = "PREPARED", errors
            grand_total += reported
        db.flush()
        results.append({"employeeId": employee_id, "caseId": row.id, "status": row.status,
                        "message": decision["message"], "validationErrors": row.validation_errors})
    cover = (db.query(HongKongIrdReportingCase)
             .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.form_type == "BIR56A",
                     HongKongIrdReportingCase.year_of_assessment == ya,
                     HongKongIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
             .order_by(HongKongIrdReportingCase.id.desc()).first())
    if cover is None or cover.status not in hk_ird.FILED_STATES + ("REJECTED",):
        cover = cover or HongKongIrdReportingCase(organization_id=organization_id, form_type="BIR56A", year_of_assessment=ya,
                                             prepared_by_id=actor_id)
        if cover.id is None:
            db.add(cover)
        payload = {"schemaVersion": hk_ird.INTERNAL_SCHEMA_VERSION, "form": "BIR56A", "yearOfAssessment": ya,
                   "employerFileNumber": identifiers.get("ird_employer_file_number"),
                   "employeeCount": sum(1 for r in results if r["status"] != "SUPPRESSED"),
                   "totalRemuneration": str(cents(grand_total))}
        cover.payload, cover.payload_hash = payload, canonical_hash(payload)
        cover.due_date = hk_ird.due_date("BIR56A", reporting_timing(db, end), ya=ya)
        cover.status = "PREPARED"
        cover.validation_errors = [] if identifiers.get("ird_employer_file_number") else [
            "the IRD employer's file number is not recorded on the employer registration"]
    db.flush()
    _audit(db, actor_id, "create", "hk_ird_annual_return", cover.id,
           new={"yearOfAssessment": ya, "employees": len(results), "total": str(cents(grand_total))}, commit=False)
    db.commit()
    return {"yearOfAssessment": ya, "bir56aCaseId": cover.id, "employees": results,
            "reportedTotal": str(cents(grand_total)), "committedPayrollGross": str(cents(payroll_total)),
            "schemaStatus": hk_ird.SCHEMA_STATUS}


def _excluded_ird(pairs) -> Decimal:
    """Gross amounts the classification EXCLUDES from IRD reporting (so the
    reconciliation compares like with like)."""
    total = ZERO
    for item, _run in pairs:
        ird = (((item.hk_calculation_trace or {}).get("classification") or {}).get("IRD") or {})
        total += dec(ird.get("excluded")) + dec(ird.get("review"))
    return total


SUBMISSION_MODES = ("ONLINE_MODE", "MIXED_MODE", "INTERNAL_PREPARATION_ONLY")
AMENDMENT_TYPES = ("ORIGINAL", "ADDITIONAL", "REPLACEMENT", "SUPPLEMENTARY")


def _record_submission(db, case: HongKongIrdReportingCase, submission: Optional[dict], actor_id) -> None:
    """The external-submission record a FILED transition requires. Zoiko never
    transmits to the IRD: this records HOW the employer submitted, from its
    evidence. ONLINE_MODE / MIXED_MODE submit Zoiko's DATA FILE, which the IRD
    accepts only from approved software — refused unless the platform's IRD
    software approval is received, unexpired and covers the form. Internal
    validation alone never satisfies that (it is an IRD decision)."""

    sub = submission or {}
    mode = sub.get("submissionMode")
    if mode not in SUBMISSION_MODES:
        raise BadRequestException("the submission mode is required: " + " / ".join(SUBMISSION_MODES))
    if not (sub.get("authorizedSigner") or "").strip():
        raise BadRequestException("the authorized signer (who signed the return for the employer) is required")
    if mode == "ONLINE_MODE" and not sub.get("transactionReference"):
        raise BadRequestException("ONLINE_MODE needs the eTAX transaction reference")
    if mode == "MIXED_MODE" and not sub.get("controlListReference"):
        raise BadRequestException("MIXED_MODE needs the signed control list reference")
    submitted_on = sub.get("submittedOn") or date.today()
    if isinstance(submitted_on, str):
        submitted_on = date.fromisoformat(submitted_on)
    if submitted_on > date.today():
        raise BadRequestException("the submission date cannot be in the future")
    if mode != "INTERNAL_PREPARATION_ONLY":
        refusal = software_approval_refusal(db, case.form_type, submitted_on)
        if refusal:
            raise BadRequestException(refusal)
    case.submission_mode, case.authorized_signer = mode, sub["authorizedSigner"].strip()
    case.transaction_reference, case.control_list_reference = sub.get("transactionReference"), sub.get("controlListReference")
    case.submitted_on, case.uploaded_by_id = submitted_on, actor_id


def transition_ird_case(db: Session, organization_id: int, case_id: int, target: str, actor_id: Optional[int],
                        filing_reference: str = None, receipt_reference: str = None,
                        submission: Optional[dict] = None) -> HongKongIrdReportingCase:
    case = _case(db, organization_id, case_id)
    if target not in hk_ird.TRANSITIONS.get(case.status, ()):
        raise BadRequestException(f"IRD case #{case.id} cannot move from {case.status} to {target}")
    if target == "AMENDED":
        raise BadRequestException("use the amendment action — it creates a linked replacement case")
    if target == "VALIDATED" and case.validation_errors:
        raise BadRequestException("the case has validation errors: " + "; ".join(case.validation_errors))
    if target == "FILED":
        if case.validation_errors:
            raise BadRequestException("a case with validation errors cannot be filed")
        if not filing_reference:
            raise BadRequestException("the IRD filing reference (from the IRD's own filing channel) is required")
        service.require_four_eyes(case.prepared_by_id, actor_id, "Filing an IRD return / notification")
        _record_submission(db, case, submission, actor_id)
        case.filing_reference, case.filed_at, case.approved_by_id = filing_reference, datetime.utcnow(), actor_id
        if case.amends_case_id:
            # The replacement is now on file: the original it replaces is
            # superseded (kept with its filed evidence), never before this.
            original = _case(db, organization_id, case.amends_case_id)
            if original.status in hk_ird.FILED_STATES:
                previous = original.status
                original.status = "AMENDED"
                _audit(db, actor_id, "status_change", "hk_ird_reporting_case", original.id,
                       old={"status": previous}, new={"status": "AMENDED", "supersededBy": case.id,
                                                      "filingReference": original.filing_reference},
                       reason=f"replaced by case #{case.id} (filing reference {filing_reference})", commit=False)
    if target in ("ACCEPTED", "ACKNOWLEDGED"):
        if not receipt_reference:
            raise BadRequestException("the IRD acknowledgement / receipt reference is required")
        case.receipt_reference, case.accepted_at = receipt_reference, datetime.utcnow()
    if target == "REJECTED":
        if not receipt_reference:
            raise BadRequestException("the IRD rejection reference / reason is required")
        # The filed evidence (payload, hash, filing reference) is kept; the case
        # returns to PREPARED for correction and re-filing.
        case.validation_errors = list(case.validation_errors or []) + [f"rejected by the IRD: {receipt_reference}"]
        case.receipt_reference = receipt_reference
    if target == "PREPARED" and case.status == "REJECTED":
        case.validation_errors = [e for e in (case.validation_errors or []) if not e.startswith("rejected by the IRD")]
    old = case.status
    case.status = target
    new = {"status": target, "filingReference": case.filing_reference, "receipt": case.receipt_reference}
    if target == "FILED":
        new["submission"] = {"mode": case.submission_mode, "authorizedSigner": case.authorized_signer,
                             "transactionReference": case.transaction_reference,
                             "controlListReference": case.control_list_reference, "submittedOn": _iso(case.submitted_on)}
    if target == "REJECTED":
        # Immutable evidence of exactly what was filed and rejected: the case
        # row is later re-prepared (new payload) and re-filed (new reference).
        new["filedEvidence"] = {"filingReference": case.filing_reference, "filedAt": _iso(case.filed_at),
                                "payloadHash": case.payload_hash, "sourcePayrollHash": case.source_payroll_hash,
                                "generatedReportId": case.generated_report_id, "payload": copy.deepcopy(case.payload)}
    _audit(db, actor_id, "status_change", "hk_ird_reporting_case", case.id, old={"status": old}, new=new)
    return case


def ird_case_history(db: Session, organization_id: int, case_id: int) -> list:
    """The case's lifecycle from the immutable audit trail (filings,
    rejections with the filed evidence, re-preparations, re-filings)."""
    from app.modules.payroll.models import TaxConfigurationAudit

    case = _case(db, organization_id, case_id)                  # 404 outside the tenant
    rows = (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "hk_ird_reporting_case", TaxConfigurationAudit.entity_id == case.id)
            .order_by(TaxConfigurationAudit.id).all())
    out = []
    for r in rows:
        new = r.new_value or {}
        evidence = new.get("filedEvidence")
        out.append({"at": _iso(r.created_at), "actorId": r.actor_id, "action": r.action,
                    "from": (r.old_value or {}).get("status"), "to": new.get("status"),
                    "filingReference": new.get("filingReference"), "reference": new.get("receipt"),
                    "reason": r.reason,
                    "filedEvidence": None if not evidence else {k: v for k, v in evidence.items() if k != "payload"}})
    return out


# A replacement case that is still being prepared: neither filed nor withdrawn.
_REPLACEMENT_CLOSED_STATES = hk_ird.FILED_STATES + ("AMENDED", "CANCELLED", "SUPPRESSED")


def open_replacement(db: Session, case: HongKongIrdReportingCase) -> Optional[HongKongIrdReportingCase]:
    """The unfiled replacement in progress for a filed case, if any (at most one)."""
    return (db.query(HongKongIrdReportingCase)
            .filter(HongKongIrdReportingCase.organization_id == case.organization_id,
                    HongKongIrdReportingCase.amends_case_id == case.id,
                    HongKongIrdReportingCase.status.notin_(_REPLACEMENT_CLOSED_STATES))
            .order_by(HongKongIrdReportingCase.id.desc()).first())


def amend_ird_case(db: Session, organization_id: int, case_id: int, reason: str, actor_id: Optional[int],
                   commit: bool = True, amendment_type: str = "REPLACEMENT") -> HongKongIrdReportingCase:
    """A NEW linked case replaces a filed one; the accepted evidence (payload,
    hash, receipt) of the original is never overwritten.

    amendment_type: REPLACEMENT (the original is superseded). SUPPLEMENTARY
    (additional income only, the original stays in force) is refused — the
    IRD's supplementary-return specification is not archived (G2) and Zoiko
    will not invent its layout. ADDITIONAL is not an amendment: it is set
    automatically on an IR56B first prepared after the year's BIR56A was
    filed.

    Lifecycle (internal case states, not an IRD-defined process): the filed
    original stays in force — shown AMENDMENT_REQUIRED — while its replacement
    is prepared; it becomes AMENDED only when the replacement is FILED
    (transition_ird_case). Cancelling the replacement leaves the original
    filed and amendable again. Asking to amend a case whose replacement is
    still open returns that replacement (no second one)."""
    original = _case(db, organization_id, case_id)
    if amendment_type not in ("REPLACEMENT", "SUPPLEMENTARY"):
        raise BadRequestException("an amendment is REPLACEMENT or SUPPLEMENTARY (ADDITIONAL is set automatically "
                                  "on an IR56B prepared after the BIR56A was filed)")
    if amendment_type == "SUPPLEMENTARY":
        raise BadRequestException("SUPPLEMENTARY returns are not supported: the IRD supplementary-return "
                                  "specification is not archived (gate G2) — file a REPLACEMENT instead")
    if original.status not in hk_ird.FILED_STATES:
        raise BadRequestException("only a filed / accepted case can be amended")
    if not reason:
        raise BadRequestException("an amendment needs a reason")
    pending = open_replacement(db, original)
    if pending is not None:
        return pending
    amendment = HongKongIrdReportingCase(
        organization_id=organization_id, employee_id=original.employee_id, form_type=original.form_type,
        year_of_assessment=original.year_of_assessment, event_date=original.event_date, due_date=original.due_date,
        income_period_start=original.income_period_start, income_period_end=original.income_period_end,
        status="PREPARED", schema_version=original.schema_version, payload=copy.deepcopy(original.payload),
        payload_hash=original.payload_hash, reported_income=copy.deepcopy(original.reported_income),
        validation_errors=[], amends_case_id=original.id, prepared_by_id=actor_id, amendment_type=amendment_type)
    db.add(amendment)
    try:
        db.flush()                       # uq_payroll_hk_ird_open_replacement: one open replacement per case
    except IntegrityError:
        db.rollback()
        if not commit:
            raise _concurrent_conflict(f"A replacement for IRD case #{case_id}")
        pending = open_replacement(db, _case(db, organization_id, case_id))
        if pending is None:
            raise _concurrent_conflict(f"A replacement for IRD case #{case_id}")
        return pending
    _audit(db, actor_id, "create", "hk_ird_reporting_case", amendment.id,
           new={"amends": original.id, "form": original.form_type, "amendmentType": amendment_type}, reason=reason,
           commit=False)
    if commit:
        db.commit()
    return amendment


def xml_lifecycle_state(db: Session, case: HongKongIrdReportingCase) -> str:
    """The IRD data-file lifecycle view of a case (DRAFT / VALIDATED /
    READY_FOR_EXTERNAL_SUBMISSION / SUBMITTED_EXTERNALLY / ACKNOWLEDGED /
    REJECTED / AMENDMENT_REQUIRED / SUPERSEDED). READY_FOR_EXTERNAL_SUBMISSION
    is shown ONLY when the IRD software approval covers the form — internal
    validation alone never makes a data file submittable. A filed case with an
    unfiled replacement in progress is AMENDMENT_REQUIRED."""

    status = case.status
    if status in ("DUE", "PREPARED"):
        return "DRAFT"
    if status == "VALIDATED":
        return ("READY_FOR_EXTERNAL_SUBMISSION" if software_approval_refusal(db, case.form_type, date.today()) is None
                else "VALIDATED")
    if status in ("FILED", "ACCEPTED", "ACKNOWLEDGED"):
        pending = (db.query(HongKongIrdReportingCase.id)
                   .filter(HongKongIrdReportingCase.amends_case_id == case.id,
                           HongKongIrdReportingCase.status.notin_(hk_ird.FILED_STATES + ("CANCELLED", "AMENDED"))).first())
        if pending:
            return "AMENDMENT_REQUIRED"
        return "SUBMITTED_EXTERNALLY" if status == "FILED" else "ACKNOWLEDGED"
    if status == "REJECTED":
        return "REJECTED"
    if status == "AMENDED":
        return "SUPERSEDED"
    return status                                               # SUPPRESSED / CANCELLED: not a data file


def serialize_ird_case(case: HongKongIrdReportingCase) -> dict:
    from sqlalchemy.orm import object_session

    db = object_session(case)
    return {"xmlLifecycleState": xml_lifecycle_state(db, case) if db is not None else None,
            "amendmentType": case.amendment_type, "submissionMode": case.submission_mode,
            "authorizedSigner": case.authorized_signer, "transactionReference": case.transaction_reference,
            "controlListReference": case.control_list_reference, "submittedOn": _iso(case.submitted_on),
            "uploadedById": case.uploaded_by_id,
            "id": case.id, "employeeId": case.employee_id, "formType": case.form_type,
            "yearOfAssessment": case.year_of_assessment, "eventDate": _iso(case.event_date), "dueDate": _iso(case.due_date),
            "status": case.status, "schemaVersion": case.schema_version, "schemaStatus": hk_ird.SCHEMA_STATUS,
            "payloadHash": case.payload_hash, "reportedIncome": case.reported_income,
            "validationErrors": case.validation_errors or [], "filingReference": case.filing_reference,
            "receiptReference": case.receipt_reference, "amendsCaseId": case.amends_case_id,
            "suppressionReason": case.suppression_reason, "preparedById": case.prepared_by_id,
            "approvedById": case.approved_by_id, "generatedReportId": case.generated_report_id,
            "employeeCopyDeliveredAt": _iso(case.employee_copy_delivered_at)}


EMPLOYEE_COPY_FORMS = ("IR56B", "IR56E", "IR56F", "IR56G")


def record_employee_copy_delivered(db: Session, organization_id: int, case_id: int, evidence_ref: str,
                                   actor_id: Optional[int]) -> HongKongIrdReportingCase:
    """IRD: the employer gives the employee a copy of the completed IR56B / E / F
    / G (ZP-HK-ENG-001 §7). Records WHEN and on what evidence — once; a case is
    never re-stamped (the first delivery is the evidence)."""
    case = _case(db, organization_id, case_id)
    if case.form_type not in EMPLOYEE_COPY_FORMS:
        raise BadRequestException(f"{case.form_type} has no employee copy")
    if case.status in ("DUE", "SUPPRESSED", "CANCELLED"):
        raise BadRequestException(f"case #{case.id} is {case.status} — there is no completed form to give the employee")
    if not evidence_ref:
        raise BadRequestException("record how the copy was delivered (evidence reference)")
    if case.employee_copy_delivered_at is not None:
        raise BadRequestException(f"the employee copy was already recorded as delivered on "
                                  f"{case.employee_copy_delivered_at:%Y-%m-%d}")
    case.employee_copy_delivered_at = datetime.utcnow()
    _audit(db, actor_id, "update", "hk_ird_reporting_case", case.id,
           new={"employeeCopyDelivered": case.employee_copy_delivered_at.isoformat(), "evidence": evidence_ref})
    return case


# ── Pack resolution for non-payroll calculations ────────────────────────

def pack_inputs(db: Session, on: date) -> tuple:
    """(rate_map, slabs, pack) of the Active HK pack in force on `on`."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    rates, slabs, pack = resolve_tax_configuration(db, HK, payroll_date=on)
    if pack is None:
        raise BadRequestException(f"no Active Hong Kong rule pack is in force on {on}")
    return {r.component_key: r for r in rates}, slabs, pack


def reporting_timing(db: Session, on: date) -> dict:
    """The IRD reporting-timing rows of the pack in force on `on` — every IRD
    due date and every IR56G hold date is computed from these, so a deadline
    can never come from a literal in the code (fail-closed)."""
    rate_map, _slabs, _pack = pack_inputs(db, on)
    try:
        return resolve_timing(rate_map)
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)


# ── Continuous contract / average wage / entitlements (§9, §10) ─────────

def continuous_contract(db: Session, organization_id: int, employee_id: int, as_of: date) -> dict:
    employee = _employee(db, employee_id, organization_id)
    facts = worker_facts(db, employee, as_of)
    if facts is None:
        raise BadRequestException("no Hong Kong statutory profile is in force on that date")
    start = date.fromisoformat(facts.get("employmentContinuityStart") or facts["dateOfJoining"])
    rate_map, _slabs, pack = pack_inputs(db, as_of)
    try:
        params = hk_cc.parameters(rate_map)
        result = hk_cc.resolve(start, as_of, hours_map(db, employee_id, start, as_of, organization_id), params,
                               facts.get("contractualWeeklyHours"))
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    result["packId"] = pack.pack_id
    return result


def _average_wage_rows(db, organization_id, employee_id, start: date, end: date) -> list:
    rows = []
    for item, run in _committed_hk_payslips(db, organization_id, start - timedelta(days=31), end + timedelta(days=31), employee_id):
        trace = item.hk_calculation_trace or {}
        eo = (trace.get("classification") or {}).get("EO_WAGES") or {}
        review = dec(eo.get("review"))
        ps, pe = date.fromisoformat(trace["period"]["start"]), date.fromisoformat(trace["period"]["end"])
        if pe < start or ps > end:
            continue
        if review != ZERO:
            raise BadRequestException(
                f"payslip #{item.id} carries {review} whose Employment Ordinance wage treatment is not certified — "
                "the average wage cannot be computed until it is classified")
        overtime = sum((dec(l["amount"]) for l in eo.get("lines") or []
                        if l["component"] == "overtime" and l["treatment"] == "INCLUDED"), ZERO)
        rows.append({"payslipId": item.id, "periodStart": ps.isoformat(), "periodEnd": pe.isoformat(),
                     "eoWages": str(eo.get("included", "0")), "overtime": str(overtime),
                     "revision": canonical_hash(trace),
                     "correctsPayslipId": (trace.get("correction") or {}).get("originalPayslipId")})
    # A linked-correction delta is folded into the row of the payslip it
    # corrects (same wage period) — never counted as a period of its own (D-14).
    by_id = {r["payslipId"]: r for r in rows}
    folded = []
    for r in rows:
        target = by_id.get(r["correctsPayslipId"]) if r["correctsPayslipId"] else None
        if r["correctsPayslipId"] is None:
            folded.append(r)
        elif target is not None:
            target["eoWages"] = str(dec(target["eoWages"]) + dec(r["eoWages"]))
            target["overtime"] = str(dec(target["overtime"]) + dec(r["overtime"]))
            target["revision"] = canonical_hash([target["revision"], r["revision"]])
    for r in folded:
        r.pop("correctsPayslipId", None)
    return folded


def calculate_average_wage(db: Session, organization_id: int, employee_id: int, benefit_type: str,
                           reference_date: date, disregarded: list, actor_id: Optional[int],
                           overtime_constant: bool = False) -> HongKongAverageWageSnapshot:
    employee = _employee(db, employee_id, organization_id)
    facts = worker_facts(db, employee, reference_date) or {}
    start = date.fromisoformat(facts.get("employmentContinuityStart") or facts.get("dateOfJoining")
                               or employee.date_of_joining.isoformat())
    rate_map, _slabs, pack = pack_inputs(db, reference_date)
    try:
        params = hk_average_wage.parameters(rate_map)
        window = hk_average_wage.lookback_window(
            reference_date, start, int(params["values"]["eo_average_wage_months"]))
        rows = _average_wage_rows(db, organization_id, employee_id, window[0], window[1])
        result = hk_average_wage.calculate(reference_date, start, rows, disregarded, benefit_type,
                                           overtime_constant, rate_map=rate_map)
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    snap = HongKongAverageWageSnapshot(
        organization_id=organization_id, employee_id=employee_id, benefit_type=benefit_type,
        reference_date=reference_date, lookback_start=date.fromisoformat(result["lookbackStart"]),
        lookback_end=date.fromisoformat(result["lookbackEnd"]), included_rows=result["includedRows"],
        excluded_periods=result["excludedPeriods"], excluded_amounts={"total": result["excludedAmount"]},
        total_wages=dec(result["wagesUsed"]), total_days=result["includedDays"],
        average_daily_wage=dec(result["averageDailyWage"]), average_monthly_wage=dec(result["averageMonthlyWage"]),
        four_fifths_daily=dec(result["fourFifthsDailyWage"]), result=result,
        source_revision_hash=result["sourceRevisionHash"], evidence_hash=result["evidenceHash"], created_by_id=actor_id)
    db.add(snap)
    db.flush()
    _audit(db, actor_id, "create", "hk_average_wage_snapshot", snap.id,
           new={"benefit": benefit_type, "referenceDate": reference_date.isoformat(),
                "averageDailyWage": result["averageDailyWage"], "evidenceHash": result["evidenceHash"]}, commit=False)
    db.commit()
    return snap


def request_average_wage_override(db, organization_id, snapshot_id, value, reason, evidence_ref, actor_id):
    snap = _snapshot(db, organization_id, snapshot_id)
    if not reason or not evidence_ref:
        raise BadRequestException("an average-wage override needs a reason and evidence (HK-014)")
    snap.override_average_daily_wage, snap.override_reason = dec(value), reason
    snap.override_evidence_ref, snap.override_requested_by_id = evidence_ref, actor_id
    snap.override_approved_by_id = None
    _audit(db, actor_id, "update", "hk_average_wage_snapshot", snap.id,
           new={"overrideRequested": str(value), "evidence": evidence_ref}, reason=reason)
    return snap


def approve_average_wage_override(db, organization_id, snapshot_id, actor_id):
    snap = _snapshot(db, organization_id, snapshot_id)
    if snap.override_average_daily_wage is None:
        raise BadRequestException("no override has been requested")
    service.require_four_eyes(snap.override_requested_by_id, actor_id, "An average-wage override")
    snap.override_approved_by_id, snap.status = actor_id, "OVERRIDDEN"
    _audit(db, actor_id, "status_change", "hk_average_wage_snapshot", snap.id,
           new={"status": "OVERRIDDEN", "calculated": str(snap.average_daily_wage),
                "override": str(snap.override_average_daily_wage)})
    return snap


def _snapshot(db, organization_id, snapshot_id) -> HongKongAverageWageSnapshot:
    snap = db.query(HongKongAverageWageSnapshot).filter(HongKongAverageWageSnapshot.id == snapshot_id,
                                                   HongKongAverageWageSnapshot.organization_id == organization_id).first()
    if snap is None:
        raise NotFoundException("Hong Kong average-wage snapshot", snapshot_id)
    return snap


def effective_average(snap: HongKongAverageWageSnapshot) -> dict:
    """The snapshot result, with an APPROVED override applied (and shown)."""
    result = dict(snap.result)
    if snap.status == "OVERRIDDEN" and snap.override_approved_by_id:
        result["calculatedAverageDailyWage"] = result["averageDailyWage"]
        result["averageDailyWage"] = str(snap.override_average_daily_wage)
        result["override"] = {"reason": snap.override_reason, "evidence": snap.override_evidence_ref}
    return result


def calculate_entitlement(db: Session, organization_id: int, employee_id: int, benefit: str, data: dict) -> dict:
    """Holiday pay / annual leave pay / sickness allowance / maternity /
    paternity pay from ONE average-wage snapshot (§9)."""
    snap = _snapshot(db, organization_id, int(data["averageWageSnapshotId"]))
    if snap.employee_id != employee_id:
        raise BadRequestException("the average-wage snapshot belongs to a different employee")
    on = date.fromisoformat(str(data.get("date") or snap.reference_date))
    average = effective_average(snap)
    rate_map, slabs, pack = pack_inputs(db, on)
    cc = continuous_contract(db, organization_id, employee_id, on)
    try:
        if benefit == "SICKNESS_ALLOWANCE":
            accrued = hk_entitlements.paid_sickness_days_accrued(
                rate_map, date.fromisoformat(cc["continuousSince"]) if cc.get("continuousSince") else on, on)
            available = dec(data.get("availablePaidSicknessDays", accrued["accrued"]))
            out = hk_entitlements.sickness_allowance(rate_map, cc, average, int(data["sicknessDays"]),
                                                     int(data.get("consecutiveDays", data["sicknessDays"])),
                                                     bool(data.get("medicallyCertified")), available,
                                                     bool(data.get("pregnancyRelated")))
            out["accrual"] = accrued
        elif benefit == "HOLIDAY_PAY":
            out = hk_entitlements.holiday_pay(rate_map, cc, average, on)
            out["calendar"] = hk_entitlements.statutory_holidays(slabs, on.year)
        elif benefit == "ANNUAL_LEAVE_PAY":
            out = hk_entitlements.annual_leave_pay(average, dec(data["days"]))
        elif benefit == "MATERNITY_LEAVE_PAY":
            out = hk_entitlements.maternity_leave_pay(rate_map, cc, average, on, bool(data.get("noticeGiven")))
        elif benefit == "PATERNITY_LEAVE_PAY":
            out = hk_entitlements.paternity_leave_pay(rate_map, cc, average, on, int(data["days"]),
                                                      bool(data.get("documentProvided")))
        else:
            raise BadRequestException(f"unknown entitlement {benefit!r}")
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    return {**out, "averageWageSnapshotId": snap.id, "continuousContract": cc["status"], "packId": pack.pack_id}


# ── Termination (§11) ───────────────────────────────────────────────────

def calculate_termination(db: Session, organization_id: int, employee_id: int, data: dict,
                          actor_id: Optional[int]) -> HongKongTerminationResult:
    employee = _employee(db, employee_id, organization_id)
    termination = date.fromisoformat(str(data["terminationDate"]))
    facts = worker_facts(db, employee, termination)
    if facts is None:
        raise BadRequestException("no Hong Kong statutory profile is in force on the termination date")
    start = date.fromisoformat(facts.get("employmentContinuityStart") or facts["dateOfJoining"])
    rate_map, _slabs, pack = pack_inputs(db, termination)
    cc = continuous_contract(db, organization_id, employee_id, termination)
    active_hold = db.query(HongKongTaxClearanceHold).filter(
        HongKongTaxClearanceHold.organization_id == organization_id, HongKongTaxClearanceHold.employee_id == employee_id,
        HongKongTaxClearanceHold.state.in_(hk_tc.HOLDING_STATES)).first() is not None
    pre_wage = data.get("preTransitionWage")
    frozen = facts.get("preTransitionMonthlyWage")
    if frozen is not None:
        if pre_wage is not None and dec(pre_wage) != dec(frozen):
            raise BadRequestException("the pre-transition wage is frozen on the statutory profile (HK-017) — it cannot "
                                      "be replaced at termination")
        pre_wage = frozen
    age = None
    if employee.date_of_birth:
        age = termination.year - employee.date_of_birth.year - (
            (termination.month, termination.day) < (employee.date_of_birth.month, employee.date_of_birth.day))
    try:
        params = hk_termination.parameters(rate_map)
        result = hk_termination.calculate(
            start=start, termination=termination, reason=data["reason"],
            pay_basis=data.get("payBasis") or facts.get("payBasis") or "MONTHLY", cc_status=cc["status"],
            params=params, post_wage=dec(data["postTransitionWage"]),
            pre_wage=dec(pre_wage) if pre_wage is not None else None,
            pre_wage_basis=facts.get("preTransitionWageBasis") or data.get("preTransitionWageBasis"),
            post_wage_basis=data.get("postTransitionWageBasis") or "LAST_FULL_MONTH",
            offsets=data.get("offsets") or [], age_at_termination=age,
            renewal_offer_refused=bool(data.get("renewalOfferRefused")),
            final_wages=dec(data.get("finalWages")), annual_leave_pay=dec(data.get("annualLeavePay")),
            holiday_pay=dec(data.get("holidayPay")), active_tax_clearance_hold=active_hold)
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    result["continuousContract"] = {"status": cc["status"], "since": cc.get("continuousSince")}
    result["packId"] = pack.pack_id
    for prior in db.query(HongKongTerminationResult).filter(HongKongTerminationResult.organization_id == organization_id,
                                                       HongKongTerminationResult.employee_id == employee_id,
                                                       HongKongTerminationResult.status == "CALCULATED"):
        prior.status = "SUPERSEDED"
    row = HongKongTerminationResult(organization_id=organization_id, employee_id=employee_id, termination_date=termination,
                               termination_reason=data["reason"], payment_type=result["paymentType"],
                               gross_entitlement=dec(result["grossEntitlement"]), total_offsets=dec(result["totalOffsets"]),
                               net_statutory_payment=dec(result["netStatutoryPayment"]), result=result,
                               evidence_hash=result["evidenceHash"], created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "create", "hk_termination_result", row.id,
           new={"paymentType": row.payment_type, "net": str(row.net_statutory_payment), "evidenceHash": row.evidence_hash},
           commit=False)
    db.commit()
    return row


def list_termination_results(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    """Termination calculations of the tenant — so a DIFFERENT operator can find
    and approve one (four-eyes), and an approved one can be issued as a statement."""
    q = db.query(HongKongTerminationResult).filter(HongKongTerminationResult.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(HongKongTerminationResult.employee_id == employee_id)
    return [{"id": r.id, "employeeId": r.employee_id, "terminationDate": _iso(r.termination_date),
             "reason": r.termination_reason, "paymentType": r.payment_type,
             "grossEntitlement": str(r.gross_entitlement), "totalOffsets": str(r.total_offsets),
             "netStatutoryPayment": str(r.net_statutory_payment),
             "totalFinalPayment": (r.result or {}).get("totalFinalPayment"), "status": r.status,
             "createdById": r.created_by_id, "approvedById": r.approved_by_id, "evidenceHash": r.evidence_hash}
            for r in q.order_by(HongKongTerminationResult.id.desc()).all()]


def list_average_wage_snapshots(db: Session, organization_id: int, employee_id: int) -> list:
    """An employee's average-wage snapshots with their override state — so a
    requested override can be found and approved by a different operator."""
    _employee(db, employee_id, organization_id)
    rows = (db.query(HongKongAverageWageSnapshot)
            .filter(HongKongAverageWageSnapshot.organization_id == organization_id,
                    HongKongAverageWageSnapshot.employee_id == employee_id)
            .order_by(HongKongAverageWageSnapshot.id.desc()).all())
    return [{"id": s.id, "benefitType": s.benefit_type, "referenceDate": _iso(s.reference_date),
             "lookbackStart": _iso(s.lookback_start), "lookbackEnd": _iso(s.lookback_end),
             "averageDailyWage": str(s.average_daily_wage), "status": s.status,
             "overrideRequested": None if s.override_average_daily_wage is None else str(s.override_average_daily_wage),
             "overrideReason": s.override_reason, "overrideRequestedById": s.override_requested_by_id,
             "overrideApprovedById": s.override_approved_by_id} for s in rows]


def approve_termination(db: Session, organization_id: int, result_id: int, actor_id: Optional[int]) -> HongKongTerminationResult:
    row = db.query(HongKongTerminationResult).filter(HongKongTerminationResult.id == result_id,
                                                HongKongTerminationResult.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Hong Kong termination result", result_id)
    if row.status != "CALCULATED":
        raise BadRequestException(f"only a CALCULATED result can be approved (this one is {row.status})")
    service.require_four_eyes(row.created_by_id, actor_id, "Approving a termination calculation")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    _audit(db, actor_id, "status_change", "hk_termination_result", row.id, new={"status": "APPROVED"})
    return row


# ── eMPF (§5, §12) ──────────────────────────────────────────────────────

EMPF_TRANSITIONS = {
    "PREPARED": ("VALIDATED",), "VALIDATED": ("SUBMITTED", "PREPARED"),
    "SUBMITTED": ("ACCEPTED", "PARTIAL", "REJECTED"), "ACCEPTED": ("PAID",), "PARTIAL": ("PAID", "AMENDED"),
    "REJECTED": ("AMENDED",), "PAID": ("RECONCILED",), "RECONCILED": ("AMENDED",), "AMENDED": (),
}


def _contribution_day(db: Session, period_end: date) -> date:
    """The MPF contribution day for a wage period, from the pack row
    mpf_contribution_day in force at the period end (never a literal)."""
    rate_map, _slabs, _pack = pack_inputs(db, period_end)
    try:
        day = int(hk_mpf.mpf_parameters(rate_map)["values"]["mpf_contribution_day"])
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    return hk_mpf.period_contribution_day(period_end, day)


def prepare_empf_submission(db: Session, organization_id: int, period: str, actor_id: Optional[int]) -> HongKongEmpfSubmission:
    """Remittance-statement rows for a contribution period from COMMITTED
    payslips. Zoiko does not transmit to eMPF (no certified interface) —
    the batch is prepared and validated for the operator's eMPF submission."""
    year, month = (int(p) for p in period.split("-"))
    start = date(year, month, 1)
    end = add_months(start, 1) - timedelta(days=1)
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    identifiers = (company.tax_identifiers or {}) if company else {}
    rows, errors = [], []
    if not identifiers.get("empf_employer_account"):
        errors.append("the eMPF employer account number is not recorded on the employer registration")
    # D-14: once a batch for the period has been SUBMITTED, a re-preparation is
    # a SUPPLEMENTARY batch carrying only payslips (e.g. approved correction
    # deltas) that no submitted batch for the period included — the submitted
    # contributions are never counted twice.
    submitted = (db.query(HongKongEmpfSubmission)
                 .filter(HongKongEmpfSubmission.organization_id == organization_id,
                         HongKongEmpfSubmission.contribution_period == period,
                         HongKongEmpfSubmission.status.in_(("SUBMITTED", "ACCEPTED", "PARTIAL", "PAID", "RECONCILED")))
                 .order_by(HongKongEmpfSubmission.id).all())
    already = {r.get("payslipId") for sub in submitted for r in (sub.rows or [])}
    for sub in submitted:           # rows the eMPF rejected are not "included" — they go again
        already -= {o.get("payslipId") for o in (sub.row_outcomes or []) if o.get("status") == "REJECTED"}
    for item, run in _committed_hk_payslips(db, organization_id, start - timedelta(days=62), end + timedelta(days=62)):
        trace = item.hk_calculation_trace or {}
        if not str(trace.get("period", {}).get("end", "")).startswith(period):
            continue
        if item.id in already:
            continue
        mpf = trace.get("mpf") or {}
        if (mpf.get("coverage") or {}).get("status") not in ("COVERED",):
            continue
        employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == item.employee_id).first()
        cf = (employee.compliance_fields or {}) if employee else {}
        facts = worker_facts(db, employee, end) or {}
        row_errors = []
        if not (cf.get("hkid") or cf.get("passport_number")):
            row_errors.append("HKID / passport missing")
        if not (facts.get("mpfSchemeRef") or cf.get("mpf_member_account")):
            row_errors.append("MPF scheme / member account mapping missing")
        rows.append({"payslipId": item.id, "employeeId": item.employee_id, "name": getattr(employee, "name", None),
                     "hkid": mask_identifier(cf.get("hkid") or cf.get("passport_number")),
                     # The member's scheme / account identifiers as RECORDED (profile
                     # fact, employee record), masked like the payslip shows them. The
                     # official eMPF member-identifier layout is not archived (G2): these
                     # are internal reconciliation fields, not a certified eMPF format.
                     "mpfSchemeRef": facts.get("mpfSchemeRef"),
                     "memberAccount": mask_identifier(cf.get("mpf_member_account")) if cf.get("mpf_member_account") else None,
                     "relevantIncome": (mpf.get("currentPeriod") or {}).get("relevantIncome"),
                     "employerMandatory": mpf.get("employer"), "employeeMandatory": mpf.get("employee"),
                     "catchUpPeriods": len(mpf.get("catchUp") or []), "errors": row_errors})
        errors += [f"payslip #{item.id}: {e}" for e in row_errors]
    totals = {"employees": len(rows),
              "relevantIncome": str(cents(sum((dec(r["relevantIncome"]) for r in rows), ZERO))),
              "employerMandatory": str(cents(sum((dec(r["employerMandatory"]) for r in rows), ZERO))),
              "employeeMandatory": str(cents(sum((dec(r["employeeMandatory"]) for r in rows), ZERO)))}
    if submitted:
        totals["batchType"] = "SUPPLEMENTARY"
        if not rows:
            errors.append(f"nothing to supplement: every committed payslip for {period} is in a submitted batch")
    payload_hash = canonical_hash({"period": period, "rows": rows})
    supplements = submitted[-1].id if submitted else None
    contribution_day = _contribution_day(db, end)
    # Idempotent: preparing the same period again with unchanged committed
    # payroll returns the live unsubmitted batch instead of a duplicate.
    same = (db.query(HongKongEmpfSubmission)
            .filter(HongKongEmpfSubmission.organization_id == organization_id,
                    HongKongEmpfSubmission.contribution_period == period,
                    HongKongEmpfSubmission.status.in_(("PREPARED", "VALIDATED")),
                    HongKongEmpfSubmission.payload_hash == payload_hash)
            .order_by(HongKongEmpfSubmission.id.desc()).first())
    if (same is not None and same.supplements_submission_id == supplements and same.contribution_day == contribution_day
            and list(same.validation_errors or []) == errors):
        return same
    # Duplicate protection: an earlier batch for the same period that was never
    # submitted is superseded by this one, so two batches can never both be
    # remitted for the same contributions. Retired BEFORE the new batch is
    # inserted — uq_payroll_hk_empf_open_batch allows one live unsubmitted batch.
    stale_batches = (db.query(HongKongEmpfSubmission)
                     .filter(HongKongEmpfSubmission.organization_id == organization_id,
                             HongKongEmpfSubmission.contribution_period == period,
                             HongKongEmpfSubmission.status.in_(("PREPARED", "VALIDATED"))).all())
    previous = {stale.id: stale.status for stale in stale_batches}
    for stale in stale_batches:
        stale.status = "AMENDED"
    sub = HongKongEmpfSubmission(organization_id=organization_id, contribution_period=period,
                            supplements_submission_id=supplements,
                            status="VALIDATED" if not errors and rows else "PREPARED", rows=rows, totals=totals,
                            payload_hash=payload_hash, validation_errors=errors,
                            contribution_day=contribution_day,
                            prepared_by_id=actor_id)
    try:
        db.flush()                       # the retirements first (UPDATE), then the INSERT below
        db.add(sub)
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = (db.query(HongKongEmpfSubmission)
                  .filter(HongKongEmpfSubmission.organization_id == organization_id,
                          HongKongEmpfSubmission.contribution_period == period,
                          HongKongEmpfSubmission.status.in_(("PREPARED", "VALIDATED")),
                          HongKongEmpfSubmission.payload_hash == payload_hash)
                  .order_by(HongKongEmpfSubmission.id.desc()).first())
        if winner is not None and winner.supplements_submission_id == supplements:
            return winner                # the concurrent request prepared exactly this batch
        raise _concurrent_conflict(f"An eMPF batch for {period}")
    for stale in stale_batches:
        stale.validation_errors = list(stale.validation_errors or []) + [
            f"superseded by batch #{sub.id} prepared for the same period"]
        _audit(db, actor_id, "status_change", "hk_empf_submission", stale.id, old={"status": previous[stale.id]},
               new={"status": "AMENDED", "supersededBy": sub.id}, commit=False)
    _audit(db, actor_id, "create", "hk_empf_submission", sub.id, new={"period": period, **totals}, commit=False)
    db.commit()
    return sub


def transition_empf_submission(db: Session, organization_id: int, submission_id: int, target: str,
                               actor_id: Optional[int], submission_reference: str = None, row_outcomes: list = None,
                               settlement_reference: str = None) -> HongKongEmpfSubmission:
    sub = db.query(HongKongEmpfSubmission).filter(HongKongEmpfSubmission.id == submission_id,
                                             HongKongEmpfSubmission.organization_id == organization_id).first()
    if sub is None:
        raise NotFoundException("Hong Kong eMPF submission", submission_id)
    if target not in EMPF_TRANSITIONS.get(sub.status, ()):
        raise BadRequestException(f"eMPF submission #{sub.id} cannot move from {sub.status} to {target}")
    if target == "SUBMITTED":
        if not submission_reference:
            raise BadRequestException("the eMPF submission reference is required (recorded from the eMPF platform)")
        service.require_four_eyes(sub.prepared_by_id, actor_id, "An eMPF submission")
        sub.submission_reference, sub.submitted_by_id, sub.approved_by_id = submission_reference, actor_id, actor_id
    if target in ("ACCEPTED", "PARTIAL", "REJECTED"):
        outcomes = row_outcomes or []
        rejected = [o for o in outcomes if o.get("status") == "REJECTED"]
        accepted = [o for o in outcomes if o.get("status") == "ACCEPTED"]
        derived = "REJECTED" if outcomes and not accepted else ("PARTIAL" if rejected else "ACCEPTED")
        if outcomes and derived != target:
            raise BadRequestException(f"the row outcomes describe a {derived} submission, not {target}")
        sub.row_outcomes = outcomes
    if target == "PAID":
        if not settlement_reference:
            raise BadRequestException("the settlement reference is required")
        sub.settlement_reference = settlement_reference
    old = sub.status
    sub.status = target
    # A rejected row never rewrites payroll history: payslips are untouched.
    _audit(db, actor_id, "status_change", "hk_empf_submission", sub.id, old={"status": old},
           new={"status": target, "reference": sub.submission_reference, "rejectedRows":
                len([o for o in (sub.row_outcomes or []) if o.get("status") == "REJECTED"])})
    return sub


# ── Salaries Tax information (HK-012) ───────────────────────────────────

def salaries_tax_estimate(db: Session, ya: str, income, deductions, allowances: dict,
                          deduction_claims: dict = None, elections=()) -> dict:
    start, _end = year_of_assessment_bounds(ya)
    rate_map, slabs, pack = pack_inputs(db, start)
    try:
        out = hk_salaries_tax.estimate(year_of_assessment=ya, rate_map=rate_map, slabs=slabs, income=dec(income),
                                       deductions=dec(deductions), allowances=allowances or {},
                                       deduction_claims=deduction_claims or {}, elections=elections or ())
    except HongKongCalculationBlockedError as exc:
        raise _blocked(exc)
    out["packId"] = pack.pack_id
    return out


# ── Super Admin: activation evidence, golden check, statutory summary ───

def gate_state(db: Session, gate: str) -> str:
    """EVIDENCE_REQUIRED / SUBMITTED / PASS for an HK-GATE-Gn artifact —
    PASS only when a DIFFERENT Super Admin reviewed an uploaded document and
    it has not been superseded."""
    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == f"HK-GATE-{gate}",
                                            SourceArtifact.superseded_by_id.is_(None)).all())
    if not rows:
        return "EVIDENCE_REQUIRED"
    for r in rows:
        if r.reviewer_id and r.file_path and r.created_by_id and r.reviewer_id != r.created_by_id:
            return "PASS"
    return "SUBMITTED"


def _pack_rows_for_golden(db: Session, pack: JurisdictionPack, on: date, period: tuple) -> tuple:
    from app.modules.payroll.service import pack_rows_for_golden

    rate_map, slabs = pack_rows_for_golden(db, pack, on)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.organization_id.is_(None)).all()
    return rate_map, slabs, rule_segments(rows, *period)


def pack_golden_check(db: Session, pack: JurisdictionPack) -> dict:
    """Every HK golden vector whose pay date is inside the pack window,
    re-run with the fixture's embedded rows REPLACED by this pack's rows
    (shared run_pack_golden_vectors; HK also binds the period-split segments)."""
    def bind(context, pay):
        period = (date.fromisoformat(context.get("period_start") or pay.replace(day=1).isoformat()),
                  date.fromisoformat(context.get("period_end") or pay.isoformat()))
        rate_map, slabs, segments = _pack_rows_for_golden(db, pack, pay, period)
        return {"rate_map": rate_map, "slabs": slabs, "hk_rule_segments": segments}

    return service.run_pack_golden_vectors(db, pack, "hk_golden", bind)


def hk_activation_evidence_refusal(db: Session, pack: JurisdictionPack) -> Optional[str]:
    if gate_state(db, "G1") != "PASS":
        return ("Hong Kong packs need gate G1 (statutory content certification by a Hong Kong specialist) evidence "
                "ACCEPTED before they can go Active — record the signed certification as HK-GATE-G1 (uploaded "
                "document); a different Super Admin reviews it.")
    # Row-level fail-closed: G1 evidence attests the review, but a value still
    # marked UNVERIFIED — G1, or with no hashed source (SOURCE_HASH_REQUIRED),
    # or outside every governed domain, must never reach Active. The specialist's
    # confirmation is recorded by re-linking the value to a reviewed, hashed
    # source in a Draft version (Statutory Configuration → governed edit).

    cfg = domains(db, pack.id)
    pending = [r for d in cfg["domains"] for r in d["rows"] if r["status"] != "SOURCED"]
    if pending or cfg["unmapped"]:
        by_status = {}
        for r in pending:
            by_status.setdefault(r["status"], []).append(r["key"])
        detail = "; ".join(f"{len(keys)} {status} ({', '.join(sorted(set(keys))[:4])}"
                           f"{', …' if len(set(keys)) > 4 else ''})" for status, keys in sorted(by_status.items()))
        if cfg["unmapped"]:
            detail += ("; " if detail else "") + f"{len(cfg['unmapped'])} row(s) outside every governed domain"
        return (f"{pack.pack_id} v{pack.version} still holds values that are not source-verified: {detail}. "
                "Link each to a reviewed, hashed source in a Draft version before activating.")
    check = pack_golden_check(db, pack)
    if not check["casesInWindow"]:
        return f"No Hong Kong golden vector falls inside {pack.pack_id} v{pack.version}'s window."
    if check["failures"]:
        return (f"{pack.pack_id} v{pack.version}'s own rows do not reproduce {len(check['failures'])} of "
                f"{check['casesInWindow']} golden vector(s): " + ", ".join(f["case"] for f in check["failures"][:5]))
    return None


def statutory_summary(db: Session) -> dict:
    """Super Admin Hong Kong compliance summary — platform-level only (no
    organization-derived counts)."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    packs = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == HK,
                                              JurisdictionPack.pack_type == "tax").order_by(JurisdictionPack.effective_from).all()
    pack_views = []
    certification_items = []
    for p in packs:
        rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p.id,
                                                  ContributionRate.organization_id.is_(None)).all()
        slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p.id, TaxSlab.organization_id.is_(None)).all()
        unsourced = [r.component_key for r in rates if not r.source_document_id] + \
                    [s.rate_label for s in slabs if not s.source_document_id]
        g1_rows = [r.component_key for r in rates if "[G1]" in (r.label or "")] + \
                  [s.rate_label for s in slabs if "[G1]" in (s.rate_label or "")]
        certification_items += [f"{p.pack_id}: {k}" for k in g1_rows]
        pack_views.append({"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                           "yearOfAssessment": p.tax_year, "effectiveFrom": _iso(p.effective_from),
                           "effectiveTo": _iso(p.effective_to), "contributionRates": len(rates), "taxSlabs": len(slabs),
                           "unsourcedRows": unsourced, "g1CertificationRows": len(g1_rows),
                           "approvedById": p.approved_by_id})
    sources = db.query(SourceArtifact).filter(SourceArtifact.id.in_(
        {r.source_document_id for p in packs for r in db.query(ContributionRate.source_document_id)
         .filter(ContributionRate.jurisdiction_pack_id == p.id)} or {-1})).all()
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == HK).first()
    return {
        "country": HK, "specification": SPEC,
        "architecture": {"payrollWithholding": "NONE — Salaries Tax is employee-assessed (no PAYE)",
                         "ir56gHold": "LEGAL_HOLD (payment control, not a deduction)",
                         "calculator": "engine/countries/hong_kong.py via the shared StandardStrategy"},
        "packs": pack_views,
        "sources": [{"id": s.id, "agency": s.agency, "title": s.title, "url": s.source_url, "sha256": s.checksum_sha256,
                     "reviewed": bool(s.reviewer_id), "unverified": "[UNVERIFIED" in (s.title or "")} for s in sources],
        "gates": [{"gate": g, "requirement": text, "state": gate_state(db, g), "evidenceTag": f"HK-GATE-{g}"}
                  for g, text in HK_GATES.items()],
        "certificationItems": certification_items,
        "serviceRegistry": registry.availability if registry else "MISSING (onboarding blocked)",
        "activationReadiness": activation_readiness(db),
        "templateCoverage": template_coverage(db),
        "ownerDecisions": owner_decisions(db),
        "externalDependencies": external_dependencies(db),
        "externalBlockers": [
            "IRD XML schemas / sample files for BIR56A, IR56B/E/F/G not archived — e-filing export gated (G2)",
            "No certified eMPF interface or test credentials — submissions recorded from operator evidence only (G2)",
            "Hong Kong specialist certification of [G1] rows (earning classification, week start, partial-month MPF basis)",
            "Parallel payroll cycles (G3), PDPO / privacy review (G5), operations runbooks (G6), launch approvals (G7)",
            "Industry Scheme (construction/catering casual), domestic helpers, ORSO scheme rules — out of launch scope",
            "Bilingual English / Traditional Chinese statutory output not validated",
        ],
    }




def preview_calculation(db: Session, data) -> dict:
    """Super Admin read-only preview: the PRODUCTION engine (calculate_payroll
    → countries/hong_kong.py) against the rows of the HK pack whose window
    contains the pay date — any status, so a Draft pack can be checked before
    activation. Creates / changes nothing."""
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.service import pack_rows_for_golden
    from app.modules.payroll.hmrc_golden_harness import _build_rate_map, _build_slabs

    pack = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == HK, JurisdictionPack.pack_type == "tax",
                                              JurisdictionPack.effective_from <= data.payDate,
                                              JurisdictionPack.effective_to >= data.payDate)
            .order_by(JurisdictionPack.effective_from.desc()).first())
    if pack is None:
        raise BadRequestException(f"no Hong Kong pack covers {data.payDate}")
    ps = data.periodStart or data.payDate.replace(day=1)
    pe = data.periodEnd or data.payDate
    rate_map, slabs = pack_rows_for_golden(db, pack, data.payDate)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.organization_id.is_(None)).all()
    facts = {"profileId": "PREVIEW", "dateOfBirth": data.dateOfBirth.isoformat(), "dateOfJoining": data.dateOfJoining.isoformat(),
             **(data.workerFacts or {})}
    ctx = PayrollContext(gross=dec(data.gross), basic=dec(data.gross), country=HK, pay_frequency=data.payFrequency,
                         pay_date=data.payDate, period_start=ps, period_end=pe,
                         rate_map=_build_rate_map(rate_map), slabs=_build_slabs(slabs),
                         hk_worker_facts=facts, hk_hours=data.hours or {}, hk_rule_segments=rule_segments(rows, ps, pe))
    try:
        result = calculate_payroll(ctx, "standard")
    except HongKongCalculationBlockedError as exc:
        return {"status": "BLOCKED", "key": exc.key, "reason": exc.reason, "packId": pack.pack_id, "packStatus": pack.status}
    return {"status": "CALCULATED", "packId": pack.pack_id, "packVersion": pack.version, "packStatus": pack.status,
            "mpfEmployee": str(result.employee_pension), "mpfEmployer": str(result.employer_pension),
            "incomeTaxWithheld": str(result.tds), "netPay": str(result.net_pay),
            "trace": result.hk_calculation_trace, "writes": "NONE"}


# ══════════════════════════════════════════════════════════════════════════
# (was hk_configuration.py)
# ══════════════════════════════════════════════════════════════════════════

_ENG = "app/modules/payroll/engine/jurisdictions/hong_kong/"
# (domain key, label, matcher on a row key, consumer)
DOMAINS = [
    ("mpf", "MPF", lambda k: k.startswith("mpf_") and k != "mpf_offset_transition_date", _ENG + "mpf.py"),
    ("smw", "Minimum Wage", lambda k: k.startswith("smw_"), _ENG + "minimum_wage.py"),
    ("continuous_contract", "Continuous Contract", lambda k: k.startswith("eo_cc_") or k == "eo_week_start_day",
     _ENG + "continuous_contract.py"),
    ("average_wage", "Average Wage", lambda k: k.startswith(("eo_average_wage_", "eo_overtime_aw_")) or k == "eo_four_fifths_factor",
     _ENG + "average_wage.py"),
    ("eo_entitlements", "Employment Ordinance Entitlements",
     lambda k: k.startswith(("eo_sickness_", "eo_maternity_", "eo_paternity_", "eo_holiday_pay_", "eo_wage_payment_")),
     _ENG + "entitlements.py"),
    ("leave_holidays", "Leave & Holidays", lambda k: k in ("HK_ANNUAL_LEAVE_SCALE", "HK_STATUTORY_HOLIDAY"),
     _ENG + "entitlements.py"),
    ("sp_lsp", "SP / LSP", lambda k: k.startswith(("sp_", "lsp_")) or k in ("mpf_offset_transition_date", "eo_days_per_year"),
     _ENG + "termination.py"),
    ("ird", "IRD timing", lambda k: k.startswith("ird_"), _ENG + "ird.py"),
    ("salaries_tax", "Salaries Tax — informational",
     lambda k: k.startswith(("hk_allowance_", "hk_deduction_", "hk_tax_")) or k.startswith("HK_SALARIES_TAX"),
     _ENG + "salaries_tax.py"),
    ("earning_classification", "Earning Classification", lambda k: k == "HK_EARNING_CLASS",
     "app/modules/payroll/hong_kong_service.py; report generators (IR56B)"),
]
SALARIES_TAX_NOTICE = "Informational calculation only — Salaries Tax is not withheld from monthly HK payroll."
EDITABLE = ("Draft", "In Review", "QA", "Approved")


def _domain_of(key: str):
    for dkey, label, match, consumer in DOMAINS:
        if match(key):
            return dkey, label, consumer
    return None, None, None




def _pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or pack.jurisdiction_country != HK or pack.pack_type != "tax":
        raise NotFoundException("Hong Kong statutory pack", pack_row_id)
    return pack


def _source(db: Session, source_id):
    from app.modules.payroll.models import SourceArtifact

    if not source_id:
        return None
    s = db.get(SourceArtifact, source_id)
    if s is None:
        return None
    return {"id": s.id, "agency": s.agency, "title": s.title, "url": s.source_url, "sha256": s.checksum_sha256,
            "reviewed": bool(s.reviewer_id) and s.reviewer_id != s.created_by_id,
            "unverified": "[UNVERIFIED" in (s.title or ""), "publicationDate": _iso(s.publication_date)}


def _unit(key: str, r) -> str:
    if r.text_value is not None:
        return "date" if len(r.text_value) == 10 and r.text_value[4] == "-" else "text"
    if r.employee_rate_pct is not None or r.employer_rate_pct is not None:
        return "percent"
    if key.endswith("_hourly_rate"):
        return "HKD per hour"
    if "days" in key or key.endswith("_day"):
        return "days" if "days" in key else "day of month"
    if "months" in key:
        return "months"
    if "weeks" in key:
        return "weeks"
    if key.endswith("_age") or "_age" in key:
        return "years of age"
    if key.endswith(("_pct",)) or "factor" in key or key.endswith("_rate"):
        return "ratio"
    return "HKD"


def _pct(v) -> str:
    return f"{(Decimal(str(v)) * 100).normalize():f}%"


def _rate_row(db: Session, pack, r) -> dict:
    dkey, dlabel, consumer = _domain_of(r.component_key)
    unit = _unit(r.component_key, r)
    if r.text_value is not None:
        display = r.text_value
    elif r.employee_rate_pct is not None or r.employer_rate_pct is not None:
        parts = []
        if r.employee_rate_pct is not None:
            parts.append(f"employee {_pct(r.employee_rate_pct)}")
        if r.employer_rate_pct is not None:
            parts.append(f"employer {_pct(r.employer_rate_pct)}")
        display = " · ".join(parts)
    elif unit == "ratio" and r.flat_amount is not None and Decimal(str(r.flat_amount)) <= 1 and "pct" not in r.component_key:
        display = f"{Decimal(str(r.flat_amount)).normalize():f}"
    elif r.flat_amount is not None:
        display = f"{Decimal(str(r.flat_amount)):,.2f}" if unit in ("HKD", "HKD per hour") else f"{Decimal(str(r.flat_amount)).normalize():f}"
    else:
        display = "—"
    src = _source(db, r.source_document_id)
    g1 = "[G1]" in (r.label or "") or bool(src and src["unverified"])
    status = ("SOURCE_HASH_REQUIRED" if not (src and src["sha256"]) else
              "UNVERIFIED — G1" if g1 else "SOURCED")
    return {"kind": "rate", "id": r.id, "key": r.component_key, "label": r.label, "domain": dkey, "domainLabel": dlabel,
            "value": display, "unit": unit,
            "raw": {"employeeRatePct": str(r.employee_rate_pct) if r.employee_rate_pct is not None else None,
                    "employerRatePct": str(r.employer_rate_pct) if r.employer_rate_pct is not None else None,
                    "flatAmount": str(r.flat_amount) if r.flat_amount is not None else None, "textValue": r.text_value},
            "effectiveFrom": _iso(r.effective_from or pack.effective_from), "effectiveTo": _iso(r.effective_to or pack.effective_to),
            "source": src, "g1": g1, "status": status, "consumer": consumer,
            "editable": pack.status in EDITABLE}


def _slab_row(db: Session, pack, s) -> dict:
    dkey, dlabel, consumer = _domain_of(s.rule_type)
    if s.rule_type == "HK_STATUTORY_HOLIDAY":
        display, unit, label = s.tax_formula, "date", f"{s.rate_label} ({s.filing_status})"
    elif s.rule_type == "HK_ANNUAL_LEAVE_SCALE":
        hi = f"–{s.max_amount.normalize():f}" if s.max_amount is not None else "+"
        display, unit, label = f"{s.flat_amount.normalize():f} days", "days", f"service year {s.min_amount.normalize():f}{hi}"
    elif s.rule_type.startswith("HK_SALARIES_TAX"):
        hi = f"{s.max_amount:,.0f}" if s.max_amount is not None else "∞"
        display, unit, label = f"{s.rate_pct.normalize():f}%", "percent of band", f"HK$ {s.min_amount:,.0f} – {hi} ({s.rate_label})"
    elif s.rule_type == "HK_EARNING_CLASS":
        display, unit = (s.tax_formula or "").split(": ")[-1] if s.tax_regime != "IRD" else (s.tax_formula or ""), "treatment"
        label = f"{s.filing_status} → {s.tax_regime}"
    else:
        display, unit, label = s.tax_formula or s.rate_label, "", s.rate_label
    src = _source(db, s.source_document_id)
    g1 = "[G1]" in (s.rate_label or "") or bool(src and src["unverified"])
    status = ("SOURCE_HASH_REQUIRED" if not (src and src["sha256"]) else "UNVERIFIED — G1" if g1 else "SOURCED")
    return {"kind": "slab", "id": s.id, "key": s.rule_type, "label": label, "domain": dkey, "domainLabel": dlabel,
            "value": display, "unit": unit,
            "raw": {"minAmount": str(s.min_amount) if s.min_amount is not None else None,
                    "maxAmount": str(s.max_amount) if s.max_amount is not None else None,
                    "ratePct": str(s.rate_pct) if s.rate_pct is not None else None,
                    "flatAmount": str(s.flat_amount) if s.flat_amount is not None else None,
                    "taxFormula": s.tax_formula, "rateLabel": s.rate_label},
            "effectiveFrom": _iso(s.effective_from or pack.effective_from), "effectiveTo": _iso(s.effective_to or pack.effective_to),
            "source": src, "g1": g1, "status": status, "consumer": consumer, "editable": pack.status in EDITABLE}


def _rows(db: Session, pack) -> list:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.component_key, ContributionRate.effective_from).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.rule_type, TaxSlab.sort_order).all())
    return [_rate_row(db, pack, r) for r in rates] + [_slab_row(db, pack, s) for s in slabs]


def domains(db: Session, pack_row_id: int) -> dict:
    pack = _pack(db, pack_row_id)
    rows = _rows(db, pack)
    out = []
    for dkey, label, _m, consumer in DOMAINS:
        items = [r for r in rows if r["domain"] == dkey]
        out.append({"key": dkey, "label": label, "consumer": consumer, "rows": items, "count": len(items),
                    "unverified": sum(1 for r in items if r["status"] != "SOURCED"),
                    "notice": SALARIES_TAX_NOTICE if dkey == "salaries_tax" else None})
    unmapped = [r["key"] for r in rows if r["domain"] is None]
    return {"pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
                     "yearOfAssessment": pack.tax_year, "effectiveFrom": _iso(pack.effective_from),
                     "effectiveTo": _iso(pack.effective_to), "approvedById": pack.approved_by_id,
                     "editable": pack.status in EDITABLE, "versionState": _version_state(pack, date.today())},
            "domains": out, "total": len(rows), "unmapped": unmapped}


def _version_state(pack, today: date) -> str:
    starts, ends = pack.effective_from, pack.effective_to
    if pack.status == "Retired":
        return "RETIRED"
    if pack.status in ("Superseded", "Deprecated"):
        return "SUPERSEDED"
    if pack.status == "Active":
        if starts and starts > today:
            return "NEXT_PUBLISHED"            # approved and live-capable, but not yet in force
        if ends and ends < today:
            return "PAST_ACTIVE"               # still pinned by its period's payroll
        return "CURRENT_ACTIVE"
    if starts and starts > today:
        return "FUTURE_DRAFT"
    return "DRAFT"


def versions(db: Session, on: Optional[date] = None) -> list:
    from app.modules.payroll.models import JurisdictionPack

    on = on or date.today()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == HK, JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.effective_from, JurisdictionPack.version).all())
    return [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status, "yearOfAssessment": p.tax_year,
             "effectiveFrom": _iso(p.effective_from), "effectiveTo": _iso(p.effective_to),
             "approvedById": p.approved_by_id, "versionState": _version_state(p, on)} for p in packs]


def explain_resolution(db: Session, on: date) -> dict:
    """Why payroll on `on` uses what it uses (pack + exact-year templates)."""
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.models import ReportTemplate
    from app.modules.payroll.service import _resolve_effective_rate_inputs

    # The explanation is the payroll decision itself: the same resolution path
    # payroll runs (single Active pack, rows present, jurisdiction ready), so it
    # can never say SELECTED where payroll would block.
    blocked = None
    try:
        _rate_map, _slabs, _rates, pack = _resolve_effective_rate_inputs(db, None, HK, on, org_opted_in=True)
    except MissingComplianceConfigurationError as exc:
        pack, blocked = None, str(exc)
    templates = []
    for report_type, kind in REPORT_TYPES.items():
        key = year_key(kind, on)
        active = (db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == HK, ReportTemplate.report_type == report_type,
                                                  ReportTemplate.reporting_year == key, ReportTemplate.status == "Active").first())
        templates.append({"reportType": report_type, "yearKey": key, "yearBasis": "year of assessment" if kind == "YA" else "calendar year",
                          "template": None if active is None else {"id": active.id, "version": active.version},
                          "rule": "exact year only — no fallback to another year's template"})
    return {"payrollDate": on.isoformat(), "yearOfAssessment": year_of_assessment(on),
            "pack": None if pack is None else {"id": pack.id, "packId": pack.pack_id, "version": pack.version,
                                               "effectiveFrom": _iso(pack.effective_from), "effectiveTo": _iso(pack.effective_to)},
            "rule": ("the Active Hong Kong statutory pack whose effective window contains the payroll date; Draft / "
                     "In Review / Approved packs are never selected; rows inside it apply by their own effective dates"),
            "outcome": ("SELECTED" if pack else
                        f"BLOCKED — HK payroll is blocked for this date (fail-closed): {blocked}"),
            "blockReason": blocked,
            "templates": templates}


def _match_key(r: dict) -> str:
    """A key stable across years: rates by component (+ start date for dated SMW rows);
    slabs by their structural identity, never by a label that embeds the year."""
    raw = r["raw"]
    if r["kind"] == "rate":
        return f"rate|{r['key']}|" + (r["effectiveFrom"] if r["key"].startswith("smw_") else "")
    if r["key"] == "HK_STATUTORY_HOLIDAY":
        return f"slab|{r['key']}|{raw['taxFormula']}|{raw['rateLabel']}"
    if r["key"] in ("HK_ANNUAL_LEAVE_SCALE",) or r["key"].startswith("HK_SALARIES_TAX"):
        return f"slab|{r['key']}|{raw['minAmount']}|{raw['maxAmount']}"
    return f"slab|{r['key']}|{r['label']}"


def compare(db: Session, from_id: int, to_id: int) -> dict:
    a, b = _pack(db, from_id), _pack(db, to_id)
    ra = {_match_key(r): r for r in _rows(db, a)}
    rb = {_match_key(r): r for r in _rows(db, b)}
    added = [rb[k] for k in sorted(set(rb) - set(ra))]
    removed = [ra[k] for k in sorted(set(ra) - set(rb))]
    changed, unchanged = [], 0
    for k in sorted(set(ra) & set(rb)):
        x, y = ra[k], rb[k]
        diffs = {f: {"from": x[f], "to": y[f]} for f in ("value", "unit", "effectiveFrom", "effectiveTo") if x[f] != y[f]}
        if x["kind"] == "rate" and a.pack_id != b.pack_id:     # a new year's window is expected, not a change
            if not x["key"].startswith("smw_"):
                diffs.pop("effectiveFrom", None)
            diffs.pop("effectiveTo", None)
        elif a.pack_id != b.pack_id and (x["effectiveFrom"], x["effectiveTo"]) == (_iso(a.effective_from), _iso(a.effective_to))                 and (y["effectiveFrom"], y["effectiveTo"]) == (_iso(b.effective_from), _iso(b.effective_to)):
            diffs.pop("effectiveFrom", None)                    # a slab spanning its own pack's year: not a change
            diffs.pop("effectiveTo", None)
        if (x["source"] or {}).get("sha256") != (y["source"] or {}).get("sha256"):
            diffs["sourceSha256"] = {"from": (x["source"] or {}).get("sha256"), "to": (y["source"] or {}).get("sha256")}
        if diffs:
            changed.append({"domain": y["domainLabel"], "key": y["key"], "label": y["label"], "changes": diffs})
        else:
            unchanged += 1
    slim = lambda r: {"domain": r["domainLabel"], "key": r["key"], "label": r["label"], "value": r["value"]}  # noqa: E731
    return {"from": {"id": a.id, "packId": a.pack_id, "version": a.version, "status": a.status, "yearOfAssessment": a.tax_year},
            "to": {"id": b.id, "packId": b.pack_id, "version": b.version, "status": b.status, "yearOfAssessment": b.tax_year},
            "added": [slim(r) for r in added], "removed": [slim(r) for r in removed], "changed": changed, "unchanged": unchanged}


def update_row(db: Session, kind: str, row_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Governed edit of one HK statutory row (Draft-family packs only)."""
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab
    from app.modules.payroll.service import _invalidate_pack_approval_on_edit, _require_editable_pack, record_tax_audit

    model = {"rate": ContributionRate, "slab": TaxSlab}.get(kind)
    if model is None:
        raise BadRequestException("kind must be 'rate' or 'slab'")
    row = db.get(model, row_id)
    if row is None or row.organization_id is not None or row.jurisdiction_country != HK:
        raise NotFoundException("Hong Kong statutory row", row_id)
    pack = _pack(db, row.jurisdiction_pack_id)
    _require_editable_pack(pack)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("A statutory change needs a change reason.")
    source_id = data.get("sourceDocumentId")
    source = db.get(SourceArtifact, int(source_id)) if source_id else None
    if source is None:
        raise BadRequestException("A statutory change needs the official source document (an existing SourceArtifact).")
    verify = data.get("specialistVerified") is True
    if verify and not (source.checksum_sha256 and source.file_path and source.reviewer_id
                       and source.reviewer_id != source.created_by_id and "[UNVERIFIED" not in (source.title or "")):
        raise BadRequestException("Recording the specialist's verification needs a stored, hashed source document reviewed "
                                  "by a Super Admin other than its uploader (and not itself marked UNVERIFIED).")
    allowed = ({"employeeRatePct": "employee_rate_pct", "employerRatePct": "employer_rate_pct", "flatAmount": "flat_amount",
                "textValue": "text_value", "effectiveFrom": "effective_from", "effectiveTo": "effective_to"} if kind == "rate" else
               {"minAmount": "min_amount", "maxAmount": "max_amount", "ratePct": "rate_pct", "flatAmount": "flat_amount",
                "taxFormula": "tax_formula", "effectiveFrom": "effective_from", "effectiveTo": "effective_to"})
    unknown = set(data) - set(allowed) - {"reason", "sourceDocumentId", "specialistVerified"}
    if unknown:
        raise BadRequestException(f"not editable here: {', '.join(sorted(unknown))}")
    old, new = {}, {}
    for field, column in allowed.items():
        if field not in data:
            continue
        value = data[field]
        if column.startswith("effective_"):
            value = date.fromisoformat(value) if value else None
        elif column in ("text_value", "tax_formula"):
            value = value if value not in ("",) else None
        else:
            value = Decimal(str(value)) if value not in (None, "") else None
        old[field], new[field] = str(getattr(row, column)), str(value)
        setattr(row, column, value)
    ef, et = row.effective_from or pack.effective_from, row.effective_to or pack.effective_to
    if ef and et and et < ef:
        db.rollback()
        raise BadRequestException("effective_to cannot be before effective_from")
    old["sourceDocumentId"], new["sourceDocumentId"] = row.source_document_id, int(source_id)
    row.source_document_id = int(source_id)
    # The HK specialist's confirmation (G1) of a value seeded "[G1]": the marker is
    # removed only together with a reviewed, hashed source (checked above), so the
    # row reads SOURCED and may then pass the activation guard.
    label_col = "label" if kind == "rate" else "rate_label"
    if verify and "[G1]" in (getattr(row, label_col) or ""):
        old["label"] = getattr(row, label_col)
        setattr(row, label_col, " ".join(getattr(row, label_col).replace("[G1]", " ").split()))
        new["label"], new["specialistVerified"] = getattr(row, label_col), True
    _invalidate_pack_approval_on_edit(pack)
    # Maker identity: the pack's last editor is whoever changed its statutory
    # substance (the approve / activate maker-checker checks read
    # updated_by_id); every editor of this version is also on the audit trail
    # (statutory_editors) so none of them can approve it.
    if actor_id is not None:
        pack.updated_by_id = actor_id
    db.flush()
    record_tax_audit(db, actor_id=actor_id, action="update", entity_type=f"hk_statutory_{kind}", entity_id=row.id,
                     jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference="HK statutory configuration",
                     old_value=old, new_value=new, reason=reason, auto_commit=False)
    db.commit()
    return (_rate_row if kind == "rate" else _slab_row)(db, pack, row)


def statutory_editors(db: Session, pack) -> set:
    """Every Super Admin who edited a statutory row of this pack version (from
    the immutable audit trail written by update_row)."""
    from app.modules.payroll.models import TaxConfigurationAudit

    rows = (db.query(TaxConfigurationAudit.actor_id)
            .filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id,
                    TaxConfigurationAudit.entity_type.in_(("hk_statutory_rate", "hk_statutory_slab")),
                    TaxConfigurationAudit.actor_id.isnot(None)).distinct().all())
    return {r[0] for r in rows}


def new_version(db: Session, pack_row_id: int, version: str, reason: str, actor_id: Optional[int]):
    """A Draft copy of an HK pack (all rows cloned). Also the only rollback path."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    src = _pack(db, pack_row_id)
    version, reason = (version or "").strip(), (reason or "").strip()
    if not version or not reason:
        raise BadRequestException("A new version needs a version number and a reason (e.g. the change or rollback reason).")
    if db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == src.pack_id, JurisdictionPack.version == version).first():
        raise BadRequestException(f"{src.pack_id} v{version} already exists")
    new = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=src.pack_id, jurisdictionCountry=HK, packType="tax", version=version, status="Draft",
        effectiveFrom=src.effective_from, effectiveTo=src.effective_to, sourceReferences=src.source_references,
        regulatoryAuthority=src.regulatory_authority, complianceCategory=src.compliance_category), actor_id=actor_id)
    new.tax_year = src.tax_year
    # the pack-level source evidence carries over (activation requires it — without
    # it a new version, including a rollback, could never go Active; found by the
    # whole-lifecycle test). Per-row sources come with the copied rows.
    new.source_document_id = src.source_document_id
    # the shared clone copies rates; slabs (holidays, earning classes, bands, leave scale) are copied here
    if not db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == new.id).first():
        cols = [c.name for c in TaxSlab.__table__.columns if c.name not in ("id", "jurisdiction_pack_id", "created_at", "updated_at")]
        for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == src.id, TaxSlab.organization_id.is_(None)).all():
            db.add(TaxSlab(jurisdiction_pack_id=new.id, **{c: getattr(s, c) for c in cols}))
    if not db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == new.id).first():
        cols = [c.name for c in ContributionRate.__table__.columns if c.name not in ("id", "jurisdiction_pack_id", "created_at", "updated_at")]
        for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == src.id,
                                                   ContributionRate.organization_id.is_(None)).all():
            db.add(ContributionRate(jurisdiction_pack_id=new.id, **{c: getattr(r, c) for c in cols}))
    db.flush()
    service.record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=new.id,
                             jurisdiction_pack_id=new.id, tax_version=version, legal_reference="HK statutory configuration",
                             old_value={"copiedFrom": f"{src.pack_id} v{src.version}"},
                             new_value={"status": "Draft", "version": version}, reason=reason, auto_commit=False)
    db.commit()
    return new


# ══════════════════════════════════════════════════════════════════════════
# (was hk_governance.py)
# ══════════════════════════════════════════════════════════════════════════

REGISTRY_OPEN, REGISTRY_CLOSED = "AVAILABLE", "PLANNED"
GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
# Report type → year-key kind: IRD forms by year of assessment, MPF / termination by calendar year.
REPORT_TYPES = {
    "HK_BIR56A": "YA", "HK_IR56B": "YA", "HK_IR56E": "YA", "HK_IR56F": "YA", "HK_IR56G": "YA",
    "HK_EMPF_REMITTANCE": "CALENDAR", "HK_MPF_CONTRIBUTION_RECORD": "CALENDAR", "HK_TERMINATION_STATEMENT": "CALENDAR",
}


PRODUCTION_EVIDENCE_TAG = "HK-PRODUCTION-VERIFICATION"
# Owner decisions (HK_OWNER_DECISION_REGISTER.md). blocksLaunch = the G7 form §C requires it recorded.
DECISIONS = {
    "D-1": ("eMPF submission interface at launch", True), "D-2": ("Retention period per data category", True),
    "D-3": ("Deletion vs anonymisation at end of retention", True), "D-4": ("Encryption at rest", True),
    "D-5": ("Production HK identity-token secret", True), "D-6": ("Bilingual output a launch requirement", True),
    "D-7": ("Launch-scope exclusions", True), "D-8": ("HK payroll-run approval four-eyes", True),
    "D-9": ("Legal-hold policy", True), "D-10": ("Privileged (assisted) access policy", True),
    "D-11": ("Future-year template publication owner", True),
    "D-12": ("Per-value reviewer columns (shared platform)", False),
    "D-13": ("Platform-wide template compare (shared platform)", False),
    "D-14": ("Audit correlation id (shared platform)", False),
}
EXTERNAL_DEPENDENCIES = (
    ("X-1", "HK payroll / statutory specialist certification", "G1"), ("X-2", "IRD schemas, samples, test submission", "G2"),
    ("X-3", "eMPF onboarding and certification", "G2"), ("X-4", "Parallel payroll cycles (real data)", "G3"),
    ("X-5", "Independent penetration test", "G5"), ("X-6", "Privacy counsel review", "G5"),
    ("X-7", "Runbook approval", "G6"), ("X-8", "Approved production snapshot (restore rehearsal)", "G7"),
    ("X-9", "Read-only production facts", "G7"), ("X-10", "Launch approvals", "G7"),
)


def _evidence(db: Session, tag: str):
    """The current (not superseded) artifact with this tag that counts as evidence, if any."""
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    return next((r for r in rows if _reviewed_by_other(r)), None), bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in DECISIONS.items():
        accepted, submitted = _evidence(db, f"HK-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"HK-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def external_dependencies(db: Session) -> list:

    return [{"key": k, "label": label, "gate": gate, "gateState": gate_state(db, gate)}
            for k, label, gate in EXTERNAL_DEPENDENCIES]


def template_content_hash(db: Session, template) -> str:
    """SHA-256 of the template's field structure + identifying metadata (computed; never stored)."""
    import hashlib
    import json

    from app.modules.payroll.models import ReportTemplateComponent, ReportTemplateComponentField

    fields = []
    for c in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == template.id):
        for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == c.id):
            fields.append([c.component_key, f.field_key, f.label, f.field_type, f.data_source_kind, f.source_column,
                           f.aggregation, bool(f.is_required), f.format_hint, f.enum_values])
    body = {"key": template.template_key, "type": template.report_type, "year": str(template.reporting_year),
            "version": template.version, "scope": template.document_scope, "fields": sorted(fields, key=str)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def year_key(kind: str, on: date) -> str:
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment

    return year_of_assessment(on) if kind == "YA" else str(on.year)


def _next_year_key(kind: str, on: date) -> str:
    return year_key(kind, date(on.year + 1, on.month, min(on.day, 28)))


def _reviewed_by_other(artifact) -> bool:
    return bool(artifact is not None and artifact.reviewer_id and artifact.file_path is not None
                and artifact.reviewer_id != artifact.created_by_id)


# ── report templates ────────────────────────────────────────────────────

def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    from app.modules.payroll.models import SourceArtifact

    if template.jurisdiction_country != HK:
        return None
    if not template.source_document_id:
        return (f"Hong Kong template {template.template_key} v{template.version} has no source evidence — link the "
                "official source document (a SourceArtifact) before activation.")
    artifact = db.get(SourceArtifact, template.source_document_id)
    if not _reviewed_by_other(artifact):
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has not been "
                "reviewed by a Super Admin other than its uploader (an uploaded document is required).")
    # Same source rule as statutory values: hashed, current, and not itself flagged unverified.
    if not artifact.checksum_sha256:
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has no SHA-256 "
                "— re-upload the official document so its hash is recorded.")
    if artifact.superseded_by_id:
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} has been "
                "superseded — link the current version of the document.")
    if "[UNVERIFIED" in (artifact.title or ""):
        return (f"The source evidence of Hong Kong template {template.template_key} v{template.version} is marked "
                "UNVERIFIED — link a verified official source.")
    if not template.approved_by_id:
        return (f"Hong Kong template {template.template_key} v{template.version} has no recorded approval — "
                "approve it (four-eyes) before activation.")
    if actor_id is not None and actor_id == template.approved_by_id:
        return (f"Hong Kong template {template.template_key} v{template.version} must be activated by a Super Admin "
                "other than its approver.")
    return None


def template_coverage(db: Session, on: Optional[date] = None) -> list:
    from app.modules.payroll.models import ReportTemplate

    on = on or date.today()
    rows = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == HK).all()
    out = []
    for report_type, kind in REPORT_TYPES.items():
        for label, key in (("current", year_key(kind, on)), ("next", _next_year_key(kind, on))):
            versions = [t for t in rows if t.report_type == report_type and str(t.reporting_year) == key]
            active = [t for t in versions if t.status == "Active"]
            out.append({"reportType": report_type, "yearKind": kind, "period": label, "yearKey": key,
                        "versions": [{"id": t.id, "version": t.version, "status": t.status,
                                      "sourceDocumentId": t.source_document_id,
                                      "approvedById": t.approved_by_id,
                                      "contentHash": template_content_hash(db, t)} for t in versions],
                        "active": active[0].id if active else None,
                        "state": "ACTIVE" if active else ("DRAFT" if versions else "MISSING")})
    return out


def compare_report_templates(db: Session, from_id: int, to_id: int) -> dict:
    """Read-only diff of two Hong Kong templates (any statuses / years)."""
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField

    a, b = db.get(ReportTemplate, from_id), db.get(ReportTemplate, to_id)
    for tid, t in ((from_id, a), (to_id, b)):
        if t is None:
            raise NotFoundException("ReportTemplate", tid)
        if t.jurisdiction_country != HK:
            raise BadRequestException(f"template #{tid} is not a Hong Kong template")

    def fields(t):
        out = {}
        for c in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == t.id):
            for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == c.id):
                out[f"{c.component_key}.{f.field_key}"] = {
                    "component": c.component_key, "label": f.label, "type": f.field_type, "sourceKind": f.data_source_kind,
                    "sourceColumn": f.source_column, "aggregation": f.aggregation, "required": bool(f.is_required),
                    "format": f.format_hint, "enum": f.enum_values}
        return out

    fa, fb = fields(a), fields(b)
    changed = []
    for k in sorted(set(fa) & set(fb)):
        diffs = {attr: {"from": fa[k][attr], "to": fb[k][attr]} for attr in fa[k] if fa[k][attr] != fb[k][attr]}
        if diffs:
            changed.append({"field": k, "changes": diffs})
    meta_attrs = ("template_key", "report_type", "reporting_year", "version", "status", "effective_from", "effective_to",
                  "source_document_id", "source_references", "regulatory_authority", "document_scope")
    meta = {m: {"from": str(getattr(a, m)), "to": str(getattr(b, m))} for m in meta_attrs if getattr(a, m) != getattr(b, m)}
    return {"from": {"id": a.id, "key": a.template_key, "version": a.version, "year": a.reporting_year, "status": a.status,
                     "contentHash": template_content_hash(db, a)},
            "to": {"id": b.id, "key": b.template_key, "version": b.version, "year": b.reporting_year, "status": b.status,
                   "contentHash": template_content_hash(db, b)},
            "sameReportType": a.report_type == b.report_type,
            "added": sorted(set(fb) - set(fa)), "removed": sorted(set(fa) - set(fb)), "changed": changed,
            "metadata": meta, "identical": not (set(fa) ^ set(fb)) and not changed}


# ── activation readiness + registry ─────────────────────────────────────

def activation_readiness(db: Session, as_of: Optional[date] = None) -> dict:
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import ReportTemplate, SourceArtifact
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    as_of = as_of or date.today()
    reqs = []
    for g in GATES:
        state = gate_state(db, g)
        reqs.append({"key": f"GATE_{g}", "label": f"{g} evidence accepted (HK-GATE-{g})", "met": state == "PASS",
                     "detail": state})
    _rates, _slabs, pack = resolve_tax_configuration(db, HK, payroll_date=as_of)
    reqs.append({"key": "ACTIVE_PACK", "label": "an Active HK rule pack in force today", "met": pack is not None,
                 "detail": f"{pack.pack_id} v{pack.version}" if pack else f"none in force on {as_of}"})
    if pack is not None:
        check = pack_golden_check(db, pack)
        ok = bool(check["casesInWindow"]) and not check["failures"]
        reqs.append({"key": "GOLDEN", "label": "the in-force pack reproduces its golden vectors", "met": ok,
                     "detail": f"{check['casesInWindow'] - len(check['failures'])}/{check['casesInWindow']} pass"})
    else:
        reqs.append({"key": "GOLDEN", "label": "the in-force pack reproduces its golden vectors", "met": False,
                     "detail": "no pack in force"})
    prod, prod_submitted = _evidence(db, PRODUCTION_EVIDENCE_TAG)
    reqs.append({"key": "PRODUCTION_VERIFICATION",
                 "label": f"production read-only verification and restore rehearsal recorded ({PRODUCTION_EVIDENCE_TAG})",
                 "met": prod is not None,
                 "detail": "PASS" if prod else ("SUBMITTED" if prod_submitted else "EVIDENCE_REQUIRED")})
    for cov in template_coverage(db, as_of):
        if cov["period"] != "current":
            continue
        tid = cov["active"]
        sourced = approved = False
        if tid:
            t = db.get(ReportTemplate, tid)
            sourced = _reviewed_by_other(db.get(SourceArtifact, t.source_document_id) if t.source_document_id else None)
            # defence in depth: an Active template must carry an independent approval even if
            # its status was set outside the governed transition
            approved = bool(t.approved_by_id) and t.approved_by_id != t.updated_by_id
        met = bool(tid) and sourced and approved
        detail = ("ACTIVE + sourced + independently approved" if met else
                  "no Active template" if not tid else
                  "source evidence missing" if not sourced else "independent approval missing")
        reqs.append({"key": f"TEMPLATE_{cov['reportType']}",
                     "label": f"{cov['reportType'][3:].replace('_', ' ')} {cov['yearKey']}: an Active template with "
                              "reviewed source evidence and an independent approval",
                     "met": met, "detail": detail})
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == HK).first()
    unmet = [r for r in reqs if not r["met"]]
    return {"asOf": as_of.isoformat(), "registry": registry.availability if registry else None,
            "requirements": reqs, "met": len(reqs) - len(unmet), "total": len(reqs),
            "canOpen": not unmet and registry is not None and registry.availability == REGISTRY_CLOSED}




def transition_hk_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """The owner's Hong Kong PLANNED <-> AVAILABLE step (shared
    transition_service_registry): AVAILABLE needs every activation-readiness
    requirement met (every gate, decision, pack, golden check and template)."""
    def readiness():
        ready = activation_readiness(db, as_of)
        return ([r for r in ready["requirements"] if not r["met"]],
                {r["key"]: r["detail"] for r in ready["requirements"]})

    return service.transition_service_registry(
        db, HK, target, reason, actor_id, label="Hong Kong", readiness=readiness,
        invalid_target_message=lambda t: f"Hong Kong availability can only be {REGISTRY_OPEN} or {REGISTRY_CLOSED}.",
        missing_row_message="There is no Hong Kong registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Hong Kong is {a}; only PLANNED moves to AVAILABLE.")


# ══════════════════════════════════════════════════════════════════════════
# (was hk_control.py)
# ══════════════════════════════════════════════════════════════════════════

_CONTROL_SPEC = "ZP-HK-ENG-001 production readiness"
IRD_FORMS = ("BIR56A", "IR56B", "IR56E", "IR56F", "IR56G")


# Transaction-scoped advisory-lock keys ("HK" + n) for transitions that INSERT
# rows, which row locks cannot serialize (there may be no row to lock yet).
_LOCK_IRD_SOFTWARE_APPROVAL = 0x484B0001
_LOCK_EMPF_CONFIGURATION = 0x484B0002


def _serialize(db, key: int) -> None:
    """Serialize a short critical section across sessions (PostgreSQL
    pg_advisory_xact_lock; released at commit / rollback). SQLite already
    serializes writers, so nothing is needed there."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def _control_audit(db, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None, commit=True):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     legal_reference=_CONTROL_SPEC, old_value=old, new_value=new, reason=reason, auto_commit=commit)




def _date(value, what):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BadRequestException(f"{what} must be a date (YYYY-MM-DD)")


IRD_APPROVAL_TAG = "HK-IRD-SOFTWARE-APPROVAL"
EMPF_CERTIFICATION_TAG = "HK-EMPF-CERTIFICATION"


def _reviewed_artifact(db, artifact_id, what, tag) -> SourceArtifact:
    """An uploaded document, filed under its evidence tag (form number), not
    superseded, reviewed by a Super Admin other than its uploader — the same
    evidence rule as the gates. The tag stops an unrelated reviewed document
    (e.g. a gate package) being recorded as an IRD approval or eMPF certification."""
    art = db.get(SourceArtifact, artifact_id) if artifact_id else None
    if art is None:
        raise BadRequestException(f"{what}: the document must be uploaded to Source Evidence first")
    if not (art.form_number or "").startswith(tag):
        raise BadRequestException(f"{what}: upload it to Source Evidence with form / tag {tag}")
    if art.superseded_by_id:
        raise BadRequestException(f"{what}: this document has been superseded — use the current version")
    if not (art.file_path and art.checksum_sha256):
        raise BadRequestException(f"{what}: the document has no stored file / SHA-256")
    if not art.reviewer_id or art.reviewer_id == art.created_by_id:
        raise BadRequestException(f"{what}: the document must be reviewed by a Super Admin other than its uploader")
    return art


# ── IRD software approval register ──────────────────────────────────────

SOFTWARE_TRANSITIONS = {
    "NOT_APPLIED": ("APPLICATION_PREPARED",),
    "APPLICATION_PREPARED": ("APPLICATION_SUBMITTED", "NOT_APPLIED"),
    "APPLICATION_SUBMITTED": ("TEST_DATA_SUBMITTED", "REQUIRES_REAPPLICATION"),
    "TEST_DATA_SUBMITTED": ("APPROVAL_RECEIVED", "REQUIRES_REAPPLICATION"),
    "APPROVAL_RECEIVED": ("APPROVAL_EXPIRED", "APPROVAL_REVOKED"),
    "APPROVAL_EXPIRED": ("REQUIRES_REAPPLICATION",),
    "APPROVAL_REVOKED": ("REQUIRES_REAPPLICATION",),
    "REQUIRES_REAPPLICATION": ("APPLICATION_PREPARED",),
}


def _software_row(db, lock: bool = False) -> Optional[HongKongIrdSoftwareApproval]:
    q = db.query(HongKongIrdSoftwareApproval).order_by(HongKongIrdSoftwareApproval.id.desc())
    return (q.with_for_update() if lock else q).first()


def _effective_software_status(row, on: date) -> str:
    if row is None:
        return "NOT_APPLIED"
    if row.status == "APPROVAL_RECEIVED" and row.expires_on and on > row.expires_on:
        return "APPROVAL_EXPIRED"                                # expiry is never ignored, even before it is recorded
    return row.status


def software_approval(db: Session, on: Optional[date] = None) -> dict:
    on = on or date.today()
    row = _software_row(db)
    status = _effective_software_status(row, on)
    base = {"status": status, "recordedStatus": row.status if row else "NOT_APPLIED", "allowedNext": list(SOFTWARE_TRANSITIONS[
        row.status if row else "NOT_APPLIED"]), "forms": list(IRD_FORMS),
        "dataFileSubmissionPermitted": status == "APPROVAL_RECEIVED",
        "notice": ("Internal validation of the IRD payload is NOT IRD approval. ONLINE / MIXED mode submission of a "
                   "Zoiko data file is refused until the IRD's approval is recorded here from its own letter.")}
    if row is None:
        return {**base, "id": None}
    return {**base, "id": row.id, "formsCovered": row.forms_covered or [], "specificationVersion": row.specification_version,
            "applicationReference": row.application_reference, "applicationSubmittedOn": _iso(row.application_submitted_on),
            "testDataSubmittedOn": _iso(row.test_data_submitted_on), "approvalReference": row.approval_reference,
            "approvalReceivedOn": _iso(row.approval_received_on), "expiresOn": _iso(row.expires_on),
            "approvalDocumentId": row.approval_document_id, "documentSha256": row.document_sha256,
            "reviewerId": row.reviewer_id, "notes": row.notes, "createdById": row.created_by_id}


def transition_software_approval(db: Session, target: str, data: dict, actor_id: Optional[int]) -> dict:
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("a reason is required")
    _serialize(db, _LOCK_IRD_SOFTWARE_APPROVAL)               # incl. the row-inserting (re)application
    row = _software_row(db, lock=True)
    current = row.status if row else "NOT_APPLIED"
    if target not in SOFTWARE_TRANSITIONS.get(current, ()):
        raise BadRequestException(f"the IRD software approval cannot move from {current} to {target}")
    old = software_approval(db)
    if target == "APPLICATION_PREPARED":
        forms = data.get("formsCovered") or []
        if not forms or any(f not in IRD_FORMS for f in forms):
            raise BadRequestException("formsCovered must list the forms applied for: " + ", ".join(IRD_FORMS))
        if not data.get("specificationVersion"):
            raise BadRequestException("the IRD specification version the output follows is required")
        # a (re)application starts a new register row; the history stays intact
        row = HongKongIrdSoftwareApproval(status=target, forms_covered=sorted(set(forms)),
                                     specification_version=data["specificationVersion"], created_by_id=actor_id)
        db.add(row)
    elif target == "NOT_APPLIED":
        row.status = target
    elif target == "APPLICATION_SUBMITTED":
        if not data.get("applicationReference"):
            raise BadRequestException("the IRD application reference is required")
        row.application_reference = data["applicationReference"]
        row.application_submitted_on = _date(data.get("applicationSubmittedOn"), "applicationSubmittedOn") or date.today()
        row.status = target
    elif target == "TEST_DATA_SUBMITTED":
        row.test_data_submitted_on = _date(data.get("testDataSubmittedOn"), "testDataSubmittedOn") or date.today()
        row.status = target
    elif target == "APPROVAL_RECEIVED":
        if not data.get("approvalReference"):
            raise BadRequestException("the IRD approval reference (from the IRD's approval letter) is required")
        art = _reviewed_artifact(db, data.get("approvalDocumentId"), "IRD approval letter", IRD_APPROVAL_TAG)
        received = _date(data.get("approvalReceivedOn"), "approvalReceivedOn")
        if not received or received > date.today():
            raise BadRequestException("approvalReceivedOn is required and cannot be in the future")
        expires = _date(data.get("expiresOn"), "expiresOn")
        if expires and expires < received:
            raise BadRequestException("expiresOn cannot be before approvalReceivedOn")
        if actor_id is not None and actor_id == row.created_by_id:
            raise BadRequestException("the approval must be recorded by a Super Admin other than the one who prepared the application")
        row.approval_reference, row.approval_received_on, row.expires_on = data["approvalReference"], received, expires
        row.approval_document_id, row.document_sha256, row.reviewer_id = art.id, art.checksum_sha256, actor_id
        row.status = target
    else:                                                       # APPROVAL_EXPIRED / APPROVAL_REVOKED / REQUIRES_REAPPLICATION
        row.status = target
    if data.get("notes"):
        row.notes = data["notes"]
    db.flush()
    _control_audit(db, actor_id, "status_change", "hk_ird_software_approval", row.id, old={"status": old["status"]},
           new={"status": target, "formsCovered": row.forms_covered, "approvalReference": row.approval_reference,
                "documentSha256": row.document_sha256, "expiresOn": _iso(row.expires_on)}, reason=reason)
    return software_approval(db)


def software_approval_refusal(db: Session, form_type: str, on: date) -> Optional[str]:
    """None when a Zoiko data file for ``form_type`` may be recorded as
    submitted on ``on`` (ONLINE / MIXED mode); otherwise the reason it may not."""
    row = _software_row(db)
    status = _effective_software_status(row, on)
    if status != "APPROVAL_RECEIVED":
        return (f"IRD software approval is {status}: a Zoiko data file cannot be recorded as submitted in ONLINE / "
                "MIXED mode. If the employer filed through its own channel, record INTERNAL_PREPARATION_ONLY.")
    if form_type not in (row.forms_covered or []):
        return f"the IRD software approval does not cover {form_type}"
    return None


# ── eMPF integration configuration ──────────────────────────────────────

EMPF_METHODS = ("EMPF_PORTAL_MANUAL", "EMPF_FILE_UPLOAD", "EMPF_API")
EMPF_ENVIRONMENTS = ("NOT_CONFIGURED", "TEST", "PRODUCTION")
EMPF_SECRET_STATUSES = ("NOT_CONFIGURED", "CONFIGURED_IN_SECRET_STORE")
_SECRETISH = re.compile(r"(://[^/\s]*:[^/\s]*@)|(password|passwd|secret|token|apikey|api_key|private[_ ]key|BEGIN )", re.I)


def empf_configurations(db: Session) -> dict:
    rows = db.query(HongKongEmpfConfiguration).order_by(HongKongEmpfConfiguration.version.desc()).all()
    active = next((r for r in rows if r.status == "ACTIVE"), None)
    return {"active": _empf_view(active) if active else None, "versions": [_empf_view(r) for r in rows],
            "methods": list(EMPF_METHODS), "environments": list(EMPF_ENVIRONMENTS),
            "secretStatuses": list(EMPF_SECRET_STATUSES),
            "notice": ("Statuses only — credentials, keys and certificates are held in the deployment secret store, "
                       "never here. Zoiko holds no certified eMPF interface (G2): every submission is made by the "
                       "employer through eMPF itself and recorded from its evidence.")}


def _empf_view(r: HongKongEmpfConfiguration) -> dict:
    return {"id": r.id, "version": r.version, "status": r.status, "submissionMethod": r.submission_method,
            "fileFormat": r.file_format, "formatVersion": r.format_version, "environment": r.environment,
            "endpointReference": r.endpoint_reference, "credentialStatus": r.credential_status,
            "certificateStatus": r.certificate_status, "certificationStatus": r.certification_status,
            "certificationEvidenceId": r.certification_evidence_id, "reason": r.reason,
            "createdById": r.created_by_id, "approvedById": r.approved_by_id, "activatedAt": _iso(r.activated_at)}


def create_empf_configuration(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    if not (data.get("reason") or "").strip():
        raise BadRequestException("a reason is required")
    method, env = data.get("submissionMethod"), data.get("environment")
    if method not in EMPF_METHODS:
        raise BadRequestException("submissionMethod must be one of " + ", ".join(EMPF_METHODS))
    if env not in EMPF_ENVIRONMENTS:
        raise BadRequestException("environment must be one of " + ", ".join(EMPF_ENVIRONMENTS))
    for k in ("credentialStatus", "certificateStatus"):
        if data.get(k, "NOT_CONFIGURED") not in EMPF_SECRET_STATUSES:
            raise BadRequestException(f"{k} must be one of " + ", ".join(EMPF_SECRET_STATUSES))
    for k in ("endpointReference", "fileFormat", "formatVersion", "reason"):
        if data.get(k) and _SECRETISH.search(str(data[k])):
            raise BadRequestException(f"{k} looks like it contains a secret — secrets are never stored in configuration")
    certification, evidence_id = "NOT_CERTIFIED", None
    if data.get("certificationEvidenceId"):
        art = _reviewed_artifact(db, data["certificationEvidenceId"], "eMPF certification evidence", EMPF_CERTIFICATION_TAG)
        certification, evidence_id = "CERTIFIED", art.id
    if method != "EMPF_PORTAL_MANUAL" and env == "PRODUCTION" and certification != "CERTIFIED":
        raise BadRequestException("an automated eMPF method in PRODUCTION needs reviewed eMPF certification evidence (G2)")
    _serialize(db, _LOCK_EMPF_CONFIGURATION)                  # next version number: no duplicate under concurrency
    last = db.query(HongKongEmpfConfiguration).order_by(HongKongEmpfConfiguration.version.desc()).first()
    row = HongKongEmpfConfiguration(version=(last.version + 1) if last else 1, status="DRAFT", submission_method=method,
                               file_format=data.get("fileFormat"), format_version=data.get("formatVersion"),
                               environment=env, endpoint_reference=data.get("endpointReference"),
                               credential_status=data.get("credentialStatus", "NOT_CONFIGURED"),
                               certificate_status=data.get("certificateStatus", "NOT_CONFIGURED"),
                               certification_status=certification, certification_evidence_id=evidence_id,
                               reason=data["reason"].strip(), created_by_id=actor_id)
    db.add(row)
    db.flush()
    _control_audit(db, actor_id, "create", "hk_empf_configuration", row.id, new=_empf_view(row), reason=row.reason)
    return _empf_view(row)


def activate_empf_configuration(db: Session, config_id: int, actor_id: Optional[int], reason: str) -> dict:
    # lock every version (id order) so two concurrent activations cannot both end ACTIVE
    db.query(HongKongEmpfConfiguration).order_by(HongKongEmpfConfiguration.id).with_for_update().all()
    row = db.get(HongKongEmpfConfiguration, config_id)
    if row is None:
        raise NotFoundException("eMPF configuration not found")
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT configuration can be activated (this one is {row.status})")
    if not (reason or "").strip():
        raise BadRequestException("a reason is required")
    if actor_id is None or actor_id == row.created_by_id:
        raise BadRequestException("the configuration must be activated by a Super Admin other than its maker")
    for prev in db.query(HongKongEmpfConfiguration).filter(HongKongEmpfConfiguration.status == "ACTIVE"):
        prev.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.activated_at = "ACTIVE", actor_id, datetime.utcnow()
    db.flush()
    _control_audit(db, actor_id, "activate", "hk_empf_configuration", row.id, old={"status": "DRAFT"},
           new={"status": "ACTIVE", "version": row.version}, reason=reason)
    return _empf_view(row)


# ── monitoring signals ──────────────────────────────────────────────────

def monitoring_signals(db: Session, as_of: Optional[date] = None) -> dict:
    """Platform-wide HK operational signals for monitoring / alerting — COUNTS
    only (no employee data). An alert rule fires when a signal with a
    threshold is above it; wiring these into the deployment's alerting is the
    PROD_MONITORING production procedure."""
    from datetime import timedelta

    from app.modules.payroll.models import (
        HongKongEmpfSubmission, HongKongIrdReportingCase, LegalHold, HongKongPayslipCorrection, HongKongTaxClearanceHold,
    )

    as_of = as_of or date.today()
    open_ird = ("DUE", "PREPARED", "VALIDATED")
    ird = db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.status.in_(open_ird))
    signals = [
        ("IRD_OVERDUE", "IRD returns / notifications past their due date and not filed",
         ird.filter(HongKongIrdReportingCase.due_date < as_of).count(), 0),
        ("IRD_DUE_30_DAYS", "IRD returns / notifications due within 30 days and not filed",
         ird.filter(HongKongIrdReportingCase.due_date >= as_of, HongKongIrdReportingCase.due_date <= as_of + timedelta(days=30)).count(), None),
        ("IRD_REJECTED", "IRD submissions recorded as rejected (awaiting re-preparation)",
         db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.status == "REJECTED").count(), 0),
        ("EMPF_PAST_CONTRIBUTION_DAY", "eMPF remittances not submitted after their contribution day",
         db.query(HongKongEmpfSubmission).filter(HongKongEmpfSubmission.status.in_(("PREPARED", "VALIDATED")),
                                            HongKongEmpfSubmission.contribution_day < as_of).count(), 0),
        ("EMPF_REJECTED_OR_PARTIAL", "eMPF remittances rejected or partially accepted",
         db.query(HongKongEmpfSubmission).filter(HongKongEmpfSubmission.status.in_(("REJECTED", "PARTIAL"))).count(), 0),
        ("IR56G_DEADLINE_PASSED", "IR56G departure cases past their filing deadline and not filed",
         db.query(HongKongTaxClearanceHold).filter(HongKongTaxClearanceHold.state.in_(("DEPARTURE_IDENTIFIED", "IR56G_DUE")),
                                              HongKongTaxClearanceHold.filing_deadline < as_of).count(), 0),
        ("IR56G_HOLDS_ACTIVE", "IR56G tax-clearance holds active (money held)",
         db.query(HongKongTaxClearanceHold).filter(HongKongTaxClearanceHold.state == "IR56G_FILED_HOLD_ACTIVE").count(), None),
        ("CORRECTIONS_AWAITING_APPROVAL", "payslip corrections awaiting a second approver",
         db.query(HongKongPayslipCorrection).filter(HongKongPayslipCorrection.status == "REQUESTED").count(), None),
        ("LEGAL_HOLDS_ACTIVE", "legal holds active (deletion blocked)",
         db.query(LegalHold).filter(LegalHold.status == "ACTIVE").count(), None),
    ]
    row = _software_row(db)
    expiring = bool(row and row.status == "APPROVAL_RECEIVED" and row.expires_on
                    and as_of <= row.expires_on <= as_of + timedelta(days=60))
    signals.append(("IRD_SOFTWARE_APPROVAL_EXPIRING", "IRD software approval expires within 60 days", int(expiring), 0))
    # Future statutory data: HK payroll fails closed from the first day of a
    # year of assessment no Active pack covers (no fallback to the previous
    # year). Warn 90 days ahead so the next year's pack is sourced, reviewed and
    # activated in time — never by creating or extending values here.
    from app.modules.payroll.models import JurisdictionPack

    next_ya = date(as_of.year if as_of < date(as_of.year, 4, 1) else as_of.year + 1, 4, 1)
    covered = (db.query(JurisdictionPack.id)
               .filter(JurisdictionPack.jurisdiction_country == "HK", JurisdictionPack.pack_type == "tax",
                       JurisdictionPack.status == "Active", JurisdictionPack.effective_from <= next_ya,
                       (JurisdictionPack.effective_to.is_(None)) | (JurisdictionPack.effective_to >= next_ya))
               .first() is not None)
    signals.append(("NEXT_YEAR_PACK_NOT_ACTIVE",
                    f"no Active statutory pack covers the next year of assessment from {next_ya.isoformat()} "
                    "(counted within 90 days of it; payroll will be refused from that date)",
                    int((next_ya - as_of).days <= 90 and not covered), 0))
    out = [{"key": k, "label": label, "value": v, "threshold": t, "alert": t is not None and v > t}
           for k, label, v, t in signals]
    return {"asOf": as_of.isoformat(), "signals": out, "alerts": sum(1 for x in out if x["alert"]),
            "notice": "Counts only. Alert delivery (paging / e-mail) is wired by the deployment — production procedure PROD_MONITORING."}


# ── production readiness center ─────────────────────────────────────────

GATE_OWNERS = {"G1": "HK payroll / statutory specialist", "G2": "IRD / eMPF (external) + engineering",
               "G3": "Payroll operations (parallel run)", "G4": "Engineering (technical certification)",
               "G5": "Security + privacy counsel", "G6": "Operations", "G7": "Product owner (launch authority)"}
PRODUCTION_PROCEDURES = (
    ("PROD_DB", "Production database migrated to the HK head and drift-checked", "Platform engineering"),
    ("PROD_SECRETS", "HK identity-token secret provisioned in the secret store (D-5)", "Platform engineering"),
    ("PROD_DEPLOY", "HK release deployed and the running revision verified", "Platform engineering"),
    ("PROD_BACKUP_RESTORE", "Backup taken and a restore rehearsal completed on a production snapshot", "Operations"),
    ("PROD_MONITORING", "HK monitoring signals and alerts wired (calculation blocks, filing deadlines, eMPF)", "Operations"),
)


def readiness_center(db: Session, as_of: Optional[date] = None) -> dict:

    as_of = as_of or date.today()
    readiness = activation_readiness(db, as_of)
    items = []

    def add(category, key, label, status, owner, evidence, next_action, blocker=None, due=None):
        items.append({"category": category, "key": key, "item": label, "status": status, "owner": owner,
                      "evidence": evidence, "nextAction": next_action, "dueDate": due,
                      "blockerReason": blocker if status in ("FAIL", "BLOCKED", "PENDING") else None})

    for r in readiness["requirements"]:
        k = r["key"]
        if k.startswith("GATE_"):
            g = k[5:]
            status = "PASS" if r["met"] else ("PENDING" if r["detail"] == "SUBMITTED" else "BLOCKED")
            add("Certification gates", k, r["label"], status, GATE_OWNERS[g], f"HK-GATE-{g} ({r['detail']})",
                "none" if r["met"] else f"upload the {g} evidence package and have a second Super Admin review it",
                None if r["met"] else f"{g} evidence not accepted — external / owner action required")
        elif k.startswith("TEMPLATE_"):
            add("Report templates", k, r["label"], "PASS" if r["met"] else "FAIL", "Compliance (Super Admin)",
                r["detail"], "none" if r["met"] else "attach reviewed source evidence; approve and activate (four-eyes)",
                None if r["met"] else r["detail"])
        else:
            add("Statutory configuration" if k in ("ACTIVE_PACK", "GOLDEN") else "Production verification", k, r["label"],
                "PASS" if r["met"] else "FAIL" if k in ("ACTIVE_PACK", "GOLDEN") else "BLOCKED",
                "Compliance (Super Admin)" if k in ("ACTIVE_PACK", "GOLDEN") else "Operations", r["detail"],
                "none" if r["met"] else "see the activation runbook", None if r["met"] else r["detail"])
    # The activation guard refuses any pack with a value that is not SOURCED;
    # show the same count here so the blocker is visible before an attempt.

    pending, open_versions = 0, []
    for v in versions(db, as_of):
        if v["versionState"] in ("SUPERSEDED", "RETIRED", "PAST_ACTIVE"):
            continue
        cfg = domains(db, v["id"])
        n = sum(1 for d in cfg["domains"] for r in d["rows"] if r["status"] != "SOURCED") + len(cfg["unmapped"])
        pending += n
        open_versions.append(f"{v['packId']} v{v['version']}: {n}")
    add("Statutory configuration", "VALUES_SOURCE_VERIFIED",
        "every value of each open version is source-verified (no UNVERIFIED — G1 / SOURCE_HASH_REQUIRED)",
        "PASS" if pending == 0 else "BLOCKED", "HK specialist (G1) + Compliance (Super Admin)",
        "; ".join(open_versions) or "no open version",
        "none" if pending == 0 else "record each specialist confirmation with a reviewed, hashed source (governed edit, Draft version)",
        None if pending == 0 else f"{pending} value(s) not source-verified — activation is refused")
    sw = software_approval(db, as_of)
    add("IRD", "IRD_SOFTWARE_APPROVAL", "IRD software approval for the employer's-return data file",
        "PASS" if sw["status"] == "APPROVAL_RECEIVED" else "BLOCKED", "Engineering + IRD (external)",
        sw.get("approvalReference") or sw["status"],
        "none" if sw["status"] == "APPROVAL_RECEIVED" else "apply to the IRD with the specification and test data (G2)",
        None if sw["status"] == "APPROVAL_RECEIVED" else
        f"{sw['status']} — until approved, returns can only be recorded as INTERNAL_PREPARATION_ONLY")
    empf = empf_configurations(db)["active"]
    if empf is None:
        add("eMPF", "EMPF_CONFIGURATION", "eMPF integration configuration (active version)", "PENDING",
            "Operations", "none", "create and activate the eMPF configuration (maker + approver)",
            "no active eMPF configuration")
    else:
        add("eMPF", "EMPF_CONFIGURATION", "eMPF integration configuration (active version)", "PASS", "Operations",
            f"v{empf['version']} {empf['submissionMethod']} / {empf['environment']}", "none")
    certified = bool(empf and empf["certificationStatus"] == "CERTIFIED")
    manual = bool(empf and empf["submissionMethod"] == "EMPF_PORTAL_MANUAL")
    add("eMPF", "EMPF_CERTIFICATION", "eMPF interface certification",
        "PASS" if certified else "NOT_APPLICABLE" if manual else "BLOCKED", "eMPF (external) + engineering",
        "certified" if certified else "manual portal submission — no interface to certify" if manual else "NOT_CERTIFIED",
        "none" if certified or manual else "decide D-1, then complete eMPF onboarding (G2)",
        None if certified or manual else "no certified eMPF interface")
    for d in owner_decisions(db):
        status = "PASS" if d["state"] == "RECORDED" else "PENDING" if d["state"] == "SUBMITTED" else (
            "BLOCKED" if d["blocksLaunch"] else "NOT_APPLICABLE")
        add("Owner decisions", f"DECISION_{d['key']}", f"{d['key']} {d['label']}", status, "Product owner",
            d["evidenceTag"], "none" if status in ("PASS", "NOT_APPLICABLE") else "record the decision document and its review",
            None if status in ("PASS", "NOT_APPLICABLE") else f"{d['key']} {d['state']}")
    ret = retention_service.retention_policies(db, HK)
    approved = sum(1 for c in ret["categories"] if c["state"] == "APPROVED")
    add("Privacy (PDPO)", "RETENTION", f"Retention periods approved ({approved}/{len(ret['categories'])} categories)",
        "PASS" if approved == len(ret["categories"]) else "BLOCKED", "Privacy counsel + product owner",
        f"D-2 {ret['decisions']['D-2']}, D-3 {ret['decisions']['D-3']}",
        "record D-2 / D-3, then propose and approve each category",
        None if approved == len(ret["categories"]) else "retention undecided — purge blocked")
    prod_ok = next((r["met"] for r in readiness["requirements"] if r["key"] == "PRODUCTION_VERIFICATION"), False)
    for key, label, owner in PRODUCTION_PROCEDURES:
        add("Production procedures", key, label, "PASS" if prod_ok else "PENDING", owner,
            PRODUCTION_EVIDENCE_TAG, "none" if prod_ok else "perform it and record it in the production-verification evidence",
            None if prod_ok else "no production evidence recorded")
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("PASS", "FAIL", "PENDING", "BLOCKED", "NOT_APPLICABLE")}
    ready = counts["FAIL"] == counts["PENDING"] == counts["BLOCKED"] == 0
    return {"asOf": as_of.isoformat(), "registry": readiness["registry"], "counts": counts, "total": len(items),
            "productionReady": ready, "items": items,
            "classification": "PRODUCTION READY" if ready else "NOT PRODUCTION READY — see BLOCKED / FAIL / PENDING items"}


# ══════════════════════════════════════════════════════════════════════════
# (was hk_corrections.py)
# ══════════════════════════════════════════════════════════════════════════

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
    return bool((getattr(item, "hk_calculation_trace", None) or {}).get("correction"))


def correction_for_run(db: Session, run: PayrollRun) -> Optional[HongKongPayslipCorrection]:
    return (db.query(HongKongPayslipCorrection)
            .filter(HongKongPayslipCorrection.correction_run_id == run.id,
                    HongKongPayslipCorrection.organization_id == run.organization_id).first())


def _correction(db: Session, organization_id: int, correction_id: int) -> HongKongPayslipCorrection:
    row = (db.query(HongKongPayslipCorrection)
           .filter(HongKongPayslipCorrection.id == correction_id, HongKongPayslipCorrection.organization_id == organization_id).first())
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
                       actor_id: Optional[int]) -> HongKongPayslipCorrection:
    from app.modules.payroll import service

    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("a Hong Kong payroll correction needs a reason")
    item = (db.query(PayslipItem)
            .filter(PayslipItem.id == payslip_id, PayslipItem.organization_id == organization_id).first())
    if item is None:
        raise NotFoundException("Payslip", payslip_id)
    if (item.country_code or "").upper() != HK or not item.hk_calculation_trace:
        raise BadRequestException("linked corrections here are for Hong Kong payslips only")
    if is_delta(item):
        raise BadRequestException("correct the original payslip, not a correction delta")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).with_for_update().one()
    if run.status not in COMMITTED_RUN_STATUSES:
        raise BadRequestException("only a committed (approved) payslip is corrected by a linked adjustment — "
                                  "recalculate a Draft / Review payslip in place")
    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == item.employee_id, PayrollEmployee.organization_id == organization_id)
                .with_for_update().one())
    from app.modules.payroll.service import _normalize_country

    if _normalize_country(employee.country_code or "") != HK:
        raise _conflict("the employee is no longer a Hong Kong employee — recalculating would use another country's "
                        "rules; a cross-jurisdiction change is not a linked adjustment")
    open_row = (db.query(HongKongPayslipCorrection)
                .filter(HongKongPayslipCorrection.organization_id == organization_id,
                        HongKongPayslipCorrection.original_payslip_id == item.id,
                        HongKongPayslipCorrection.status == "REQUESTED").first())
    if open_row is not None:
        raise _conflict(f"correction #{open_row.id} of payslip {item.id} is still awaiting approval — approve or "
                        "reject it before requesting another")
    trace = item.hk_calculation_trace
    coverage = ((trace.get("mpf") or {}).get("coverage") or {}).get("status")
    if coverage == "PENDING_60_DAY":
        raise _conflict("this payslip's MPF was accruing under the 60-day rule and is caught up by a later payslip — "
                        "correcting a pending period needs Hong Kong specialist review (G1); not automated")
    for later in (db.query(PayslipItem)
                  .filter(PayslipItem.organization_id == organization_id, PayslipItem.employee_id == employee.id,
                          PayslipItem.id != item.id, PayslipItem.hk_calculation_trace.isnot(None)).all()):
        caught = {c.get("payslipId") for c in ((later.hk_calculation_trace or {}).get("mpf") or {}).get("catchUp") or []}
        if item.id in caught:
            raise _conflict(f"payslip {later.id} caught up this period's MPF — correcting it would leave that catch-up "
                            "stale; needs Hong Kong specialist review (G1); not automated")

    chain = [(c, db.get(PayslipItem, c.delta_payslip_id)) for c in
             db.query(HongKongPayslipCorrection).filter(HongKongPayslipCorrection.original_payslip_id == item.id,
                                                   HongKongPayslipCorrection.status == "APPROVED")
             .order_by(HongKongPayslipCorrection.sequence).all()]
    effective = metrics(trace)
    effective_cols = {c: dec(getattr(item, c, None)) for c in DELTA_COLUMNS}
    for _c, delta_item in chain:
        for key, value in metrics(delta_item.hk_calculation_trace).items():
            effective[key] = effective.get(key, ZERO) + value
        for col in DELTA_COLUMNS:
            effective_cols[col] += dec(getattr(delta_item, col, None))

    after_values = _hk_frozen_recompute(db, run, employee, item, organization_id)
    after_trace = after_values.get("hk_calculation_trace") or {}
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

    sequence = db.query(HongKongPayslipCorrection).filter(HongKongPayslipCorrection.original_payslip_id == item.id).count() + 1
    now = datetime.utcnow().replace(microsecond=0)
    correction = HongKongPayslipCorrection(
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
        hk_calculation_trace=_delta_trace(trace, after_trace, delta, meta),
        notes=f"Correction delta of payslip {item.id} (Hong Kong correction #{correction.id})", tds=ZERO,
        **col_delta)
    db.add(delta_item)
    db.flush()
    correction.correction_run_id, correction.delta_payslip_id = corr_run.id, delta_item.id
    _update_run_totals(db, corr_run)
    _audit(db, actor_id, "create", "hk_payslip_correction", correction.id,
                      old={"originalPayslipId": item.id, "before": correction.before},
                      new={"after": correction.after, "delta": correction.delta, "correctionRunId": corr_run.id},
                      reason=reason, commit=False)
    db.commit()
    db.refresh(correction)
    return correction


def _open_hold(db: Session, organization_id: int, employee_id: int) -> Optional[HongKongTaxClearanceHold]:
    return (db.query(HongKongTaxClearanceHold)
            .filter(HongKongTaxClearanceHold.organization_id == organization_id, HongKongTaxClearanceHold.employee_id == employee_id,
                    HongKongTaxClearanceHold.state.notin_(("INACTIVE", "CASE_CLOSED")))
            .order_by(HongKongTaxClearanceHold.id.desc()).first())


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
    service.require_four_eyes(correction.requested_by_id, actor_id, "Approving a Hong Kong payroll correction")
    original = db.get(PayslipItem, correction.original_payslip_id)
    if original is None or canonical_hash(original.hk_calculation_trace) != correction.original_trace_hash:
        raise _conflict("the original payslip changed after the correction was requested — reject and request it again")
    correction.status, correction.approved_by_id = "APPROVED", actor_id
    correction.approved_at = datetime.utcnow().replace(microsecond=0)
    correction.consequences = apply_consequences(db, correction, actor_id)
    _audit(db, actor_id, "status_change", "hk_payslip_correction", correction.id,
                      old={"status": "REQUESTED"}, new={"status": "APPROVED", "consequences": correction.consequences},
                      reason=correction.reason, commit=False)


def apply_consequences(db: Session, correction: HongKongPayslipCorrection, actor_id: Optional[int]) -> dict:
    """Every Hong Kong statutory consequence of an approved correction. Filed
    evidence is never edited: a filed return gets a linked AMENDMENT case; an
    unfiled one is sent back for regeneration; an unsubmitted eMPF batch is
    superseded; results built on the period are listed for review."""
    org = correction.organization_id
    original = db.get(PayslipItem, correction.original_payslip_id)
    ot = original.hk_calculation_trace or {}
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
        cases = (db.query(HongKongIrdReportingCase)
                 .filter(HongKongIrdReportingCase.organization_id == org, HongKongIrdReportingCase.year_of_assessment == ya,
                         HongKongIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
                 .filter((HongKongIrdReportingCase.employee_id == correction.employee_id)
                         | (HongKongIrdReportingCase.form_type == "BIR56A")).all())
        for case in cases:
            if case.form_type == "IR56E":
                continue                                   # commencement: reports no income
            if case.status in hk_ird.FILED_STATES and open_replacement(db, case) is not None:
                continue                                   # its open replacement (also in `cases`) carries the change
            entry = {"caseId": case.id, "form": case.form_type, "yearOfAssessment": ya}
            if case.status in hk_ird.FILED_STATES:
                if case.form_type == "BIR56A":
                    out["ird"].append({**entry, "action": "COVER_ALREADY_FILED",
                                       "note": "submit the amended IR56B under the IRD's amendment procedure (G2)"})
                    continue
                amendment = amend_ird_case(db, org, case.id, note, actor_id, commit=False)
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
        subs = (db.query(HongKongEmpfSubmission)
                .filter(HongKongEmpfSubmission.organization_id == org, HongKongEmpfSubmission.contribution_period == month,
                        HongKongEmpfSubmission.status != "AMENDED").all())
        submitted = [s.id for s in subs if s.status in SUBMITTED_EMPF_STATES]
        for sub in subs:
            if sub.status in SUBMITTED_EMPF_STATES:
                continue
            previous = sub.status
            sub.status = "AMENDED"
            sub.validation_errors = list(sub.validation_errors or []) + [f"superseded by {note} — prepare {month} again"]
            _audit(db, actor_id, "status_change", "hk_empf_submission", sub.id, old={"status": previous},
                              new={"status": "AMENDED", "supersededBy": f"hk_payslip_correction:{correction.id}"},
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
        for snap in (db.query(HongKongAverageWageSnapshot)
                     .filter(HongKongAverageWageSnapshot.organization_id == org,
                             HongKongAverageWageSnapshot.employee_id == correction.employee_id).all()):
            if str(snap.lookback_start) <= str(period_end) and str(snap.lookback_end) >= str(period_start):
                out["averageWage"].append({"snapshotId": snap.id, "benefit": snap.benefit_type,
                                           "action": "RECALCULATE_AVERAGE_WAGE"})
    for result in (db.query(HongKongTerminationResult)
                   .filter(HongKongTerminationResult.organization_id == org,
                           HongKongTerminationResult.employee_id == correction.employee_id,
                           HongKongTerminationResult.status.in_(("CALCULATED", "APPROVED"))).all()):
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


def approve_correction(db: Session, organization_id: int, correction_id: int, actor_id: Optional[int]) -> HongKongPayslipCorrection:
    """Moves the correction run through the SHARED lifecycle to APPROVED (the
    four-eyes check and the consequences run in its HK hook)."""
    from app.modules.payroll import service

    correction = _correction(db, organization_id, correction_id)
    if correction.status != "REQUESTED":
        raise _conflict(f"correction #{correction.id} is {correction.status}")
    service.require_four_eyes(correction.requested_by_id, actor_id, "Approving a Hong Kong payroll correction")
    run = db.get(PayrollRun, correction.correction_run_id)
    while run.status != PayrollStatus.APPROVED:
        run = service.advance_payroll_run_status(db, run.id, actor_id, organization_id)
    db.refresh(correction)
    return correction


def reject_correction(db: Session, organization_id: int, correction_id: int, reason: str,
                      actor_id: Optional[int]) -> HongKongPayslipCorrection:
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
    _audit(db, actor_id, "status_change", "hk_payslip_correction", correction.id,
                      old={"status": "REQUESTED"}, new={"status": "REJECTED", "discarded": discarded},
                      reason=reason, commit=False)
    db.commit()
    db.refresh(correction)
    return correction


def list_corrections(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    q = db.query(HongKongPayslipCorrection).filter(HongKongPayslipCorrection.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(HongKongPayslipCorrection.employee_id == employee_id)
    return [serialize(c) for c in q.order_by(HongKongPayslipCorrection.id.desc()).all()]


def serialize(c: HongKongPayslipCorrection) -> dict:
    delta = c.delta or {}
    return {"id": c.id, "employeeId": c.employee_id, "originalPayslipId": c.original_payslip_id,
            "originalRunId": c.original_run_id, "correctionRunId": c.correction_run_id,
            "deltaPayslipId": c.delta_payslip_id, "sequence": c.sequence, "status": c.status, "reason": c.reason,
            "netPayDelta": delta.get("col:net_pay"), "grossPayDelta": delta.get("col:gross_pay"),
            "employeeMpfDelta": delta.get("col:employee_pension"), "employerMpfDelta": delta.get("col:employer_pension"),
            "delta": delta, "before": c.before, "after": c.after, "warnings": c.warnings or [],
            "consequences": c.consequences, "requestedById": c.requested_by_id,
            "requestedAt": _iso(c.requested_at), "approvedById": c.approved_by_id,
            "approvedAt": _iso(c.approved_at), "rejectedById": c.rejected_by_id,
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


# ══════════════════════════════════════════════════════════════════════════
# (was hk_ird_schema.py)
# ══════════════════════════════════════════════════════════════════════════

FORMS = ("BIR56A", "IR56B", "IR56E", "IR56F", "IR56G")
# Engineering limit (not statutory): an annual return for a large employer is
# far below this; anything larger is refused before parsing (resource guard).
MAX_XML_BYTES = 20 * 1024 * 1024
AGENCY = "Inland Revenue Department"


def _form_number(form: str, ya: str) -> str:
    return f"HK-IRD-SCHEMA:{form}:{ya}"


def registered_schema(db: Session, form: str, ya: str) -> Optional[SourceArtifact]:
    return (db.query(SourceArtifact)
            .filter(SourceArtifact.form_number == _form_number(form, ya), SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).first())


def register_schema(db: Session, form: str, ya: str, path: str, actor_id: Optional[int] = None,
                    source_url: Optional[str] = None) -> SourceArtifact:
    form = (form or "").upper()
    if form not in FORMS:
        raise BadRequestException(f"unknown IRD form {form!r} (expected one of {', '.join(FORMS)})")
    file = Path(path)
    if not file.is_file():
        raise BadRequestException(f"schema file not found: {path}")
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    current = registered_schema(db, form, ya)
    if current is not None and current.checksum_sha256 == digest:
        return current                                   # idempotent: same file already registered
    artifact = SourceArtifact(agency=AGENCY, title=f"IRD electronic schema — {form} YA {ya} (registered, unreviewed)",
                              form_number=_form_number(form, ya), source_url=source_url, checksum_sha256=digest,
                              file_path=str(file), original_filename=file.name, created_by_id=actor_id)
    db.add(artifact)
    db.flush()
    if current is not None:
        current.superseded_by_id = artifact.id           # a changed schema supersedes; history is kept
    db.commit()
    return artifact


def _parser():
    """Hardened XML parser: no entity expansion, no network / external DTD
    access (XXE / entity-expansion safe) for schema files and documents."""
    from lxml import etree

    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def _reviewed(art: SourceArtifact) -> bool:
    """Four-eyes: reviewed by someone other than the registrant (the HK-GATE rule)."""
    return bool(art.reviewer_id) and art.reviewer_id != art.created_by_id


def readiness(db: Session, ya: str) -> list:
    out = []
    for form in FORMS:
        art = registered_schema(db, form, ya)
        out.append({"form": form, "yearOfAssessment": ya,
                    "status": "EXTERNAL SCHEMA REQUIRED" if art is None else
                    ("REGISTERED — REVIEWED" if _reviewed(art) else "REGISTERED — AWAITING REVIEW"),
                    "sha256": None if art is None else art.checksum_sha256,
                    "artifactId": None if art is None else art.id})
    return out


def validate(xml_bytes: bytes, schema_path: str) -> list:
    """Validation errors of an XML document against an XSD ([] = valid)."""
    from lxml import etree

    if len(xml_bytes or b"") > MAX_XML_BYTES:
        return [f"document exceeds the {MAX_XML_BYTES // (1024 * 1024)} MB limit — refused before parsing"]
    parser = _parser()
    schema = etree.XMLSchema(etree.parse(schema_path, parser))
    try:
        doc = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as exc:
        return [f"not well-formed XML: {exc}"]
    docinfo = doc.getroottree().docinfo
    if docinfo.internalDTD is not None or docinfo.doctype:
        # An IRD return never needs a DOCTYPE; entity declarations are refused
        # outright (XXE / entity expansion), not merely left unresolved.
        return ["a DOCTYPE / entity declaration is not accepted in an IRD submission"]
    try:
        if schema.validate(doc):
            return []
    except etree.XMLSchemaValidateError as exc:
        return [f"schema validation failed: {exc}"]
    return [f"line {e.line}: {e.message}" for e in schema.error_log]

# ══════════════════════════════════════════════════════════════════════════
# (moved from service.py) report generators, preflight, employer readiness,
# profile validation, pack holidays, payslip hold view
# ══════════════════════════════════════════════════════════════════════════

# ── Hong Kong: IRD annual return / notifications, eMPF remittance, MPF
#    contribution record (ZP-HK-ENG-001 §7, §5, HK-011, HK-010) ────────────
#
# Hong Kong reports use the SAME shared architecture as every other
# jurisdiction: a Super-Admin-authored ReportTemplate (versioned, effective
# dated, maker-checker approved, activated through the normal lifecycle), a
# GeneratedReport row with a frozen templateSnapshot, the shared scope_key
# "one live report per scope" uniqueness, the shared certificate PDF for
# employee copies and the shared report history / audit. There is no HK-only
# report infrastructure. Only the VALUES are country-specific: each generator
# delegates every statutory decision to the pure modules in
# engine/jurisdictions/hong_kong/ and to this module, exactly as W-2 delegates
# its box values and Form 138 its quarter arithmetic.
#
# Layout honesty: the IRD BIR56A/IR56B/E/F/G XML schemas and the eMPF
# prescribed remittance format are NOT archived in this build (release gate
# G2), so these templates carry Zoiko's own internal field map and every
# report discloses that in `knownGaps`. No IRD or eMPF layout is invented and
# nothing is transmitted to IRD or eMPF. The HK statutory case/submission
# tables stay the FILING TRACKER and link to their report through
# generated_report_id — the same split the UK uses between GeneratedReport and
# RtiSubmission.

_HK_REPORT_FINALIZED_STATUSES = (
    PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID, PayrollStatus.CLOSED,
)
_HK_LAYOUT_DISCLOSURE = (
    "This is Zoiko's own internal field map for the Hong Kong form, not the IRD / eMPF prescribed "
    "layout. The official IRD BIR56A / IR56B / IR56E / IR56F / IR56G XML schemas and the eMPF "
    "remittance specification are not archived in this build, so no official layout is claimed and "
    "nothing is transmitted to IRD or eMPF (release gate G2). External e-filing stays disabled "
    "until a Super Admin activates an IRD-layout template that has been checked against the archived "
    "schema."
)


def _hk_active_template(db: Session, report_template_id: int, expected_types) -> "ReportTemplate":
    """A Hong Kong report template, of one of `expected_types`, that has been
    Activated (shared require_active_report_template): it must belong to HK —
    a stray UK/US row carrying an HK report_type can never be substituted for
    the seeded HK template — be of the right type, and be Active, which keeps a
    seeded HK template inert until a distinct Super Admin activates it."""
    types = (expected_types,) if isinstance(expected_types, str) else tuple(expected_types)
    return service.require_active_report_template(
        db, report_template_id, country=HK, report_types=types,
        wrong_country_message=lambda t: (f"Template {t.template_key} is a {t.jurisdiction_country!r} template — Hong Kong "
                                         f"reports can only be generated against an 'HK' template."),
        wrong_type_message=lambda t: f"This template is a {t.report_type!r} template, not one of {', '.join(types)}.")


def _hk_require_template_year(template: "ReportTemplate", year: str) -> None:
    """Exact-year rule for every HK report: the template's reporting year must
    BE the report's year (IRD: the year of assessment "2025/26"; MPF /
    termination: the calendar year "2026"). An Active template of another
    year is never used — the Super Admin publishes that year's version."""
    if str(template.reporting_year) != str(year):
        raise BadRequestException(
            f"Template {template.template_key} v{template.version} is the {template.reporting_year} version; this report "
            f"is for {year}. Publish and activate the {year} version — an earlier year's template is never used."
        )


def _hk_walk_report_components(db: Session, template: "ReportTemplate", values: dict) -> tuple:
    """Walks the template's real components/fields and resolves each field's
    value from `values` (a field_key -> real computed value map the caller
    already built), leaving an unrecognized field_key None rather than
    fabricating a value — the same contract as
    _walk_us_aggregate_report_components. Returns
    (component_snapshots, resolved_values)."""
    components = (
        db.query(ReportTemplateComponent)
        .filter(ReportTemplateComponent.report_template_id == template.id)
        .order_by(ReportTemplateComponent.sort_order)
        .all()
    )
    component_snapshots = []
    resolved: dict = {}
    for component in components:
        fields = (
            db.query(ReportTemplateComponentField)
            .filter(ReportTemplateComponentField.component_id == component.id)
            .order_by(ReportTemplateComponentField.sort_order)
            .all()
        )
        field_snapshots = []
        for field in fields:
            field_snapshots.append({
                "fieldKey": field.field_key, "label": field.label, "type": field.field_type,
                "dataSourceKind": field.data_source_kind, "sourceColumn": field.source_column,
                "aggregation": field.aggregation,
            })
            resolved[field.field_key] = values.get(field.field_key)
        component_snapshots.append({"componentKey": component.component_key, "label": component.label, "fields": field_snapshots})
    return component_snapshots, resolved


def _hk_report_configuration_lineage(db: Session, organization_id: int, employee_id: Optional[int],
                                     reporting_year: str, reporting_period: Optional[str]) -> list:
    """The statutory configuration version(s) the report's payslips were
    calculated on — each committed HK payslip's PINNED pack, never today's
    resolution (a superseded version stays the truth for its own payroll).
    Scope = the report's own period: a year of assessment ("2025/26"), a
    contribution month ("2026-05"), up to a termination date, or a calendar
    year. Ordered by first pay date; empty when no payslip is in scope."""
    import re as _re
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment_bounds

    try:
        if "/" in (reporting_year or ""):
            start, end = year_of_assessment_bounds(reporting_year)
        elif reporting_period and _re.fullmatch(r"\d{4}-\d{2}", reporting_period):
            y, m = int(reporting_period[:4]), int(reporting_period[5:])
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        elif reporting_period and _re.fullmatch(r"\d{4}-\d{2}-\d{2}", reporting_period):
            end = date.fromisoformat(reporting_period)
            start = date(end.year, 1, 1)
        else:
            start, end = date(int(reporting_year), 1, 1), date(int(reporting_year), 12, 31)
    except (TypeError, ValueError):
        return []
    seen = {}
    for item, run in sorted(_committed_hk_payslips(db, organization_id, start, end, employee_id=employee_id),
                            key=lambda p: (p[1].pay_date, p[0].id)):
        pid = item.tax_policy_pack_id
        if pid and pid not in seen:
            pack = db.get(JurisdictionPack, pid)
            seen[pid] = {"packRowId": pid, "packId": pack.pack_id if pack else None,
                         "version": pack.version if pack else None, "firstPayDate": run.pay_date.isoformat()}
    return list(seen.values())


def _hk_write_report(db: Session, organization_id: int, template: "ReportTemplate", scope_key: str,
                     rendered_data: dict, reporting_year: str, reporting_period: Optional[str],
                     actor_id: Optional[int], employee_id: Optional[int] = None,
                     reconciliation: Optional[dict] = None) -> GeneratedReport:
    """The shared "one live report per scope" write: any prior Generated row for
    the same LOGICAL report — (organization, jurisdiction, report type,
    reporting year, reporting period, scope_key), whichever template VERSION
    produced it — is flipped to Superseded rather than overwritten or deleted,
    and the new row is inserted with the frozen templateSnapshot already inside
    `rendered_data` (HK-011: a report is immutable evidence; regenerating is a
    new version, never an edit). Keying on the template id instead left a v1.0
    report live beside its v1.1 regeneration. The new row records which
    report(s) it superseded (rendered_data.supersedesReportIds); each
    superseded row keeps its own template version and configuration lineage."""
    previous = service.supersede_live_reports(
        db, organization_id, template.report_type, scope_key=scope_key,
        jurisdiction_country=template.jurisdiction_country, reporting_year=reporting_year,
        reporting_period=reporting_period)
    if previous:
        db.flush()                      # the partial unique "one Generated" index sees the flip first
        rendered_data = {**rendered_data, "supersedesReportIds": previous}
    lineage = _hk_report_configuration_lineage(db, organization_id, employee_id, reporting_year, reporting_period)
    if lineage:
        rendered_data = {**rendered_data, "configurationLineage": lineage}
    row = GeneratedReport(
        organization_id=organization_id, report_template_id=template.id, template_version=template.version,
        report_type=template.report_type, payroll_run_id=None, employee_id=employee_id, scope_key=scope_key,
        jurisdiction_country=template.jurisdiction_country, jurisdiction_state=template.jurisdiction_state,
        reporting_year=reporting_year, reporting_period=reporting_period,
        applicable_tax_pack_id=lineage[-1]["packRowId"] if lineage else None,
        applicable_tax_pack_version=lineage[-1]["version"] if lineage else None,
        status="Generated", generated_by_id=actor_id,
        rendered_data=rendered_data, reconciliation=reconciliation,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row.document_scope = template.document_scope
    return row


def _hk_employer_values(db: Session, organization_id: int) -> tuple:
    """The employer identity every HK report carries. HK employer registration
    facts (BR number, IRD employer file number, eMPF employer account) live on
    the shared CompanyComplianceDetails.tax_identifiers via
    JURISDICTION_TAX_SCHEMAS['HK'] — read here, never duplicated."""
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    identifiers = (company.tax_identifiers or {}) if company else {}
    return company, {
        "employer_name": company.name if company else None,
        "employer_address": company.address if company else None,
        "employer_br_number": identifiers.get("br_number"),     # JURISDICTION_TAX_SCHEMAS["HK"] key
        "employer_ird_file_number": identifiers.get("ird_employer_file_number"),
        "employer_empf_account": identifiers.get("empf_employer_account"),
    }


def generate_hong_kong_bir56a(
    db: Session, organization_id: int, report_template_id: int, ya: str, actor_id: Optional[int] = None,
) -> GeneratedReport:
    """Hong Kong's annual employer's return (BIR56A) for a year of assessment
    ending 31 March.

    The reconciliation itself is NOT recomputed here: generate_annual_return already builds
    the BIR56A cover case plus one IR56B case per reportable employee from
    COMMITTED payroll only, with IR56F / IR56G duplicate suppression and an
    exact reconciliation of reported remuneration to committed payroll
    (HK-011). This function runs that same statutory pass and then REPRESENTS
    its outcome as a shared GeneratedReport, so the return gains the template
    versioning, report history, audit trail, reconciliation block and Super
    Admin cross-org visibility every other jurisdiction's return already had.
    The cases stay the filing tracker and each one links to the report through
    generated_report_id."""
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment_bounds

    template = _hk_active_template(db, report_template_id, "HK_BIR56A")
    _hk_require_template_year(template, ya)
    _validate_hong_kong_ya(ya)
    outcome = generate_annual_return(db, organization_id, ya, actor_id)
    company, employer_values = _hk_employer_values(db, organization_id)

    employees = []
    for line in outcome.get("employees", []):
        employees.append({
            "employeeId": line.get("employeeId"),
            "caseId": line.get("caseId"),
            "status": line.get("status"),
            "message": line.get("message"),
            "validationErrors": line.get("validationErrors") or [],
        })
    box_values = {
        **employer_values,
        "employer_ya": ya,
        "employee_count": len([e for e in employees if e["status"] != "SUPPRESSED"]),
        "total_remuneration": outcome.get("reportedTotal"),
        "committed_payroll_gross": outcome.get("committedPayrollGross"),
        "bir56a_case_id": outcome.get("bir56aCaseId"),
        "schema_status": outcome.get("schemaStatus"),
    }
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    ya_start, ya_end = year_of_assessment_bounds(ya)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": values,
        "yearOfAssessment": ya,
        "period": {"reportingYear": ya, "periodKey": "ANNUAL",
                   "periodStart": ya_start.isoformat(), "periodEnd": ya_end.isoformat()},
        "employees": employees,
        "totals": {"reportedTotal": outcome.get("reportedTotal"),
                   "committedPayrollGross": outcome.get("committedPayrollGross")},
        "knownGaps": [
            _HK_LAYOUT_DISCLOSURE,
            "Per-employee IR56B details are reported on the per-employee HK_IR56B report, not on this "
            "aggregate cover; this report carries the employee count and the reconciled total only.",
        ],
    }
    reconciliation = {
        "status": "Reconciled" if outcome.get("reportedTotal") == outcome.get("committedPayrollGross") else "Variance",
        "reportedTotal": outcome.get("reportedTotal"),
        "committedPayrollGross": outcome.get("committedPayrollGross"),
        "tolerance": None,
    }
    report = _hk_write_report(db, organization_id, template, f"PERIOD:{ya}:BIR56A", rendered_data, ya, "ANNUAL",
                              actor_id, reconciliation=reconciliation)
    # The case is the filing tracker; it points at the report that represents it.
    # Only the BIR56A COVER case is linked here — deliberately not every case for
    # the year. The per-employee IR56B cases and the IR56E/F/G notification cases
    # are represented by their OWN reports (generate_hong_kong_ir56b /
    # generate_hong_kong_ir56_notification), and each of those functions links its
    # own case. Linking them here would overwrite that mapping with the aggregate
    # cover report and leave an employee's certificate pointing at a document that
    # has no per-employee fields.
    from app.modules.payroll.models import HongKongIrdReportingCase

    cover = (db.query(HongKongIrdReportingCase)
             .filter(HongKongIrdReportingCase.organization_id == organization_id,
                     HongKongIrdReportingCase.id == outcome.get("bir56aCaseId"))
             .first())
    if cover is None:
        raise BadRequestException(
            f"The statutory pass for {ya} did not produce a BIR56A cover case to link — the report is not filed."
        )
    if cover.generated_report_id != report.id:
        cover.generated_report_id = report.id
        db.commit()
    return report


def _validate_hong_kong_ya(ya: str) -> None:
    """A Hong Kong year of assessment is "YYYY/YY" and ends 31 March (never a
    calendar year, never a dash) — validated at the API boundary so a
    mistyped period can never silently produce an empty return."""
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment_bounds

    if not ya or "/" not in ya or len(ya) != 7:
        raise BadRequestException(
            f"Invalid Hong Kong year of assessment {ya!r} — expected 'YYYY/YY' (e.g. '2025/26')."
        )
    try:
        year_of_assessment_bounds(ya)
    except (ValueError, TypeError):
        raise BadRequestException(f"Invalid Hong Kong year of assessment {ya!r} — expected 'YYYY/YY'.")


def generate_hong_kong_ir56b(
    db: Session, organization_id: int, report_template_id: int, employee_id: int, ya: str,
    actor_id: Optional[int] = None,
) -> GeneratedReport:
    """The per-employee annual return (IR56B) for a year of assessment — Hong
    Kong's employee-copy document.

    Reads the employee's PREPARED/SUPPRESSED IR56B case for the year (built
    from committed payroll by generate_annual_return) and renders
    its real reported-income fields, employment period and MPF totals. Because
    the template is PER_EMPLOYEE, the SHARED
    generate_report_certificate_pdf_bytes produces the employee's copy
    unchanged — the same route India's Form 130 and the UK's P60 use."""
    template = _hk_active_template(db, report_template_id, "HK_IR56B")
    _hk_require_template_year(template, ya)
    _validate_hong_kong_ya(ya)
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment_bounds
    from app.modules.payroll.models import HongKongIrdReportingCase

    employee = service._get_employee_or_404(db, organization_id, employee_id)
    case = (db.query(HongKongIrdReportingCase)
            .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.employee_id == employee_id,
                    HongKongIrdReportingCase.form_type == "IR56B", HongKongIrdReportingCase.year_of_assessment == ya)
            .order_by(HongKongIrdReportingCase.id.desc()).first())
    if case is None:
        raise BadRequestException(
            f"No IR56B has been prepared for employee #{employee_id} for {ya} — run the year's annual return first."
        )
    if case.status == "SUPPRESSED":
        raise BadRequestException(
            f"The IR56B for employee #{employee_id} ({ya}) is SUPPRESSED: {case.suppression_reason}"
        )
    _company, employer_values = _hk_employer_values(db, organization_id)
    start, end = year_of_assessment_bounds(ya)
    reported = dict(case.reported_income or {})

    # MPF totals for the assessment year come from the employee's own committed
    # HK payslips (the shared employee/employer pension slots), not from a
    # second MPF store.
    mpf_employee, mpf_employer, relevant_income = _hk_year_totals(db, organization_id, employee_id, start, end)
    compliance = employee.compliance_fields or {}
    box_values = {
        **employer_values,
        "employee_name": employee.name,
        "employee_hkid": mask_identifier(compliance.get("hkid") or compliance.get("passport_number")),
        "employee_passport_number": mask_identifier(compliance.get("passport_number")),
        "employment_start": _iso_date(case.income_period_start or employee.date_of_joining or start),
        "employment_end": _iso_date(case.income_period_end or employee.date_of_leaving or end),
        "year_of_assessment": ya,
        "total_remuneration": float(sum(_hk_dec(v) for v in reported.values())),
        "mpf_employee_total": float(mpf_employee),
        "mpf_employer_total": float(mpf_employer),
        "mpf_relevant_income_total": float(relevant_income),
        "case_id": case.id,
        "case_status": case.status,
        "due_date": _iso_date(case.due_date),
        "schema_status": hk_service_schema_status(),
    }
    for field, amount in reported.items():
        box_values[f"ird_{str(field).lower()}"] = float(_hk_dec(amount))
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": employer_values,
        "employees": [{"employeeId": employee.id, "employeeName": employee.name, "values": values}],
        "yearOfAssessment": ya,
        "reportedIncome": reported,
        "caseId": case.id,
        "caseStatus": case.status,
        "knownGaps": [
            _HK_LAYOUT_DISCLOSURE,
            "Reportable field labels are the pack's own IRD field keys; the certified field numbering and "
            "the [G1] specialist sign-off over the HK_EARNING_CLASS mapping are still outstanding.",
            "Identity is MASKED on this report (HK-022 / PCPD HR Code, the same rule the HK payslips apply): "
            "the unmasked HKID is never written into a GeneratedReport, so the official IRD copy still has to "
            "be produced from the employee record through the filing channel.",
        ],
    }
    report = _hk_write_report(db, organization_id, template, f"EMPLOYEE:{employee.id}:{ya}", rendered_data, ya, "ANNUAL",
                              actor_id, employee_id=employee.id)
    if case.generated_report_id != report.id:
        case.generated_report_id = report.id
        db.commit()
    return report


def hk_service_schema_status() -> str:
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird as hk_ird

    return hk_ird.SCHEMA_STATUS


def _hk_preflight_employee_facts(employee) -> dict:
    compliance = employee.compliance_fields or {}
    return {
        "id": employee.id, "code": employee.employee_code, "name": employee.name,
        "identity": {"hkid": compliance.get("hkid"), "passport_number": compliance.get("passport_number")},
        "dob": employee.date_of_birth, "joining": employee.date_of_joining,
        "termination": employee.date_of_leaving,
    }


def _hk_mpf_enrolled(db: Session, employee, as_of) -> bool:
    """MPF enrolment evidence: a recorded MPF member account (compliance
    field) or an MPF scheme reference on the statutory profile in force."""

    if (employee.compliance_fields or {}).get("mpf_member_account"):
        return True
    facts = worker_facts(db, employee, as_of) or {}
    return bool(facts.get("mpfSchemeRef"))


def _hk_run_employees(db: Session, run: PayrollRun) -> list:
    """The HK employees a run covers — the same selection generate_payslips_for_run
    makes, filtered to Hong Kong."""
    rows = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == run.organization_id,
        PayrollEmployee.status == EmployeeStatus.ACTIVE,
        or_(PayrollEmployee.date_of_joining == None, PayrollEmployee.date_of_joining <= run.period_start),  # noqa: E711
    ).all()
    return [e for e in rows if service._resolve_employee_country(db, run.organization_id, getattr(e, "country_code", None)) == "HK"]


def _hk_dry_run_trace(db: Session, run: PayrollRun, employee, cache: dict, calculation_mode,
                      allowance_components, org_opted_in):
    """(trace, None) or (None, HongKongCalculationBlockedError) — read-only."""
    from app.modules.payroll.engine.countries.hong_kong import HongKongCalculationBlockedError

    try:
        country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate, _pr, _po = service._resolve_employee_calc_inputs(
            db, run.organization_id, employee, cache=cache, payroll_date=run.pay_date, org_opted_in=org_opted_in, run=run,
        )
        values = service._compute_payslip_values(
            db, run, employee, rate_map, slabs, country, calculation_mode,
            allowance_components=allowance_components, resolved_pack=resolved_pack,
            state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
            reciprocity=reciprocity, locality_rate=locality_rate,
        )
        return values.get("hk_calculation_trace") or {}, None
    except HongKongCalculationBlockedError as exc:
        return None, exc


def _hk_frozen_recompute(db: Session, run: PayrollRun, employee, item: PayslipItem, organization_id: int) -> dict:
    """The corrected values of a COMMITTED Hong Kong payslip, recalculated on
    its own frozen statutory context: the original tax_rule_snapshot is
    replayed and the original pack stays pinned (period segments are read from
    ITS rows), from the employee's current facts. Read-only; nothing is
    persisted (D-14 linked corrections, request_correction)."""
    calculation_mode = service._resolve_run_calc_inputs(db, run, organization_id)
    org_opted_in = service._org_uses_canonical_tax_pack(db, organization_id)
    country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate, _pr, _po = service._resolve_employee_calc_inputs(
        db, organization_id, employee, payroll_date=run.pay_date, org_opted_in=org_opted_in, run=run,
    )
    if item.tax_rule_snapshot:
        replay_rates, replay_slabs = service._reconstruct_rate_map_and_slabs_from_snapshot(item.tax_rule_snapshot)
        if replay_rates or replay_slabs:
            rate_map = {service._normalize_engine_component_key(r.component_key): r for r in replay_rates}
            slabs = replay_slabs
    pinned = db.get(JurisdictionPack, item.tax_policy_pack_id) if item.tax_policy_pack_id else None
    if pinned is not None and resolved_pack is not None:
        resolved_pack = (resolved_pack[0], resolved_pack[1], pinned)
    return service._compute_payslip_values(
        db, run, employee, rate_map, slabs, country, calculation_mode,
        allowance_components=service._resolve_allowance_components(db, organization_id), resolved_pack=resolved_pack,
        state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
        reciprocity=reciprocity, locality_rate=locality_rate,
    )


def _hk_preflight_state(db: Session, organization_id: int, employee_id: int) -> dict:
    """(hold, ird_cases) for one employee — the payment control and any open
    employer return, read from the same rows the payment path reads."""
    from app.modules.payroll.models import HongKongIrdReportingCase, HongKongTaxClearanceHold

    hold = (db.query(HongKongTaxClearanceHold)
            .filter(HongKongTaxClearanceHold.organization_id == organization_id,
                    HongKongTaxClearanceHold.employee_id == employee_id,
                    HongKongTaxClearanceHold.state.notin_(("INACTIVE", "CASE_CLOSED")))
            .order_by(HongKongTaxClearanceHold.id.desc()).first())
    cases = (db.query(HongKongIrdReportingCase)
             .filter(HongKongIrdReportingCase.organization_id == organization_id,
                     HongKongIrdReportingCase.employee_id == employee_id)
             .order_by(HongKongIrdReportingCase.id.desc()).all())
    hold_view = None if hold is None else {
        "id": hold.id, "state": hold.state,
        "filing_deadline": hold.filing_deadline.isoformat() if hold.filing_deadline else None,
    }
    case_views = [{"id": c.id, "form_type": c.form_type, "status": c.status,
                   "dueDate": c.due_date.isoformat() if c.due_date else None} for c in cases]
    return hold_view, case_views


def hk_payroll_preflight(db: Session, organization_id: int, run_id: int, today: Optional[date] = None) -> dict:
    """Hong Kong payroll-run preflight (ZP-HK-ENG-001 §14 / HK-014) — the statutory
    exceptions that must be resolved or blocked before a HK run is approved:
    Employment Ordinance wage-payment timing and continuous contract, the
    Statutory Minimum Wage position, MPF coverage / contribution position, and
    IRD reporting readiness (an IR56G hold is a payment control, not a deduction).

    Read-only: a persisted trace is read when the run is calculated, otherwise the
    engine is dry-run. No rate is evaluated here — engine/jurisdictions/hong_kong/
    preflight.py only turns the engine's own answers into operator checks.
    """
    from app.modules.payroll.engine.countries.hong_kong import HongKongCalculationBlockedError
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    run = service.get_payroll_run_by_id(db, run_id, organization_id)

    if is_correction_run(run):
        return correction_preflight(db, run)
    today = today or date.today()
    period_end = run.period_end or run.pay_date
    checks = []
    rates, slabs, pack = resolve_tax_configuration(db, "HK", payroll_date=run.pay_date)
    if pack is None:
        checks.append(pf.check("HK_PACK_NOT_ACTIVE", pf.BLOCK, f"no Active Hong Kong statutory pack is in force on "
                               f"{run.pay_date} — no Hong Kong payslip may be calculated", source="tax_resolver",
                               action="Activate the Hong Kong rule pack"))
        return {"runId": run.id, **pf.summarize(checks)}
    rate_map = {r.component_key: r for r in rates}
    checks.extend(pf.pack_checks(rate_map))
    employees = _hk_run_employees(db, run)
    persisted = {i.employee_id: i for i in db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == "HK", PayslipItem.status != PayslipStatus.FAILED)}
    cache: dict = {}
    calculation_mode = service._resolve_run_calc_inputs(db, run, organization_id)
    allowance_components = service._resolve_allowance_components(db, organization_id)
    org_opted_in = service._org_uses_canonical_tax_pack(db, organization_id)
    for employee in employees:
        facts = _hk_preflight_employee_facts(employee)
        checks.extend(pf.identity_checks(facts))
        if employee.id in persisted:
            trace = persisted[employee.id].hk_calculation_trace or {}
        else:
            trace, exc = _hk_dry_run_trace(db, run, employee, cache, calculation_mode, allowance_components, org_opted_in)
            if exc is not None:
                checks.append(pf.engine_block_check(facts, exc))
                continue
        try:
            cc = continuous_contract(db, organization_id, employee.id, period_end)
        except (BadRequestException, HongKongCalculationBlockedError):
            # No in-force statutory profile / an incomplete pack: continuity is
            # reported as not assessed rather than assumed continuous.
            cc = None
        hold, cases = _hk_preflight_state(db, organization_id, employee.id)
        checks.extend(pf.trace_checks(
            facts, trace, cc=cc, hold=hold, ird_cases=cases, rate_map=rate_map,
            pay_date=run.pay_date, period_end=period_end, termination=employee.date_of_leaving, today=today,
            enrolled=_hk_mpf_enrolled(db, employee, period_end)))
    out = pf.summarize(checks)
    out.update({"runId": run.id, "payDate": run.pay_date.isoformat() if run.pay_date else None,
                "wagePeriodEnd": period_end.isoformat(), "payDateDue": run.pay_date.isoformat(),
                "pack": f"{pack.pack_id} v{pack.version}" if pack else None,
                "employeeCount": len(employees), "calculated": len(persisted)})
    return out


def _iso_date(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def hk_employer_readiness(db: Session, organization_id: int, today: Optional[date] = None) -> dict:
    """Hong Kong payroll readiness dashboard (ZP-HK-ENG-001 §14) — the
    organisation-level view: employer registrations, the rule pack in force,
    unresolved worker facts, open IR56G holds, IRD reporting due / overdue and
    the eMPF position.

    Read-only. Built from the SAME check builders as hk_payroll_preflight
    (engine/jurisdictions/hong_kong/preflight.py) and the same statutory-profile
    resolution the calculator uses, so this screen can never show READY for
    something the payroll run or its approval gate would BLOCK."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import HongKongEmpfSubmission, HongKongIrdReportingCase, HongKongTaxClearanceHold

    today = today or date.today()
    checks = []
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    ids = (company.tax_identifiers or {}) if company else {}
    for key, label, severity in (
        ("br_number", "Business Registration number", pf.BLOCK),
        ("ird_employer_file_number", "IRD employer's file number (BIR56A / IR56)", pf.BLOCK),
        ("empf_employer_account", "eMPF employer account number", pf.WARN),
        ("ec_insurance_policy_number", "Employees' Compensation insurance policy (compulsory)", pf.WARN),
    ):
        if not ids.get(key):
            checks.append(pf.check(f"HK_REGISTRATION_MISSING:{key}", severity, f"{label} is not recorded",
                                   source="Company Details → Hong Kong employer registration",
                                   action=f"Record the {label} under Compliance → Company Details"))
    expiry = ids.get("ec_insurance_expiry")
    if expiry:
        try:
            if date.fromisoformat(str(expiry)) < today:
                checks.append(pf.check("HK_EC_INSURANCE_EXPIRED", pf.BLOCK,
                                       f"the Employees' Compensation insurance policy expired on {expiry}",
                                       source="Employees' Compensation Ordinance (compulsory insurance)",
                                       action="Record the renewed policy"))
        except ValueError:
            checks.append(pf.check("HK_EC_INSURANCE_EXPIRY_INVALID", pf.WARN, f"insurance expiry {expiry!r} is not a date"))

    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "HK").first()
    availability = registry.availability if registry else "MISSING"
    if availability != "AVAILABLE":
        checks.append(pf.check("HK_SERVICE_NOT_AVAILABLE", pf.INFO,
                               f"Hong Kong is {availability} on the platform service registry — production onboarding "
                               "is gated until the release gates are evidenced", source="jurisdiction_service_registry"))

    rates, slabs, pack = resolve_tax_configuration(db, "HK", payroll_date=today)
    if pack is None:
        checks.append(pf.check("HK_PACK_NOT_ACTIVE", pf.BLOCK, f"no Active Hong Kong statutory pack is in force on {today}",
                               source="tax_resolver", action="Activate the Hong Kong rule pack (Super Admin)"))
    else:
        checks.extend(pf.pack_checks({r.component_key: r for r in rates}))

    employees = [e for e in db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id, PayrollEmployee.status == EmployeeStatus.ACTIVE).all()
        if service._resolve_employee_country(db, organization_id, getattr(e, "country_code", None)) == "HK"]
    without_profile = 0
    from app.modules.payroll.engine.jurisdictions.hong_kong import mpf as hk_mpf
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    rate_lookup = {r.component_key: r for r in rates} if pack is not None else {}
    for employee in employees:
        facts = _hk_preflight_employee_facts(employee)
        checks.extend(pf.identity_checks(facts))
        worker = worker_facts(db, employee, today)
        if worker is not None and pack is not None:
            # MPF enrolment state (spec §5 eligibility card / exception queue).
            try:
                coverage = hk_mpf.resolve_coverage(worker, today, today, hk_mpf.mpf_parameters(rate_lookup))
                checks.extend(pf.enrolment_checks(facts, coverage, _hk_mpf_enrolled(db, employee, today), today))
            except HongKongCalculationBlockedError:
                pass                     # the profile / pack gap is already reported by its own check
        if worker is None:
            without_profile += 1
            checks.append(pf.check("HK_PROFILE_MISSING", pf.BLOCK,
                                   "no Hong Kong statutory profile version is in force — the calculator blocks this "
                                   "employee", facts, source="EmployeeStatutoryProfile",
                                   action="Record a Hong Kong statutory profile version (Employees → Hong Kong statutory profile)"))

    holds = db.query(HongKongTaxClearanceHold).filter(HongKongTaxClearanceHold.organization_id == organization_id,
                                                 HongKongTaxClearanceHold.state != "CASE_CLOSED").all()
    for hold in holds:
        if hold.state in ("DEPARTURE_IDENTIFIED", "IR56G_DUE"):
            severity = pf.BLOCK if hold.filing_deadline < today else pf.WARN
            checks.append(pf.check("HK_IR56G_DUE", severity,
                                   f"IR56G for case #{hold.id} is due by {hold.filing_deadline} (departure "
                                   f"{hold.expected_departure_date})", {"id": hold.employee_id},
                                   source="IRD PAM 46(e)", action="File the IR56G and record the filing reference"))
        else:
            checks.append(pf.check("HK_IR56G_HOLD_ACTIVE", pf.INFO,
                                   f"IR56G case #{hold.id} is {hold.state}: payments are withheld (legal hold, not a deduction)",
                                   {"id": hold.employee_id}, source="IRD PAM 46(e)"))

    open_cases = db.query(HongKongIrdReportingCase).filter(
        HongKongIrdReportingCase.organization_id == organization_id,
        HongKongIrdReportingCase.status.in_(("DUE", "PREPARED", "VALIDATED"))).all()
    for case in open_cases:
        if case.form_type == "IR56G" or case.due_date is None:
            continue
        if case.due_date < today:
            checks.append(pf.check("HK_IRD_OVERDUE", pf.WARN, f"{case.form_type} case #{case.id} was due {case.due_date}",
                                   {"id": case.employee_id}, source="IRD employer obligations",
                                   action="Prepare, validate and file it through the IRD's own channel"))
        elif (case.due_date - today).days <= 30:
            checks.append(pf.check("HK_IRD_DUE_SOON", pf.INFO, f"{case.form_type} case #{case.id} is due {case.due_date}",
                                   {"id": case.employee_id}, source="IRD employer obligations"))

    from app.modules.payroll.models import LegalHold, HongKongPayslipCorrection

    open_corrections = (db.query(HongKongPayslipCorrection)
                        .filter(HongKongPayslipCorrection.organization_id == organization_id,
                                HongKongPayslipCorrection.status == "REQUESTED").all())
    for corr in open_corrections:
        checks.append(pf.check("HK_CORRECTION_AWAITING_APPROVAL", pf.INFO,
                               f"payroll correction #{corr.id} of payslip {corr.original_payslip_id} awaits approval by a "
                               "different operator", {"id": corr.employee_id},
                               source="ZP-HK-ENG-001 §12 linked adjustment",
                               action="Approve or reject it (Compliance → Hong Kong Compliance Centre → Corrections)"))
    active_holds = (db.query(LegalHold)
                    .filter(LegalHold.organization_id == organization_id, LegalHold.status == "ACTIVE").count())
    if active_holds:
        checks.append(pf.check("HK_LEGAL_HOLD_ACTIVE", pf.INFO,
                               f"{active_holds} legal hold(s) in force — HK records in scope cannot be deleted",
                               source="D-19 legal hold"))
    latest_empf = (db.query(HongKongEmpfSubmission).filter(HongKongEmpfSubmission.organization_id == organization_id)
                   .order_by(HongKongEmpfSubmission.contribution_period.desc(), HongKongEmpfSubmission.id.desc()).first())
    summary = pf.summarize(checks)
    return {
        **summary,
        "asOf": today.isoformat(),
        "pack": None if pack is None else {"packId": pack.pack_id, "version": pack.version, "status": pack.status,
                                           "yearOfAssessment": pack.tax_year,
                                           "effectiveFrom": _iso_date(pack.effective_from),
                                           "effectiveTo": _iso_date(pack.effective_to)},
        "serviceRegistry": availability,
        "registration": {k: bool(ids.get(k)) for k in ("br_number", "ird_employer_file_number",
                                                       "empf_employer_account", "ec_insurance_policy_number")},
        "workforce": {"hongKongEmployees": len(employees), "withoutStatutoryProfile": without_profile},
        "taxClearance": {"openCases": len(holds)},
        "corrections": {"awaitingApproval": len(open_corrections)},
        "legalHolds": {"active": active_holds},
        "ird": {"openCases": len(open_cases)},
        "empf": None if latest_empf is None else {"contributionPeriod": latest_empf.contribution_period,
                                                  "status": latest_empf.status},
        "salariesTax": "Employee-assessed by the IRD — no payroll withholding",
        # The pack in force, exactly as the calculator resolves it (tenant
        # Tax Configuration view — HK has no per-organisation slab rows).
        "parameters": [] if pack is None else [
            {"componentKey": r.component_key, "label": r.label,
             "ratePct": None if r.employee_rate_pct is None else str(r.employee_rate_pct),
             "employerRatePct": None if r.employer_rate_pct is None else str(r.employer_rate_pct),
             "flatAmount": None if r.flat_amount is None else str(r.flat_amount),
             "textValue": r.text_value, "sourceDocumentId": r.source_document_id}
            for r in sorted(rates, key=lambda r: r.component_key)],
        "salariesTaxBands": [] if pack is None else [
            {"ruleType": t.rule_type, "minAmount": str(t.min_amount),
             "maxAmount": None if t.max_amount is None else str(t.max_amount), "ratePct": str(t.rate_pct)}
            for t in sorted(slabs, key=lambda t: (t.rule_type or "", t.min_amount))
            if (t.rule_type or "").startswith("HK_SALARIES_TAX")],
    }


def _hk_run_has_payslips(db: Session, run: PayrollRun) -> bool:
    return db.query(PayslipItem.id).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == "HK").first() is not None


def _hk_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """HK-gated hook of advance_payroll_run_status (a run without HK payslips is
    untouched). A BLOCK check is a statutory exception that must be resolved
    before the money is committed — the operator cannot approve past it."""
    if not _hk_run_has_payslips(db, run):
        return

    if is_correction_run(run):
        # D-14: a linked correction is approved by a different operator, and
        # its statutory consequences are applied in this same transaction.
        before_run_transition(db, run, next_status, actor_id)
        return
    if next_status == PayrollStatus.APPROVED:
        from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

        result = hk_payroll_preflight(db, run.organization_id, run.id)
        blocks = [c for c in result["checks"] if c["severity"] == pf.BLOCK]
        if blocks:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Hong Kong preflight blocks approval: "
                + "; ".join(f"{c['code']} ({c.get('employeeCode') or 'run'})" for c in blocks[:10])))


def _hk_dec(value):
    from decimal import Decimal

    if value is None or value == "":
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _hk_year_totals(db: Session, organization_id: int, employee_id: int, start: date, end: date) -> tuple:
    """(employee MPF, employer MPF, relevant income) over the committed HK
    payslips paid inside [start, end]. Reads the same persisted payslip columns
    the certificate PDF and bank file read — never a second contribution store."""
    rows = (
        db.query(PayslipItem)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .filter(PayslipItem.organization_id == organization_id, PayslipItem.employee_id == employee_id,
                PayslipItem.country_code == "HK", PayrollRun.pay_date >= start, PayrollRun.pay_date <= end,
                PayrollRun.status.in_(_HK_REPORT_FINALIZED_STATUSES))
        .all()
    )
    employee_total = employer_total = relevant = Decimal("0")
    for item in rows:
        employee_total += _hk_dec(item.employee_pension)
        employer_total += _hk_dec(item.employer_pension)
        relevant += _hk_dec(((item.hk_calculation_trace or {}).get("mpf") or {})
                            .get("currentPeriod", {}).get("relevantIncome"))
    return employee_total, employer_total, relevant


def generate_hong_kong_ir56_notification(
    db: Session, organization_id: int, report_template_id: int, case_id: int, actor_id: Optional[int] = None,
) -> GeneratedReport:
    """An IR56 employee notification (IR56E commencement, IR56F cessation, or
    IR56G departure) for one employee.

    The HongKongIrdReportingCase is the source of truth — it already holds the
    resolved filing deadline, the income period and the payload produced from
    committed payroll — so this renders the case rather than re-deriving it,
    and links the case to its report. IR56G additionally reports the amount
    currently held under the tax-clearance hold (a legal hold, not a
    deduction: net pay is unchanged)."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import tax_clearance as hk_tc
    from app.modules.payroll.models import HongKongIrdReportingCase, HongKongTaxClearanceHold

    template = _hk_active_template(db, report_template_id, ("HK_IR56E", "HK_IR56F", "HK_IR56G"))
    case = (db.query(HongKongIrdReportingCase)
            .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.id == case_id)
            .first())
    if case is None:
        raise NotFoundException("Hong Kong IRD reporting case", case_id)
    _hk_require_template_year(template, case.year_of_assessment)
    form_to_type = {"IR56E": "HK_IR56E", "IR56F": "HK_IR56F", "IR56G": "HK_IR56G"}
    expected = form_to_type.get(case.form_type)
    if expected is None:
        raise BadRequestException(
            f"Case #{case_id} is a {case.form_type!r} case, not an employee notification (IR56E / IR56F / IR56G)."
        )
    if template.report_type != expected:
        raise BadRequestException(
            f"A {case.form_type} case must be reported on a {expected} template, not {template.report_type!r}."
        )
    employee = service._get_employee_or_404(db, organization_id, case.employee_id)
    _company, employer_values = _hk_employer_values(db, organization_id)
    compliance = employee.compliance_fields or {}
    hold, hold_amount = None, None
    if case.form_type == "IR56G":
        hold = (db.query(HongKongTaxClearanceHold)
                .filter(HongKongTaxClearanceHold.organization_id == organization_id,
                        HongKongTaxClearanceHold.employee_id == case.employee_id,
                        HongKongTaxClearanceHold.state.in_(hk_tc.HOLDING_STATES))
                .order_by(HongKongTaxClearanceHold.id.desc()).first())
        if hold is not None:

            hold_amount = float(held_total(db, hold))

    box_values = {
        **employer_values,
        "employee_name": employee.name,
        "employee_hkid": mask_identifier(compliance.get("hkid") or compliance.get("passport_number")),
        "employee_passport_number": mask_identifier(compliance.get("passport_number")),
        "form_type": case.form_type,
        "event_date": _iso_date(case.event_date),
        "due_date": _iso_date(case.due_date),
        "income_period_start": _iso_date(case.income_period_start),
        "income_period_end": _iso_date(case.income_period_end),
        "reported_total": float(sum(_hk_dec(v) for v in (case.reported_income or {}).values())) or None,
        "hold_state": hold.state if hold is not None else None,
        "hold_filing_deadline": _iso_date(hold.filing_deadline) if hold is not None else None,
        "hold_statutory_expiry": _iso_date(hold.statutory_hold_expiry) if hold is not None else None,
        "amount_withheld": hold_amount,
        "case_id": case.id,
        "case_status": case.status,
    }
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": employer_values,
        "employees": [{"employeeId": employee.id, "employeeName": employee.name, "values": values}],
        "formType": case.form_type,
        "caseId": case.id,
        "caseStatus": case.status,
        "eventDate": _iso_date(case.event_date),
        "dueDate": _iso_date(case.due_date),
        "knownGaps": [
            _HK_LAYOUT_DISCLOSURE,
            "The IR56G 'Additional' form flow (an employee who departs and later returns) is not modelled; "
            "only the initial departure notification is produced.",
            "Identity is MASKED on this report (HK-022 / PCPD HR Code): the unmasked HKID is never written "
            "into a GeneratedReport, so the official IRD copy still has to be produced from the employee "
            "record through the filing channel.",
        ],
    }
    report = _hk_write_report(db, organization_id, template, f"CASE:{case.form_type}:{case.id}", rendered_data,
                              case.year_of_assessment, case.form_type, actor_id, employee_id=case.employee_id)
    # The case is the filing tracker; it points at the report that represents it
    # (the shared history row, so the case is always resolvable back to the exact
    # rendered document and template version it was issued on).
    if case.generated_report_id != report.id:
        case.generated_report_id = report.id
        db.commit()
    return report


def generate_hong_kong_empf_remittance(
    db: Session, organization_id: int, report_template_id: int, submission_id: int,
    actor_id: Optional[int] = None,
) -> GeneratedReport:
    """The employer's eMPF remittance statement for one contribution period,
    rendered from a PREPARED eMPF submission (prepare_empf_submission builds those rows from
    committed payslips only, with per-member validation errors).

    Zoiko transmits nothing: the statement is the operator's input to their own
    eMPF submission, and the submission's own lifecycle (SUBMITTED /
    ACCEPTED / REJECTED, four-eyes) stays the record of what actually happened
    on the eMPF platform (release gate G2)."""
    from app.modules.payroll.models import HongKongEmpfSubmission

    template = _hk_active_template(db, report_template_id, "HK_EMPF_REMITTANCE")
    submission = (db.query(HongKongEmpfSubmission)
                  .filter(HongKongEmpfSubmission.organization_id == organization_id, HongKongEmpfSubmission.id == submission_id)
                  .first())
    if submission is None:
        raise NotFoundException("Hong Kong eMPF submission", submission_id)
    _hk_require_template_year(template, str(submission.contribution_period)[:4])
    _company, employer_values = _hk_employer_values(db, organization_id)
    totals = submission.totals or {}
    members = [
        {"payslipId": r.get("payslipId"), "employeeId": r.get("employeeId"), "name": r.get("name"),
         "hkid": r.get("hkid"), "mpfSchemeRef": r.get("mpfSchemeRef"), "memberAccount": r.get("memberAccount"),
         "memberIdentifierStatus": "INTERNAL — the eMPF member-identifier layout is not archived (G2)",
         "relevantIncome": r.get("relevantIncome"),
         "employerMandatory": r.get("employerMandatory"), "employeeMandatory": r.get("employeeMandatory"),
         "catchUpPeriods": r.get("catchUpPeriods"), "errors": r.get("errors") or []}
        for r in (submission.rows or [])
    ]
    box_values = {
        **employer_values,
        "contribution_period": submission.contribution_period,
        "contribution_day": _iso_date(submission.contribution_day),
        "submission_status": submission.status,
        "member_count": totals.get("employees"),
        "total_relevant_income": totals.get("relevantIncome"),
        "total_employer_mandatory": totals.get("employerMandatory"),
        "total_employee_mandatory": totals.get("employeeMandatory"),
        "validation_error_count": len(submission.validation_errors or []),
        "submission_id": submission.id,
    }
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": values,
        "period": {"contributionPeriod": submission.contribution_period,
                   "contributionDay": _iso_date(submission.contribution_day)},
        "employees": members,
        "totals": totals,
        "validationErrors": submission.validation_errors or [],
        "knownGaps": [
            _HK_LAYOUT_DISCLOSURE,
            "MPF voluntary contributions are NOT in the first release: only mandatory employer and "
            "employee contributions are reported, and no voluntary-contribution subsystem exists. The "
            "remittance statement keeps one line per contributing member, so voluntary amounts can be "
            "added to that line later without changing the report's shape.",
            "Identity is masked here; the unmasked value is never placed in a GeneratedReport.",
        ],
    }
    report = _hk_write_report(db, organization_id, template,
                              f"SUBMISSION:{submission.contribution_period}:{submission.id}", rendered_data,
                              submission.contribution_period[:4], submission.contribution_period, actor_id)
    if submission.generated_report_id != report.id:
        submission.generated_report_id = report.id
        db.commit()
    return report


def generate_hong_kong_mpf_contribution_record(
    db: Session, organization_id: int, report_template_id: int, employee_id: int, period: str,
    actor_id: Optional[int] = None,
) -> GeneratedReport:
    """The employee's own MPF contribution / pay record (HK-010: "provide
    employee MPF contribution / pay records"). Not a filing — an employee
    document — so it is generated straight from the employee's committed HK
    payslips for the contribution period, in the same employee_pension /
    employer_pension / relevant-income columns every other jurisdiction's
    employee statement reads.

    `period` is a calendar month ("2026-05"); `period=None` is not accepted
    because MPF is contributed monthly and an unbounded record would silently
    mix contribution periods."""
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import add_months

    template = _hk_active_template(db, report_template_id, "HK_MPF_CONTRIBUTION_RECORD")
    if not period or len(str(period)) != 7 or str(period)[4] != "-":
        raise BadRequestException(
            f"Invalid contribution period {period!r} — expected a calendar month, e.g. '2026-05'."
        )
    employee = service._get_employee_or_404(db, organization_id, employee_id)        # tenant refusal first
    _hk_require_template_year(template, str(period)[:4])
    year, month = (int(p) for p in str(period).split("-"))
    start = date(year, month, 1)
    end = add_months(start, 1) - timedelta(days=1)

    items = (
        db.query(PayslipItem, PayrollRun)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .filter(PayslipItem.organization_id == organization_id, PayslipItem.employee_id == employee_id,
                PayslipItem.country_code == "HK", PayrollRun.pay_date >= start, PayrollRun.pay_date <= end,
                PayrollRun.status.in_(_HK_REPORT_FINALIZED_STATUSES))
        .order_by(PayrollRun.pay_date)
        .all()
    )
    if not items:
        raise BadRequestException(
            f"Employee #{employee_id} has no committed Hong Kong payroll in {period} — there is no MPF record to report."
        )
    _company, employer_values = _hk_employer_values(db, organization_id)
    lines, employee_total, employer_total, relevant_total = [], Decimal("0"), Decimal("0"), Decimal("0")
    for item, item_run in items:
        trace = item.hk_calculation_trace or {}
        relevant = _hk_dec((trace.get("mpf") or {}).get("currentPeriod", {}).get("relevantIncome"))
        coverage = (trace.get("mpf") or {}).get("coverage") or {}
        line = {
            "payslipItemId": item.id,
            "payDate": item_run.pay_date.isoformat() if item_run.pay_date else None,
            "periodEnd": (trace.get("period") or {}).get("end"),
            "relevantIncome": float(relevant),
            "employerMandatory": float(_hk_dec(item.employer_pension)),
            "employeeMandatory": float(_hk_dec(item.employee_pension)),
            "coverageStatus": coverage.get("status"),
            "catchUpPeriods": len((trace.get("mpf") or {}).get("catchUp") or []),
        }
        lines.append(line)
        relevant_total += relevant
        employer_total += _hk_dec(item.employer_pension)
        employee_total += _hk_dec(item.employee_pension)

    # The statutory pack + version the figures came from is read back off the
    # payslip's own tax_rule_snapshot pin, so a historical record can always be
    # re-derived against the pack that actually produced it.
    pack_ref = None
    for item, _item_run in items:
        snap = item.tax_rule_snapshot if isinstance(item.tax_rule_snapshot, dict) else None
        if snap and (snap.get("packId") or snap.get("pack_id")):
            pack_ref = {"packId": snap.get("packId") or snap.get("pack_id"),
                        "version": snap.get("version") or snap.get("packVersion")}
            break
    if pack_ref is None:
        # No pin on any payslip: fall back to the pack FK the same items carry,
        # rather than reporting the statutory pack as unknown when it is
        # recoverable (a payslip that pinned a pack always sets both).
        pinned = {i.tax_policy_pack_id for i, _r in items if i.tax_policy_pack_id}
        if len(pinned) == 1:
            pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pinned.pop()).first()
            if pack is not None:
                pack_ref = {"packId": pack.id, "version": pack.version}
    compliance = employee.compliance_fields or {}
    box_values = {
        **employer_values,
        "employee_name": employee.name,
        "employee_hkid": mask_identifier(compliance.get("hkid") or compliance.get("passport_number")),
        "employee_passport_number": mask_identifier(compliance.get("passport_number")),
        "contribution_period": period,
        "payslip_count": len(items),
        "total_relevant_income": float(relevant_total),
        "total_employer_mandatory": float(employer_total),
        "total_employee_mandatory": float(employee_total),
        "pack_id": (pack_ref or {}).get("packId"),
        "pack_version": (pack_ref or {}).get("version"),
    }
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": employer_values,
        "employees": [{"employeeId": employee.id, "employeeName": employee.name, "values": values}],
        "contributionPeriod": period,
        "period": {"periodStart": start.isoformat(), "periodEnd": end.isoformat()},
        "lines": lines,
        "totals": {"relevantIncome": float(relevant_total), "employerMandatory": float(employer_total),
                   "employeeMandatory": float(employee_total)},
        "statutoryPack": pack_ref,
        "knownGaps": [
            "MPF voluntary contributions are NOT in the first release; this record reports mandatory "
            "employer and employee contributions only.",
            "The per-line 'coverage status' and any catch-up contribution count come from the payroll "
            "calculation trace itself, so a replay against the same pack reproduces this record exactly.",
        ],
    }
    return _hk_write_report(db, organization_id, template, f"EMPLOYEE:{employee.id}:{period}", rendered_data,
                            str(year), period, actor_id, employee_id=employee.id)


def generate_hong_kong_termination_statement(
    db: Session, organization_id: int, report_template_id: int, termination_result_id: int,
    actor_id: Optional[int] = None,
) -> GeneratedReport:
    """The employee's Hong Kong termination statement (ZP-HK-ENG-001 document
    service: "leave / termination statements"). It RENDERS an APPROVED
    (four-eyes) HongKongTerminationResult — never recalculates it — so the figures
    the employee receives are exactly the approved evidence (evidence hash
    included). An employee document, not a filing: nothing is transmitted."""
    from app.modules.payroll.models import HongKongTerminationResult

    template = _hk_active_template(db, report_template_id, "HK_TERMINATION_STATEMENT")
    row = (db.query(HongKongTerminationResult)
           .filter(HongKongTerminationResult.id == termination_result_id,
                   HongKongTerminationResult.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException(f"Hong Kong termination result {termination_result_id} not found.")
    _hk_require_template_year(template, str(row.termination_date.year))
    if row.status != "APPROVED":
        raise BadRequestException(
            f"Termination result #{row.id} is {row.status} — only an APPROVED (four-eyes) calculation is issued "
            "to the employee as a statement.")
    employee = service._get_employee_or_404(db, organization_id, row.employee_id)
    _company, employer_values = _hk_employer_values(db, organization_id)
    r = row.result or {}
    portions = r.get("portions") or {}

    def portion(name):
        p = portions.get(name) or {}
        value = p.get("amountAfterCap", p.get("amount"))
        return float(_hk_dec(value)) if value is not None else None

    compliance = employee.compliance_fields or {}
    box_values = {
        **employer_values,
        "employee_name": employee.name,
        "employee_hkid": mask_identifier(compliance.get("hkid") or compliance.get("passport_number")),
        "termination_date": row.termination_date.isoformat(),
        "termination_reason": row.termination_reason,
        "payment_type": row.payment_type,
        "pre_transition_portion": portion("preTransition"),
        "post_transition_portion": portion("postTransition"),
        "gross_entitlement": float(_hk_dec(row.gross_entitlement)),
        "total_offsets": float(_hk_dec(row.total_offsets)),
        "net_statutory_payment": float(_hk_dec(row.net_statutory_payment)),
        "final_wages": float(_hk_dec(r.get("finalWages"))),
        "annual_leave_pay": float(_hk_dec(r.get("annualLeavePay"))),
        "holiday_pay": float(_hk_dec(r.get("holidayPay"))),
        "total_final_payment": float(_hk_dec(r.get("totalFinalPayment"))),
        "payment_hold": r.get("paymentHold") or "",
        "evidence_hash": row.evidence_hash,
        "pack_id": r.get("packId"),
    }
    component_snapshots, values = _hk_walk_report_components(db, template, box_values)
    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                             "components": component_snapshots},
        "employer": employer_values,
        "employees": [{"employeeId": employee.id, "employeeName": employee.name, "values": values}],
        "termination": {"resultId": row.id, "terminationDate": row.termination_date.isoformat(),
                        "reason": row.termination_reason, "paymentType": row.payment_type,
                        "approvedById": row.approved_by_id, "evidenceHash": row.evidence_hash},
        "offsets": r.get("offsets") or [],
        "knownGaps": [
            "An employee statement rendered from the approved termination calculation; it is not an IRD / "
            "Labour Department filing and nothing is transmitted.",
            "The SP / LSP day-count convention (days / 365 for an incomplete year) is a Hong Kong specialist "
            "certification item (G1).",
            "Leave and holiday pay shown are the amounts entered on the approved calculation; terminations "
            "before 1 May 2025 are out of scope.",
        ],
    }
    return _hk_write_report(db, organization_id, template, f"TERMINATION:{row.id}", rendered_data,
                            str(row.termination_date.year), row.termination_date.isoformat(), actor_id,
                            employee_id=employee.id)




def _hk_pack_holidays(db: Session, year: int) -> List[dict]:
    """The year's statutory holidays straight from the in-force HK rule pack's
    own calendar rows (one source-linked slab row per day). No pack / no rows
    for that year seeds nothing — a Labour Department date is never guessed."""
    from app.modules.payroll.engine.countries.hong_kong import HongKongCalculationBlockedError
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements as hk_entitlements
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        _rates, slabs, pack = resolve_tax_configuration(db, "HK", payroll_date=date(year, 12, 31))
        if pack is None:
            return []
        return hk_entitlements.statutory_holidays(slabs, year)
    except (BadRequestException, HongKongCalculationBlockedError):   # no calendar for that year
        return []

# Hong Kong statutory-profile value sets (ZP-HK-ENG-001 §3, §5).
_HK_PROFILE_CHOICES = {
    "hk_employment_relationship": ("EMPLOYEE", "CASUAL_INDUSTRY", "DOMESTIC", "CONTRACTOR_REVIEW"),
    "hk_identity_document_type": ("HKID", "PASSPORT"),
    "hk_residency_status": ("RESIDENT", "NON_RESIDENT"),
    "hk_mpf_exemption_code": ("NONE", "EXEMPT_AGE", "EXEMPT_DOMESTIC", "EXEMPT_STATUTORY_SCHEME", "EXEMPT_ORSO",
                               "EXEMPT_INBOUND", "INDUSTRY_SCHEME_SPECIAL"),
    "hk_pay_basis": ("MONTHLY", "DAILY", "HOURLY", "PIECE"),
    "hk_termination_reason": ("REDUNDANCY", "FIXED_TERM_EXPIRY_REDUNDANCY", "LAY_OFF", "DISMISSAL", "FIXED_TERM_EXPIRY",
                               "DEATH", "RESIGNATION_ILL_HEALTH", "RESIGNATION_AGE_65", "SUMMARY_DISMISSAL", "RESIGNATION"),
    "hk_pre_transition_wage_basis": ("LAST_FULL_MONTH", "TWELVE_MONTH_AVERAGE"),
}

def _hk_statutory_profile_errors(data) -> list:
    errors = []
    for field, allowed in _HK_PROFILE_CHOICES.items():
        value = getattr(data, field, None)
        if value is not None and value not in allowed:
            errors.append(f"{field} must be one of {', '.join(allowed)}.")
    code = data.hk_mpf_exemption_code
    if code in ("EXEMPT_STATUTORY_SCHEME", "EXEMPT_ORSO", "EXEMPT_INBOUND") and not data.hk_mpf_exemption_evidence_ref:
        errors.append(f"{code} needs hk_mpf_exemption_evidence_ref (the exemption is never inferred).")
    hours = data.hk_contractual_weekly_hours
    if hours is not None and not (0 <= hours <= 168):
        errors.append("hk_contractual_weekly_hours must be between 0 and 168.")
    if data.hk_pre_transition_monthly_wage is not None and data.hk_pre_transition_monthly_wage <= 0:
        errors.append("hk_pre_transition_monthly_wage must be greater than 0.")
    if data.hk_pre_transition_monthly_wage is not None and not data.hk_pre_transition_evidence_ref:
        errors.append("the frozen pre-1-May-2025 wage needs hk_pre_transition_evidence_ref (HK-017).")
    return errors

_HK_FROZEN_PROFILE_FIELDS = ("hk_pre_transition_monthly_wage", "hk_pre_transition_wage_basis",
                             "hk_pre_transition_evidence_ref")

def _hk_profile_values(db: Session, employee, data, previous) -> dict:
    """HK columns for a new version: every HK field not sent in THIS request
    carries forward from the previous HK version (a full snapshot per
    version); the frozen pre-transition wage can never change once recorded
    (HK-017); the identity token is derived server-side from the employee's
    own identifier, never accepted from the client (HK-022)."""
    import hashlib


    sent = data.model_fields_set
    values = {}
    for col in HK_PROFILE_COLUMNS:
        if col == "hk_identity_token":
            continue
        if col in sent:
            values[col] = getattr(data, col)
        elif previous is not None and previous.country_code == "HK":
            values[col] = getattr(previous, col)
    if previous is not None and previous.country_code == "HK":
        for col in _HK_FROZEN_PROFILE_FIELDS:
            before = getattr(previous, col)
            if before is not None and values.get(col) != before:
                raise BadRequestException(
                    f"{col} is frozen pre-transition wage evidence (HK-017) and cannot change in a later version.")
    cf = employee.compliance_fields or {}
    ident = cf.get("hkid") if values.get("hk_identity_document_type") != "PASSPORT" else cf.get("passport_number")

    values["hk_identity_token"] = identity_token(ident)          # keyed, versioned (D-19)
    return values

def _hk_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    """Hong Kong IR56G: the payslip's held-ledger line, if any — shown on the
    payslip as a LEGAL HOLD, separate from deductions (net pay unchanged)."""
    if (getattr(item, "country_code", None) or "").upper() != "HK":
        return None
    from sqlalchemy.orm import object_session
    from app.modules.payroll.models import HongKongTaxClearanceHoldLine

    session = object_session(item)
    line = session.query(HongKongTaxClearanceHoldLine).filter(
        HongKongTaxClearanceHoldLine.payslip_item_id == item.id).first() if session is not None else None
    if line is None:
        return None
    return {"status": line.status, "amount": str(line.amount), "holdId": line.hold_id,
            "basis": "IR56G departure tax-clearance hold — money remains owed to the employee"}


# ══════════════════════════════════════════════════════════════════════════
# Platform registration — the ONLY way the shared platform reaches this module
# ══════════════════════════════════════════════════════════════════════════

# Hong Kong record categories for the shared retention framework (D-2 / D-3).
RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and calculation traces"),
    ("MPF_RECORDS", "MPF contribution records and eMPF submissions"),
    ("IRD_RETURNS", "IRD returns and notifications (BIR56A / IR56B / E / F / G)"),
    ("TERMINATION_RECORDS", "Termination statements, SP / LSP and average-wage snapshots"),
    ("EMPLOYEE_IDENTITY", "HKID / passport and statutory profile data"),
    ("WORK_HOURS", "Hours-worked records (minimum wage)"),
    ("ACCESS_LOGS", "HK access events and download logs"),
    ("CORRECTIONS", "Payslip corrections and their evidence"),
)


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    for model, label in ((HongKongIrdReportingCase, "IRD reporting cases"),
                         (HongKongTaxClearanceHold, "IR56G tax-clearance cases"),
                         (HongKongWorkHours, "verified work hours"),
                         (HongKongAverageWageSnapshot, "average-wage snapshots"),
                         (HongKongTerminationResult, "termination results"),
                         (HongKongPayslipCorrection, "payroll corrections")):
        if db.query(model.id).filter(model.organization_id == organization_id, model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return (db.query(EmployeeStatutoryProfile.id)
            .filter(EmployeeStatutoryProfile.employee_id == employee_id, EmployeeStatutoryProfile.country_code == HK)
            .first() is not None)


def is_hk_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == HK
                                        or str(getattr(report, "report_type", "") or "").startswith("HK_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=HK, label="Hong Kong", categories=RETENTION_CATEGORIES, period_decision="D-2", end_decision="D-3",
        decision_reference="HK-DECISION-D-2", decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_hk_report, audit_spec="ZP-HK-ENG-001 production readiness")


# hook name (asked for by the platform) -> attribute of this module
JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_hk_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "hk_activation_evidence_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_hk_before_run_transition",
    "pack_holidays": "_hk_pack_holidays",
    "statutory_profile_errors": "_hk_statutory_profile_errors",
    "statutory_profile_values": "_hk_profile_values",
    "payslip_hold_view": "_hk_payslip_hold_view",
}

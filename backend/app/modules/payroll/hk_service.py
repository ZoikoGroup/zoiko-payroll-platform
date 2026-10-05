"""
modules/payroll/hk_service.py
-----------------------------
Hong Kong (ZP-HK-ENG-001) service layer — the DB-facing half of the Hong Kong
country implementation. It is part of the SHARED payroll service (service.py
calls into it; it calls service.py's shared primitives), not a parallel
runtime: rule packs, rates, evidence, the effective-dated statutory profile,
payslips, audit (record_tax_audit), RBAC and tenant scoping are all the
shared ones. Everything statutory is computed by the pure modules in
engine/jurisdictions/hong_kong/ and engine/countries/hong_kong.py.

Tenant isolation (HK-021): every function takes the caller's organization_id
(from the authenticated context, never the request body) and every query is
filtered by it. Four-eyes (HK-022): IR56G release, IRD filing/amendment, eMPF
submission, average-wage override and termination approval all require an
approver distinct from the preparer.
"""

import copy
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.jurisdictions.hong_kong import (
    average_wage as hk_average_wage, continuous_contract as hk_cc, entitlements as hk_entitlements,
    ird as hk_ird, mpf as hk_mpf, salaries_tax as hk_salaries_tax, tax_clearance as hk_tc,
    termination as hk_termination,
)
from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, add_months, canonical_hash, cents, dec, resolve_timing, rule_segments,
    year_of_assessment, year_of_assessment_bounds,
)
from app.modules.payroll.models import (
    CompanyComplianceDetails, ContributionRate, EmployeeStatutoryProfile, HkgAverageWageSnapshot,
    HkgEmpfSubmission, HkgIrdReportingCase, HkgTaxClearanceHold, HkgTaxClearanceHoldLine, HkgTerminationResult,
    HkgWorkHours, JurisdictionPack, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem, SourceArtifact, TaxSlab,
)

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


def _four_eyes(preparer: Optional[int], approver: Optional[int], what: str) -> None:
    if approver is None:
        raise BadRequestException(f"{what} needs an approver.")
    if preparer is not None and approver == preparer:
        raise BadRequestException(f"{what}: the approver must be a different person from the preparer (four-eyes).")


# ── Worker facts (HKWorkerProfile on the shared statutory profile) ──────

HK_PROFILE_COLUMNS = tuple(c.name for c in EmployeeStatutoryProfile.__table__.columns if c.name.startswith("hkg_"))
# Never copied into a payroll trace (HK-022: privileged identity data).
_TRACE_EXCLUDED = ("hkg_identity_token",)


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
    head, *rest = column[len("hkg_"):].split("_")
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
        current = (db.query(HkgWorkHours)
                   .filter(HkgWorkHours.organization_id == organization_id, HkgWorkHours.employee_id == employee_id,
                           HkgWorkHours.work_date == day, HkgWorkHours.superseded_by_id.is_(None)).first())
        if current is not None and not reason:
            raise BadRequestException(f"{day} already has verified hours — a correction needs a reason")
        row = HkgWorkHours(organization_id=organization_id, employee_id=employee_id, work_date=day, hours=hours,
                           source=source, evidence_ref=entry.get("evidenceRef"), recorded_by_id=actor_id)
        db.add(row)
        db.flush()
        if current is not None:
            current.superseded_by_id, current.supersede_reason = row.id, reason
        created.append(row)
        _audit(db, actor_id, "create", "hkg_work_hours", row.id,
               old={"supersedes": current.id, "hours": str(current.hours)} if current else None,
               new={"employeeId": employee_id, "date": day.isoformat(), "hours": str(hours), "source": source},
               reason=reason, commit=False)
    db.commit()
    return created


def hours_map(db: Session, employee_id: int, start: date, end: date, organization_id: int = None) -> dict:
    q = db.query(HkgWorkHours).filter(HkgWorkHours.employee_id == employee_id, HkgWorkHours.work_date >= start,
                                      HkgWorkHours.work_date <= end, HkgWorkHours.superseded_by_id.is_(None))
    if organization_id is not None:
        q = q.filter(HkgWorkHours.organization_id == organization_id)
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
                    PayslipItem.hkg_calculation_trace.isnot(None), PayrollRun.id != current_run.id).all())
    current_key = (current_run.period_end or current_run.pay_date, current_run.id)
    earlier = [(i, r) for i, r in rows if _trace_order_key(i, r) < current_key]
    caught = {c.get("payslipId") for i, _r in earlier for c in ((i.hkg_calculation_trace or {}).get("mpf") or {}).get("catchUp") or []}
    out = []
    for item, _run in sorted(earlier, key=lambda p: _trace_order_key(*p)):
        trace = item.hkg_calculation_trace or {}
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
    return dict(hkg_worker_facts=facts, hkg_hours=hours_input(db, employee, start, end, facts),
                hkg_rule_segments=rule_segments(rows, start, end))


# ── IR56G tax-clearance hold (§8) ───────────────────────────────────────

def _hold(db, organization_id, hold_id) -> HkgTaxClearanceHold:
    row = db.query(HkgTaxClearanceHold).filter(HkgTaxClearanceHold.id == hold_id,
                                               HkgTaxClearanceHold.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Hong Kong tax-clearance case", hold_id)
    return row


def _hold_view(hold: HkgTaxClearanceHold) -> dict:
    return {"state": hold.state, "expectedDepartureDate": _iso(hold.expected_departure_date),
            "filingDeadline": _iso(hold.filing_deadline), "filedDate": _iso(hold.filed_date),
            "statutoryHoldExpiry": _iso(hold.statutory_hold_expiry), "releaseBasis": hold.release_basis,
            "releasedAmount": None if hold.released_amount is None else str(hold.released_amount)}


def _transition(db, hold, target, actor_id, reason=None):
    if not hk_tc.can_transition(hold.state, target):
        raise BadRequestException(f"IR56G case cannot move from {hold.state} to {target}")
    old = _hold_view(hold)
    hold.state = target
    _audit(db, actor_id, "status_change", "hkg_tax_clearance_hold", hold.id, old=old, new=_hold_view(hold),
           reason=reason, commit=False)


def identify_departure(db: Session, organization_id: int, employee_id: int, expected_departure: date,
                       actor_id: Optional[int], identified_on: Optional[date] = None,
                       return_date: Optional[date] = None) -> HkgTaxClearanceHold:
    employee = _employee(db, employee_id, organization_id)
    identified_on = identified_on or date.today()
    facts = worker_facts(db, employee, identified_on) or {}
    timing = reporting_timing(db, identified_on)
    need = hk_ird.tax_clearance_required(timing, expected_departure, return_date,
                                          bool(facts.get("frequentTravelExempt")),
                                          facts.get("likelyChargeable") is not False)
    if not need["required"]:
        raise BadRequestException(f"IR56G / tax clearance is not required: {need['reason']}")
    open_case = (db.query(HkgTaxClearanceHold)
                 .filter(HkgTaxClearanceHold.organization_id == organization_id, HkgTaxClearanceHold.employee_id == employee_id,
                         HkgTaxClearanceHold.state != "CASE_CLOSED").first())
    if open_case is not None:
        raise BadRequestException(f"an open IR56G case (#{open_case.id}, {open_case.state}) already exists — change it instead")
    hold = HkgTaxClearanceHold(organization_id=organization_id, employee_id=employee_id,
                               expected_departure_date=expected_departure, identified_on=identified_on,
                               filing_deadline=hk_tc.filing_deadline(expected_departure, timing),
                               state=hk_tc.initial_state(identified_on, expected_departure, timing), prepared_by_id=actor_id)
    db.add(hold)
    db.flush()
    case = HkgIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type="IR56G",
                               year_of_assessment=year_of_assessment(expected_departure),
                               event_date=expected_departure, due_date=hold.filing_deadline, status="DUE",
                               prepared_by_id=actor_id)
    db.add(case)
    db.flush()
    hold.ird_case_id = case.id
    _audit(db, actor_id, "create", "hkg_tax_clearance_hold", hold.id, new=_hold_view(hold),
           reason=f"Departure identified; IR56G due by {hold.filing_deadline}", commit=False)
    db.commit()
    return hold


def record_ir56g_filed(db: Session, organization_id: int, hold_id: int, filed_on: date, filing_reference: str,
                       actor_id: Optional[int]) -> HkgTaxClearanceHold:
    """The operator filed IR56G through IRD's own channel: the hold becomes
    ACTIVE from the filing date (withhold all moneys payable)."""
    hold = _hold(db, organization_id, hold_id)
    if not filing_reference:
        raise BadRequestException("the IR56G filing reference is required")
    hold.filed_date = filed_on
    hold.statutory_hold_expiry = hk_tc.statutory_hold_expiry(filed_on, reporting_timing(db, filed_on))
    _transition(db, hold, "IR56G_FILED_HOLD_ACTIVE", actor_id, reason=f"IR56G filed {filed_on} ref {filing_reference}")
    case = db.query(HkgIrdReportingCase).filter(HkgIrdReportingCase.id == hold.ird_case_id).first()
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
    items = [i for i in q.all() if not (i.hkg_calculation_trace or {}).get("correction")]
    # A linked correction is booked to its ORIGINAL wage period but its money is
    # released when the correction is approved (D-14): it is held when THAT date
    # falls on / after the IR56G filing.
    from app.modules.payroll.models import HkgPayslipCorrection

    for corr in (db.query(HkgPayslipCorrection)
                 .filter(HkgPayslipCorrection.organization_id == hold.organization_id,
                         HkgPayslipCorrection.employee_id == hold.employee_id,
                         HkgPayslipCorrection.status == "APPROVED", HkgPayslipCorrection.delta_payslip_id.isnot(None)).all()):
        if corr.approved_at is not None and corr.approved_at.date() >= hold.filed_date:
            delta = db.get(PayslipItem, corr.delta_payslip_id)
            if delta is not None and dec(delta.net_pay) > ZERO:
                items.append(delta)
    return items


def refresh_hold_lines(db: Session, hold: HkgTaxClearanceHold) -> None:
    """Append a held-ledger line for every covered payslip not yet held.
    Lines are never deleted; a payslip's net pay stays owed (HK-013)."""
    if hold.state not in hk_tc.HOLDING_STATES or hold.filed_date is None:
        return
    held = {line.payslip_item_id for line in db.query(HkgTaxClearanceHoldLine).filter(HkgTaxClearanceHoldLine.hold_id == hold.id)}
    for item in _holding_payslips(db, hold):
        if item.id not in held:
            db.add(HkgTaxClearanceHoldLine(hold_id=hold.id, organization_id=hold.organization_id,
                                           payslip_item_id=item.id, amount=dec(item.net_pay)))
    db.flush()


def held_total(db: Session, hold: HkgTaxClearanceHold) -> Decimal:
    refresh_hold_lines(db, hold)          # the held ledger is always current
    return cents(sum((dec(l.amount) for l in db.query(HkgTaxClearanceHoldLine)
                      .filter(HkgTaxClearanceHoldLine.hold_id == hold.id, HkgTaxClearanceHoldLine.status == "HELD")), ZERO))


def request_hold_release(db: Session, organization_id: int, hold_id: int, basis: str, reference: Optional[str],
                         evidence_ref: str, actor_id: Optional[int]) -> HkgTaxClearanceHold:
    hold = _hold(db, organization_id, hold_id)
    if hold.state not in hk_tc.HOLDING_STATES:
        raise BadRequestException(f"no active hold to release (state {hold.state})")
    if basis not in hk_tc.RELEASE_BASES or not evidence_ref:
        raise BadRequestException(f"release needs a basis ({', '.join(hk_tc.RELEASE_BASES)}) and evidence")
    hold.release_basis, hold.release_reference, hold.release_evidence_ref = basis, reference, evidence_ref
    hold.release_requested_by_id = actor_id
    _audit(db, actor_id, "update", "hkg_tax_clearance_hold", hold.id, new={"releaseRequested": basis, "evidence": evidence_ref})
    return hold


def approve_hold_release(db: Session, organization_id: int, hold_id: int, actor_id: Optional[int],
                         on: Optional[date] = None) -> HkgTaxClearanceHold:
    """Four-eyes release: the approver must differ from the requester; the
    statute's conditions are re-checked here (never trusted from the request)."""
    hold = _hold(db, organization_id, hold_id)
    refresh_hold_lines(db, hold)
    refusal = hk_tc.release_refusal(hold.state, hold.release_basis, hold.release_reference, hold.release_evidence_ref,
                                    hold.filed_date, on or date.today(), hold.release_requested_by_id, actor_id,
                                    timing=reporting_timing(db, on or date.today()))
    if refusal:
        _audit(db, actor_id, "refused", "hkg_tax_clearance_hold", hold.id, new={"attempted": "release"}, reason=refusal)
        raise BadRequestException(refusal)
    amount = held_total(db, hold)
    now = datetime.utcnow()
    for line in db.query(HkgTaxClearanceHoldLine).filter(HkgTaxClearanceHoldLine.hold_id == hold.id,
                                                          HkgTaxClearanceHoldLine.status == "HELD"):
        line.status, line.released_at = "RELEASED", now
    hold.released_amount, hold.released_by_id, hold.released_at = amount, actor_id, now
    _transition(db, hold, "LETTER_OF_RELEASE_RECEIVED", actor_id,
                reason=f"released on {hold.release_basis} ({hold.release_reference or hold.release_evidence_ref})")
    db.commit()
    return hold


def change_departure(db: Session, organization_id: int, hold_id: int, reason: str, evidence_ref: str,
                     actor_id: Optional[int], new_departure: Optional[date] = None) -> HkgTaxClearanceHold:
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


def close_hold(db: Session, organization_id: int, hold_id: int, actor_id: Optional[int]) -> HkgTaxClearanceHold:
    hold = _hold(db, organization_id, hold_id)
    if hold.state == "DEPARTURE_CANCELLED_OR_CHANGED" and hold.filed_date is not None and held_total(db, hold) > ZERO:
        raise BadRequestException("the case still holds money — approve a release before closing it")
    _transition(db, hold, "CASE_CLOSED", actor_id)
    db.commit()
    return hold


def serialize_hold(db: Session, hold: HkgTaxClearanceHold) -> dict:
    lines = db.query(HkgTaxClearanceHoldLine).filter(HkgTaxClearanceHoldLine.hold_id == hold.id).all()
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
    holds = {h.employee_id: h for h in db.query(HkgTaxClearanceHold)
             .filter(HkgTaxClearanceHold.organization_id == organization_id, HkgTaxClearanceHold.state != "CASE_CLOSED")}
    from app.modules.payroll import hk_corrections

    correction_run = hk_corrections.is_correction_run(run)
    paid_on = hk_corrections.effective_payment_date(db, run)
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

def _case(db, organization_id, case_id) -> HkgIrdReportingCase:
    row = db.query(HkgIrdReportingCase).filter(HkgIrdReportingCase.id == case_id,
                                               HkgIrdReportingCase.organization_id == organization_id).first()
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
                 PayslipItem.hkg_calculation_trace.isnot(None),
                 PayrollRun.pay_date >= start, PayrollRun.pay_date <= end))
    if employee_id is not None:
        q = q.filter(PayslipItem.employee_id == employee_id)
    return q.all()


def create_event_cases(db: Session, organization_id: int, employee_id: int, actor_id: Optional[int]) -> list:
    """IR56E / IR56F from the effective profile facts (IR56G is created by
    identify_departure). Idempotent per (form, event date)."""
    employee = _employee(db, employee_id, organization_id)
    facts = worker_facts(db, employee, date.today()) or {}
    created = []

    def ensure(form, event):
        existing = (db.query(HkgIrdReportingCase)
                    .filter(HkgIrdReportingCase.organization_id == organization_id,
                            HkgIrdReportingCase.employee_id == employee_id, HkgIrdReportingCase.form_type == form,
                            HkgIrdReportingCase.event_date == event).first())
        if existing is not None:
            return
        row = HkgIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type=form,
year_of_assessment=year_of_assessment(event), event_date=event,
                                   due_date=hk_ird.due_date(form, reporting_timing(db, event), event_date=event),
                                   status="DUE", prepared_by_id=actor_id)
        db.add(row)
        db.flush()
        created.append(row)
        _audit(db, actor_id, "create", "hkg_ird_reporting_case", row.id, new={"form": form, "event": event.isoformat()},
               commit=False)

    if employee.date_of_joining and facts.get("likelyChargeable"):
        ensure("IR56E", employee.date_of_joining)
    termination = facts.get("terminationDate")
    if termination and not facts.get("expectedDepartureDate"):
        ensure("IR56F", date.fromisoformat(termination))
    db.commit()
    return created


def generate_annual_return(db: Session, organization_id: int, ya: str, actor_id: Optional[int]) -> dict:
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
    cover_filed = (db.query(HkgIrdReportingCase.id)
                   .filter(HkgIrdReportingCase.organization_id == organization_id, HkgIrdReportingCase.form_type == "BIR56A",
                           HkgIrdReportingCase.year_of_assessment == ya,
                           HkgIrdReportingCase.status.in_(hk_ird.FILED_STATES)).first() is not None)
    for employee_id, pairs in sorted(by_employee.items()):
        employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == employee_id).first()
        fields, gross = {}, ZERO
        for item, _run in pairs:
            # Paid gross: the unpaid-day deduction is not remuneration.
            gross += dec(item.gross_pay) - dec(getattr(item, "attendance_deduction", None))
            for field, amount in ((item.hkg_calculation_trace or {}).get("ird") or {}).get("reportable", {}).items():
                fields[field] = fields.get(field, ZERO) + dec(amount)
        reported = sum(fields.values(), ZERO)
        payroll_total += gross
        period = hk_ird.employee_period_in_year(ya, employee.date_of_joining or start, employee.date_of_leaving)
        # An IR56F / IR56G reports income from the start of the year (or of
        # the employment) to the cessation / departure (its event date).
        prior = [{"id": c.id, "formType": c.form_type, "status": c.status,
                  "incomePeriodStart": _iso(c.income_period_start or period[0]),
                  "incomePeriodEnd": _iso(c.income_period_end or c.event_date)}
                 for c in db.query(HkgIrdReportingCase).filter(
                     HkgIrdReportingCase.organization_id == organization_id, HkgIrdReportingCase.employee_id == employee_id,
                     HkgIrdReportingCase.year_of_assessment == ya,
                     HkgIrdReportingCase.form_type.in_(("IR56F", "IR56G")))]
        decision = hk_ird.ir56b_suppression(ya, period, prior)
        existing = (db.query(HkgIrdReportingCase)
                    .filter(HkgIrdReportingCase.organization_id == organization_id, HkgIrdReportingCase.employee_id == employee_id,
                            HkgIrdReportingCase.form_type == "IR56B", HkgIrdReportingCase.year_of_assessment == ya,
                            HkgIrdReportingCase.status.notin_(("AMENDED", "CANCELLED"))).first())
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
        row = existing or HkgIrdReportingCase(organization_id=organization_id, employee_id=employee_id, form_type="IR56B",
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
        row.source_payroll_hash = canonical_hash([(i.id, str(i.gross_pay), canonical_hash(i.hkg_calculation_trace)) for i, _r in pairs])
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
    cover = (db.query(HkgIrdReportingCase)
             .filter(HkgIrdReportingCase.organization_id == organization_id, HkgIrdReportingCase.form_type == "BIR56A",
                     HkgIrdReportingCase.year_of_assessment == ya,
                     HkgIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
             .order_by(HkgIrdReportingCase.id.desc()).first())
    if cover is None or cover.status not in hk_ird.FILED_STATES + ("REJECTED",):
        cover = cover or HkgIrdReportingCase(organization_id=organization_id, form_type="BIR56A", year_of_assessment=ya,
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
    _audit(db, actor_id, "create", "hkg_ird_annual_return", cover.id,
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
        ird = (((item.hkg_calculation_trace or {}).get("classification") or {}).get("IRD") or {})
        total += dec(ird.get("excluded")) + dec(ird.get("review"))
    return total


SUBMISSION_MODES = ("ONLINE_MODE", "MIXED_MODE", "INTERNAL_PREPARATION_ONLY")
AMENDMENT_TYPES = ("ORIGINAL", "ADDITIONAL", "REPLACEMENT", "SUPPLEMENTARY")


def _record_submission(db, case: HkgIrdReportingCase, submission: Optional[dict], actor_id) -> None:
    """The external-submission record a FILED transition requires. Zoiko never
    transmits to the IRD: this records HOW the employer submitted, from its
    evidence. ONLINE_MODE / MIXED_MODE submit Zoiko's DATA FILE, which the IRD
    accepts only from approved software — refused unless the platform's IRD
    software approval is received, unexpired and covers the form. Internal
    validation alone never satisfies that (it is an IRD decision)."""
    from app.modules.payroll import hk_control

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
        refusal = hk_control.software_approval_refusal(db, case.form_type, submitted_on)
        if refusal:
            raise BadRequestException(refusal)
    case.submission_mode, case.authorized_signer = mode, sub["authorizedSigner"].strip()
    case.transaction_reference, case.control_list_reference = sub.get("transactionReference"), sub.get("controlListReference")
    case.submitted_on, case.uploaded_by_id = submitted_on, actor_id


def transition_ird_case(db: Session, organization_id: int, case_id: int, target: str, actor_id: Optional[int],
                        filing_reference: str = None, receipt_reference: str = None,
                        submission: Optional[dict] = None) -> HkgIrdReportingCase:
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
        _four_eyes(case.prepared_by_id, actor_id, "Filing an IRD return / notification")
        _record_submission(db, case, submission, actor_id)
        case.filing_reference, case.filed_at, case.approved_by_id = filing_reference, datetime.utcnow(), actor_id
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
    _audit(db, actor_id, "status_change", "hkg_ird_reporting_case", case.id, old={"status": old}, new=new)
    return case


def ird_case_history(db: Session, organization_id: int, case_id: int) -> list:
    """The case's lifecycle from the immutable audit trail (filings,
    rejections with the filed evidence, re-preparations, re-filings)."""
    from app.modules.payroll.models import TaxConfigurationAudit

    case = _case(db, organization_id, case_id)                  # 404 outside the tenant
    rows = (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "hkg_ird_reporting_case", TaxConfigurationAudit.entity_id == case.id)
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


def amend_ird_case(db: Session, organization_id: int, case_id: int, reason: str, actor_id: Optional[int],
                   commit: bool = True, amendment_type: str = "REPLACEMENT") -> HkgIrdReportingCase:
    """A NEW linked case replaces a filed one; the accepted evidence (payload,
    hash, receipt) of the original is never overwritten.

    amendment_type: REPLACEMENT (the original is superseded). SUPPLEMENTARY
    (additional income only, the original stays in force) is refused — the
    IRD's supplementary-return specification is not archived (G2) and Zoiko
    will not invent its layout. ADDITIONAL is not an amendment: it is set
    automatically on an IR56B first prepared after the year's BIR56A was
    filed."""
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
    amendment = HkgIrdReportingCase(
        organization_id=organization_id, employee_id=original.employee_id, form_type=original.form_type,
        year_of_assessment=original.year_of_assessment, event_date=original.event_date, due_date=original.due_date,
        income_period_start=original.income_period_start, income_period_end=original.income_period_end,
        status="PREPARED", schema_version=original.schema_version, payload=copy.deepcopy(original.payload),
        payload_hash=original.payload_hash, reported_income=copy.deepcopy(original.reported_income),
        validation_errors=[], amends_case_id=original.id, prepared_by_id=actor_id, amendment_type=amendment_type)
    db.add(amendment)
    original.status = "AMENDED"
    db.flush()
    _audit(db, actor_id, "create", "hkg_ird_reporting_case", amendment.id,
           new={"amends": original.id, "form": original.form_type, "amendmentType": amendment_type}, reason=reason,
           commit=False)
    if commit:
        db.commit()
    return amendment


def xml_lifecycle_state(db: Session, case: HkgIrdReportingCase) -> str:
    """The IRD data-file lifecycle view of a case (DRAFT / VALIDATED /
    READY_FOR_EXTERNAL_SUBMISSION / SUBMITTED_EXTERNALLY / ACKNOWLEDGED /
    REJECTED / AMENDMENT_REQUIRED / SUPERSEDED). READY_FOR_EXTERNAL_SUBMISSION
    is shown ONLY when the IRD software approval covers the form — internal
    validation alone never makes a data file submittable. A filed case with an
    unfiled replacement in progress is AMENDMENT_REQUIRED."""
    from app.modules.payroll import hk_control

    status = case.status
    if status in ("DUE", "PREPARED"):
        return "DRAFT"
    if status == "VALIDATED":
        return ("READY_FOR_EXTERNAL_SUBMISSION" if hk_control.software_approval_refusal(db, case.form_type, date.today()) is None
                else "VALIDATED")
    if status in ("FILED", "ACCEPTED", "ACKNOWLEDGED"):
        pending = (db.query(HkgIrdReportingCase.id)
                   .filter(HkgIrdReportingCase.amends_case_id == case.id,
                           HkgIrdReportingCase.status.notin_(hk_ird.FILED_STATES + ("CANCELLED", "AMENDED"))).first())
        if pending:
            return "AMENDMENT_REQUIRED"
        return "SUBMITTED_EXTERNALLY" if status == "FILED" else "ACKNOWLEDGED"
    if status == "REJECTED":
        return "REJECTED"
    if status == "AMENDED":
        return "SUPERSEDED"
    return status                                               # SUPPRESSED / CANCELLED: not a data file


def serialize_ird_case(case: HkgIrdReportingCase) -> dict:
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
                                   actor_id: Optional[int]) -> HkgIrdReportingCase:
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
    _audit(db, actor_id, "update", "hkg_ird_reporting_case", case.id,
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
        trace = item.hkg_calculation_trace or {}
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
                           overtime_constant: bool = False) -> HkgAverageWageSnapshot:
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
    snap = HkgAverageWageSnapshot(
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
    _audit(db, actor_id, "create", "hkg_average_wage_snapshot", snap.id,
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
    _audit(db, actor_id, "update", "hkg_average_wage_snapshot", snap.id,
           new={"overrideRequested": str(value), "evidence": evidence_ref}, reason=reason)
    return snap


def approve_average_wage_override(db, organization_id, snapshot_id, actor_id):
    snap = _snapshot(db, organization_id, snapshot_id)
    if snap.override_average_daily_wage is None:
        raise BadRequestException("no override has been requested")
    _four_eyes(snap.override_requested_by_id, actor_id, "An average-wage override")
    snap.override_approved_by_id, snap.status = actor_id, "OVERRIDDEN"
    _audit(db, actor_id, "status_change", "hkg_average_wage_snapshot", snap.id,
           new={"status": "OVERRIDDEN", "calculated": str(snap.average_daily_wage),
                "override": str(snap.override_average_daily_wage)})
    return snap


def _snapshot(db, organization_id, snapshot_id) -> HkgAverageWageSnapshot:
    snap = db.query(HkgAverageWageSnapshot).filter(HkgAverageWageSnapshot.id == snapshot_id,
                                                   HkgAverageWageSnapshot.organization_id == organization_id).first()
    if snap is None:
        raise NotFoundException("Hong Kong average-wage snapshot", snapshot_id)
    return snap


def effective_average(snap: HkgAverageWageSnapshot) -> dict:
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
                          actor_id: Optional[int]) -> HkgTerminationResult:
    employee = _employee(db, employee_id, organization_id)
    termination = date.fromisoformat(str(data["terminationDate"]))
    facts = worker_facts(db, employee, termination)
    if facts is None:
        raise BadRequestException("no Hong Kong statutory profile is in force on the termination date")
    start = date.fromisoformat(facts.get("employmentContinuityStart") or facts["dateOfJoining"])
    rate_map, _slabs, pack = pack_inputs(db, termination)
    cc = continuous_contract(db, organization_id, employee_id, termination)
    active_hold = db.query(HkgTaxClearanceHold).filter(
        HkgTaxClearanceHold.organization_id == organization_id, HkgTaxClearanceHold.employee_id == employee_id,
        HkgTaxClearanceHold.state.in_(hk_tc.HOLDING_STATES)).first() is not None
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
    for prior in db.query(HkgTerminationResult).filter(HkgTerminationResult.organization_id == organization_id,
                                                       HkgTerminationResult.employee_id == employee_id,
                                                       HkgTerminationResult.status == "CALCULATED"):
        prior.status = "SUPERSEDED"
    row = HkgTerminationResult(organization_id=organization_id, employee_id=employee_id, termination_date=termination,
                               termination_reason=data["reason"], payment_type=result["paymentType"],
                               gross_entitlement=dec(result["grossEntitlement"]), total_offsets=dec(result["totalOffsets"]),
                               net_statutory_payment=dec(result["netStatutoryPayment"]), result=result,
                               evidence_hash=result["evidenceHash"], created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "create", "hkg_termination_result", row.id,
           new={"paymentType": row.payment_type, "net": str(row.net_statutory_payment), "evidenceHash": row.evidence_hash},
           commit=False)
    db.commit()
    return row


def list_termination_results(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    """Termination calculations of the tenant — so a DIFFERENT operator can find
    and approve one (four-eyes), and an approved one can be issued as a statement."""
    q = db.query(HkgTerminationResult).filter(HkgTerminationResult.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(HkgTerminationResult.employee_id == employee_id)
    return [{"id": r.id, "employeeId": r.employee_id, "terminationDate": _iso(r.termination_date),
             "reason": r.termination_reason, "paymentType": r.payment_type,
             "grossEntitlement": str(r.gross_entitlement), "totalOffsets": str(r.total_offsets),
             "netStatutoryPayment": str(r.net_statutory_payment),
             "totalFinalPayment": (r.result or {}).get("totalFinalPayment"), "status": r.status,
             "createdById": r.created_by_id, "approvedById": r.approved_by_id, "evidenceHash": r.evidence_hash}
            for r in q.order_by(HkgTerminationResult.id.desc()).all()]


def list_average_wage_snapshots(db: Session, organization_id: int, employee_id: int) -> list:
    """An employee's average-wage snapshots with their override state — so a
    requested override can be found and approved by a different operator."""
    _employee(db, employee_id, organization_id)
    rows = (db.query(HkgAverageWageSnapshot)
            .filter(HkgAverageWageSnapshot.organization_id == organization_id,
                    HkgAverageWageSnapshot.employee_id == employee_id)
            .order_by(HkgAverageWageSnapshot.id.desc()).all())
    return [{"id": s.id, "benefitType": s.benefit_type, "referenceDate": _iso(s.reference_date),
             "lookbackStart": _iso(s.lookback_start), "lookbackEnd": _iso(s.lookback_end),
             "averageDailyWage": str(s.average_daily_wage), "status": s.status,
             "overrideRequested": None if s.override_average_daily_wage is None else str(s.override_average_daily_wage),
             "overrideReason": s.override_reason, "overrideRequestedById": s.override_requested_by_id,
             "overrideApprovedById": s.override_approved_by_id} for s in rows]


def approve_termination(db: Session, organization_id: int, result_id: int, actor_id: Optional[int]) -> HkgTerminationResult:
    row = db.query(HkgTerminationResult).filter(HkgTerminationResult.id == result_id,
                                                HkgTerminationResult.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Hong Kong termination result", result_id)
    if row.status != "CALCULATED":
        raise BadRequestException(f"only a CALCULATED result can be approved (this one is {row.status})")
    _four_eyes(row.created_by_id, actor_id, "Approving a termination calculation")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    _audit(db, actor_id, "status_change", "hkg_termination_result", row.id, new={"status": "APPROVED"})
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


def prepare_empf_submission(db: Session, organization_id: int, period: str, actor_id: Optional[int]) -> HkgEmpfSubmission:
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
    submitted = (db.query(HkgEmpfSubmission)
                 .filter(HkgEmpfSubmission.organization_id == organization_id,
                         HkgEmpfSubmission.contribution_period == period,
                         HkgEmpfSubmission.status.in_(("SUBMITTED", "ACCEPTED", "PARTIAL", "PAID", "RECONCILED")))
                 .order_by(HkgEmpfSubmission.id).all())
    already = {r.get("payslipId") for sub in submitted for r in (sub.rows or [])}
    for sub in submitted:           # rows the eMPF rejected are not "included" — they go again
        already -= {o.get("payslipId") for o in (sub.row_outcomes or []) if o.get("status") == "REJECTED"}
    for item, run in _committed_hk_payslips(db, organization_id, start - timedelta(days=62), end + timedelta(days=62)):
        trace = item.hkg_calculation_trace or {}
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
        from app.modules.payroll.employee_validation import mask_identifier

        rows.append({"payslipId": item.id, "employeeId": item.employee_id, "name": getattr(employee, "name", None),
                     "hkid": mask_identifier(cf.get("hkid") or cf.get("passport_number")),
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
    same = (db.query(HkgEmpfSubmission)
            .filter(HkgEmpfSubmission.organization_id == organization_id,
                    HkgEmpfSubmission.contribution_period == period,
                    HkgEmpfSubmission.status.in_(("PREPARED", "VALIDATED")),
                    HkgEmpfSubmission.payload_hash == payload_hash)
            .order_by(HkgEmpfSubmission.id.desc()).first())
    if (same is not None and same.supplements_submission_id == supplements and same.contribution_day == contribution_day
            and list(same.validation_errors or []) == errors):
        return same
    sub = HkgEmpfSubmission(organization_id=organization_id, contribution_period=period,
                            supplements_submission_id=supplements,
                            status="VALIDATED" if not errors and rows else "PREPARED", rows=rows, totals=totals,
                            payload_hash=payload_hash, validation_errors=errors,
                            contribution_day=contribution_day,
                            prepared_by_id=actor_id)
    db.add(sub)
    db.flush()
    # Duplicate protection: an earlier batch for the same period that was never
    # submitted is superseded by this one, so two batches can never both be
    # remitted for the same contributions.
    for stale in (db.query(HkgEmpfSubmission)
                  .filter(HkgEmpfSubmission.organization_id == organization_id,
                          HkgEmpfSubmission.contribution_period == period, HkgEmpfSubmission.id != sub.id,
                          HkgEmpfSubmission.status.in_(("PREPARED", "VALIDATED"))).all()):
        previous = stale.status
        stale.status = "AMENDED"
        stale.validation_errors = list(stale.validation_errors or []) + [
            f"superseded by batch #{sub.id} prepared for the same period"]
        _audit(db, actor_id, "status_change", "hkg_empf_submission", stale.id, old={"status": previous},
               new={"status": "AMENDED", "supersededBy": sub.id}, commit=False)
    _audit(db, actor_id, "create", "hkg_empf_submission", sub.id, new={"period": period, **totals}, commit=False)
    db.commit()
    return sub


def transition_empf_submission(db: Session, organization_id: int, submission_id: int, target: str,
                               actor_id: Optional[int], submission_reference: str = None, row_outcomes: list = None,
                               settlement_reference: str = None) -> HkgEmpfSubmission:
    sub = db.query(HkgEmpfSubmission).filter(HkgEmpfSubmission.id == submission_id,
                                             HkgEmpfSubmission.organization_id == organization_id).first()
    if sub is None:
        raise NotFoundException("Hong Kong eMPF submission", submission_id)
    if target not in EMPF_TRANSITIONS.get(sub.status, ()):
        raise BadRequestException(f"eMPF submission #{sub.id} cannot move from {sub.status} to {target}")
    if target == "SUBMITTED":
        if not submission_reference:
            raise BadRequestException("the eMPF submission reference is required (recorded from the eMPF platform)")
        _four_eyes(sub.prepared_by_id, actor_id, "An eMPF submission")
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
    _audit(db, actor_id, "status_change", "hkg_empf_submission", sub.id, old={"status": old},
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
    from app.modules.payroll.service import _sg_pack_rows_for_golden

    rate_map, slabs = _sg_pack_rows_for_golden(db, pack, on)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.organization_id.is_(None)).all()
    return rate_map, slabs, rule_segments(rows, *period)


def pack_golden_check(db: Session, pack: JurisdictionPack) -> dict:
    """Every HK golden vector whose pay date is inside the pack window,
    re-run with the fixture's embedded rows REPLACED by this pack's rows."""
    import json
    from pathlib import Path

    from app.modules.payroll.hmrc_golden_harness import GoldenCaseMismatch, run_golden_case

    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hk_golden"
    in_window, passed, failures = 0, 0, []
    for path in sorted(fixtures.glob("*.json")) if fixtures.exists() else []:
        case = json.loads(path.read_text(encoding="utf-8"))
        ctx = case["context"]
        pay = date.fromisoformat(ctx["pay_date"])
        if not (pack.effective_from and pack.effective_from <= pay and (pack.effective_to is None or pay <= pack.effective_to)):
            continue
        in_window += 1
        bound = copy.deepcopy(case)
        period = (date.fromisoformat(ctx.get("period_start") or pay.replace(day=1).isoformat()),
                  date.fromisoformat(ctx.get("period_end") or pay.isoformat()))
        rm, sl, seg = _pack_rows_for_golden(db, pack, pay, period)
        bound["context"]["rate_map"], bound["context"]["slabs"], bound["context"]["hkg_rule_segments"] = rm, sl, seg
        try:
            run_golden_case(bound)
            passed += 1
        except GoldenCaseMismatch as e:
            failures.append({"case": path.stem, "diffs": [{"field": d["field"], "expected": str(d["expected"]),
                                                           "actual": str(d["actual"])} for d in e.diffs]})
        except Exception as e:                                       # noqa: BLE001 — a crash is a failure
            failures.append({"case": path.stem, "error": f"{type(e).__name__}: {e}"})
    return {"casesInWindow": in_window, "passed": passed, "failures": failures}


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
    from app.modules.payroll import hk_configuration

    cfg = hk_configuration.domains(db, pack.id)
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
        "activationReadiness": _governance().activation_readiness(db),
        "templateCoverage": _governance().template_coverage(db),
        "ownerDecisions": _governance().owner_decisions(db),
        "externalDependencies": _governance().external_dependencies(db),
        "externalBlockers": [
            "IRD XML schemas / sample files for BIR56A, IR56B/E/F/G not archived — e-filing export gated (G2)",
            "No certified eMPF interface or test credentials — submissions recorded from operator evidence only (G2)",
            "Hong Kong specialist certification of [G1] rows (earning classification, week start, partial-month MPF basis)",
            "Parallel payroll cycles (G3), PDPO / privacy review (G5), operations runbooks (G6), launch approvals (G7)",
            "Industry Scheme (construction/catering casual), domestic helpers, ORSO scheme rules — out of launch scope",
            "Bilingual English / Traditional Chinese statutory output not validated",
        ],
    }


def _governance():
    from app.modules.payroll import hk_governance

    return hk_governance


def preview_calculation(db: Session, data) -> dict:
    """Super Admin read-only preview: the PRODUCTION engine (calculate_payroll
    → countries/hong_kong.py) against the rows of the HK pack whose window
    contains the pay date — any status, so a Draft pack can be checked before
    activation. Creates / changes nothing."""
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.service import _sg_pack_rows_for_golden
    from app.modules.payroll.hmrc_golden_harness import _build_rate_map, _build_slabs

    pack = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == HK, JurisdictionPack.pack_type == "tax",
                                              JurisdictionPack.effective_from <= data.payDate,
                                              JurisdictionPack.effective_to >= data.payDate)
            .order_by(JurisdictionPack.effective_from.desc()).first())
    if pack is None:
        raise BadRequestException(f"no Hong Kong pack covers {data.payDate}")
    ps = data.periodStart or data.payDate.replace(day=1)
    pe = data.periodEnd or data.payDate
    rate_map, slabs = _sg_pack_rows_for_golden(db, pack, data.payDate)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.organization_id.is_(None)).all()
    facts = {"profileId": "PREVIEW", "dateOfBirth": data.dateOfBirth.isoformat(), "dateOfJoining": data.dateOfJoining.isoformat(),
             **(data.workerFacts or {})}
    ctx = PayrollContext(gross=dec(data.gross), basic=dec(data.gross), country=HK, pay_frequency=data.payFrequency,
                         pay_date=data.payDate, period_start=ps, period_end=pe,
                         rate_map=_build_rate_map(rate_map), slabs=_build_slabs(slabs),
                         hkg_worker_facts=facts, hkg_hours=data.hours or {}, hkg_rule_segments=rule_segments(rows, ps, pe))
    try:
        result = calculate_payroll(ctx, "standard")
    except HongKongCalculationBlockedError as exc:
        return {"status": "BLOCKED", "key": exc.key, "reason": exc.reason, "packId": pack.pack_id, "packStatus": pack.status}
    return {"status": "CALCULATED", "packId": pack.pack_id, "packVersion": pack.version, "packStatus": pack.status,
            "mpfEmployee": str(result.employee_pension), "mpfEmployer": str(result.employer_pension),
            "incomeTaxWithheld": str(result.tds), "netPay": str(result.net_pay),
            "trace": result.hkg_calculation_trace, "writes": "NONE"}

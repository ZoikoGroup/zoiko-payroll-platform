"""
payroll/netherlands_org_router.py
---------------------------------
Organisation API for Netherlands payroll (ZP-NL-ENG-001 Phase 12), mounted
inside payroll_router as /api/payroll/netherlands (so the subscription gate
applies).

Rules every route follows:
  * The organisation is ALWAYS the caller's own (current_user.organization_id);
    no route takes an organisation id. A principal without an organisation
    (Super Admin) uses the Super Admin workspace instead.
  * Every employee / record / run / return id is checked against that
    organisation before the service is called — several service functions
    look rows up by id alone.
  * Reads need a payroll operator (org_admin or payroll_admin). The employer
    registration is changed by an org admin only.
  * Statutory facts are never typed in: no tax-credit amount, no AWf class, no
    premium percentage. Contracts and tax-credit instructions are new versions,
    never edits (the AWf class is always derived from the contract).
  * Authority transport (filing, Digipoort, authority payments) stays LOCKED
    until gate G3 — exactly as in the Super Admin workspace.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database import get_db

router = APIRouter(prefix="/netherlands", tags=["Netherlands (Organisation)"])

NL = "NL"


# ── helpers ──────────────────────────────────────────────────────────────────

def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _cols(obj, exclude=()) -> Dict[str, Any]:
    return {c.name: _plain(getattr(obj, c.name)) for c in obj.__table__.columns if c.name not in exclude}


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Netherlands payroll routes act on your own organisation; "
                                 "Super Admin uses the Super Admin Netherlands workspace.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _date(payload: dict, key: str, required: bool = True) -> Optional[date]:
    raw = payload.get(key)
    if raw in (None, ""):
        if required:
            raise BadRequestException(f"{key} is required")
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise BadRequestException(f"{key} must be a date (YYYY-MM-DD)")


def _dec(payload: dict, key: str, required: bool = True, default: Optional[str] = None) -> Optional[Decimal]:
    raw = payload.get(key)
    if raw in (None, ""):
        if required and default is None:
            raise BadRequestException(f"{key} is required")
        return None if default is None else Decimal(default)
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise BadRequestException(f"{key} must be a number")


def _employee(db: Session, org_id: int, employee_id: int):
    from app.modules.payroll.models import PayrollEmployee

    emp = (db.query(PayrollEmployee)
           .filter(PayrollEmployee.id == employee_id, PayrollEmployee.organization_id == org_id).first())
    if emp is None:
        raise NotFoundException("PayrollEmployee", employee_id)
    if (emp.country_code or "").upper() != NL:
        raise BadRequestException("this employee is not on Netherlands payroll")
    return emp


def _owned(db: Session, model, row_id: int, org_id: int):
    row = db.query(model).filter(model.id == row_id, model.organization_id == org_id).first()
    if row is None:
        raise NotFoundException(model.__name__, row_id)
    return row


def _run(db: Session, org_id: int, run_id: int):
    from app.modules.payroll.models import PayrollRun

    return _owned(db, PayrollRun, run_id, org_id)


def _locked(action: str):
    raise BadRequestException(
        f"Netherlands {action} is locked until gate G3 is signed (official Gegevensspecificaties, PKIoverheid "
        "certificate and Digipoort test access). Returns can be built and reconciled, not transmitted.")


def _json(model) -> dict:
    return model.model_dump(mode="json")


# ── employer registration (spec §10, panels A–H) ─────────────────────────────

@router.get("/employer-profile", summary="Your Netherlands employer registration in force (null when none)")
def get_employer_profile(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    try:
        return _json(nl.get_employer_profile(db, organization_id=_org_id(current_user)))
    except NotFoundException:
        return None


@router.post("/employer-profile", summary="Record a new employer-registration version (org admin)")
def create_employer_profile(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    from pydantic import ValidationError

    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_schemas import EmployerProfileCreate

    try:
        data = EmployerProfileCreate(**payload)
    except ValidationError as exc:
        raise BadRequestException(f"invalid employer registration: {exc.errors()[0].get('msg')}")
    result = nl.create_employer_profile(db, organization_id=_org_id(current_user), data=data,
                                        actor_id=_actor(current_user))
    db.commit()
    return _json(result)


@router.get("/readiness", summary="Readiness card H plus the platform's G1–G8 launch gates")
def get_readiness(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    org_id = _org_id(current_user)
    try:
        card = _json(nl.get_employer_readiness_card(db, organization_id=org_id))
    except NotFoundException:
        card = None
    return {"employer": card, "gates": nl.gate_states(db)}


# ── catalogs the organisation picks from (read-only here) ────────────────────

@router.get("/caos", summary="Netherlands collective agreements (governed registry, read-only)")
def list_caos(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll.models import CollectiveAgreement as M

    org_id = _org_id(current_user)
    rows = (db.query(M).filter(M.jurisdiction_country == NL,
                               or_(M.organization_id.is_(None), M.organization_id == org_id))
            .order_by(M.name).all())
    return [{k: _plain(getattr(r, k, None)) for k in ("id", "agreement_code", "name", "agreement_type",
                                                      "employee_group", "version", "effective_from",
                                                      "effective_to", "status")} for r in rows]


@router.get("/pension-schemes", summary="Pension schemes: platform catalog + your own (read-only)")
def list_pension_schemes(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlPensionScheme as M

    org_id = _org_id(current_user)
    rows = (db.query(M).filter(or_(M.organization_id.is_(None), M.organization_id == org_id))
            .order_by(M.fund_name, M.effective_from.desc()).all())
    return [_cols(r) for r in rows]


@router.get("/wkr", summary="Work-related costs scheme: committed accumulator revisions + settlements (read-only)")
def get_wkr(tax_year: int = Query(...), current_user=Depends(get_current_payroll_operator),
            db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlWkrAccumulator as A, PayrollNlWkrSettlement as S

    org_id = _org_id(current_user)
    revisions = (db.query(A).filter(A.organization_id == org_id, A.tax_year == tax_year)
                 .order_by(A.revision.desc()).all())
    settlements = (db.query(S).filter(S.organization_id == org_id, S.tax_year == tax_year)
                   .order_by(S.id.desc()).all())
    return {"taxYear": tax_year, "latest": _cols(revisions[0]) if revisions else None,
            "revisions": [_cols(r) for r in revisions], "settlements": [_cols(s) for s in settlements]}


@router.get("/absence-pay-policies", summary="Your sickness-pay policies")
def list_absence_pay_policies(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlAbsencePayPolicy as M

    rows = (db.query(M).filter(M.organization_id == _org_id(current_user))
            .order_by(M.effective_from.desc()).all())
    return [_cols(r) for r in rows]


@router.post("/absence-pay-policies", summary="Record a sickness-pay policy (org admin)")
def create_absence_pay_policy(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    row = nl.create_absence_pay_policy(
        db, organization_id=_org_id(current_user), effective_from=_date(payload, "effective_from"),
        year1_pct=_dec(payload, "year1_pct"), year2_pct=_dec(payload, "year2_pct"),
        waiting_days=int(payload.get("waiting_days") or 0),
        year1_min_wage_floor=bool(payload.get("year1_min_wage_floor", True)))
    db.commit()
    db.refresh(row)
    return _cols(row)


# ── one employee's Netherlands record ────────────────────────────────────────

@router.get("/employees/{employee_id}", summary="Everything Netherlands payroll holds for one employee")
def get_employee_record(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import (PayrollNlCompanyCar, PayrollNlExpatDecision, PayrollNlSicknessEvent,
                                            PayrollNlTerminationSettlement)

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)

    def rows(model, order):
        return [_cols(r) for r in db.query(model).filter(model.organization_id == org_id,
                                                         model.employee_id == emp.id).order_by(order).all()]

    try:
        fields = _json(nl.get_employee_nl_fields(db, employee_id=emp.id))
    except NotFoundException:
        fields = None
    return {
        "employee": {"id": emp.id, "name": emp.name, "employeeCode": emp.employee_code,
                     "bsnRecorded": bool((emp.compliance_fields or {}).get("bsn"))},
        "statutoryFields": fields,
        "incomeRelationships": [_json(r) for r in nl.get_income_relationships(db, organization_id=org_id,
                                                                              employee_id=emp.id)],
        "taxCreditInstructions": [_json(r) for r in nl.get_tax_credit_instructions(db, organization_id=org_id,
                                                                                   employee_id=emp.id)],
        "contracts": [_json(r) for r in nl.get_contract_versions(db, organization_id=org_id, employee_id=emp.id)],
        "companyCars": rows(PayrollNlCompanyCar, PayrollNlCompanyCar.effective_from.desc()),
        "expatDecisions": rows(PayrollNlExpatDecision, PayrollNlExpatDecision.granted_from.desc()),
        "sicknessEvents": rows(PayrollNlSicknessEvent, PayrollNlSicknessEvent.first_sick_day.desc()),
        "terminationSettlements": rows(PayrollNlTerminationSettlement, PayrollNlTerminationSettlement.id.desc()),
    }


@router.post("/employees/{employee_id}/income-relationships", summary="Open an income relationship (IKV)")
def create_income_relationship(employee_id: int, payload: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from pydantic import ValidationError

    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_schemas import IncomeRelationshipCreate

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    try:
        data = IncomeRelationshipCreate(**{**payload, "employeeId": emp.id})
    except ValidationError as exc:
        raise BadRequestException(f"invalid income relationship: {exc.errors()[0].get('msg')}")
    result = nl.create_income_relationship(db, organization_id=org_id, employee_id=emp.id, data=data,
                                           actor_id=_actor(current_user))
    db.commit()
    return _json(result)


@router.put("/income-relationships/{ikv_id}/close", summary="Close an income relationship (end date + reason)")
def close_income_relationship(ikv_id: int, payload: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlIncomeRelationship
    from app.modules.payroll.netherlands_schemas import IncomeRelationshipUpdate

    _owned(db, PayrollNlIncomeRelationship, ikv_id, _org_id(current_user))
    reason = (payload.get("closedReason") or "").strip()
    if not reason:
        raise BadRequestException("closing an income relationship needs a reason")
    result = nl.update_income_relationship(
        db, ikv_id=ikv_id, actor_id=_actor(current_user),
        data=IncomeRelationshipUpdate(endDate=_date(payload, "endDate"), status="CLOSED", closedReason=reason))
    db.commit()
    return _json(result)


@router.post("/employees/{employee_id}/tax-credit-instructions",
             summary="Record the employee's signed loonheffingskorting instruction (supersedes the active one)")
def create_tax_credit_instruction(employee_id: int, payload: Dict[str, Any] = Body(...),
                                  current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from pydantic import ValidationError

    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_schemas import TaxCreditInstructionCreate

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    # Only the employee's yes/no instruction is captured — never a credit amount.
    allowed = {k: payload[k] for k in ("applyTaxCredit", "formVersion", "signedAt", "effectiveFrom",
                                       "signedDocumentArtifactId") if k in payload}
    try:
        data = TaxCreditInstructionCreate(**allowed, employeeId=emp.id)
    except ValidationError as exc:
        raise BadRequestException(f"invalid tax-credit instruction: {exc.errors()[0].get('msg')}")
    result = nl.create_tax_credit_instruction(db, organization_id=org_id, employee_id=emp.id, data=data,
                                              actor_id=_actor(current_user))
    db.commit()
    return _json(result)


@router.post("/employees/{employee_id}/contracts", summary="Record a new contract version (AWf class is derived)")
def create_contract_version(employee_id: int, payload: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from pydantic import ValidationError

    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlContractVersion as M
    from app.modules.payroll.netherlands_schemas import ContractVersionCreate

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    latest = (db.query(M.version).filter(M.organization_id == org_id, M.employee_id == emp.id)
              .order_by(M.version.desc()).first())
    allowed = {k: payload[k] for k in ("contractTerm", "writtenRecord", "writtenEvidenceRef", "onCall",
                                       "agreedHoursPerWeek", "statutoryExceptionCode", "startDate", "endDate",
                                       "incomeRelationshipId") if k in payload}
    try:
        data = ContractVersionCreate(**allowed, employeeId=emp.id, version=(latest[0] if latest else 0) + 1)
    except ValidationError as exc:
        raise BadRequestException(f"invalid contract: {exc.errors()[0].get('msg')}")
    result = nl.create_contract_version(db, organization_id=org_id, employee_id=emp.id, data=data,
                                        actor_id=_actor(current_user))
    db.commit()
    return _json(result)


@router.post("/employees/{employee_id}/company-cars", summary="Register a company car (addition from the pack)")
def add_company_car(employee_id: int, payload: Dict[str, Any] = Body(...),
                    current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    window = (payload.get("addition_rate_window_key") or "").strip()
    if not window:
        raise BadRequestException("addition_rate_window_key is required (the pack's car-addition window)")
    row = nl.add_company_car(
        db, organization_id=org_id, employee_id=emp.id, catalog_value=_dec(payload, "catalog_value"),
        first_admission_date=_date(payload, "first_admission_date"), addition_rate_window_key=window,
        effective_from=_date(payload, "effective_from"), vehicle_class=payload.get("vehicle_class") or None,
        plate_masked=payload.get("plate_masked") or None,
        private_use_status=payload.get("private_use_status") or "PRIVATE",
        no_private_use_evidence_ref=payload.get("no_private_use_evidence_ref") or None,
        employee_own_contribution=_dec(payload, "employee_own_contribution", default="0"))
    db.commit()
    db.refresh(row)
    return _cols(row)


@router.post("/employees/{employee_id}/sickness-events", summary="Record a first sick day")
def record_sickness_event(employee_id: int, payload: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlAbsencePayPolicy

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    policy_id = payload.get("policy_id")
    if policy_id:
        _owned(db, PayrollNlAbsencePayPolicy, int(policy_id), org_id)
    row = nl.record_sickness_event(db, organization_id=org_id, employee_id=emp.id,
                                   first_sick_day=_date(payload, "first_sick_day"),
                                   policy_id=int(policy_id) if policy_id else None)
    db.commit()
    db.refresh(row)
    return _cols(row)


@router.put("/sickness-events/{event_id}/close", summary="Record the recovery date")
def close_sickness_event(event_id: int, payload: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlSicknessEvent

    org_id = _org_id(current_user)
    _owned(db, PayrollNlSicknessEvent, event_id, org_id)
    row = nl.close_sickness_event(db, event_id, org_id, _date(payload, "recovery_date"))
    db.commit()
    db.refresh(row)
    return _cols(row)


@router.post("/employees/{employee_id}/termination-settlements",
             summary="Prepare a termination settlement (final pay components kept separate)")
def prepare_termination_settlement(employee_id: int, payload: Dict[str, Any] = Body(...),
                                   current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlIncomeRelationship

    org_id = _org_id(current_user)
    emp = _employee(db, org_id, employee_id)
    ikv_id = payload.get("income_relationship_id")
    if ikv_id:
        _owned(db, PayrollNlIncomeRelationship, int(ikv_id), org_id)
    reason = (payload.get("reason") or "").strip()
    initiated_by = (payload.get("initiated_by") or "").strip()
    if not reason or not initiated_by:
        raise BadRequestException("reason and initiated_by are required")
    try:
        service_months = int(payload["service_months"])
    except (KeyError, TypeError, ValueError):
        raise BadRequestException("service_months must be a whole number")
    row = nl.prepare_termination_settlement(
        db, organization_id=org_id, employee_id=emp.id, termination_date=_date(payload, "termination_date"),
        reason=reason, initiated_by=initiated_by, service_months=service_months,
        monthly_salary=_dec(payload, "monthly_salary"), annual_salary=_dec(payload, "annual_salary"),
        unused_leave_hours=_dec(payload, "unused_leave_hours", default="0"),
        hourly_wage=_dec(payload, "hourly_wage"), actor_id=_actor(current_user),
        income_relationship_id=int(ikv_id) if ikv_id else None)
    db.commit()
    db.refresh(row)
    return _cols(row)


@router.put("/termination-settlements/{settlement_id}/approve",
            summary="Approve a termination settlement (four-eyes: not the preparer)")
def approve_termination_settlement(settlement_id: int, current_user=Depends(get_current_payroll_operator),
                                   db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import PayrollNlTerminationSettlement

    org_id = _org_id(current_user)
    _owned(db, PayrollNlTerminationSettlement, settlement_id, org_id)
    row = nl.approve_termination_settlement(db, settlement_id, org_id, actor_id=_actor(current_user))
    db.commit()
    db.refresh(row)
    return _cols(row)


# ── payroll run workspace ────────────────────────────────────────────────────

@router.get("/runs/{run_id}/preflight", summary="Netherlands preflight + exceptions for a run (read-only)")
def get_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    run = _run(db, _org_id(current_user), run_id)
    checks = nl.nl_run_preflight(db, run)
    blocked = any(c.get("severity") == "BLOCK" for c in checks)
    return {"runId": run.id, "status": "BLOCKED" if blocked else ("WARN" if checks else "OK"), "checks": checks}


@router.get("/runs/{run_id}/fingerprint", summary="Approval fingerprint over the run's frozen NL inputs")
def get_run_fingerprint(run_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    run = _run(db, _org_id(current_user), run_id)
    return {**nl.nl_approval_fingerprint(db, run), "stored": run.nl_approval_fingerprint}


# ── loonaangifte (build / reconcile / view) — transport LOCKED until G3 ──────

_RETURN_FIELDS = ("id", "loonheffingennummer", "tax_year", "period_code", "period_start", "period_end", "due_date",
                  "payment_due_date", "version", "return_type", "correction_of_id", "status", "total_wage_tax",
                  "total_awf", "total_aof", "total_whk", "total_wko", "total_zvw_employer", "total_zvw_employee",
                  "total_final_levies", "total_payable", "spec_version", "journal_reconciled",
                  "reconciliation_report", "created_at")


def _return_row(r) -> dict:
    return {f: _plain(getattr(r, f, None)) for f in _RETURN_FIELDS}


@router.get("/loonaangifte", summary="Your built payroll-tax returns")
def list_returns(tax_year: Optional[int] = Query(None), current_user=Depends(get_current_payroll_operator),
                 db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings

    return [_return_row(r) for r in filings.list_returns(db, _org_id(current_user), tax_year)]


@router.get("/loonaangifte/{return_id}", summary="One return with its employee lines")
def get_return(return_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings
    from app.modules.payroll.models import PayrollNlLoonaangifteReturn

    _owned(db, PayrollNlLoonaangifteReturn, return_id, _org_id(current_user))
    ret, lines = filings.get_return_with_lines(db, return_id)
    return {**_return_row(ret), "lines": [{k: _plain(getattr(l, k, None)) for k in (
        "id", "employee_id", "income_relationship_id", "personnel_number", "line_type", "wage_lb_phf", "wage_sv",
        "wage_zvw", "hours", "awf_class", "premium_amounts", "wage_tax", "zvw")} for l in lines]}


@router.post("/loonaangifte/build", summary="Build a return from committed payroll (REGULAR / NIL / ZERO)")
def build_return(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_payroll_operator),
                 db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings
    from app.modules.payroll.models import PayrollNlEmployerProfile

    org_id = _org_id(current_user)
    profile = (db.query(PayrollNlEmployerProfile).filter(PayrollNlEmployerProfile.organization_id == org_id,
                                                         PayrollNlEmployerProfile.effective_to.is_(None)).first())
    if profile is None:
        raise BadRequestException("record your Netherlands employer registration first")
    return_type = payload.get("return_type") or "REGULAR"
    if return_type not in ("REGULAR", "NIL", "ZERO"):
        raise BadRequestException("build REGULAR, NIL or ZERO returns here; corrections use /{id}/correction")
    try:
        ret = filings.build_loonaangifte_return(db, organization_id=org_id, employer_profile_id=profile.id,
                                                tax_year=int(payload["tax_year"]), period_code=str(payload["period_code"]),
                                                return_type=return_type, actor_id=_actor(current_user))
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid build request: {exc}")
    db.commit()
    db.refresh(ret)
    return _return_row(ret)


@router.put("/loonaangifte/{return_id}/reconcile", summary="Re-derive from committed payroll and compare")
def reconcile_return(return_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings
    from app.modules.payroll.models import PayrollNlLoonaangifteReturn

    _owned(db, PayrollNlLoonaangifteReturn, return_id, _org_id(current_user))
    try:
        report = filings.reconcile_return(db, return_id, _actor(current_user))
    finally:
        db.commit()  # the mismatch report is evidence too
    return report


@router.post("/loonaangifte/{return_id}/file", summary="LOCKED until gate G3")
def file_return(return_id: int, current_user=Depends(get_current_payroll_operator)):
    _locked("filing")


# ── jaaropgaaf (annual statements) ───────────────────────────────────────────

_STATEMENT_EXCLUDE = ("idempotency_key",)


@router.get("/annual-statements", summary="Annual statements (jaaropgaaf)")
def list_annual_statements(tax_year: Optional[int] = Query(None), employee_id: Optional[int] = Query(None),
                           current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_annual_service as annual

    rows = annual.list_annual_statements(db, _org_id(current_user), tax_year=tax_year, employee_id=employee_id)
    return [_cols(r, _STATEMENT_EXCLUDE) for r in rows]


@router.post("/annual-statements/generate", summary="Generate (or return the existing) jaaropgaaf DRAFT")
def generate_annual_statement(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_payroll_operator),
                              db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_annual_service as annual

    org_id = _org_id(current_user)
    try:
        employee_id, tax_year = int(payload["employee_id"]), int(payload["tax_year"])
    except (KeyError, TypeError, ValueError):
        raise BadRequestException("employee_id and tax_year are required")
    _employee(db, org_id, employee_id)
    row = annual.generate_annual_statement(db, org_id, employee_id, tax_year, actor_id=_actor(current_user))
    db.commit()
    db.refresh(row)
    return _cols(row, _STATEMENT_EXCLUDE)


@router.put("/annual-statements/{statement_id}/issue", summary="Issue a DRAFT jaaropgaaf to the employee")
def issue_annual_statement(statement_id: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_annual_service as annual
    from app.modules.payroll.models import PayrollNlAnnualStatement

    _owned(db, PayrollNlAnnualStatement, statement_id, _org_id(current_user))
    row = annual.issue_annual_statement(db, statement_id, _actor(current_user))
    db.commit()
    db.refresh(row)
    return _cols(row, _STATEMENT_EXCLUDE)


# ── SEPA salary payment batches ──────────────────────────────────────────────

_BATCH_EXCLUDE = ("idempotency_key",)


@router.get("/payment-batches", summary="SEPA payment batches")
def list_payment_batches(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_payment_service as payments

    return [_cols(b, _BATCH_EXCLUDE) for b in payments.list_payment_batches(db, _org_id(current_user))]


@router.get("/payment-batches/{batch_id}", summary="One batch with its items (IBANs masked)")
def get_payment_batch(batch_id: int, current_user=Depends(get_current_payroll_operator),
                      db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_payment_service as payments
    from app.modules.payroll.models import PayrollNlPaymentBatch

    _owned(db, PayrollNlPaymentBatch, batch_id, _org_id(current_user))
    batch, items = payments.get_batch_with_items(db, batch_id)
    out_items = []
    for item in items:
        row = _cols(item)
        for key in [k for k in row if "iban" in k and row[k]]:
            row[key] = f"{str(row[key])[:4]}{'*' * max(len(str(row[key])) - 8, 0)}{str(row[key])[-4:]}"
        out_items.append(row)
    return {**_cols(batch, _BATCH_EXCLUDE), "items": out_items}


@router.post("/runs/{run_id}/salary-batch", summary="Create the SEPA salary batch of an approved run")
def create_salary_batch(run_id: int, payload: Optional[Dict[str, Any]] = Body(None),
                        current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_payment_service as payments

    run = _run(db, _org_id(current_user), run_id)
    batch = payments.create_salary_payment_batch(
        db, run.id, _actor(current_user),
        requested_execution_date=_date(payload or {}, "requested_execution_date", required=False))
    db.commit()
    db.refresh(batch)
    return _cols(batch, _BATCH_EXCLUDE)


@router.post("/authority-payments/prepare", summary="LOCKED until gate G3")
def authority_payment_prepare(current_user=Depends(get_current_payroll_operator)):
    _locked("authority payment")

"""
payroll/my_org_router.py
------------------------
Organisation API for Malaysia statutory setup (ZP-MY-ENG-001 Phase 5), mounted
inside payroll_router as /api/payroll/malaysia. Same house rules as the Poland
organisation router:

  * Dormancy: the router-level guard refuses EVERY route with 404 while
    Malaysia onboarding is off (MY_TENANT_ONBOARDING_ENABLED, or the canary
    allow-list), or when the caller's payroll jurisdiction is not Malaysia.
    Malaysia is dormant, not forbidden.
  * The organisation is always the caller's own; no route takes an org id,
    and every child id is checked against that organisation in the service.
  * Reads need a payroll operator; writes need an org admin and a reason;
    approvals and reveals are four-eyes in the service (spec §15).
  * NRIC / TIN / EPF / SOCSO / work-pass numbers are returned masked
    everywhere; the single-use reveal response is the only one that carries
    the value (MY-029).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.payroll import malaysia_service as my


def require_my_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_dormancy, service

    org_id = getattr(current_user, "organization_id", None)
    if not malaysia_dormancy.onboarding_enabled(org_id):
        raise NotFoundException(malaysia_dormancy.DORMANT_MESSAGE)
    if org_id is None:
        return
    if not malaysia_dormancy.is_malaysia(service._resolve_org_country(db, org_id)):
        raise NotFoundException("The Malaysia API is only available to organisations whose payroll "
                                "jurisdiction is Malaysia.")


router = APIRouter(prefix="/malaysia", tags=["Malaysia (Organisation)"], dependencies=[Depends(require_my_tenant)])


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Malaysia routes act on your own organisation.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _row(row):
    return my._json_safe(my._facts(row))


def _commit(db: Session, row):
    db.commit()
    db.refresh(row)
    return _row(row)


def _split(body: Dict[str, Any]):
    body = dict(body or {})
    return body, body.pop("reason", None)


def _list(db: Session, model, organization_id: int, employee_id: Optional[int] = None):
    q = db.query(model).filter(model.organization_id == organization_id)
    if employee_id is not None:
        my._employee(db, organization_id, employee_id)
        q = q.filter(model.employee_id == employee_id)
    return [_row(r) for r in q.order_by(model.id).all()]


def _run(db: Session, organization_id: int, run_id: int):
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    return run


# ── summary ─────────────────────────────────────────────────────────────────
@router.get("/summary", summary="Malaysia statutory setup summary (read-only)")
def my_summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return my.statutory_summary(db)


# ── employer registrations (MY-016) ─────────────────────────────────────────
@router.get("/employer-registrations", summary="Every version of your Malaysia employer registrations")
def my_list_registrations(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, my._models().PayrollMyEmployerRegistration, _org_id(current_user))


@router.post("/employer-registrations", summary="Record a DRAFT Malaysia employer registration (org admin)")
def my_create_registration(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, my.record_my_employer_registration(db, _org_id(current_user), payload,
                                                          _actor(current_user), reason))


@router.post("/employer-registrations/{row_id}/approve", summary="Approve an employer registration (four-eyes)")
def my_approve_registration(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.approve_my_employer_registration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/employer-registrations/{row_id}/verify", summary="Verify or reject an ACTIVE registration (four-eyes)")
def my_verify_registration(row_id: int, body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.verify_my_employer_registration(db, _org_id(current_user), row_id, _actor(current_user),
                                                          body.get("outcome"), body.get("reason")))


# ── worker statutory profiles (spec §4) ─────────────────────────────────────
@router.get("/employees/{employee_id}/worker-profiles", summary="Every version of an employee's Malaysia profile")
def my_list_profiles(employee_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    return _list(db, my._models().PayrollMyWorkerProfile, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/worker-profiles", summary="Record a DRAFT worker statutory profile")
def my_create_profile(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, my.record_my_worker_profile(db, _org_id(current_user), employee_id, payload,
                                                   _actor(current_user), reason))


@router.post("/worker-profiles/{row_id}/approve", summary="Approve a worker statutory profile (four-eyes)")
def my_approve_profile(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.approve_my_worker_profile(db, _org_id(current_user), row_id, _actor(current_user)))


# ── work assignments: labour territory + holiday state (MY-003) ─────────────
@router.get("/employees/{employee_id}/work-assignments", summary="Every version of an employee's work location")
def my_list_assignments(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return _list(db, my._models().PayrollMyWorkAssignment, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/work-assignments", summary="Record a DRAFT work assignment")
def my_create_assignment(employee_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, my.record_my_work_assignment(db, _org_id(current_user), employee_id, payload,
                                                    _actor(current_user), reason))


@router.post("/work-assignments/{row_id}/approve", summary="Approve a work assignment (four-eyes)")
def my_approve_assignment(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.approve_my_work_assignment(db, _org_id(current_user), row_id, _actor(current_user)))


# ── tax declarations (MY-010) ───────────────────────────────────────────────
@router.get("/employees/{employee_id}/declarations", summary="Every TP1 / TP3 / CP38 / zakat declaration")
def my_list_declarations(employee_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    return _list(db, my._models().PayrollMyTaxDeclaration, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/declarations", summary="Record a received declaration (with evidence)")
def my_create_declaration(employee_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.record_my_declaration(db, _org_id(current_user), employee_id, dict(body or {}),
                                                _actor(current_user)))


@router.post("/declarations/{row_id}/approve", summary="Approve a declaration (four-eyes)")
def my_approve_declaration(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.approve_my_declaration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/declarations/{row_id}/withdraw", summary="Withdraw a declaration from a date (history kept)")
def my_withdraw_declaration(row_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, my.withdraw_my_declaration(db, _org_id(current_user), row_id, _actor(current_user),
                                                  body.get("reason"), body.get("effectiveTo")))


# ── identifier vault (spec §15, MY-029) ─────────────────────────────────────
@router.get("/employees/{employee_id}/identifiers", summary="An employee's Malaysian identifiers on file (masked)")
def my_list_identifiers(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return my.list_my_identifiers(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/identifiers", summary="Put an identifier on file (masked response)")
def my_create_identifier(employee_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = my.create_my_identifier(db, _org_id(current_user), body.get("identifierType"), body.get("value"),
                                  _actor(current_user), employee_id=employee_id)
    db.commit()
    return my.identifier_view(row)


@router.post("/identifiers/{vault_id}/reveal-request", summary="Request a single-use reveal (reason required)")
def my_request_reveal(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    my.request_my_identifier_reveal(db, _org_id(current_user), vault_id, body.get("reason"), _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_REQUESTED"}


@router.post("/identifiers/{vault_id}/reveal-approve", summary="Approve a reveal request (four-eyes)")
def my_approve_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    my.approve_my_identifier_reveal(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_APPROVED"}


@router.post("/identifiers/{vault_id}/reveal", summary="Use an approved reveal once (requester only)")
def my_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    out = my.reveal_my_identifier(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return out


@router.post("/identifiers/{vault_id}/delete", summary="Delete an identifier (reason required; history kept)")
def my_delete_identifier(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    row = my.delete_my_identifier(db, _org_id(current_user), vault_id, _actor(current_user), body.get("reason"))
    db.commit()
    return my.identifier_view(row)


# ── labour by territory (Phase 6) ───────────────────────────────────────────
@router.get("/employees/{employee_id}/leave-entitlement", summary="Whole-year leave entitlement by territory")
def my_leave_entitlement_view(employee_id: int, as_of: date = Query(..., alias="asOf"),
                              current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return my.my_leave_entitlement(db, _org_id(current_user), employee_id, as_of)


@router.get("/employees/{employee_id}/holidays", summary="The employee's federal + state public holidays")
def my_holiday_calendar_view(employee_id: int, year: int = Query(...),
                             current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return my.my_holiday_calendar(db, _org_id(current_user), employee_id, year)


# ── employer events and tax-clearance holds (Phase 7, MY-019 / MY-020) ─────
@router.get("/employees/{employee_id}/employer-events", summary="CP22 / CP22A / CP21 / death notices of an employee")
def my_list_events(employee_id: int, current_user=Depends(get_current_payroll_operator),
                   db: Session = Depends(get_db)):
    return _list(db, my._models().PayrollMyEmployerEvent, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/employer-events", summary="Record an employer event (due date from signed content)")
def my_create_event(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, my.record_my_employer_event(db, _org_id(current_user), employee_id, payload,
                                                   _actor(current_user), reason))


@router.post("/employer-events/{row_id}/submitted", summary="Record the HASiL submission receipt (four-eyes)")
def my_submit_event(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    return _commit(db, my.submit_my_employer_event(db, _org_id(current_user), row_id, _actor(current_user),
                                                   body.get("submittedOn"), body.get("receiptRef"),
                                                   body.get("evidenceRef")))


@router.post("/employer-events/{row_id}/cancel", summary="Cancel an OPEN employer event (reason required)")
def my_cancel_event(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    return _commit(db, my.cancel_my_employer_event(db, _org_id(current_user), row_id, _actor(current_user),
                                                   body.get("reason")))


@router.post("/employer-events/{row_id}/clearance-hold", summary="Open the tax-clearance hold for a departure event")
def my_open_hold(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                 db: Session = Depends(get_db)):
    row = my.open_my_clearance_hold(db, _org_id(current_user), row_id, _actor(current_user), body.get("openedOn"),
                                    body.get("reason"))
    db.commit()
    return my.hold_view(db, row)


@router.post("/clearance-holds/{hold_id}/release-request", summary="Put a hold forward for release (HASiL letter)")
def my_request_release(hold_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    row = my.request_my_hold_release(db, _org_id(current_user), hold_id, _actor(current_user),
                                     body.get("releaseReference"), body.get("evidenceRef"))
    db.commit()
    return my.hold_view(db, row)


@router.post("/clearance-holds/{hold_id}/release-approve", summary="Release a clearance hold (four-eyes)")
def my_approve_release(hold_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = my.approve_my_hold_release(db, _org_id(current_user), hold_id, _actor(current_user))
    db.commit()
    return my.hold_view(db, row)


# ── Phase 9: filings, settlements, reconciliation, journal (MY-021 / MY-022) ─
# Payload generation only; no live HASiL / EPF / PERKESO / HRD / bank call (D-5).
@router.get("/filings", summary="Malaysia filing records (canonical payloads; masked identifiers)")
def my_list_filings(period: Optional[str] = Query(None), form: Optional[str] = Query(None),
                    status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    return myf.list_my_filings(db, _org_id(current_user), period=period, form_code=form, status=status)


@router.get("/filings/{filing_id}", summary="One Malaysia filing with its canonical payload")
def my_get_filing(filing_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    return myf.get_my_filing(db, _org_id(current_user), filing_id)


@router.post("/filings/rebuild/{run_id}", summary="Rebuild the monthly authority filings of a PAID run (idempotent)")
def my_rebuild_filings(run_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import malaysia_filing as myf

    run = _run(db, _org_id(current_user), run_id)
    if str(getattr(run.status, "value", run.status)) not in myf.PAID_STATUSES:
        raise BadRequestException("Filings are built for a PAID run.")
    rows = myf.build_my_run_filings(db, run, _actor(current_user))
    db.commit()
    return [myf.filing_view(r) for r in rows]


@router.post("/filings/annual", summary="Build EA / Form E / CP8D for a closed year (idempotent)")
def my_build_annual(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    myf.refuse_out_of_scope(body.get("form"))
    rows = myf.build_my_annual_filings(db, _org_id(current_user), int(body.get("year") or 0),
                                       body.get("legalEntityId"), _actor(current_user))
    db.commit()
    return [myf.filing_view(r) for r in rows]


@router.post("/employer-events/{row_id}/filing", summary="Build the CP22 / CP22A / CP21 payload of an event")
def my_build_event_filing(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    row = myf.build_my_event_filing(db, _org_id(current_user), row_id, _actor(current_user))
    db.commit()
    return myf.filing_view(row)


@router.post("/filings/{filing_id}/approve", summary="Approve a DRAFT filing (four-eyes; archived layout only)")
def my_approve_filing(filing_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    row = myf.approve_my_filing(db, _org_id(current_user), filing_id, _actor(current_user))
    db.commit()
    return myf.filing_view(row)


@router.post("/filings/{filing_id}/submission", summary="Record a manual submission (idempotent by reference)")
def my_record_submission(filing_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    row = myf.record_my_filing_submission(db, _org_id(current_user), filing_id, body.get("submissionRef"),
                                          _actor(current_user))
    db.commit()
    return myf.filing_view(row)


@router.post("/filings/{filing_id}/response", summary="Record the authority's receipt or rejection")
def my_record_response(filing_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_filing as myf

    row = myf.record_my_filing_response(db, _org_id(current_user), filing_id, body, _actor(current_user))
    db.commit()
    return myf.filing_view(row)


@router.get("/settlements", summary="Malaysia PCB / EPF / PERKESO / HRD liabilities")
def my_list_settlements(period: Optional[str] = Query(None), liability: Optional[str] = Query(None),
                        status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_settlement as mss

    return mss.list_my_settlements(db, _org_id(current_user), period=period, liability=liability, status=status)


@router.post("/settlements/{settlement_id}/payments", summary="Record a payment (idempotent by reference)")
def my_record_payment(settlement_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_settlement as mss

    row = mss.record_my_settlement_payment(db, _org_id(current_user), settlement_id, body, _actor(current_user))
    db.commit()
    return mss.settlement_view(row)


@router.post("/settlements/{settlement_id}/reconcile", summary="Reconcile a liability (or raise a variance)")
def my_reconcile(settlement_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_settlement as mss

    out = mss.reconcile_my_settlement(db, _org_id(current_user), settlement_id, _actor(current_user))
    db.commit()
    return out


@router.get("/variances", summary="Malaysia reconciliation variances")
def my_list_variances(status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                      db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_settlement as mss

    return mss.list_my_variances(db, _org_id(current_user), status=status)


@router.post("/variances/{variance_id}/resolve", summary="Resolve a variance (four-eyes, reason required)")
def my_resolve_variance(variance_id: int, body: Dict[str, Any] = Body(...),
                        current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_settlement as mss

    row = mss.resolve_my_variance(db, _org_id(current_user), variance_id, body.get("reason"), _actor(current_user))
    db.commit()
    return mss.variance_view(row)


@router.get("/runs/{run_id}/journal", summary="Accounting journal of a PAID run (balanced or BLOCKED)")
def my_run_journal(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import malaysia_journal as myj

    return myj.build_my_journal(db, _org_id(current_user), run_id)


# ── employee summary, run preflight ─────────────────────────────────────────
@router.get("/employees/{employee_id}/summary", summary="An employee's Malaysia records (identifiers masked)")
def my_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return my.employee_summary(db, _org_id(current_user), employee_id)


@router.get("/runs/{run_id}/preflight", summary="Malaysia payroll preflight for a run (read-only)")
def my_run_preflight_view(run_id: int, current_user=Depends(get_current_payroll_operator),
                          db: Session = Depends(get_db)):
    return my.my_run_preflight(db, _run(db, _org_id(current_user), run_id))

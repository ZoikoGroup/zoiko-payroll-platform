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

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
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


# ── employee summary, run preflight ─────────────────────────────────────────
@router.get("/employees/{employee_id}/summary", summary="An employee's Malaysia records (identifiers masked)")
def my_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return my.employee_summary(db, _org_id(current_user), employee_id)


@router.get("/runs/{run_id}/preflight", summary="Malaysia payroll preflight for a run (read-only)")
def my_run_preflight_view(run_id: int, current_user=Depends(get_current_payroll_operator),
                          db: Session = Depends(get_db)):
    return my.my_run_preflight(db, _run(db, _org_id(current_user), run_id))

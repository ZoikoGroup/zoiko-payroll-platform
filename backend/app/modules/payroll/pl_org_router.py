"""
payroll/pl_org_router.py
------------------------
Organisation API for Poland statutory setup (ZP-PL-ENG-001 Phase 4), mounted
inside payroll_router as /api/payroll/poland. Same house rules as the New
Zealand organisation router:

  * Dormancy: the router-level guard refuses EVERY route with 404 while
    PL_TENANT_ONBOARDING_ENABLED is off, or when the caller's payroll
    jurisdiction is not Poland (PL-001). Poland is dormant, not forbidden.
  * The organisation is always the caller's own; no route takes an org id,
    and every child id is checked against that organisation in the service.
  * Reads need a payroll operator; writes need an org admin and a reason;
    approvals and reveals are four-eyes in the service (spec §13).
  * PESEL / NIP / NRS are returned masked everywhere; the single-use reveal
    response is the only one that carries the value (PL-025).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.payroll import poland_service as pl


def require_pl_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_dormancy, service

    if not poland_dormancy.onboarding_enabled():
        raise NotFoundException(poland_dormancy.DORMANT_MESSAGE)
    org_id = getattr(current_user, "organization_id", None)
    if org_id is None:
        return
    if not poland_dormancy.is_poland(service._resolve_org_country(db, org_id)):
        raise NotFoundException("The Poland API is only available to organisations whose payroll "
                                "jurisdiction is Poland.")


router = APIRouter(prefix="/poland", tags=["Poland (Organisation)"], dependencies=[Depends(require_pl_tenant)])


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Poland routes act on your own organisation.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _row(row):
    return pl._json_safe(pl._facts(row))


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
        pl._employee(db, organization_id, employee_id)
        q = q.filter(model.employee_id == employee_id)
    return [_row(r) for r in q.order_by(model.id).all()]


def _run(db: Session, organization_id: int, run_id: int):
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    return run


# ── summary ─────────────────────────────────────────────────────────────────
@router.get("/summary", summary="Poland statutory setup summary (read-only)")
def pl_summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return pl.statutory_summary(db)


# ── employer registrations (PL-001) ─────────────────────────────────────────
@router.get("/employer-registrations", summary="Every version of your Poland employer registrations")
def pl_list_registrations(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, pl._models().PayrollPlEmployerRegistration, _org_id(current_user))


@router.post("/employer-registrations", summary="Record a DRAFT Poland employer registration (org admin)")
def pl_create_registration(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, pl.record_pl_employer_registration(db, _org_id(current_user), payload,
                                                          _actor(current_user), reason))


@router.post("/employer-registrations/{row_id}/approve", summary="Approve an employer registration (four-eyes)")
def pl_approve_registration(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.approve_pl_employer_registration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/employer-registrations/{row_id}/verify", summary="Verify or reject an ACTIVE registration (four-eyes)")
def pl_verify_registration(row_id: int, body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.verify_pl_employer_registration(db, _org_id(current_user), row_id, _actor(current_user),
                                                          body.get("outcome"), body.get("reason")))


@router.post("/employer-registrations/{row_id}/nrs",
             summary="Put the ZUS contribution account (NRS) on file for a DRAFT registration (masked response)")
def pl_set_nrs(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
               db: Session = Depends(get_db)):
    row = pl.set_pl_employer_nrs(db, _org_id(current_user), row_id, body.get("nrs"), _actor(current_user))
    db.commit()
    return pl.identifier_view(row)


# ── worker statutory profiles (spec §3) ─────────────────────────────────────
@router.get("/employees/{employee_id}/worker-profiles", summary="Every version of an employee's Poland profile")
def pl_list_profiles(employee_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    return _list(db, pl._models().PayrollPlWorkerProfile, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/worker-profiles", summary="Record a DRAFT worker statutory profile")
def pl_create_profile(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, pl.record_pl_worker_profile(db, _org_id(current_user), employee_id, payload,
                                                   _actor(current_user), reason))


@router.post("/worker-profiles/{row_id}/approve", summary="Approve a worker statutory profile (four-eyes)")
def pl_approve_profile(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.approve_pl_worker_profile(db, _org_id(current_user), row_id, _actor(current_user)))


# ── statements (PL-005 / PL-007 / PL-010) ───────────────────────────────────
@router.get("/employees/{employee_id}/statements", summary="Every PIT / PPK / cap statement of an employee")
def pl_list_statements(employee_id: int, current_user=Depends(get_current_payroll_operator),
                       db: Session = Depends(get_db)):
    return _list(db, pl._models().PayrollPlDeclaration, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/statements", summary="Record a received statement (with evidence)")
def pl_create_statement(employee_id: int, body: Dict[str, Any] = Body(...),
                        current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.record_pl_declaration(db, _org_id(current_user), employee_id, dict(body or {}),
                                                _actor(current_user)))


@router.post("/statements/{row_id}/approve", summary="Approve a statement (four-eyes)")
def pl_approve_statement(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.approve_pl_declaration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/statements/{row_id}/withdraw", summary="Withdraw a statement from a date (history kept)")
def pl_withdraw_statement(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                          db: Session = Depends(get_db)):
    return _commit(db, pl.withdraw_pl_declaration(db, _org_id(current_user), row_id, _actor(current_user),
                                                  body.get("reason"), body.get("effectiveTo")))


# ── PPK (spec §7) ───────────────────────────────────────────────────────────
@router.get("/employees/{employee_id}/ppk", summary="Every version of an employee's PPK participation")
def pl_list_ppk(employee_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, pl._models().PayrollPlPpkParticipation, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/ppk", summary="Record a DRAFT PPK participation version")
def pl_create_ppk(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                  db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, pl.record_pl_ppk_participation(db, _org_id(current_user), employee_id, payload,
                                                      _actor(current_user), reason))


@router.post("/ppk/{row_id}/approve", summary="Approve a PPK participation version (four-eyes)")
def pl_approve_ppk(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, pl.approve_pl_ppk_participation(db, _org_id(current_user), row_id, _actor(current_user)))


@router.get("/ppk/reenrolment-due", summary="Opted-out participants whose re-enrolment checkpoint has come")
def pl_ppk_due(on: Optional[date] = Query(None), current_user=Depends(get_current_payroll_operator),
               db: Session = Depends(get_db)):
    if on is None:
        from app.core.exceptions import BadRequestException

        raise BadRequestException("Pass ?on=YYYY-MM-DD (the checkpoint date is never assumed).")
    return pl.pl_ppk_reenrolment_due(db, _org_id(current_user), on)


# ── identifier vault (spec §13, PL-025) ─────────────────────────────────────
@router.get("/employees/{employee_id}/identifiers", summary="An employee's PESEL / NIP on file (masked)")
def pl_list_identifiers(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return pl.list_pl_identifiers(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/identifiers", summary="Put a PESEL or NIP on file (masked response)")
def pl_create_identifier(employee_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = pl.create_pl_identifier(db, _org_id(current_user), body.get("identifierType"), body.get("value"),
                                  _actor(current_user), employee_id=employee_id)
    db.commit()
    return pl.identifier_view(row)


@router.post("/identifiers/{vault_id}/reveal-request", summary="Request a single-use reveal (reason required)")
def pl_request_reveal(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    pl.request_pl_identifier_reveal(db, _org_id(current_user), vault_id, body.get("reason"), _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_REQUESTED"}


@router.post("/identifiers/{vault_id}/reveal-approve", summary="Approve a reveal request (four-eyes)")
def pl_approve_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    pl.approve_pl_identifier_reveal(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_APPROVED"}


@router.post("/identifiers/{vault_id}/reveal", summary="Use an approved reveal once (requester only)")
def pl_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    out = pl.reveal_pl_identifier(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return out


@router.post("/identifiers/{vault_id}/delete", summary="Delete an identifier (reason required; history kept)")
def pl_delete_identifier(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    row = pl.delete_pl_identifier(db, _org_id(current_user), vault_id, _actor(current_user), body.get("reason"))
    db.commit()
    return pl.identifier_view(row)


# ── annual cap panel, employee summary, run preflight ───────────────────────
@router.get("/employees/{employee_id}/annual-cap", summary="Pension/disability year-to-date bases and evidence")
def pl_annual_cap(employee_id: int, year: int = Query(...), current_user=Depends(get_current_payroll_operator),
                  db: Session = Depends(get_db)):
    return pl.pl_annual_cap_view(db, _org_id(current_user), employee_id, year)


@router.get("/employees/{employee_id}/leave-entitlement", summary="Annual leave entitlement (20 / 26 days, spec §8)")
def pl_leave_entitlement(employee_id: int, as_of: date = Query(..., alias="asOf"),
                         current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return pl.pl_leave_entitlement(db, _org_id(current_user), employee_id, as_of)


@router.get("/employees/{employee_id}/summary", summary="An employee's Poland records (identifiers masked)")
def pl_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return pl.employee_summary(db, _org_id(current_user), employee_id)


@router.get("/runs/{run_id}/preflight", summary="Poland payroll preflight for a run (read-only)")
def pl_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return pl.pl_run_preflight(db, _run(db, _org_id(current_user), run_id))

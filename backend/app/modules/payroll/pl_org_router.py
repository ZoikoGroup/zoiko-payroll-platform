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

    org_id = getattr(current_user, "organization_id", None)
    if not poland_dormancy.onboarding_enabled(org_id):
        raise NotFoundException(poland_dormancy.DORMANT_MESSAGE)
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


# ── incapacity episodes (spec §9, PL-017) ───────────────────────────────────
@router.get("/employees/{employee_id}/incapacity-episodes",
            summary="Incapacity episodes of an employee (certificate and medical pointer withheld, PL-017)")
def pl_list_episodes(employee_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    return pl.list_pl_incapacity_episodes(db, _org_id(current_user), employee_id, restricted=True)


@router.get("/employees/{employee_id}/incapacity-episodes/restricted",
            summary="Incapacity episodes with certificate references (org admin, restricted HR record)")
def pl_list_episodes_restricted(employee_id: int, current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    return pl.list_pl_incapacity_episodes(db, _org_id(current_user), employee_id, restricted=False)


@router.post("/employees/{employee_id}/incapacity-episodes", summary="Record a DRAFT incapacity episode")
def pl_create_episode(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    payload, reason = _split(body)
    row = pl.record_pl_incapacity_episode(db, _org_id(current_user), employee_id, payload, _actor(current_user),
                                          reason)
    db.commit()
    return pl.episode_view(row, restricted=False)


@router.post("/incapacity-episodes/{row_id}/approve", summary="Approve an incapacity episode (four-eyes)")
def pl_approve_episode(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = pl.approve_pl_incapacity_episode(db, _org_id(current_user), row_id, _actor(current_user))
    db.commit()
    return pl.episode_view(row, restricted=False)


@router.post("/incapacity-episodes/{row_id}/cancel", summary="Cancel an incapacity episode (reason required)")
def pl_cancel_episode(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    row = pl.cancel_pl_incapacity_episode(db, _org_id(current_user), row_id, _actor(current_user),
                                          body.get("reason"))
    db.commit()
    return pl.episode_view(row, restricted=False)


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


# ── Phase 8: filings, settlements, reconciliation, journal (spec §10) ───────
# Payload generation only; no live ZUS / e-Deklaracje / PPK / bank call (PL-021).
@router.get("/filings", summary="Poland filing records (canonical payloads; masked identifiers)")
def pl_list_filings(period: Optional[str] = Query(None), form: Optional[str] = Query(None),
                    status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    return plf.list_pl_filings(db, _org_id(current_user), period=period, form_code=form, status=status)


@router.get("/filings/{filing_id}", summary="One Poland filing with its canonical payload")
def pl_get_filing(filing_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    return plf.get_pl_filing(db, _org_id(current_user), filing_id)


@router.post("/filings/rebuild/{run_id}", summary="Rebuild the monthly ZUS filings of a PAID run (idempotent)")
def pl_rebuild_filings(run_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    run = _run(db, _org_id(current_user), run_id)
    if str(getattr(run.status, "value", run.status)) not in plf.PAID_STATUSES:
        from app.core.exceptions import BadRequestException

        raise BadRequestException("Filings are built for a PAID run.")
    rows = plf.build_pl_run_filings(db, run, _actor(current_user))
    db.commit()
    return [plf.filing_view(r) for r in rows]


@router.post("/filings/annual", summary="Build PIT-11 / PIT-4R for a closed tax year (idempotent)")
def pl_build_annual(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    form = str(body.get("form") or "").strip().upper()
    if form in plf.OUT_OF_SCOPE_FORMS:
        plf._conflict("PL_FORM_OUT_OF_SCOPE", plf.OUT_OF_SCOPE_FORMS[form])
    rows = plf.build_pl_annual_filings(db, _org_id(current_user), int(body.get("year") or 0),
                                       body.get("legalEntityId"), _actor(current_user))
    db.commit()
    return [plf.filing_view(r) for r in rows]


@router.post("/filings/registration", summary="Build a ZUA / ZZA / ZWUA registration payload (idempotent)")
def pl_build_registration(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                          db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    row = plf.build_pl_registration_filing(db, _org_id(current_user), int(body.get("employeeId") or 0),
                                           body.get("form"), body.get("eventDate"), _actor(current_user),
                                           reason_code=body.get("reasonCode"))
    db.commit()
    return plf.filing_view(row)


@router.post("/filings/{filing_id}/approve", summary="Approve a DRAFT filing (four-eyes; archived schema only)")
def pl_approve_filing(filing_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    row = plf.approve_pl_filing(db, _org_id(current_user), filing_id, _actor(current_user))
    db.commit()
    return plf.filing_view(row)


@router.post("/filings/{filing_id}/submission", summary="Record a manual submission (idempotent by reference)")
def pl_record_submission(filing_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    row = plf.record_pl_filing_submission(db, _org_id(current_user), filing_id, body.get("submissionRef"),
                                          _actor(current_user))
    db.commit()
    return plf.filing_view(row)


@router.post("/filings/{filing_id}/response", summary="Record the authority's receipt or rejection")
def pl_record_response(filing_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    from app.modules.payroll import poland_filing as plf

    row = plf.record_pl_filing_response(db, _org_id(current_user), filing_id, body, _actor(current_user))
    db.commit()
    return plf.filing_view(row)


@router.get("/settlements", summary="Poland ZUS / PIT / PPK liabilities")
def pl_list_settlements(period: Optional[str] = Query(None), liability: Optional[str] = Query(None),
                        status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import poland_settlement as pss

    return pss.list_pl_settlements(db, _org_id(current_user), period=period, liability=liability, status=status)


@router.post("/settlements/{settlement_id}/payments", summary="Record a payment (idempotent by reference)")
def pl_record_payment(settlement_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_settlement as pss

    row = pss.record_pl_settlement_payment(db, _org_id(current_user), settlement_id, body, _actor(current_user))
    db.commit()
    return pss.settlement_view(row)


@router.post("/settlements/{settlement_id}/reconcile", summary="Reconcile a liability (or raise a variance)")
def pl_reconcile(settlement_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_settlement as pss

    out = pss.reconcile_pl_settlement(db, _org_id(current_user), settlement_id, _actor(current_user))
    db.commit()
    return out


@router.get("/variances", summary="Poland reconciliation variances")
def pl_list_variances(status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                      db: Session = Depends(get_db)):
    from app.modules.payroll import poland_settlement as pss

    return pss.list_pl_variances(db, _org_id(current_user), status=status)


@router.post("/variances/{variance_id}/resolve", summary="Resolve a variance (four-eyes, reason required)")
def pl_resolve_variance(variance_id: int, body: Dict[str, Any] = Body(...),
                        current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_settlement as pss

    row = pss.resolve_pl_variance(db, _org_id(current_user), variance_id, body.get("reason"), _actor(current_user))
    db.commit()
    return pss.variance_view(row)


@router.get("/runs/{run_id}/journal", summary="Accounting journal of a PAID run (balanced or BLOCKED)")
def pl_run_journal(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import poland_journal as plj

    return plj.build_pl_journal(db, _org_id(current_user), run_id)

# ── Phase 9: parallel payroll cycles (AC-PL-03, gate G6) ────────────────────
def _parallel():
    from app.modules.payroll import poland_parallel

    return poland_parallel


@router.get("/parallel-imports", summary="Poland parallel-cycle imports")
def pl_list_parallel_imports(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _parallel().list_parallel_imports(db, _org_id(current_user))


@router.post("/parallel-imports", summary="Compare an incumbent payroll file with a committed Poland run")
def pl_create_parallel_import(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    result = _parallel().import_parallel(db, _org_id(current_user), body, _actor(current_user))
    db.commit()
    return result


@router.get("/parallel-imports/{import_id}", summary="One parallel import with its differences")
def pl_get_parallel_import(import_id: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    return _parallel().parallel_summary(db, _org_id(current_user), import_id)


@router.post("/parallel-imports/{import_id}/accept", summary="Accept a clean parallel cycle (four-eyes)")
def pl_accept_parallel_import(import_id: int, current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    result = _parallel().accept_import(db, _org_id(current_user), import_id, _actor(current_user))
    db.commit()
    return result


@router.post("/parallel-imports/{import_id}/withdraw", summary="Withdraw an open parallel import (reason required)")
def pl_withdraw_parallel_import(import_id: int, body: Dict[str, Any] = Body(...),
                                current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    result = _parallel().withdraw_import(db, _org_id(current_user), import_id, dict(body or {}).get("reason"),
                                         _actor(current_user))
    db.commit()
    return result


@router.post("/parallel-differences/{difference_id}/explain", summary="Explain a parallel-run difference")
def pl_explain_parallel_difference(difference_id: int, body: Dict[str, Any] = Body(...),
                                   current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    result = _parallel().explain_difference(db, _org_id(current_user), difference_id,
                                            dict(body or {}).get("reason"), _actor(current_user))
    db.commit()
    return result


@router.post("/parallel-differences/{difference_id}/accept", summary="Accept an explained difference (four-eyes)")
def pl_accept_parallel_difference(difference_id: int, current_user=Depends(get_current_org_admin),
                                  db: Session = Depends(get_db)):
    result = _parallel().accept_difference(db, _org_id(current_user), difference_id, _actor(current_user))
    db.commit()
    return result

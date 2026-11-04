"""
payroll/nz_org_router.py
------------------------
Organisation API for New Zealand statutory setup (ZP-NZ-ENG-001 Phase 4),
mounted inside payroll_router as /api/payroll/new-zealand. Same house rules as
the Japan organisation router:

  * Dormancy: the router-level guard refuses EVERY route with 404 while
    NZ_TENANT_ONBOARDING_ENABLED is off, or when the caller's payroll
    jurisdiction is not New Zealand. New Zealand is dormant, not forbidden.
  * The organisation is always the caller's own; no route takes an org id,
    and every child id is checked against that organisation in the service.
  * Reads need a payroll operator; writes need an org admin and a reason
    (NZ-024); approvals are four-eyes in the service.
  * The IRD number is returned masked everywhere; the single-use reveal
    response is the only one that carries digits (NZ-023).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.payroll import new_zealand_service as nz


def require_nz_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import nz_dormancy, service

    if not nz_dormancy.onboarding_enabled():
        raise NotFoundException(nz_dormancy.DORMANT_MESSAGE)
    org_id = getattr(current_user, "organization_id", None)
    if org_id is None:
        return
    if not nz_dormancy.is_new_zealand(service._resolve_org_country(db, org_id)):
        raise NotFoundException("The New Zealand API is only available to organisations whose payroll "
                                "jurisdiction is New Zealand.")


router = APIRouter(prefix="/new-zealand", tags=["New Zealand (Organisation)"],
                   dependencies=[Depends(require_nz_tenant)])


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("New Zealand routes act on your own organisation.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _row(row):
    return nz._json_safe(nz._facts(row))


def _rows(rows):
    return [_row(row) for row in rows]


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
        nz._nz_employee(db, organization_id, employee_id)
        q = q.filter(model.employee_id == employee_id)
    return _rows(q.order_by(model.id).all())


def _run(db: Session, organization_id: int, run_id: int):
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    return run


# ── summary / readiness ─────────────────────────────────────────────────────
@router.get("/summary", summary="New Zealand statutory setup summary (read-only)")
def nz_summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return nz.statutory_summary(db)


@router.get("/readiness", summary="New Zealand release-gate readiness (read-only)")
def nz_readiness(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return {"available": False, "unmet": nz.nz_unmet_requirements(db)}


# ── employer profiles ───────────────────────────────────────────────────────
@router.get("/employer-profiles", summary="Every version of your New Zealand employer profiles")
def nz_list_employer_profiles(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, nz._nz_models().PayrollNzEmployerProfile, _org_id(current_user))


@router.post("/employer-profiles", summary="Record a DRAFT New Zealand employer profile (org admin)")
def nz_create_employer_profile(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, nz.record_nz_employer_profile(db, _org_id(current_user), payload, _actor(current_user), reason))


@router.post("/employer-profiles/{row_id}/approve", summary="Approve an employer profile (four-eyes)")
def nz_approve_employer_profile(row_id: int, current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_employer_profile(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/employer-profiles/{row_id}/verify", summary="Verify or reject an ACTIVE employer profile (four-eyes)")
def nz_verify_employer_profile(row_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, nz.verify_nz_employer_profile(db, _org_id(current_user), row_id, _actor(current_user),
                                                     body.get("outcome"), body.get("reason")))


@router.post("/employer-profiles/{row_id}/ird-number",
             summary="Put the employer IRD number on file for a DRAFT profile version (masked response)")
def nz_set_employer_ird(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    row = nz.set_nz_employer_ird(db, _org_id(current_user), row_id, body.get("irdNumber"), _actor(current_user))
    db.commit()
    return nz.nz_ird_view(row)


# ── employee records ────────────────────────────────────────────────────────
@router.get("/employees/{employee_id}/tax-profiles", summary="Every version of the employee's tax profile")
def nz_list_tax_profile(employee_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _list(db, nz._nz_models().PayrollNzEmployeeTaxProfile, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/tax-profiles", summary="Record a DRAFT tax profile (org admin)")
def nz_create_tax_profile(employee_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, nz.record_nz_tax_profile(db, _org_id(current_user), employee_id, payload, _actor(current_user), reason))


@router.post("/tax-profiles/{row_id}/approve", summary="Approve a tax profile (four-eyes)")
def nz_approve_tax_profile(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_tax_profile(db, _org_id(current_user), row_id, _actor(current_user)))


@router.get("/employees/{employee_id}/kiwisaver", summary="Every version of the employee's KiwiSaver election")
def nz_list_kiwisaver_election(employee_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _list(db, nz._nz_models().PayrollNzKiwiSaverElection, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/kiwisaver", summary="Record a DRAFT KiwiSaver election (org admin)")
def nz_create_kiwisaver_election(employee_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, nz.record_nz_kiwisaver_election(db, _org_id(current_user), employee_id, payload, _actor(current_user), reason))


@router.post("/kiwisaver/{row_id}/approve", summary="Approve a KiwiSaver election (four-eyes)")
def nz_approve_kiwisaver_election(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_kiwisaver_election(db, _org_id(current_user), row_id, _actor(current_user)))


@router.get("/employees/{employee_id}/work-patterns", summary="Every version of the employee's work pattern")
def nz_list_work_pattern(employee_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _list(db, nz._nz_models().PayrollNzWorkPatternVersion, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/work-patterns", summary="Record a DRAFT work pattern (org admin)")
def nz_create_work_pattern(employee_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, nz.record_nz_work_pattern(db, _org_id(current_user), employee_id, payload, _actor(current_user), reason))


@router.post("/work-patterns/{row_id}/approve", summary="Approve a work pattern (four-eyes)")
def nz_approve_work_pattern(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_work_pattern(db, _org_id(current_user), row_id, _actor(current_user)))


# ── authority notices (NZ-010) ──────────────────────────────────────────────
@router.get("/employees/{employee_id}/authority-deductions", summary="The employee's authority notice versions")
def nz_list_notices(employee_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    rows = _list(db, nz._nz_models().PayrollNzAuthorityDeduction, _org_id(current_user), employee_id)
    return [{k: v for k, v in row.items() if k != "evidence_ref"} for row in rows]


@router.post("/employees/{employee_id}/authority-deductions",
             summary="Import an authority notice (file + JSON metadata); stored as its hash only")
async def nz_import_notice(employee_id: int, file: UploadFile = File(...), meta: str = Form(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    try:
        metadata = json.loads(meta)
    except ValueError:
        raise BadRequestException("meta must be a JSON object.")
    row = nz.import_nz_authority_notice(db, _org_id(current_user), employee_id, metadata, await file.read(),
                                        _actor(current_user))
    return _commit(db, row)


@router.post("/authority-deductions/{row_id}/approve", summary="Approve an authority notice (four-eyes)")
def nz_approve_notice(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_authority_notice(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/authority-deductions/{row_id}/revoke", summary="Revoke an approved authority notice (four-eyes)")
def nz_revoke_notice(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    return _commit(db, nz.revoke_nz_authority_notice(db, _org_id(current_user), row_id, _actor(current_user),
                                                     body.get("reason")))


# ── opening balances ────────────────────────────────────────────────────────
@router.get("/employees/{employee_id}/opening-balances", summary="Opening-balance requests for the employee")
def nz_list_opening_balances(employee_id: int, current_user=Depends(get_current_payroll_operator),
                             db: Session = Depends(get_db)):
    return nz.list_nz_opening_balance_requests(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/opening-balances",
             summary="Request a year-to-date opening balance (evidence required; a second person approves)")
def nz_request_opening_balance(employee_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    request = nz.request_nz_opening_balance(db, _org_id(current_user), employee_id, body, _actor(current_user))
    db.commit()
    return request


@router.post("/opening-balances/{request_id}/approve", summary="Approve an opening balance (four-eyes)")
def nz_approve_opening_balance(request_id: int, current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    return _commit(db, nz.approve_nz_opening_balance(db, _org_id(current_user), request_id, _actor(current_user)))


# ── IRD-number vault (NZ-023) ───────────────────────────────────────────────
@router.get("/employees/{employee_id}/ird-number", summary="Whether the employee's IRD number is on file (masked)")
def nz_get_ird(employee_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    rows = [r for r in nz.list_nz_ird_numbers(db, _org_id(current_user), employee_id) if r["onFile"]]
    return rows[0] if rows else {"onFile": False, "masked": None}


@router.post("/employees/{employee_id}/ird-number", summary="Put the employee's IRD number on file (masked response)")
def nz_set_ird(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
               db: Session = Depends(get_db)):
    row = nz.create_nz_ird_number(db, _org_id(current_user), "EMPLOYEE", body.get("irdNumber"),
                                  _actor(current_user), employee_id=employee_id)
    db.commit()
    return nz.nz_ird_view(row)


@router.post("/ird-numbers/{vault_id}/delete", summary="Delete an IRD number from the vault (reason required)")
def nz_delete_ird(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                  db: Session = Depends(get_db)):
    row = nz.delete_nz_ird_number(db, _org_id(current_user), vault_id, _actor(current_user), body.get("reason"))
    db.commit()
    return nz.nz_ird_view(row)


@router.post("/ird-numbers/{vault_id}/reveal-requests", summary="Request to reveal an IRD number (reason required)")
def nz_request_ird_reveal(vault_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    event = nz.request_nz_ird_reveal(db, _org_id(current_user), vault_id, body.get("reason"), _actor(current_user))
    db.commit()
    return {"eventId": event.id, "action": event.action}


@router.post("/ird-numbers/{vault_id}/reveal-approvals", summary="Approve a reveal request (a second person)")
def nz_approve_ird_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    event = nz.approve_nz_ird_reveal(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"eventId": event.id, "action": event.action}


@router.post("/ird-numbers/{vault_id}/reveal", summary="Reveal an IRD number once, to the requester")
def nz_reveal_ird(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    result = nz.reveal_nz_ird_number(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return result


# ── runs ────────────────────────────────────────────────────────────────────
@router.get("/runs/{run_id}/preflight", summary="New Zealand approval blockers for a run (read-only)")
def nz_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return {"problems": nz.nz_run_preflight(db, _run(db, _org_id(current_user), run_id))}


@router.get("/runs/{run_id}/fingerprint", summary="Stored vs current approval fingerprint (read-only)")
def nz_run_fingerprint(run_id: int, current_user=Depends(get_current_payroll_operator),
                       db: Session = Depends(get_db)):
    run = _run(db, _org_id(current_user), run_id)
    current = nz.nz_approval_fingerprint(db, run)
    return {"stored": run.nz_approval_fingerprint, "current": current,
            "matches": bool(run.nz_approval_fingerprint) and run.nz_approval_fingerprint == current}


@router.get("/employees/{employee_id}/summary", summary="The employee's New Zealand statutory summary")
def nz_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return nz.employee_summary(db, _org_id(current_user), employee_id)


# ── Holidays Act (Phase 5): employments, entitlements, leave, public holidays ─
def _leave():
    from app.modules.payroll import nz_leave_service

    return nz_leave_service


@router.get("/employees/{employee_id}/employments", summary="The employee's New Zealand employment instances")
def nz_list_employments(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    lv = _leave()
    return [lv.employment_view(row) for row in lv.list_nz_employments(db, _org_id(current_user), employee_id)]


@router.post("/employees/{employee_id}/employments", summary="Record a DRAFT employment instance (org admin)")
def nz_create_employment(employee_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    lv = _leave()
    payload, reason = _split(body)
    row = lv.record_nz_employment(db, _org_id(current_user), employee_id, payload, _actor(current_user), reason)
    db.commit()
    return lv.employment_view(row)


@router.post("/employments/{row_id}/approve", summary="Approve an employment instance (four-eyes)")
def nz_approve_employment(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    lv = _leave()
    row = lv.approve_nz_employment(db, _org_id(current_user), row_id, _actor(current_user))
    db.commit()
    return lv.employment_view(row)


@router.post("/employments/{row_id}/end", summary="End an employment instance (org admin)")
def nz_end_employment(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    lv = _leave()
    body = dict(body or {})
    row = lv.end_nz_employment(db, _org_id(current_user), row_id, body.get("endDate"),
                               body.get("terminationReason"), _actor(current_user), body.get("reason"))
    db.commit()
    return lv.employment_view(row)


@router.post("/leave/vest", summary="Vest Holidays Act entitlements due up to a date (idempotent)")
def nz_vest_entitlements(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    body = dict(body or {})
    result = _leave().vest_entitlements(db, _org_id(current_user), body.get("asOf"),
                                        employee_id=body.get("employeeId"), actor_id=_actor(current_user))
    db.commit()
    return result


@router.get("/employees/{employee_id}/leave-entitlements",
            summary="The employee's legal leave entitlements (weeks / days) and the planning view")
def nz_list_entitlements(employee_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    result = _leave().balances(db, _org_id(current_user), _actor(current_user), employee_id)
    db.commit()
    return result


@router.get("/employees/{employee_id}/leave-events",
            summary="The employee's leave events (restricted ones only with the permission)")
def nz_list_leave_events(employee_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    result = _leave().visible_events(db, _org_id(current_user), _actor(current_user), employee_id)
    db.commit()
    return result


@router.post("/leave-events/{event_id}/cancel", summary="Cancel an approved leave event (org admin)")
def nz_cancel_leave_event(event_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = _leave().cancel_leave_event(db, _org_id(current_user), event_id, _actor(current_user),
                                      dict(body or {}).get("reason"))
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/public-holidays/propose", summary="Propose DRAFT public-holiday decisions for a year")
def nz_propose_public_holidays(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    lv = _leave()
    body = dict(body or {})
    rows = lv.propose_public_holiday_decisions(db, _org_id(current_user), body.get("year"),
                                               employee_id=body.get("employeeId"), actor_id=_actor(current_user))
    db.commit()
    return [lv.decision_view(row) for row in rows]


@router.get("/employees/{employee_id}/public-holiday-decisions",
            summary="The employee's public-holiday decisions")
def nz_list_public_holiday_decisions(employee_id: int, current_user=Depends(get_current_payroll_operator),
                                     db: Session = Depends(get_db)):
    lv = _leave()
    return [lv.decision_view(row) for row in lv.list_public_holiday_decisions(db, _org_id(current_user), employee_id)]


@router.put("/public-holiday-decisions/{decision_id}", summary="Change a DRAFT public-holiday decision (org admin)")
def nz_update_public_holiday_decision(decision_id: int, body: Dict[str, Any] = Body(...),
                                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    lv = _leave()
    payload, reason = _split(body)
    row = lv.update_public_holiday_decision(db, _org_id(current_user), decision_id, payload, _actor(current_user),
                                            reason)
    db.commit()
    return lv.decision_view(row)


@router.post("/public-holiday-decisions/{decision_id}/approve",
             summary="Approve a public-holiday decision (four-eyes)")
def nz_approve_public_holiday_decision(decision_id: int, current_user=Depends(get_current_org_admin),
                                       db: Session = Depends(get_db)):
    lv = _leave()
    row = lv.approve_public_holiday_decision(db, _org_id(current_user), decision_id, _actor(current_user))
    db.commit()
    return lv.decision_view(row)


@router.get("/employees/{employee_id}/gross-earnings", summary="The employee's Holidays Act gross-earnings ledger")
def nz_list_gross_earnings(employee_id: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    lv = _leave()
    return [lv.gross_earnings_view(row) for row in lv.list_gross_earnings(db, _org_id(current_user), employee_id)]


@router.get("/permissions/family-violence", summary="Holders of the family-violence leave permission")
def nz_list_fv_holders(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _leave().family_violence_view_holders(db, _org_id(current_user))


@router.post("/permissions/family-violence", summary="Grant the family-violence leave permission (another admin)")
def nz_grant_fv_view(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    body = dict(body or {})
    try:
        user_id = int(body.get("userId"))
    except (TypeError, ValueError):
        raise BadRequestException("userId must be a whole number.")
    row = _leave().grant_family_violence_view(db, _org_id(current_user), _actor(current_user), user_id,
                                               body.get("reason"))
    db.commit()
    return {"id": row.id, "userId": row.user_id}


@router.delete("/permissions/family-violence/{user_id}", summary="Revoke the family-violence leave permission")
def nz_revoke_fv_view(user_id: int, reason: Optional[str] = None, current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    row = _leave().revoke_family_violence_view(db, _org_id(current_user), _actor(current_user), user_id, reason)
    db.commit()
    return {"id": row.id, "revoked": True}

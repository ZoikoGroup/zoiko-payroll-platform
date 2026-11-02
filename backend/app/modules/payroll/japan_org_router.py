"""
payroll/japan_org_router.py
---------------------------
Organisation API for Japan statutory setup (ZP-JP-ENG-001 Phase 5), mounted
inside payroll_router as /api/payroll/japan. Same house rules as the Brazil /
Mexico / Netherlands organisation routers:

  * Dormancy: the router-level guard refuses EVERY route with 404 while
    JP_TENANT_ONBOARDING_ENABLED is off, or when the caller's payroll
    jurisdiction is not Japan. Japan is dormant, not forbidden.
  * The organisation is always the caller's own; no route takes an org id.
  * Every child id is checked against that organisation before the service
    acts.
  * Reads need a payroll operator; writes need an org admin.
  * My Number routes never accept or return a stored plaintext except through
    the approved reveal boundary.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.payroll import japan_service as jp


def require_japan_tenant(current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    from app.modules.payroll import japan_dormancy, service

    if not japan_dormancy.onboarding_enabled():
        raise NotFoundException(japan_dormancy.DORMANT_MESSAGE)
    org_id = getattr(current_user, "organization_id", None)
    if org_id is None:
        return
    if not japan_dormancy.is_japan(service._resolve_org_country(db, org_id)):
        raise NotFoundException("The Japan API is only available to organisations whose payroll "
                                "jurisdiction is Japan.")


router = APIRouter(prefix="/japan", tags=["Japan (Organisation)"],
                   dependencies=[Depends(require_japan_tenant)])


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Japan routes act on your own organisation.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _row(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _rows(rows):
    return [_row(row) for row in rows]


def _commit(db: Session, row):
    db.commit()
    db.refresh(row)
    return _row(row)


def _list(db: Session, model, organization_id: int, employee_id: Optional[int] = None):
    q = db.query(model).filter(model.organization_id == organization_id)
    if employee_id is not None:
        jp._jp_employee(db, organization_id, employee_id)
        q = q.filter(model.employee_id == employee_id)
    return _rows(q.order_by(model.id).all())


# ── readiness / summary ─────────────────────────────────────────────────────

@router.get("/readiness", summary="Japan release-gate readiness (dormant, read-only)")
def readiness(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return jp.statutory_summary(db)


@router.get("/summary", summary="Japan statutory setup summary (read-only)")
def summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return jp.statutory_summary(db)


# ── employer registration ───────────────────────────────────────────────────

@router.get("/employer", summary="Every version of your Japan employer registration")
def list_employer_registrations(current_user=Depends(get_current_payroll_operator),
                                db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpEmployerRegistration, _org_id(current_user))


@router.post("/employer", summary="Record a DRAFT Japan employer registration (org admin)")
def create_employer_registration(body: Dict[str, Any] = Body(...),
                                 current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    row = jp.record_employer_registration(db, _org_id(current_user), body, _actor(current_user))
    return _commit(db, row)


@router.post("/employer/{registration_id}/approve",
             summary="Approve a Japan employer registration (four-eyes, org admin)")
def approve_employer_registration(registration_id: int,
                                  current_user=Depends(get_current_org_admin),
                                  db: Session = Depends(get_db)):
    row = jp.approve_employer_registration(db, _org_id(current_user), registration_id,
                                           _actor(current_user))
    return _commit(db, row)


# ── work conditions ────────────────────────────────────────────────────────

@router.get("/work-conditions", summary="Every version of your Japan work conditions")
def list_work_conditions(current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpWorkConditions, _org_id(current_user))


@router.post("/work-conditions", summary="Record DRAFT Japan work conditions (org admin)")
def create_work_conditions(body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    row = jp.record_work_conditions(db, _org_id(current_user), body, _actor(current_user))
    return _commit(db, row)


@router.post("/work-conditions/{conditions_id}/approve",
             summary="Approve DRAFT Japan work conditions (second person)")
def approve_work_conditions(conditions_id: int,
                            current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    row = jp.approve_work_conditions(db, _org_id(current_user), conditions_id,
                                     _actor(current_user))
    return _commit(db, row)


# ── worker tax profile ──────────────────────────────────────────────────────

@router.get("/employees/{employee_id}/tax-profiles",
            summary="Every Japan worker tax-profile version for an employee")
def list_worker_tax_profiles(employee_id: int,
                             current_user=Depends(get_current_payroll_operator),
                             db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpWorkerTaxProfile, _org_id(current_user),
                 employee_id)


@router.post("/employees/{employee_id}/tax-profiles",
             summary="Record a DRAFT Japan worker tax profile (org admin)")
def create_worker_tax_profile(employee_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    row = jp.record_worker_tax_profile(db, _org_id(current_user), employee_id, body,
                                       _actor(current_user))
    return _commit(db, row)


@router.post("/tax-profiles/{profile_id}/approve",
             summary="Approve a Japan worker tax profile (four-eyes, org admin)")
def approve_worker_tax_profile(profile_id: int,
                               current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    row = jp.approve_worker_tax_profile(db, _org_id(current_user), profile_id,
                                        _actor(current_user))
    return _commit(db, row)


# ── social insurance enrolment / events ─────────────────────────────────────

@router.get("/employees/{employee_id}/social-insurance",
            summary="Every Japan social-insurance enrolment version for an employee")
def list_social_insurance_enrollments(employee_id: int,
                                      current_user=Depends(get_current_payroll_operator),
                                      db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpSocialInsuranceEnrollment,
                 _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/social-insurance",
             summary="Record a DRAFT Japan social-insurance enrolment (org admin)")
def create_social_insurance_enrollment(employee_id: int,
                                       body: Dict[str, Any] = Body(...),
                                       current_user=Depends(get_current_org_admin),
                                       db: Session = Depends(get_db)):
    row = jp.record_social_insurance_enrollment(db, _org_id(current_user), employee_id, body,
                                                _actor(current_user))
    return _commit(db, row)


@router.post("/social-insurance/{enrollment_id}/approve",
             summary="Approve a Japan social-insurance enrolment (four-eyes, org admin)")
def approve_social_insurance_enrollment(enrollment_id: int,
                                        current_user=Depends(get_current_org_admin),
                                        db: Session = Depends(get_db)):
    row = jp.approve_social_insurance_enrollment(db, _org_id(current_user), enrollment_id,
                                                 _actor(current_user))
    return _commit(db, row)


@router.get("/employees/{employee_id}/social-insurance-events",
            summary="Japan social-insurance lifecycle events for an employee")
def list_social_insurance_events(employee_id: int,
                                 current_user=Depends(get_current_payroll_operator),
                                 db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollJpSocialInsuranceEvent

    return _list(db, PayrollJpSocialInsuranceEvent, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/social-insurance-events",
             summary="Record a Japan SMR/lifecycle event (org admin)")
def record_social_insurance_event(employee_id: int, body: Dict[str, Any] = Body(...),
                                  current_user=Depends(get_current_org_admin),
                                  db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle

    row = japan_lifecycle.record_event(
        db, organization_id=_org_id(current_user), employee_id=employee_id,
        event_type=body.get("eventType") or body.get("event_type"),
        effective_from=body.get("effectiveFrom") or body.get("effective_from"),
        effective_to=body.get("effectiveTo") or body.get("effective_to"),
        payload=body.get("payload"),
        evidence_ref=body.get("evidenceRef") or body.get("evidence_ref"),
        actor_id=_actor(current_user))
    db.commit()
    db.refresh(row)
    return _row(row)


@router.post("/social-insurance-events/{event_id}/approve",
             summary="Approve a Japan social-insurance event (org admin)")
def approve_social_insurance_event(event_id: int,
                                   current_user=Depends(get_current_org_admin),
                                   db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle

    row = japan_lifecycle.approve_event(db, organization_id=_org_id(current_user),
                                        event_id=event_id, actor_id=_actor(current_user))
    db.commit()
    db.refresh(row)
    return _row(row)


@router.post("/social-insurance-events/{event_id}/apply",
             summary="Apply an approved Japan social-insurance event to the enrolment")
def apply_social_insurance_event(event_id: int,
                                 current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle

    result = japan_lifecycle.apply_approved_event(
        db, organization_id=_org_id(current_user), event_id=event_id,
        actor_id=_actor(current_user))
    db.commit()
    return _row(result)


# ── employment insurance ────────────────────────────────────────────────────

@router.get("/employees/{employee_id}/employment-insurance",
            summary="Every Japan employment-insurance profile version for an employee")
def list_employment_insurance_profiles(employee_id: int,
                                        current_user=Depends(get_current_payroll_operator),
                                        db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpEmploymentInsuranceProfile,
                 _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/employment-insurance",
             summary="Record a DRAFT Japan employment-insurance profile (org admin)")
def create_employment_insurance_profile(employee_id: int,
                                        body: Dict[str, Any] = Body(...),
                                        current_user=Depends(get_current_org_admin),
                                        db: Session = Depends(get_db)):
    row = jp.record_employment_insurance_profile(db, _org_id(current_user), employee_id,
                                                 body, _actor(current_user))
    return _commit(db, row)


@router.post("/employment-insurance/{profile_id}/approve",
             summary="Approve a Japan employment-insurance profile (four-eyes, org admin)")
def approve_employment_insurance_profile(profile_id: int,
                                         current_user=Depends(get_current_org_admin),
                                         db: Session = Depends(get_db)):
    row = jp.approve_employment_insurance_profile(db, _org_id(current_user), profile_id,
                                                  _actor(current_user))
    return _commit(db, row)


# ── resident-tax notices ────────────────────────────────────────────────────

@router.get("/employees/{employee_id}/resident-tax-notices",
            summary="Every imported Japan resident-tax notice version for an employee")
def list_resident_tax_notices(employee_id: int,
                              current_user=Depends(get_current_payroll_operator),
                              db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpResidentTaxAssessment, _org_id(current_user),
                 employee_id)


@router.post("/employees/{employee_id}/resident-tax-notices",
             summary="Import a municipal resident-tax notice (twelve amounts; org admin)")
def create_resident_tax_notice(employee_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    row = jp.record_resident_tax_assessment(db, _org_id(current_user), employee_id, body,
                                            _actor(current_user))
    return _commit(db, row)


@router.post("/resident-tax-notices/{assessment_id}/approve",
             summary="Approve an imported Japan resident-tax notice (four-eyes, org admin)")
def approve_resident_tax_notice(assessment_id: int,
                                current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    row = jp.approve_resident_tax_assessment(db, _org_id(current_user), assessment_id,
                                             _actor(current_user))
    return _commit(db, row)


# ── run preflight & approval fingerprint ────────────────────────────────────

@router.get("/runs/{run_id}/preflight", summary="Japan preflight for a run (read-only)")
def run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator),
                  db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayslipItem, PayrollRun

    org_id = _org_id(current_user)
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id,
                                      PayrollRun.organization_id == org_id).first()
    if run is None:
        raise NotFoundException(f"Run #{run_id} not found in this organisation.")
    payslips = (db.query(PayslipItem)
                .filter(PayslipItem.payroll_run_id == run.id,
                        PayslipItem.country_code == "JP").all())
    checks = []
    for item in payslips:
        if not item.jp_calculation_snapshot:
            checks.append({"severity": "BLOCK", "code": "JP_SNAPSHOT_MISSING",
                           "message": f"Payslip #{item.id} has no frozen Japan calculation snapshot."})
    stored = getattr(run, "jp_approval_fingerprint", None)
    current = jp.jp_approval_fingerprint(db, run)
    if stored and current and stored != current:
        checks.append({"severity": "BLOCK", "code": "JP_FINGERPRINT_CHANGED",
                       "message": "Japan inputs changed after approval."})
    if not stored:
        checks.append({"severity": "INFO", "code": "JP_NOT_APPROVED",
                       "message": "The run has no stored Japan approval fingerprint yet."})
    return {"status": "BLOCKED" if any(c["severity"] == "BLOCK" for c in checks) else "OK",
            "checks": checks, "currentFingerprint": current, "storedFingerprint": stored}


@router.get("/runs/{run_id}/fingerprint",
            summary="Approval fingerprint over the run's frozen Japan inputs")
def run_fingerprint(run_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollRun

    org_id = _org_id(current_user)
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id,
                                      PayrollRun.organization_id == org_id).first()
    if run is None:
        raise NotFoundException(f"Run #{run_id} not found in this organisation.")
    return {"fingerprint": jp.jp_approval_fingerprint(db, run),
            "stored": getattr(run, "jp_approval_fingerprint", None)}


# ── My Number vault ─────────────────────────────────────────────────────────

@router.get("/my-numbers", summary="My Number vault rows (masked only)")
def list_my_numbers(employee_id: Optional[int] = None,
                    current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return jp.list_my_numbers(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/my-number",
             summary="Collect and encrypt an employee/dependant My Number (org admin)")
def create_my_number(employee_id: int, body: Dict[str, Any] = Body(...),
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    row = jp.create_my_number(db, _org_id(current_user), employee_id, body,
                              _actor(current_user))
    db.commit()
    return {"id": row.id, "employeeId": row.employee_id, "masked": "•••• •••• ••••",
            "status": row.status}


@router.post("/my-numbers/{vault_id}/reveal-request",
             summary="Request a second person's approval to reveal a My Number")
def request_my_number_reveal(vault_id: int, body: Dict[str, Any] = Body(...),
                             current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    row = jp.request_my_number_reveal(db, _org_id(current_user), vault_id,
                                      body.get("reason", ""), _actor(current_user))
    db.commit()
    return _row(row)


@router.post("/my-numbers/{vault_id}/reveal-approve",
             summary="Approve a My Number reveal (four-eyes, org admin)")
def approve_my_number_reveal(vault_id: int,
                             current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    row = jp.approve_my_number_reveal(db, _org_id(current_user), vault_id,
                                      _actor(current_user))
    db.commit()
    return _row(row)


@router.post("/my-numbers/{vault_id}/reveal",
             summary="Reveal an approved My Number (audited)")
def reveal_my_number(vault_id: int,
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    result = jp.reveal_my_number(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return result


@router.delete("/my-numbers/{vault_id}", summary="Delete a My Number (ciphertext nulled)")
def delete_my_number(vault_id: int,
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    row = jp.delete_my_number(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"id": row.id, "status": row.status, "deletedAt": row.deleted_at}

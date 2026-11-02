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

@router.get("/readiness", summary="Japan release gates G0-G8 with checks and evidence (read-only)")
def jp_readiness(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_readiness
    return japan_readiness.jp_readiness(db)


@router.get("/summary", summary="Japan statutory setup summary (read-only)")
def jp_summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return jp.statutory_summary(db)


# ── employer registration ───────────────────────────────────────────────────

@router.get("/employer", summary="Every version of your Japan employer registration")
def jp_list_employer_registrations(current_user=Depends(get_current_payroll_operator),
                                db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpEmployerRegistration, _org_id(current_user))


@router.post("/employer", summary="Record a DRAFT Japan employer registration (org admin)")
def jp_create_employer_registration(body: Dict[str, Any] = Body(...),
                                 current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    row = jp.record_employer_registration(db, _org_id(current_user), body, _actor(current_user))
    return _commit(db, row)


@router.post("/employer/{registration_id}/approve",
             summary="Approve a Japan employer registration (four-eyes, org admin)")
def jp_approve_employer_registration(registration_id: int,
                                  current_user=Depends(get_current_org_admin),
                                  db: Session = Depends(get_db)):
    row = jp.approve_employer_registration(db, _org_id(current_user), registration_id,
                                           _actor(current_user))
    return _commit(db, row)


# ── work conditions ────────────────────────────────────────────────────────

@router.get("/work-conditions", summary="Every version of your Japan work conditions")
def jp_list_work_conditions(current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpWorkConditions, _org_id(current_user))


@router.post("/work-conditions", summary="Record DRAFT Japan work conditions (org admin)")
def jp_create_work_conditions(body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    row = jp.record_work_conditions(db, _org_id(current_user), body, _actor(current_user))
    return _commit(db, row)


@router.post("/work-conditions/{conditions_id}/approve",
             summary="Approve DRAFT Japan work conditions (second person)")
def jp_approve_work_conditions(conditions_id: int,
                            current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    row = jp.approve_work_conditions(db, _org_id(current_user), conditions_id,
                                     _actor(current_user))
    return _commit(db, row)


# ── attendance approvals ───────────────────────────────────────────────────

@router.get("/employees/{employee_id}/attendance-approvals",
            summary="Japan attendance approvals for an employee")
def jp_list_attendance_approvals(employee_id: int,
                              current_user=Depends(get_current_payroll_operator),
                              db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpAttendanceApproval, _org_id(current_user),
                 employee_id)


@router.post("/employees/{employee_id}/attendance-approvals",
             summary="Request approval of an employee's attendance for a pay period")
def jp_request_attendance_approval(employee_id: int, body: Dict[str, Any] = Body(...),
                                current_user=Depends(get_current_payroll_operator),
                                db: Session = Depends(get_db)):
    row = jp.request_attendance_approval(db, _org_id(current_user), employee_id, body,
                                         _actor(current_user))
    return _commit(db, row)


@router.post("/attendance-approvals/{approval_id}/approve",
             summary="Approve a period's attendance (second person; rows must be unchanged)")
def jp_approve_attendance_approval(approval_id: int,
                                current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    row = jp.approve_attendance_approval(db, _org_id(current_user), approval_id,
                                         _actor(current_user))
    return _commit(db, row)


@router.get("/bonus-reports",
            summary="JPS bonus payment report obligations (due date, overdue flag)")
def jp_list_bonus_reports(status: Optional[str] = None,
                       current_user=Depends(get_current_payroll_operator),
                       db: Session = Depends(get_db)):
    return jp.list_bonus_reports(db, _org_id(current_user), status)


@router.get("/employees/{employee_id}/summary",
            summary="Japan versions in force, attendance approvals and masked My Number")
def jp_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    return jp.employee_summary(db, _org_id(current_user), employee_id)


# ── worker tax profile ──────────────────────────────────────────────────────

@router.get("/employees/{employee_id}/tax-profiles",
            summary="Every Japan worker tax-profile version for an employee")
def jp_list_worker_tax_profiles(employee_id: int,
                             current_user=Depends(get_current_payroll_operator),
                             db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpWorkerTaxProfile, _org_id(current_user),
                 employee_id)


@router.post("/employees/{employee_id}/tax-profiles",
             summary="Record a DRAFT Japan worker tax profile (org admin)")
def jp_create_worker_tax_profile(employee_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    row = jp.record_worker_tax_profile(db, _org_id(current_user), employee_id, body,
                                       _actor(current_user))
    return _commit(db, row)


@router.post("/tax-profiles/{profile_id}/approve",
             summary="Approve a Japan worker tax profile (four-eyes, org admin)")
def jp_approve_worker_tax_profile(profile_id: int,
                               current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    row = jp.approve_worker_tax_profile(db, _org_id(current_user), profile_id,
                                        _actor(current_user))
    return _commit(db, row)


# ── social insurance enrolment / events ─────────────────────────────────────

@router.get("/employees/{employee_id}/social-insurance",
            summary="Every Japan social-insurance enrolment version for an employee")
def jp_list_social_insurance_enrollments(employee_id: int,
                                      current_user=Depends(get_current_payroll_operator),
                                      db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpSocialInsuranceEnrollment,
                 _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/social-insurance",
             summary="Record a DRAFT Japan social-insurance enrolment (org admin)")
def jp_create_social_insurance_enrollment(employee_id: int,
                                       body: Dict[str, Any] = Body(...),
                                       current_user=Depends(get_current_org_admin),
                                       db: Session = Depends(get_db)):
    row = jp.record_social_insurance_enrollment(db, _org_id(current_user), employee_id, body,
                                                _actor(current_user))
    return _commit(db, row)


@router.post("/social-insurance/{enrollment_id}/approve",
             summary="Approve a Japan social-insurance enrolment (four-eyes, org admin)")
def jp_approve_social_insurance_enrollment(enrollment_id: int,
                                        current_user=Depends(get_current_org_admin),
                                        db: Session = Depends(get_db)):
    row = jp.approve_social_insurance_enrollment(db, _org_id(current_user), enrollment_id,
                                                 _actor(current_user))
    return _commit(db, row)


@router.get("/employees/{employee_id}/social-insurance-events",
            summary="Japan social-insurance lifecycle events for an employee")
def jp_list_social_insurance_events(employee_id: int,
                                 current_user=Depends(get_current_payroll_operator),
                                 db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollJpSocialInsuranceEvent

    return _list(db, PayrollJpSocialInsuranceEvent, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/social-insurance-events",
             summary="Record a Japan SMR/lifecycle event (org admin)")
def jp_record_social_insurance_event(employee_id: int, body: Dict[str, Any] = Body(...),
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
def jp_approve_social_insurance_event(event_id: int,
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
def jp_apply_social_insurance_event(event_id: int,
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
def jp_list_employment_insurance_profiles(employee_id: int,
                                        current_user=Depends(get_current_payroll_operator),
                                        db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpEmploymentInsuranceProfile,
                 _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/employment-insurance",
             summary="Record a DRAFT Japan employment-insurance profile (org admin)")
def jp_create_employment_insurance_profile(employee_id: int,
                                        body: Dict[str, Any] = Body(...),
                                        current_user=Depends(get_current_org_admin),
                                        db: Session = Depends(get_db)):
    row = jp.record_employment_insurance_profile(db, _org_id(current_user), employee_id,
                                                 body, _actor(current_user))
    return _commit(db, row)


@router.post("/employment-insurance/{profile_id}/approve",
             summary="Approve a Japan employment-insurance profile (four-eyes, org admin)")
def jp_approve_employment_insurance_profile(profile_id: int,
                                         current_user=Depends(get_current_org_admin),
                                         db: Session = Depends(get_db)):
    row = jp.approve_employment_insurance_profile(db, _org_id(current_user), profile_id,
                                                  _actor(current_user))
    return _commit(db, row)


# ── resident-tax notices ────────────────────────────────────────────────────

@router.get("/employees/{employee_id}/resident-tax-notices",
            summary="Every imported Japan resident-tax notice version for an employee")
def jp_list_resident_tax_notices(employee_id: int,
                              current_user=Depends(get_current_payroll_operator),
                              db: Session = Depends(get_db)):
    return _list(db, jp._jp_models().PayrollJpResidentTaxAssessment, _org_id(current_user),
                 employee_id)


@router.post("/employees/{employee_id}/resident-tax-notices",
             summary="Import a municipal resident-tax notice (twelve amounts; org admin)")
def jp_create_resident_tax_notice(employee_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    row = jp.record_resident_tax_assessment(db, _org_id(current_user), employee_id, body,
                                            _actor(current_user))
    return _commit(db, row)


@router.post("/resident-tax-notices/{assessment_id}/approve",
             summary="Approve an imported Japan resident-tax notice (four-eyes, org admin)")
def jp_approve_resident_tax_notice(assessment_id: int,
                                current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    row = jp.approve_resident_tax_assessment(db, _org_id(current_user), assessment_id,
                                             _actor(current_user))
    return _commit(db, row)


# ── run preflight & approval fingerprint ────────────────────────────────────

@router.get("/runs/{run_id}/preflight", summary="Japan preflight for a run (read-only)")
def jp_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator),
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
def jp_run_fingerprint(run_id: int, current_user=Depends(get_current_payroll_operator),
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
def jp_list_my_numbers(employee_id: Optional[int] = None,
                    current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return jp.list_my_numbers(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/my-number",
             summary="Collect and encrypt an employee/dependant My Number (org admin)")
def jp_create_my_number(employee_id: int, body: Dict[str, Any] = Body(...),
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    row = jp.create_my_number(db, _org_id(current_user), employee_id, body,
                              _actor(current_user))
    db.commit()
    return {"id": row.id, "employeeId": row.employee_id, "masked": "•••• •••• ••••",
            "status": row.status}


@router.post("/my-numbers/{vault_id}/reveal-request",
             summary="Request a second person's approval to reveal a My Number")
def jp_request_my_number_reveal(vault_id: int, body: Dict[str, Any] = Body(...),
                             current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    row = jp.request_my_number_reveal(db, _org_id(current_user), vault_id,
                                      body.get("reason", ""), _actor(current_user))
    db.commit()
    return _row(row)


@router.post("/my-numbers/{vault_id}/reveal-approve",
             summary="Approve a My Number reveal (four-eyes, org admin)")
def jp_approve_my_number_reveal(vault_id: int,
                             current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    row = jp.approve_my_number_reveal(db, _org_id(current_user), vault_id,
                                      _actor(current_user))
    db.commit()
    return _row(row)


@router.post("/my-numbers/{vault_id}/reveal",
             summary="Reveal an approved My Number (audited)")
def jp_reveal_my_number(vault_id: int,
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    result = jp.reveal_my_number(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return result


@router.delete("/my-numbers/{vault_id}", summary="Delete a My Number (ciphertext nulled)")
def jp_delete_my_number(vault_id: int,
                     current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    row = jp.delete_my_number(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"id": row.id, "status": row.status, "deletedAt": row.deleted_at}


# ── Phase 8: run exceptions, corrections, journal ───────────────────────────

@router.get("/runs/{run_id}/exceptions", summary="Japan run exceptions and their approvals")
def jp_list_run_exceptions(run_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle
    return japan_lifecycle.list_jp_run_exceptions(db, _org_id(current_user), run_id)


@router.post("/runs/{run_id}/exceptions/approve",
             summary="Approve one Japan run exception (a second person, never the run's preparer)")
def jp_approve_run_exception(run_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle
    result = japan_lifecycle.approve_jp_run_exception(
        db, organization_id=_org_id(current_user), run_id=run_id, key=str(body.get("key") or ""),
        approver_id=_actor(current_user), note=body.get("note"))
    db.commit()
    return result


@router.post("/payslips/{payslip_id}/corrections",
             summary="Correct a committed Japan payslip (blocked until jp_correction_policy is signed)")
def jp_create_correction(payslip_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_lifecycle
    result = japan_lifecycle.create_jp_correction(
        db, organization_id=_org_id(current_user), payslip_item_id=payslip_id,
        reason=body.get("reason") or "", changes=body.get("changes") or {}, actor_id=_actor(current_user))
    db.commit()
    return result


@router.post("/runs/{run_id}/journal", summary="Journal lines for a committed Japan run (account map in the body)")
def jp_run_journal(run_id: int, body: Dict[str, Any] = Body(default={}),
                current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_journal
    return japan_journal.build_jp_journal(db, _org_id(current_user), run_id, body.get("accounts"))


# ── Phase 8: year-end adjustment ────────────────────────────────────────────

@router.get("/employees/{employee_id}/year-end/declarations", summary="Year-end declarations of an employee")
def jp_list_yea_declarations(employee_id: int, tax_year: Optional[int] = None,
                          current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    return japan_year_end.list_declarations(db, _org_id(current_user), employee_id, tax_year)


@router.post("/employees/{employee_id}/year-end/declarations", summary="Record a DRAFT year-end declaration")
def jp_create_yea_declaration(employee_id: int, body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.record_declaration(db, _org_id(current_user), employee_id, body, _actor(current_user))
    return _commit(db, row)


@router.post("/year-end/declarations/{declaration_id}/approve",
             summary="Approve a year-end declaration (second person)")
def jp_approve_yea_declaration(declaration_id: int, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.approve_declaration(db, _org_id(current_user), declaration_id, _actor(current_user))
    return _commit(db, row)


@router.get("/year-end/{tax_year}/cases", summary="Year-end adjustment cases for a tax year")
def jp_list_yea_cases(tax_year: int, current_user=Depends(get_current_payroll_operator),
                   db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    return japan_year_end.list_cases(db, _org_id(current_user), tax_year)


@router.post("/employees/{employee_id}/year-end/{tax_year}/cases", summary="Open a year-end adjustment case")
def jp_open_yea_case(employee_id: int, tax_year: int, current_user=Depends(get_current_org_admin),
                  db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.open_case(db, _org_id(current_user), employee_id, tax_year, _actor(current_user))
    return _commit(db, row)


@router.post("/year-end/cases/{case_id}/calculate", summary="Calculate a year-end case (blocks until G1 tables)")
def jp_calculate_yea_case(case_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.calculate_case(db, _org_id(current_user), case_id, _actor(current_user))
    return _commit(db, row)


@router.post("/year-end/cases/{case_id}/review", summary="Review a calculated year-end case (second person)")
def jp_review_yea_case(case_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.review_case(db, _org_id(current_user), case_id, _actor(current_user))
    return _commit(db, row)


@router.post("/year-end/cases/{case_id}/apply", summary="Apply a reviewed year-end case to an open salary run")
def jp_apply_yea_case(case_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                   db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    try:
        run_id = int(body.get("runId") or body.get("run_id"))
    except (TypeError, ValueError):
        raise BadRequestException("runId is required.")
    row = japan_year_end.apply_case(db, _org_id(current_user), case_id, run_id, _actor(current_user))
    return _commit(db, row)


@router.post("/year-end/cases/{case_id}/void", summary="Void a year-end case that is not locked")
def jp_void_yea_case(case_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_year_end
    row = japan_year_end.void_case(db, _org_id(current_user), case_id, _actor(current_user))
    return _commit(db, row)


# ── Phase 8: remittance obligations and filing previews ─────────────────────

@router.get("/obligations", summary="Japan remittance obligations (withholding, social insurance, resident tax)")
def jp_list_obligations(status: Optional[str] = None, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    return japan_filing.list_obligations(db, _org_id(current_user), status)


@router.post("/obligations/{obligation_id}/approve", summary="Approve a remittance (second person)")
def jp_approve_obligation(obligation_id: int, current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    result = japan_filing.approve_obligation(db, _org_id(current_user), obligation_id, _actor(current_user))
    db.commit()
    return result


@router.post("/obligations/{obligation_id}/submit", summary="Record that an approved remittance was made")
def jp_submit_obligation(obligation_id: int, body: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    result = japan_filing.submit_obligation(db, _org_id(current_user), obligation_id, body.get("channel") or "")
    db.commit()
    return result


@router.post("/obligations/{obligation_id}/receipt", summary="Record the receipt of a submitted remittance")
def jp_obligation_receipt(obligation_id: int, body: Dict[str, Any] = Body(...),
                       current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    result = japan_filing.record_obligation_receipt(
        db, _org_id(current_user), obligation_id, accepted=bool(body.get("accepted")),
        receipt_ref=body.get("receiptRef") or body.get("receipt_ref"))
    db.commit()
    return result


@router.get("/filings/withholding-certificate/{case_id}", summary="Withholding certificate preview (JSON)")
def jp_withholding_certificate(case_id: int, current_user=Depends(get_current_payroll_operator),
                            db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    return japan_filing.withholding_certificate(db, _org_id(current_user), case_id)


@router.get("/filings/salary-payment-reports/{tax_year}",
            summary="Salary payment reports by municipality (JSON preview)")
def jp_salary_payment_reports(tax_year: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    return japan_filing.salary_payment_reports(db, _org_id(current_user), tax_year)


@router.get("/filings/bonus-report/{paid_on}", summary="JPS bonus payment report preview (JSON)")
def jp_bonus_report(paid_on: str, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    return japan_filing.bonus_payment_report(db, _org_id(current_user), paid_on)


@router.get("/filings/annual-determination/{year}", summary="Annual determination report preview (JSON)")
def jp_annual_determination(year: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    from app.modules.payroll import japan_filing
    return japan_filing.annual_determination_report(db, _org_id(current_user), year)


# ── Phase 9: parallel cycles (release gate G7) ──────────────────────────────

@router.get("/parallel-imports", summary="Japan parallel-cycle imports")
def jp_list_parallel_imports(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    return japan_parallel.list_jp_parallel_imports(db, _org_id(current_user))


@router.post("/parallel-imports", summary="Import an incumbent payroll file for a committed Japan run")
def jp_create_parallel_import(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    result = japan_parallel.import_jp_parallel(db, _org_id(current_user), body, _actor(current_user))
    db.commit()
    return result


@router.get("/parallel-imports/{import_id}", summary="One parallel cycle with its differences")
def jp_get_parallel_import(import_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    return japan_parallel.jp_parallel_summary(db, _org_id(current_user), import_id)


@router.post("/parallel-imports/{import_id}/accept", summary="Accept a clean parallel cycle (not its importer)")
def jp_accept_parallel_import(import_id: int, current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    result = japan_parallel.accept_jp_parallel_import(db, _org_id(current_user), import_id, _actor(current_user))
    db.commit()
    return result


@router.post("/parallel-imports/{import_id}/withdraw", summary="Withdraw an open parallel cycle")
def jp_withdraw_parallel_import(import_id: int, current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    result = japan_parallel.withdraw_jp_parallel_import(db, _org_id(current_user), import_id)
    db.commit()
    return result


@router.post("/parallel-differences/{difference_id}/explain", summary="Explain a parallel-run difference")
def jp_explain_parallel_difference(difference_id: int, body: Dict[str, Any] = Body(...),
                                current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    result = japan_parallel.explain_jp_parallel_difference(db, _org_id(current_user), difference_id,
                                               body.get("reason") or "", _actor(current_user))
    db.commit()
    return result


@router.post("/parallel-differences/{difference_id}/accept",
             summary="Accept an explained difference (not its explainer)")
def jp_accept_parallel_difference(difference_id: int, current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    from app.modules.payroll import japan_parallel
    result = japan_parallel.accept_jp_parallel_difference(db, _org_id(current_user), difference_id, _actor(current_user))
    db.commit()
    return result

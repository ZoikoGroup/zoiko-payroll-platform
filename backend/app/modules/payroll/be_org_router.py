"""
payroll/be_org_router.py
------------------------
Organisation API for Belgium statutory setup (ZP-BE-ENG-001 Block A1, D4),
mounted inside payroll_router as /api/payroll/belgium. Same house rules as the
Poland organisation router:

  * Dormancy: the router-level guard refuses EVERY route with 404 unless
    belgium_dormancy admits the caller's organisation (flag or canary) AND the
    organisation's payroll jurisdiction is Belgium.
  * The organisation is always the caller's own; no route takes an org id, and
    every child id is checked against that organisation in the service.
  * Reads need a payroll operator; writes need an org admin and a reason;
    approvals and reveals are four-eyes in the service.
  * NISS / BIS / the ONSS number are returned masked everywhere; the single-use
    reveal response is the only one that carries the value (BE-040).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.payroll import belgium_service as be


def require_be_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_dormancy, service

    org_id = getattr(current_user, "organization_id", None)
    if not belgium_dormancy.onboarding_enabled(org_id):
        raise NotFoundException(belgium_dormancy.DORMANT_MESSAGE)
    if org_id is None:
        return
    if not belgium_dormancy.is_belgium(service._resolve_org_country(db, org_id)):
        raise NotFoundException("The Belgium API is only available to organisations whose payroll "
                                "jurisdiction is Belgium.")


router = APIRouter(prefix="/belgium", tags=["Belgium (Organisation)"], dependencies=[Depends(require_be_tenant)])


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Belgium routes act on your own organisation.")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _row(row):
    return be._json_safe(be._facts(row))


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
        be._employee(db, organization_id, employee_id)
        q = q.filter(model.employee_id == employee_id)
    return [_row(r) for r in q.order_by(model.id).all()]


# ── employer registrations (BE-001) ─────────────────────────────────────────
@router.get("/employer-registrations", summary="Every version of your Belgium employer registrations")
def be_list_registrations(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeEmployerRegistration, _org_id(current_user))


@router.post("/employer-registrations", summary="Record a DRAFT Belgium employer registration (org admin)")
def be_create_registration(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_employer_registration(db, _org_id(current_user), payload,
                                                          _actor(current_user), reason))


@router.post("/employer-registrations/{row_id}/approve", summary="Approve an employer registration (four-eyes)")
def be_approve_registration(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_employer_registration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/employer-registrations/{row_id}/verify", summary="Verify or reject an ACTIVE registration (four-eyes)")
def be_verify_registration(row_id: int, body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.verify_be_employer_registration(db, _org_id(current_user), row_id, _actor(current_user),
                                                          body.get("outcome"), body.get("reason")))


@router.post("/employer-registrations/{row_id}/onss-number",
             summary="Put the employer's ONSS number on file for a DRAFT registration (masked response)")
def be_set_onss(row_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                db: Session = Depends(get_db)):
    row = be.set_be_employer_onss(db, _org_id(current_user), row_id, body.get("onssNumber"), _actor(current_user))
    db.commit()
    return be.identifier_view(row)


# ── establishment units ─────────────────────────────────────────────────────
@router.get("/establishment-units", summary="Every version of your Belgium establishment units")
def be_list_units(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeEstablishmentUnit, _org_id(current_user))


@router.post("/establishment-units", summary="Record a DRAFT establishment unit (org admin)")
def be_create_unit(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                   db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_establishment_unit(db, _org_id(current_user), payload, _actor(current_user),
                                                       reason))


@router.post("/establishment-units/{row_id}/approve", summary="Approve an establishment unit (four-eyes)")
def be_approve_unit(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_establishment_unit(db, _org_id(current_user), row_id, _actor(current_user)))


# ── worker profiles (BE-002) ────────────────────────────────────────────────
@router.get("/employees/{employee_id}/worker-profiles", summary="Every version of an employee's Belgium profile")
def be_list_profiles(employee_id: int, current_user=Depends(get_current_payroll_operator),
                     db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeWorkerProfile, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/worker-profiles", summary="Record a DRAFT worker statutory profile")
def be_create_profile(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_worker_profile(db, _org_id(current_user), employee_id, payload,
                                                   _actor(current_user), reason))


@router.post("/worker-profiles/{row_id}/approve", summary="Approve a worker statutory profile (four-eyes)")
def be_approve_profile(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_worker_profile(db, _org_id(current_user), row_id, _actor(current_user)))


# ── work schedules (BE-022) ─────────────────────────────────────────────────
@router.get("/employees/{employee_id}/work-schedules", summary="Every work schedule of an employee")
def be_list_schedules(employee_id: int, current_user=Depends(get_current_payroll_operator),
                      db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeWorkSchedule, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/work-schedules", summary="Record a DRAFT work schedule")
def be_create_schedule(employee_id: int, body: Dict[str, Any] = Body(...),
                       current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_work_schedule(db, _org_id(current_user), employee_id, payload,
                                                  _actor(current_user), reason))


@router.post("/work-schedules/{row_id}/approve", summary="Approve a work schedule (four-eyes)")
def be_approve_schedule(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_work_schedule(db, _org_id(current_user), row_id, _actor(current_user)))


# ── employment classifications (BE-003 / BE-020) ────────────────────────────
@router.get("/employees/{employee_id}/classifications", summary="Every employment classification of an employee")
def be_list_classifications(employee_id: int, current_user=Depends(get_current_payroll_operator),
                            db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeEmploymentClassification, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/classifications", summary="Record a DRAFT employment classification")
def be_create_classification(employee_id: int, body: Dict[str, Any] = Body(...),
                             current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_employment_classification(db, _org_id(current_user), employee_id, payload,
                                                              _actor(current_user), reason))


@router.post("/classifications/{row_id}/approve", summary="Approve an employment classification (four-eyes)")
def be_approve_classification(row_id: int, current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_employment_classification(db, _org_id(current_user), row_id,
                                                               _actor(current_user)))


# ── declarations ────────────────────────────────────────────────────────────
@router.get("/employees/{employee_id}/declarations", summary="Every declaration of an employee")
def be_list_declarations(employee_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeDeclaration, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/declarations", summary="Record a received declaration (with evidence)")
def be_create_declaration(employee_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.record_be_declaration(db, _org_id(current_user), employee_id, dict(body or {}),
                                                _actor(current_user)))


@router.post("/declarations/{row_id}/approve", summary="Approve a declaration (four-eyes)")
def be_approve_declaration(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_declaration(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/declarations/{row_id}/withdraw", summary="Withdraw a declaration from a date (history kept)")
def be_withdraw_declaration(row_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.withdraw_be_declaration(db, _org_id(current_user), row_id, _actor(current_user),
                                                  body.get("reason"), body.get("effectiveTo")))


# ── identifiers (masked; four-eyes single-use reveal) ───────────────────────
@router.get("/employees/{employee_id}/identifiers", summary="An employee's NISS / BIS on file (masked)")
def be_list_identifiers(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return be.list_be_identifiers(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/identifiers", summary="Put a NISS or BIS on file (masked response)")
def be_create_identifier(employee_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    row = be.create_be_identifier(db, _org_id(current_user), body.get("identifierType"), body.get("value"),
                                  _actor(current_user), employee_id=employee_id)
    db.commit()
    return be.identifier_view(row)


@router.post("/identifiers/{vault_id}/reveal-request", summary="Request a single-use reveal (reason required)")
def be_request_reveal(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    be.request_be_identifier_reveal(db, _org_id(current_user), vault_id, body.get("reason"), _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_REQUESTED"}


@router.post("/identifiers/{vault_id}/reveal-approve", summary="Approve a reveal request (four-eyes)")
def be_approve_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    be.approve_be_identifier_reveal(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return {"vaultId": vault_id, "state": "REVEAL_APPROVED"}


@router.post("/identifiers/{vault_id}/reveal", summary="Use an approved reveal once (requester only)")
def be_reveal(vault_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    out = be.reveal_be_identifier(db, _org_id(current_user), vault_id, _actor(current_user))
    db.commit()
    return out


@router.post("/identifiers/{vault_id}/delete", summary="Delete an identifier (reason required; history kept)")
def be_delete_identifier(vault_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    row = be.delete_be_identifier(db, _org_id(current_user), vault_id, _actor(current_user), body.get("reason"))
    db.commit()
    return be.identifier_view(row)


# ── employee summary ────────────────────────────────────────────────────────
@router.get("/employees/{employee_id}/summary", summary="An employee's Belgium records (identifiers masked)")
def be_employee_summary(employee_id: int, current_user=Depends(get_current_payroll_operator),
                        db: Session = Depends(get_db)):
    return be.employee_summary(db, _org_id(current_user), employee_id)


# ── applicability resolver (spec §2, §13): read-only ────────────────────────
@router.post("/classification/resolve",
             summary="Resolve employer / worker category, Joint Committee and blocking reasons for a pay date")
def be_resolve_classification(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_payroll_operator),
                              db: Session = Depends(get_db)):
    body = dict(body or {})
    return be.resolve_be_classification(db, _org_id(current_user), body.get("employeeId"), body.get("payDate"),
                                        period_start=body.get("periodStart"))


# ── Joint Committee picker (D3): platform definitions, read-only ────────────
@router.get("/joint-committees", summary="Belgian Joint Committee agreements (platform definitions) for the picker")
def be_list_joint_committees(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import be_super_admin

    _org_id(current_user)
    return be_super_admin.joint_committees(db)


@router.get("/options", summary="Choice lists for the Belgium organisation screens (catalogue vocabularies)")
def be_org_options(current_user=Depends(get_current_payroll_operator)):
    _org_id(current_user)
    return be.org_options()


# ── G-28: platform pay component -> Belgian component mappings ──────────────
@router.get("/component-mappings", summary="Every version of your platform -> Belgian pay component mappings")
def be_list_component_mappings(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeComponentMapping, _org_id(current_user))


@router.post("/component-mappings", summary="Record a DRAFT pay component mapping (org admin)")
def be_create_component_mapping(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                                db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_component_mapping(db, _org_id(current_user), payload, _actor(current_user),
                                                      reason))


@router.post("/component-mappings/{row_id}/approve", summary="Approve a pay component mapping (four-eyes)")
def be_approve_component_mapping(row_id: int, current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_component_mapping(db, _org_id(current_user), row_id, _actor(current_user)))


# ── B1: employer substitute days (D15) ──────────────────────────────────────
@router.get("/substitute-days", summary="Your recorded Belgian substitute holidays")
def be_list_substitute_days(year: Optional[int] = None, current_user=Depends(get_current_payroll_operator),
                            db: Session = Depends(get_db)):
    return be.be_substitute_days(db, _org_id(current_user), year)


@router.post("/substitute-days", summary="Record an employer substitute day for a public holiday (audited)")
def be_create_substitute_day(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    out = be.record_be_substitute_day(db, _org_id(current_user), body, _actor(current_user))
    db.commit()
    return out


# ── B2: absence episodes and holiday certificates ───────────────────────────
@router.get("/employees/{employee_id}/absence-episodes", summary="An employee's absence episodes (no diagnosis)")
def be_list_absence_episodes(employee_id: int, current_user=Depends(get_current_payroll_operator),
                             db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeAbsenceEpisode, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/absence-episodes", summary="Record a DRAFT absence episode (dates and kind only)")
def be_create_absence_episode(employee_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_absence_episode(db, _org_id(current_user), employee_id, payload,
                                                    _actor(current_user), reason))


@router.post("/absence-episodes/{row_id}/approve", summary="Approve an absence episode (four-eyes)")
def be_approve_absence_episode(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_absence_episode(db, _org_id(current_user), row_id, _actor(current_user)))


@router.post("/absence-episodes/{row_id}/cancel", summary="Cancel an absence episode (reason; history kept)")
def be_cancel_absence_episode(row_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _commit(db, be.cancel_be_absence_episode(db, _org_id(current_user), row_id, _actor(current_user),
                                                    body.get("reason")))


@router.get("/employees/{employee_id}/holiday-certificates", summary="An employee's holiday certificates")
def be_list_holiday_certificates(employee_id: int, current_user=Depends(get_current_payroll_operator),
                                 db: Session = Depends(get_db)):
    return _list(db, be._models().PayrollBeHolidayCertificate, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/holiday-certificates", summary="Record a DRAFT holiday certificate")
def be_create_holiday_certificate(employee_id: int, body: Dict[str, Any] = Body(...),
                                  current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    payload, reason = _split(body)
    return _commit(db, be.record_be_holiday_certificate(db, _org_id(current_user), employee_id, payload,
                                                        _actor(current_user), reason))


@router.post("/holiday-certificates/{row_id}/approve",
             summary="Approve a holiday certificate (four-eyes; immutable afterwards)")
def be_approve_holiday_certificate(row_id: int, current_user=Depends(get_current_org_admin),
                                   db: Session = Depends(get_db)):
    return _commit(db, be.approve_be_holiday_certificate(db, _org_id(current_user), row_id, _actor(current_user)))


# ── B3: run preflight, corrections, payment batches (D13) ───────────────────
@router.get("/runs/{run_id}/preflight", summary="Belgian run preflight: blocking items, pending items, fingerprint")
def be_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return be.be_run_preflight_view(db, _org_id(current_user), run_id)


@router.post("/payslips/{payslip_item_id}/corrections",
             summary="Linked correction of a committed Belgian payslip (reason + evidence; original untouched)")
def be_create_correction(payslip_item_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    out = be.create_be_correction(db, _org_id(current_user), payslip_item_id, body, _actor(current_user))
    db.commit()
    return out


@router.get("/runs/{run_id}/payment-preview", summary="Payable Belgian payslips and exceptions (nothing built)")
def be_payment_preview(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    out = pay.salary_payment_preview(db, _org_id(current_user), run_id)
    for row in out["payable"]:
        row["iban"] = pay.mask_iban(row["iban"])
        row["amount"] = str(row["amount"])
    return out


@router.post("/runs/{run_id}/payment-batches", summary="Build the DRAFT SEPA salary batch of a committed run")
def be_create_payment_batch(run_id: int, body: Dict[str, Any] = Body(default={}),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    body = dict(body or {})
    execution = be._as_date(body["executionDate"], "executionDate") if body.get("executionDate") else None
    row = pay.create_salary_payment_batch(db, _org_id(current_user), run_id, _actor(current_user),
                                          requested_execution_date=execution,
                                          idempotency_key=body.get("idempotencyKey"),
                                          exclusions=body.get("exclusions"))
    db.commit()
    return pay.batch_view(db, _org_id(current_user), row.id)


@router.get("/payment-batches", summary="Your Belgian payment batches")
def be_list_payment_batches(runId: Optional[int] = None, current_user=Depends(get_current_payroll_operator),
                            db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    return pay.list_payment_batches(db, _org_id(current_user), runId)


@router.get("/payment-batches/{batch_id}", summary="A Belgian payment batch (IBANs masked)")
def be_get_payment_batch(batch_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.post("/payment-batches/{batch_id}/approve", summary="Approve a payment batch (four-eyes)")
def be_approve_payment_batch(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    pay.approve_payment_batch(db, _org_id(current_user), batch_id, _actor(current_user))
    db.commit()
    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.post("/payment-batches/{batch_id}/submit", summary="Mark an approved batch as submitted to the bank")
def be_submit_payment_batch(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    pay.submit_payment_batch(db, _org_id(current_user), batch_id, _actor(current_user))
    db.commit()
    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.post("/payment-batches/{batch_id}/bank-result", summary="Record the bank's outcome for a submitted batch")
def be_payment_bank_result(batch_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    pay.record_bank_result(db, _org_id(current_user), batch_id, body.get("outcome"))
    db.commit()
    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.post("/payment-batches/{batch_id}/reconcile", summary="Reconcile an accepted batch with the bank statement")
def be_reconcile_payment_batch(batch_id: int, current_user=Depends(get_current_org_admin),
                               db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    pay.reconcile_payment_batch(db, _org_id(current_user), batch_id)
    db.commit()
    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.post("/payment-batches/{batch_id}/returns", summary="Record a returned transfer (reason)")
def be_payment_return(batch_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                      db: Session = Depends(get_db)):
    from app.modules.payroll import belgium_payment_service as pay

    pay.handle_payment_return(db, _org_id(current_user), batch_id, body.get("endToEndId"), body.get("reason"))
    db.commit()
    return pay.batch_view(db, _org_id(current_user), batch_id)


@router.get("/payment-batches/{batch_id}/file", summary="Download the pain.001 file of an approved batch")
def be_payment_batch_file(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    from app.modules.payroll import belgium_payment_service as pay

    name, xml = pay.batch_file(db, _org_id(current_user), batch_id)
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/runs/{run_id}/exceptions/acknowledge",
             summary="Acknowledge one employee's engine exception before approval (reason; audited)")
def be_acknowledge_exception(run_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    out = be.acknowledge_be_run_exception(db, _org_id(current_user), run_id, body, _actor(current_user))
    db.commit()
    return out

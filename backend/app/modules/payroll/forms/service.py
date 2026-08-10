"""
modules/payroll/forms/service.py
---------------------------------
"Send Template" — build a data-collection form (standard Employee fields +
org-defined custom fields), email it to one or more employees as a
single-use no-login link, and review what they submit before it's applied
to PayrollEmployee. Nothing here touches an employee record until an admin
explicitly approves a submission.
"""
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.modules.payroll.models import (
    PayrollEmployee, PayrollCustomFieldDefinition, PayrollUpdateForm,
    PayrollUpdateFormSend, PayrollUpdateFormSubmission,
    FormSendStatus, FormSubmissionStatus,
)
from app.modules.payroll.service import FIELD_MAP, log_activity, ActivityStatus
from app.core.exceptions import NotFoundException
from app.services.email_service import send_update_form_invite_email
from app.config import settings

FORM_TOKEN_TTL_DAYS = 7
_NUMERIC_STANDARD_FIELDS = {"ctc", "basic", "hra"}


# ── Custom field definitions ────────────────────────────────────────────

def _slugify_key(label: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in label.strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "field"


def list_custom_fields(db: Session, organization_id: int) -> List[PayrollCustomFieldDefinition]:
    return db.query(PayrollCustomFieldDefinition).filter(
        PayrollCustomFieldDefinition.organization_id == organization_id
    ).order_by(PayrollCustomFieldDefinition.created_at).all()


def create_custom_field(db: Session, organization_id: int, label: str, field_type: str,
                         select_options: List[str] = None, actor_id: int = None) -> PayrollCustomFieldDefinition:
    base_key = _slugify_key(label)
    key = base_key
    suffix = 1
    while db.query(PayrollCustomFieldDefinition).filter(
        PayrollCustomFieldDefinition.organization_id == organization_id,
        PayrollCustomFieldDefinition.field_key == key,
    ).first():
        suffix += 1
        key = f"{base_key}_{suffix}"

    field = PayrollCustomFieldDefinition(
        organization_id=organization_id, field_key=key, label=label,
        field_type=field_type, select_options=select_options, created_by=actor_id,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    log_activity(db, organization_id, f"Custom employee field '{label}' added.", ActivityStatus.INFO, actor_id=actor_id)
    return field


def delete_custom_field(db: Session, organization_id: int, field_id: int) -> None:
    field = db.query(PayrollCustomFieldDefinition).filter(
        PayrollCustomFieldDefinition.id == field_id,
        PayrollCustomFieldDefinition.organization_id == organization_id,
    ).first()
    if not field:
        raise NotFoundException(f"Custom field {field_id} not found.")
    db.delete(field)
    db.commit()
    # Existing PayrollEmployee.custom_fields[key] values are deliberately
    # left in place — removing the definition just stops it being shown or
    # asked for going forward; it isn't a data-erasure action.


# ── Form templates ───────────────────────────────────────────────────────

def create_form(db: Session, organization_id: int, name: str, fields: list, actor_id: int = None) -> PayrollUpdateForm:
    fields_dump = [f.model_dump() if hasattr(f, "model_dump") else f for f in fields]
    form = PayrollUpdateForm(organization_id=organization_id, name=name, fields_config=fields_dump, created_by=actor_id)
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def list_forms(db: Session, organization_id: int) -> List[PayrollUpdateForm]:
    return db.query(PayrollUpdateForm).filter(
        PayrollUpdateForm.organization_id == organization_id
    ).order_by(PayrollUpdateForm.created_at.desc()).all()


def get_form(db: Session, organization_id: int, form_id: int) -> PayrollUpdateForm:
    form = db.query(PayrollUpdateForm).filter(
        PayrollUpdateForm.id == form_id, PayrollUpdateForm.organization_id == organization_id,
    ).first()
    if not form:
        raise NotFoundException(f"Form {form_id} not found.")
    return form


# ── Sending ──────────────────────────────────────────────────────────────

def send_form(db: Session, organization_id: int, form_id: int, employee_ids: List[int]) -> dict:
    form = get_form(db, organization_id, form_id)
    results = []
    expires_at = datetime.now(timezone.utc) + timedelta(days=FORM_TOKEN_TTL_DAYS)

    for emp_id in employee_ids:
        employee = db.query(PayrollEmployee).filter(
            PayrollEmployee.id == emp_id, PayrollEmployee.organization_id == organization_id,
        ).first()
        if not employee:
            results.append({"employeeId": emp_id, "status": "failed", "reason": "Employee not found."})
            continue
        if not employee.email:
            results.append({"employeeId": emp_id, "status": "failed", "reason": "Employee has no email on file."})
            continue

        token = secrets.token_urlsafe(32)
        send = PayrollUpdateFormSend(
            organization_id=organization_id, form_id=form.id, employee_id=employee.id,
            token=token, status=FormSendStatus.SENT.value, expires_at=expires_at,
        )
        db.add(send)
        db.commit()
        db.refresh(send)

        form_link = f"{settings.FRONTEND_URL}/forms/fill/{token}"
        sent_ok = send_update_form_invite_email(
            employee.email, employee.name, form.name, form_link,
            expires_at.strftime("%b %d, %Y"), organization_id=organization_id, db=db,
        )
        results.append({"employeeId": emp_id, "status": "sent" if sent_ok else "failed",
                         **({"reason": "Email delivery failed."} if not sent_ok else {})})

    sent_count = len([r for r in results if r["status"] == "sent"])
    log_activity(db, organization_id, f"Sent '{form.name}' to {sent_count} employee(s).", ActivityStatus.INFO)
    return {"results": results}


# ── Public (unauthenticated) fetch/submit ────────────────────────────────
# These two functions are the ONLY code paths reachable without a login —
# they must never expose anything beyond the single form tied to the exact
# token presented, and never accept organization_id from the caller.

def _get_send_by_token(db: Session, token: str) -> PayrollUpdateFormSend:
    send = db.query(PayrollUpdateFormSend).filter(PayrollUpdateFormSend.token == token).first()
    if not send:
        raise NotFoundException("This link is invalid.")
    return send


def _aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_public_form(db: Session, token: str) -> dict:
    send = _get_send_by_token(db, token)
    now = datetime.now(timezone.utc)

    if now > _aware(send.expires_at) and send.status == FormSendStatus.SENT.value:
        send.status = FormSendStatus.EXPIRED.value
        db.commit()
    elif send.status == FormSendStatus.SENT.value:
        send.status = FormSendStatus.OPENED.value
        send.opened_at = now
        db.commit()

    form = db.query(PayrollUpdateForm).filter(PayrollUpdateForm.id == send.form_id).first()
    employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == send.employee_id).first()

    current_values = {}
    for f in (form.fields_config or []):
        key = f["key"]
        if f.get("source") == "custom":
            current_values[key] = (employee.custom_fields or {}).get(key)
        else:
            current_values[key] = getattr(employee, FIELD_MAP.get(key, key), None)

    return {
        "formName": form.name,
        "employeeName": employee.name,
        "fields": form.fields_config,
        "currentValues": current_values,
        "status": send.status,
    }


def submit_public_form(db: Session, token: str, values: dict) -> dict:
    send = _get_send_by_token(db, token)

    if send.status == FormSendStatus.SUBMITTED.value:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="This form has already been submitted.")

    now = datetime.now(timezone.utc)
    if send.status == FormSendStatus.EXPIRED.value or now > _aware(send.expires_at):
        send.status = FormSendStatus.EXPIRED.value
        db.commit()
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="This link has expired.")

    form = db.query(PayrollUpdateForm).filter(PayrollUpdateForm.id == send.form_id).first()
    allowed_keys = {f["key"] for f in (form.fields_config or [])}
    clean_values = {k: v for k, v in (values or {}).items() if k in allowed_keys}

    submission = PayrollUpdateFormSubmission(
        organization_id=send.organization_id, send_id=send.id,
        submitted_data=clean_values, status=FormSubmissionStatus.PENDING.value,
    )
    db.add(submission)
    send.status = FormSendStatus.SUBMITTED.value
    send.submitted_at = now
    db.commit()
    return {"message": "Thank you — your response has been submitted for review."}


# ── Review queue ─────────────────────────────────────────────────────────

def _current_values_for(employee: PayrollEmployee, form: PayrollUpdateForm) -> dict:
    current_values = {}
    for f in (form.fields_config or []):
        key = f["key"]
        if f.get("source") == "custom":
            current_values[key] = (employee.custom_fields or {}).get(key)
        else:
            current_values[key] = getattr(employee, FIELD_MAP.get(key, key), None)
    return current_values


def list_submissions(db: Session, organization_id: int, status: str = None) -> List[dict]:
    query = db.query(PayrollUpdateFormSubmission, PayrollUpdateFormSend, PayrollEmployee, PayrollUpdateForm).join(
        PayrollUpdateFormSend, PayrollUpdateFormSubmission.send_id == PayrollUpdateFormSend.id,
    ).join(
        PayrollEmployee, PayrollUpdateFormSend.employee_id == PayrollEmployee.id,
    ).join(
        PayrollUpdateForm, PayrollUpdateFormSend.form_id == PayrollUpdateForm.id,
    ).filter(PayrollUpdateFormSubmission.organization_id == organization_id)
    if status:
        query = query.filter(PayrollUpdateFormSubmission.status == status)

    rows = query.order_by(PayrollUpdateFormSubmission.created_at.desc()).all()
    return [
        {
            "id": submission.id,
            "employeeId": employee.id,
            "employeeName": employee.name,
            "formName": form.name,
            "fields": form.fields_config,
            "submittedData": submission.submitted_data,
            "currentValues": _current_values_for(employee, form),
            "status": submission.status,
            "createdAt": submission.created_at,
        }
        for submission, send, employee, form in rows
    ]


def _apply_submission(employee: PayrollEmployee, form: PayrollUpdateForm, data: dict) -> None:
    for f in (form.fields_config or []):
        key = f["key"]
        if key not in data:
            continue
        value = data[key]
        if value == "" or value is None:
            continue
        if f.get("source") == "custom":
            custom = dict(employee.custom_fields or {})
            custom[key] = value
            employee.custom_fields = custom
        else:
            attr = FIELD_MAP.get(key)
            if not attr or not hasattr(employee, attr):
                continue
            if attr in _NUMERIC_STANDARD_FIELDS:
                try:
                    value = Decimal(str(value))
                except Exception:
                    continue
            setattr(employee, attr, value)


def review_submission(db: Session, organization_id: int, submission_id: int, approve: bool,
                       notes: str = None, actor_id: int = None) -> dict:
    submission = db.query(PayrollUpdateFormSubmission).filter(
        PayrollUpdateFormSubmission.id == submission_id,
        PayrollUpdateFormSubmission.organization_id == organization_id,
    ).first()
    if not submission:
        raise NotFoundException(f"Submission {submission_id} not found.")
    if submission.status != FormSubmissionStatus.PENDING.value:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="This submission has already been reviewed.")

    send = db.query(PayrollUpdateFormSend).filter(PayrollUpdateFormSend.id == submission.send_id).first()
    form = db.query(PayrollUpdateForm).filter(PayrollUpdateForm.id == send.form_id).first()
    employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == send.employee_id).first()

    if approve:
        _apply_submission(employee, form, submission.submitted_data or {})
        submission.status = FormSubmissionStatus.APPROVED.value
    else:
        submission.status = FormSubmissionStatus.REJECTED.value

    submission.reviewed_by = actor_id
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.review_notes = notes
    db.commit()

    log_activity(
        db, organization_id,
        f"{'Approved' if approve else 'Rejected'} '{form.name}' submission from '{employee.name}'.",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    return {"message": "Submission approved and applied." if approve else "Submission rejected."}

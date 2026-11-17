"""
tests/test_public_form_fields.py
--------------------------------
P1 follow-ups (2026-11-16):

1. A public (Send Template) form may only ask for details an employee provides
   about themselves - not salary, status, dates or job details, which an
   approved submission used to write straight onto the employee record.
2. Email is required when a single employee is created through the API.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import router as payroll_router
from app.modules.payroll import service
from app.modules.payroll.forms import service as forms_service
from app.modules.payroll.models import (
    PayrollUpdateForm, PayrollUpdateFormSend, PayrollUpdateFormSubmission,
)
from app.modules.payroll.schemas import EmployeeCreate


def _employee(db, organization):
    return service.create_employee(db, EmployeeCreate(
        name="Asha Rao", email="asha@example.com", country_code="IN", employee_code="PF-1",
        ctc=Decimal("600000"),
    ), organization.id)


def _send(db, organization, form, employee):
    send = PayrollUpdateFormSend(organization_id=organization.id, form_id=form.id, employee_id=employee.id,
                                 token=f"tok-{form.id}", status="sent",
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(send)
    db.commit()
    return send


# 1 ── public forms: self-service fields only ─────────────────────────────────

def test_a_form_asking_for_salary_or_status_is_refused(db, organization):
    with pytest.raises(BadRequestException) as exc:
        forms_service.create_form(db, organization.id, "Bad form", [
            {"key": "bankName", "label": "Bank name", "type": "text", "source": "standard"},
            {"key": "ctc", "label": "CTC (annual)", "type": "number", "source": "standard"},
            {"key": "status", "label": "Status", "type": "select", "source": "standard"},
        ])
    assert "CTC (annual)" in exc.value.message and "Status" in exc.value.message
    assert "Bank name" not in exc.value.message
    assert db.query(PayrollUpdateForm).count() == 0


def test_self_service_and_custom_fields_are_allowed(db, organization):
    form = forms_service.create_form(db, organization.id, "Bank details", [
        {"key": key, "label": key, "type": "text", "source": "standard"}
        for key in ("name", "email", "phone", "bankName", "bankAccountNumber", "ifscCode", "panNumber", "uan")
    ] + [{"key": "tshirt", "label": "T-shirt size", "type": "text", "source": "custom"}])
    assert len(form.fields_config) == 9


def test_an_older_form_never_shows_or_applies_employer_fields(db, organization):
    employee = _employee(db, organization)
    # Saved before the rule existed (written straight to the table).
    form = PayrollUpdateForm(organization_id=organization.id, name="Old form", fields_config=[
        {"key": "bankName", "label": "Bank name", "type": "text", "source": "standard"},
        {"key": "ctc", "label": "CTC", "type": "number", "source": "standard"},
    ])
    db.add(form)
    db.commit()
    send = _send(db, organization, form, employee)

    public = forms_service.get_public_form(db, send.token)
    assert [f["key"] for f in public["fields"]] == ["bankName"]
    assert "ctc" not in public["currentValues"]

    forms_service.submit_public_form(db, send.token, {"bankName": "HDFC", "ctc": "9999999"})
    submission = db.query(PayrollUpdateFormSubmission).one()
    assert submission.submitted_data == {"bankName": "HDFC"}

    # Even a stored submission that carries the field never applies it.
    submission.submitted_data = {"bankName": "HDFC", "ctc": "9999999"}
    db.commit()
    forms_service.review_submission(db, organization.id, submission.id, approve=True)
    db.refresh(employee)
    assert employee.bank_name == "HDFC" and employee.ctc == Decimal("600000")


# 2 ── email required on single create ────────────────────────────────────────

@pytest.mark.parametrize("email", [None, "", "   "])
def test_api_create_without_email_is_refused(db, organization, email):
    user = SimpleNamespace(organization_id=organization.id)
    with pytest.raises(BadRequestException, match="Email is required"):
        payroll_router.create_employee(EmployeeCreate(name="No Email", email=email), db=db, current_user=user)

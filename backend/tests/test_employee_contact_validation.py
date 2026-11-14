"""
tests/test_employee_contact_validation.py
-----------------------------------------
Employee email / phone validation (QA: phone fields accepted letters; email
format only loosely checked in the browser). Every employee write path now
normalises and validates both on the server:

  * email: trimmed + lowercased, one "@", a dotted domain;
  * phone: digits, spaces, ( ) - . and a leading + only; stored as E.164; a
    number without a country code is read as the employee's own country.

An unchanged legacy value already stored is not re-checked, so old records
stay editable.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.payroll import service
from app.modules.payroll.contact_validation import (
    ContactValidationError, normalize_email, normalize_employee_contact, normalize_phone,
)
from app.modules.payroll.models import PayrollEmployee
from app.modules.payroll.schemas import BulkEmployeeRequest, EmployeeCreate, EmployeeUpdate


# ── The rules ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, country, expected", [
    ("98765 43210", "IN", "+919876543210"),
    ("07700 900123", "UK", "+447700900123"),          # payroll "UK" is ISO "GB"
    ("(415) 555-0123", "US", "+14155550123"),
    ("0412 345 678", "AU", "+61412345678"),
    ("876-555-0123", "JM", "+18765550123"),           # Caribbean NANP
    ("0044 7700 900123", "IN", "+447700900123"),      # 00 prefix
    ("+44 7700 900123", "IN", "+447700900123"),       # a foreign number is fine
    ("+592 222 1234", "GY", "+5922221234"),
])
def test_phone_is_normalised_to_e164(raw, country, expected):
    assert normalize_phone(raw, country) == expected


@pytest.mark.parametrize("raw", ["98765abc10", "+44 7700 9OO123", "call me", "#123", "98765/43210"])
def test_phone_with_letters_or_symbols_is_rejected(raw):
    with pytest.raises(ContactValidationError, match="only digits"):
        normalize_phone(raw, "IN")


@pytest.mark.parametrize("raw", ["+1 555", "+1234567890123456", "12"])
def test_phone_of_impossible_length_is_rejected(raw):
    with pytest.raises(ContactValidationError):
        normalize_phone(raw, "IN")


def test_national_phone_without_a_country_needs_the_country_code():
    with pytest.raises(ContactValidationError, match="country code"):
        normalize_phone("9876543210", None)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_values_are_none(blank):
    assert normalize_phone(blank, "IN") is None and normalize_email(blank) is None


def test_email_is_trimmed_and_lowercased():
    assert normalize_email("  John.Doe@Example.COM ") == "john.doe@example.com"


@pytest.mark.parametrize("raw", ["a@b", "a@@b.com", "a b@c.com", "a@b..com", "x@y.c0m", "@b.com", "a@.com",
                                 "a" * 65 + "@b.com", "a@" + "b" * 250 + ".com"])
def test_invalid_email_is_rejected(raw):
    with pytest.raises(ContactValidationError, match="valid email"):
        normalize_email(raw)


def test_unchanged_legacy_value_is_not_rechecked():
    legacy = SimpleNamespace(email="Old Value", phone="call reception")
    fields = {"email": "old value", "phone": "call reception"}
    assert normalize_employee_contact(fields, "IN", current=legacy) == fields   # untouched, no error
    with pytest.raises(ContactValidationError):
        normalize_employee_contact({"phone": "call me later"}, "IN", current=legacy)


# ── The write paths ─────────────────────────────────────────────────────────

def _create(db, organization, **kw):
    data = {"name": "Asha Rao", "email": "asha@example.com", "country_code": "IN", "employee_code": "ZC-9001"}
    data.update(kw)
    return service.create_employee(db, EmployeeCreate(**data), organization.id)


def test_create_stores_normalised_email_and_e164_phone(db, organization):
    emp = _create(db, organization, email=" Asha.Rao@Example.COM ", phone="98765 43210")
    assert emp.email == "asha.rao@example.com"
    assert emp.phone == "+919876543210"


def test_create_rejects_letters_in_phone(db, organization):
    with pytest.raises(HTTPException) as exc:
        _create(db, organization, phone="98765abc10")
    assert exc.value.status_code == 400 and "only digits" in exc.value.detail
    assert db.query(PayrollEmployee).count() == 0


def test_create_rejects_invalid_email(db, organization):
    with pytest.raises(HTTPException) as exc:
        _create(db, organization, email="asha@@example")
    assert exc.value.status_code == 400


def test_duplicate_check_sees_the_normalised_email(db, organization):
    _create(db, organization, email="asha@example.com")
    with pytest.raises(HTTPException) as exc:
        _create(db, organization, email="  ASHA@Example.com", employee_code="ZC-9002")
    assert exc.value.status_code == 409


def test_update_validates_a_changed_phone(db, organization):
    emp = _create(db, organization)
    with pytest.raises(HTTPException):
        service.update_employee(db, emp.id, EmployeeUpdate(phone="call me"), organization.id)
    updated = service.update_employee(db, emp.id, EmployeeUpdate(phone="0044 7700 900123"), organization.id)
    assert updated.phone == "+447700900123"


def test_legacy_record_stays_editable(db, organization):
    """A phone stored before the rules is not re-checked when the edit form
    sends it back unchanged with another field."""
    emp = PayrollEmployee(organization_id=organization.id, employee_code="ZC-9003", name="Legacy",
                          email="legacy@example.com", phone="ext 42 reception", country_code="IN")
    db.add(emp)
    db.commit()
    updated = service.update_employee(
        db, emp.id, EmployeeUpdate(designation="Lead", phone="ext 42 reception"), organization.id)
    assert updated.designation == "Lead" and updated.phone == "ext 42 reception"


def test_bulk_create_reports_a_bad_phone_row_without_failing_the_batch(db, organization, monkeypatch):
    # The employee-code generator takes a PostgreSQL advisory lock; the SQLite
    # test DB only needs a starting code for the batch.
    import app.core.code_generation as code_generation
    monkeypatch.setattr(code_generation, "generate_employee_code", lambda db, organization_id: "ZC-0001")
    payload = BulkEmployeeRequest(employees=[
        {"name": "Good Row", "email": "Good@Example.com", "phone": 9876543210, "countryCode": "IN"},
        {"name": "Bad Row", "email": "bad@example.com", "phone": "98765abc10", "countryCode": "IN"},
    ])
    result = service.bulk_create_employees(db, payload, organization.id)
    assert result["created"] == 1
    assert result["employees"][0].email == "good@example.com"
    assert result["employees"][0].phone == "+919876543210"     # numeric Excel cell, national number
    (failure,) = result["failed"]
    assert failure["row"]["name"] == "Bad Row" and "only digits" in failure["reason"]


def test_bulk_update_validates_and_normalises(db, organization):
    emp = _create(db, organization)
    payload = BulkEmployeeRequest(employees=[{"id": emp.id, "phone": "(98765) 43210"}])
    result = service.bulk_update_employees(db, payload, organization.id)
    assert result["failed"] == [] and result["employees"][0].phone == "+919876543210"
    bad = service.bulk_update_employees(
        db, BulkEmployeeRequest(employees=[{"id": emp.id, "email": "not-an-email"}]), organization.id)
    assert bad["updated"] == 0 and "valid email" in bad["failed"][0]["reason"]


# ── Send Template: public submission and approval ───────────────────────────

def _form_send(db, organization, employee):
    from datetime import datetime, timedelta, timezone

    from app.modules.payroll.forms import service as forms_service
    from app.modules.payroll.models import PayrollUpdateFormSend

    form = forms_service.create_form(db, organization.id, "Contact update", [
        {"key": "email", "label": "Email", "type": "text", "source": "standard"},
        {"key": "phone", "label": "Phone", "type": "text", "source": "standard"},
    ])
    send = PayrollUpdateFormSend(organization_id=organization.id, form_id=form.id, employee_id=employee.id,
                                 token="tok-contact-123", status="sent",
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(send)
    db.commit()
    return forms_service, send


def test_public_form_refuses_a_bad_phone(db, organization):
    emp = _create(db, organization)
    forms_service, send = _form_send(db, organization, emp)
    with pytest.raises(HTTPException) as exc:
        forms_service.submit_public_form(db, send.token, {"phone": "phone me"})
    assert exc.value.status_code == 400


def test_approving_a_submission_applies_normalised_values(db, organization):
    from app.modules.payroll.models import PayrollUpdateFormSubmission

    emp = _create(db, organization)
    forms_service, send = _form_send(db, organization, emp)
    forms_service.submit_public_form(db, send.token, {"email": " New@Example.COM ", "phone": "98765 43210"})
    sub = db.query(PayrollUpdateFormSubmission).one()
    assert sub.submitted_data == {"email": "new@example.com", "phone": "+919876543210"}
    forms_service.review_submission(db, organization.id, sub.id, approve=True)
    db.refresh(emp)
    assert (emp.email, emp.phone) == ("new@example.com", "+919876543210")


def test_approval_refuses_a_legacy_bad_submission_and_a_duplicate_email(db, organization):
    from app.modules.payroll.models import PayrollUpdateFormSubmission

    emp = _create(db, organization)
    _create(db, organization, email="taken@example.com", employee_code="ZC-9004")
    forms_service, send = _form_send(db, organization, emp)
    # Stored before validation existed (written straight to the table).
    sub = PayrollUpdateFormSubmission(organization_id=organization.id, send_id=send.id,
                                      submitted_data={"phone": "call me"}, status="pending")
    db.add(sub)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        forms_service.review_submission(db, organization.id, sub.id, approve=True)
    assert exc.value.status_code == 400
    sub.submitted_data = {"email": "TAKEN@example.com"}
    db.commit()
    with pytest.raises(HTTPException) as exc:
        forms_service.review_submission(db, organization.id, sub.id, approve=True)
    assert exc.value.status_code == 409

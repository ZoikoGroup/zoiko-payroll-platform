"""
tests/test_communications_part0_gaps.py
---------------------------------------
Positive-path coverage (6.5) for the operations that previously sent no
email, each asserting recipient, event_type and the communication_events row:

  - bulk employee create / update / delete → one summary to the org contact;
    bulk update additionally sends the per-employee sensitive-field notice
    (same notice + key family as the single-employee update) — nothing else
  - Germany overtime work-record HR approval decision → the employee
  - Super Admin forced password reset → IAM-007 with the admin-initiated
    copy variant, now audited (auth_email_events + communication_events)
  - form assignment (send_form) — already existed; now audited, and still
    synchronous because its response reports per-employee delivery
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.modules.communications.models import CommunicationEvent


def _rows(db, **filters):
    q = db.query(CommunicationEvent)
    for key, value in filters.items():
        q = q.filter(getattr(CommunicationEvent, key) == value)
    return q.order_by(CommunicationEvent.id).all()


@pytest.fixture()
def org(db, organization):
    from app.modules.payroll.models import CompanyComplianceDetails

    organization.email = "hr@testorg.test"
    db.add(CompanyComplianceDetails(
        organization_id=organization.id, name="Test Org", jurisdiction_country="IN", jurisdiction_state="KA",
    ))
    db.commit()
    # code_generation takes a PostgreSQL advisory lock; no-op it on SQLite.
    db.connection().connection.driver_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)
    return organization


@pytest.fixture()
def captured(monkeypatch):
    """Record (template, recipient, context) for every real send_approval_email."""
    from app.services import email_service

    sent = []
    real = email_service.send_approval_email

    def recorder(email, template_name, context, **kw):
        sent.append((template_name, email, context))
        return real(email, template_name, context, **kw)

    monkeypatch.setattr(email_service, "send_approval_email", recorder)
    return sent


def _employee(db, org_id, code, email, **extra):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}", email=email,
        country_code="IN", ctc=600000, basic=25000, hra=10000, status="Active",
        date_of_joining=date(2026, 1, 1), **extra,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


# ── 0.1 Bulk employee operations ────────────────────────────────────────────

def test_bulk_create_sends_one_summary_and_no_per_employee_welcome(db, org, captured):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import BulkEmployeeRequest

    payload = BulkEmployeeRequest(employees=[
        {"name": "Asha Rao", "email": "asha@testorg.test", "countryCode": "IN", "status": "active",
         "employmentType": "full_time", "panNumber": "AASPR0001A"},
        {"name": "Bharat Menon", "email": "bharat@testorg.test", "countryCode": "IN", "status": "active",
         "employmentType": "full_time", "panNumber": "ABCPR0002B"},
    ])
    result = service.bulk_create_employees(db, payload, org.id, actor_id=9)
    assert result["created"] == 2, result

    assert [(t, e) for t, e, _ in captured] == [("bulk_employee_operation_summary.html", "hr@testorg.test")]
    (row,) = _rows(db, event_type="payroll.bulk_employees_created")
    assert (row.outcome, row.recipient_email, row.module, row.actor_user_id) == (
        "sent", "hr@testorg.test", "payroll", 9,
    )
    assert _rows(db, event_type="payroll.employee_created") == []


def test_bulk_update_sends_sensitive_notices_only_to_changed_employees_plus_summary(db, org, captured):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import BulkEmployeeRequest

    bank_change = _employee(db, org.id, "E-1", "one@testorg.test", bank_account="111")
    cosmetic = _employee(db, org.id, "E-2", "two@testorg.test", designation="Analyst")

    payload = BulkEmployeeRequest(employees=[
        {"id": bank_change.id, "name": bank_change.name, "bankAccountNumber": "999"},
        {"id": cosmetic.id, "name": cosmetic.name, "designation": "Senior Analyst"},
    ])
    result = service.bulk_update_employees(db, payload, org.id, actor_id=9)
    assert result["updated"] == 2, result

    recipients = sorted((t, e) for t, e, _ in captured)
    assert recipients == [
        ("bulk_employee_operation_summary.html", "hr@testorg.test"),
        ("employee_sensitive_fields_changed.html", "one@testorg.test"),
    ]
    (notice,) = _rows(db, event_type="payroll.employee_sensitive_fields_changed")
    assert (notice.recipient_email, notice.outcome) == ("one@testorg.test", "sent")
    assert f"obj:employee:{bank_change.id}" in notice.idempotency_key
    (summary,) = _rows(db, event_type="payroll.bulk_employees_updated")
    assert summary.outcome == "sent"
    summary_ctx = next(c for t, _, c in captured if t == "bulk_employee_operation_summary.html")
    assert summary_ctx["succeeded_count"] == 2
    assert "1 employee(s)" in summary_ctx["employee_notice_line"]


def test_bulk_delete_sends_one_summary_with_failures(db, org, captured):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import BulkDeleteRequest

    emp = _employee(db, org.id, "E-9", "gone@testorg.test")
    result = service.bulk_delete_employees(db, BulkDeleteRequest(employee_ids=[emp.id, 424242]), org.id, actor_id=9)
    assert result["deleted"] == [emp.id] and len(result["failed"]) == 1

    assert [(t, e) for t, e, _ in captured] == [("bulk_employee_operation_summary.html", "hr@testorg.test")]
    ctx = captured[0][2]
    assert (ctx["succeeded_count"], ctx["failed_count"], ctx["has_failures"]) == (1, 1, True)
    (row,) = _rows(db, event_type="payroll.bulk_employees_deleted")
    assert row.outcome == "sent"
    assert _rows(db, event_type="payroll.employee_deleted") == []


def test_bulk_duplicate_submission_sends_one_summary(db, org, captured):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import BulkDeleteRequest

    request = BulkDeleteRequest(employee_ids=[31337])  # nothing deletable; same failed outcome twice
    service.bulk_delete_employees(db, request, org.id)
    service.bulk_delete_employees(db, request, org.id)
    outcomes = [r.outcome for r in _rows(db, event_type="payroll.bulk_employees_deleted")]
    assert outcomes == ["sent", "skipped_duplicate"]
    assert len(captured) == 1


# ── 0.2 Germany overtime approval decision ─────────────────────────────────

def test_overtime_approval_decision_notifies_employee(db, organization, captured):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import GermanyOvertimeWorkRecordCreate

    emp = _employee(db, organization.id, "DE-1", "ot@testorg.test")
    emp.country_code = "DE"
    db.commit()
    start = datetime(2026, 3, 2, 18, 0, tzinfo=timezone.utc)
    row = service.create_germany_overtime_work_record(
        db, emp.id, organization.id,
        GermanyOvertimeWorkRecordCreate(
            work_date=start.date(), start_datetime=start, end_datetime=start.replace(hour=20),
            hours=Decimal("2.00"), entry_source="MANUAL",
        ),
        actor_id=1,
    )
    assert row.hr_approval_status == "PENDING"
    service.set_germany_overtime_work_record_approval(db, row.id, organization.id, "APPROVED", actor_id=5)

    assert [(t, e) for t, e, _ in captured] == [("overtime_record_decision.html", "ot@testorg.test")]
    assert captured[0][2]["approved"] is True
    (event,) = _rows(db, event_type="payroll.overtime_record_approved")
    assert (event.outcome, event.actor_user_id, event.module) == ("sent", 5, "payroll")

    # Re-setting the same status is a no-op; reversing the decision notifies again.
    service.set_germany_overtime_work_record_approval(db, row.id, organization.id, "APPROVED", actor_id=5)
    service.set_germany_overtime_work_record_approval(db, row.id, organization.id, "REJECTED", actor_id=5)
    assert [c[2]["approved"] for c in captured] == [True, False]
    assert _rows(db, event_type="payroll.overtime_record_rejected")[0].outcome == "sent"


# ── 0.4 Super Admin forced password reset ──────────────────────────────────

def test_admin_reset_uses_iam007_admin_variant_and_is_audited(db, organization, captured):
    from app.core.security import hash_password
    from app.modules.auth import service as auth_service
    from app.modules.auth.models import User, UserRole
    from app.modules.super_admin import router as sa_router

    target = User(
        email="member@testorg.test", hashed_password=hash_password("x-Pass-1!"), role=UserRole.PAYROLL_ADMIN,
        organization_id=organization.id, first_name="Mem", last_name="Ber", is_active=True,
    )
    admin = User(
        email="sa@zoiko.dev", hashed_password=hash_password("x-Pass-2!"), role=UserRole.SUPER_ADMIN,
        first_name="Super", last_name="Admin", is_active=True,
    )
    db.add_all([target, admin])
    db.commit()

    sa_router.admin_reset_password(target.id, current_user=admin, db=db)

    ((template, recipient, ctx),) = captured
    assert (template, recipient) == ("org_admin_password_reset.html", "member@testorg.test")
    assert ctx["admin_initiated"] is True and ctx["self_requested"] is False
    assert ctx["subject"] == "A Zoiko Payroll administrator reset your password"
    (row,) = _rows(db, event_type=auth_service.ADMIN_RESET_EVENT_TYPE)
    assert (row.template_id, row.outcome, row.actor_user_id, row.module) == ("IAM-007", "sent", admin.id, "auth")
    (auth_row,) = db.query(auth_service.AuthEmailEvent).all()
    assert auth_row.outcome == "sent" and auth_row.event_type == auth_service.ADMIN_RESET_EVENT_TYPE


def test_admin_variant_renders_distinct_copy():
    from app.services.email_service import _compose_email_html, _load_template

    template = _load_template("org_admin_password_reset.html")
    admin = _compose_email_html(template, {"admin_initiated": True, "self_requested": False, "expires_at_local": "X"})
    self_req = _compose_email_html(template, {"admin_initiated": False, "self_requested": True, "expires_at_local": "X"})
    assert "platform administrator started a password reset" in admin
    assert "A password reset was requested for your account" not in admin
    assert "A password reset was requested for your account" in self_req
    assert "started a password reset for your account" not in self_req


# ── 0.5 Form assignment ─────────────────────────────────────────────────────

def test_form_assignment_is_audited_and_reports_delivery_synchronously(db, organization, captured):
    from app.modules.payroll.forms import service as forms_service
    from app.modules.payroll.models import PayrollUpdateForm

    emp = _employee(db, organization.id, "F-1", "form@testorg.test")
    form = PayrollUpdateForm(organization_id=organization.id, name="Bank details refresh", fields_config=[])
    db.add(form)
    db.commit()

    result = forms_service.send_form(db, organization.id, form.id, [emp.id])

    assert result["results"] == [{"employeeId": emp.id, "status": "sent"}]
    assert [(t, e) for t, e, _ in captured] == [("update_form_invite.html", "form@testorg.test")]
    (row,) = _rows(db, event_type="payroll.form_assigned")
    assert (row.outcome, row.recipient_email) == ("sent", "form@testorg.test")

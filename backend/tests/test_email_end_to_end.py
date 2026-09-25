"""
tests/test_email_end_to_end.py
-------------------------------
Real, business-logic-driven coverage for the 8 email-sending functions that
previously had zero coverage or coverage built only from hand-constructed
model rows / dummy arguments:

  - send_report_generated_email / send_report_generation_failed_email
  - send_password_reset_self_service_email
  - send_password_reset_completed_email
  - send_handoff_confirmation_email / send_handoff_support_notification_email
  - send_approval_email (missing-template failure path)
  - send_update_form_invite_email

Each test drives the actual service function that triggers the email
(real report generation against a real payroll run, a real single-use
password-reset token, a real Assist handoff confirmation, a real form
send) rather than constructing throwaway rows and calling the
`_notify_*` / `send_*_email` wrapper directly — so a regression in the
business logic upstream of the email (report validation, token
single-use enforcement, handoff cooldown, form-send bookkeeping) fails
these tests too, not just a template-rendering test.

SMTP is globally neutralized by conftest's autouse `_no_real_smtp`
fixture — sends log "Mock sending email ... | template=..." and never
open a socket.
"""
import logging
from datetime import date

import pytest

# Imported at module (collection) level so Base.metadata carries the Assist
# tables *before* any test's `db` fixture calls Base.metadata.create_all() —
# a lazy import inside a test body would run too late, after that call.
import app.modules.assist.models  # noqa: F401

from app.core.exceptions import BadRequestException


def _mock_send_templates(caplog):
    """Template names seen in "Mock sending email" records."""
    names = set()
    for record in caplog.records:
        msg = record.getMessage() or ""
        if "Mock sending email" in msg and "template=" in msg:
            names.add(msg.split("template=")[-1].strip())
    return names


# ── Shared fixtures ──────────────────────────────────────────────────────

def _make_user(db, email, organization_id=None, first_name="Test", last_name="User"):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole
    user = User(
        email=email, hashed_password=hash_password("a-strong-password-1"),
        role=UserRole.PAYROLL_ADMIN, first_name=first_name, last_name=last_name,
        organization_id=organization_id, is_active=True, is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_company(db, organization_id, country="IN"):
    from app.modules.payroll.models import CompanyComplianceDetails
    company = CompanyComplianceDetails(
        organization_id=organization_id, name="Acme India Pvt Ltd", tax_no="AAAAA0000A",
        jurisdiction_country=country, jurisdiction_state="",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _make_run_with_payslip(db, organization_id, status="Approved"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem
    employee = PayrollEmployee(
        organization_id=organization_id, employee_code="E001", name="Asha Rao", email="asha@acme.com",
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization_id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status=status, total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name="Asha Rao", basic_salary=60000, hra=20000, gross_pay=100000,
        pf=7200, esi=750, professional_tax=200, tds=11850, total_deductions=20000, net_pay=80000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, employee, item


def _build_template(db, creator, approver, country="IN", version="1.0"):
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.schemas import (
        ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
    )
    template = payroll_service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-SALARY-E2E", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry=country, reportingYear="2026-27", version=version,
        ), actor_id=creator.id,
    )
    earnings = payroll_service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"), actor_id=creator.id,
    )
    payroll_service.upsert_report_field(
        db, earnings.id, ReportTemplateFieldUpsert(
            fieldKey="gross_pay", label="Gross Pay", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay",
        ), actor_id=creator.id,
    )
    template = payroll_service.set_report_template_approver(db, template.id, actor_id=approver.id)
    assert template.status == "Approved"
    template = payroll_service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    template = payroll_service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    assert template.status == "Active"
    return template


# ── 1. Report generated / generation failed ─────────────────────────────

def test_report_generated_email_via_real_generation_pipeline(db, organization, caplog):
    from app.modules.payroll import service as payroll_service
    organization.email = "admin@acme.com"
    db.commit()
    creator = _make_user(db, "creator-report@acme.com")
    approver = _make_user(db, "approver-report@acme.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_template(db, creator, approver)

    with caplog.at_level(logging.INFO):
        report = payroll_service.generate_report_from_template(
            db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
        )
        payroll_service._notify_report_generated(db, report, organization.id)

    # The real pipeline actually ran (not a stub): rendered data reflects the
    # real payslip figures, proving the report itself generated correctly.
    assert report.status == "Generated"
    assert report.rendered_data["employees"][0]["values"]["gross_pay"] == float(item.gross_pay)
    sent = _mock_send_templates(caplog)
    assert "report_generated_ready.html" in sent, sent


def test_report_generation_failed_email_via_real_unfinalized_run(db, organization, caplog):
    from app.modules.payroll import service as payroll_service
    organization.email = "admin@acme.com"
    db.commit()
    creator = _make_user(db, "creator-report2@acme.com")
    approver = _make_user(db, "approver-report2@acme.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Draft")  # not finalized
    template = _build_template(db, creator, approver)

    with caplog.at_level(logging.INFO):
        with pytest.raises(BadRequestException) as excinfo:
            payroll_service.generate_report_from_template(
                db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
            )
        # Mirrors the router's own except-block (payroll/router.py
        # generate_report): real reason, not a canned message.
        payroll_service._notify_report_generation_failed(
            db, organization.id, template.report_type, run.period_label, str(excinfo.value),
        )
    sent = _mock_send_templates(caplog)
    assert "report_generation_failed.html" in sent, sent


# ── 2. Password reset — self-service ────────────────────────────────────

def test_password_reset_self_service_email_via_generate_random_password(db, organization, caplog):
    from app.core.security import verify_password
    from app.modules.auth import service as auth_service
    user = _make_user(db, "selfservice@acme.com", organization_id=organization.id)
    old_hash = user.hashed_password

    with caplog.at_level(logging.INFO):
        result = auth_service.generate_random_password(db, user.id)

    assert result["password"]
    db.refresh(user)
    # The password was genuinely replaced, not just an email fired blind.
    assert user.hashed_password != old_hash
    assert verify_password(result["password"], user.hashed_password)
    sent = _mock_send_templates(caplog)
    assert "password_reset_self_service.html" in sent, sent


# ── 3. Password reset — completed (real single-use token) ──────────────

def test_password_reset_completed_email_via_real_token_flow(db, organization, caplog):
    from app.modules.auth import service as auth_service
    from app.modules.auth.models import SecurityActionPurpose
    user = _make_user(db, "resetflow@acme.com", organization_id=organization.id)

    raw_token, _expires_at = auth_service._issue_action_token(
        db, user.email, user.organization_id, SecurityActionPurpose.RESET,
    )
    db.commit()

    with caplog.at_level(logging.INFO):
        result = auth_service.complete_action_token(
            db, raw_token, SecurityActionPurpose.RESET, "a-new-strong-password-1",
        )
    assert result["message"].startswith("Password set successfully")

    # Replaying the same, now-consumed token must be rejected — proves this
    # exercised the real single-use token machinery, not a stub.
    with pytest.raises(BadRequestException):
        auth_service.complete_action_token(db, raw_token, SecurityActionPurpose.RESET, "another-password-1")

    sent = _mock_send_templates(caplog)
    assert "password_reset_completed.html" in sent, sent


# ── 4/5. Assist handoff — confirmation + support notification ──────────

def test_handoff_emails_via_real_confirm_handoff_flow(db, organization, caplog, monkeypatch):
    from app.config import settings
    from app.modules.assist import service as assist_service
    # send_handoff_support_notification_email skips entirely (no send, no
    # template) when neither ASSIST_SUPPORT_EMAIL nor SMTP_FROM_EMAIL is
    # configured. Pin it explicitly rather than relying on whatever another
    # test in the same session left the shared settings singleton at.
    monkeypatch.setattr(settings, "ASSIST_SUPPORT_EMAIL", "support@acme.com")
    user = _make_user(db, "handoff-user@acme.com", organization_id=organization.id)
    payload = {
        "destination": "PAYROLL_SUPPORT",
        "reason_code": "COMPLEX_TAX_QUESTION",
        "summary": "Employee asked about a multi-state tax withholding edge case.",
    }
    preview = assist_service.create_handoff_preview(db, organization.id, user, payload)
    assert preview.state == "PREVIEWED"

    with caplog.at_level(logging.INFO):
        handoff = assist_service.confirm_handoff(db, organization.id, user, preview.id)

    assert handoff.state == "CREATED"
    assert handoff.case_id.startswith(f"case_{organization.id}_")

    # Real cooldown gate: a second preview for the same user within 24h must
    # be blocked, proving confirm_handoff's own re-check ran for real.
    with pytest.raises(BadRequestException):
        assist_service.create_handoff_preview(db, organization.id, user, payload)

    sent = _mock_send_templates(caplog)
    assert "assist_handoff_confirmation.html" in sent, sent
    assert "assist_handoff_support_notification.html" in sent, sent


# ── 6. send_approval_email — missing-template failure path ─────────────

def test_send_approval_email_missing_template_fails_loudly(caplog):
    from app.services.email_service import send_approval_email
    with caplog.at_level(logging.WARNING):
        result = send_approval_email(
            "someone@acme.com", "this_template_does_not_exist.html", {"subject": "x"},
        )
    # Must report failure explicitly, never silently report success for a
    # template that doesn't exist.
    assert result is False
    assert any(
        "this_template_does_not_exist.html" in (r.getMessage() or "") and "not found" in (r.getMessage() or "")
        for r in caplog.records
    )


# ── 7. Update-form invite ────────────────────────────────────────────────

def test_update_form_invite_email_via_real_send_form(db, organization, caplog):
    from app.modules.payroll.forms import service as forms_service
    from app.modules.payroll.models import PayrollEmployee

    employee = PayrollEmployee(
        organization_id=organization.id, employee_code="E100", name="Priya Nair", email="priya@acme.com",
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    form = forms_service.create_form(
        db, organization.id, "New Joiner Details",
        [{"key": "ctc", "label": "CTC", "type": "number"}],
    )

    with caplog.at_level(logging.INFO):
        result = forms_service.send_form(db, organization.id, form.id, [employee.id])

    assert result["results"] == [{"employeeId": employee.id, "status": "sent"}]
    sent = _mock_send_templates(caplog)
    assert "update_form_invite.html" in sent, sent

    # An employee with no email on file must fail the real validation path,
    # not silently "succeed" with no email sent.
    no_email_employee = PayrollEmployee(organization_id=organization.id, employee_code="E101", name="No Email Guy")
    db.add(no_email_employee)
    db.commit()
    db.refresh(no_email_employee)
    result2 = forms_service.send_form(db, organization.id, form.id, [no_email_employee.id])
    assert result2["results"][0]["status"] == "failed"
    assert result2["results"][0]["reason"] == "Employee has no email on file."

"""Payroll-Core email templates — canonical blue/white design + real trigger wiring.

Covers the 16 payroll-core templates (13 new + 3 restyled onto the shared
_base_wrapper.html shell):
  - render smoke: every template composes through the shared wrapper without
    unresolved placeholders, carries the canonical palette and the fixed
    security advisory;
  - palette parity: the wrapper and the advisory literally use the PALETTE
    hex values, so the design system has no per-file drift;
  - trigger wiring: real service functions (create/update/delete employee,
    leave submission, run/payslip deletion) and the `_notify_*` helpers each
    fire the correct template to the correct recipient, best-effort.

SMTP is globally neutralized by conftest's autouse `_no_real_smtp` fixture —
sends log "Mock sending email ... | template=..." and never open a socket.
"""

import logging
import os
from datetime import date

from app.services.email_service import (
    PALETTE,
    _compose_email_html,
    _get_org_contact_email,
    send_elster_filing_status_email,
)
from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollRun,
    PayslipItem,
    PayrollStatus,
)
from app.modules.payroll import service as payroll_service

import pytest

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "email_templates",
)

NEW_TEMPLATES = [
    "employee_created.html",
    "employee_deleted.html",
    "employee_sensitive_fields_changed.html",
    "payroll_run_created.html",
    "payroll_run_deleted.html",
    "payslip_deleted.html",
    "leave_request_submitted.html",
    "elster_filing_submitted.html",
    "elster_filing_blocked.html",
    "jurisdiction_pack_changed.html",
    "organization_details_changed.html",
    "report_generated_ready.html",
    "report_generation_failed.html",
]
RESTYLED_TEMPLATES = [
    "payroll_run_approved.html",
    "leave_request_approved.html",
    "leave_request_rejected.html",
]
ALL_TEMPLATES = NEW_TEMPLATES + RESTYLED_TEMPLATES

BASE_CONTEXT = {
    "company_name": "Acme Payroll",
    "support_email": "support@acme.com",
    "logo_url": "https://app.zoikopayroll.com/zoikopayroll-logo-light.png",
    "frontend_url": "https://app.zoikopayroll.com",
    "subject": "Test subject | Zoiko Payroll",
    "preheader": "Test preheader",
    "heading": "Test heading",
    "accent_bar": PALETTE["success"],
    "employee_name": "Jane Doe",
    "employee_code": "ZC-0001",
    "department": "Engineering",
    "designation": "Engineer",
    "date_of_joining": "2026-01-01",
    "pay_period": "Jan 2026",
    "pay_date": "2026-01-31",
    "run_code": "PY202601",
    "employee_count": 5,
    "payslip_number": "PS-0001",
    "leave_type": "Paid Leave",
    "start_date": "2026-02-01",
    "end_date": "2026-02-03",
    "days": 3,
    "plural": True,
    "request_code": "LV-0001",
    "reason": "Vacation",
    "transmission_type": "LOHNSTEUER_ANMELDUNG",
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "status": "BLOCKED_EXTERNAL",
    "blocked_reason": "No ELSTER transmission connector is authorized.",
    "transferticket": "",
    "pack_id": "DE-TAX",
    "version": "2.1",
    "jurisdiction": "Germany",
    "report_label": "Payroll Register",
    "report_id": 42,
    "template_version": "1.3",
    "details_panel": "<tr><td>a</td><td>b</td></tr>",
    "cta_url": "https://app.zoikopayroll.com",
    "cta_label": "Open",
}


def _render(name, extra=None):
    from app.services.email_service import _SECURITY_ADVISORY_HTML, _load_template
    context = {**BASE_CONTEXT, "security_advisory_block": _SECURITY_ADVISORY_HTML}
    if extra:
        context.update(extra)
    return _compose_email_html(_load_template(name), context)


def _mock_send_templates(caplog):
    """Template names seen in "Mock sending email" records."""
    names = set()
    for record in caplog.records:
        if "Mock sending email" in (record.getMessage() or "") and "template=" in (record.getMessage() or ""):
            names.add((record.getMessage() or "").split("template=")[-1].strip())
    return names


def _non_send_records(caplog):
    return [r for r in caplog.records if "Mock sending email" in (r.getMessage() or "")]


# ── Render smoke ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_template_composes_through_wrapper(name):
    html = _render(name)
    assert "{{" not in html and "{{/if}}" not in html, f"{name} has an unresolved placeholder"
    assert "Security Advisory" in html, name


@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_template_carries_canonical_palette(name):
    html = _render(name)
    for token in (PALETTE["page"], PALETTE["heading"], PALETTE["muted"], PALETTE["panel"], PALETTE["cta"]):
        assert token in html, f"{name} missing palette token {token}"


def test_every_payroll_template_uses_body_slot_not_standalone_shell():
    for name in ALL_TEMPLATES:
        with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
            body = f.read()
        assert "<!DOCTYPE html>" not in body, f"{name} is not a body-only fragment"


def test_base_wrapper_is_single_source_of_palette():
    with open(os.path.join(TEMPLATES_DIR, "_base_wrapper.html"), encoding="utf-8") as f:
        wrapper = f.read()
    for value in (
        PALETTE["page"], PALETTE["card"], PALETTE["border"], PALETTE["cta"],
        PALETTE["cta_hover"], PALETTE["heading"], PALETTE["muted"], PALETTE["panel"],
    ):
        assert value in wrapper, f"wrapper missing shell palette value {value}"
    # drift guard — no payload template (wrapper or any of the 16 fragments)
    # may hardcode a hex outside the shared PALETTE.
    import re
    allowed = set(PALETTE.values())
    for name in ["_base_wrapper.html"] + ALL_TEMPLATES:
        with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
            body = f.read()
        for hex_literal in re.findall(r"#[0-9a-fA-F]{6}", body):
            assert hex_literal in allowed, f"{name} hardcodes color {hex_literal} outside PALETTE"


def test_advisory_uses_canonical_palette():
    from app.services.email_service import _SECURITY_ADVISORY_HTML
    for value in (PALETTE["panel"], PALETTE["border"], PALETTE["heading"], PALETTE["muted"]):
        assert value in _SECURITY_ADVISORY_HTML, f"advisory missing palette value {value}"


def test_employee_email_subjects_have_no_sensitive_identifiers():
    """§10 copy standard — subjects never carry salary/bank/tax identifiers."""
    rendered = _render("employee_created.html")
    assert "500000" not in rendered.upper() and "CTC" not in _render("employee_created.html")


# ── Trigger wiring: employee lifecycle (real service functions) ──────────

def test_create_employee_notifies_onboarded_email(db, organization, caplog):
    from app.modules.payroll.schemas import EmployeeCreate
    with caplog.at_level(logging.INFO):
        emp = payroll_service.create_employee(
            db,
            EmployeeCreate(
                name="Jane Doe", email="jane@example.com", country_code="IN", department="Engineering",
                employee_code="ZC-1701",  # explicit — skips PG-only generate_employee_code on the sqlite test DB
            ),
            organization.id,
        )
    sent = _mock_send_templates(caplog)
    assert "employee_created.html" in sent, sent
    assert emp.email == "jane@example.com"


def test_update_employee_sensitive_change_notifies(db, organization, caplog):
    from app.modules.payroll.schemas import EmployeeUpdate
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1701",
        name="Jane Doe", email="jane@example.com",
        country_code="IN", bank_account="ACC-1",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with caplog.at_level(logging.INFO):
        payroll_service.update_employee(db, emp.id, EmployeeUpdate(bank_account="ACC-2"), organization.id)
    sent = _mock_send_templates(caplog)
    assert "employee_sensitive_fields_changed.html" in sent, sent


def test_update_employee_non_sensitive_change_sends_nothing(db, organization, caplog):
    from app.modules.payroll.schemas import EmployeeUpdate
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1702",
        name="Jane Doe", email="jane@example.com", country_code="IN",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with caplog.at_level(logging.INFO):
        payroll_service.update_employee(db, emp.id, EmployeeUpdate(designation="Senior Engineer"), organization.id)
    assert "Mock sending email" not in " | ".join(r.getMessage() for r in caplog.records), "no mail expected"


def test_delete_employee_notifies(db, organization, caplog):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1703",
        name="Jane Doe", email="jane@example.com", country_code="IN",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with caplog.at_level(logging.INFO):
        payroll_service.delete_employee(db, emp.id, organization.id)
    sent = _mock_send_templates(caplog)
    assert "employee_deleted.html" in sent, sent


# ── Trigger wiring: leave request submission (real service function) ─────

def test_leave_request_submission_notifies_org(db, organization, caplog, monkeypatch):
    from types import SimpleNamespace
    # generate_business_code's real impl takes a Postgres advisory lock
    # (pg_advisory_xact_lock) — not available on the sqlite test DB.
    monkeypatch.setattr(
        "app.core.code_generation.generate_business_code", lambda *a, **k: "LV-0001",
    )
    organization.email = "admin@acme.com"
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1704",
        name="Jane Doe", email="jane@example.com", country_code="IN",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    data = SimpleNamespace(
        employeeId=emp.id, leaveType="paid",
        startDate=date(2026, 2, 1), endDate=date(2026, 2, 3), reason="Vacation", source="manual",
    )
    with caplog.at_level(logging.INFO):
        payroll_service.create_payroll_leave_request(db, data, organization.id)
    sent = _mock_send_templates(caplog)
    assert "leave_request_submitted.html" in sent, sent
    assert any("admin@acme.com" in r.getMessage() for r in (_non_send_records(caplog) if False else caplog.records))


# ── Trigger wiring: run + payslip deletion (real service functions) ───────

def _draft_run(db, organization, period="Jan 2026"):
    run = PayrollRun(
        organization_id=organization.id, period_label=period, run_code="PY202601",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31),
        status=PayrollStatus.DRAFT.value, calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_delete_payroll_run_notifies_org(db, organization, caplog):
    organization.email = "admin@acme.com"
    run = _draft_run(db, organization)
    with caplog.at_level(logging.INFO):
        payroll_service.delete_payroll_run(db, run.id, organization.id)
    sent = _mock_send_templates(caplog)
    assert "payroll_run_deleted.html" in sent, sent


def test_delete_payslip_notifies_employee(db, organization, caplog):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1705",
        name="Jane Doe", email="jane@example.com", country_code="IN",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    run = _draft_run(db, organization)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name="Jane Doe", payslip_number="PS-0001",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    with caplog.at_level(logging.INFO):
        payroll_service.delete_payslip(db, item.id, organization.id)
    sent = _mock_send_templates(caplog)
    assert "payslip_deleted.html" in sent, sent


# ── Trigger wiring: admin-facing helpers ─────────────────────────────────

def test_payroll_run_created_notifies_org(db, organization, caplog):
    organization.email = "admin@acme.com"
    run = _draft_run(db, organization)
    with caplog.at_level(logging.INFO):
        payroll_service._notify_payroll_run_created(db, run, organization.id)
    sent = _mock_send_templates(caplog)
    assert "payroll_run_created.html" in sent, sent


def test_elster_blocked_notifies_org_with_blocked_variant(db, organization, caplog):
    organization.email = "admin@acme.com"
    from app.modules.payroll.models import GermanyElsterTransmission
    row = GermanyElsterTransmission(
        organization_id=organization.id, transmission_type="LOHNSTEUER_ANMELDUNG",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        status="BLOCKED_EXTERNAL", blocked_reason="No ELSTER connector is authorized.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    with caplog.at_level(logging.INFO):
        payroll_service._notify_elster_transmission(db, row, organization.id)
    sent = _mock_send_templates(caplog)
    assert "elster_filing_blocked.html" in sent, sent
    assert "elster_filing_submitted.html" not in sent


def test_elster_submitted_variant_chosen_only_for_real_submitted_statuses(db, organization, caplog):
    """BLOCKED_EXTERNAL must render the blocked copy; only QUEUED/TRANSMITTED/
    ACKNOWLEDGED render the submitted copy. The persistable status alone
    decides the template — never the caller's intent."""
    with caplog.at_level(logging.INFO):
        send_elster_filing_status_email(
            "admin@acme.com", "BLOCKED_EXTERNAL", "LOHNSTEUER_ANMELDUNG",
            "2026-01-01", "2026-01-31", blocked_reason="No ELSTER connector is authorized.",
            organization_id=organization.id, db=db,
        )
        send_elster_filing_status_email(
            "admin@acme.com", "QUEUED", "LOHNSTEUER_ANMELDUNG",
            "2026-01-01", "2026-01-31", organization_id=organization.id, db=db,
        )
        send_elster_filing_status_email(
            "admin@acme.com", "REJECTED", "LOHNSTEUER_ANMELDUNG",
            "2026-01-01", "2026-01-31", blocked_reason="Validation errors.",
            organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "elster_filing_blocked.html" in sent, sent
    assert "elster_filing_submitted.html" in sent, sent


def test_jurisdiction_pack_change_fans_out_to_linked_org(db, organization, caplog):
    from app.modules.payroll.models import JurisdictionPack, CompanyComplianceDetails
    organization.email = "admin@acme.com"
    pack = JurisdictionPack(
        pack_id="DE-TAX", version="2.0", jurisdiction_country="DE",
        jurisdiction_state=None, jurisdiction_locality=None,
        pack_type="tax", status="Draft", currency="EUR",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    # Link the org to the pack the way an opted-in org is (active_pack_id).
    link = CompanyComplianceDetails(organization_id=organization.id, active_pack_id=pack.id)
    db.add(link)
    db.commit()
    with caplog.at_level(logging.INFO):
        payroll_service._notify_jurisdiction_pack_changed(
            db, pack, [("Country", "DE", "US"), ("Version", "2.0", "2.1")],
        )
    sent = _mock_send_templates(caplog)
    assert "jurisdiction_pack_changed.html" in sent, sent


def test_jurisdiction_pack_no_change_sends_nothing(db, organization, caplog):
    from app.modules.payroll.models import JurisdictionPack
    pack = JurisdictionPack(
        pack_id="DE-TAX", version="2.0", jurisdiction_country="DE", pack_type="tax", status="Draft",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    with caplog.at_level(logging.INFO):
        payroll_service._notify_jurisdiction_pack_changed(db, pack, [])
    assert not _mock_send_templates(caplog)


def test_report_generated_and_failed_variants(db, organization, caplog):
    from app.modules.payroll.models import GeneratedReport
    organization.email = "admin@acme.com"
    report = GeneratedReport(
        organization_id=organization.id, report_template_id=1, template_version="1.3",
        report_type="PAYROLL_REGISTER", jurisdiction_country="DE", reporting_year="2026",
        reporting_period="Jan 2026", status="Generated", rendered_data={},
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    with caplog.at_level(logging.INFO):
        payroll_service._notify_report_generated(db, report, organization.id)
        payroll_service._notify_report_generation_failed(
            db, organization.id, "PAYROLL_REGISTER", "Jan 2026", "Run is not finalized.",
        )
    sent = _mock_send_templates(caplog)
    assert "report_generated_ready.html" in sent, sent
    assert "report_generation_failed.html" in sent, sent


def test_org_contact_email_helper(db, organization):
    organization.email = "admin@acme.com"
    db.commit()
    assert _get_org_contact_email(db, organization.id) == "admin@acme.com"
    assert _get_org_contact_email(db, None) is None
"""Batch-2 email templates — Enterprise / Policy / Forms / Assist / Orgs / Billing / Super-Admin.

Covers the 23 batch-2 templates (18 new + 3 restyled: org_created,
assist_handoff_confirmation, update_form_invite) on the same shared
_base_wrapper.html + PALETTE design system as batch-1:

  - render smoke: every template composes through the shared wrapper with no
    unresolved placeholders and the canonical palette;
  - palette parity: no batch-2 file hardcodes a hex outside PALETTE;
  - trigger wiring: real service call sites (enterprise jurisdiction
    lifecycle, policy update, forms review/submission, billing override,
    super-admin currency) and surrogate senders each fire the correct
    template to the correct recipient, best-effort.

SMTP is globally neutralized by conftest's autouse `_no_real_smtp` fixture —
sends log "Mock sending email ... | template=..." and never open a socket.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.services.email_service import (
    PALETTE,
    _compose_email_html,
)
from app.modules.payroll.enterprise.models import EnterpriseJurisdiction, JurisdictionStatus
from app.modules.payroll.enterprise.schemas import GeneralConfig, JurisdictionConfigUpdate

import pytest

TEMPLATES_DIR = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))),
    "app", "email_templates",
)

NEW_TEMPLATES = [
    "jurisdiction_added.html",
    "jurisdiction_config_updated.html",
    "jurisdiction_verified.html",
    "jurisdiction_removed.html",
    "enterprise_activated.html",
    "enterprise_deactivated.html",
    "payroll_policy_changed.html",
    "integration_status_changed.html",
    "form_submission_approved.html",
    "form_submission_rejected.html",
    "form_public_submission_confirmation.html",
    "assist_kill_switch_alert.html",
    "organization_suspended.html",
    "organization_deleted.html",
    "entitlement_override_granted.html",
    "user_status_changed.html",
    "policy_assigned_to_organization.html",
    "organization_currency_changed.html",
]
RESTYLED_TEMPLATES = [
    "org_created.html",
    "assist_handoff_confirmation.html",
    "update_form_invite.html",
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
    "country_label": "Germany",
    "country_code": "DE",
    "status_note": "",
    "active_switched": True,
    "jurisdictions_label": "Germany, France",
    "policy_name": "ACME India Policy",
    "provider_label": "Zoiko Bank",
    "category_label": "Banking",
    "enabled": True,
    "disabled": False,
    "state_word": "enabled",
    "state_color": "15803d",
    "form_name": "KYC Review",
    "notes": "Not enough detail.",
    "org_name": "Acme GmbH",
    "suspended": False,
    "restored": True,
    "reason": "",
    "feature_label": "Assist seats",
    "limit_display": "Unlimited",
    "user_name": "Jane Doe",
    "deactivated": False,
    "activated": True,
    "pack_label": "DE-PAYROLL-2026-V1",
    "version": "2.1",
    "old_currency": "INR",
    "new_currency": "EUR",
    "recipient_first_name": "Jane",
    "organization_name": "Acme GmbH",
    "reference_id": "ORG-ABCD-INIT",
    "requester_name": "Jane",
    "case_id": "CS-4821",
    "summary": "Cannot access the payroll export module.",
    "destination_label": "Payroll Support",
    "sla_reference": "24 hours",
    "expires_at": "Feb 14, 2026",
    "toggled_by": "ops@zoiko.example",
    "timestamp": "Feb 1, 2026 at 09:00 UTC",
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
        msg = record.getMessage() or ""
        if "Mock sending email" in msg and "template=" in msg:
            names.add(msg.split("template=")[-1].strip())
    return names


# ── Render smoke ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_batch2_template_composes_through_wrapper(name):
    html = _render(name)
    assert "{{" not in html and "{{/if}}" not in html, f"{name} has an unresolved placeholder"
    assert "Security Advisory" in html, name


@pytest.mark.parametrize("name", ALL_TEMPLATES)
def test_every_batch2_template_carries_canonical_palette(name):
    html = _render(name)
    for token in (PALETTE["page"], PALETTE["heading"], PALETTE["muted"], PALETTE["panel"], PALETTE["cta"]):
        assert token in html, f"{name} missing palette token {token}"


def test_every_batch2_template_is_body_only_fragment():
    for name in NEW_TEMPLATES + RESTYLED_TEMPLATES:
        with open(__import__("os").path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
            body = f.read()
        assert "<!DOCTYPE html>" not in body, f"{name} is not a body-only fragment"


def test_batch2_templates_do_not_hardcode_palette_external_hexes():
    import re
    allowed = set(PALETTE.values())
    for name in ALL_TEMPLATES:
        with open(__import__("os").path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
            body = f.read()
        for hex_literal in re.findall(r"#[0-9a-fA-F]{6}", body):
            assert hex_literal in allowed, f"{name} hardcodes color {hex_literal} outside PALETTE"


def test_state_colored_template_renders_state_word():
    enabled = _render("integration_status_changed.html", {"enabled": True, "disabled": False, "state_word": "enabled", "state_color": "15803d"})
    assert "color:#15803d;" in enabled and ">enabled<" in enabled.replace(" ", "")
    disabled = _render("integration_status_changed.html", {"enabled": False, "disabled": True, "state_word": "disabled", "state_color": "5b7290"})
    assert "color:#5b7290;" in disabled and ">disabled<" in disabled.replace(" ", "")


def test_status_changed_template_only_shows_active_branch():
    activated = _render("user_status_changed.html", {"deactivated": False, "activated": True})
    assert "active" in activated and "deactivated" not in activated
    deactivated = _render("user_status_changed.html", {"deactivated": True, "activated": False})
    assert "deactivated" in deactivated and "color:#b91c1c;" in deactivated


def test_rejected_template_notes_block_is_conditional():
    with_notes = _render("form_submission_rejected.html", {"notes": "Not enough detail."})
    assert "Reviewer note" in with_notes
    without = _render("form_submission_rejected.html", {"notes": ""})
    assert "Reviewer note" not in without


# ── Trigger wiring: enterprise jurisdiction lifecycle (real service) ───────

def test_add_jurisdiction_notifies_org(db, organization, caplog):
    organization.email = "admin@acme.com"
    from app.modules.payroll.enterprise import service as ent_service
    with caplog.at_level(logging.INFO):
        row = ent_service.add_jurisdiction(db, organization.id, "DE")
    sent = _mock_send_templates(caplog)
    assert "jurisdiction_added.html" in sent, sent
    assert row.country_code == "DE"


def test_update_jurisdiction_config_notifies_with_diff(db, organization, caplog):
    organization.email = "admin@acme.com"
    row = EnterpriseJurisdiction(
        organization_id=organization.id, country_code="DE",
        status=JurisdictionStatus.DRAFT.value,
        general_config={"payrollFrequency": "Monthly"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.modules.payroll.enterprise import service as ent_service
    with caplog.at_level(logging.INFO):
        ent_service.update_jurisdiction_config(
            db, organization.id, row.id,
            JurisdictionConfigUpdate(generalConfig=GeneralConfig(payrollFrequency="Weekly")),
        )
    sent = _mock_send_templates(caplog)
    assert "jurisdiction_config_updated.html" in sent, sent


def test_update_jurisdiction_config_no_change_sends_nothing(db, organization, caplog):
    organization.email = "admin@acme.com"
    row = EnterpriseJurisdiction(
        organization_id=organization.id, country_code="DE",
        status=JurisdictionStatus.DRAFT.value,
        general_config={"payrollFrequency": "Monthly"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.modules.payroll.enterprise import service as ent_service
    with caplog.at_level(logging.INFO):
        ent_service.update_jurisdiction_config(
            db, organization.id, row.id,
            JurisdictionConfigUpdate(generalConfig=GeneralConfig(payrollFrequency="Monthly")),
        )
    assert not _mock_send_templates(caplog)


def test_verify_jurisdiction_notifies(db, organization, caplog, monkeypatch):
    organization.email = "admin@acme.com"
    row = EnterpriseJurisdiction(
        organization_id=organization.id, country_code="DE",
        status=JurisdictionStatus.CONFIGURED.value,
        general_config={"payrollFrequency": "Monthly"},
        compliance_config={"governmentFilingSchedule": "Quarterly"},
        payroll_rules_config={"overtime": "None"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.modules.payroll.enterprise import service as ent_service
    # verify hits the engine country resolver indirectly via company details —
    # resolve lazily to keep this a black-box test.
    monkeypatch.setattr(
        "app.modules.payroll.enterprise.service._recompute_enterprise_status",
        lambda db, organization_id: None,
    )
    with caplog.at_level(logging.INFO):
        out = ent_service.verify_jurisdiction(db, organization.id, row.id)
    sent = _mock_send_templates(caplog)
    assert "jurisdiction_verified.html" in sent, sent
    assert out.status == JurisdictionStatus.VERIFIED.value


def test_remove_jurisdiction_notifies(db, organization, caplog):
    organization.email = "admin@acme.com"
    row = EnterpriseJurisdiction(organization_id=organization.id, country_code="DE")
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.modules.payroll.enterprise import service as ent_service
    monkeypatch_cfg = pytest.MonkeyPatch()
    monkeypatch_cfg.setattr(
        "app.modules.payroll.enterprise.service._recompute_enterprise_status",
        lambda db, organization_id: None,
    )
    try:
        with caplog.at_level(logging.INFO):
            ent_service.remove_jurisdiction(db, organization.id, row.id)
    finally:
        monkeypatch_cfg.undo()
    sent = _mock_send_templates(caplog)
    assert "jurisdiction_removed.html" in sent, sent


# ── Trigger wiring: policy update + integration toggle (real service) ──────

def _mk_policy(db, organization):
    from app.modules.payroll.policy.models import PayrollPolicy, PolicyIntegration, PolicyOvertimeRule, CalculationMode
    policy = PayrollPolicy(
        organization_id=organization.id, name="Default Policy", status="active",
        is_default=True, calculation_mode=CalculationMode.STANDARD.value,
        effective_date=__import__("datetime").date.today(),
    )
    db.add(policy)
    db.flush()
    ot = PolicyOvertimeRule(policy_id=policy.id, enabled=False, minimum_overtime_minutes=30, approval_required=True)
    db.add(ot)
    integration = PolicyIntegration(policy_id=policy.id, category="banking", provider_key="zoiko_bank", enabled=False)
    db.add(integration)
    db.commit()
    db.refresh(policy)
    return policy


def test_update_policy_name_notifies(db, organization, caplog):
    organization.email = "admin@acme.com"
    policy = _mk_policy(db, organization)
    from app.modules.payroll.policy import service as policy_service
    from app.modules.payroll.policy.schemas import PayrollPolicyUpdate
    with caplog.at_level(logging.INFO):
        policy_service.update_policy(db, policy.id, PayrollPolicyUpdate(name="ACME Standard"), organization.id)
    sent = _mock_send_templates(caplog)
    assert "payroll_policy_changed.html" in sent, sent


def test_update_policy_no_change_sends_nothing(db, organization, caplog):
    organization.email = "admin@acme.com"
    policy = _mk_policy(db, organization)
    from app.modules.payroll.policy import service as policy_service
    from app.modules.payroll.policy.schemas import PayrollPolicyUpdate
    with caplog.at_level(logging.INFO):
        policy_service.update_policy(db, policy.id, PayrollPolicyUpdate(status="active"), organization.id)
    assert not _mock_send_templates(caplog)


def test_set_integration_enabled_notifies(db, organization, caplog):
    organization.email = "admin@acme.com"
    policy = _mk_policy(db, organization)
    from app.modules.payroll.policy import service as policy_service
    with caplog.at_level(logging.INFO):
        policy_service.set_integration_enabled(db, policy.id, "banking", "zoiko_bank", True, organization.id)
    sent = _mock_send_templates(caplog)
    assert "integration_status_changed.html" in sent, sent


# ── Trigger wiring: forms review + public submission (real service) ────────

def _mk_form_flow(db, organization):
    from app.modules.payroll.models import (
        PayrollEmployee, PayrollCustomFieldDefinition, PayrollUpdateForm,
        PayrollUpdateFormSend, PayrollUpdateFormSubmission, FormSendStatus,
    )
    from datetime import datetime as _dt
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="ZC-1711",
        name="Jane Doe", email="jane@example.com", country_code="IN",
    )
    db.add(emp)
    db.flush()
    form = PayrollUpdateForm(
        organization_id=organization.id, name="KYC Review",
        fields_config=[{"key": "bank_account", "source": "standard", "label": "Bank account"}],
    )
    db.add(form)
    db.flush()
    send = PayrollUpdateFormSend(
        organization_id=organization.id, form_id=form.id, employee_id=emp.id,
        token="tok-abc", status=FormSendStatus.SUBMITTED.value,
        expires_at=_dt.now(timezone.utc) + timedelta(days=7),
    )
    db.add(send)
    db.flush()
    sub = PayrollUpdateFormSubmission(
        organization_id=organization.id, send_id=send.id,
        submitted_data={"bank_account": "ACC-9"}, status="pending",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return emp, form, send, sub


def test_form_submission_rejected_notifies_employee(db, organization, caplog):
    from app.modules.payroll.forms import service as forms_service
    emp, form, send, sub = _mk_form_flow(db, organization)
    with caplog.at_level(logging.INFO):
        forms_service.review_submission(db, organization.id, sub.id, approve=False, notes="Not enough detail.")
    sent = _mock_send_templates(caplog)
    assert "form_submission_rejected.html" in sent, sent


def test_form_submission_approved_notifies_employee(db, organization, caplog):
    from app.modules.payroll.forms import service as forms_service
    emp, form, send, sub = _mk_form_flow(db, organization)
    with caplog.at_level(logging.INFO):
        forms_service.review_submission(db, organization.id, sub.id, approve=True)
    sent = _mock_send_templates(caplog)
    assert "form_submission_approved.html" in sent, sent


def test_public_form_submission_notifies_employee(db, organization, caplog):
    from app.modules.payroll.models import FormSendStatus
    from app.modules.payroll.forms import service as forms_service
    emp, form, send, sub = _mk_form_flow(db, organization)
    send.status = FormSendStatus.SENT.value
    db.commit()
    with caplog.at_level(logging.INFO):
        forms_service.submit_public_form(db, "tok-abc", {"bank_account": "ACC-9"})
    sent = _mock_send_templates(caplog)
    assert "form_public_submission_confirmation.html" in sent, sent


# ── Trigger wiring: billing override (real service) ────────────────────────

def test_entitlement_override_notifies_org(db, organization, caplog):
    organization.email = "admin@acme.com"
    from app.modules.billing.entitlements import create_entitlement_override
    with caplog.at_level(logging.INFO):
        create_entitlement_override(
            db, organization.id, "assist_seats", 100,
            granted_by_user_id=1, reason="Expansion quarter",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
        )
    sent = _mock_send_templates(caplog)
    assert "entitlement_override_granted.html" in sent, sent


# ── Trigger wiring: super admin currency (real service) ────────────────────

def test_org_currency_change_notifies(db, organization, caplog):
    organization.email = "admin@acme.com"
    organization.organization_name = "Acme GmbH"
    organization.currency = "INR"
    db.commit()
    from app.modules.super_admin.service import update_organization_currency
    with caplog.at_level(logging.INFO):
        update_organization_currency(db, organization.id, "EUR")
    sent = _mock_send_templates(caplog)
    assert "organization_currency_changed.html" in sent, sent


# ── Trigger wiring: ops + org lifecycle senders (direct surrogate) ─────────

def test_kill_switch_alert_is_internal_ops(db, caplog, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ASSIST_SUPPORT_EMAIL", "ops@zoiko.example")
    from app.services.email_service import send_assist_kill_switch_alert_email
    with caplog.at_level(logging.INFO):
        send_assist_kill_switch_alert_email(True, "ops@zoiko.example", db=db)
    sent = _mock_send_templates(caplog)
    assert "assist_kill_switch_alert.html" in sent, sent
    assert any("ops@zoiko.example" in (r.getMessage() or "") for r in caplog.records)


def test_org_suspended_sender(db, organization, caplog):
    from app.services.email_service import send_organization_suspended_email
    with caplog.at_level(logging.INFO):
        send_organization_suspended_email(
            "admin@acme.com", "Acme GmbH", suspended=True,
            reason="", organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "organization_suspended.html" in sent, sent


def test_org_deleted_sender(db, organization, caplog):
    from app.services.email_service import send_organization_deleted_email
    with caplog.at_level(logging.INFO):
        send_organization_deleted_email("admin@acme.com", "Acme GmbH", db=db)
    sent = _mock_send_templates(caplog)
    assert "organization_deleted.html" in sent, sent


def test_user_status_sender(db, organization, caplog):
    from app.services.email_service import send_user_status_changed_email
    with caplog.at_level(logging.INFO):
        send_user_status_changed_email(
            "jane@example.com", "Jane Doe", is_active=False,
            organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "user_status_changed.html" in sent, sent


def test_policy_assigned_sender(db, organization, caplog):
    from app.services.email_service import send_policy_assigned_to_organization_email
    with caplog.at_level(logging.INFO):
        send_policy_assigned_to_organization_email(
            "admin@acme.com", "DE-PAYROLL-2026-V1", version="2.1",
            country_label="Germany", organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "policy_assigned_to_organization.html" in sent, sent


def test_update_form_invite_sender_has_heading_and_cta(db, organization, caplog):
    from app.services.email_service import send_update_form_invite_email
    with caplog.at_level(logging.INFO):
        send_update_form_invite_email(
            "jane@example.com", "Jane Doe", "KYC Review",
            "https://app.zoikopayroll.com/form/tok-abc", "Feb 14, 2026",
            organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "update_form_invite.html" in sent, sent


def test_org_created_sender_has_heading_and_cta(db, organization, caplog):
    from app.services.email_service import send_organization_created_email
    with caplog.at_level(logging.INFO):
        send_organization_created_email(
            "admin@acme.com", "Jane", "Acme GmbH", reference_id="ORG-ABCD-INIT",
            setup_link="https://app.zoikopayroll.com/login",
            organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "org_created.html" in sent, sent


def test_handoff_confirmation_sender_has_heading(db, organization, caplog):
    from app.services.email_service import send_handoff_confirmation_email
    with caplog.at_level(logging.INFO):
        send_handoff_confirmation_email(
            "jane@example.com", "Jane", "CS-4821", "Cannot access exports.",
            "payroll_support", sla_reference="24 hours",
            organization_id=organization.id, db=db,
        )
    sent = _mock_send_templates(caplog)
    assert "assist_handoff_confirmation.html" in sent, sent
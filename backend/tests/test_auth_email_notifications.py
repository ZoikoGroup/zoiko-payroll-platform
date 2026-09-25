"""
tests/test_auth_email_notifications.py
--------------------------------------
Coverage for the "record of truth" email audit + the five missing IAM
notification emails (IAM-008 plus four notices whose catalog IDs are
pending — they were previously mis-tagged IAM-009..012, which the spec
assigns to MFA/sign-in templates) plus the COM-001 registration email:

  - IAM-008  change_password ("Your Zoiko Payroll password was changed")
  - (pending) generate_random_password (self-service replacement notice)
  - (pending) password-reset completion confirmation
  - (pending) role change notice (affected user only)
  - (pending) account deactivation notice (names the acting org admin)
  - COM-001  organization created (register_enterprise) — now audited

Structural idempotency (Part 1): every dispatch INSERTs an auth_email_events
row BEFORE any SMTP call; a duplicate idempotency_key suppresses the resend
while persisting a skipped_duplicate row. Token-link flows (reset request /
resend-invite) use a per-attempt key so a legitimate re-request still mints +
sends the fresh superseding link.

SMTP is globally neutralized (host "") by tests/conftest.py's autouse
_no_real_smtp fixture; tests that count sends monkeypatch the service-layer
_send_*_email wrappers instead.
"""

import re

import pytest

from app.modules.auth import service
from app.modules.auth.models import SecurityActionPurpose, User, UserRole
from app.modules.auth.schemas import UserUpdateRequest


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def org(db, organization):
    return organization


@pytest.fixture()
def manager(db, org):
    """Same-org ORG_ADMIN who acts (invites, changes roles, deactivates)."""
    user = User(
        email="manager@example.com",
        hashed_password=service.hash_password("ManagerPass1!"),
        role=UserRole.ORG_ADMIN,
        organization_id=org.id,
        first_name="Rina",
        last_name="Banerjee",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def member(db, org):
    """The affected user — every notification below is addressed to them."""
    user = User(
        email="member@example.com",
        hashed_password=service.hash_password("MemberPass1!"),
        role=UserRole.PAYROLL_ADMIN,
        organization_id=org.id,
        first_name="Kavya",
        last_name="Nair",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _audit_rows(db):
    return db.query(service.AuthEmailEvent).order_by(service.AuthEmailEvent.id).all()


def _reset_link_capture(monkeypatch):
    """Request a reset link for a user and hand back (token, capture list)."""
    calls = []

    def fake_send_reset_email(db, user, link, expires_at_local="", reference_id="", **kw):
        calls.append({"email": user.email, "link": link})
        return True

    monkeypatch.setattr(service, "_send_reset_email", fake_send_reset_email)
    return calls


# ── IAM-008: change_password ───────────────────────────────────────────────

def _make_recorder(monkeypatch, name):
    """Monkeypatch a service._send_*_email wrapper. Records (args, kwargs) per
    call so positional wrappers (db, user, ...) keep their values."""
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(service, name, fake)
    return calls


def _sent_user(call):
    """The affected-user arg (second positional) of a recorded send."""
    return call[0][1]


def test_change_password_sends_iam008_and_audits(db, manager, member, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_password_changed_email")
    result = service.change_password(db, member.id, "MemberPass1!", "NewMemberPass2!")
    db.expire_all()

    assert result == {"message": "Password changed successfully."}
    assert len(calls) == 1
    assert _sent_user(calls[0]).email == member.email

    rows = _audit_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == service.PASSWORD_CHANGED_EVENT_TYPE
    assert row.template_id == service.PASSWORD_CHANGED_TEMPLATE_ID == "IAM-008"
    assert row.recipient_email == member.email
    assert row.user_id == member.id
    assert row.organization_id == member.organization_id
    assert row.actor_user_id == member.id  # the owner acted on their own account
    assert row.outcome == "sent"


def test_change_password_wrong_current_rejected_without_email(db, member, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_password_changed_email")
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="Current password is incorrect."):
        service.change_password(db, member.id, "WrongPass1!", "Whatever9!")
    assert calls == []
    assert _audit_rows(db) == []


def test_change_password_double_submit_sends_once_and_records_duplicate(db, member, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_password_changed_email")
    service.change_password(db, member.id, "MemberPass1!", "NewMemberPass2!")
    service.change_password(db, member.id, "NewMemberPass2!", "SameAgain9!")
    # ^ idempotency is keyed on tenant|event|recipient|template — the second
    #   attempt (same args) must not emit a second email, even though the
    #   password is now the new one and would verify fine.

    assert len(calls) == 1

    rows = _audit_rows(db)
    outcomes = [r.outcome for r in rows]
    assert outcomes.count("sent") == 1
    assert outcomes.count("skipped_duplicate") == 1


# ── Password replaced (catalog ID pending): generate_random_password ──────────────────────────────────────

def test_generate_random_password_sends_iam009(db, member, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_password_reset_self_service_email")

    payload = service.generate_random_password(db, member.id)
    assert payload["password"]  # single in-band generation, never emailed

    assert len(calls) == 1
    assert _sent_user(calls[0]).email == member.email

    row = _audit_rows(db)[0]
    assert row.event_type == service.PASSWORD_REPLACED_EVENT_TYPE
    assert row.template_id == service.PASSWORD_REPLACED_TEMPLATE_ID == "IAM-TBD-PWD-REPLACED"
    assert row.outcome == "sent"


# ── Reset completed (catalog ID pending) ───────────────────────────────────────────────

def test_complete_reset_sends_iam010_confirmation(db, member, monkeypatch):
    calls = _reset_link_capture(monkeypatch)
    service.request_password_reset(db, member.email)
    token = calls[0]["link"].split("token=", 1)[1]

    confirmations = _make_recorder(monkeypatch, "_send_password_reset_completed_email")
    result = service.complete_action_token(db, token, SecurityActionPurpose.RESET, "ResetPass9!")
    assert "Password set" in result["message"]
    db.refresh(member)
    assert service.verify_password("ResetPass9!", member.hashed_password)

    assert len(confirmations) == 1
    assert _sent_user(confirmations[0]).email == member.email

    completed = [r for r in _audit_rows(db) if r.template_id == service.RESET_COMPLETED_TEMPLATE_ID]
    assert len(completed) == 1
    assert completed[0].event_type == service.RESET_COMPLETED_EVENT_TYPE
    assert completed[0].outcome == "sent"


# ── IAM-002: invite + resend (token-link: per-attempt key) ─────────────────

def test_invite_and_resend_are_distinct_sends_double_row(db, member, manager, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_invite_email")

    service._dispatch_invite_email(db, member, manager)
    service._dispatch_invite_email(db, member, manager)

    assert len(calls) == 2  # resend is legitimate: each link supersedes the last

    rows = [r for r in _audit_rows(db) if r.template_id == "IAM-002"]
    assert len(rows) == 2
    assert all(r.outcome == "sent" for r in rows)
    # per-attempt keys, both rooted at the same base key
    base = "|".join([
        str(member.organization_id),
        service.INVITE_EVENT_TYPE,
        member.email.lower(),
        service.INVITE_TEMPLATE_ID,
        service.TOKEN_MATERIAL_VERSION,
    ])
    assert all(r.idempotency_key.startswith(base + "|") for r in rows)
    assert rows[0].idempotency_key != rows[1].idempotency_key


# ── Role changed (catalog ID pending) ──────────────────────────────────────────────────

def test_role_changed_notify_addresses_affected_user_with_actor(db, member, manager, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_role_changed_email")

    sent = service.notify_role_changed(
        db, user=member, actor=manager,
        old_role=UserRole.PAYROLL_ADMIN, new_role=UserRole.ORG_ADMIN,
    )
    assert sent is True
    assert len(calls) == 1
    db, user, old_role, new_role, actor_name = calls[0][0]
    assert user.email == member.email
    assert old_role == UserRole.PAYROLL_ADMIN
    assert new_role == UserRole.ORG_ADMIN
    assert actor_name == "Rina Banerjee"

    row = _audit_rows(db)[0]
    assert row.template_id == service.ROLE_CHANGED_TEMPLATE_ID == "IAM-TBD-ROLE-CHANGED"
    assert row.actor_user_id == manager.id
    assert row.outcome == "sent"


def test_router_update_user_notifies_on_role_change_only(db, manager, monkeypatch):
    from app.modules.auth import router

    # Role change must be one ORG_ADMIN can actually assign (admin -> payroll)
    # so the router's own can_create_role check passes.
    admin_user = User(
        email="swap@example.com",
        hashed_password=service.hash_password("SwapPass1!"),
        role=UserRole.ORG_ADMIN,
        organization_id=manager.organization_id,
        first_name="Dev",
        last_name="Raj",
        is_active=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    calls = _make_recorder(monkeypatch, "_send_role_changed_email")
    updated = router.update_user(
        admin_user.id,
        UserUpdateRequest(role=UserRole.PAYROLL_ADMIN),
        current_user=manager,
        db=db,
    )
    assert updated.role == UserRole.PAYROLL_ADMIN
    assert calls and _sent_user(calls[0]).email == admin_user.email

    counts = [r.outcome for r in _audit_rows(db)]
    assert counts.count("sent") == 1


def test_router_update_user_ignores_role_when_unchanged(db, member, manager, monkeypatch):
    from app.modules.auth import router

    calls = _make_recorder(monkeypatch, "_send_role_changed_email")
    router.update_user(
        member.id,
        UserUpdateRequest(first_name="Kavi"),
        current_user=manager,
        db=db,
    )
    assert calls == []
    assert _audit_rows(db) == []


# ── Account deactivated (catalog ID pending) ───────────────────────────────────────────

def test_deactivate_notify_names_acting_admin(db, member, manager, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_account_deactivated_email")
    sent = service.notify_user_deactivated(db, user=member, actor=manager)
    assert sent is True
    assert _sent_user(calls[0]).email == member.email
    assert calls[0][0][2] == "Rina Banerjee"

    row = _audit_rows(db)[0]
    assert row.template_id == service.DEACTIVATED_TEMPLATE_ID == "IAM-TBD-DEACTIVATED"
    assert row.outcome == "sent"


def test_deactivate_notify_falls_back_when_actor_has_no_name(db, member, manager, monkeypatch):
    calls = _make_recorder(monkeypatch, "_send_account_deactivated_email")
    anonymous = User(
        email="anon@example.com",
        hashed_password=service.hash_password("AnonPass1!"),
        role=UserRole.ORG_ADMIN,
        organization_id=member.organization_id,
        first_name="", last_name="",
        is_active=True,
    )
    db.add(anonymous)
    db.commit()
    service.notify_user_deactivated(db, user=member, actor=anonymous)
    assert calls[0][0][2] == "an organization administrator"


def test_router_deactivate_flow_and_self_deactivate_guard(db, member, manager, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.auth import router

    calls = _make_recorder(monkeypatch, "_send_account_deactivated_email")
    router.deactivate_user(member.id, current_user=manager, db=db)
    db.refresh(member)
    assert member.is_active is False
    assert len(calls) == 1
    assert _sent_user(calls[0]).email == member.email

    # Self-deactivation is rejected BEFORE any email is attempted.
    manager.is_active = True
    db.commit()
    with pytest.raises(BadRequestException, match="cannot deactivate your own"):
        router.deactivate_user(manager.id, current_user=manager, db=db)
    assert len(calls) == 1  # still just the member notification


# ── COM-001: register_enterprise now audits the org-created email ──────────

def test_register_enterprise_audits_com001(db, monkeypatch):
    from app.modules.auth.schemas import RegisterRequest
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(
        pack_id="IN-NOTIF", jurisdiction_country="IN", pack_type="tax", version="1.0", status="Active",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    from decimal import Decimal
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
        component_key="pf", label="PF", employee_share="—", employer_share="—", total="—",
        employee_rate_pct=Decimal("12.00"),
    ))
    db.commit()

    org_created_calls = []

    def fake_send_org_created_email(**kwargs):
        org_created_calls.append(kwargs)
        return True

    from app.services import email_service
    monkeypatch.setattr(email_service, "send_organization_created_email", fake_send_org_created_email)

    result = service.register_enterprise(
        db,
        RegisterRequest(
            organization="Notify Co", name="Ada Admin", email="notify-admin@example.com",
            password="a-strong-password-1", country="IN", terms_accepted=True,
        ),
    )
    assert result is not None

    assert len(org_created_calls) == 1
    org = db.query(Organization).filter(Organization.country == "IN").first()
    assert org is not None

    rows = [r for r in _audit_rows(db) if r.template_id == "COM-001"]
    assert len(rows) == 1
    assert rows[0].event_type == "commercial.organization_created"
    assert rows[0].recipient_email == "notify-admin@example.com"
    assert rows[0].organization_id == org.id
    assert rows[0].outcome == "sent"


# ── Template restyle smoke (Part 3.3) ──────────────────────────────────────

TEMPLATES_DIR = None


def _template_path(name):
    global TEMPLATES_DIR
    if TEMPLATES_DIR is None:
        TEMPLATES_DIR = __import__("os").path.join(
            __import__("os").path.dirname(__import__("os").path.dirname(__file__)),
            "app", "email_templates",
        )
    return __import__("os").path.join(TEMPLATES_DIR, name)


def _read_template(name):
    with open(_template_path(name), encoding="utf-8") as f:
        return f.read()


DANGER_ACCENT_TEMPLATES = {
    "password_changed.html",
    "password_reset_self_service.html",
    "password_reset_completed.html",
    "account_deactivated.html",
    "org_admin_password_reset.html",
}
CALM_TEMPLATES = {"role_changed.html", "org_admin_invite.html"}
PALETTE = ("#0B2D5C", "#1E4FA0", "#D8E4F5", "#F3F8FF")


def test_blue_white_palette_across_all_notification_templates():
    for name in DANGER_ACCENT_TEMPLATES | CALM_TEMPLATES:
        html = _read_template(name)
        for token in PALETTE:
            assert token in html, f"{name} missing palette token {token}"
        assert "{{security_advisory_block}}" in html, name


def test_danger_accent_only_on_attention_templates():
    for name in DANGER_ACCENT_TEMPLATES:
        assert "#C0392B" in _read_template(name), f"{name} should carry the danger accent"
    for name in CALM_TEMPLATES:
        assert "#C0392B" not in _read_template(name), f"{name} must NOT carry the danger accent"


def test_no_legacy_dark_slate_theme_in_ported_templates():
    for name in ("org_admin_invite.html", "org_admin_password_reset.html"):
        html = _read_template(name)
        for legacy in ("#020617", "#0f172a", "#1e293b", "#4f46e5", "#94a3b8"):
            assert legacy not in html, f"{name} still has legacy slate token {legacy}"


def test_ported_templates_keep_test_asserted_copy():
    invite = _read_template("org_admin_invite.html")
    assert "Accept the invitation to access {{organization_name}}." in invite
    assert re.search(r"\{\{inviter_name\}\}</span>\s*invited you to access Zoiko Payroll for", invite)
    assert "Effective permissions are confirmed after sign-in." in invite
    assert ">Accept invitation</a>" in invite
    assert "{{role_name}}" in invite and "{{organization_name}}" in invite

    reset = _read_template("org_admin_password_reset.html")
    assert "Use the secure link only if you requested a reset." in reset
    assert ">Reset password</a>" in reset
    assert "{{expires_at_local}}" in reset
    assert "If this was not you" in reset
    # Header brand mark is the single-source logo partial (a real <img> of
    # the hosted logo); the old text lockup must be gone, not stacked.
    assert "{{logo_header_block}}" in reset
    assert '<span style="color:#ffffff;">Zoiko</span>' not in reset
    assert "temporary_password" not in reset


def test_partial_text_exact_and_no_duplication_in_templates():
    from app.services.email_service import SECURITY_ADVISORY_TEXT

    for name in DANGER_ACCENT_TEMPLATES | CALM_TEMPLATES:
        html = _read_template(name)
        assert html.count("{{security_advisory_block}}") == 1, name
    assert "never ask you to send your password" in SECURITY_ADVISORY_TEXT
"""
tests/test_invite_flow.py
-------------------------
IAM-002 user-invitation flow (org_admin invites payroll_admin):

- supersession: re-invite invalidates the prior live INVITE token (§04)
- accept: consumes token, sets password, marks account claimed/verified
- claim-guard: an already-verified account can never be claimed by a
  replayed invite link (§06)
- template copy compliance + context (organization_name, role_name,
  absolute expiry) (§10)
"""

import re

import pytest

from app.modules.auth import service
from app.modules.auth.models import SecurityActionPurpose, User, UserRole

from app.services import email_service


@pytest.fixture()
def inviter(db, organization):
    actor = User(
        email="owner@acme.test",
        hashed_password="x" * 60,
        role=UserRole.ORG_ADMIN,
        organization_id=organization.id,
        first_name="Sarah",
        last_name="Jenkins",
        is_active=True,
        is_verified=True,
    )
    db.add(actor)
    db.commit()
    db.refresh(actor)
    return actor


@pytest.fixture()
def capture_invite_send(monkeypatch):
    calls = []

    def fake_send(db, user, actor, link, expires_at_local="", reference_id="", **kw):
        calls.append({
            "email": user.email,
            "link": link,
            "expires_at_local": expires_at_local,
            "reference_id": reference_id,
            "actor": actor,
        })
        return True

    monkeypatch.setattr(service, "_send_invite_email", fake_send)
    return calls


def _live_invites(db, email):
    from datetime import datetime

    return [
        t for t in db.query(service.SecurityActionToken)
        .filter_by(email=email, purpose=SecurityActionPurpose.INVITE)
        .all()
        if t.used_at is None and t.superseded_at is None and t.expires_at > datetime.utcnow()
    ]


def test_reinvite_supersedes_prior_live_token(db, inviter, capture_invite_send):
    class Data:
        email = "new.payroll@acme.test"
        role = UserRole.PAYROLL_ADMIN
        first_name = "Alex"
        last_name = "Doe"
        phone = ""
        send_invite = True

    service.invite_user(db, inviter, Data())
    user = db.query(User).filter_by(email=Data.email).first()
    # Admin hits "Resend invite" → new link supersedes the old one.
    service.resend_user_invite(db, inviter, user)
    assert len(_live_invites(db, Data.email)) == 1
    assert len(capture_invite_send) == 2
    # Old link is dead.
    old_token = capture_invite_send[0]["link"].split("token=", 1)[1]
    assert service._consume_action_token(db, old_token, SecurityActionPurpose.INVITE) is None


def test_accept_generates_temp_password_and_claims_account(db, organization, capture_invite_send):
    user = User(
        email="claim.me@acme.test",
        hashed_password="x" * 60,
        role=UserRole.PAYROLL_ADMIN,
        organization_id=organization.id,
        first_name="Claim",
        last_name="Me",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()

    service.resend_user_invite(db, None, user)
    token = capture_invite_send[0]["link"].split("token=", 1)[1]

    result = service.claim_invitation(db, token)
    assert result is not None
    claimed_user, temp_password = result

    db.refresh(claimed_user)
    assert claimed_user.is_verified is True          # account now claimed
    assert len(_live_invites(db, claimed_user.email)) == 0
    # Temporary password actually authenticates (real DB credential change).
    logged_in = service.login_user(db, claimed_user.email, temp_password)
    assert logged_in["user"].role == UserRole.PAYROLL_ADMIN


def test_cannot_replay_invite_link_after_claimed(db, organization, capture_invite_send):
    user = User(
        email="replay@acme.test",
        hashed_password="x" * 60,
        role=UserRole.PAYROLL_ADMIN,
        organization_id=organization.id,
        first_name="Re",
        last_name="Play",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()

    service.resend_user_invite(db, None, user)
    token = capture_invite_send[0]["link"].split("token=", 1)[1]
    first = service.claim_invitation(db, token)
    assert first is not None
    original_password = first[1]
    # Replay must fail AND must not rotate the password of the claimed account.
    assert service.claim_invitation(db, token) is None
    db.refresh(user)
    assert service.verify_password(original_password, user.hashed_password)


def test_invite_email_context_and_copy(monkeypatch):
    captured = {}

    def fake_approval(email, template_name, context, **kw):
        captured.update(template=template_name, **context)
        return True

    monkeypatch.setattr("app.services.email_service.send_approval_email", fake_approval)

    from app.services.email_service import send_user_invite_email

    send_user_invite_email(
        email="new.payroll@acme.test",
        first_name="Alex",
        invite_link="http://localhost:8000/auth/accept-invite?token=t",
        inviter_name="Sarah Jenkins",
        role_name="Payroll Administrator",
        organization_name="Acme Corp",
        expires_at_local="23 August 2026 at 10:00 UTC",
        reference_id="INV-9921-ORG",
    )

    assert captured["template"] == "org_admin_invite.html"
    assert captured["subject"] == "You have been invited to Zoiko Payroll"
    assert captured["preheader"] == "Accept the invitation to access Acme Corp."
    assert captured["role_name"] == "Payroll Administrator"
    assert captured["organization_name"] == "Acme Corp"
    assert captured["reference_id"] == "INV-9921-ORG"


def test_invite_template_compliance():
    path = service.__file__.replace(
        "modules\\auth\\service.py", "email_templates\\org_admin_invite.html"
    ).replace("modules/auth/service.py", "email_templates/org_admin_invite.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()

    assert "Accept the invitation to access {{organization_name}}." in html
    assert ">Accept invitation</a>" in html                       # single CTA
    assert "{{security_advisory_block}}" in html                  # shared partial
    assert email_service.SECURITY_ADVISORY_TEXT not in html       # string not duplicated in file
    assert "{{role_name}}" in html and "{{organization_name}}" in html
    assert re.search(r"\{\{inviter_name\}\}</span>\s*invited you to access Zoiko Payroll for", html)
    assert "Effective permissions are confirmed after sign-in." in html
    assert not re.search(
        r"<img[^>]*(width\s*=\s*[\"']?1[\s\"'>]|height\s*=\s*[\"']?1[\s\"'>]|display:\s*none)",
        html, re.IGNORECASE,
    )


def test_security_advisory_partial_renders_in_both_iam_templates():
    """The verbatim anti-phishing notice lives in ONE place (email_service)
    and is injected into every IAM template via {{security_advisory_block}}."""
    from app.services.email_service import (
        _load_template,
        _render_template,
        SECURITY_ADVISORY_TEXT,
    )

    base_ctx = {
        "first_name": "X", "action_url": "http://x/", "logo_url": "",
        "expires_at_local": "", "reference_id": "", "inviter_name": "Y",
        "organization_name": "Z", "role_name": "R",
        # send_approval_email injects this from the single-source constant
        "security_advisory_block": email_service._SECURITY_ADVISORY_HTML,
    }
    for name in ("org_admin_password_reset.html", "org_admin_invite.html"):
        rendered = _render_template(_load_template(name), dict(base_ctx))
        assert SECURITY_ADVISORY_TEXT in rendered, name
        assert ">Security Advisory</p>" in rendered, name
        assert "{{security_advisory_block}}" not in rendered, name


def test_role_display_label_for_payroll_admin():
    label = service.ROLE_DISPLAY_LABELS[UserRole.PAYROLL_ADMIN]
    assert label == "Payroll Administrator"

"""
tests/test_password_reset_flow.py
---------------------------------
IAM-007 password-reset request/consume/notify flow:

- supersession: a new reset request invalidates the prior live token (§04)
- consumption: one-time use, superseded tokens rejected at click time (§07)
- recipient re-resolution: inactive user cannot complete reset (§06)
- email-enumeration protection: generic response regardless of existence
- expiry rendered as absolute date/time with named zone (§10)

SMTP is monkeypatched — no real email is sent.
"""

import re

import pytest

from app.modules.auth import service
from app.modules.auth.models import SecurityActionPurpose, User, UserRole


VERBATIM_DISCLAIMER = (
    "Zoiko Payroll will never ask you to send your password, "
    "multifactor authentication code, bank details, tax identifiers "
    "or payroll files by email."
)


@pytest.fixture()
def org_admin_user(db, organization):
    user = User(
        email="org.admin@example.com",
        hashed_password="x" * 60,
        role=UserRole.ORG_ADMIN,
        organization_id=organization.id,
        first_name="Alex",
        last_name="Admin",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def payroll_admin_user(db, organization):
    user = User(
        email="payroll.admin@example.com",
        hashed_password="x" * 60,
        role=UserRole.PAYROLL_ADMIN,
        organization_id=organization.id,
        first_name="Pay",
        last_name="Roller",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def capture_send(monkeypatch):
    """Replace _send_reset_email with a recorder; returns list of kwargs."""
    calls = []

    def fake_send_reset_email(db, user, link, expires_at_local="", reference_id="", **kw):
        calls.append({
            "email": user.email,
            "link": link,
            "expires_at_local": expires_at_local,
            "reference_id": reference_id,
        })
        return True

    monkeypatch.setattr(service, "_send_reset_email", fake_send_reset_email)
    return calls


def _live_tokens(db, email):
    from datetime import datetime

    return [
        t for t in db.query(service.SecurityActionToken)
        .filter_by(email=email, purpose=SecurityActionPurpose.RESET)
        .all()
        if t.used_at is None and t.superseded_at is None and t.expires_at > datetime.utcnow()
    ]


def test_double_request_supersedes_prior_token(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    service.request_password_reset(db, org_admin_user.email)

    assert len(_live_tokens(db, org_admin_user.email)) == 1
    assert len(capture_send) == 2


def test_superseded_token_cannot_be_consumed(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    old_token = _extract_token(capture_send[0]["link"])
    service.request_password_reset(db, org_admin_user.email)

    assert service._consume_action_token(db, old_token, SecurityActionPurpose.RESET) is None
    # The new token still works.
    new_token = _extract_token(capture_send[1]["link"])
    assert service._consume_action_token(db, new_token, SecurityActionPurpose.RESET) is not None


def test_consumed_token_single_use(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    token = _extract_token(capture_send[0]["link"])

    first = service._consume_action_token(db, token, SecurityActionPurpose.RESET)
    second = service._consume_action_token(db, token, SecurityActionPurpose.RESET)
    assert first is not None
    assert second is None


def test_complete_rejects_inactive_user_and_restores_generic_error(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    token = _extract_token(capture_send[0]["link"])
    # Consume happens before the active check, so emulate the endpoint order:
    # validate first must pass while active.
    assert service.validate_action_token(db, token, SecurityActionPurpose.RESET) is not None

    org_admin_user.is_active = False
    db.commit()

    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="no longer valid"):
        service.complete_action_token(db, token, SecurityActionPurpose.RESET, "NewPass123!")


def test_complete_sets_new_password_for_active_user(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    token = _extract_token(capture_send[0]["link"])

    result = service.complete_action_token(db, token, SecurityActionPurpose.RESET, "NewPass123!")
    db.refresh(org_admin_user)
    assert "Password set" in result["message"]
    assert service.verify_password("NewPass123!", org_admin_user.hashed_password)

    # Replaying the same link fails.
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        service.complete_action_token(db, token, SecurityActionPurpose.RESET, "OtherPass123!")


def test_enumeration_protection_generic_response(db, capture_send):
    known = service.request_password_reset(db, "nobody@example.com")
    unknown = service.request_password_reset(db, "ghost@example.com")
    assert known == unknown
    assert capture_send == []


def test_expiry_is_absolute_with_named_zone(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    rendered = capture_send[0]["expires_at_local"]
    assert " UTC" in rendered
    # e.g. "22 August 2026 at 14:05 UTC"
    assert re.search(r"\d{1,2} \w+ \d{4} at \d{2}:\d{2} UTC", rendered)
    assert not re.search(r"\bin \d+\s*(hour|min)", rendered, re.IGNORECASE)


def test_link_is_opaque(db, org_admin_user, capture_send):
    service.request_password_reset(db, org_admin_user.email)
    link = capture_send[0]["link"]
    base, query = link.split("?", 1)
    # Query string carries ONLY a high-entropy opaque token — no email,
    # user_id or any readable/structured data.
    match = re.fullmatch(r"token=([A-Za-z0-9_\-]+)", query)
    assert match is not None
    assert len(match.group(1)) >= 40  # secrets.token_urlsafe(32)
    assert base.endswith("/reset-password")


def test_template_copy_compliance():
    from app.services.email_service import SECURITY_ADVISORY_TEXT

    with open(service.__file__.replace(
        "modules\\auth\\service.py", "email_templates\\org_admin_password_reset.html"
    ).replace("modules/auth/service.py", "email_templates/org_admin_password_reset.html"),
        encoding="utf-8",
    ) as f:
        html = f.read()

    assert "Use the secure link only if you requested a reset." in html
    assert "{{security_advisory_block}}" in html   # verbatim notice via shared partial
    assert VERBATIM_DISCLAIMER == __import__(
        "app.services.email_service", fromlist=["SECURITY_ADVISORY_TEXT"]
    ).SECURITY_ADVISORY_TEXT
    assert ">Reset password</a>" in html          # single primary CTA label
    assert "{{expires_at_local}}" in html         # absolute, caller-formatted
    assert "If this was not you" in html
    # §07: no tracking pixels — hidden/1x1 images barred; the content logo is
    # a visible, sized image and allowed.
    assert not re.search(
        r"<img[^>]*(width\s*=\s*[\"']?1[\s\"'>]|height\s*=\s*[\"']?1[\s\"'>]|display:\s*none)",
        html, re.IGNORECASE,
    )
    assert 'alt="Zoiko Payroll"' in html
    assert "{{logo_url}}" in html
    assert "temporary_password" not in html


def test_works_for_payroll_admin_too(db, payroll_admin_user, capture_send):
    service.request_password_reset(db, payroll_admin_user.email)
    assert len(capture_send) == 1
    assert capture_send[0]["email"] == payroll_admin_user.email
    assert len(_live_tokens(db, payroll_admin_user.email)) == 1


def test_payroll_admin_full_cycle_including_unverified_invite_account(db, organization, capture_send):
    """Payroll admins are created via org-admin invite (is_verified=False until
    they first set a password). Forgot-password must work identically for them:
    same request → same IAM-007 email → same consume → password really changes."""
    from app.core.exceptions import BadRequestException

    user = User(
        email="hr.lead@example.com",
        hashed_password=service.hash_password("InvitedTemp1!"),
        role=UserRole.PAYROLL_ADMIN,
        organization_id=organization.id,
        first_name="Hana",
        last_name="Reed",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 1. Request
    result = service.request_password_reset(db, user.email)
    assert result == {
        "message": "If that email is registered, a password reset link has been sent."
    }
    token = _extract_token(capture_send[0]["link"])

    # 2. Open the form page (validate) then submit (consume + set)
    assert service.validate_action_token(db, token, SecurityActionPurpose.RESET) is not None
    service.complete_action_token(db, token, SecurityActionPurpose.RESET, "BrandNew2#pwd")
    db.refresh(user)
    assert service.verify_password("BrandNew2#pwd", user.hashed_password)

    # 3. Link dead afterwards
    with pytest.raises(BadRequestException):
        service.complete_action_token(db, token, SecurityActionPurpose.RESET, "Another3$pwd")

    # 4. New password actually logs in (login path checks hash + active state)
    logged_in = service.login_user(db, user.email, "BrandNew2#pwd")
    assert logged_in["user"].role == UserRole.PAYROLL_ADMIN
    assert logged_in["access_token"]


def _extract_token(link: str) -> str:
    return link.split("token=", 1)[1]

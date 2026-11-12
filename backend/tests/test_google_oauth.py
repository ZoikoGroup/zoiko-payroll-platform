from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import pytest

from starlette.requests import Request

from app.modules.auth import router as auth_router


def _request(cookie=None):
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/auth/google/callback",
        "raw_path": b"/api/auth/google/callback",
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    })


def _state_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[auth_router.GOOGLE_STATE_COOKIE]
    return morsel.value, f"{morsel.key}={morsel.value}"


def test_google_oauth_callback_requires_and_consumes_matching_browser_state(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        auth_router.service,
        "google_sign_in",
        lambda db, code, request, mode: {
            "action": "pending",
            "token": "pending-token",
            "email": "new@example.com",
        },
    )

    start = auth_router.google_register(_request())
    query = parse_qs(urlsplit(start.headers["location"]).query)
    state_cookie_value, cookie_header = _state_cookie(start)
    assert query["state"] == [state_cookie_value.split(":", 1)[1]]
    assert state_cookie_value.startswith("register:")

    callback = auth_router.google_callback(
        _request(cookie_header),
        code="authorization-code",
        state=query["state"][0],
        db=None,
    )
    assert callback.headers["location"].endswith(
        "/register?pending=pending-token&email=new%40example.com"
    )
    assert f"{auth_router.GOOGLE_STATE_COOKIE}=" in callback.headers["set-cookie"]
    assert "Max-Age=0" in callback.headers["set-cookie"]


def test_google_oauth_callback_rejects_missing_or_mismatched_state(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    calls = []
    monkeypatch.setattr(
        auth_router.service,
        "google_sign_in",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    start = auth_router.google_register(_request())
    query = parse_qs(urlsplit(start.headers["location"]).query)
    _state_value, cookie_header = _state_cookie(start)
    missing_cookie = auth_router.google_callback(
        _request(),
        code="authorization-code",
        state=query["state"][0],
        db=None,
    )
    assert missing_cookie.headers["location"].endswith("/login?error=google_state_invalid")

    response = auth_router.google_callback(
        _request(cookie_header),
        code="authorization-code",
        state="attacker-controlled",
        db=None,
    )
    assert response.headers["location"].endswith("/login?error=google_state_invalid")
    assert calls == []


# ── Callback outcomes ─────────────────────────────────────────────────────

def _callback_with(monkeypatch, result=None, exc=None, **params):
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth_router.settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(auth_router.settings, "FRONTEND_URL", "https://app.example.com")

    def fake_sign_in(db, code, request, mode):
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(auth_router.service, "google_sign_in", fake_sign_in)
    start = auth_router.google_login(_request())
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    _value, cookie_header = _state_cookie(start)
    kwargs = {"code": "authorization-code", "state": state, **params}
    return auth_router.google_callback(_request(cookie_header), db=None, **kwargs).headers["location"]


def test_registered_account_is_signed_straight_in_with_tokens_in_the_fragment(monkeypatch):
    location = _callback_with(monkeypatch, {"action": "session",
                                            "session": {"access_token": "AT", "refresh_token": "RT"}})
    assert location == "https://app.example.com/auth/google/callback#access_token=AT&refresh_token=RT"
    assert "?" not in location  # never in the query string (server/access logs)


def test_registered_account_owing_mfa_goes_to_the_login_second_factor(monkeypatch):
    location = _callback_with(monkeypatch, {"action": "mfa", "mfa_token": "MT", "mfa_mode": "challenge"})
    assert location == "https://app.example.com/login#mfa_token=MT&mfa_mode=challenge"


def test_unregistered_google_identity_goes_to_registration(monkeypatch):
    location = _callback_with(monkeypatch, {"action": "pending", "token": "PT", "email": "new@example.com"})
    assert location == "https://app.example.com/register?pending=PT&email=new%40example.com"


def test_refusal_returns_a_fixed_reason_code_never_free_text(monkeypatch):
    from app.core.exceptions import UnauthorizedException

    location = _callback_with(monkeypatch, exc=UnauthorizedException("Your account has been deactivated."))
    assert location == "https://app.example.com/login?error=google_sign_in_failed&reason=account_deactivated"


def test_cancel_on_googles_consent_screen_is_a_friendly_login_message(monkeypatch):
    location = _callback_with(monkeypatch, code=None, error="access_denied")
    assert location == "https://app.example.com/login?error=google_cancelled"


# ── Service: who is "already registered", and registration integrity ─────

def _google_profile(monkeypatch, **profile):
    from app.modules.auth import service

    full = {"id": "google-sub-1", "email": "new@example.com", "verified_email": True,
            "given_name": "Ada", "family_name": "Admin", **profile}
    monkeypatch.setattr(service, "_google_tokens", lambda code: {"access_token": "x"})
    monkeypatch.setattr(service, "_google_userinfo", lambda token: full)
    return full


def _user(db, email, password="a-strong-password-1"):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization

    org = Organization(organization_name="Acme", organization_code="AC" + email.split("@")[0][:8].upper(),
                       is_active=True)
    db.add(org)
    db.flush()
    user = User(email=email, hashed_password=hash_password(password) if password else "",
                role=UserRole.ORG_ADMIN, organization_id=org.id, first_name="Ada",
                last_name="Admin", is_active=True, is_verified=True)
    db.add(user)
    db.commit()
    return user


def _mfa_off(monkeypatch):
    # tests/conftest.py enforces MFA for the whole suite; production's
    # default (config.py) is "off", where Google signs straight in.
    from app.modules.auth import mfa

    monkeypatch.setattr(mfa.settings, "MFA_ENFORCEMENT", "off")


def test_registered_email_signs_in_whatever_its_case(db, monkeypatch):
    from app.modules.auth import service

    _mfa_off(monkeypatch)
    user = _user(db, "Ada.Admin@Example.com")
    _google_profile(monkeypatch, email="ada.admin@example.com")
    result = service.google_sign_in(db, "code")
    assert result["action"] == "session"
    db.refresh(user)
    assert user.google_id == "google-sub-1"
    assert user.auth_provider != "google"  # still a password account too


def test_unregistered_email_gets_a_pending_registration(db, monkeypatch):
    from app.modules.auth import service

    _google_profile(monkeypatch)
    result = service.google_sign_in(db, "code")
    assert result["action"] == "pending" and result["email"] == "new@example.com"
    assert service.get_google_pending(db, result["token"])["google_id"] == "google-sub-1"


def test_google_sign_in_applies_the_same_mfa_rule_as_password_sign_in(db, monkeypatch):
    from app.modules.auth import mfa, service

    _user(db, "mfa-admin@example.com")
    _google_profile(monkeypatch, email="mfa-admin@example.com")
    monkeypatch.setattr(mfa.settings, "MFA_ENFORCEMENT", "enforce")
    result = service.google_sign_in(db, "code")
    assert result["action"] == "mfa" and result["mfa_mode"] == "enroll" and result["mfa_token"]


def test_suspended_organization_cannot_sign_in_with_google(db, monkeypatch):
    from app.core.exceptions import UnauthorizedException
    from app.modules.auth import service
    from app.modules.organizations.models import Organization

    user = _user(db, "suspended@example.com")
    db.query(Organization).filter(Organization.id == user.organization_id).update({"is_active": False})
    db.commit()
    _google_profile(monkeypatch, email="suspended@example.com")
    with pytest.raises(UnauthorizedException, match="suspended"):
        service.google_sign_in(db, "code")


def _active_in_pack(db):
    from decimal import Decimal

    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-GOOGLE-TEST", jurisdiction_country="IN", pack_type="tax",
                            version="1.0", status="Active")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    db.add(ContributionRate(organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
                            component_key="pf", label="PF", employee_share="-", employer_share="-",
                            total="-", employee_rate_pct=Decimal("12.00")))
    db.commit()


def _google_registration(**overrides):
    from app.modules.auth.schemas import RegisterRequest

    fields = dict(organization="Google Co", name="Ada Admin", email="new@example.com", country="IN",
                  terms_accepted=True, auth_provider="google")
    fields.update(overrides)
    return RegisterRequest(**fields)


def test_google_registration_needs_the_callbacks_pending_token(db):
    from app.core.exceptions import BadRequestException
    from app.modules.auth import service

    _active_in_pack(db)
    # A client-supplied google_id alone (the old contract) is refused.
    with pytest.raises(BadRequestException, match="expired"):
        service.register_enterprise(db, _google_registration(google_id="attacker-sub"))


def test_google_registration_takes_identity_and_email_from_the_token(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.auth import service
    from app.modules.auth.models import User

    _active_in_pack(db)
    _google_profile(monkeypatch)
    token = service.google_sign_in(db, "code")["token"]

    with pytest.raises(BadRequestException, match="Google account"):
        service.register_enterprise(db, _google_registration(email="victim@example.com",
                                                             google_pending_token=token))

    service.register_enterprise(db, _google_registration(google_pending_token=token, google_id="attacker-sub"))
    admin = db.query(User).filter(User.email == "new@example.com").one()
    assert admin.google_id == "google-sub-1" and admin.auth_provider == "google"
    assert service.get_google_pending(db, token) is None  # single use

    # ... and the next "Continue with Google" signs that account straight in.
    _mfa_off(monkeypatch)
    assert service.google_sign_in(db, "code")["action"] == "session"


def test_email_registration_still_requires_a_password(db):
    from app.core.exceptions import BadRequestException
    from app.modules.auth import service
    from app.modules.auth.schemas import RegisterRequest

    _active_in_pack(db)
    with pytest.raises(BadRequestException, match="password"):
        service.register_enterprise(db, RegisterRequest(organization="Pw Co", name="Ada Admin",
                                                        email="pw@example.com", country="IN", terms_accepted=True))

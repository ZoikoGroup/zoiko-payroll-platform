"""Microsoft / Apple sign-in, sign-up and Company SSO discovery.

Mirrors tests/test_google_oauth.py: browser-state CSRF checks on the
callbacks, fixed-code redirects, identity matching rules, and registration
integrity (identity from the pending token only, single use, welcome email).
"""

import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import pytest
from jose import jwt
from starlette.requests import Request

from app.core import social_oauth
from app.modules.auth import router as auth_router
from app.modules.auth import social

MS_CLIENT = "ms-client-id"
APPLE_CLIENT = "com.example.payroll.web"
TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def _request(path, cookie=None, method="GET"):
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    return Request({"type": "http", "http_version": "1.1", "method": method, "scheme": "http",
                    "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
                    "server": ("testserver", 80), "client": ("127.0.0.1", 12345)})


def _configure(monkeypatch):
    s = auth_router.settings
    monkeypatch.setattr(s, "FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(s, "MICROSOFT_CLIENT_ID", MS_CLIENT)
    monkeypatch.setattr(s, "MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setattr(s, "MICROSOFT_TENANT", "common")
    monkeypatch.setattr(s, "APPLE_CLIENT_ID", APPLE_CLIENT)
    monkeypatch.setattr(s, "APPLE_TEAM_ID", "TEAM123456")
    monkeypatch.setattr(s, "APPLE_KEY_ID", "KEY1234567")
    monkeypatch.setattr(s, "APPLE_PRIVATE_KEY", _apple_key_pem())
    monkeypatch.setattr(s, "APPLE_REDIRECT_URI", "https://api.example.com/api/auth/apple/callback")


_KEY = None


def _apple_key():
    global _KEY
    if _KEY is None:
        from cryptography.hazmat.primitives.asymmetric import ec

        _KEY = ec.generate_private_key(ec.SECP256R1())
    return _KEY


def _apple_key_pem():
    from cryptography.hazmat.primitives import serialization

    return _apple_key().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()).decode()


def _state_cookie(response, provider):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[f"zoiko_{provider}_oauth_state"]
    return morsel, f"{morsel.key}={morsel.value}"


# ── Callbacks: CSRF state, outcomes, fixed-code failures ──────────────────

def _start(monkeypatch, provider, mode, result=None, exc=None):
    _configure(monkeypatch)
    calls = []

    def fake_sign_in(db, prov, code, request=None, mode=None, apple_user=None):
        calls.append({"provider": prov, "code": code, "mode": mode, "apple_user": apple_user})
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(social, "sign_in", fake_sign_in)
    start = getattr(auth_router, f"{provider}_{mode}")(_request(f"/api/auth/{provider}/{mode}"))
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    morsel, cookie_header = _state_cookie(start, provider)
    return start, state, morsel, cookie_header, calls


def test_microsoft_start_and_callback_hand_a_new_identity_to_registration(monkeypatch):
    start, state, morsel, cookie, calls = _start(
        monkeypatch, "microsoft", "register",
        result={"action": "pending", "token": "tok", "email": "new@contoso.com", "provider": "microsoft"})
    location = start.headers["location"]
    assert location.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert morsel.value == f"register:{state}"
    assert morsel["samesite"].lower() == "lax" and morsel["httponly"]

    response = auth_router.microsoft_callback(_request("/api/auth/microsoft/callback", cookie),
                                              code="c", state=state, error=None, db=None)
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://app.example.com/register?pending=tok&provider=microsoft&email=new%40contoso.com")
    assert "Max-Age=0" in response.headers["set-cookie"]  # state is single use
    assert calls == [{"provider": "microsoft", "code": "c", "mode": "register", "apple_user": None}]


def test_microsoft_callback_rejects_missing_or_mismatched_state(monkeypatch):
    _start_resp, state, _m, cookie, calls = _start(monkeypatch, "microsoft", "login", result={})
    for req, st in ((_request("/cb"), state), (_request("/cb", cookie), "attacker")):
        response = auth_router.microsoft_callback(req, code="c", state=st, error=None, db=None)
        assert response.headers["location"].endswith("/login?error=oauth_state_invalid&provider=microsoft")
    assert calls == []


def test_cancelled_sign_up_returns_to_the_registration_page(monkeypatch):
    _s, state, _m, cookie, _c = _start(monkeypatch, "microsoft", "register", result={})
    response = auth_router.microsoft_callback(_request("/cb", cookie), code=None, state=state,
                                              error="access_denied", db=None)
    assert response.headers["location"].endswith("/register?error=oauth_cancelled&provider=microsoft")


def test_refusal_is_a_fixed_reason_code_never_free_text(monkeypatch):
    from app.core.exceptions import UnauthorizedException

    _s, state, _m, cookie, _c = _start(monkeypatch, "microsoft", "login",
                                       exc=UnauthorizedException("Your organization has been suspended. <b>x</b>"))
    location = auth_router.microsoft_callback(_request("/cb", cookie), code="c", state=state, error=None,
                                              db=None).headers["location"]
    assert location.endswith("/login?error=oauth_failed&provider=microsoft&reason=organization_suspended")


def test_session_tokens_travel_only_in_the_fragment(monkeypatch):
    _s, state, _m, cookie, _c = _start(monkeypatch, "microsoft", "login", result={
        "action": "session", "session": {"access_token": "AT", "refresh_token": "RT"}})
    location = auth_router.microsoft_callback(_request("/cb", cookie), code="c", state=state, error=None,
                                              db=None).headers["location"]
    assert location == "https://app.example.com/auth/social/callback#access_token=AT&refresh_token=RT"


def test_apple_uses_a_cross_site_cookie_and_a_303_back_to_the_frontend(monkeypatch):
    start, state, morsel, cookie, calls = _start(
        monkeypatch, "apple", "register",
        result={"action": "pending", "token": "tok", "email": "abc@privaterelay.appleid.com", "provider": "apple"})
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert start.headers["location"].startswith(social_oauth.APPLE_AUTHORIZATION_ENDPOINT)
    assert query["response_mode"] == ["form_post"] and query["scope"] == ["name email"]
    # Apple POSTs back cross-site: only a SameSite=None; Secure cookie survives that.
    assert morsel["samesite"].lower() == "none" and morsel["secure"]

    response = auth_router.apple_callback(
        _request("/api/auth/apple/callback", cookie, method="POST"), code="c", state=state, error=None,
        user='{"name": {"firstName": "Ada", "lastName": "Lovelace"}}', db=None)
    assert response.status_code == 303
    assert "/register?pending=tok&provider=apple" in response.headers["location"]
    assert calls[0]["apple_user"] == {"name": {"firstName": "Ada", "lastName": "Lovelace"}}


def test_unconfigured_provider_cannot_start(monkeypatch):
    from app.core.exceptions import BadRequestException

    monkeypatch.setattr(auth_router.settings, "APPLE_PRIVATE_KEY", "")
    with pytest.raises(BadRequestException, match="not configured"):
        auth_router.apple_login(_request("/api/auth/apple/login"))
    assert social.provider_status()["apple"] is False


# ── id_token checks and the outbound boundary ────────────────────────────

def _id_token(**claims):
    base = {"exp": int(time.time()) + 600, "iat": int(time.time())}
    return jwt.encode({**base, **claims}, "not-checked", algorithm="HS256")


def test_microsoft_id_token_issuer_audience_and_expiry_are_checked():
    good = dict(iss=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0", tid=TENANT_ID, aud=MS_CLIENT, sub="s")
    assert social_oauth.microsoft_claims(_id_token(**good), MS_CLIENT)["sub"] == "s"
    for bad in (dict(good, aud="someone-else"), dict(good, iss="https://evil.example/v2.0"),
                dict(good, tid="00000000-0000-0000-0000-000000000000"), dict(good, exp=int(time.time()) - 3600)):
        with pytest.raises(social_oauth.IdTokenError):
            social_oauth.microsoft_claims(_id_token(**bad), MS_CLIENT)
    with pytest.raises(social_oauth.IdTokenError):
        social_oauth.microsoft_claims("not-a-jwt", MS_CLIENT)


def test_only_microsoft_verified_emails_are_trusted():
    assert social_oauth.microsoft_email_is_verified({"tid": social_oauth.MICROSOFT_CONSUMER_TENANT_ID})
    assert social_oauth.microsoft_email_is_verified({"tid": TENANT_ID, "xms_edov": True})
    assert not social_oauth.microsoft_email_is_verified({"tid": TENANT_ID})


def test_apple_client_secret_is_an_es256_jwt_apple_can_verify():
    from cryptography.hazmat.primitives import serialization

    secret = social_oauth.apple_client_secret("TEAM123456", APPLE_CLIENT, "KEY1234567",
                                              _apple_key_pem().replace("\n", "\\n"))
    public_pem = _apple_key().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    claims = jwt.decode(secret, public_pem, algorithms=["ES256"], audience=social_oauth.APPLE_ISSUER)
    assert claims["iss"] == "TEAM123456" and claims["sub"] == APPLE_CLIENT
    assert jwt.get_unverified_header(secret)["kid"] == "KEY1234567"


def test_microsoft_token_endpoint_is_built_only_from_a_valid_tenant():
    assert social_oauth.microsoft_endpoint("contoso.onmicrosoft.com", "token") == \
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
    for tenant in ("evil.example/../x", "a/b", "", "x@y"):
        with pytest.raises(ValueError):
            social_oauth.microsoft_endpoint(tenant, "token")


# ── Service: matching, linking and registration ──────────────────────────

def _profile(monkeypatch, provider, **overrides):
    profile = {"subject": f"{provider}-sub-1", "email": "new@example.com", "email_verified": True,
               "given_name": "Ada", "family_name": "Admin", "is_private_relay": False, **overrides}
    monkeypatch.setattr(social, "_microsoft_profile", lambda code: profile)
    monkeypatch.setattr(social, "_apple_profile", lambda code, user: profile)
    return profile


def _user(db, email):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization

    org = Organization(organization_name="Acme", organization_code="AC" + email.split("@")[0][:8].upper(),
                       is_active=True)
    db.add(org)
    db.flush()
    user = User(email=email, hashed_password=hash_password("a-strong-password-1"), role=UserRole.ORG_ADMIN,
                organization_id=org.id, first_name="Ada", last_name="Admin", is_active=True, is_verified=True)
    db.add(user)
    db.commit()
    return user


def _mfa_off(monkeypatch):
    from app.modules.auth import mfa

    monkeypatch.setattr(mfa.settings, "MFA_ENFORCEMENT", "off")


def test_verified_email_links_an_existing_account(db, monkeypatch):
    from app.modules.auth.models import OAuthIdentity

    _configure(monkeypatch)
    _mfa_off(monkeypatch)
    user = _user(db, "Ada@Example.com")
    _profile(monkeypatch, "microsoft", email="ada@example.com")
    assert social.sign_in(db, "microsoft", "code")["action"] == "session"
    identity = db.query(OAuthIdentity).one()
    assert (identity.user_id, identity.provider) == (user.id, "microsoft")


def test_unverified_microsoft_email_never_takes_over_an_existing_account(db, monkeypatch):
    from app.modules.auth.models import OAuthIdentity

    _configure(monkeypatch)
    _user(db, "victim@example.com")
    _profile(monkeypatch, "microsoft", email="victim@example.com", email_verified=False)
    result = social.sign_in(db, "microsoft", "code")
    assert result["action"] == "pending"  # not a session as the victim
    assert db.query(OAuthIdentity).count() == 0


def test_microsoft_sign_in_applies_the_same_mfa_rule_as_password_sign_in(db, monkeypatch):
    from app.modules.auth import mfa

    _configure(monkeypatch)
    _user(db, "mfa@example.com")
    _profile(monkeypatch, "microsoft", email="mfa@example.com")
    monkeypatch.setattr(mfa.settings, "MFA_ENFORCEMENT", "enforce")
    assert social.sign_in(db, "microsoft", "code")["action"] == "mfa"


def _active_in_pack(db):
    from decimal import Decimal

    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-SOCIAL-TEST", jurisdiction_country="IN", pack_type="tax",
                            version="1.0", status="Active")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    db.add(ContributionRate(organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
                            component_key="pf", label="PF", employee_share="-", employer_share="-",
                            total="-", employee_rate_pct=Decimal("12.00")))
    db.commit()


def _registration(**overrides):
    from app.modules.auth.schemas import RegisterRequest

    fields = dict(organization="Social Co", name="Ada Admin", email="new@example.com", country="IN",
                  terms_accepted=True)
    fields.update(overrides)
    return RegisterRequest(**fields)


def _capture_welcome(monkeypatch):
    from app.services import email_service

    sent = []
    monkeypatch.setattr(email_service, "send_organization_created_email",
                        lambda **kwargs: sent.append(kwargs) or True)
    return sent


def test_microsoft_registration_takes_identity_from_the_token_and_sends_the_welcome_email(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.auth import service
    from app.modules.auth.models import OAuthIdentity, User

    _configure(monkeypatch)
    _active_in_pack(db)
    sent = _capture_welcome(monkeypatch)
    _profile(monkeypatch, "microsoft")
    token = social.sign_in(db, "microsoft", "code", mode="register")["token"]

    # No token, a wrong provider's token, or someone else's email: refused.
    with pytest.raises(BadRequestException, match="expired"):
        service.register_enterprise(db, _registration(auth_provider="microsoft"))
    with pytest.raises(BadRequestException, match="expired"):
        service.register_enterprise(db, _registration(auth_provider="apple", oauth_pending_token=token))
    with pytest.raises(BadRequestException, match="Microsoft account"):
        service.register_enterprise(db, _registration(auth_provider="microsoft", oauth_pending_token=token,
                                                      email="victim@example.com"))

    service.register_enterprise(db, _registration(auth_provider="microsoft", oauth_pending_token=token))
    admin = db.query(User).filter(User.email == "new@example.com").one()
    assert admin.auth_provider == "microsoft" and admin.hashed_password == ""
    assert db.query(OAuthIdentity).filter_by(user_id=admin.id, subject="microsoft-sub-1").count() == 1
    assert social.get_pending(db, token) is None  # single use
    assert len(sent) == 1  # welcome email, same as every other sign-up method

    _mfa_off(monkeypatch)
    assert social.sign_in(db, "microsoft", "code")["action"] == "session"


def test_apple_hide_my_email_user_can_register_with_a_work_email(db, monkeypatch):
    from app.modules.auth import service
    from app.modules.auth.models import OAuthIdentity, User
    from app.modules.organizations.models import Organization

    _configure(monkeypatch)
    _active_in_pack(db)
    sent = _capture_welcome(monkeypatch)
    relay = "x7y2k9q4@privaterelay.appleid.com"
    _profile(monkeypatch, "apple", email=relay, is_private_relay=True)
    result = social.sign_in(db, "apple", "code", mode="register")
    assert result["is_private_relay"] is True
    assert social.public_pending(db, result["token"]) == {
        "provider": "apple", "email": relay, "given_name": "Ada", "family_name": "Admin", "is_private_relay": True}

    service.register_enterprise(db, _registration(auth_provider="apple", oauth_pending_token=result["token"],
                                                  email="ada@company.com"))
    admin = db.query(User).filter(User.email == "ada@company.com").one()
    identity = db.query(OAuthIdentity).filter_by(user_id=admin.id).one()
    assert (identity.provider_email, identity.is_private_relay) == (relay, True)
    # Account and billing contact both use the work email.
    assert db.query(Organization).filter(Organization.id == admin.organization_id).one().email == "ada@company.com"
    assert len(sent) == 1


def test_password_is_still_required_for_email_sign_up_and_unknown_providers_are_refused(db):
    from pydantic import ValidationError

    from app.core.exceptions import BadRequestException
    from app.modules.auth import service

    _active_in_pack(db)
    with pytest.raises(BadRequestException, match="password"):
        service.register_enterprise(db, _registration())
    with pytest.raises(ValidationError):
        _registration(auth_provider="facebook")


# ── Company SSO discovery ─────────────────────────────────────────────────

def test_company_sso_is_off_by_default(db, monkeypatch):
    from app.core.exceptions import NotFoundException

    monkeypatch.setattr(social.settings, "COMPANY_SSO_ENABLED", False)
    assert social.provider_status()["sso"] is False
    with pytest.raises(NotFoundException):
        social.discover_sso(db, "it@acme.example")


def test_sso_discovery_finds_only_configured_https_domains(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.auth.models import OrganizationSsoDomain

    monkeypatch.setattr(social.settings, "COMPANY_SSO_ENABLED", True)
    assert social.provider_status()["sso"] is True

    org_user = _user(db, "it@acme.example")
    db.add(OrganizationSsoDomain(organization_id=org_user.organization_id, domain="acme.example",
                                 login_url="https://idp.acme.example/sso/zoiko"))
    db.add(OrganizationSsoDomain(organization_id=org_user.organization_id, domain="plain.example",
                                 login_url="http://idp.plain.example/sso"))
    db.commit()

    assert social.discover_sso(db, "Someone@ACME.example") == {
        "sso": True, "login_url": "https://idp.acme.example/sso/zoiko"}
    assert social.discover_sso(db, "a@newco.example") == {"sso": False}
    assert social.discover_sso(db, "a@plain.example") == {"sso": False}  # never send users to http
    with pytest.raises(BadRequestException):
        social.discover_sso(db, "not-an-email")

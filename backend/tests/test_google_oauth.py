from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

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

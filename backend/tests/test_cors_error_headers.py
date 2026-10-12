"""
tests/test_cors_error_headers.py
-----------------------------------
Coverage for core/exceptions.py's _cors_headers (platform infrastructure
fix plan, 2026-09-18). Previously reflected ANY Origin header verbatim
(falling back to "*") paired with Allow-Credentials: true on every error
response, bypassing the real allowlist main.py's CORSMiddleware enforces
on the success path. Now must match that same allowlist exactly.
"""

from unittest.mock import Mock

from app.core.exceptions import _cors_headers
from app.config import settings


def _make_request(origin: str = None):
    request = Mock()
    request.headers = {"origin": origin} if origin else {}
    return request


def test_cors_headers_allows_a_configured_origin():
    allowed_origin = next(iter(_cors_headers.__globals__["_ALLOWED_ORIGINS"]))
    headers = _cors_headers(_make_request(allowed_origin))
    assert headers["Access-Control-Allow-Origin"] == allowed_origin
    assert headers["Access-Control-Allow-Credentials"] == "true"


def test_cors_headers_rejects_an_arbitrary_unconfigured_origin():
    # The exact bug this test guards against: an attacker-controlled
    # origin must NOT get a credentialed CORS pass on an error response.
    headers = _cors_headers(_make_request("https://evil.example.com"))
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Credentials" not in headers


def test_cors_headers_omits_origin_when_none_sent():
    headers = _cors_headers(_make_request(None))
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Credentials" not in headers


def test_cors_headers_never_falls_back_to_wildcard():
    # The exact prior behavior being removed: "*" must never appear,
    # since it was previously the fallback for a missing Origin header.
    headers = _cors_headers(_make_request(None))
    assert headers.get("Access-Control-Allow-Origin") != "*"


def test_cors_allowlist_matches_configured_settings():
    configured = {o.strip() for o in settings.PAYROLL_CORS_ORIGINS.split(",") if o.strip()}
    assert _cors_headers.__globals__["_ALLOWED_ORIGINS"] == configured

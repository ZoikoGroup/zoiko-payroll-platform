"""
tests/_mfa_login.py
-------------------
Sign in through the REAL login flow, including the mandatory MFA step for
privileged roles (ZP-PRIV B08): on first login the TOTP is enrolled with
pyotp (as an authenticator app would), afterwards each login answers the
challenge with a fresh code. Returns the final HTTP response, so a test can
keep reading ``response.json()["access_token"]`` exactly as before.

MFA is never switched off for tests; this helper goes through it.
"""

from __future__ import annotations

import time

import pyotp

# email -> (TOTP secret, last 30-second step used) for this test process.
_SECRETS: dict = {}


def _next_code(email: str) -> str:
    secret, last_step = _SECRETS[email]
    step = int(time.time() // 30)
    if last_step is not None and step <= last_step:
        step = last_step + 1  # the server refuses a replayed step; +1 is inside its window
    _SECRETS[email] = (secret, step)
    return pyotp.TOTP(secret).at(step * 30)


def mfa_login(client, json: dict):
    email = json["email"]
    first = client.post("/api/auth/login", json=json)
    if first.status_code != 200:
        return first
    body = first.json()
    if body.get("mfa_enrollment_required"):
        token = body["mfa_token"]
        begin = client.post("/api/auth/mfa/enroll/begin", json={"mfaToken": token})
        assert begin.status_code == 200, begin.text
        _SECRETS[email] = (begin.json()["secret"], None)
        return client.post("/api/auth/mfa/enroll/confirm", json={"mfaToken": token, "code": _next_code(email)})
    if body.get("mfa_required"):
        if email not in _SECRETS:
            raise AssertionError(f"{email} has MFA enrolled outside this test helper")
        return client.post("/api/auth/mfa/challenge", json={"mfaToken": body["mfa_token"],
                                                            "code": _next_code(email)})
    return first


def step_up(client, email: str, headers: dict) -> dict:
    """A fresh MFA code -> an access token with a current mfa_at (for
    approve / break-glass / export / reveal actions)."""
    r = client.post("/api/auth/mfa/step-up", json={"code": _next_code(email)}, headers=headers)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def totp_code(email: str) -> str:
    return _next_code(email)

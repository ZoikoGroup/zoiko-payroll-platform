"""
tests/privacy/test_mfa_sessions.py
----------------------------------
MFA, step-up and session hardening (ZP-PRIV B08) over HTTP.
"""

from __future__ import annotations

import time

import pyotp

PASSWORD = "Priv-Test-Password-1!"


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


def _enrol(client, email):
    first = _login(client, email).json()
    assert first["mfa_enrollment_required"] and first["mfa_token"] and not first.get("access_token")
    begin = client.post("/api/auth/mfa/enroll/begin", json={"mfaToken": first["mfa_token"]}).json()
    assert begin["otpauthUri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(begin["secret"])
    done = client.post("/api/auth/mfa/enroll/confirm", json={"mfaToken": first["mfa_token"], "code": totp.now()})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["access_token"] and len(body["recovery_codes"]) == 10
    return begin["secret"], body


def _code(secret, step_offset=1):
    return pyotp.TOTP(secret).at((int(time.time() // 30) + step_offset) * 30)


def test_privileged_roles_must_enrol_and_password_alone_never_gives_a_session(client, world):
    for who in ("SA", "SP", "APP", "TA"):
        body = _login(client, world.users[who].email).json()
        assert body.get("mfa_enrollment_required") is True and not body.get("access_token"), who
    # payroll_admin: MFA optional -> normal session.
    pa = _login(client, world.users["PA"].email).json()
    assert pa["access_token"] and not pa.get("mfa_required")


def test_challenge_replay_wrong_code_and_recovery(client, world):
    email = world.users["TA"].email
    secret, enrolled = _enrol(client, email)
    challenge = _login(client, email).json()
    assert challenge["mfa_required"] is True
    bad = client.post("/api/auth/mfa/challenge", json={"mfaToken": challenge["mfa_token"], "code": "123456"})
    assert bad.status_code == 401
    code = _code(secret)
    ok = client.post("/api/auth/mfa/challenge", json={"mfaToken": challenge["mfa_token"], "code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    # The challenge token is single-use, and the code cannot be replayed.
    again = client.post("/api/auth/mfa/challenge", json={"mfaToken": challenge["mfa_token"], "code": code})
    assert again.status_code == 401
    replay = client.post("/api/auth/mfa/challenge",
                         json={"mfaToken": _login(client, email).json()["mfa_token"], "code": code})
    assert replay.status_code == 401
    recovery = enrolled["recovery_codes"][0]
    use = client.post("/api/auth/mfa/challenge",
                      json={"mfaToken": _login(client, email).json()["mfa_token"], "recoveryCode": recovery})
    assert use.status_code == 200
    reuse = client.post("/api/auth/mfa/challenge",
                        json={"mfaToken": _login(client, email).json()["mfa_token"], "recoveryCode": recovery})
    assert reuse.status_code == 401


def test_password_only_token_for_a_privileged_role_is_refused(client, world):
    from app.core.security import create_access_token

    u = world.users["TA"]
    token = create_access_token({"sub": u.email, "role": "org_admin", "user_id": u.id,
                                 "organization_id": u.organization_id})
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401 and resp.json()["error"] == "MFA_REQUIRED"


def test_privileged_access_tokens_live_15_minutes(world):
    from app.core.security import decode_access_token

    payload = decode_access_token(world.token("SA"))
    assert payload["exp"] - time.time() <= 15 * 60 + 5


def test_step_up_mints_a_fresh_mfa_at_and_gates_sensitive_actions(client, world):
    email = world.users["TA"].email
    secret, enrolled = _enrol(client, email)
    stale = {"Authorization": f"Bearer {world.token('TA', mfa_at=int(time.time()) - 3600)}"}
    gated = client.post("/api/auth/mfa/recovery-codes", headers=stale)
    assert gated.status_code == 403 and gated.json()["error"] == "STEP_UP_REQUIRED"
    stepped = client.post("/api/auth/mfa/step-up", headers=stale, json={"code": _code(secret)})
    assert stepped.status_code == 200
    fresh = {"Authorization": f"Bearer {stepped.json()['accessToken']}"}
    assert client.post("/api/auth/mfa/recovery-codes", headers=fresh).status_code == 200
    # Mandatory roles cannot switch MFA off.
    assert client.post("/api/auth/mfa/disable", headers=fresh).status_code == 403


def test_refresh_rotation_and_reuse_detection(client, world):
    session = _login(client, world.users["PA"].email).json()
    first = session["refresh_token"]
    rotated = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first
    reused = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert reused.status_code == 401
    # Reuse revoked the whole family, including the newest token.
    assert client.post("/api/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_logout_revokes_the_refresh_token(client, world):
    session = _login(client, world.users["PA"].email).json()
    h = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.post("/api/auth/logout", headers=h, json={"refresh_token": session["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_role_change_revokes_tokens_and_refresh(client, world, db):
    from app.modules.auth.models import UserRole

    session = _login(client, world.users["PA"].email).json()
    world.users["PA"].role = UserRole.ORG_ADMIN
    db.commit()
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {session['access_token']}"}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401


def test_privileged_refresh_requires_reauth_when_idle(client, world, db):
    from datetime import datetime, timedelta

    from app.modules.auth.models import RefreshTokenRecord

    email = world.users["TA"].email
    _, enrolled = _enrol(client, email)
    record = db.query(RefreshTokenRecord).order_by(RefreshTokenRecord.id.desc()).first()
    record.issued_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    resp = client.post("/api/auth/refresh", json={"refresh_token": enrolled["refresh_token"]})
    assert resp.status_code == 401 and "sign in again" in resp.json()["message"]


def test_privileged_refresh_requires_reauth_on_a_new_device(client, world):
    email = world.users["TA"].email
    _, enrolled = _enrol(client, email)
    resp = client.post("/api/auth/refresh", json={"refresh_token": enrolled["refresh_token"]},
                       headers={"user-agent": "a-different-browser/1.0"})
    assert resp.status_code == 401


def test_mfa_off_is_password_only_and_never_asks_for_a_code(client, world, db, monkeypatch):
    """DEC-11: with MFA_ENFORCEMENT off (the default) sign-in is password only,
    sensitive actions need no fresh code, and an enrolled user is not challenged."""
    import pyotp

    from app.config import settings
    from app.modules.auth import mfa

    secret = mfa.begin_enrollment(db, world.users["TA"])["secret"]
    mfa.confirm_enrollment(db, world.users["TA"], pyotp.TOTP(secret).now())
    monkeypatch.setattr(settings, "MFA_ENFORCEMENT", "off")
    for email in ("sa@platform.example", "ta@tenant-a.example"):
        r = client.post("/api/auth/login", json={"email": email, "password": "Priv-Test-Password-1!"})
        assert r.status_code == 200 and r.json().get("access_token"), r.text
        assert not r.json().get("mfa_required") and not r.json().get("mfa_enrollment_required")
    token = client.post("/api/auth/login", json={"email": "ta@tenant-a.example",
                                                 "password": "Priv-Test-Password-1!"}).json()["access_token"]
    created = client.post("/api/organization-admin/api-clients", headers={"Authorization": f"Bearer {token}"},
                          json={"name": "x", "scopes": ["employees:read"], "expiresInDays": 30})
    assert created.status_code == 200, created.text  # was 403 STEP_UP_REQUIRED with enforcement on

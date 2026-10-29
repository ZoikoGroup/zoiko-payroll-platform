"""Platform Users — one user's account, registration and security detail.

GET /api/super-admin/users/{user_id} is Super Admin only, read-only, returns
every datetime as timezone-aware UTC ("Z"), never returns a password hash,
MFA secret or token, infers how the account was created, and records each
view as a PRIVILEGED_READ security event. The list returns UTC times too.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta


def _detail(client, world, who, user_key):
    return client.get(f"/api/super-admin/users/{world.users[user_key].id}", headers=world.headers(who))


def _registered_org(world):
    org = world.orgs["A"]
    org.industry, org.company_type = "Technology", "Private Limited"
    org.address, org.city, org.state, org.country = "1 Test Street", "Pune", "Maharashtra", "India"
    org.email, org.phone = "office@tenant-a.example", "+91 20 0000 0000"
    org.tax_no, org.registration_number = "SYNTHETIC-ID-01", "U12345MH2026PTC000001"
    org.tax_identifiers = {"pan": "SYNTHETIC-ID-01"}
    org.workspace_type = "PRODUCTION"
    org.terms_accepted_at = datetime(2026, 10, 29, 10, 0, 12)
    org.created_by_user_id = None
    world.db.commit()
    return org


def test_only_super_admin_can_read_user_detail(client, world):
    for who in ("TA", "PA", "SP"):
        assert _detail(client, world, who, "TA").status_code in (401, 403), who
    assert _detail(client, world, "SA", "TA").status_code == 200


def test_unknown_user_is_404(client, world):
    resp = client.get("/api/super-admin/users/987654", headers=world.headers("SA"))
    assert resp.status_code == 404


def test_detail_returns_registration_details_with_utc_times(client, world):
    _registered_org(world)
    body = _detail(client, world, "SA", "TA").json()

    account = body["account"]
    assert account["email"] == world.users["TA"].email and account["role"] == "org_admin"
    assert account["created_at"].endswith("Z") or account["created_at"].endswith("+00:00")
    assert account["created_via"] == "REGISTRATION"                 # first user of a self-registered org

    org = body["organization"]
    assert (org["industry"], org["city"], org["country"]) == ("Technology", "Pune", "India")
    assert org["registration_number"] == "U12345MH2026PTC000001"
    from app.core.jurisdiction import get_jurisdiction_schema

    labels = {f["key"]: f["label"] for f in (get_jurisdiction_schema("India") or {}).get("fields", [])}
    assert org["tax_identifiers"] == [{"key": "pan", "label": labels.get("pan", "pan"), "value": "SYNTHETIC-ID-01"}]
    assert org["terms_accepted_at"].startswith("2026-10-29T10:00:12")
    assert org["terms_accepted_at"].endswith("Z") or org["terms_accepted_at"].endswith("+00:00")
    assert org["workspace_type"] == "PRODUCTION"


def test_created_via_is_inferred(client, world):
    from app.modules.auth.models import SecurityActionPurpose, SecurityActionToken

    _registered_org(world)
    assert _detail(client, world, "SA", "SA").json()["account"]["created_via"] == "PLATFORM_ACCOUNT"
    assert _detail(client, world, "SA", "PA").json()["account"]["created_via"] == "ADDED_BY_ADMIN"

    world.db.add(SecurityActionToken(email=world.users["PA"].email, organization_id=world.orgs["A"].id,
                                     purpose=SecurityActionPurpose.INVITE, token_hash="f" * 64,
                                     expires_at=datetime.utcnow() + timedelta(days=3)))
    world.db.commit()
    account = _detail(client, world, "SA", "PA").json()["account"]
    assert account["created_via"] == "INVITED" and account["invitation_sent_at"] is not None

    world.orgs["A"].workspace_type = "EVALUATION"
    world.db.commit()
    assert _detail(client, world, "SA", "TA").json()["account"]["created_via"] == "TRIAL_SIGNUP"


def test_security_activity(client, world):
    from app.modules.auth.models import AuthAuditEvent

    user = world.users["TA"]
    now = datetime.utcnow()
    world.db.add_all([
        AuthAuditEvent(occurred_at=now - timedelta(hours=2), event_type="LOGIN_FAILED", user_id=user.id,
                       reason="BAD_PASSWORD", client_address="198.51.100.4"),
        AuthAuditEvent(occurred_at=now - timedelta(days=40), event_type="LOGIN_FAILED", user_id=user.id),
        AuthAuditEvent(occurred_at=now - timedelta(hours=1), event_type="LOGIN_SUCCESS", user_id=user.id,
                       client_address="198.51.100.4", user_agent="Mozilla/5.0 Test"),
    ])
    world.db.commit()
    security = _detail(client, world, "SA", "TA").json()["security"]
    assert security["mfa_required"] is True
    assert security["last_login_ip"] == "198.51.100.4"
    assert security["last_login_user_agent"] == "Mozilla/5.0 Test"
    assert security["failed_logins_30d"] == 1
    assert security["last_login_at"].endswith("Z") or security["last_login_at"].endswith("+00:00")


def test_no_secret_is_ever_returned(client, world):
    from app.modules.auth.models import MfaCredential

    world.db.add(MfaCredential(user_id=world.users["TA"].id, secret_encrypted="CIPHERTEXT-SENTINEL",
                               confirmed_at=datetime.utcnow()))
    world.db.commit()
    resp = _detail(client, world, "SA", "TA")
    blob = json.dumps(resp.json())
    for forbidden in ("hashed_password", "secret", "CIPHERTEXT-SENTINEL", "token_hash", "recovery",
                      world.users["TA"].hashed_password):
        assert forbidden not in blob, forbidden
    assert resp.json()["security"]["mfa_confirmed_at"] is not None


def test_each_view_is_recorded_as_a_privileged_read(client, world):
    from app.modules.security.models import SecurityEvent

    before = world.db.query(SecurityEvent).filter(SecurityEvent.event_type == "PRIVILEGED_READ").count()
    assert _detail(client, world, "SA", "TA").status_code == 200
    rows = (world.db.query(SecurityEvent).filter(SecurityEvent.event_type == "PRIVILEGED_READ")
            .order_by(SecurityEvent.id.desc()).all())
    assert len(rows) == before + 1
    assert rows[0].actor_user_id == world.users["SA"].id
    assert rows[0].target_id == f"user:{world.users['TA'].id}" and rows[0].reason_code == "PLATFORM_USER_DETAIL"


def test_list_returns_utc_times_and_new_flags(client, world):
    resp = client.get("/api/super-admin/users", headers=world.headers("SA"), params={"limit": 200})
    assert resp.status_code == 200
    row = next(u for u in resp.json()["users"] if u["id"] == world.users["TA"].id)
    assert row["created_at"].endswith("Z") or row["created_at"].endswith("+00:00")
    assert "is_verified" in row and "workspace_type" in row and "updated_at" in row

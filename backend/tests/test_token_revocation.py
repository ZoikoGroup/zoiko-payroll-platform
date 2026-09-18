"""
tests/test_token_revocation.py
--------------------------------
Coverage for JWT revocation on logout (platform infrastructure fix plan,
Tier 3): the jti claim, auth/service.py's revoke_token/is_token_revoked/
logout_user/run_revoked_token_cleanup_sweep, and get_current_user's
revocation check.
"""

from datetime import datetime, timedelta

import pytest

from app.core.exceptions import UnauthorizedException
from app.core.security import create_access_token, create_refresh_token, decode_access_token
from app.modules.auth import service
from app.modules.auth.models import RevokedToken, User, UserRole


@pytest.fixture()
def user(db):
    u = User(
        email="revoke-test@zoiko.dev",
        hashed_password="x",
        role=UserRole.PAYROLL_ADMIN,
        organization_id=None,
        first_name="Revoke",
        last_name="Test",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _payload_for(user):
    return {"sub": user.email, "role": user.role.value, "user_id": user.id, "organization_id": user.organization_id}


def test_issued_tokens_carry_a_unique_jti(user):
    token_a = create_access_token(_payload_for(user))
    token_b = create_access_token(_payload_for(user))
    jti_a = decode_access_token(token_a)["jti"]
    jti_b = decode_access_token(token_b)["jti"]
    assert jti_a and jti_b
    assert jti_a != jti_b


def test_revoke_token_then_is_token_revoked(db):
    service.revoke_token(db, "some-jti-value", datetime.utcnow() + timedelta(hours=1))
    assert service.is_token_revoked(db, "some-jti-value") is True
    assert service.is_token_revoked(db, "a-different-jti") is False


def test_is_token_revoked_returns_false_for_missing_jti(db):
    assert service.is_token_revoked(db, None) is False
    assert service.is_token_revoked(db, "") is False


def test_revoke_token_is_idempotent(db):
    expires = datetime.utcnow() + timedelta(hours=1)
    service.revoke_token(db, "dup-jti", expires)
    service.revoke_token(db, "dup-jti", expires)
    assert db.query(RevokedToken).filter(RevokedToken.jti == "dup-jti").count() == 1


def test_logout_user_revokes_the_access_token(db, user):
    token = create_access_token(_payload_for(user))
    jti = decode_access_token(token)["jti"]

    service.logout_user(db, token)

    assert service.is_token_revoked(db, jti) is True


def test_logout_user_also_revokes_a_supplied_refresh_token(db, user):
    access = create_access_token(_payload_for(user))
    refresh = create_refresh_token(_payload_for(user))

    service.logout_user(db, access, refresh_token=refresh)

    from app.core.security import decode_refresh_token
    assert service.is_token_revoked(db, decode_access_token(access)["jti"]) is True
    assert service.is_token_revoked(db, decode_refresh_token(refresh)["jti"]) is True


def test_get_current_user_rejects_a_revoked_token(db, user):
    from app.core.dependencies import get_current_user

    token = create_access_token(_payload_for(user))
    service.logout_user(db, token)

    with pytest.raises(UnauthorizedException):
        get_current_user(token=token, db=db)


def test_get_current_user_still_accepts_a_non_revoked_token(db, user):
    from app.core.dependencies import get_current_user

    token = create_access_token(_payload_for(user))
    result = get_current_user(token=token, db=db)
    assert result.id == user.id


def test_cleanup_sweep_deletes_only_expired_revocations(db):
    service.revoke_token(db, "expired-jti", datetime.utcnow() - timedelta(hours=1))
    service.revoke_token(db, "still-valid-jti", datetime.utcnow() + timedelta(hours=1))

    result = service.run_revoked_token_cleanup_sweep(db)

    assert result["deleted"] == 1
    assert service.is_token_revoked(db, "expired-jti") is False
    assert service.is_token_revoked(db, "still-valid-jti") is True

"""
tests/test_invite_payroll_admin_resilience.py
---------------------------------------------
Regression: Org Admin > Team > "Invite Payroll Admin" returned HTTP 500
("Something went wrong on the server"). invite_user flushed the new User
and then ran the invite-email work (token supersede/insert + audit-row
claim, which commits or rolls back on its own) in the SAME transaction,
inside a try/except that only logged. Two ways that became a 500:

  A. a DB error in the invite work left the session needing a rollback,
     so the final db.commit() raised PendingRollbackError;
  B. the audit-row claim's own IntegrityError branch called db.rollback(),
     discarding the just-flushed User, so db.refresh(user) raised.

The account must now be created even when the invite email work fails.
"""

import pytest
from pydantic import ValidationError

from app.core.exceptions import AlreadyExistsException
from app.modules.auth import service
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import UserCreateRequest


@pytest.fixture()
def inviter(db, organization):
    actor = User(
        email="owner@example.com", hashed_password="x" * 60, role=UserRole.ORG_ADMIN,
        organization_id=organization.id, first_name="Sarah", last_name="Jenkins",
        is_active=True, is_verified=True,
    )
    db.add(actor)
    db.commit()
    db.refresh(actor)
    return actor


@pytest.fixture()
def no_real_send(monkeypatch):
    monkeypatch.setattr(service, "_send_invite_email", lambda *a, **k: True)


def _data(email="new.payroll@example.com", phone=""):
    return UserCreateRequest(
        email=email, first_name="Alex", last_name="Doe",
        role=UserRole.PAYROLL_ADMIN, phone=phone, send_invite=True,
    )


def test_invite_survives_db_error_in_invite_email_work(db, inviter, no_real_send, monkeypatch):
    def broken_issue_token(db, *a, **k):
        # A failed flush leaves the session needing a rollback — the same
        # state an aborted Postgres transaction produces.
        db.add(User(email=None, hashed_password=None, role=UserRole.EMPLOYEE))
        db.flush()

    monkeypatch.setattr(service, "_issue_action_token", broken_issue_token)

    user = service.invite_user(db, inviter, _data())

    assert user.id is not None
    assert db.query(User).filter_by(email="new.payroll@example.com").count() == 1


def test_invite_survives_audit_claim_rollback(db, inviter, no_real_send, monkeypatch):
    def claim_lost_race(db, **kw):
        # Mirrors _claim_audit_row's own IntegrityError branch.
        db.rollback()
        return None

    monkeypatch.setattr(service, "_claim_audit_row", claim_lost_race)

    user = service.invite_user(db, inviter, _data(email="race@example.com"))

    assert user.email == "race@example.com"
    assert db.query(User).filter_by(email="race@example.com").count() == 1


def test_invite_happy_path_still_sends(db, inviter, monkeypatch):
    sent = []
    monkeypatch.setattr(service, "_send_invite_email", lambda db, u, a, link, **k: sent.append(u.email) or True)

    user = service.invite_user(db, inviter, _data(email="ok@example.com"))

    assert user.is_verified is False
    assert sent == ["ok@example.com"]


def test_invite_duplicate_email_is_case_insensitive(db, inviter, no_real_send):
    service.invite_user(db, inviter, _data(email="dup@example.com"))
    with pytest.raises(AlreadyExistsException):
        service.invite_user(db, inviter, _data(email="DUP@example.com"))


def test_invite_phone_longer_than_column_is_rejected_by_validation():
    with pytest.raises(ValidationError):
        _data(phone="9" * 41)
    assert _data(phone="9" * 40).phone == "9" * 40

"""
tests/test_session_idle_timeout_field.py
----------------------------------------
QA bug "signed out automatically after 30-40 minutes": privileged sessions
are revoked after PRIVILEGED_REFRESH_IDLE_MINUTES without a refresh, but the
client had no way to know the deadline and so could not warn the user.
Every issued session now carries refresh_idle_timeout_seconds (privileged
roles) or None (no idle limit), on login and on refresh alike.
"""

from app.config import settings
from app.modules.auth import service
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import LoginResponse


def _user(db, organization, role, email):
    user = User(
        email=email, hashed_password="x" * 60, role=role, organization_id=organization.id,
        first_name="T", last_name="User", is_active=True, is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_privileged_session_reports_idle_timeout(db, organization):
    user = _user(db, organization, UserRole.ORG_ADMIN, "admin@example.com")
    session = service.issue_session(db, user)
    assert session["refresh_idle_timeout_seconds"] == settings.PRIVILEGED_REFRESH_IDLE_MINUTES * 60


def test_non_privileged_session_reports_no_idle_timeout(db, organization):
    user = _user(db, organization, UserRole.PAYROLL_ADMIN, "payroll@example.com")
    session = service.issue_session(db, user)
    assert session["refresh_idle_timeout_seconds"] is None


def test_refresh_keeps_reporting_idle_timeout(db, organization):
    user = _user(db, organization, UserRole.ORG_ADMIN, "admin2@example.com")
    import time

    # Privileged roles need an MFA sign-in on the session to be refreshable.
    first = service.issue_session(db, user, mfa_at=int(time.time()))
    rotated = service.refresh_user_token(db, first["refresh_token"])
    assert rotated["refresh_idle_timeout_seconds"] == settings.PRIVILEGED_REFRESH_IDLE_MINUTES * 60


def test_login_response_schema_exposes_field():
    assert "refresh_idle_timeout_seconds" in LoginResponse.model_fields

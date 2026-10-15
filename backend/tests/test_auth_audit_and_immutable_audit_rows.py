"""G5 F-5 / F-6 (draft for Security review). TEST-ONLY data; app modules imported lazily."""
import hashlib

import pytest


def _user(db, email="f5user@zoikotest.example.com", active=True, org_id=None, password="Corr3ct-Horse!"):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password=hash_password(password), role=UserRole.ORG_ADMIN, organization_id=org_id,
             first_name="T", last_name="User", is_active=active)
    db.add(u)
    db.commit()
    return u


def _events(db):
    from app.modules.auth.models import AuthAuditEvent

    return [(e.event_type, e.user_id, e.email_sha256, e.reason) for e in db.query(AuthAuditEvent).order_by(AuthAuditEvent.id)]


def test_each_auth_event_writes_exactly_one_row_and_never_a_secret(db, organization):
    from app.core.exceptions import UnauthorizedException
    from app.modules.auth import service
    from app.modules.auth.models import AuthAuditEvent

    u = _user(db, org_id=organization.id)
    out = service.login_user(db, u.email, "Corr3ct-Horse!")
    with pytest.raises(UnauthorizedException):
        service.login_user(db, u.email, "wrong")
    with pytest.raises(UnauthorizedException):
        service.login_user(db, "Nobody@Elsewhere.example.com", "x")
    service.refresh_user_token(db, out["refresh_token"])
    service.logout_user(db, out["access_token"], out["refresh_token"], user=u)
    assert _events(db) == [
        ("LOGIN_SUCCESS", u.id, None, None),
        ("LOGIN_FAILED", u.id, None, "BAD_PASSWORD"),
        ("LOGIN_FAILED", None, hashlib.sha256(b"nobody@elsewhere.example.com").hexdigest(), "UNKNOWN_EMAIL"),
        ("REFRESH", u.id, None, None),
        ("LOGOUT", u.id, None, None),
    ]
    blob = " ".join(str(v) for e in db.query(AuthAuditEvent) for v in e.__dict__.values())
    for secret in ("Corr3ct-Horse!", "wrong", out["access_token"], out["refresh_token"], "Nobody@Elsewhere"):
        assert secret not in blob


def test_inactive_account_is_recorded(db):
    from app.core.exceptions import UnauthorizedException
    from app.modules.auth import service

    u = _user(db, email="inactive@zoikotest.example.com", active=False)
    with pytest.raises(UnauthorizedException):
        service.login_user(db, u.email, "Corr3ct-Horse!")
    assert _events(db) == [("ACCOUNT_INACTIVE", u.id, None, "ACCOUNT_DEACTIVATED")]


def test_login_is_refused_when_the_audit_row_cannot_be_written(db, monkeypatch):
    from sqlalchemy.orm import Session

    from app.core.exceptions import ZoikoException
    from app.modules.auth import service

    u = _user(db, email="audit-down@zoikotest.example.com")
    real_commit = Session.commit

    def failing(self):
        if any(type(o).__name__ == "AuthAuditEvent" for o in self.new):
            raise RuntimeError("audit store down")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", failing)
    with pytest.raises(ZoikoException) as exc:
        service.login_user(db, u.email, "Corr3ct-Horse!")
    assert exc.value.status_code == 503


@pytest.mark.parametrize("table", ["payroll_tax_configuration_audit", "assisted_access_audit_events",
                                   "payroll_personal_data_access_events", "auth_audit_events"])
def test_audit_tables_reject_update_and_delete_but_accept_insert(db, table):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.modules.auth import audit as auth_audit

    names = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert {f"{table}_no_update", f"{table}_no_delete"} <= names
    if table == "auth_audit_events":
        auth_audit.record(db, auth_audit.LOGOUT)                                  # INSERT works
        for stmt in ("UPDATE auth_audit_events SET reason = 'x'", "DELETE FROM auth_audit_events"):
            with pytest.raises((IntegrityError, OperationalError), match="append-only"):
                db.execute(text(stmt))
            db.rollback()
        assert db.execute(text("SELECT count(*) FROM auth_audit_events")).scalar() == 1


def test_the_purge_scope_allows_delete_only_inside_it(db):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.core.audit_immutability import audit_purge_scope
    from app.modules.auth import audit as auth_audit

    auth_audit.record(db, auth_audit.LOGOUT)
    with audit_purge_scope(db, "TEST purge"):
        with pytest.raises((IntegrityError, OperationalError), match="append-only"):
            db.execute(text("UPDATE auth_audit_events SET reason = 'x'"))           # UPDATE never allowed
    db.rollback()
    with audit_purge_scope(db, "TEST purge"):
        db.execute(text("DELETE FROM auth_audit_events"))
    db.commit()
    assert db.execute(text("SELECT count(*) FROM auth_audit_events")).scalar() == 0
    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        auth_audit.record(db, auth_audit.LOGOUT)
        db.execute(text("DELETE FROM auth_audit_events"))                           # scope closed again

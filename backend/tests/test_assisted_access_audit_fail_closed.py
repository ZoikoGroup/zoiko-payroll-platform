"""G5 F-4 (draft for Security review): no assisted action without an audit record.
TEST-ONLY data. App modules are imported inside the tests (collection-order hazard)."""
import pytest

from tests.test_assisted_access import people  # noqa: F401  (fixture)


def _request(path="/api/payroll/employees", method="GET", query=""):
    from starlette.requests import Request

    return Request({"type": "http", "method": method, "path": path, "query_string": query.encode(), "headers": [],
                    "server": ("test", 80), "scheme": "http", "root_path": ""})


def _active_token(db, people):
    from app.modules.assisted_access import service as svc

    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="TEST: F-4")
    svc.approve_assisted_access(db, s, approver=people.admin, decision_reason="TEST ok")
    s, token = svc.activate_assisted_access(db, s, requested_by=people.sa1)
    return s, token


def _rows(db, session_id, event_type):
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    return db.query(AssistedAccessAuditEvent).filter(AssistedAccessAuditEvent.assisted_access_session_id == session_id,
                                                     AssistedAccessAuditEvent.event_type == event_type).all()


def test_a_legacy_assisted_token_is_refused_before_anything_runs_or_is_recorded(db, people):
    """ZP-PRIV Part D: the assisted-access token path is retired. A token minted
    by the legacy flow is refused at the principal resolver (401), so no
    endpoint runs and no ORG_API_CALL_STARTED intent row is written. The
    fail-closed intent audit itself now guards temporary support logins
    (tests/privacy/test_support_access.py::test_support_intent_audit_fails_closed)."""
    from app.core.dependencies import get_current_org_scoped_principal
    from app.core.exceptions import UnauthorizedException

    s, token = _active_token(db, people)
    req = _request(query="token=secret&x=1")
    with pytest.raises(UnauthorizedException) as exc:
        get_current_org_scoped_principal(req, token=token, db=db)
    assert "Support Access" in exc.value.detail
    assert _rows(db, s.id, "ORG_API_CALL_STARTED") == []


def test_normal_tokens_write_no_assisted_audit_rows(db, people):
    from app.core.dependencies import get_current_org_scoped_principal
    from app.core.security import create_access_token
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    # A payroll admin (MFA optional) with a normal access token.
    token = create_access_token({"sub": people.payroll.email, "user_id": people.payroll.id,
                                 "role": people.payroll.role.value, "organization_id": people.org.id})
    before = db.query(AssistedAccessAuditEvent).count()
    user = get_current_org_scoped_principal(_request(), token=token, db=db)
    assert user.id == people.payroll.id and db.query(AssistedAccessAuditEvent).count() == before

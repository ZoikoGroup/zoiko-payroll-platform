"""G5 F-4 (draft for Security review): no assisted action without an audit record.
TEST-ONLY data. App modules are imported inside the tests (collection-order hazard)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

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


def test_assisted_request_writes_a_started_row_before_the_endpoint_once_per_request(db, people):
    from app.core.dependencies import get_current_org_scoped_principal

    s, token = _active_token(db, people)
    req = _request(query="token=secret&x=1")
    principal = get_current_org_scoped_principal(req, token=token, db=db)
    assert principal.organization_id == people.org.id
    started = _rows(db, s.id, "ORG_API_CALL_STARTED")
    assert len(started) == 1 and started[0].method == "GET" and started[0].path == "/api/payroll/employees"
    assert "secret" not in str(started[0].payload)
    assert req.state.assisted_intent_id == started[0].id
    get_current_org_scoped_principal(req, token=token, db=db)                 # same request again: no duplicate
    assert len(_rows(db, s.id, "ORG_API_CALL_STARTED")) == 1


def test_a_failed_intent_write_refuses_the_request_with_503(db, people, monkeypatch):
    from sqlalchemy.orm import Session

    from app.core.dependencies import get_current_org_scoped_principal
    from app.core.exceptions import ZoikoException

    s, token = _active_token(db, people)
    real_commit = Session.commit

    def failing_commit(self):
        if any(getattr(o, "event_type", None) == "ORG_API_CALL_STARTED" for o in self.new):
            raise RuntimeError("audit store down")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    ran = []
    with pytest.raises(ZoikoException) as exc:
        get_current_org_scoped_principal(_request(method="POST"), token=token, db=db)
        ran.append("endpoint")                                                # never reached
    monkeypatch.setattr(Session, "commit", real_commit)
    assert exc.value.status_code == 503 and ran == []
    assert _rows(db, s.id, "ORG_API_CALL_STARTED") == []


def test_completion_row_carries_the_intent_id_and_gaps_raise_a_security_alert(db, people, monkeypatch):
    from app.core.dependencies import get_current_org_scoped_principal
    from app.modules.assisted_access import audit, service as svc
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    s, token = _active_token(db, people)
    done = _request(path="/api/payroll/runs")
    get_current_org_scoped_principal(done, token=token, db=db)
    missing = _request(path="/api/payroll/employees/7", method="DELETE")
    get_current_org_scoped_principal(missing, token=token, db=db)

    class _NoClose:                                     # the middleware's own session, bound to the test DB
        def __init__(self):
            self._db = db

        def __getattr__(self, name):
            return getattr(self._db, name)

        def close(self):
            pass

    monkeypatch.setattr("app.database.SessionLocal", _NoClose)
    done.scope["headers"] = [(b"authorization", f"Bearer {token}".encode())]
    audit.record_request_if_assisted(done, 200)
    completion = _rows(db, s.id, "ORG_API_CALL")
    assert len(completion) == 1 and completion[0].payload["intent_id"] == done.state.assisted_intent_id

    assert svc.assisted_audit_gap_alerts(db) == []                            # inside the grace period
    old = datetime.utcnow() - timedelta(minutes=30)
    for e in db.query(AssistedAccessAuditEvent).filter(AssistedAccessAuditEvent.assisted_access_session_id == s.id):
        e.recorded_at = old
    db.commit()
    gaps = svc.assisted_audit_gap_alerts(db)
    assert gaps == [{"session_id": s.id, "unmatched_starts": 1, "first_event_id": missing.state.assisted_intent_id}]


def test_normal_tokens_write_no_assisted_audit_rows(db, people):
    from app.core.dependencies import get_current_org_scoped_principal
    from app.core.security import create_access_token
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    token = create_access_token({"sub": people.admin.email, "user_id": people.admin.id, "role": people.admin.role.value,
                                 "organization_id": people.org.id})
    before = db.query(AssistedAccessAuditEvent).count()
    user = get_current_org_scoped_principal(_request(), token=token, db=db)
    assert user.id == people.admin.id and db.query(AssistedAccessAuditEvent).count() == before

"""
tests/test_assist.py
--------------------
Integration tests for Zoiko Payroll Assist (backend).

Runs against a throwaway SQLite database. Covers the notice gate, session
lifecycle, message → response flow (SAFE / REFUSED), A3 action preview →
confirm → receipt, handoffs, drafts, feedback, idempotency, KB management,
the SSE stream and the audit/retention admin endpoints.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="assist_test_")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.sqlite3')}"
os.environ["ENVIRONMENT"] = "development"
# Force the deterministic engine so tests are hermetic (no external LLM/API).
os.environ["ASSIST_MODEL_PROVIDER"] = ""
os.environ["ASSIST_MODEL_BASE_URL"] = ""
os.environ["ASSIST_MODEL_API_KEY"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import PayrollRun  # noqa: E402

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()
_org = Organization(organization_name="Test Org", organization_code="TEST", is_active=True)
_db.add(_org)
_db.commit()

_db.add(
    User(
        email="assist-test@example.com",
        hashed_password=hash_password("strong-password"),
        role=UserRole.ORG_ADMIN,
        first_name="Assist",
        last_name="Tester",
        organization_id=_org.id,
        is_active=True,
    )
)
_db.commit()

_db.add(
    PayrollRun(
        organization_id=_org.id,
        run_code="T-2026-01",
        period_label="Jan 1-31, 2026",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 5),
        status="Draft",
        employee_count=0,
    )
)
_db.commit()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def headers(client):
    r = client.post("/api/auth/login", json={"email": "assist-test@example.com", "password": "strong-password"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ack_notice(client, headers):
    """Acknowledge the required policy notice for the shared test user."""
    notice = client.get("/api/assist/notices/current", headers=headers).json()
    r = client.post(f"/api/assist/notices/{notice['notice_version']}/acknowledge", headers=headers)
    assert r.status_code == 200, r.text
    return notice


@pytest.fixture(scope="module")
def session_id(client, headers, ack_notice):
    r = client.post(
        "/api/assist/sessions",
        headers=headers,
        json={"title": "pytest session", "context": {"object": {"type": "PAYROLL_RUN", "id": str(_org.id), "version": 1}}},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_status(client, headers):
    r = client.get("/api/assist/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["knowledge_available"] is True


def test_capabilities_and_suggestions_seeded(client, headers):
    caps = client.get("/api/assist/capabilities", headers=headers).json()["capabilities"]
    assert len(caps) >= 6
    sugg = client.get("/api/assist/suggestions", headers=headers).json()["suggestions"]
    assert len(sugg) >= 5


def test_notice_gate_blocks_until_acknowledged(client):
    """A fresh user is blocked from messaging until the notice is acked."""
    from app.modules.auth.models import User as _User
    from app.modules.auth.models import UserRole as _Role

    _db.add(
        _User(
            email="gate-check@example.com",
            hashed_password=hash_password("strong-password"),
            role=_Role.PAYROLL_ADMIN,
            first_name="Gate",
            last_name="Check",
            organization_id=_org.id,
            is_active=True,
        )
    )
    _db.commit()
    login = client.post("/api/auth/login", json={"email": "gate-check@example.com", "password": "strong-password"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    s = client.post("/api/assist/sessions", headers=h, json={"title": "gate"})
    sid = s.json()["id"]

    notice = client.get("/api/assist/notices/current", headers=h).json()
    assert notice["required"] is True and notice["acknowledged"] is False

    r = client.post(
        f"/api/assist/sessions/{sid}/messages",
        headers=h,
        json={"content": {"type": "TEXT", "text": "What is the run status?"}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "NOTICE_REQUIRED"

    ack = client.post(f"/api/assist/notices/{notice['notice_version']}/acknowledge", headers=h)
    assert ack.status_code == 200 and ack.json()["acknowledged"] is True
    assert client.get("/api/assist/notices/current", headers=h).json()["acknowledged"] is True


def test_session_lifecycle(client, headers):
    r = client.post("/api/assist/sessions", headers=headers, json={"title": "lc"})
    sid = r.json()["id"]
    assert client.get(f"/api/assist/sessions/{sid}", headers=headers).status_code == 200
    up = client.patch(f"/api/assist/sessions/{sid}", headers=headers, json={"title": "renamed"})
    assert up.json()["title"] == "renamed"
    arc = client.post(f"/api/assist/sessions/{sid}/archive", headers=headers)
    assert arc.json()["status"] == "ARCHIVED"


def test_message_flow_safe(client, headers, session_id):
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "What exceptions exist on this run?"}},
    )
    assert r.status_code == 200, r.text
    resp = client.get(f"/api/assist/responses/{r.json()['response_id']}", headers=headers).json()
    assert resp["state"] == "COMPLETED"
    assert resp["safety_state"] == "SAFE"
    assert any(b["block_type"] == "text" for b in resp["blocks"])
    assert resp["sources"]


def test_kb_question_no_payroll_message(client, headers, session_id):
    """An unmatched knowledge question must not report a missing payroll run."""
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "Explain the quantum telemetry of lunar regolith sampling rigs."}},
    )
    assert r.status_code == 200, r.text
    resp = client.get(f"/api/assist/responses/{r.json()['response_id']}", headers=headers).json()
    assert resp["safety_state"] == "SAFE"
    text = next((b["content"] for b in resp["blocks"] if b["block_type"] == "text"), "")
    assert "couldn't find a payroll run" not in text
    assert "No matching knowledge article was found" in text


def test_missing_run_guidance_message():
    """Run-aware tool failure must guide the user to create/open a run."""
    from app.modules.assist import gateway

    answer = gateway.deterministic_answer(
        "review.run_readiness", "Is the run ready?",
        {"found": False, "reason": "No visible payroll run."}, [],
    )
    assert "couldn't find a payroll run" in answer["answer"]
    assert "Create or open a payroll run first" in answer["answer"]


def test_kb_fallback_unit():
    from app.modules.assist import gateway

    answer = gateway.deterministic_answer("explain.field", "Explain X", None, [])
    assert "No matching knowledge article was found" in answer["answer"]
    assert "couldn't find a payroll run" not in answer["answer"]


def test_prohibited_intent_refused(client, headers, session_id):
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "Approve the payroll run now."}},
    )
    assert r.status_code == 200
    resp = client.get(f"/api/assist/responses/{r.json()['response_id']}", headers=headers).json()
    assert resp["safety_state"] == "REFUSED"


def test_action_preview_lifecycle(client, headers):
    # Materialize exceptions via a readiness question on the fresh run.
    s = client.post("/api/assist/sessions", headers=headers, json={"context": {"object": {"type": "PAYROLL_RUN", "id": str(_org.id)}}})
    sid = s.json()["id"]
    ack = client.get("/api/assist/notices/current", headers=headers).json()
    client.post(f"/api/assist/notices/{ack['notice_version']}/acknowledge", headers=headers)
    client.post(
        f"/api/assist/sessions/{sid}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "Is the run ready?"}},
    )

    p = client.post(
        "/api/assist/action-previews",
        headers=headers,
        json={"action_id": "payroll.assignException", "target": {"type": "PAYROLL_EXCEPTION", "id": str(_org.id)}, "arguments": {"assignee_role": "PAYROLL_ADMIN"}},
    )
    assert p.status_code == 200, p.text
    preview_id = p.json()["preview_id"]
    assert p.json()["state"] == "READY_FOR_CONFIRMATION"

    c = client.post(f"/api/assist/action-previews/{preview_id}/confirm", headers=headers, json={})
    assert c.status_code == 200, c.text
    receipt_id = c.json()["receipt_id"]
    assert c.json()["outcome"] == "SUCCEEDED"
    rec = client.get(f"/api/assist/action-receipts/{receipt_id}", headers=headers)
    assert rec.status_code == 200


def test_handoff_preview_lifecycle(client, headers):
    p = client.post(
        "/api/assist/handoff-previews",
        headers=headers,
        json={"destination": "PAYROLL_SUPPORT", "reason_code": "USER_REQUESTED", "summary": "Needs help."},
    )
    assert p.status_code == 200, p.text
    h = client.post(f"/api/assist/handoff-previews/{p.json()['preview_id']}/confirm", headers=headers)
    assert h.status_code == 200, h.text
    assert h.json()["state"] == "CREATED"
    assert client.get(f"/api/assist/handoffs/{h.json()['handoff_id']}", headers=headers).status_code == 200


def test_drafts_crud(client, headers):
    d = client.post("/api/assist/drafts", headers=headers, json={"draft_type": "note", "content": "v1"})
    did = d.json()["id"]
    listed = client.get("/api/assist/drafts", headers=headers)
    assert listed.status_code == 200
    assert any(x["id"] == did for x in listed.json()["drafts"])
    up = client.patch(f"/api/assist/drafts/{did}", headers=headers, json={"content": "v2"})
    assert up.json()["revision"] == 2
    assert client.delete(f"/api/assist/drafts/{did}", headers=headers).status_code == 200


def test_auto_action_preview_block(client, headers):
    """A3 intent in a session bound to a run yields an 'action' block that can be confirmed."""
    s = client.post(
        "/api/assist/sessions",
        headers=headers,
        json={"context": {"object": {"type": "PAYROLL_RUN", "id": str(_org.id), "version": 1}}},
    )
    sid = s.json()["id"]
    ack = client.get("/api/assist/notices/current", headers=headers).json()
    client.post(f"/api/assist/notices/{ack['notice_version']}/acknowledge", headers=headers)

    r = client.post(
        f"/api/assist/sessions/{sid}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "Add a note to this run for the reviewer."}},
    )
    assert r.status_code == 200, r.text
    resp = client.get(f"/api/assist/responses/{r.json()['response_id']}", headers=headers).json()
    action = next((b for b in resp["blocks"] if b["block_type"] == "action"), None)
    assert action is not None, "expected an action block"
    assert action["data"]["action_id"] == "payroll.addExceptionNote"
    assert action["data"]["preview_id"]
    assert action["data"]["state"] == "READY_FOR_CONFIRMATION"

    c = client.post(
        f"/api/assist/action-previews/{action['data']['preview_id']}/confirm",
        headers=headers,
        json={},
    )
    assert c.status_code == 200, c.text
    assert c.json()["outcome"] == "SUCCEEDED"


def test_idempotency(client, headers, session_id):
    payload = {"content": {"type": "TEXT", "text": "What is the run status?"}}
    h = {**headers, "Idempotency-Key": "pytest-idem-1"}
    a = client.post(f"/api/assist/sessions/{session_id}/messages", headers=h, json=payload)
    b = client.post(f"/api/assist/sessions/{session_id}/messages", headers=h, json=payload)
    assert a.json()["response_id"] == b.json()["response_id"]


def test_feedback(client, headers, session_id):
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "What exceptions exist on this run?"}},
    )
    resp_id = r.json()["response_id"]
    fb = client.post(f"/api/assist/responses/{resp_id}/feedback", headers=headers, json={"rating": "helpful"})
    assert fb.status_code == 200
    assert client.get(f"/api/assist/responses/{resp_id}/audit-reference", headers=headers).status_code == 200


def test_sse_stream(client, headers, session_id):
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "What exceptions exist on this run?"}},
    )
    resp_id = r.json()["response_id"]
    sse = client.get(f"/api/assist/responses/{resp_id}/events/stream", headers=headers)
    assert sse.status_code == 200
    assert "data:" in sse.text
    assert "assistant_response_completed" in sse.text


def test_audit_and_retention_admin(client, headers):
    audit = client.get("/api/assist/admin/audit-events", headers=headers)
    assert audit.status_code == 200 and audit.json()["total"] >= 1
    admins = client.get("/api/assist/admin/sessions", headers=headers)
    assert admins.status_code == 200 and admins.json()["total"] >= 1
    ret = client.get("/api/assist/admin/retention", headers=headers)
    assert ret.status_code == 200
    assert ret.json()["total_sessions"] >= 1


def test_model_executions_logged(client, headers, session_id):
    r = client.post(
        f"/api/assist/sessions/{session_id}/messages",
        headers=headers,
        json={"content": {"type": "TEXT", "text": "What is the run status?"}},
    )
    response_id = r.json()["response_id"]
    rows = client.get("/api/assist/admin/model-executions", headers=headers).json()
    assert rows["total"] >= 1
    match = next((x for x in rows["executions"] if x["response_id"] == response_id), None)
    assert match is not None
    assert match["provider"] == "deterministic"
    assert match["status"] == "ok"
    assert match["latency_ms"] is not None and match["latency_ms"] >= 0


def test_retention_cleanup_archives_expired(client, headers):
    expired = client.post(
        "/api/assist/sessions",
        headers=headers,
        json={"title": "expired session"},
    ).json()
    sid = expired["id"]
    from app.modules.assist.models import AssistSession

    s = _db.get(AssistSession, sid)
    s.expires_at = date(2020, 1, 1)
    _db.commit()

    before = client.get("/api/assist/admin/retention", headers=headers).json()
    assert before["expired_sessions"] >= 1

    run = client.post("/api/assist/admin/retention/run", headers=headers)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["archived"] >= 1
    assert body["expired_remaining"] == 0

    after = client.get(f"/api/assist/sessions/{sid}", headers=headers).json()
    assert after["status"] == "ARCHIVED"

    audit = client.get(
        "/api/assist/admin/audit-events",
        headers=headers,
        params={"session_id": sid, "limit": 100},
    ).json()
    assert any(e["event_type"] == "assist.session_expired_by_retention" for e in audit["events"])


def test_kb_crud(client, headers):
    created = client.post(
        "/api/assist/knowledge/items",
        headers=headers,
        json={"title": "pytest kb", "body": "Body.", "content_type": "HOW_TO", "authority": "TIER_4_TENANT"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]
    assert created.json()["state"] == "DRAFT"
    listed = client.get("/api/assist/knowledge/items", headers=headers).json()
    assert any(i["id"] == item_id for i in listed)
    assert client.patch(f"/api/assist/knowledge/items/{item_id}", headers=headers, json={"title": "renamed kb"}).json()["title"] == "renamed kb"

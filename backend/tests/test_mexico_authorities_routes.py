"""Mexico Phase 8 — the authority routes end to end (flag on, SYNTHETIC world)
and the Super Admin read-only overview with the blocks."""

from tests import _mx_authority_helpers as ah
from tests._mx_employer_helpers import ORG_BASE, SUPER_ADMIN, http, principal


def test_org_authority_flow_through_the_api(db, monkeypatch):
    w = ah.committed_world(db, monkeypatch, code="MXAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as a:              # one principal per context (global override)
        summary = a.get(f"{ORG_BASE}/authorities/summary").json()
        assert summary["registrations"][0]["registroPatronal"] and summary["movements"] == {}
        assert {x["code"] for x in summary["blocks"]} >= {"MX_IDSE_SUA_SIPARE_LAYOUTS", "DUE_DATE_UNSOURCED",
                                                          "MX_FILING_CALENDAR_EMPTY", "MX_AUTHORITY_TRANSMISSION"}
        assert a.post(f"{ORG_BASE}/authorities/accrue").json()["sourcesAdded"] > 0
        liabs = a.get(f"{ORG_BASE}/authorities/liabilities").json()
        assert {l["authority"] for l in liabs} == {"SAT_ISR", "IMSS", "IMSS_RCV", "INFONAVIT", "ISN"}   # A18
        assert all(l["dueState"] == "DUE_DATE_UNSOURCED" for l in liabs)
        gen = a.post(f"{ORG_BASE}/authorities/movements/generate").json()
        (mv,) = gen["created"]
        assert "12345678901" not in str(a.get(f"{ORG_BASE}/authorities/movements").json())
        exp = a.post(f"{ORG_BASE}/authorities/movements/export", json={})
        assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
        assert exp.headers["cache-control"].split(",")[0].strip() == "no-store"   # ZP-PRIV appends ", private"
        assert "attachment" in exp.headers["content-disposition"]
        assert "NOT AN IMSS / IDSE FILE" in exp.text and "12345678901" in exp.text
        # UNKNOWN through the API: no retry before a status check, then the same key.
        assert a.post(f"{ORG_BASE}/authorities/movements/{mv['id']}/unknown", json={"note": "no acuse"}).status_code == 200
        refused = a.post(f"{ORG_BASE}/authorities/movements/{mv['id']}/confirm-retry", json={"reason": "x"})
        assert refused.status_code >= 400 and "MX_AUTHORITY_STATUS_CHECK_REQUIRED" in refused.text
        a.post(f"{ORG_BASE}/authorities/movements/{mv['id']}/status-check", json={"found": False})
        retried = a.post(f"{ORG_BASE}/authorities/movements/{mv['id']}/confirm-retry", json={"reason": "not in IDSE"})
        assert retried.json()["status"] == "PENDING" and retried.json()["idempotencyKey"] == mv["idempotencyKey"]
        bad = a.post(f"{ORG_BASE}/authorities/nonsense/1/unknown", json={})
        assert bad.status_code == 400
        # ISN return + four-eyes acceptance through two users.
        ret = a.post(f"{ORG_BASE}/authorities/isn-returns", json={"stateCode": "CDMX", "periodKey": "2026-06"}).json()
        assert ret["reconciliation"]["matches"]
        a.post(f"{ORG_BASE}/authorities/isn-returns/{ret['id']}/file", json={"reference": "SYN-CDMX"})
        same = a.post(f"{ORG_BASE}/authorities/isn-returns/{ret['id']}/outcome", json={"outcome": "ACCEPTED"})
        assert same.status_code >= 400 and "MX_FOUR_EYES_REQUIRED" in same.text
    with http(db, principal(w.org.id, w.users[1].id)) as b:                  # the second person
        ok = b.post(f"{ORG_BASE}/authorities/isn-returns/{ret['id']}/outcome", json={"outcome": "ACCEPTED"})
        assert ok.status_code == 200 and ok.json()["status"] == "ACCEPTED", ok.text
        status = b.get(f"{ORG_BASE}/runs/{w.run.id}/status").json()
        assert status["authorities"]["status"] == "IN_PROGRESS" and status["payroll"]["status"] == "Approved"


def test_super_admin_overview_is_read_only_and_names_the_blocks(db, monkeypatch):
    w = ah.committed_world(db, monkeypatch, code="MXSAO")
    with http(db, SUPER_ADMIN) as c:
        out = c.get(f"/api/super-admin/compliance/mexico/authorities?organization_id={w.org.id}").json()
    assert out["movements"] == {} and out["liabilities"] == {}
    assert {"MX_IDSE_SUA_SIPARE_LAYOUTS", "DUE_DATE_UNSOURCED", "MX_AUTHORITY_BANK_PAYMENT",
            "MX_WORK_RISK_REVIEW"} <= {b["code"] for b in out["blocks"]}

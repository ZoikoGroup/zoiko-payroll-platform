"""Mexico Phase 7 — the CFDI routes end to end (flag on, SYNTHETIC seams,
test-only mock PAC) and the Super Admin read-only overview, which reports
why production cannot generate (builder / signer / PAC)."""

from tests import _mx_cfdi_helpers as ch
from tests._mx_employer_helpers import ORG_BASE, SUPER_ADMIN, http, principal


def test_org_cfdi_flow_through_the_api(db, monkeypatch, tmp_path):
    w = ch.committed_world(db, monkeypatch, tmp_path)
    w.org.workspace_type = "EVALUATION"
    db.commit()
    ch.mock(monkeypatch, stamp=["timeout"])
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        view = c.get(f"{ORG_BASE}/runs/{w.run.id}/cfdi").json()
        assert view["ready"] is True and view["summary"]["status"] == "NOT_STARTED"
        gen = c.post(f"{ORG_BASE}/runs/{w.run.id}/cfdi/generate")
        assert gen.status_code == 200, gen.text[:300]
        doc_id = gen.json()["created"][0]["id"]
        c.post(f"{ORG_BASE}/cfdi/outbox/process")
        detail = c.get(f"{ORG_BASE}/cfdi/documents/{doc_id}").json()
        assert detail["status"] == "UNKNOWN" and detail["retry"]["providerConfig"] is False
        assert "xml" not in str(detail).lower().replace("xmlstorageref", "")
        refused = c.post(f"{ORG_BASE}/cfdi/documents/{doc_id}/confirm-retry", json={"reason": "x"})
        assert refused.status_code >= 400 and "MX_CFDI_STATUS_QUERY_REQUIRED" in refused.text
        assert c.post(f"{ORG_BASE}/cfdi/documents/{doc_id}/status-query").status_code == 200
        c.post(f"{ORG_BASE}/cfdi/outbox/process")
        ok = c.post(f"{ORG_BASE}/cfdi/documents/{doc_id}/confirm-retry", json={"reason": "PAC never received it"})
        assert ok.status_code == 200 and ok.json()["status"] == "SIGNED"
        c.post(f"{ORG_BASE}/cfdi/outbox/process")
        final = c.get(f"{ORG_BASE}/cfdi/documents/{doc_id}").json()
        assert final["status"] == "STAMPED"
        assert [o["idempotencyKey"] for o in final["outbox"] if o["action"] == "STAMP"] == [final["outbox"][0]["idempotencyKey"]] * 2
        assert "OPERATOR_RETRY_CONFIRMED" in [e["type"] for e in final["events"]]
        reasons = c.get(f"{ORG_BASE}/cfdi/cancellation-reasons").json()
        assert [r["code"] for r in reasons] == ["SYN1", "SYN2"]
        status = c.get(f"{ORG_BASE}/runs/{w.run.id}/status").json()
        assert status["cfdi"]["status"] == "STAMPED" and status["payroll"]["status"] == "Approved"


def test_super_admin_overview_is_read_only_and_names_the_blocks(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_builder as B

    w = ch.committed_world(db, monkeypatch, tmp_path)
    monkeypatch.setattr(B, "_BUILDER", B.SatBuilder())
    monkeypatch.setattr(B, "_SIGNER", B.GcpSmSigner())
    with http(db, SUPER_ADMIN) as c:
        out = c.get(f"/api/super-admin/compliance/mexico/cfdi?organization_id={w.org.id}").json()
    assert out["total"] == 0 and out["schemaRelease"]["cfdiVersion"] == "4.0"
    # Phase 11b: with the verified pinned SAT set installed the builder is no
    # longer blocked; signing (X4) and the PAC (X3) still are.
    assert {b["code"] for b in out["blocked"]} == {"MX_CSD_SIGNING_BLOCKED", "MX_PAC_NOT_CONFIGURED"}


def test_super_admin_overview_probes_the_seams_without_calling_them(db, monkeypatch, tmp_path):
    """The overview asks each seam whether it is blocked; it never builds or
    signs, so a working (here: synthetic) builder cannot fail the page."""
    w = ch.committed_world(db, monkeypatch, tmp_path)             # synthetic builder / signer installed
    ch.mock(monkeypatch)
    with http(db, SUPER_ADMIN) as c:
        r = c.get(f"/api/super-admin/compliance/mexico/cfdi?organization_id={w.org.id}")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["blocked"] == []

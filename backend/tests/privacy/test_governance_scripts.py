"""
tests/privacy/test_governance_scripts.py
----------------------------------------
Part 9-12 tooling: Privacy Assurance API (record review needs
platform_security + step-up), the attestation verdict (never VERIFIED
unsigned), register counts, the defect gate, change control (CODEOWNERS +
CI gate), the alert drill, joiner / mover / leaver, the post-deploy smoke
and the evidence-pack leak check.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.privacy._evidence import record

REPO = Path(__file__).resolve().parents[3]
API = "/api/super-admin/privacy-assurance/controls"


# ── Privacy Assurance API ───────────────────────────────────────────────────

def test_assurance_view_is_security_readers_only_and_never_says_pass(client, world):
    for who, status in (("SA", 200), ("APP", 200), ("SP", 403), ("TA", 403), ("PA", 403)):
        assert client.get(API, headers=world.headers(who)).status_code == status, who
    body = client.get(API, headers=world.headers("APP")).json()
    assert body["summary"]["total"] == 46 and len(body["controls"]) == 46
    assert sum(body["summary"]["p0"].values()) == 41 and sum(body["summary"]["p1"].values()) == 5
    assert body["attestation"]["verdict"] in ("NOT VERIFIED", "BLOCKED")
    assert {c["status"] for c in body["controls"]} <= {"NT", "ENGINEERING_COMPLETE_AWAITING_REVIEW", "FAIL"}
    assert '"PASS"' not in json.dumps(body) and body["generatedAt"].endswith("Z")
    by_id = {c["id"]: c for c in body["controls"]}
    assert {i for i, c in by_id.items() if c["priority"] == "P1"} == {"A06", "D09", "E07", "F03", "F07"}
    assert by_id["D01"]["humanProofs"] and by_id["D01"]["status"] == "NT"


def test_record_review_needs_platform_security_step_up_and_proof(client, world, db):
    from app.modules.security.models import SecurityEvent

    body = {"decision": "accepted", "proofReference": "QA-2026-11 run 42 / EP-03"}
    assert client.post(f"{API}/A01/reviews", headers=world.headers("SA"), json=body).status_code == 403
    stale = world.headers("APP", mfa_at=int(time.time()) - 3600)
    r = client.post(f"{API}/A01/reviews", headers=stale, json=body)
    assert r.status_code == 403 and r.json()["error"] == "STEP_UP_REQUIRED"
    assert client.post(f"{API}/A01/reviews", headers=world.headers("APP"),
                       json={"decision": "accepted", "proofReference": "x"}).status_code == 422
    assert client.post(f"{API}/A01/reviews", headers=world.headers("APP"),
                       json={"decision": "pass", "proofReference": "QA-1"}).status_code == 422
    assert client.post(f"{API}/Z99/reviews", headers=world.headers("APP"), json=body).status_code == 404
    ok = client.post(f"{API}/A01/reviews", headers=world.headers("APP"), json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["reviewerUserId"] == world.users["APP"].id and ok.json()["recordedAt"].endswith("Z")
    ev = db.query(SecurityEvent).filter(SecurityEvent.event_type == "CONTROL_REVIEW_RECORDED").one()
    assert ev.target_id == "A01" and ev.reason_code == "ACCEPTED" and ev.ticket_reference == body["proofReference"]
    view = client.get(API, headers=world.headers("SA")).json()
    a01 = next(c for c in view["controls"] if c["id"] == "A01")
    assert a01["reviews"][0]["reviewerEmail"] == "app@platform.example"
    assert a01["status"] == "ENGINEERING_COMPLETE_AWAITING_REVIEW"     # engineering status unchanged
    assert view["summary"]["reviewed"] == 1 and view["attestation"]["verdict"] in ("NOT VERIFIED", "BLOCKED")
    record(test_id="P12_record_review", role="platform_security", scope="privacy assurance", tenant_ids=None,
           endpoint="POST /api/super-admin/privacy-assurance/controls/{id}/reviews", expected_status=200,
           actual_status=200, security_event_id=ev.id, note="step-up + proof required; reviewer identity stored")


# ── Verdict rules ───────────────────────────────────────────────────────────

def _register(**over):
    from app.modules.security import assurance

    reg = assurance.load_register()
    reg = json.loads(json.dumps(reg, default=str))
    # Verdict-logic tests start from a baseline with no failing control
    # (the live register may carry an owner-accepted FAIL, e.g. B08 / DEC-11).
    for c in reg["controls"]:
        if c["status"] == "FAIL":
            c["status"] = "ENGINEERING_COMPLETE_AWAITING_REVIEW"
    reg.update(over)
    return reg


def _accept_all(reg, reviewer="Independent Reviewer, Example Audit LLP"):
    return [{"control": c["id"], "reviewer": reviewer, "decision": "accepted", "proofReference": "QA-1"}
            for c in reg["controls"]]


def test_register_counts_and_default_verdict():
    from app.modules.security import assurance

    reg = _register()
    out = assurance.compute_verdict(reg, [], [])
    assert out["verdict"] == "NOT VERIFIED" and out["total"] == 46
    assert sum(out["p0"].values()) == 41 and sum(out["p1"].values()) == 5
    d_e_f = [c for c in reg["controls"] if c["section"] in ("D", "E", "F")]
    assert len(d_e_f) == 23 and {c["status"] for c in d_e_f} <= {"NT", "ENGINEERING_COMPLETE_AWAITING_REVIEW"}
    assert all(c.get("human_proofs") for c in reg["controls"] if c["status"] == "NT")


def test_verified_is_impossible_without_a_named_reviewer():
    from app.modules.security import assurance

    reg = _register()
    # Every control "accepted" but no named independent reviewer on the register.
    assert assurance.compute_verdict(reg, _accept_all(reg), [])["verdict"] == "NOT VERIFIED"
    # Reviews without a reviewer name do not count at all.
    assert assurance.compute_verdict(reg, _accept_all(reg, reviewer=""), [])["reviewed"] == 0
    # NT controls still block VERIFIED even when everything is accepted and signed.
    signed = _register(attestation={"independent_reviewer": "Example Audit LLP"})
    assert assurance.compute_verdict(signed, _accept_all(signed), [])["verdict"] == "NOT VERIFIED"


def test_blocking_conditions():
    from app.modules.security import assurance

    reg = _register()
    reg["controls"][0]["status"] = "PASS"
    assert assurance.compute_verdict(reg, [], [])["verdict"] == "BLOCKED"
    reg = _register()
    reg["controls"][1]["status"] = "FAIL"
    assert assurance.compute_verdict(reg, [], [])["verdict"] == "BLOCKED"
    reg = _register()
    rejected = [{"control": "A02", "reviewer": "R", "decision": "rejected", "proofReference": "QA-2"}]
    assert assurance.compute_verdict(reg, rejected, [])["verdict"] == "BLOCKED"
    assert assurance.compute_verdict(_register(), [], [{"id": "PD-9", "reason": "critical"}])["verdict"] == "BLOCKED"
    assert assurance.compute_verdict(_register(), [], [], test_failures=1)["verdict"] == "BLOCKED"
    reg = _register()
    reg["controls"].pop()
    assert assurance.compute_verdict(reg, [], [])["verdict"] == "BLOCKED"


def test_missing_register_fails_closed(tmp_path):
    from app.modules.security import assurance

    out = assurance.assurance_report(None, path=tmp_path / "missing.yaml")
    assert out["attestation"]["verdict"] == "BLOCKED" and out["controls"] == []


def test_attestation_script_writes_an_immutable_record_and_never_verifies(tmp_path, monkeypatch):
    from scripts import generate_evidence_pack, run_privacy_attestation

    monkeypatch.setattr(run_privacy_attestation, "ATTESTATIONS", tmp_path)
    monkeypatch.setattr(run_privacy_attestation, "REPO", tmp_path.parent)
    monkeypatch.setattr(generate_evidence_pack, "build", lambda n: {"EP-01": {"path": "x", "files": 0}})
    rec = run_privacy_attestation.attest(skip_tests=True, build_number="T-1")
    assert rec["verdict"] in ("NOT VERIFIED", "BLOCKED") and rec["buildNumber"] == "T-1" and len(rec["gitSha"]) >= 7
    assert rec["controls"]["total"] == 46
    files = list(tmp_path.glob("attestation-*.json"))
    assert len(files) == 1
    with pytest.raises(FileExistsError):
        with open(files[0], "x", encoding="utf-8"):
            pass


# ── Defect gate (F06) ───────────────────────────────────────────────────────

HEADER = "id,title,control_id,control_priority,type,severity,status,owner,opened_at,closed_at,notes\n"


@pytest.mark.parametrize("row, code", [
    ("PD-1,t,A01,P0,defect,critical,open,o,2026-10-19T00:00:00Z,,\n", 1),
    ("PD-1,t,A01,P0,defect,critical,closed,o,2026-10-19T00:00:00Z,2026-10-19T00:00:00Z,\n", 0),
    ("PD-1,t,A01,P0,exception,low,open,o,2026-10-19T00:00:00Z,,\n", 1),
    ("PD-1,t,A06,P1,exception,low,open,o,2026-10-19T00:00:00Z,,\n", 0),
    ("PD-1,t,A01,P0,defect,high,open,o,2026-10-19T00:00:00Z,,\n", 0),
])
def test_defect_gate(tmp_path, row, code):
    from scripts.check_privacy_defects import main

    path = tmp_path / "defects.csv"
    path.write_text(HEADER + row, encoding="utf-8")
    assert main(["--register", str(path)]) == code


def test_repository_defect_register_passes_the_gate():
    from scripts.check_privacy_defects import main

    assert main([]) == 0


# ── Change control (F07 / E06) ──────────────────────────────────────────────

def test_codeowners_covers_identity_authz_and_migrations():
    from app.modules.security import assurance

    paths = assurance.privacy_paths()
    for required in ("backend/app/core/dependencies.py", "backend/app/core/authz/", "backend/app/modules/auth/",
                     "backend/alembic/versions/", "backend/app/modules/security/", "docs/privacy/"):
        assert required in paths, required


def test_ci_gate_blocks_deploy_on_the_privacy_suite():
    import yaml

    for name in ("backend-deploy.yml", "backend-deploy-staging.yml"):
        wf = yaml.safe_load((REPO / ".github" / "workflows" / name).read_text(encoding="utf-8"))
        jobs = wf["jobs"]
        assert "privacy-isolation" in jobs["deploy"]["needs"], name
        runs = " ".join(s.get("run", "") for s in jobs["privacy-isolation"]["steps"])
        for cmd in ("tests/privacy/test_route_registry.py", "pytest -q -p no:cacheprovider tests/privacy",
                    "scripts.scan_test_data", "scripts.check_privacy_defects"):
            assert cmd in runs, (name, cmd)
        assert "postgres" in jobs["privacy-isolation"]["services"]
        assert jobs["privacy-isolation"]["env"]["ZP_REQUIRE_POSTGRES_TESTS"] == "1"
        steps = [s.get("name", "") for s in jobs["deploy"]["steps"]]
        assert "Post-deploy privacy smoke" in steps


def test_alert_rules_export_is_in_sync(tmp_path):
    from app.modules.security import alerts

    fresh = tmp_path / "rules.json"
    alerts.export_rules(fresh)
    committed = json.loads((REPO / "docs" / "privacy" / "alert_rules.json").read_text(encoding="utf-8"))
    assert json.loads(fresh.read_text(encoding="utf-8")) == committed


# ── Alert drill, JML, smoke, evidence ───────────────────────────────────────

def test_alert_drill_fires_and_delivers_every_rule(db, world):
    from app.modules.security import alerts
    from app.modules.security.models import AlertEvent
    from app.modules.security.ops import run_alert_drill

    out = run_alert_drill(db, tag="t1")
    assert out["allFired"] and out["allDelivered"]
    assert {r["rule"] for r in out["rules"]} == set(alerts.RULES_BY_KEY)
    for a in db.query(AlertEvent).all():
        assert "Synthetic Worker" not in a.summary and "@" not in a.summary
    live = run_alert_drill(db, live=True, tag="t2")
    assert live["allFired"] and all(db.query(AlertEvent).get(r["alertId"]).is_drill for r in live["rules"])


def test_jml_leaver_mover_incident_and_idempotence(client, world, db):
    from app.modules.auth.models import RefreshTokenRecord, User
    from app.modules.security.ops import jml_reconcile
    from app.modules.support_access.models import SupportAccessGrant

    req = client.post("/api/super-admin/support-access/request", headers=world.headers("SP"), json={
        "organizationCode": "PRIVA", "reason": "r", "ticketReference": "T-1", "minutes": 5,
        "scopeType": "diagnostics"}).json()
    client.post(f"/api/organization-admin/support-access/{req['id']}/approve", headers=world.headers("TA"), json={})
    sp_token = world.token("SP")
    events = [{"email": "sp@platform.example", "event": "leaver"},
              {"user_id": world.users["PS2"].id, "event": "mover", "new_role": "support_operator"},
              {"email": "nobody@platform.example", "event": "leaver"},
              {"email": "sa@platform.example", "event": "promotion"}]
    dry = jml_reconcile(db, events, apply=False)
    assert db.query(User).get(world.users["SP"].id).is_active  # dry run changes nothing
    out = jml_reconcile(db, events, apply=True)
    db.expire_all()
    assert not db.query(User).get(world.users["SP"].id).is_active
    assert db.query(SupportAccessGrant).get(req["id"]).status == "revoked"
    assert db.query(User).get(world.users["PS2"].id).role.value == "support_operator"
    assert db.query(RefreshTokenRecord).filter(RefreshTokenRecord.user_id == world.users["SP"].id,
                                               RefreshTokenRecord.revoked_at.is_(None)).count() == 0
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {sp_token}"}).status_code == 401
    assert [r["status"] for r in out["results"]][2:] == ["no matching account", "rejected: unknown event"]
    again = jml_reconcile(db, events, apply=True)
    assert "deactivate" not in again["results"][0]["actions"] and again["results"][1]["actions"] == []
    assert "@" not in json.dumps(dry) + json.dumps(out)


def test_post_deploy_smoke_passes_when_denied_and_fails_on_a_leak(client, world, monkeypatch):
    from scripts import post_deploy_privacy_smoke as smoke

    def via_testclient(base, method, path, token=None, body=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = client.request(method, path, headers=headers, json=body)
        return resp.status_code, None

    tokens = {"super_admin": world.token("SA"), "support_operator": world.token("SP"),
              "platform_security": world.token("APP"), "org_admin": world.token("TA")}
    monkeypatch.setattr(smoke, "_request", via_testclient)
    monkeypatch.setattr(smoke, "_login", lambda base, identity: tokens[identity["role"]])
    ok = smoke.run("http://testserver", [{"role": r} for r in ("super_admin", "support_operator",
                                                               "platform_security")],
                   str(world.employees["A1"].id), "smoke-test-1")
    assert ok["result"] == "OK" and ok["failed"] == 0 and len(ok["checks"]) == 20
    leak = smoke.run("http://testserver", [{"role": "org_admin"}], str(world.employees["A1"].id), "smoke-test-2")
    assert leak["result"] == "FAIL"   # a tenant admin CAN read: proves the smoke detects access
    assert "token" not in json.dumps(ok).lower().replace("smoke", "")


def test_evidence_pack_refuses_tokens_and_secrets(tmp_path):
    from scripts.generate_evidence_pack import EvidenceLeak, check_clean

    check_clean('{"role": "super_admin", "password": "***"}', "ok")
    for bad in ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXg", '{"password": "Hunter2-real"}',
                "zpmc_abcdef12.secretsecretsecret", "Bearer abcdefghijklmnopqrstuvwxyz"):
        with pytest.raises(EvidenceLeak):
            check_clean(bad, "x")


def test_mfa_removal_is_recorded_as_a_failing_control_not_hidden():
    """DEC-11: switching two-step verification off is visible - B08 is FAIL
    in the register and the verdict is BLOCKED, never NOT VERIFIED/VERIFIED."""
    from app.modules.security import assurance

    reg = assurance.load_register()
    assert next(c for c in reg["controls"] if c["id"] == "B08")["status"] == "FAIL"
    assert assurance.compute_verdict(reg, [], [])["verdict"] == "BLOCKED"

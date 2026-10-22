"""Mexico Phase 10d (plan D10): the release gates G1–G8 and the owner (legal)
decisions are SIGNED / RECORDED only by independently reviewed, uploaded
evidence. The build signs nothing; with every gate signed Mexico still stays
off until the deployment flag is set (activation runbook). SYNTHETIC rows."""

import pytest


def _S():
    from app.modules.payroll import mexico_service

    return mexico_service


def _evidence(db, tag, created_by, reviewer=None, file_path="evidence/mx.pdf", superseded_by=None):
    from app.modules.payroll.models import SourceArtifact

    row = SourceArtifact(agency="Zoiko (SYNTHETIC)", title=f"{tag} evidence", form_number=tag,
                         created_by_id=created_by, reviewer_id=reviewer, file_path=file_path,
                         superseded_by_id=superseded_by)
    db.add(row)
    db.flush()
    return row


def test_today_every_gate_is_open_and_every_decision_open(db):
    out = _S().statutory_summary(db)
    assert [g["gate"] for g in out["gates"]] == [f"G{i}" for i in range(1, 9)]
    assert {g["state"] for g in out["gates"]} == {"OPEN"} and out["signedGates"] == 0
    assert {d["state"] for d in out["decisions"]} == {"OPEN"} and len(out["decisions"]) == 3
    assert out["available"] is False and out["phase"] == 10
    assert all(g["checklist"] == f"docs/mexico/release-gates/{g['gate']}/CHECKLIST.md" for g in out["gates"])
    assert {r["state"] for r in out["retention"]} == {"BLOCKED_UNDECIDED"} and len(out["retention"]) == 8


def test_a_gate_is_signed_only_by_independently_reviewed_uploaded_evidence(db):
    _evidence(db, "MX-GATE-G1", created_by=801)                                # submitted, not reviewed
    _evidence(db, "MX-GATE-G2", created_by=801, reviewer=801)                  # self-review is not a review
    _evidence(db, "MX-GATE-G3", created_by=801, reviewer=802, file_path=None)  # no document, no signature
    _evidence(db, "MX-GATE-G4", created_by=None, reviewer=802)                 # unknown maker, no four eyes
    signed = _evidence(db, "MX-GATE-G5", created_by=801, reviewer=802)        # independent review + document
    replacement = _evidence(db, "SYNTHETIC-REPLACEMENT", created_by=801)
    _evidence(db, "MX-GATE-G6", created_by=801, reviewer=802, superseded_by=replacement.id)   # superseded: never counts
    states = {g["gate"]: g for g in _S().gate_states(db)}
    assert {k: states[k]["state"] for k in ("G1", "G2", "G3", "G4")} == dict.fromkeys(("G1", "G2", "G3", "G4"),
                                                                                    "SUBMITTED")
    assert states["G5"]["state"] == "SIGNED" and states["G5"]["artifactId"] == signed.id
    assert states["G6"]["state"] == "OPEN" and states["G7"]["state"] == states["G8"]["state"] == "OPEN"


def test_the_review_api_refuses_the_creator(db):
    from app.modules.payroll import service

    row = _evidence(db, "MX-GATE-G7", created_by=801)
    with pytest.raises(Exception, match="reviewer different"):
        service.mark_source_artifact_reviewed(db, row.id, 801)


def test_a_recorded_decision_unblocks_only_the_proposal_never_a_purge(db):
    from app.modules.payroll import retention_service

    _evidence(db, "MX-DECISION-RETENTION-PERIOD", created_by=801, reviewer=802)
    _evidence(db, "MX-DECISION-RETENTION-END", created_by=801, reviewer=802)
    decisions = {d["key"]: d["state"] for d in _S().owner_decisions(db)}
    assert decisions == {"MX-D-RETENTION-PERIOD": "RECORDED", "MX-D-RETENTION-END": "RECORDED", "MX-D-HOSTING": "OPEN"}
    row = retention_service.propose_retention_policy(db, "MX", {
        "recordCategory": "PAYROLL_RECORDS", "retentionYears": 5, "endOfRetention": "ANONYMISE",
        "legalBasis": "SYNTHETIC", "reason": "SYNTHETIC"}, 801)
    assert row["status"] == "DRAFT"
    assert retention_service.purge_refusal(db, "MX", "PAYROLL_RECORDS")              # still refused: not approved


def test_all_gates_signed_opens_the_registry_but_not_mexico(db, monkeypatch):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import jurisdiction_hooks, mexico_dormancy

    db.add(JurisdictionServiceRegistry(country="MX", availability="PLANNED"))
    db.commit()
    for i in range(1, 9):
        _evidence(db, f"MX-GATE-G{i}", created_by=801, reviewer=802)
    db.commit()
    assert _S().statutory_summary(db)["signedGates"] == 8
    jurisdiction_hooks.call("MX", "service_registry_transition", db, "AVAILABLE", "SYNTHETIC: all gates", actor_id=802)
    out = _S().statutory_summary(db)
    assert out["registry"] == "AVAILABLE"
    assert mexico_dormancy.onboarding_enabled() is False and out["available"] is False   # the flag is still off


def test_the_documents_the_readiness_view_names_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    docs = _S().statutory_summary.__globals__
    for rel in (docs["RELEASE_GATES_DOC"], docs["ACTIVATION_RUNBOOK_DOC"], docs["RELEASE_CHECKLIST_DOC"],
                docs["UNKNOWN_RUNBOOK_DOC"], *[f"docs/mexico/release-gates/G{i}/CHECKLIST.md" for i in range(1, 9)]):
        assert (root / rel).is_file(), rel

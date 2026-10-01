"""
tests/test_singapore_evidence_registry.py
-----------------------------------------
Singapore production closure — evidence-controlled G1–G8 / D1–D3 and the
fifteen-category activation readiness dashboard.

Gate and decision evidence is an ordinary SourceArtifact tagged with form
number SG-GATE-G<n> / SG-DECISION-D<n> (the existing Source Evidence store:
SHA-256, file upload, reviewer != creator, audited review). A gate is PASS
only when an artifact is on record with its creator, reviewed by a DIFFERENT
user, hashed and not superseded; anything less is SUBMITTED (no document) or
UNDER_REVIEW (document uploaded, awaiting a distinct reviewer).
Nothing here is regulator certification.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date

import pytest

A, B = 101, 202
SHA = "a" * 64


@pytest.fixture(autouse=True)
def _uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path))          # evidence files never leave the test

def _summary(db):
    from app.modules.payroll import service

    return service.get_sg_statutory_summary(db, date(2026, 9, 25))


def _ready(db):
    return _summary(db)["activationReadiness"]


def _gate(db, key):
    return next(g for g in _ready(db)["productionGates"] if g["key"] == key)


def _evidence(db, tag, actor=A, upload=True, typed_sha=None):
    """A gate / decision artifact as the Super Admin UI records it: created,
    then the signed document uploaded (server-computed SHA-256)."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    art = service.create_source_artifact(db, SourceArtifactCreate(
        agency="Independent reviewer", title=f"Evidence for {tag}", formNumber=tag, checksumSha256=typed_sha),
        actor_id=actor)
    if upload:
        art = service.upload_source_artifact_file(db, art.id, f"{tag}.pdf", "application/pdf",
                                                  f"signed evidence {tag}".encode(), actor_id=actor)
    return art


def test_without_evidence_no_gate_or_decision_passes(db):
    ready = _ready(db)
    gates = {g["key"]: g["status"] for g in ready["productionGates"]}
    assert gates.pop("G3") == "BUSINESS_DECISION_REQUIRED"
    assert set(gates.values()) == {"EVIDENCE_REQUIRED"}
    assert all(g["evidenceRecorded"] is None and g["evidenceTag"] == f"SG-GATE-{g['key']}" for g in ready["productionGates"])
    assert {d["status"] for d in ready["pendingDecisions"]} == {"BUSINESS_DECISION_REQUIRED"}


def test_gate_evidence_needs_a_distinct_reviewer_a_hash_and_no_supersession(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    art = _evidence(db, "SG-GATE-G1", actor=A)
    assert _gate(db, "G1")["status"] == "UNDER_REVIEW"
    with pytest.raises(BadRequestException, match="different"):
        service.mark_source_artifact_reviewed(db, art.id, reviewer_id=A)          # the creator cannot accept it
    assert _gate(db, "G1")["status"] == "UNDER_REVIEW"
    service.mark_source_artifact_reviewed(db, art.id, reviewer_id=B)
    g1 = _gate(db, "G1")
    assert g1["status"] == "PASS" and g1["evidenceRecorded"][0]["accepted"] is True
    newer = _evidence(db, "SG-OTHER", actor=A)
    art.superseded_by_id = newer.id                                                # replaced evidence no longer counts
    db.commit()
    assert _gate(db, "G1")["status"] == "EVIDENCE_REQUIRED"                        # no current artifact left
    assert _gate(db, "G2")["status"] == "EVIDENCE_REQUIRED"                        # per gate


def test_a_document_less_or_creatorless_artifact_is_never_accepted(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    typed = _evidence(db, "SG-GATE-G2", actor=A, upload=False, typed_sha=SHA)       # hand-typed hash, no document
    with pytest.raises(BadRequestException, match="no uploaded document"):
        service.mark_source_artifact_reviewed(db, typed.id, reviewer_id=B)
    typed.reviewer_id, typed.reviewer_approved_at = B, typed.created_at              # e.g. a pre-existing row
    db.commit()
    orphan = _evidence(db, "SG-GATE-G4", actor=None)                               # no creator on record
    service.mark_source_artifact_reviewed(db, orphan.id, reviewer_id=B)
    assert _gate(db, "G2")["status"] == "SUBMITTED"                                # a typed hash is no document
    assert _gate(db, "G4")["status"] == "UNDER_REVIEW"                             # no creator: never accepted


def test_reviewed_gate_evidence_cannot_have_its_document_replaced(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    art = _evidence(db, "SG-GATE-G6", actor=A)
    service.mark_source_artifact_reviewed(db, art.id, reviewer_id=B)
    accepted_sha = _gate(db, "G6")["evidenceRecorded"][0]["sha256"]
    with pytest.raises(BadRequestException, match="cannot be replaced"):
        service.upload_source_artifact_file(db, art.id, "other.pdf", "application/pdf", b"swapped", actor_id=A)
    db.refresh(art)
    assert art.checksum_sha256 == accepted_sha and _gate(db, "G6")["status"] == "PASS"


def test_other_source_evidence_keeps_its_existing_replace_behaviour(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    art = service.create_source_artifact(db, SourceArtifactCreate(agency="IRS", title="Pub 15-T", formNumber="15-T"),
                                         actor_id=A)
    service.upload_source_artifact_file(db, art.id, "a.pdf", "application/pdf", b"v1", actor_id=A)
    service.mark_source_artifact_reviewed(db, art.id, reviewer_id=B)
    again = service.upload_source_artifact_file(db, art.id, "b.pdf", "application/pdf", b"v2", actor_id=A)
    assert again.original_filename == "b.pdf"                                      # unchanged for non-SG evidence


def test_a_recorded_d1_decision_moves_g3_to_its_iras_evidence(db):
    from app.modules.payroll import service

    decision = service.record_sg_decision(db, "D1", "EXPORT_ONLY", "Export mode until AIS-API onboarding", actor_id=A)
    assert next(d for d in _ready(db)["pendingDecisions"] if d["key"] == "D1")["status"] == "SUBMITTED"
    service.upload_source_artifact_file(db, decision.id, "d1.pdf", "application/pdf", b"signed D1 memo", actor_id=A)
    assert next(d for d in _ready(db)["pendingDecisions"] if d["key"] == "D1")["status"] == "UNDER_REVIEW"
    service.mark_source_artifact_reviewed(db, decision.id, reviewer_id=B)
    d1 = next(d for d in _ready(db)["pendingDecisions"] if d["key"] == "D1")
    assert d1["status"] == "DECISION_RECORDED" and d1["evidenceRecorded"][0]["accepted"]
    assert (d1["recordedValue"], d1["decisionMakerId"], d1["reviewerId"]) == ("EXPORT_ONLY", A, B)
    assert _gate(db, "G3")["status"] == "EVIDENCE_REQUIRED"


def test_the_dashboard_has_the_sixteen_categories_and_never_hides_a_blocker(db):
    rows = {r["key"]: r for r in _ready(db)["readinessDashboard"]}
    assert list(rows) == ["engineering", "configuration", "super_admin", "report_templates", "generators", "security",
                          "tenant_isolation", "database", "migration", "deployment", "testing", "external_evidence",
                          "business_decisions", "external_data", "external_integrations", "production_activation"]
    assert {r["status"] for r in rows.values()} <= {"PASS", "BLOCKED", "EXTERNAL_REQUIRED", "BUSINESS_DECISION_REQUIRED"}
    assert rows["engineering"]["basis"] == "internal" and "not regulator certification" in rows["engineering"]["evidence"]
    assert rows["database"]["status"] == "PASS"                   # create_all: every Singapore object exists
    assert rows["migration"]["status"] == "BLOCKED"               # no alembic_version in the test database
    assert rows["deployment"]["status"] == "EXTERNAL_REQUIRED" and rows["deployment"]["basis"] == "owner"
    for key in ("external_evidence", "external_data", "external_integrations"):
        assert rows[key]["status"] == "EXTERNAL_REQUIRED", key
    assert rows["business_decisions"]["status"] == "BUSINESS_DECISION_REQUIRED"
    assert rows["testing"]["status"] == "BLOCKED"                  # no golden run recorded in an empty database
    assert "AIS-API" in rows["external_integrations"]["evidence"]
    assert rows["report_templates"]["status"] == "BLOCKED"        # none seeded in an empty database
    activation = rows["production_activation"]
    assert activation["status"] == "BLOCKED"
    assert "no Active Singapore statutory pack" in activation["evidence"] and "service registry missing" in activation["evidence"]


def test_the_dashboard_reads_the_real_alembic_head_and_schema(db, monkeypatch):
    from app.modules.payroll import service

    state = service._sg_database_state(db)
    assert state["codeHeads"] == ["cd62503afe26"] and state["missingSgObjects"] == [] and state["error"] is None
    monkeypatch.setattr(service, "_sg_database_state", lambda _db: {**state, "databaseHeads": ["cd62503afe26"],
                                                                      "atHead": True})
    rows = {r["key"]: r for r in _ready(db)["readinessDashboard"]}
    assert rows["migration"]["status"] == "PASS"


def test_every_template_row_states_external_validation_is_required(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()
    templates = next(s for s in _summary(db)["sections"] if s["key"] == "reportTemplates")["values"]["templates"]
    assert len(templates) == 11
    assert all(t["externalValidation"] == "EXTERNAL_VALIDATION_REQUIRED" and t["officialCertification"] is False
               for t in templates)


# ══ Supersession: the only way to change accepted evidence (final closure) ══

def test_accepted_evidence_is_changed_only_by_supersession_and_the_old_record_is_kept(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import SourceArtifact, TaxConfigurationAudit

    first = _evidence(db, "SG-GATE-G7", actor=A)
    service.mark_source_artifact_reviewed(db, first.id, reviewer_id=B)
    assert _gate(db, "G7")["status"] == "PASS"
    second = _evidence(db, "SG-GATE-G7", actor=A)                                    # the corrected document
    service.supersede_sg_gate_evidence(db, first.id, second.id, actor_id=A)
    assert _gate(db, "G7")["status"] == "UNDER_REVIEW"                               # supersession withdraws acceptance
    kept = db.get(SourceArtifact, first.id)
    assert (kept.superseded_by_id, kept.reviewer_id) == (second.id, B) and kept.file_path and kept.checksum_sha256
    service.mark_source_artifact_reviewed(db, second.id, reviewer_id=B)
    g7 = _gate(db, "G7")
    assert g7["status"] == "PASS"
    assert [(e["id"], e["superseded"], e["accepted"]) for e in g7["evidenceRecorded"]] == [
        (first.id, True, False), (second.id, False, True)]
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "source_artifact",
                                                   TaxConfigurationAudit.entity_id == first.id,
                                                   TaxConfigurationAudit.reason.like("%superseded by%")).one()
    assert (audit.actor_id, audit.new_value["supersededById"]) == (A, second.id)


def test_supersession_refuses_every_unsafe_pairing(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    g5a, g5b, g5c = (_evidence(db, "SG-GATE-G5") for _ in range(3))
    g8 = _evidence(db, "SG-GATE-G8")
    other = service.create_source_artifact(db, SourceArtifactCreate(agency="IRS", title="Pub 15", formNumber="15"), actor_id=A)
    for old, new, match in ((g5a, g8, "same form number"), (g5a, g5a, "itself"), (other, g5a, "Only Singapore")):
        with pytest.raises(BadRequestException, match=match):
            service.supersede_sg_gate_evidence(db, old.id, new.id, actor_id=A)
    service.supersede_sg_gate_evidence(db, g5a.id, g5b.id, actor_id=A)
    with pytest.raises(BadRequestException, match="already superseded"):
        service.supersede_sg_gate_evidence(db, g5a.id, g5c.id, actor_id=A)
    with pytest.raises(BadRequestException, match="itself superseded"):
        service.supersede_sg_gate_evidence(db, g5c.id, g5a.id, actor_id=A)


def test_the_supersede_route_is_platform_super_admin_only():
    from app.core.dependencies import get_current_super_admin
    from app.main import app

    path = "/api/super-admin/compliance/source-artifacts/{id}/supersede"
    route = next(r for r in app.routes if getattr(r, "path", None) == path and "PUT" in getattr(r, "methods", ()))
    assert get_current_super_admin in {d.call for d in route.dependant.dependencies}

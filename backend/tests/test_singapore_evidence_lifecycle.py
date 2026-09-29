"""
tests/test_singapore_evidence_lifecycle.py
------------------------------------------
Singapore final completion programme (2026-09-29): the G1–G8 evidence
lifecycle EVIDENCE_REQUIRED -> SUBMITTED -> UNDER_REVIEW -> PASS | REJECTED |
EXPIRED, and structured owner decisions D1–D3 (selected option, decision
maker, reason, reviewer, review status).

No new table or column: each review outcome / decision is an immutable
TaxConfigurationAudit row on the SourceArtifact; the summary derives the
state. Before this pass a reviewer could only ACCEPT (no rejection, no
validity date), and a decision memo recorded no selected option.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date

import pytest

from tests.test_singapore_evidence_registry import A, B, _evidence, _gate, _ready

C = 303


@pytest.fixture(autouse=True)
def _uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path))


def _decision(db, key):
    return next(d for d in _ready(db)["pendingDecisions"] if d["key"] == key)


def test_the_full_gate_lifecycle_and_its_structured_fields(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    g5 = _gate(db, "G5")
    assert g5["status"] == "EVIDENCE_REQUIRED" and "SG-GATE-G5" in g5["nextAction"]
    assert g5["validationCriteria"] and g5["requiredArtifact"] == g5["evidenceRequired"] and g5["owner"]
    art = service.create_source_artifact(db, SourceArtifactCreate(agency="MOM", title="Levy bill", formNumber="SG-GATE-G5"),
                                         actor_id=A)
    assert _gate(db, "G5")["status"] == "SUBMITTED"                                 # registered, no document
    service.upload_source_artifact_file(db, art.id, "bill.pdf", "application/pdf", b"levy bill", actor_id=A)
    assert _gate(db, "G5")["status"] == "UNDER_REVIEW"
    service.review_sg_gate_evidence(db, art.id, "ACCEPTED", notes="Reconciled to FWL", valid_until=date(2027, 3, 31),
                                    actor_id=B, today=date(2026, 9, 25))
    g5 = _gate(db, "G5")
    assert (g5["status"], g5["reviewedBy"], g5["expiryDate"], g5["notes"], g5["submittedArtifactId"]) == (
        "PASS", B, "2027-03-31", "Reconciled to FWL", art.id)
    assert g5["blockingReason"] is None and g5["nextAction"] == "None"


def test_accepted_evidence_expires_after_its_validity_date(db):
    from app.modules.payroll import service

    art = _evidence(db, "SG-GATE-G7", actor=A)
    service.review_sg_gate_evidence(db, art.id, "ACCEPTED", valid_until=date(2026, 9, 30), actor_id=B,
                                    today=date(2026, 9, 25))
    assert _gate(db, "G7")["status"] == "PASS"                                       # as of 25 Sep
    later = next(g for g in service.get_sg_statutory_summary(db, date(2026, 10, 1))["activationReadiness"]
                 ["productionGates"] if g["key"] == "G7")
    assert later["status"] == "EXPIRED" and "validity" in later["blockingReason"]
    dash = {r["key"]: r for r in service.get_sg_statutory_summary(db, date(2026, 10, 1))["activationReadiness"]
            ["readinessDashboard"]}
    assert "G7: EXPIRED" in dash["external_evidence"]["evidence"]


def test_rejected_evidence_is_final_and_replaced_only_by_supersession(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    art = _evidence(db, "SG-GATE-G6", actor=A)
    with pytest.raises(BadRequestException, match="notes"):
        service.review_sg_gate_evidence(db, art.id, "REJECTED", actor_id=B)
    service.review_sg_gate_evidence(db, art.id, "REJECTED", notes="Memo unsigned", actor_id=B)
    g6 = _gate(db, "G6")
    assert (g6["status"], g6["notes"], g6["reviewedBy"]) == ("REJECTED", "Memo unsigned", B)
    for attempt in (lambda: service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=C),
                    lambda: service.mark_source_artifact_reviewed(db, art.id, reviewer_id=C),
                    lambda: service.upload_source_artifact_file(db, art.id, "x.pdf", "application/pdf", b"x", actor_id=A)):
        with pytest.raises(BadRequestException, match="REJECTED"):
            attempt()
    assert _gate(db, "G6")["status"] == "REJECTED"
    fixed = _evidence(db, "SG-GATE-G6", actor=A)
    service.supersede_sg_gate_evidence(db, art.id, fixed.id, actor_id=A)
    assert _gate(db, "G6")["status"] == "UNDER_REVIEW"
    service.review_sg_gate_evidence(db, fixed.id, "ACCEPTED", actor_id=B)
    assert _gate(db, "G6")["status"] == "PASS"
    outcome = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "source_artifact",
                                                      TaxConfigurationAudit.entity_id == art.id,
                                                      TaxConfigurationAudit.action == "review",
                                                      TaxConfigurationAudit.reason.like("%REJECTED%")).one())
    assert (outcome.actor_id, outcome.new_value["sgEvidenceOutcome"]) == (B, "REJECTED")


def test_review_outcome_refusals(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    art = _evidence(db, "SG-GATE-G1", actor=A)
    other = service.create_source_artifact(db, SourceArtifactCreate(agency="IRS", title="Pub 15", formNumber="15"), actor_id=A)
    bare = _evidence(db, "SG-GATE-G2", actor=A, upload=False)
    for call, match in (
            (lambda: service.review_sg_gate_evidence(db, art.id, "MAYBE", actor_id=B), "Outcome"),
            (lambda: service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=A), "different"),     # maker
            (lambda: service.review_sg_gate_evidence(db, other.id, "ACCEPTED", actor_id=B), "Only Singapore"),
            (lambda: service.review_sg_gate_evidence(db, bare.id, "ACCEPTED", actor_id=B), "no uploaded document"),
            (lambda: service.review_sg_gate_evidence(db, art.id, "ACCEPTED", valid_until=date(2026, 1, 1), actor_id=B,
                                                     today=date(2026, 9, 25)), "future"),
            (lambda: service.review_sg_gate_evidence(db, art.id, "REJECTED", notes="x", valid_until=date(2027, 1, 1),
                                                     actor_id=B), "ACCEPTED evidence")):
        with pytest.raises(BadRequestException, match=match):
            call()
    assert _gate(db, "G1")["status"] == "UNDER_REVIEW"                               # every refusal wrote nothing
    service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=B)
    with pytest.raises(BadRequestException, match="already reviewed"):
        service.review_sg_gate_evidence(db, art.id, "REJECTED", notes="late", actor_id=C)   # a review is never replaced
    assert _gate(db, "G1")["status"] == "PASS"


def test_a_decision_records_option_maker_reason_and_needs_a_second_admin(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    d2 = _decision(db, "D2")
    assert d2["status"] == "BUSINESS_DECISION_REQUIRED" and d2["recordedValue"] is None
    assert d2["inForceValue"] == service.SG_HOTFIX_POLICY and "No decision recorded" in d2["blockingReason"]
    for kwargs, match in ((dict(key="D9", selected_value="X", reason="r"), "Unknown"),
                          (dict(key="D2", selected_value="LOOSE", reason="r"), "must be one of"),
                          (dict(key="D2", selected_value="PROHIBITED", reason="  "), "reason")):
        with pytest.raises(BadRequestException, match=match):
            service.record_sg_decision(db, actor_id=A, **kwargs)
    row = service.record_sg_decision(db, "D2", "PROHIBITED", "No emergency activations in year one", actor_id=A)
    d2 = _decision(db, "D2")
    assert (d2["status"], d2["recordedValue"], d2["decisionMakerId"], d2["reason"]) == (
        "SUBMITTED", "PROHIBITED", A, "No emergency activations in year one")
    service.upload_source_artifact_file(db, row.id, "d2.pdf", "application/pdf", b"signed D2", actor_id=A)
    with pytest.raises(BadRequestException, match="different"):
        service.review_sg_gate_evidence(db, row.id, "ACCEPTED", actor_id=A)          # the decision maker cannot accept it
    service.review_sg_gate_evidence(db, row.id, "ACCEPTED", actor_id=B)
    d2 = _decision(db, "D2")
    assert (d2["status"], d2["reviewerId"], d2["reviewStatus"]) == ("DECISION_RECORDED", B, "PASS")
    # Recording never changes the behaviour in force — it is flagged instead.
    assert service.SG_HOTFIX_POLICY == "RESTRICTED" and d2["inForceDiffers"] is True and d2["effectIfDifferent"]


def test_a_decision_memo_without_a_selected_option_records_no_decision(db):
    from app.modules.payroll import service

    memo = _evidence(db, "SG-DECISION-D3", actor=A)                                  # generic Source Evidence upload
    service.mark_source_artifact_reviewed(db, memo.id, reviewer_id=B)
    d3 = _decision(db, "D3")
    assert d3["status"] == "BUSINESS_DECISION_REQUIRED" and "no selected option" in d3["blockingReason"]


@pytest.mark.parametrize("path, method", [
    ("/api/super-admin/compliance/source-artifacts/{id}/sg-review", "PUT"),
    ("/api/super-admin/compliance/singapore/decisions", "POST"),
])
def test_the_new_routes_are_platform_super_admin_only(path, method):
    from app.core.dependencies import get_current_super_admin
    from app.main import app

    route = next(r for r in app.routes if getattr(r, "path", None) == path and method in getattr(r, "methods", ()))
    assert get_current_super_admin in {d.call for d in route.dependant.dependencies}


def test_every_singapore_governance_route_requires_the_platform_super_admin():
    """Sweep: every Super Admin route that governs Singapore (its compliance
    screens, evidence, decisions, packs, templates, hotfixes) resolves the
    real get_current_super_admin dependency — which refuses org admins,
    payroll admins and an org-bound super admin (test_singapore_phase56_admin)."""
    from app.core.dependencies import get_current_super_admin
    from app.main import app

    def deps(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from deps(d)

    governed = [r for r in app.routes if getattr(r, "path", "").startswith("/api/super-admin/")
                and any(k in r.path for k in ("/singapore", "/source-artifacts", "/jurisdiction-packs", "/report-templates",
                                                "/hotfix"))]
    assert len(governed) >= 20
    unguarded = [f"{sorted(r.methods)} {r.path}" for r in governed if get_current_super_admin not in set(deps(r.dependant))]
    assert unguarded == []


def test_every_refused_evidence_governance_action_is_audited_and_changes_nothing(db):
    """Final closure: self-review (both review paths), review / upload after a
    rejection and replacing a completed review each leave one "refused" audit
    row and no change — the pack / template refusal-audit rule, applied to
    Singapore gate / decision evidence."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import SourceArtifact, TaxConfigurationAudit

    def refused(artifact_id):
        return [(a.actor_id, a.new_value["attempted"]) for a in db.query(TaxConfigurationAudit).filter(
            TaxConfigurationAudit.entity_type == "source_artifact", TaxConfigurationAudit.entity_id == artifact_id,
            TaxConfigurationAudit.action == "refused").order_by(TaxConfigurationAudit.id)]

    art = _evidence(db, "SG-GATE-G2", actor=A)
    for call in (lambda: service.mark_source_artifact_reviewed(db, art.id, reviewer_id=A),
                 lambda: service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=A)):
        with pytest.raises(BadRequestException, match="different"):
            call()
    assert refused(art.id) == [(A, "review"), (A, "review:ACCEPTED")]
    assert db.get(SourceArtifact, art.id).reviewer_id is None and _gate(db, "G2")["status"] == "UNDER_REVIEW"
    service.review_sg_gate_evidence(db, art.id, "REJECTED", notes="unsigned", actor_id=B)
    for call in (lambda: service.mark_source_artifact_reviewed(db, art.id, reviewer_id=C),
                 lambda: service.upload_source_artifact_file(db, art.id, "x.pdf", "application/pdf", b"x", actor_id=A)):
        with pytest.raises(BadRequestException, match="REJECTED"):
            call()
    assert refused(art.id)[2:] == [(C, "review"), (A, "upload")]
    ok = _evidence(db, "SG-GATE-G4", actor=A)
    service.review_sg_gate_evidence(db, ok.id, "ACCEPTED", actor_id=B)
    with pytest.raises(BadRequestException, match="already reviewed"):
        service.review_sg_gate_evidence(db, ok.id, "REJECTED", notes="late", actor_id=C)
    assert refused(ok.id) == [(C, "review:REJECTED")] and _gate(db, "G4")["status"] == "PASS"


def test_other_countries_source_evidence_self_review_is_unchanged(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit
    from app.modules.payroll.schemas import SourceArtifactCreate

    other = service.create_source_artifact(db, SourceArtifactCreate(agency="IRS", title="Pub 15", formNumber="15"), actor_id=A)
    with pytest.raises(BadRequestException, match="different"):
        service.mark_source_artifact_reviewed(db, other.id, reviewer_id=A)
    assert not db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_id == other.id,
                                                      TaxConfigurationAudit.action == "refused").count()

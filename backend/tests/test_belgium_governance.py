"""Belgium (ZP-BE-ENG-001) Blocks K2 / K3: release-gate evidence and decision records.

K2: a gate check that needs an evidence tag stays NOT MET with no evidence, with PENDING evidence, with REJECTED
or SUPPORTING evidence, and when the recorder tries to accept it; it counts only when ACCEPTED by another person.
Evidence never satisfies a gate's data-derived checks (G6 keys, G-21 decision …).
K3: proposals are imported PROPOSED (nothing decided); deciding is four-eyes; a later decision supersedes and the
history is kept; a decision does not change content — its linked content keys show whether the rows are signed.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestException


def _gov():
    from app.modules.payroll import belgium_governance

    return belgium_governance


def _gate(db, key):
    from app.modules.payroll import belgium_readiness

    return next(g for g in belgium_readiness.be_readiness(db)["gates"] if g["gate"] == key)


def _check(db, gate, key):
    return next(c for c in _gate(db, gate)["checks"] if c["key"] == key)


@pytest.fixture
def people(db):
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Governance BV", code="BEGOV", admins=3, country="BE")
    return [u.id for u in t.users]


# ── K2 ─────────────────────────────────────────────────────────────────────
def test_an_evidence_check_counts_only_accepted_by_a_second_person(db, people):
    gov = _gov()
    a, b, _c = people
    assert _check(db, "G7", "be-owner-content")["ok"] is False                         # no evidence
    row = gov.be_record_gate_evidence(db, {"gate": "G7", "evidenceType": "BE-OWNER-CONTENT",
                                           "reference": "Content owner: TEST ONLY Person (Payroll Content lead)"}, a)
    db.commit()
    check = _check(db, "G7", "be-owner-content")
    assert check["ok"] is False and "submitted, not reviewed" in check["detail"]          # PENDING
    with pytest.raises(BadRequestException, match="four-eyes"):
        gov.be_decide_gate_evidence(db, row.id, "ACCEPTED", "looks right", a)            # the recorder
    gov.be_decide_gate_evidence(db, row.id, "ACCEPTED", "named and trained", b)
    db.commit()
    assert _check(db, "G7", "be-owner-content")["ok"] is True
    with pytest.raises(BadRequestException, match="already ACCEPTED"):
        gov.be_decide_gate_evidence(db, row.id, "REJECTED", "changed my mind", b)         # never changed again


def test_rejected_and_supporting_evidence_never_count_and_tags_belong_to_their_gate(db, people):
    gov = _gov()
    a, b, _c = people
    rejected = gov.be_record_gate_evidence(db, {"gate": "G5", "evidenceType": "BE-FILING-E2E",
                                                "reference": "log TEST-1"}, a)
    gov.be_decide_gate_evidence(db, rejected.id, "REJECTED", "no outage case", b)
    supporting = gov.be_record_gate_evidence(db, {"gate": "G5", "evidenceType": "SUPPORTING",
                                                  "reference": "dry-run notes"}, a)
    gov.be_decide_gate_evidence(db, supporting.id, "ACCEPTED", "useful", b)
    db.commit()
    assert _check(db, "G5", "be-filing-e2e")["ok"] is False
    with pytest.raises(BadRequestException, match="evidenceType for G1"):
        gov.be_record_gate_evidence(db, {"gate": "G1", "evidenceType": "BE-FILING-E2E", "reference": "x"}, a)
    with pytest.raises(BadRequestException, match="gate must be"):
        gov.be_record_gate_evidence(db, {"gate": "G9", "evidenceType": "SUPPORTING", "reference": "x"}, a)


def test_evidence_makes_a_gate_eligible_only_with_all_its_required_evidence(db, people):
    from app.modules.payroll import belgium_readiness as r

    gov = _gov()
    a, b, _c = people
    for tag in r.OWNER_TAGS:
        row = gov.be_record_gate_evidence(db, {"gate": "G7", "evidenceType": tag, "reference": f"{tag} owner"}, a)
        assert _gate(db, "G7")["passed"] is False                                        # not until all accepted
        gov.be_decide_gate_evidence(db, row.id, "ACCEPTED", "ok", b)
    db.commit()
    assert _gate(db, "G7")["passed"] is True                                             # G7 = owner evidence only
    for tag in r.SECURITY_TAGS:                                                          # G6 needs more than evidence
        row = gov.be_record_gate_evidence(db, {"gate": "G6", "evidenceType": tag, "reference": f"{tag} sign-off"}, a)
        gov.be_decide_gate_evidence(db, row.id, "ACCEPTED", "ok", b)
    db.commit()
    g6 = _gate(db, "G6")
    assert g6["passed"] is False and not next(c for c in g6["checks"] if c["key"] == "retention_decided")["ok"]


def test_the_database_refuses_self_accepted_evidence(db, people):
    from datetime import datetime

    from app.modules.payroll.models import PayrollBeGateEvidence

    a = people[0]
    db.add(PayrollBeGateEvidence(gate="G3", evidence_type="BE-CONNECTIVITY-DMFA", reference="x", status="ACCEPTED",
                                 recorded_by_id=a, decided_by_id=a, decided_at=datetime.utcnow()))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ── K3 ─────────────────────────────────────────────────────────────────────
def test_proposals_are_imported_proposed_and_nothing_is_decided(db, people):
    from app.modules.payroll.models import PayrollBeDecision

    gov = _gov()
    created = gov.be_import_decision_proposals(db, people[0])
    db.commit()
    assert {r.gap_key for r in created} == set(gov.DECISION_GAPS)                        # 8 drafted + G-11 / G-12
    assert all(r.status == "PROPOSED" and r.decided_value is None for r in created)
    assert gov.be_import_decision_proposals(db, people[0]) == []                         # idempotent
    assert db.query(PayrollBeDecision).filter(PayrollBeDecision.status != "PROPOSED").count() == 0
    assert all(d["state"] == "PROPOSED" for d in gov.be_list_decisions(db))


def test_deciding_is_four_eyes_and_a_later_decision_supersedes(db, people):
    from app.modules.payroll import belgium_service as be

    gov = _gov()
    a, b, c = people
    first = gov.be_propose_decision(db, {"gapKey": "G-21", "proposal": "TEST ONLY retention proposal"}, a)
    with pytest.raises(BadRequestException, match="four-eyes"):
        gov.be_decide(db, first.id, {"decidedValue": "x", "reason": "y"}, a)
    gov.be_decide(db, first.id, {"decidedValue": "TEST ONLY periods", "reason": "legal review"}, b)
    db.commit()
    assert next(d for d in be.owner_decisions(db) if d["key"] == "G-21")["state"] == "RECORDED"
    assert _check(db, "G6", "retention_decided")["ok"] is True                           # readiness reads it
    second = gov.be_propose_decision(db, {"gapKey": "G-21", "proposal": "TEST ONLY revised"}, c)
    gov.be_decide(db, second.id, {"decidedValue": "TEST ONLY revised periods", "reason": "update"}, a)
    db.commit()
    db.refresh(first)
    assert first.status == "SUPERSEDED" and first.superseded_by_id == second.id
    view = next(d for d in gov.be_list_decisions(db) if d["gapKey"] == "G-21")
    assert view["current"]["id"] == second.id and [h["status"] for h in view["history"]] == ["DECIDED", "SUPERSEDED"]
    with pytest.raises(BadRequestException, match="Only a PROPOSED"):
        gov.be_decide(db, first.id, {"decidedValue": "x", "reason": "y"}, c)


def test_a_decision_feeds_content_only_through_signed_rows(db, people):
    """G-02 (rounding) and G-26 (ONSS split) name the content rows the engine reads; deciding them changes no row —
    the engine keeps reading the signed pack (pending until a specialist enters and a second person signs)."""
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_belgium_canonical_packs import seed_belgium

    gov = _gov()
    a, b, _c = people
    pack = seed_belgium(db)["pack"]
    db.commit()
    before = {r.component_key: r.label for r in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id)}
    for gap in ("G-02", "G-26"):
        row = gov.be_propose_decision(db, {"gapKey": gap, "proposal": f"TEST ONLY {gap}"}, a)
        decided = gov.be_decide(db, row.id, {"decidedValue": f"TEST ONLY {gap}", "reason": "r"}, b)
        db.commit()
        view = gov.be_decision_view(db, decided)
        assert {k["key"] for k in view["contentKeys"]} == set(gov.DECISION_GAPS[gap][1])
        assert all(k["signed"] is False for k in view["contentKeys"])                   # content still pending
    after = {r.component_key: r.label for r in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id)}
    assert before == after and all(content.PENDING_MARK in after[k] for k in gov.DECISION_GAPS["G-02"][1])


def test_the_database_refuses_a_self_decided_record(db, people):
    from datetime import datetime

    from app.modules.payroll.models import PayrollBeDecision

    a = people[0]
    db.add(PayrollBeDecision(gap_key="G-01", proposal_text="x", status="DECIDED", decided_value="v",
                             proposed_by_id=a, decided_by_id=a, decided_at=datetime.utcnow()))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

"""Mexico final mile X1 — the decision register: seeded from
DECISIONS_PENDING.md and the gap register, four-eyes, versioned, typed answers
validated against the code that would read them, and never a change to a
calculation by itself. SYNTHETIC users; no worker data."""

from decimal import Decimal as D

import pytest

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, SA_B, _http

SA_C = 964


def _S():
    from app.modules.payroll import mexico_decision_service

    return mexico_decision_service


@pytest.fixture()
def seeded(db):
    out = _S().seed_decisions(db)
    db.commit()
    return out


def _id(db, code, version=1):
    from app.modules.payroll.models import PayrollMxDecision as M

    return db.query(M).filter(M.code == code, M.version == version).one().id


def _proposal(chosen, **extra):
    return {"chosen_option": chosen, "rationale": "SYNTHETIC rationale for a test", "cited_sources": ["S35"], **extra}


def test_the_register_is_seeded_from_the_documents_idempotently(db, seeded):
    codes = set(seeded["added"])
    assert {"D-01", "D-02", "D-07", "D-07b", "D-21", "D-22", "D-23", "C4", "C5", "C12"} <= codes
    assert "D-15" not in codes                                     # resolved by sources (W2-5)
    d01 = _S().get_mx_decision(db, _id(db, "D-01"))
    assert d01["status"] == "OPEN" and d01["gates"] == ["G1"] and d01["answerKind"] == "ROUNDING_RULE"
    assert d01["blockCodes"] == ["MX_ROUNDING_RULE_MISSING"] and d01["contentKeys"] == ["mx_rounding_rule"]
    assert len(d01["options"]) == 2 and "S35" in d01["questionSources"] and d01["citedSources"] == []
    assert d01["editable"] is False
    d07b = _S().get_mx_decision(db, _id(db, "D-07b"))
    assert d07b["allowedValues"] == ["UMA", "ZONE_MIN_WAGE"] and "485" in d07b["question"]
    again = _S().seed_decisions(db)
    assert again["added"] == [] and set(again["skipped"]) == codes


def test_typed_answers_are_checked_against_the_code_that_reads_them(db, seeded):
    from app.core.exceptions import BadRequestException

    S = _S()
    for code, bad in (("D-01", "ROUND:1"), ("D-01", "HALF_UP:0"), ("D-21", "GUESS"), ("D-02", "FORTNIGHT")):
        with pytest.raises(BadRequestException):
            S.propose_mx_decision(db, _id(db, code), _proposal(bad), SA_A.id)
    for missing in ({"rationale": ""}, {"cited_sources": []}):
        with pytest.raises(BadRequestException):
            S.propose_mx_decision(db, _id(db, "D-17"), {**_proposal("anything"), **missing}, SA_A.id)
    assert S.propose_mx_decision(db, _id(db, "D-01"), _proposal("HALF_DOWN:1"), SA_A.id)["status"] == "PROPOSED"
    assert S.propose_mx_decision(db, _id(db, "D-21"), _proposal("SAME_LABEL"), SA_A.id)["status"] == "PROPOSED"


def test_half_down_expresses_the_cff_whole_peso_option():
    """D-01 option 2 (CFF Art. 20 ¶10): 1–50 centavos down, 51–99 up."""
    from app.modules.payroll.engine.jurisdictions.mexico import rounding

    r = rounding.parse("HALF_DOWN:1")
    assert (r(D("10.50")), r(D("10.51")), r(D("10.01"))) == (D("10"), D("11"), D("10"))


def test_four_eyes_hash_ticket_and_immutability(db, seeded):
    from app.core.exceptions import BadRequestException

    S = _S()
    did = _id(db, "D-01")
    proposed = S.propose_mx_decision(db, did, _proposal("HALF_UP:0.01"), SA_A.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        S.approve_mx_decision(db, did, SA_A.id)
    approved = S.approve_mx_decision(db, did, SA_B.id)
    assert approved["status"] == "APPROVED" and approved["contentHash"] == proposed["contentHash"]
    t = approved["ticket"]
    assert t["contentKeys"] == ["mx_rounding_rule"] and t["value"] == "HALF_UP:0.01"
    assert t["citation"] == f"DECISION/D-01#{approved['contentHash'][:12]}" and "never an Active pack" in t["target"]
    for act in (lambda: S.propose_mx_decision(db, did, _proposal("HALF_EVEN:0.01"), SA_C),
                lambda: S.withdraw_mx_decision(db, did, {"reason": "x"}, SA_C)):
        with pytest.raises(BadRequestException):
            act()
    assert S.get_mx_decision(db, did)["chosenOption"] == "HALF_UP:0.01"
    with pytest.raises(BadRequestException, match="reference"):
        S.mark_mx_decision_transcribed(db, did, {"reference": ""}, SA_C)
    assert S.mark_mx_decision_transcribed(db, did, {"reference": "commit abc1234"}, SA_C)["status"] == "TRANSCRIBED"


def test_a_revision_supersedes_only_once_approved(db, seeded):
    from app.core.exceptions import BadRequestException

    S = _S()
    did = _id(db, "D-22")
    S.propose_mx_decision(db, did, _proposal("INCREMENTAL_MONTHLY"), SA_A.id)
    S.approve_mx_decision(db, did, SA_B.id)
    new = S.revise_mx_decision(db, did, SA_A.id)
    assert (new["version"], new["status"], new["supersedesId"]) == (2, "OPEN", did)
    with pytest.raises(BadRequestException, match="already has an open revision"):
        S.revise_mx_decision(db, did, SA_A.id)
    assert S.get_mx_decision(db, did)["status"] == "APPROVED"           # still in force
    S.propose_mx_decision(db, new["id"], _proposal("MONTHLY_TOTAL_LESS_WITHHELD"), SA_A.id)
    S.approve_mx_decision(db, new["id"], SA_B.id)
    assert S.get_mx_decision(db, did)["status"] == "SUPERSEDED"


def test_withdrawing_a_proposal_reopens_and_refusals_are_audited(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxConfigurationAudit as A

    S = _S()
    did = _id(db, "D-17")
    S.propose_mx_decision(db, did, _proposal("DAILY_SALARY_OVER_JORNADA_HOURS"), SA_A.id)
    seeded_sources = S.get_mx_decision(db, did)["questionSources"]
    back = S.withdraw_mx_decision(db, did, {"reason": "SYNTHETIC: wrong source"}, SA_B.id)
    assert back["status"] == "OPEN" and back["chosenOption"] is None and back["contentHash"] is None
    assert back["citedSources"] == [] and back["questionSources"] == seeded_sources     # the question keeps its own
    with pytest.raises(BadRequestException):
        S.withdraw_mx_decision(db, did, {"reason": ""}, SA_B.id)
    assert S.withdraw_mx_decision(db, did, {"reason": "SYNTHETIC: not needed"}, SA_B.id)["status"] == "WITHDRAWN"
    actions = [a.action for a in db.query(A).filter(A.entity_type == "mx_decision", A.entity_id == did)]
    assert {"propose", "withdraw", "refused"} <= set(actions)


def test_a_decision_never_changes_a_calculation_by_itself(db, seeded):
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.engine.jurisdictions.mexico import rounding
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    S = _S()
    did = _id(db, "D-01")
    S.propose_mx_decision(db, did, _proposal("HALF_UP:0.01"), SA_A.id)
    S.approve_mx_decision(db, did, SA_B.id)
    assert not any(r.key == "mx_rounding_rule" for r in c.MX_SCALAR_CONTENT)
    with pytest.raises(MXBlock) as exc:
        rounding.rounder(Content({}, []))
    assert exc.value.key == "MX_ROUNDING_RULE_MISSING"


def test_traceability_from_block_codes_and_open_decisions_per_gate(db, seeded):
    from app.modules.payroll import mexico_service

    S = _S()
    (hit,) = S.mx_decisions_for_block(db, "MX_ROUNDING_RULE_MISSING")
    assert hit["code"] == "D-01"
    before = S.open_by_gate(db)
    assert before["G1"] >= 5 and before.get("G5", 0) >= 5
    did = _id(db, "D-01")
    S.propose_mx_decision(db, did, _proposal("HALF_UP:0.01"), SA_A.id)
    S.approve_mx_decision(db, did, SA_B.id)
    assert S.open_by_gate(db)["G1"] == before["G1"] - 1
    gates = {g["gate"]: g for g in mexico_service.gate_checklists(db)["gates"]}
    assert gates["G1"]["openDecisions"] == before["G1"] - 1


def test_the_routes_are_super_admin_only_and_four_eyes_over_http(db, seeded):
    did = _id(db, "D-21")
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/decisions").status_code == 403
        assert c.post(f"{BASE}/decisions/{did}/propose", json={}).status_code == 403
    with _http(db, SA_A) as c:
        listed = c.get(f"{BASE}/decisions", params={"gate": "G1", "status": "OPEN"}).json()
        assert listed and all("G1" in d["gates"] and d["status"] == "OPEN" for d in listed)
        r = c.post(f"{BASE}/decisions/{did}/propose", json={"chosenOption": "SWAPPED", "rationale": "SYNTHETIC",
                                                          "citedSources": ["S30"]})
        assert r.status_code == 200 and r.json()["status"] == "PROPOSED"
        assert c.post(f"{BASE}/decisions/{did}/approve").status_code == 400            # the proposer
    with _http(db, SA_B) as c:
        assert c.post(f"{BASE}/decisions/{did}/approve").json()["status"] == "APPROVED"
        assert [d["code"] for d in c.get(f"{BASE}/decisions/by-block/MX_CFDI_TIMEZONE_RULE_INVALID").json()] == ["D-21"]

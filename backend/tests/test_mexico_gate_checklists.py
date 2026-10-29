"""Completion W5-3: readiness per gate — each G1–G8 checklist item is either
confirmed by a code check now (tagged `<!-- code: key -->` in its
CHECKLIST.md) or awaits the gate's signed evidence. Nothing here signs a gate."""

from datetime import datetime

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, SA_B, _http


def _view(db):
    from app.modules.payroll import mexico_service

    return mexico_service.gate_checklists(db)


def test_every_code_tag_is_a_known_check_and_every_check_is_used():
    from app.modules.payroll import mexico_service as S, mexico_sources

    root = mexico_sources.REPO_ROOT / "docs" / "mexico" / "release-gates"
    used = set()
    for gate, _label in S.GATES:
        for line in (root / gate / "CHECKLIST.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("- ["):
                m = S._CHECKLIST_ITEM.match(line)
                assert m, line                                       # every item parses
                if m.group("code"):
                    used.add(m.group("code"))
    assert used == set(S.GATE_CODE_CHECK_KEYS)


def test_every_gate_lists_its_items_split_into_code_and_evidence(db):
    body = _view(db)
    gates = {g["gate"]: g for g in body["gates"]}
    assert list(gates) == ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
    assert all(g["available"] and g["items"] for g in gates.values())
    assert (gates["G1"]["codeTotal"], gates["G6"]["codeTotal"], gates["G8"]["codeTotal"]) == (7, 0, 0)
    for g in gates.values():
        for item in g["items"]:
            assert item["kind"] in ("code", "evidence") and item["text"] and item["detail"]
            assert "**" not in item["text"] and "<!--" not in item["text"]
            if item["kind"] == "evidence":
                assert item["met"] is False and "awaits" in item["detail"]      # nothing is signed
    assert "Nothing here signs a gate" in body["note"]


def test_code_items_reflect_the_current_state(db):
    """No pack seeded: the pack checks are unmet with a reason; the decisions
    still open today (01 Diario, rounding, SDI source, CDMX D-06) are unmet;
    payroll is blocked in every state without an Active ISN pack."""
    items = {i["code"]: i for g in _view(db)["gates"] for i in g["items"] if i["kind"] == "code"}
    national = items["national_pack_approved"]
    assert national["met"] is False and "no national Mexico pack" in national["detail"]
    for key in ("sources_verified", "golden_pass", "cfdi_release_active", "pay_frequency_01", "rounding_rule",
                "cfdi_sdi_source", "isn_pack_approved", "isn_d06"):
        assert items[key]["met"] is False, key
    assert items["unsupported_states_blocked"]["met"] is True and "32" in items["unsupported_states_blocked"]["detail"]


def test_a_signed_gate_meets_its_evidence_items(db):
    from app.modules.payroll.models import SourceArtifact

    db.add(SourceArtifact(agency="SYNTHETIC", title="G8 evidence (SYNTHETIC)", form_number="MX-GATE-G8",
                          created_by_id=SA_A.id, reviewer_id=SA_B.id, reviewer_approved_at=datetime.utcnow(),
                          file_path="evidence/synthetic.pdf"))
    db.commit()
    gates = {g["gate"]: g for g in _view(db)["gates"]}
    assert gates["G8"]["state"] == "SIGNED"
    assert all(i["met"] and "signed gate evidence" in i["detail"] for i in gates["G8"]["items"])
    assert not any(i["met"] for i in gates["G7"]["items"])


def test_the_route_is_super_admin_only(db):
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/readiness/gate-checklists").status_code == 403
    with _http(db, SA_A) as c:
        r = c.get(f"{BASE}/readiness/gate-checklists")
    assert r.status_code == 200 and len(r.json()["gates"]) == 8

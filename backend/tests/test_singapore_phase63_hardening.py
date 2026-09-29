"""
tests/test_singapore_phase63_hardening.py
-----------------------------------------
Phase 6.3 Decision A — the shared report-template lifecycle no longer lets
Draft / Review jump straight to Published: every release passes through
Approved (which only set_report_template_approver's distinct-approver
action or an explicit Approved step reaches), then Published -> Active ->
Superseded. Exercised on Singapore templates plus one non-Singapore
template, because REPORT_TEMPLATE_TRANSITIONS is shared by every
jurisdiction. Self-approval, released-approval and correction-versioning
protections are re-proved on top of the tighter graph.

app.* imports are lazy (tests/_db_safety.py).
"""

import pytest

MAKER, CHECKER, PUBLISHER = 101, 202, 303


def _template(db, key="SG-P63-T", country="SG", report_type="SG_PAYROLL_REGISTER", version="1.0"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name="register", reportType=report_type, jurisdictionCountry=country,
        reportingYear="2026", version=version), actor_id=MAKER)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(
        componentKey="employer_info", label="Employer Information", sortOrder=0), actor_id=MAKER)
    db.refresh(t)
    return t


def _status(db, t, status, actor=PUBLISHER):
    from app.modules.payroll import service

    return service.set_report_template_status(db, t.id, status, actor_id=actor)


def test_draft_to_published_is_rejected_even_with_a_distinct_approver(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    with pytest.raises(BadRequestException, match="cannot move from Draft to Published"):
        _status(db, t, "Published")
    # An approval recorded then sent back to Draft still cannot shortcut to Published.
    service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    _status(db, service.get_report_template(db, t.id), "Draft", actor=MAKER)
    with pytest.raises(BadRequestException, match="requires an Approved template"):
        _status(db, service.get_report_template(db, t.id), "Published")
    assert service.get_report_template(db, t.id).status == "Draft"


def test_review_to_published_is_rejected_even_with_a_distinct_approver(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    _status(db, t, "Review", actor=MAKER)
    service.set_report_template_approver(db, t.id, actor_id=CHECKER)       # approver recorded, still Review
    t = service.get_report_template(db, t.id)
    assert (t.status, t.approved_by_id) == ("Review", CHECKER)
    with pytest.raises(BadRequestException, match="cannot move from Review to Published"):
        _status(db, t, "Published")
    assert service.get_report_template(db, t.id).status == "Review"


def test_full_chain_draft_review_approved_published_active_succeeds(db):
    from app.modules.payroll import service

    t = _template(db)
    _status(db, t, "Review", actor=MAKER)
    service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    t = _status(db, service.get_report_template(db, t.id), "Approved")
    assert t.status == "Approved"
    t = _status(db, t, "Published")
    assert t.status == "Published"
    t = _status(db, t, "Active")
    assert (t.status, t.approved_by_id) == ("Active", CHECKER)


def test_approve_action_then_published_then_active_succeeds(db):
    """The standard path every other jurisdiction's tests use: the approve
    action auto-advances Draft -> Approved, then Published, then Active."""
    from app.modules.payroll import service

    t = _template(db)
    t = service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    assert t.status == "Approved"
    assert _status(db, t, "Published").status == "Published"
    assert _status(db, t, "Active").status == "Active"


@pytest.mark.parametrize("target", ["Draft", "Approved", "Review", "Published"])
def test_active_cannot_return_to_an_earlier_state(db, target):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = service.set_report_template_approver(db, _template(db).id, actor_id=CHECKER)
    t = _status(db, _status(db, t, "Published"), "Active")
    with pytest.raises(BadRequestException, match="cannot move from Active"):
        _status(db, t, target)
    assert service.get_report_template(db, t.id).status == "Active"


@pytest.mark.parametrize("target", ["Draft", "Review", "Approved", "Published", "Active", "Superseded"])
def test_superseded_is_terminal(db, target):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = service.set_report_template_approver(db, _template(db).id, actor_id=CHECKER)
    t = _status(db, _status(db, _status(db, t, "Published"), "Active"), "Superseded")
    with pytest.raises(BadRequestException, match="Superseded is final"):
        _status(db, t, target)
    assert service.get_report_template(db, t.id).status == "Superseded"


def test_self_approval_still_blocks_publication(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    with pytest.raises(BadRequestException, match="cannot approve it"):             # completion programme:
        service.set_report_template_approver(db, t.id, actor_id=MAKER)             # refused at Approve now
    t = service.get_report_template(db, t.id)
    t.approved_by_id, t.status = MAKER, "Approved"                                  # and still at Publish
    db.commit()
    with pytest.raises(BadRequestException, match="distinct approver"):
        _status(db, t, "Published", actor=MAKER)


def test_released_approval_cannot_be_replaced(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = service.set_report_template_approver(db, _template(db).id, actor_id=CHECKER)
    t = _status(db, t, "Published")
    with pytest.raises(BadRequestException, match="release evidence"):
        service.set_report_template_approver(db, t.id, actor_id=999)
    assert service.get_report_template(db, t.id).approved_by_id == CHECKER


def test_correction_after_release_is_a_new_version_that_must_be_approved_again(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    v1 = service.set_report_template_approver(db, _template(db).id, actor_id=CHECKER)
    v1 = _status(db, _status(db, v1, "Published"), "Active")
    v2 = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=v1.template_key, name="register", reportType=v1.report_type, jurisdictionCountry="SG",
        reportingYear="2026", version="1.1"), actor_id=MAKER)
    assert (v2.status, v2.previous_version_id, v2.approved_by_id) == ("Draft", v1.id, None)
    with pytest.raises(BadRequestException):                              # the new version cannot shortcut either
        _status(db, v2, "Published")
    v2 = service.set_report_template_approver(db, v2.id, actor_id=CHECKER)
    assert _status(db, v2, "Published").status == "Published"
    assert service.get_report_template(db, v1.id).status == "Active"      # v1 untouched until superseded


def test_tightened_graph_applies_to_other_jurisdictions(db):
    """REPORT_TEMPLATE_TRANSITIONS is shared: a non-Singapore template gets
    the same Approved-before-Published rule, and its normal release path
    (approve -> Published -> Active) is unchanged."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db, key="IN-P63-T", country="IN", report_type="TDS")
    with pytest.raises(BadRequestException, match="cannot move from Draft to Published"):
        _status(db, t, "Published")
    t = service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    assert _status(db, _status(db, t, "Published"), "Active").status == "Active"


def test_transition_graph_publishes_only_from_approved():
    from app.modules.payroll.service import REPORT_TEMPLATE_TRANSITIONS

    assert [s for s, nxt in REPORT_TEMPLATE_TRANSITIONS.items() if "Published" in nxt] == ["Approved"]
    assert [s for s, nxt in REPORT_TEMPLATE_TRANSITIONS.items() if "Active" in nxt] == ["Published"]
    assert REPORT_TEMPLATE_TRANSITIONS["Superseded"] == ()


def test_status_route_returns_the_structured_400_for_a_shortcut(db):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_super_admin
    from app.database import get_db
    from app.main import app

    t = _template(db)

    class _SuperAdmin:
        id = PUBLISHER
        role = "super_admin"
        organization_id = None

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_super_admin] = lambda: _SuperAdmin()
    app.dependency_overrides[get_db] = lambda: db
    try:
        r = TestClient(app).put(f"/api/super-admin/report-templates/{t.id}/status", json={"status": "Published"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
    assert r.status_code == 400, r.text
    body = r.json()
    assert (body["success"], body["error"]) == (False, "BAD_REQUEST")
    assert "cannot move from Draft to Published" in body["message"]


# ── Decision B — hotfix activation audit (shared route, Singapore evidence) ─
# Emergency hotfix activation bypasses ONLY the distinct-approver gate and
# the Singapore approver-!=-activator rule (F2); every Singapore evidence
# gate still applies. Phase 6.3 fixed one concrete defect: a REFUSED hotfix
# used to commit its self-approval anyway, leaving a phantom approval (with
# no approval audit row) that a second Super Admin could activate on.

def _sg_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


def _hotfix(db, pack, actor=MAKER):
    from app.modules.payroll import service

    return service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-6.3", "emergency statutory fix", actor_id=actor)


def test_refused_sg_hotfix_leaves_no_phantom_approval(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    with pytest.raises(BadRequestException, match="passing golden-vector"):         # no SG golden PASS yet
        _hotfix(db, pack)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)
    service.run_golden_test_certification(db, "SG", actor_id=CHECKER)
    with pytest.raises(BadRequestException, match="distinct approver"):              # nobody can ride it
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER)
    db.refresh(pack)
    assert pack.status == "Draft"


def test_refused_hotfix_on_another_country_leaves_no_phantom_approval(db):
    """The fix is in the shared hotfix function — a US pack refused by the
    US source-evidence gate keeps no approval either."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="US-P63-HOTFIX", jurisdiction_country="US", pack_type="tax", version="1.0",
                            status="Draft")
    db.add(pack)
    db.commit()
    with pytest.raises(BadRequestException, match="Source Evidence"):
        _hotfix(db, pack)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)


def test_hotfix_cannot_skip_singapore_evidence_gates(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    service.run_golden_test_certification(db, "SG", actor_id=CHECKER)
    source = pack.source_document_id
    pack.source_document_id = None
    db.commit()
    with pytest.raises(BadRequestException, match="Source Evidence"):
        _hotfix(db, pack)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)
    pack.source_document_id = source
    pack.effective_from = None
    db.commit()
    with pytest.raises(BadRequestException, match="Effective From"):
        _hotfix(db, pack)


def test_successful_sg_hotfix_is_the_audited_emergency_path(db):
    """Unchanged behaviour: a lone Super Admin may activate an evidenced,
    golden-PASS Singapore pack in an emergency, and it is always recorded
    for mandatory retrospective review — while the normal path still
    refuses that same lone actor (F2)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation, TaxConfigurationAudit

    pack = _sg_pack(db)
    service.run_golden_test_certification(db, "SG", actor_id=MAKER)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=MAKER)
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=MAKER)
    row = _hotfix(db, pack, actor=MAKER)
    assert (row.status, row.approved_by_id, row.updated_by_id) == ("Active", MAKER, MAKER)
    hf = db.query(PackHotfixActivation).filter(PackHotfixActivation.jurisdiction_pack_id == pack.id).one()
    assert (hf.incident_id, hf.activated_by_id, hf.reviewed) == ("INC-6.3", MAKER, False)
    assert any(a.action == "status_change" and a.new_value == {"status": "Active"}
               for a in db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                               TaxConfigurationAudit.entity_id == pack.id))
    with pytest.raises(BadRequestException, match="cannot move directly"):          # still no downgrade
        service.set_jurisdiction_pack_status(db, pack.id, "Draft", actor_id=CHECKER)


def test_hotfix_requires_incident_and_justification(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    for incident, why in (("", "x"), ("INC", " ")):
        with pytest.raises(BadRequestException, match="required"):
            service.activate_jurisdiction_pack_hotfix(db, pack.id, incident, why, actor_id=MAKER)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)

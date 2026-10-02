"""
tests/test_singapore_phase610_registry.py
-----------------------------------------
Singapore Phase 6.10 — the owner's registry step (PLANNED <-> AVAILABLE), the
only thing that opens Singapore onboarding.

Before this phase the jurisdiction_service_registry row had no API or service
path at all: opening onboarding meant a raw UPDATE with no audit row and no
check that any gate had passed. transition_sg_service_registry now:
  - refuses AVAILABLE (one "refused" audit row, nothing changed) unless every
    registry-transition requirement of the readiness summary is met at that
    moment — Active pack, golden PASS, all 11 templates Active, configuration /
    database / migration PASS, G1–G8 accepted, D1–D3 recorded AND in force,
    the deploy owner's SG-OPS-DEPLOYMENT sign-off accepted, no unreviewed hotfix;
  - always allows closing an AVAILABLE Singapore back to PLANNED (rollback);
  - refuses every other value (LIMITED_AVAILABILITY would silently open
    onboarding — the onboarding gate treats anything but PLANNED /
    NOT_AVAILABLE as open);
  - records both directions with the owner's reason and an evidence snapshot.

Every artifact here is disposable test data in a throwaway database; nothing
represents real regulator evidence. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date

import pytest

A, B = 101, 202                      # two distinct Super Admin actors
AS_OF = date(2026, 9, 25)


@pytest.fixture(autouse=True)
def _uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path))          # evidence files never leave the test


@pytest.fixture
def at_head(db, monkeypatch):
    """SQLite create_all has no alembic_version; model the migrated database."""
    from app.modules.payroll import service

    state = service._sg_database_state(db)
    monkeypatch.setattr(service, "_sg_database_state",
                        lambda _db: {**state, "databaseHeads": list(state["codeHeads"]), "atHead": True})


def _activation(db):
    from app.modules.payroll import service

    return service.get_sg_statutory_summary(db, AS_OF)["activationReadiness"]


def _unmet(db):
    return {r["key"] for r in _activation(db)["registryTransition"]["requirements"] if not r["met"]}


def _transition(db, target, actor=A, reason="Owner change record CR-1"):
    from app.modules.payroll import service

    return service.transition_sg_service_registry(db, target, reason, actor_id=actor, as_of=AS_OF)


def _registry(db):
    from app.modules.billing.models import JurisdictionServiceRegistry

    db.expire_all()
    return db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").one()


def _audits(db, action):
    from app.modules.payroll.models import TaxConfigurationAudit

    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "jurisdiction_service_registry",
                    TaxConfigurationAudit.action == action).order_by(TaxConfigurationAudit.id).all())


def _accepted_evidence(db, tag):
    """Register (A), upload, and accept (B, a different Super Admin)."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    art = service.create_source_artifact(db, SourceArtifactCreate(
        agency="Test evidence", title=f"Disposable {tag}", formNumber=tag), actor_id=A)
    service.upload_source_artifact_file(db, art.id, f"{tag}.pdf", "application/pdf", f"test {tag}".encode(), actor_id=A)
    return service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=B, today=AS_OF)


def _recorded_decision(db, key, value):
    from app.modules.payroll import service

    art = service.record_sg_decision(db, key, value, f"Test decision {key}", actor_id=A)
    service.upload_source_artifact_file(db, art.id, f"{key}.pdf", "application/pdf", b"memo", actor_id=A)
    return service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=B, today=AS_OF)


def _seed_all(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed_templates
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    monkeypatch.setattr(seed_templates, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed_templates.run()
    return pack


def _activate_pack(db, pack):
    from app.modules.payroll import service

    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A, reason="test activation")


def _activate_templates(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG").all():
        service.set_report_template_approver(db, t.id, actor_id=B)
        service.set_report_template_status(db, t.id, "Published", actor_id=A)
        service.set_report_template_status(db, t.id, "Active", actor_id=A)


def _everything_but_the_deploy_signoff(db, monkeypatch):
    pack = _seed_all(db, monkeypatch)
    _accepted_evidence(db, "SG-GATE-G1")                       # G1 before the pack (runbook §G–H)
    _activate_pack(db, pack)
    _activate_templates(db)
    for key, value in (("D1", "EXPORT_ONLY"), ("D2", "RESTRICTED"), ("D3", "SG_ONLY")):
        _recorded_decision(db, key, value)
    for n in range(2, 9):
        _accepted_evidence(db, f"SG-GATE-G{n}")
    return pack


def test_a_seeded_singapore_cannot_be_made_available_and_the_refusal_is_audited(db, monkeypatch, at_head):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    _seed_all(db, monkeypatch)
    assert _registry(db).availability == "PLANNED"
    unmet = _unmet(db)
    assert {"pack_active", "golden_vectors", "templates_active", "deployment_signoff"} <= unmet
    assert {f"gate_G{n}" for n in range(1, 9)} <= unmet and {"decision_D1", "decision_D2", "decision_D3"} <= unmet
    with pytest.raises(BadRequestException, match="cannot be made AVAILABLE"):
        _transition(db, "AVAILABLE")
    assert _registry(db).availability == "PLANNED"
    refused = _audits(db, "refused")
    assert len(refused) == 1 and refused[0].actor_id == A
    assert refused[0].new_value["attempted"] == "availability:AVAILABLE"
    assert set(refused[0].new_value["unmet"]) == unmet
    assert _audits(db, "status_change") == []
    assert get_jurisdiction_onboarding_block_reason(db, "SG") is not None          # onboarding stays closed


def test_available_needs_every_requirement_then_opens_onboarding_and_planned_closes_it(db, monkeypatch, at_head):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    pack = _everything_but_the_deploy_signoff(db, monkeypatch)
    assert _unmet(db) == {"deployment_signoff"}                   # the one remaining owner record
    with pytest.raises(BadRequestException, match="Deploy-owner sign-off"):
        _transition(db, "AVAILABLE")
    assert _registry(db).availability == "PLANNED"

    signoff = _accepted_evidence(db, "SG-OPS-DEPLOYMENT")
    dash = {r["key"]: r["status"] for r in _activation(db)["readinessDashboard"]}
    assert dash["deployment"] == "PASS"
    assert _activation(db)["registryTransition"]["availableAllowed"] is True
    assert get_jurisdiction_onboarding_block_reason(db, "SG") is not None          # still closed until the step

    assert _transition(db, "AVAILABLE", actor=B, reason="Go-live CR-7").availability == "AVAILABLE"
    assert get_jurisdiction_onboarding_block_reason(db, "SG") is None
    change = _audits(db, "status_change")[-1]
    assert change.actor_id == B and change.reason == "Go-live CR-7"
    assert (change.old_value["availability"], change.new_value["availability"]) == ("PLANNED", "AVAILABLE")
    evidence = change.new_value["evidence"]
    assert evidence["pack"] == {"packId": pack.pack_id, "version": pack.version}
    assert evidence["deploymentSignoff"] == signoff.id
    assert set(evidence["gates"]) == {f"G{n}" for n in range(1, 9)} and all(evidence["gates"].values())
    assert evidence["decisions"] == {"D1": "EXPORT_ONLY", "D2": "RESTRICTED", "D3": "SG_ONLY"}

    assert _transition(db, "PLANNED", reason="Rollback CR-8").availability == "PLANNED"      # runbook §N
    assert get_jurisdiction_onboarding_block_reason(db, "SG") is not None
    assert [a.new_value["availability"] for a in _audits(db, "status_change")] == ["AVAILABLE", "PLANNED"]


def test_a_decision_recorded_but_not_in_force_keeps_singapore_closed(db, monkeypatch, at_head):
    from app.modules.payroll import service

    pack = _seed_all(db, monkeypatch)
    _recorded_decision(db, "D2", "PROHIBITED")                    # differs from SG_HOTFIX_POLICY (RESTRICTED)
    assert service.SG_HOTFIX_POLICY == "RESTRICTED"
    item = next(r for r in _activation(db)["registryTransition"]["requirements"] if r["key"] == "decision_D2")
    assert item["met"] is False and "differs" in item["detail"] and "code change" in item["detail"]
    assert pack.status == "Draft"


def test_only_planned_and_available_are_governed_singapore_states(db, monkeypatch, at_head):
    from app.core.exceptions import BadRequestException

    _seed_all(db, monkeypatch)
    for value in ("LIMITED_AVAILABILITY", "PARTNER_SUPPORTED", "NOT_AVAILABLE", ""):
        with pytest.raises(BadRequestException, match="governed Singapore state"):
            _transition(db, value)
    with pytest.raises(BadRequestException, match="already PLANNED"):
        _transition(db, "PLANNED")
    with pytest.raises(BadRequestException, match="reason"):
        _transition(db, "AVAILABLE", reason="  ")
    with pytest.raises(BadRequestException, match="identified Super Admin"):
        _transition(db, "AVAILABLE", actor=None)
    assert _registry(db).availability == "PLANNED"
    assert len(_audits(db, "refused")) == 5 and _audits(db, "status_change") == []


def test_there_is_no_registry_row_to_open_without_the_seed(db, at_head):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="no Singapore registry row"):
        _transition(db, "AVAILABLE")
    assert _audits(db, "refused")[0].new_value["attempted"] == "availability:AVAILABLE"


def test_the_deploy_signoff_is_gate_evidence_with_maker_checker(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    _seed_all(db, monkeypatch)
    art = service.create_source_artifact(db, SourceArtifactCreate(
        agency="Deploy owner", title="Deploy sign-off", formNumber="SG-OPS-DEPLOYMENT"), actor_id=A)
    service.upload_source_artifact_file(db, art.id, "signoff.pdf", "application/pdf", b"signed", actor_id=A)
    assert _activation(db)["deploymentSignoff"]["status"] == "UNDER_REVIEW"
    with pytest.raises(BadRequestException, match="different"):
        service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=A, today=AS_OF)
    service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=B, today=AS_OF)
    signoff = _activation(db)["deploymentSignoff"]
    assert signoff["status"] == "PASS" and signoff["submittedArtifactId"] == art.id and signoff["reviewedBy"] == B


def test_the_registry_route_is_platform_super_admin_only():
    from app.core.dependencies import get_current_super_admin
    from app.main import app

    path = "/api/super-admin/compliance/singapore/service-registry"
    route = next(r for r in app.routes if getattr(r, "path", None) == path and "POST" in getattr(r, "methods", ()))
    assert get_current_super_admin in {d.call for d in route.dependant.dependencies}


def test_no_other_countrys_registry_row_is_touched(db, monkeypatch, at_head):
    from app.modules.billing.models import JurisdictionServiceRegistry

    db.add(JurisdictionServiceRegistry(country="AU", availability="PLANNED"))
    db.commit()
    _everything_but_the_deploy_signoff(db, monkeypatch)
    _accepted_evidence(db, "SG-OPS-DEPLOYMENT")
    _transition(db, "AVAILABLE")
    db.expire_all()
    assert db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "AU").one().availability == "PLANNED"

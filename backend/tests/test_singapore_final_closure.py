"""
tests/test_singapore_final_closure.py
-------------------------------------
Singapore final closure programme (2026-09-29, second pass). One test group
per closed gap; each fails on the tree before this pass.

  Hotfix policy     explicit switch (owner decision D2), default = the
                    behaviour in force; PROHIBITED / FOLLOW_UP_REQUIRED enforced
                    and their refusals audited.
  Authority errors  IRAS / CPF Board rejection messages captured verbatim on a
                    REJECTED / UNKNOWN outcome, refused on any other step.
  IR8A batches      each row carries its 200-record myTax Portal batch.
  IR8A guard        the Phase 6.7 refusal no longer claims revision/amendment
                    is unimplemented.
  Void refusals     a refused void of filing evidence is audited.
  Super Admin       service availability, hotfix policy, AIS setting (no tenant
                    data), LQS quota readiness, production gates from the
                    backend — never shown as passed.
  Seeding           re-seeding never demotes, re-approves or rewrites a
                    promoted / superseded Singapore template.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date

import pytest

A, B, C = 101, 202, 303


def _audits(db, entity_type, entity_id, action=None):
    from app.modules.payroll.models import TaxConfigurationAudit

    q = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == entity_type,
                                               TaxConfigurationAudit.entity_id == entity_id)
    if action:
        q = q.filter(TaxConfigurationAudit.action == action)
    return q.order_by(TaxConfigurationAudit.id).all()


def _gated_pack(db):
    """The canonical SG pack (source evidence + effective-from) with a
    closed effective window, plus a PASS golden run."""
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    pack.effective_to = date(2029, 12, 31)
    db.commit()
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    return pack


def _later_pack(db, source_id):
    from app.modules.payroll.models import JurisdictionPack

    later = JurisdictionPack(pack_id="SG-CLOSURE-2030", version="1.0", jurisdiction_country="SG", pack_type="tax",
                             status="Approved", effective_from=date(2030, 1, 1), source_document_id=source_id,
                             approved_by_id=B)
    db.add(later)
    db.commit()
    return later


# ══ Hotfix policy (D2) ═════════════════════════════════════════════════════

def test_hotfix_policy_default_is_the_behaviour_in_force_and_is_reported(db):
    from app.modules.payroll import service

    assert service.SG_HOTFIX_POLICY == "RESTRICTED"
    assert service.SG_HOTFIX_POLICIES == ("RESTRICTED", "PROHIBITED", "FOLLOW_UP_REQUIRED")
    policy = service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]["statutoryPack"]["hotfixPolicy"]
    assert policy == {"current": "RESTRICTED", "options": ["RESTRICTED", "PROHIBITED", "FOLLOW_UP_REQUIRED"],
                      "unreviewedHotfixes": 0}


def test_prohibited_policy_refuses_and_audits_a_sg_hotfix(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation

    pack = _gated_pack(db)
    monkeypatch.setattr(service, "SG_HOTFIX_POLICY", "PROHIBITED")
    with pytest.raises(BadRequestException, match="PROHIBITED"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-1", "emergency", actor_id=A)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)
    assert db.query(PackHotfixActivation).count() == 0
    [row] = _audits(db, "jurisdiction_pack", pack.id, "refused")
    assert row.new_value == {"attempted": "Active", "result": "REFUSED", "path": "hotfix"}


def test_follow_up_policy_blocks_further_activations_until_the_hotfix_is_reviewed(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _gated_pack(db)
    monkeypatch.setattr(service, "SG_HOTFIX_POLICY", "FOLLOW_UP_REQUIRED")
    service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-2", "emergency", actor_id=A)
    later = _later_pack(db, pack.source_document_id)
    with pytest.raises(BadRequestException, match="awaiting its retrospective review"):
        service.set_jurisdiction_pack_status(db, later.id, "Active", actor_id=C)            # normal path
    with pytest.raises(BadRequestException, match="awaiting its retrospective review"):
        service.activate_jurisdiction_pack_hotfix(db, later.id, "INC-3", "again", actor_id=A)   # hotfix path
    db.refresh(later)
    assert later.status == "Approved" and len(_audits(db, "jurisdiction_pack", later.id, "refused")) == 2
    [activation] = service.list_pack_hotfix_activations(db, reviewed=False)
    service.review_pack_hotfix_activation(db, activation.id, "verified", actor_id=B)
    assert service.set_jurisdiction_pack_status(db, later.id, "Active", actor_id=C).status == "Active"


def test_restricted_policy_does_not_require_the_review_before_the_next_activation(db):
    from app.modules.payroll import service

    pack = _gated_pack(db)
    service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-4", "emergency", actor_id=A)
    later = _later_pack(db, pack.source_document_id)
    assert service.set_jurisdiction_pack_status(db, later.id, "Active", actor_id=C).status == "Active"


# ══ Authority error capture ════════════════════════════════════════════════

def _ir8a_original(db, organization, outcome=None):
    from tests.test_singapore_phase68_ir8a_modifications import _employee, _original, _pack, _payslip, _template

    template = _template(db)
    pack = _pack(db)
    for code, gross in (("CLA", "6000"), ("CLB", "4000"), ("CLC", "5000")):
        _payslip(db, organization, _employee(db, organization, code), date(2026, 3, 31), gross, "0", pack)
    return template, _original(db, organization, template, outcome=outcome)


def test_iras_rejection_messages_are_captured_verbatim(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    _template, base = _ir8a_original(db, organization)
    errors = ["Record 2: NRIC/FIN invalid", "Record 3: Gross salary must not be blank"]
    with pytest.raises(BadRequestException, match="REJECTED or UNKNOWN"):
        service.transition_sg_ir8a(db, organization.id, base.id, "ACKNOWLEDGED", actor_id=B, reference="IRAS-1",
                                   errors=errors)
    view = service.transition_sg_ir8a(db, organization.id, base.id, "REJECTED", actor_id=B, reference="IRAS-REJ-1",
                                      errors=errors + ["  "])
    assert view["acknowledgement"] == {"outcome": "REJECTED", "reference": "IRAS-REJ-1", "errors": errors}
    assert view["history"][-1]["errors"] == errors


def test_cpf_board_rejection_messages_are_captured_on_the_ezpay_record(db, organization):
    from app.modules.payroll import service
    from tests.test_singapore_completion_programme import _sg_report

    row = _sg_report(db, organization, "SG_CPF_EZPAY", "SUBMITTED")
    out = service.transition_sg_cpf_ezpay(db, organization.id, row.id, "REJECTED", actor_id=B, reference="CPF-REJ",
                                          errors=["Invalid CSN"])
    assert out.reconciliation["history"][-1]["errors"] == ["Invalid CSN"]


def test_transition_request_schema_accepts_authority_errors():
    from app.modules.payroll.schemas import SGCpfEzpayTransitionRequest

    body = SGCpfEzpayTransitionRequest.model_validate({"status": "REJECTED", "reference": "R", "errors": ["x"]})
    assert body.errors == ["x"]


# ══ IR8A: myTax Portal batches, guard message ══════════════════════════════

def test_ir8a_rows_carry_their_mytax_portal_submission_batch(db, organization, monkeypatch):
    from app.modules.payroll import service

    monkeypatch.setattr(service, "_SG_MYTAX_MAX_RECORDS", 2)
    _template, base = _ir8a_original(db, organization)
    data = base.rendered_data
    rows = data["employeeRows"]
    assert [r["submissionBatch"] for r in rows] == [1, 1, 2]
    assert [r["employeeName"] for r in rows] == sorted(r["employeeName"] for r in rows)
    assert data["myTaxPortalSubmission"]["batches"] == [{"batch": 1, "records": 2}, {"batch": 2, "records": 1}]
    assert data["myTaxPortalSubmission"]["submissions"] == 2


def test_the_acknowledged_guard_points_to_the_built_modification_workflow(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    template, base = _ir8a_original(db, organization, outcome="ACKNOWLEDGED")
    again = service.generate_sg_ir8a(db, organization.id, template.id, 2026, actor_id=A)
    with pytest.raises(BadRequestException) as exc:
        service.transition_sg_ir8a(db, organization.id, again.id, "SUBMITTED_MANUALLY", actor_id=B, reference="X")
    assert "not implemented" not in exc.value.message and f"extract {base.id}" in exc.value.message


# ══ Void refusals audited ══════════════════════════════════════════════════

def test_a_refused_void_of_filing_evidence_is_audited_once(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from tests.test_singapore_completion_programme import _sg_report

    for report_type, status in (("SG_IR8A", "ACKNOWLEDGED"), ("SG_CPF_EZPAY", "ACCEPTED")):
        row = _sg_report(db, organization, report_type, status)
        with pytest.raises(BadRequestException, match="cannot be voided"):
            service.void_generated_report(db, organization.id, row.id, "oops", actor_id=B)
        [audit] = _audits(db, "generated_report", row.id, "refused")
        assert (audit.actor_id, audit.old_value, audit.new_value) == (
            B, {"status": status}, {"attempted": "Void", "result": "REFUSED"})


# ══ Super Admin governance / readiness facts ═══════════════════════════════

def test_readiness_reports_service_availability_ais_setting_and_gates(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import service

    ready = service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]
    assert ready["serviceAvailability"] is None
    db.add(JurisdictionServiceRegistry(country="SG", availability="PLANNED", filing_responsibility="NOT_OFFERED"))
    db.commit()
    ready = service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]
    assert ready["serviceAvailability"]["availability"] == "PLANNED"
    ais = ready["aisSubmissionModeSetting"]                  # the setting's definition, never tenant data
    assert ais["options"] == ["EXPORT_ONLY", "DIRECT_API"]
    assert ais["optionStates"]["DIRECT_API"] == "EXTERNAL_INTEGRATION_REQUIRED"
    gates = ready["productionGates"]
    assert [g["key"] for g in gates] == [f"G{i}" for i in range(1, 9)]
    assert all(g["status"] in ("EVIDENCE_REQUIRED", "BUSINESS_DECISION_REQUIRED") and g["evidenceRecorded"] is None
               for g in gates)


def test_lqs_quota_is_an_explicit_fail_safe_operations_item(db):
    from app.modules.payroll import service

    ops = next(s for s in service.get_sg_statutory_summary(db, date(2026, 9, 25))["sections"] if s["key"] == "operations")
    quota = next(i for i in ops["values"]["items"] if i["key"] == "lqs_quota")
    assert quota["state"] == "EXTERNAL_DATA_REQUIRED" and quota["generator"] == "Not built"
    assert "lqs_quota" not in ops["missing"]                  # an external blocker, not a missing internal template


# ══ Seeding never demotes ══════════════════════════════════════════════════

def test_reseeding_never_demotes_reapproves_or_rewrites_a_promoted_sg_template(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed
    from app.modules.payroll.models import ReportTemplate

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()
    promoted = {"SG-IR8A": ("Approved", B), "SG-SDL-MONTHLY": ("Published", B), "SG-CPF-EZPAY": ("Active", B),
                "SG-PWM-COMPLIANCE": ("Superseded", C)}
    for key, (status, approver) in promoted.items():
        t = db.query(ReportTemplate).filter(ReportTemplate.template_key == key).one()
        t.status, t.approved_by_id = status, approver
    db.commit()
    before = {t.template_key: (t.id, t.status, t.approved_by_id, t.description, t.updated_at)
              for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    seed.run()
    after = {t.template_key: (t.id, t.status, t.approved_by_id, t.description, t.updated_at)
             for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    assert len(after) == 11
    for key in promoted:
        assert after[key] == before[key], key


# ══ Readiness: pending decisions / external dependencies (§20 visibility) ══

def test_readiness_lists_the_open_owner_decisions_with_the_value_in_force(db):
    from app.modules.payroll import service

    ready = service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]
    decisions = {d["key"]: d for d in ready["pendingDecisions"]}
    assert set(decisions) == {"D1", "D2", "D3"}
    assert all(d["status"] == "BUSINESS_DECISION_REQUIRED" for d in decisions.values())
    assert decisions["D2"]["inForce"] == service.SG_HOTFIX_POLICY
    # Sweden opts into the same controls under its own spec (ZP-SE-ENG-001);
    # that is a per-country opt-in, not the ALL_COUNTRIES widening D3 asks about.
    assert decisions["D3"]["inForceValue"] == "SG_ONLY"
    assert decisions["D3"]["inForce"].startswith("SG_ONLY")


def test_external_dependencies_are_derived_from_the_configuration(db):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    empty = {d["key"] for d in service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]["externalDependencies"]}
    assert {"ais_api", "fwl_s_pass_end_day_basis", "lqs_part_time_hourly", "lqs_quota", "gates"} <= empty
    seed_singapore(db)
    db.commit()
    seeded = {d["key"] for d in service.get_sg_statutory_summary(db, date(2026, 9, 25))["activationReadiness"]["externalDependencies"]}
    assert "lqs_part_time_hourly" not in seeded                    # published MOM value, seeded with its source
    assert {"ais_api", "fwl_s_pass_end_day_basis", "lqs_quota", "gates"} <= seeded   # still external


# ══ Service registry: pack activation never opens onboarding ═══════════════

def test_sg_onboarding_fails_closed_without_a_registry_row_even_with_an_active_pack(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason
    from app.modules.payroll.models import JurisdictionPack
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").delete()
    pack.status = "Active"                                          # HARNESS: an Active pack
    db.commit()
    when = date(2026, 9, 25)
    assert "not yet available" in get_jurisdiction_onboarding_block_reason(db, "SG", as_of=when)
    db.add(JurisdictionServiceRegistry(country="SG", availability="PLANNED"))
    db.commit()
    assert "not yet available" in get_jurisdiction_onboarding_block_reason(db, "SG", as_of=when)
    db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").update(
        {"availability": "AVAILABLE"})
    db.commit()
    assert get_jurisdiction_onboarding_block_reason(db, "SG", as_of=when) is None       # owner's step opens it
    assert db.query(JurisdictionPack).filter(JurisdictionPack.id == pack.id).one().status == "Active"


def test_other_countries_keep_the_missing_registry_row_fall_through(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    for country in ("UK", "Canada", "AU", "IN"):                    # no registry row, no pack
        reason = get_jurisdiction_onboarding_block_reason(db, country)
        assert "not yet configured" in reason and "not yet available" not in reason, country   # canonical-pack check


def test_the_canonical_seed_creates_a_planned_row_and_never_changes_an_existing_one(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from scripts.seed_singapore_canonical_pack import seed_singapore

    seed_singapore(db)
    db.commit()
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").one()
    assert (row.availability, row.filing_responsibility) == ("PLANNED", "NOT_OFFERED")
    row.availability = "AVAILABLE"                                  # the owner's later decision
    db.commit()
    from scripts.seed_singapore_canonical_pack import _ensure_service_registry_row
    assert _ensure_service_registry_row(db) == "AVAILABLE"
    db.commit()
    assert db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").count() == 1


def test_readiness_shows_the_registry_state_and_no_longer_lists_retail_averaging(db):
    from app.modules.payroll import service

    summary = service.get_sg_statutory_summary(db, date(2026, 9, 25))
    items = {i["key"]: i for i in next(s for s in summary["sections"] if s["key"] == "readiness")["values"]["items"]}
    assert items["service_registry"]["status"] == "BLOCKED" and "No registry row" in items["service_registry"]["evidence"]
    deps = {d["key"] for d in summary["activationReadiness"]["externalDependencies"]}
    assert "pwm_retail_averaging" not in deps       # implemented from MOM Annex D (test_singapore_pwm_retail_averaging.py)


def test_the_ais_api_boundary_is_an_explicit_checklist_and_nothing_can_submit(db):
    """Final closure: the AIS-API 2.0 prerequisites are listed item by item,
    none is claimed, no credential is configured, and the product still
    offers only the EXPORT_READY extract."""
    from app.modules.payroll import service

    summary = service.get_sg_statutory_summary(db, date(2026, 9, 25))
    ops = {i["key"]: i for i in next(s for s in summary["sections"] if s["key"] == "operations")["values"]["items"]}
    api = ops["ais_api"]
    assert api["state"] == "EXTERNAL_INTEGRATION_REQUIRED" and api["credentialsConfigured"] is False
    prereq = {p["key"]: p["status"] for p in api["integrationPrerequisites"]}
    assert set(prereq) == {"d1_decision", "apex_onboarding", "specification", "credentials", "corppass", "sandbox"}
    assert prereq["d1_decision"] == "BUSINESS_DECISION_REQUIRED" and "PASS" not in prereq.values()
    assert not any(hasattr(service, name) for name in ("submit_sg_ais", "submit_sg_ir8a_api", "sg_ais_api_submit"))
    dash = {r["key"]: r["status"] for r in summary["activationReadiness"]["readinessDashboard"]}
    assert dash["external_integrations"] == "EXTERNAL_REQUIRED"

"""
tests/test_singapore_phase58_lifecycle.py
-----------------------------------------
Phase 5.8 — report-template lifecycle hardening (shared by every
jurisdiction, exercised here on Singapore templates) and the Singapore
Super Admin activation-readiness view.

  - REPORT_TEMPLATE_TRANSITIONS: Draft/Review/Approved move among
    themselves; only Approved -> Published (Phase 6.3 removed the Draft/Review
    -> Published shortcut); Published -> Active -> Superseded; a released version never
    returns to an editable state; Superseded is final; unknown statuses fail.
  - Maker-checker: distinct approver still required; approval is release
    evidence and cannot be replaced once released; editing after approval
    clears it; an upsert can neither set a status nor name an approver.
  - Correction after release is a new version (previous_version_id).
  - Summary: per-component lifecycle / validation state, activation gates,
    template counts, PWM provenance — and no PWM schedule row ever reaches a
    payslip's tax_rule_snapshot.

Assertions are structural (keys, model fields, behaviour). app.* imports
are lazy (tests/_db_safety.py).
"""

import json
from datetime import date
from decimal import Decimal

import pytest

MAKER, CHECKER, PUBLISHER = 101, 202, 303


def _template(db, key="SG-PAYROLL-REGISTER-T", report_type="SG_PAYROLL_REGISTER", version="1.0"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name="SG register", reportType=report_type, jurisdictionCountry="SG",
        reportingYear="2026", version=version), actor_id=MAKER)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(
        componentKey="employer_info", label="Employer Information", sortOrder=0), actor_id=MAKER)
    db.refresh(t)
    return t


def _release(db, t):
    """Draft -> Approved (distinct checker) -> Published -> Active."""
    from app.modules.payroll import service

    service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    service.set_report_template_status(db, t.id, "Published", actor_id=PUBLISHER)
    return service.set_report_template_status(db, t.id, "Active", actor_id=PUBLISHER, reason="release 2026")


def _audits(db, template_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "report_template", TaxConfigurationAudit.entity_id == template_id)
            .order_by(TaxConfigurationAudit.id).all())


# ── Transition graph ────────────────────────────────────────────────────────

def test_full_lifecycle_succeeds_and_every_step_is_audited(db):
    from app.modules.payroll import service

    t = _template(db)
    service.set_report_template_status(db, t.id, "Review", actor_id=MAKER, reason="ready for review")
    service.set_report_template_status(db, t.id, "Draft", actor_id=MAKER)          # review can send it back
    t = _release(db, t)
    assert (t.status, t.approved_by_id) == ("Active", CHECKER)
    t = service.set_report_template_status(db, t.id, "Superseded", actor_id=PUBLISHER, reason="replaced by 1.1")
    assert t.status == "Superseded"
    changes = [a for a in _audits(db, t.id) if a.action == "status_change"]
    assert [(a.old_value["status"], a.new_value["status"]) for a in changes] == [
        ("Draft", "Review"), ("Review", "Draft"), ("Approved", "Published"), ("Published", "Active"),
        ("Active", "Superseded")]
    assert all(a.actor_id and a.created_at and a.tax_version == "1.0" for a in changes)
    assert changes[-2].reason == "release 2026" and changes[-2].new_value["approvedById"] == CHECKER
    assert changes[-2].new_value["templateKey"] == "SG-PAYROLL-REGISTER-T"


@pytest.mark.parametrize("target", ["Draft", "Review", "Approved", "Published"])
def test_active_template_never_returns_to_an_earlier_state(db, target):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _release(db, _template(db))
    with pytest.raises(BadRequestException, match="cannot move from Active"):
        service.set_report_template_status(db, t.id, target, actor_id=PUBLISHER)
    db.refresh(t)
    assert t.status == "Active"
    with pytest.raises(BadRequestException):                                        # and it stays uneditable
        service._require_editable_report_template(t)


@pytest.mark.parametrize("path,target", [
    ((), "Active"),                        # Draft -> Active skips review and release
    (("approve",), "Active"),              # Approved -> Active skips Published
    (("approve", "Published"), "Draft"),   # released -> editable
    (("approve", "Published", "Active", "Superseded"), "Active"),   # Superseded is final
    ((), "Foo"),                           # not a lifecycle state at all
])
def test_invalid_transitions_are_refused(db, path, target):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    for step in path:
        if step == "approve":
            service.set_report_template_approver(db, t.id, actor_id=CHECKER)
        else:
            service.set_report_template_status(db, t.id, step, actor_id=PUBLISHER)
    before = service.get_report_template(db, t.id).status
    with pytest.raises(BadRequestException):
        service.set_report_template_status(db, t.id, target, actor_id=PUBLISHER)
    assert service.get_report_template(db, t.id).status == before


def test_transition_graph_is_the_documented_lifecycle():
    from app.modules.payroll.engine.jurisdictions.singapore.statutory_summary import TEMPLATE_STATUSES
    from app.modules.payroll.service import REPORT_TEMPLATE_TRANSITIONS, _EDITABLE_TEMPLATE_STATUSES

    assert tuple(REPORT_TEMPLATE_TRANSITIONS) == TEMPLATE_STATUSES
    for released in ("Published", "Active", "Superseded"):
        assert not set(REPORT_TEMPLATE_TRANSITIONS[released]) & set(_EDITABLE_TEMPLATE_STATUSES)
    assert REPORT_TEMPLATE_TRANSITIONS["Superseded"] == ()
    assert REPORT_TEMPLATE_TRANSITIONS["Published"] == ("Active", "Superseded")


# ── Maker-checker ──────────────────────────────────────────────────────────

def test_self_approval_still_blocks_publication(db):
    """Completion programme: the last editor's self-approval is now refused
    at the Approve step itself (Singapore opt-in, the pack rule of 6.5 B);
    the Publish gate still refuses an approver equal to the last editor."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    with pytest.raises(BadRequestException, match="cannot approve it"):
        service.set_report_template_approver(db, t.id, actor_id=MAKER)            # the last editor approves
    t = service.get_report_template(db, t.id)
    assert (t.status, t.approved_by_id) == ("Draft", None)
    t.approved_by_id, t.status = MAKER, "Approved"                                 # e.g. a legacy row
    db.commit()
    with pytest.raises(BadRequestException, match="distinct approver"):
        service.set_report_template_status(db, t.id, "Published", actor_id=MAKER)


def test_released_approval_cannot_be_replaced(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _release(db, _template(db))
    with pytest.raises(BadRequestException, match="release evidence"):
        service.set_report_template_approver(db, t.id, actor_id=999)
    db.refresh(t)
    assert t.approved_by_id == CHECKER


def test_editing_after_approval_clears_the_approval(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateFieldUpsert

    from app.modules.payroll.models import ReportTemplateComponent

    t = _template(db)
    service.set_report_template_approver(db, t.id, actor_id=CHECKER)
    comp = db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == t.id).one()
    service.upsert_report_field(db, comp.id, ReportTemplateFieldUpsert(
        fieldKey="employer_name", label="Employer", fieldType="text", dataSourceKind="EMPLOYER_PROFILE",
        sourceColumn="name"), actor_id=MAKER)
    db.refresh(t)
    assert (t.status, t.approved_by_id) == ("Draft", None)                        # stale approval never carries over
    # Phase 6.3: refused by the Approved-before-Published transition rule
    # (before 6.3 this same attempt reached the distinct-approver gate).
    with pytest.raises(BadRequestException, match="requires an Approved template"):
        service.set_report_template_status(db, t.id, "Published", actor_id=PUBLISHER)


def test_upsert_cannot_set_status_or_name_an_approver(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    created = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey="SG-BYPASS", name="x", reportType="SG_PAYROLL_REGISTER", jurisdictionCountry="SG",
        reportingYear="2026", status="Active", approvedById=CHECKER), actor_id=MAKER)
    assert (created.status, created.approved_by_id) == ("Draft", None)
    service.set_report_template_approver(db, created.id, actor_id=CHECKER)
    edited = service.upsert_report_template(db, ReportTemplateUpsert(
        id=created.id, templateKey="SG-BYPASS", name="renamed", reportType="SG_PAYROLL_REGISTER",
        jurisdictionCountry="SG", reportingYear="2026", status="Published", approvedById=777), actor_id=MAKER)
    assert (edited.status, edited.approved_by_id, edited.name) == ("Draft", None, "renamed")


def test_correction_after_release_is_a_new_version(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplateComponent
    from app.modules.payroll.schemas import ReportTemplateUpsert

    v1 = _release(db, _template(db))
    with pytest.raises(BadRequestException):                                        # v1 is not editable in place
        service.upsert_report_template(db, ReportTemplateUpsert(
            templateKey=v1.template_key, name="edited", reportType=v1.report_type, jurisdictionCountry="SG",
            reportingYear="2026", version="1.0"), actor_id=MAKER)
    v2 = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=v1.template_key, name="SG register", reportType=v1.report_type, jurisdictionCountry="SG",
        reportingYear="2026", version="1.1"), actor_id=MAKER)
    assert (v2.status, v2.previous_version_id, v2.approved_by_id) == ("Draft", v1.id, None)
    assert db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == v2.id).count() == 1
    db.refresh(v1)
    assert (v1.status, v1.name) == ("Active", "SG register")                       # v1 untouched
    service.set_report_template_approver(db, v2.id, actor_id=CHECKER)
    service.set_report_template_status(db, v2.id, "Published", actor_id=PUBLISHER)
    with pytest.raises(BadRequestException, match="already Active"):
        service.set_report_template_status(db, v2.id, "Active", actor_id=PUBLISHER)
    service.set_report_template_status(db, v1.id, "Superseded", actor_id=PUBLISHER)
    assert service.set_report_template_status(db, v2.id, "Active", actor_id=PUBLISHER).status == "Active"


def test_status_route_is_super_admin_and_carries_a_reason():
    from app.core.dependencies import get_current_super_admin
    from app.main import app
    from app.modules.payroll.schemas import ReportTemplateStatusUpdate

    route = next(r for r in app.routes if getattr(r, "path", None) == "/api/super-admin/report-templates/{id}/status")

    def calls(dep, out):
        for d in dep.dependencies:
            out.add(d.call)
            calls(d, out)
        return out
    assert get_current_super_admin in calls(route.dependant, set())
    assert "reason" in ReportTemplateStatusUpdate.model_fields


# ── Singapore Super Admin readiness view ───────────────────────────────────

def _seeded_summary(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()
    return pack, service.get_sg_statutory_summary(db, date(2026, 9, 25))


def test_activation_readiness_reports_the_real_gates_without_activating(db, monkeypatch):
    from app.modules.payroll.models import SgpPwmOvertimeSchedule, SourceArtifact

    pack, summary = _seeded_summary(db, monkeypatch)
    ready = summary["activationReadiness"]
    sp = ready["statutoryPack"]
    assert (sp["status"], sp["version"], sp["activation"]) == ("Draft", pack.version, "NOT_ACTIVE")
    assert sp["externalValidation"] == "EXTERNAL_VALIDATION_REQUIRED"
    source = db.get(SourceArtifact, pack.source_document_id)
    assert sp["sourceHash"] == source.checksum_sha256 and sp["source"]["id"] == source.id
    gates = {g["key"]: g["met"] for g in sp["activationGates"]}
    assert gates == {"distinct_approver": False, "source_evidence_linked": True, "effective_from_set": True,
                     "latest_golden_run_pass": False,
                     # Phase 6.10: G1 not accepted; the seeded rows DO reproduce every golden vector in the window.
                     "g1_evidence_accepted": False, "pack_reproduces_golden_vectors": True,
                     "effective_from_first_of_month": True}
    assert ready["reportTemplates"]["total"] == 11 and ready["reportTemplates"]["Draft"] == 11
    assert ready["reportTemplates"]["Active"] == 0
    pwm_sources = {s for (s,) in db.query(SgpPwmOvertimeSchedule.source_document_id).distinct()}
    assert (ready["pwm"]["rows"], ready["pwm"]["schedules"]) == (6132, 84)
    assert ready["pwm"]["sourceDocuments"] == len(pwm_sources) == 6                # the six MOM PDFs
    assert ready["pwm"]["latestRetrieved"] and ready["pwm"]["lastSeeded"]
    db.refresh(pack)
    assert pack.status == "Draft"                                                    # nothing was activated


def test_sections_expose_lifecycle_and_validation_state(db, monkeypatch):
    _pack, summary = _seeded_summary(db, monkeypatch)
    for key in ("cpf", "sdl", "shg", "fwl", "lqs", "pwm", "iras", "ir21"):
        s = next(x for x in summary["sections"] if x["key"] == key)
        assert {"lifecycleState", "validationState", "sourcesReviewed", "effectiveTo", "lastRetrievedAt"} <= set(s)
        assert s["lifecycleState"] == "DRAFT" and s["validationState"] == "EXTERNAL_VALIDATION_REQUIRED", key
    templates = next(x for x in summary["sections"] if x["key"] == "reportTemplates")["values"]["templates"]
    assert len(templates) == 11
    assert all(t["status"] == "Draft" and t["allowedNextStatuses"] == ["Review", "Approved"]
               for t in templates)                                                  # from the service graph, per status
    assert all(t["officialCertification"] is False for t in templates)


def test_summary_response_schema_includes_activation_readiness(db, monkeypatch):
    from app.modules.super_admin.schemas import SgpStatutoryAdminSummaryResponse

    _pack, summary = _seeded_summary(db, monkeypatch)
    parsed = SgpStatutoryAdminSummaryResponse.model_validate(summary).model_dump()
    assert parsed["activationReadiness"] == summary["activationReadiness"]


# ── PWM reference rows never enter a payslip snapshot ──────────────────────

def test_no_pwm_schedule_row_enters_a_payslip_tax_rule_snapshot(db, organization, monkeypatch):
    import app.core.code_generation as code_generation
    from app.modules.payroll import service
    from app.modules.payroll.models import (
        CompanyComplianceDetails, ContributionRate, PayrollEmployee, PayrollRun, PayslipItem, SgpPwmOvertimeSchedule,
    )
    from scripts.seed_singapore_canonical_pack import seed_singapore

    counter = {"n": 0}

    def _codes(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 100
        return f"T58{prefix}{counter['n']:06d}"
    monkeypatch.setattr(code_generation, "generate_business_code", _codes)
    pack = seed_singapore(db)
    pack.status = "Active"
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", active_pack_id=pack.id))
    db.add(PayrollEmployee(organization_id=organization.id, employee_code="SNAP", name="Snap", country_code="SG",
                           ctc=Decimal("30000"), basic=Decimal("30000"), hra=Decimal("0"), date_of_birth=date(1986, 3, 15),
                           sgp_cpf_residency_status="SC", sgp_work_pass_type="NONE", sgp_shg_funds="NONE",
                           compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "RETAIL", "pwm_group": "ALL"}))
    db.commit()
    run = PayrollRun(organization_id=organization.id, period_label="Jul", period_start=date(2026, 7, 1),
                     period_end=date(2026, 7, 31), pay_date=date(2026, 7, 31))
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    snapshot = item.tax_rule_snapshot or {}
    assert snapshot, "the payslip must carry its statutory snapshot"
    text = json.dumps(snapshot, default=str)
    assert "sgp_pwm_overtime_schedules" not in text and "required_gross" not in text and "overtime_hours" not in text
    pwm_hashes = {h for (h,) in db.query(SgpPwmOvertimeSchedule.source_sha256).distinct()}
    assert not any(h in text for h in pwm_hashes)
    pack_rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
    assert db.query(SgpPwmOvertimeSchedule).count() == 6132 > pack_rows                  # the 6,132 cells stay outside

"""
tests/test_super_admin_ui_part11.py
--------------------------------------------
Coverage for the Super Admin UI completion items (§19 gap-closure
Part 11, 2026-09-09): Automated Impact Preview, Emergency Hotfix Mode,
RTI & Forms summary, and Test Certification. DB-integration style.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import (
    JurisdictionPack, CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem,
    GeneratedReport, ReportTemplate, EmployeeStatus, PayrollStatus,
)


def _make_tax_pack(db, pack_id, country="UK", state=None, status="Active"):
    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=country, jurisdiction_state=state, pack_type="tax", version="1.0", status=status)
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _make_company(db, org_id, country="UK", active_pack_id=None):
    company = CompanyComplianceDetails(organization_id=org_id, name="Test Co", jurisdiction_country=country, active_pack_id=active_pack_id)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _make_second_org(db, code="OPTPACK"):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="Impact Preview Org", organization_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


# ── Automated Impact Preview ─────────────────────────────────────────────

def test_impact_preview_excludes_orgs_not_opted_into_canonical_tracking(db, organization):
    pack = _make_tax_pack(db, "UK-IMPACT-TEST1")
    _make_company(db, organization.id, country="UK", active_pack_id=None)
    preview = service.get_jurisdiction_pack_impact_preview(db, pack.id)
    assert preview["totalOrganizationsEligible"] == 1
    assert preview["totalOrganizationsGenuinelyAffected"] == 0
    assert preview["organizations"][0]["optedIntoCanonicalTracking"] is False


def test_impact_preview_includes_opted_in_org_with_employee_and_run_counts(db, organization):
    pack = _make_tax_pack(db, "UK-IMPACT-TEST2")
    _make_company(db, organization.id, country="UK", active_pack_id=pack.id)

    emp1 = PayrollEmployee(organization_id=organization.id, employee_code="IPE1", name="A", status=EmployeeStatus.ACTIVE)
    emp2 = PayrollEmployee(organization_id=organization.id, employee_code="IPE2", name="B", status=EmployeeStatus.INACTIVE)
    db.add_all([emp1, emp2])
    db.commit()

    draft_run = PayrollRun(organization_id=organization.id, period_label="Draft Run", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), status=PayrollStatus.DRAFT.value)
    paid_run = PayrollRun(organization_id=organization.id, period_label="Paid Run", period_start=date(2026, 5, 1), period_end=date(2026, 5, 31), pay_date=date(2026, 5, 31), status=PayrollStatus.PAID.value)
    db.add_all([draft_run, paid_run])
    db.commit()

    preview = service.get_jurisdiction_pack_impact_preview(db, pack.id)
    org_entry = preview["organizations"][0]
    assert org_entry["optedIntoCanonicalTracking"] is True
    assert org_entry["activeEmployeeCount"] == 1
    assert org_entry["unfinalizedRunCount"] == 1  # only the Draft run, not the Paid one
    assert preview["totalOrganizationsGenuinelyAffected"] == 1
    assert preview["totalActiveEmployeesAffected"] == 1
    assert preview["totalUnfinalizedRunsAffected"] == 1


def test_impact_preview_missing_pack_raises(db, organization):
    with pytest.raises(NotFoundException):
        service.get_jurisdiction_pack_impact_preview(db, 999999)


# ── Emergency Hotfix Mode ─────────────────────────────────────────────────

def test_hotfix_activation_requires_incident_id(db, organization):
    pack = JurisdictionPack(pack_id="UK-HOTFIX-TEST1", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    with pytest.raises(BadRequestException, match="incident_id"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "", "Fixing a live bug", actor_id=1)


def test_hotfix_activation_requires_justification(db, organization):
    pack = JurisdictionPack(pack_id="UK-HOTFIX-TEST2", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    with pytest.raises(BadRequestException, match="justification"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-001", "", actor_id=1)


def test_hotfix_activation_bypasses_distinct_approver_gate_and_records_activation(db, organization):
    # Note: no approved_by_id set, and only ONE actor (self) throughout —
    # would be rejected by the normal set_jurisdiction_pack_status path.
    pack = JurisdictionPack(pack_id="UK-HOTFIX-TEST3", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved")
    db.add(pack)
    db.commit()
    db.refresh(pack)

    updated = service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-001", "Live PAYE bug producing wrong tax", actor_id=42)
    assert updated.status == "Active"

    activations = service.list_pack_hotfix_activations(db)
    assert len(activations) == 1
    assert activations[0].incident_id == "INC-001"
    assert activations[0].reviewed is False


def test_hotfix_activation_still_enforces_date_overlap_guard(db, organization):
    _make_tax_pack(db, "UK-HOTFIX-OVERLAP-EXISTING", status="Active")
    existing = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "UK-HOTFIX-OVERLAP-EXISTING").first()
    existing.effective_from = date(2026, 4, 6)
    existing.effective_to = None
    db.commit()

    new_pack = JurisdictionPack(
        pack_id="UK-HOTFIX-OVERLAP-NEW", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved",
        effective_from=date(2026, 6, 1), effective_to=None,
    )
    db.add(new_pack)
    db.commit()
    db.refresh(new_pack)

    with pytest.raises(BadRequestException, match="overlap"):
        service.activate_jurisdiction_pack_hotfix(db, new_pack.id, "INC-002", "Emergency", actor_id=1)


def test_review_pack_hotfix_activation_marks_reviewed(db, organization):
    pack = JurisdictionPack(pack_id="UK-HOTFIX-TEST4", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-003", "Emergency", actor_id=1)
    activation = service.list_pack_hotfix_activations(db, reviewed=False)[0]

    reviewed = service.review_pack_hotfix_activation(db, activation.id, "Confirmed correct, no further action.", actor_id=2)
    assert reviewed.reviewed is True
    assert reviewed.reviewed_by_id == 2

    assert service.list_pack_hotfix_activations(db, reviewed=False) == []
    assert len(service.list_pack_hotfix_activations(db, reviewed=True)) == 1


# ── RTI & Forms summary ───────────────────────────────────────────────────

def _make_generated_report(db, org_id, report_type, scope_key=None, run_id=None):
    template = ReportTemplate(template_key=f"UK-{report_type}-P11", name=report_type, report_type=report_type, jurisdiction_country="UK", reporting_year="2026-27", version="1.0", status="Active")
    db.add(template)
    db.commit()
    db.refresh(template)
    report = GeneratedReport(
        organization_id=org_id, report_template_id=template.id, template_version="1.0", report_type=report_type,
        payroll_run_id=run_id, scope_key=scope_key,
        jurisdiction_country="UK", reporting_year="2026-27", status="Generated",
        rendered_data={}, reconciliation={"status": "MATCH"} if run_id else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def test_rti_forms_summary_lists_reports_with_submission_status(db, organization):
    report = _make_generated_report(db, organization.id, "EPS", scope_key="PERIOD:2026-27:M01")
    service.create_rti_submission(db, organization.id, report.id)

    summary = service.get_rti_forms_summary(db, organization.id)
    assert len(summary) == 1
    assert summary[0]["reportType"] == "EPS"
    assert summary[0]["submissions"][0]["status"] == "DRAFT"


def test_rti_forms_summary_excludes_non_rti_report_types(db, organization):
    _make_generated_report(db, organization.id, "TDS")
    summary = service.get_rti_forms_summary(db, organization.id)
    assert summary == []


def test_rti_forms_summary_empty_for_org_with_no_reports(db, organization):
    assert service.get_rti_forms_summary(db, organization.id) == []


# ── Test Certification ────────────────────────────────────────────────────

def test_run_golden_test_certification_reports_no_real_cases(db, organization):
    run = service.run_golden_test_certification(db, actor_id=1)
    # The real fixtures dir has zero non-underscore-prefixed files at the
    # time this was written (Part 10 is blocked on real HMRC files) —
    # this must be reported honestly, not as a false PASS.
    assert run.status == "NO_REAL_CASES"
    assert run.real_case_count == 0


def test_list_test_certification_runs_orders_newest_first(db, organization):
    run1 = service.run_golden_test_certification(db, actor_id=1)
    run2 = service.run_golden_test_certification(db, actor_id=1)
    runs = service.list_test_certification_runs(db)
    assert runs[0].id == run2.id
    assert runs[1].id == run1.id

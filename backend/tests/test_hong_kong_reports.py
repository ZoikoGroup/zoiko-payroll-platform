"""
tests/test_hong_kong_reports.py
--------------------------------
Hong Kong (ZP-HK-ENG-001 v1.0) — the seven shared report templates and their
five generators, added to the SAME ReportTemplate / GeneratedReport pipeline
India, the UK, the US and Singapore already use.

What these tests actually hold down:

  * Hong Kong is an ORDINARY shared-pipeline jurisdiction. Every HK template is
    an ordinary ReportTemplate (versioned, maker-checker, seeded in Draft) and
    every generator writes a shared GeneratedReport. Nothing HK-specific forks
    the report architecture.
  * Hong Kong has NO payroll income tax. No HK template may carry a "tax"
    component, and the seeded components are contributions-only — the same
    shape Cayman and The Bahamas get. MPF uses the shared employee_pension /
    employer_pension slots.
  * A seeded HK template is INERT until a distinct Super Admin approves,
    publishes and activates it: Draft, wrong report type, and wrong-jurisdiction
    templates are all refused.
  * Every generator is tenant-scoped and reads the CALLER's organization, never
    a client-supplied one, and every route is behind the payroll-operator RBAC.
  * A report is immutable evidence: regenerating supersedes rather than
    overwrites, and the case/submission that a report represents links to it.
  * Reported figures come from COMMITTED payroll and reconcile to it (HK-011);
    an uncommitted or non-HK payslip is never in scope.
  * MPF is MANDATORY contributions only — voluntary MPF is out of the first
    release, so a below-threshold employee contributes nothing and no
    voluntary subsystem is implied.
  * Employee identity is MASKED on every HK report (HK-022 / PCPD HR Code); the
    unmasked HKID is never written into a GeneratedReport.
  * Every HK report discloses that its layout is Zoiko's own internal field map,
    not the IRD / eMPF prescribed format (release gate G2), and nothing claims
    to have been transmitted.

All identifiers are synthetic. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal

import pytest

D = Decimal
YA = "2025/26"
MPF_PERIOD = "2026-05"

HK_TYPES = ["HK_BIR56A", "HK_IR56B", "HK_IR56E", "HK_IR56F", "HK_IR56G",
            "HK_EMPF_REMITTANCE", "HK_MPF_CONTRIBUTION_RECORD", "HK_TERMINATION_STATEMENT"]


# ── helpers ────────────────────────────────────────────────────────────────

def _employer(db, organization, **identifiers):
    from app.modules.payroll.models import CompanyComplianceDetails

    row = (db.query(CompanyComplianceDetails)
           .filter(CompanyComplianceDetails.organization_id == organization.id).first())
    if row is None:
        row = CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="HK")
        db.add(row)
        db.commit()
        db.refresh(row)
    row.name = "Zoiko HK Test Ltd"
    row.address = "18/F, One Pacific Place, Hong Kong"
    row.tax_no = "12345678-000"
    row.tax_identifiers = {
        "br_number": "62222222",
        "ird_employer_file_number": "IRDFN-99887766",
        "empf_employer_account": "MPF-EMP-12345678",
        **(identifiers or {}),
    }
    db.commit()
    return row


def _active_pack(db, organization):
    from app.modules.payroll.models import CompanyComplianceDetails
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    # Both year-of-assessment packs are live: these reports span 2025/26 and
    # 2026/27 pay dates, and an IRD due date resolves from the pack in force on
    # its event date — never from a literal.
    pack25, pack26 = seed_hong_kong_all(db)
    for p in (pack25, pack26):
        p.status = "Active"
    row = _employer(db, organization)
    row.active_pack_id = pack26.id
    db.commit()
    return pack26


def _employee(db, org_id, code, **kw):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="HK", ctc=D("40000"), date_of_birth=date(1990, 5, 20),
        date_of_joining=date(2025, 6, 2),
        compliance_fields={"hkid": "Z1234567", "passport_number": "H1234567",
                           "mpf_member_account": "MB-HK-001"},
    )
    fields.update(kw)
    emp = PayrollEmployee(**fields)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _hk_payslip(db, org_id, employee, pay_date, gross="20000", relevant_income=None,
                run_status="APPROVED", country="HK", employer_pension="0", employee_pension="0",
                ird_fields=None, coverage_status="COVERED"):
    """A committed HK payslip with the real trace shape the HK engine writes:
    trace['ird']['reportable'] for the IR56B reconciliation and
    trace['mpf'] for the MPF record / eMPF line."""
    from app.modules.payroll.models import PayslipItem, PayrollRun, PayrollStatus
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    pack = resolve_tax_configuration(db, "HK", payroll_date=pay_date)[2]
    run = PayrollRun(organization_id=org_id, period_label=pay_date.strftime("%b %Y"),
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
                     status=getattr(PayrollStatus, run_status))
    db.add(run)
    db.commit()
    db.refresh(run)
    ri = D(relevant_income) if relevant_income is not None else D(gross)
    reportable = ird_fields if ird_fields is not None else {
        "FE_INCOME_EMPLOYMENTS": str(ri), "FE_INCOME_OTHER": "0",
    }
    # The real trace shape the HK engine writes (engine/countries/hong_kong.py
    # build_mpf_trace): "period" is TOP level; "mpf" carries coverage,
    # currentPeriod, catchUp and the period's employer/employee totals; a
    # contributing month is COVERED. hk_service's eMPF pass matches a
    # contribution month against trace["period"]["end"] and reads the totals off
    # trace["mpf"]["employer"] / ["employee"].
    trace = {
        "period": {"start": pay_date.replace(day=1).isoformat(), "end": pay_date.isoformat(),
                   "payDate": pay_date.isoformat()},
        "ird": {"reportable": reportable},
        "mpf": {"coverage": {"status": coverage_status},
                "currentPeriod": {"relevantIncome": str(ri)},
                "employer": str(employer_pension),
                "employee": str(employee_pension),
                "catchUp": []},
    }
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=org_id,
                       employee_name=employee.name, country_code=country, gross_pay=D(gross),
                       net_pay=D(gross), hkg_calculation_trace=trace,
                       tax_policy_pack_id=pack.id if pack else None,
                       tax_rule_snapshot={"packId": pack.id, "version": getattr(pack, "version", None)}
                       if pack else None,
                       employer_pension=D(employer_pension), employee_pension=D(employee_pension))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, run


def _template(db, key, report_type, status="Active", country="HK", scope="AGGREGATE"):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key=key, name=key, report_type=report_type, jurisdiction_country=country,
                       reporting_year="2025/26", version="1.0", status=status, document_scope=scope)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _seeded(db, template_key, status="Active"):
    """The REAL seeded Hong Kong template (its actual components and fields),
    promoted through the lifecycle the way a Super Admin would. Using the
    genuine seeded shape is the point: it proves the generators and the seed
    agree on the field keys, which a hand-built empty template would not."""
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll.models import ReportTemplate

    seed_hong_kong(db)
    t = (db.query(ReportTemplate)
         .filter(ReportTemplate.template_key == template_key, ReportTemplate.version == "1.0").one())
    t.status = status
    db.commit()
    db.refresh(t)
    return t


def _annual_return(db, org_id, ya=YA):
    """Run hk_service's statutory annual-return pass, which is what builds the
    BIR56A cover case and the per-employee IR56B cases every HK report then
    renders. The reports REPRESENT that pass's outcome; they never re-derive it."""
    from app.modules.payroll import hk_service

    return hk_service.generate_annual_return(db, org_id, ya, None)


def _ir56_case(db, org_id, employee, form_type, event_date, status="DUE", ya=YA):
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird as hk_ird
    from app.modules.payroll.hk_service import reporting_timing
    from app.modules.payroll.models import HkgIrdReportingCase

    case = HkgIrdReportingCase(organization_id=org_id, employee_id=employee.id, form_type=form_type,
                               year_of_assessment=ya, event_date=event_date,
                               due_date=hk_ird.due_date(form_type, reporting_timing(db, event_date),
                                                        event_date=event_date, ya=ya),
                               status=status, income_period_start=date(2025, 4, 1),
                               income_period_end=event_date,
                               reported_income={"FE_INCOME_EMPLOYMENTS": "20000.00"})
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ── the seeded Hong Kong templates ─────────────────────────────────────────

def test_seed_script_seeds_every_hk_template_in_draft_and_a_bir56a_ird56b_calendar(db):
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll.models import ReportTemplate, StatutoryFilingCalendar

    seed_hong_kong(db)

    templates = {t.template_key: t for t in db.query(ReportTemplate)
                 .filter(ReportTemplate.jurisdiction_country == "HK").all()}
    assert set(templates) == {"HK-BIR56A", "HK-IR56B", "HK-IR56E", "HK-IR56F", "HK-IR56G",
                              "HK-EMPF-REMITTANCE", "HK-MPF-CONTRIBUTION-RECORD", "HK-TERMINATION-STATEMENT"}
    assert {t.report_type for t in templates.values()} == set(HK_TYPES)
    # Seeded templates are INERT: a distinct Super Admin still has to approve,
    # publish and activate each one before an Organization can generate against it.
    assert {t.status for t in templates.values()} == {"Draft"}
    assert templates["HK-IR56B"].document_scope == "PER_EMPLOYEE"
    assert templates["HK-EMPF-REMITTANCE"].document_scope == "AGGREGATE"
    assert templates["HK-TERMINATION-STATEMENT"].document_scope == "PER_EMPLOYEE"

    rows = (db.query(StatutoryFilingCalendar)
            .filter(StatutoryFilingCalendar.jurisdiction_country == "HK").all())
    assert {(r.report_type, r.period_key) for r in rows} == {
        ("HK_BIR56A", "ANNUAL-2025/26"), ("HK_IR56B", "ANNUAL-2025/26"),
        ("HK_BIR56A", "ANNUAL-2026/27"), ("HK_IR56B", "ANNUAL-2026/27"),
    }
    assert all(r.status == "Draft" for r in rows)
    # A Hong Kong year of assessment ends 31 March, so 2025/26 is due 1 May 2026
    # and 2026/27 is due 1 May 2027 — never a calendar-year May.
    due = {(r.report_type, r.period_key): r.due_date for r in rows}
    assert due[("HK_BIR56A", "ANNUAL-2025/26")] == date(2026, 5, 1)
    assert due[("HK_IR56B", "ANNUAL-2025/26")] == date(2026, 5, 1)
    assert due[("HK_BIR56A", "ANNUAL-2026/27")] == date(2027, 5, 1)
    assert due[("HK_IR56B", "ANNUAL-2026/27")] == date(2027, 5, 1)


def test_seed_script_is_idempotent_for_hong_kong(db):
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll.models import ReportTemplate, StatutoryFilingCalendar

    seed_hong_kong(db)
    seed_hong_kong(db)

    assert db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "HK").count() == len(HK_TYPES)
    assert db.query(StatutoryFilingCalendar).filter(
        StatutoryFilingCalendar.jurisdiction_country == "HK").count() == 4


def test_a_promoted_hk_template_is_never_silently_rewritten_by_a_re_seed(db):
    """A HK template a Super Admin has already Activated must survive a re-run
    untouched — the seed never edits a promoted template in place."""
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll.models import ReportTemplate

    seed_hong_kong(db)
    t = (db.query(ReportTemplate)
         .filter(ReportTemplate.template_key == "HK-BIR56A").one())
    t.status, t.name = "Active", "Renamed by a Super Admin"
    db.commit()
    t_id = t.id

    seed_hong_kong(db)

    db.expire_all()
    again = db.query(ReportTemplate).filter(ReportTemplate.id == t_id).one()
    assert again.status == "Active"
    assert again.name == "Renamed by a Super Admin"
    assert db.query(ReportTemplate).filter(ReportTemplate.template_key == "HK-BIR56A").count() == 1


def test_no_hong_kong_template_carries_a_tax_component(db):
    """Hong Kong withholds no payroll income tax. Salaries Tax is employee-
    assessed and reported to IRD after the year of assessment, so a "tax"
    component on any HK template would be a fabricated withholding."""
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent

    seed_hong_kong(db)
    keys = (db.query(ReportTemplateComponent.component_key)
            .join(ReportTemplate, ReportTemplateComponent.report_template_id == ReportTemplate.id)
            .filter(ReportTemplate.jurisdiction_country == "HK").all())
    keys = [k[0] for k in keys]
    assert "tax" not in keys
    assert "deductions" not in keys
    # MPF uses the shared employee/employer pension components instead.
    assert "contributions" in keys and "employer_contributions" in keys


def test_hong_kong_employer_and_employee_identity_fields_resolve_from_real_columns(db):
    from app.modules.payroll import service

    assert "hkid" in service._PAYROLL_EMPLOYEE_FIELD_CATALOG
    assert "passport_number" in service._PAYROLL_EMPLOYEE_FIELD_CATALOG
    assert set(service._PAYROLL_EMPLOYEE_FIELDS_BY_COUNTRY["HK"]) >= {
        "name", "date_of_joining", "date_of_leaving", "hkid", "passport_number"}
    assert "ird_employer_file_number" in service._EMPLOYER_PROFILE_FIELD_CATALOG
    assert "empf_employer_account" in service._EMPLOYER_PROFILE_FIELD_CATALOG


def test_every_hong_kong_report_type_is_offered_by_the_shared_component_catalog(db):
    from app.modules.payroll import service

    for report_type in HK_TYPES:
        available = service.get_available_report_components(report_type)
        assert available, f"{report_type} has no component catalog"
        assert {"key": "employer_info", "label": "Employer Information"} in available
        # The per-employee employee documents are the ones the shared
        # certificate PDF renders, so they must be PER_EMPLOYEE.
        assert "employee_info" in {c["key"] for c in available} or report_type in (
            "HK_BIR56A", "HK_EMPF_REMITTANCE")


# ── RBAC / tenancy wiring ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/payroll/hong-kong/reports/bir56a",
                                  "/api/payroll/hong-kong/reports/ir56b",
                                  "/api/payroll/hong-kong/reports/ir56-notification",
                                  "/api/payroll/hong-kong/reports/empf-remittance",
                                  "/api/payroll/hong-kong/reports/mpf-contribution-record"])
def test_hk_generator_routes_use_payroll_operator_rbac_and_the_caller_org(path):
    import inspect

    from app.core.dependencies import get_current_payroll_operator
    from app.main import app

    routes = [r for r in app.routes if getattr(r, "path", None) == path]
    assert [m for r in routes for m in r.methods] == ["POST"]

    def calls(dep, out):
        for d in dep.dependencies:
            out.add(d.call)
            calls(d, out)
        return out
    assert get_current_payroll_operator in calls(routes[0].dependant, set())
    source = inspect.getsource(routes[0].endpoint)
    assert "current_user.organization_id" in source          # never a client-supplied organization


@pytest.mark.parametrize("role,org", [("employee", 1), (None, 1)])
def test_payroll_operator_dependency_denies_non_operators(role, org):
    from types import SimpleNamespace

    from app.core.dependencies import get_current_payroll_operator
    from app.core.exceptions import ForbiddenException

    with pytest.raises(ForbiddenException):
        get_current_payroll_operator(SimpleNamespace(role=role, organization_id=org, id=9))


# ── template gates ────────────────────────────────────────────────────────

def test_bir56a_refuses_draft_wrong_type_and_foreign_jurisdiction_templates(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    draft = _template(db, "HK-BIR56A-D", "HK_BIR56A", status="Draft")
    with pytest.raises(BadRequestException, match="not Active"):
        service.generate_hong_kong_bir56a(db, organization.id, draft.id, YA)

    wrong = _template(db, "HK-OTHER", "HK_IR56B")
    with pytest.raises(BadRequestException, match="not one of"):
        service.generate_hong_kong_bir56a(db, organization.id, wrong.id, YA)

    foreign = _template(db, "UK-FAKE", "HK_BIR56A", country="UK")
    with pytest.raises(BadRequestException, match="'UK' template"):
        service.generate_hong_kong_bir56a(db, organization.id, foreign.id, YA)


@pytest.mark.parametrize("ya", ["2025-26", "2025", "2025/2026", "25/26", "", "not-a-ya"])
def test_bir56a_rejects_anything_that_is_not_a_hong_kong_year_of_assessment(db, organization, ya):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db, "HK-BIR56A-YA", "HK_BIR56A")
    with pytest.raises(BadRequestException):
        service.generate_hong_kong_bir56a(db, organization.id, t.id, ya)


def test_mpf_contribution_record_requires_a_calendar_month(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db, "HK-MPF-REC-P", "HK_MPF_CONTRIBUTION_RECORD", scope="PER_EMPLOYEE")
    for bad in ["2026", "2026-05-31", "202605", "2026-5", ""]:
        with pytest.raises(BadRequestException, match="expected a calendar month"):
            service.generate_hong_kong_mpf_contribution_record(
                db, organization.id, t.id, 1, bad)


# ── HK-BIR56A ──────────────────────────────────────────────────────────────

def test_bir56a_reconciles_to_committed_payroll_and_links_only_the_cover_case(db, organization):
    from app.modules.payroll import hk_service, service
    from app.modules.payroll.models import HkgIrdReportingCase

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-001")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000")
    t = _seeded(db, "HK-BIR56A")

    report = service.generate_hong_kong_bir56a(db, organization.id, t.id, YA)

    assert report.report_type == "HK_BIR56A"
    assert report.jurisdiction_country == "HK"
    assert report.reporting_year == YA
    assert report.status == "Generated"
    # HK-011: the reported total reconciles EXACTLY to committed payroll.
    assert report.reconciliation["status"] == "Reconciled"
    assert report.reconciliation["reportedTotal"] == report.reconciliation["committedPayrollGross"]

    # The statutory pass ran, and the COVER case points at the report...
    cover = (db.query(HkgIrdReportingCase)
             .filter(HkgIrdReportingCase.form_type == "BIR56A",
                     HkgIrdReportingCase.year_of_assessment == YA).one())
    assert cover.generated_report_id == report.id
    # ...but the per-employee IR56B case is NOT hijacked by the aggregate cover.
    # It must stay free for its own per-employee report to claim.
    ir56b = (db.query(HkgIrdReportingCase)
             .filter(HkgIrdReportingCase.form_type == "IR56B",
                     HkgIrdReportingCase.employee_id == emp.id).one())
    assert ir56b.generated_report_id is None
    assert ir56b.reported_income["FE_INCOME_EMPLOYMENTS"] == "20000.00"


def test_bir56a_discloses_the_internal_layout_and_claims_no_transmission(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-DISC")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="15000")
    t = _seeded(db, "HK-BIR56A")

    gaps = " ".join(service.generate_hong_kong_bir56a(db, organization.id, t.id, YA).rendered_data["knownGaps"])
    assert "not the IRD" in gaps
    assert "not archived in this build" in gaps
    assert "nothing is transmitted" in gaps
    assert "G2" in gaps


def test_bir56a_is_regenerable_evidence_not_an_overwrite(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-HIST")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000")
    t = _seeded(db, "HK-BIR56A")

    first = service.generate_hong_kong_bir56a(db, organization.id, t.id, YA)
    second = service.generate_hong_kong_bir56a(db, organization.id, t.id, YA)

    assert second.id != first.id
    db.refresh(first)
    assert first.status == "Superseded"          # the earlier report is preserved, never deleted
    live = (db.query(GeneratedReport)
            .filter(GeneratedReport.scope_key == first.scope_key,
                    GeneratedReport.status == "Generated").all())
    assert [r.id for r in live] == [second.id]


# ── HK-IR56B ───────────────────────────────────────────────────────────────

def test_ir56b_is_a_per_employee_report_with_a_masked_identity_and_a_case_link(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-IR56B-1")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000",
                employer_pension="1000", employee_pension="0")
    _annual_return(db, organization.id)          # builds the IR56B case
    t = _seeded(db, "HK-IR56B")

    report = service.generate_hong_kong_ir56b(db, organization.id, t.id, emp.id, YA)

    assert report.report_type == "HK_IR56B"
    assert report.employee_id == emp.id          # the shared "all reports for this employee" query works
    assert report.rendered_data["employees"][0]["employeeId"] == emp.id
    values = report.rendered_data["employees"][0]["values"]
    assert values["total_remuneration"] == 20000.0
    assert values["mpf_employer_total"] == 1000.0
    assert values["mpf_employee_total"] == 0.0    # mandatory MPF is 5% employer / nil employee

    # HK-022 / PCPD HR Code: the unmasked HKID is never persisted in a report.
    assert values["employee_hkid"] != "Z1234567"
    assert values["employee_hkid"].endswith("4567")
    assert "Z1234567" not in str(report.rendered_data)
    assert "MASKED" in " ".join(report.rendered_data["knownGaps"])

    # The case is the filing tracker and points at the report.
    from app.modules.payroll.models import HkgIrdReportingCase
    case = (db.query(HkgIrdReportingCase)
            .filter(HkgIrdReportingCase.form_type == "IR56B",
                    HkgIrdReportingCase.employee_id == emp.id).one())
    assert case.generated_report_id == report.id


def test_ir56b_refuses_a_suppressed_employee_and_another_tenants_employee(db, organization):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-SUP")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000")
    _annual_return(db, organization.id)
    t = _seeded(db, "HK-IR56B")

    from app.modules.payroll.models import HkgIrdReportingCase
    case = (db.query(HkgIrdReportingCase)
            .filter(HkgIrdReportingCase.form_type == "IR56B",
                    HkgIrdReportingCase.employee_id == emp.id).one())
    case.status, case.suppression_reason = "SUPPRESSED", "IR56F already reported the employee"
    db.commit()
    with pytest.raises(BadRequestException, match="SUPPRESSED"):
        service.generate_hong_kong_ir56b(db, organization.id, t.id, emp.id, YA)

    # An employee with no prepared case at all is a clear 400, not an empty report.
    other_emp = _employee(db, organization.id, "HK-NO-CASE")
    with pytest.raises(BadRequestException, match="No IR56B has been prepared"):
        service.generate_hong_kong_ir56b(db, organization.id, t.id, other_emp.id, YA)

    # A different tenant's employee id is a 404, never a cross-tenant read.
    other = Organization(organization_name="Other Org", organization_code="HK-OTHER")
    db.add(other)
    db.commit()
    stranger = _employee(db, other.id, "HK-STRANGER")
    with pytest.raises(NotFoundException):
        service.generate_hong_kong_ir56b(db, organization.id, t.id, stranger.id, YA)


def test_ir56b_reports_no_tax_component_and_only_committed_payslips(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-COMMIT")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000",
                employer_pension="1000", employee_pension="0")
    # A DRAFT run's payslip is not committed payroll and must not be reported.
    _hk_payslip(db, organization.id, emp, date(2026, 4, 30), gross="99000",
                employer_pension="5000", employee_pension="0", run_status="DRAFT")
    _annual_return(db, organization.id)
    t = _seeded(db, "HK-IR56B")

    values = service.generate_hong_kong_ir56b(
        db, organization.id, t.id, emp.id, YA).rendered_data["employees"][0]["values"]
    assert values["mpf_employer_total"] == 1000.0
    assert "tax" not in values


# ── HK-IR56E / IR56F / IR56G notifications ─────────────────────────────────

@pytest.mark.parametrize("form_type,report_type", [("IR56E", "HK_IR56E"),
                                                   ("IR56F", "HK_IR56F"),
                                                   ("IR56G", "HK_IR56G")])
def test_ir56_notification_renders_its_case_matching_template_and_links_it(db, organization, form_type, report_type):
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, f"HK-{form_type}")
    case = _ir56_case(db, organization.id, emp, form_type, date(2025, 6, 2))
    t = _seeded(db, f"HK-{form_type}")

    report = service.generate_hong_kong_ir56_notification(db, organization.id, t.id, case.id)

    assert report.report_type == report_type
    assert report.employee_id == emp.id
    assert report.rendered_data["formType"] == form_type
    assert report.rendered_data["caseId"] == case.id
    assert report.rendered_data["dueDate"] == case.due_date.isoformat()
    assert case.generated_report_id == report.id


def test_ir56_notification_refuses_a_mismatched_template_and_a_non_notification_case(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-MISMATCH")
    e_case = _ir56_case(db, organization.id, emp, "IR56E", date(2025, 6, 2))
    f_template = _template(db, "HK-IR56F-M", "HK_IR56F", scope="PER_EMPLOYEE")
    with pytest.raises(BadRequestException, match="must be reported on a HK_IR56E template"):
        service.generate_hong_kong_ir56_notification(db, organization.id, f_template.id, e_case.id)

    b_case = _ir56_case(db, organization.id, emp, "IR56B", date(2026, 3, 31))
    e_template = _template(db, "HK-IR56E-M", "HK_IR56E", scope="PER_EMPLOYEE")
    with pytest.raises(BadRequestException, match="not an employee notification"):
        service.generate_hong_kong_ir56_notification(db, organization.id, e_template.id, b_case.id)


def test_ir56g_reports_the_tax_clearance_hold_as_a_hold_not_a_deduction(db, organization):
    from app.modules.payroll import hk_service, service
    from app.modules.payroll.engine.jurisdictions.hong_kong import tax_clearance as hk_tc
    from app.modules.payroll.models import HkgTaxClearanceHold, HkgTaxClearanceHoldLine

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-IR56G-HOLD")
    case = _ir56_case(db, organization.id, emp, "IR56G", date(2026, 2, 28))
    item, _run = _hk_payslip(db, organization.id, emp, date(2026, 2, 28), gross="20000")
    t = _seeded(db, "HK-IR56G")

    # No hold exists yet, so the hold block is empty rather than zero-fabricated.
    values = service.generate_hong_kong_ir56_notification(
        db, organization.id, t.id, case.id).rendered_data["employees"][0]["values"]
    assert values["hold_state"] is None
    assert values["amount_withheld"] is None

    # A hold in a HOLDING state, with a real held-ledger line, is reported as the
    # withheld amount.
    hold = HkgTaxClearanceHold(organization_id=organization.id, employee_id=emp.id, ird_case_id=case.id,
                               state=hk_tc.HOLDING_STATES[0], expected_departure_date=date(2026, 2, 28),
                               identified_on=date(2026, 1, 28), filing_deadline=date(2026, 1, 28),
                               filed_date=date(2026, 1, 28), statutory_hold_expiry=date(2026, 2, 28))
    db.add(hold)
    db.commit()
    db.refresh(hold)
    db.add(HkgTaxClearanceHoldLine(hold_id=hold.id, organization_id=organization.id,
                                   payslip_item_id=item.id, amount=D("20000")))
    db.commit()

    data = service.generate_hong_kong_ir56_notification(
        db, organization.id, t.id, case.id).rendered_data
    values = data["employees"][0]["values"]
    assert values["hold_state"] in hk_tc.HOLDING_STATES
    assert D(values["amount_withheld"]) == D("20000.00")
    # The wording the reader actually sees: the field label itself says the
    # withheld amount is a legal hold, not a deduction — money that stays owed
    # to the employee, with net pay unchanged.
    labels = [f["label"] for c in data["templateSnapshot"]["components"] for f in c["fields"]]
    assert any("legal hold, not a deduction" in lbl for lbl in labels)


def test_ir56_notification_is_tenant_isolated(db, organization):
    from app.core.exceptions import NotFoundException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    other = Organization(organization_name="Other Org 2", organization_code="HK-OTHER-2")
    db.add(other)
    db.commit()
    _employer(db, other)
    stranger = _employee(db, other.id, "HK-NOT-MINE")
    case = _ir56_case(db, other.id, stranger, "IR56E", date(2025, 6, 2))
    t = _template(db, "HK-IR56E-TEN", "HK_IR56E", scope="PER_EMPLOYEE")

    with pytest.raises(NotFoundException):
        service.generate_hong_kong_ir56_notification(db, organization.id, t.id, case.id)


# ── HK-EMPF-REMITTANCE ────────────────────────────────────────────────────

def test_empf_remittance_represents_the_submission_and_links_it(db, organization):
    from app.modules.payroll import hk_service, service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-EMPF-1")
    _hk_payslip(db, organization.id, emp, date(2026, 5, 29), gross="20000",
                relevant_income="20000", employer_pension="1000", employee_pension="0")
    submission = hk_service.prepare_empf_submission(db, organization.id, MPF_PERIOD, None)
    t = _seeded(db, "HK-EMPF-REMITTANCE")

    report = service.generate_hong_kong_empf_remittance(db, organization.id, t.id, submission.id)

    assert report.report_type == "HK_EMPF_REMITTANCE"
    assert report.rendered_data["period"]["contributionPeriod"] == MPF_PERIOD
    assert report.rendered_data["totals"] == submission.totals
    assert report.rendered_data["employees"][0]["relevantIncome"] == "20000"
    # The identity on the remittance line is the ALREADY-MASKED value hk_service
    # persisted; the unmasked HKID is not re-derived here.
    assert report.rendered_data["employees"][0]["hkid"] != "Z1234567"
    assert "Z1234567" not in str(report.rendered_data)
    assert submission.generated_report_id == report.id

    gaps = " ".join(report.rendered_data["knownGaps"])
    assert "voluntary contributions are NOT in the first release" in gaps
    assert "not the IRD" in gaps


def test_empf_remittance_is_tenant_isolated(db, organization):
    from app.core.exceptions import NotFoundException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    other = Organization(organization_name="Other Org 3", organization_code="HK-OTHER-3")
    db.add(other)
    db.commit()
    _employer(db, other)
    stranger = _employee(db, other.id, "HK-EMPF-NOT-MINE")
    _hk_payslip(db, other.id, stranger, date(2026, 5, 29), gross="20000")
    from app.modules.payroll import hk_service
    submission = hk_service.prepare_empf_submission(db, other.id, MPF_PERIOD, None)
    t = _template(db, "HK-EMPF-TEN", "HK_EMPF_REMITTANCE")

    with pytest.raises(NotFoundException):
        service.generate_hong_kong_empf_remittance(db, organization.id, t.id, submission.id)


def test_empf_excludes_draft_and_non_hong_kong_payslips(db, organization):
    from app.modules.payroll import hk_service, service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-EMPF-SCOPE")
    _hk_payslip(db, organization.id, emp, date(2026, 5, 29), gross="20000", employer_pension="1000")
    _hk_payslip(db, organization.id, emp, date(2026, 5, 31), gross="99000",
                employer_pension="9000", run_status="DRAFT")
    _hk_payslip(db, organization.id, emp, date(2026, 5, 30), gross="88000",
                employer_pension="8000", country="US")
    submission = hk_service.prepare_empf_submission(db, organization.id, MPF_PERIOD, None)
    t = _seeded(db, "HK-EMPF-REMITTANCE")

    totals = service.generate_hong_kong_empf_remittance(
        db, organization.id, t.id, submission.id).rendered_data["totals"]
    assert totals["employees"] == 1
    assert D(totals["relevantIncome"]) == D("20000.00")


def test_ird_reconciliation_excludes_another_jurisdictions_payslip_for_the_same_employee(db, organization):
    """Jurisdiction isolation (Workstream C): a committed US or Singapore payslip
    for the same employee, in the same year of assessment, even one carrying an
    HK-shaped trace, never enters the BIR56A / IR56B totals or their reconciliation
    to committed payroll."""
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-ISO")
    _hk_payslip(db, organization.id, emp, date(2026, 1, 30), gross="20000")
    _hk_payslip(db, organization.id, emp, date(2026, 2, 27), gross="77000", country="US")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="66000", country="SG")
    t = _seeded(db, "HK-BIR56A")

    report = service.generate_hong_kong_bir56a(db, organization.id, t.id, YA)

    assert report.reconciliation["status"] == "Reconciled"
    assert D(report.reconciliation["reportedTotal"]) == D("20000")
    assert D(report.reconciliation["committedPayrollGross"]) == D("20000")


def test_empf_reports_no_voluntary_contribution_amount(db, organization):
    """Voluntary MPF is out of the first release (D-B): the report structure can
    carry it later, but nothing today may present a voluntary amount as if it
    were a real figure."""
    from app.modules.payroll import hk_service, service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-VOL")
    # Below the minimum relevant income: the employer still pays 5%, the
    # employee contributes nil, and there is no voluntary amount anywhere.
    _hk_payslip(db, organization.id, emp, date(2026, 5, 29), gross="5000", relevant_income="5000",
                employer_pension="250", employee_pension="0")
    submission = hk_service.prepare_empf_submission(db, organization.id, MPF_PERIOD, None)
    t = _seeded(db, "HK-EMPF-REMITTANCE")

    data = service.generate_hong_kong_empf_remittance(
        db, organization.id, t.id, submission.id).rendered_data
    assert data["totals"]["employeeMandatory"] == "0.00"
    assert D(data["totals"]["employerMandatory"]) == D("250.00")
    assert "voluntary" not in str(data["employees"]).lower().replace(
        "voluntary contributions are not in the first release", "")


# ── HK-MPF-CONTRIBUTION-RECORD (HK-010) ────────────────────────────────────

def test_mpf_contribution_record_is_the_employees_own_period_record(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-REC-1")
    _hk_payslip(db, organization.id, emp, date(2026, 5, 15), gross="20000", relevant_income="20000",
                employer_pension="1000", employee_pension="0")
    _hk_payslip(db, organization.id, emp, date(2026, 4, 15), gross="20000", relevant_income="20000",
                employer_pension="1000", employee_pension="0")   # the month BEFORE, not in scope
    t = _seeded(db, "HK-MPF-CONTRIBUTION-RECORD")

    report = service.generate_hong_kong_mpf_contribution_record(
        db, organization.id, t.id, emp.id, MPF_PERIOD)

    assert report.employee_id == emp.id
    assert report.rendered_data["contributionPeriod"] == MPF_PERIOD
    values = report.rendered_data["employees"][0]["values"]
    assert values["payslip_count"] == 1                # April's payslip is excluded
    assert values["total_relevant_income"] == 20000.0
    assert values["total_employer_mandatory"] == 1000.0
    assert values["total_employee_mandatory"] == 0.0
    # The statutory pack the figures were calculated under is reported back, so
    # a historical record can be re-derived against the pack that produced it.
    assert report.rendered_data["statutoryPack"]["packId"] is not None


def test_mpf_contribution_record_refuses_a_month_with_no_committed_hk_payroll(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-REC-EMPTY")
    t = _seeded(db, "HK-MPF-CONTRIBUTION-RECORD")

    with pytest.raises(BadRequestException, match="no committed Hong Kong payroll"):
        service.generate_hong_kong_mpf_contribution_record(
            db, organization.id, t.id, emp.id, "2026-11")      # the template's own year, no payroll


def test_mpf_contribution_record_is_tenant_isolated(db, organization):
    from app.core.exceptions import NotFoundException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    other = Organization(organization_name="Other Org 4", organization_code="HK-OTHER-4")
    db.add(other)
    db.commit()
    _employer(db, other)
    stranger = _employee(db, other.id, "HK-REC-NOT-MINE")
    _hk_payslip(db, other.id, stranger, date(2026, 5, 15), gross="20000")
    t = _template(db, "HK-MPF-REC-TEN", "HK_MPF_CONTRIBUTION_RECORD", scope="PER_EMPLOYEE")

    with pytest.raises(NotFoundException):
        service.generate_hong_kong_mpf_contribution_record(
            db, organization.id, t.id, stranger.id, MPF_PERIOD)


# ── shared report visibility ───────────────────────────────────────────────

def test_hong_kong_form_types_appear_in_the_shared_rti_form_summary(db):
    from app.modules.payroll import service

    assert "HK_BIR56A" in service._RTI_FORMS_SUMMARY_REPORT_TYPES
    for report_type in ("HK_IR56B", "HK_IR56E", "HK_IR56F", "HK_IR56G", "HK_EMPF_REMITTANCE"):
        assert report_type in service._RTI_FORMS_SUMMARY_REPORT_TYPES


@pytest.mark.parametrize("report_type", HK_TYPES)
def test_hong_kong_report_templates_are_refused_by_the_generic_generator(db, organization, report_type):
    """Every HK type has a bespoke generator whose subject is a statutory
    result, not a payslip column. The generic generate_report_from_template
    must never be a second, divergent way to produce it (the same restraint
    Singapore applies to its dedicated types)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db, f"HK-GENERIC-{report_type}", report_type, scope="PER_EMPLOYEE")
    with pytest.raises(BadRequestException, match="dedicated Hong Kong generator"):
        service.generate_report_from_template(db, organization.id, t.id, payroll_run_id=1)


def test_generic_generator_requires_an_active_hong_kong_template(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    published = _template(db, "HK-PUBLISHED-ONLY", "HK_SOME_OTHER_TYPE", status="Published")
    with pytest.raises(BadRequestException, match="generated only from the Active version"):
        service.generate_report_from_template(db, organization.id, published.id, payroll_run_id=1)


def test_hk_generators_write_reports_a_tenant_cannot_see_across_orgs(db, organization):
    from app.core.exceptions import NotFoundException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    _active_pack(db, organization)
    _employer(db, organization)
    emp = _employee(db, organization.id, "HK-SCOPE")
    _hk_payslip(db, organization.id, emp, date(2026, 3, 31), gross="20000")
    t = _seeded(db, "HK-BIR56A")
    report = service.generate_hong_kong_bir56a(db, organization.id, t.id, YA)

    other = Organization(organization_name="Other Org 5", organization_code="HK-OTHER-5")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundException):
        service.get_generated_report(db, other.id, report.id)

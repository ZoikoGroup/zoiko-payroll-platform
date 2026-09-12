"""
tests/test_germany_payroll_summary_report.py
------------------------------------------------
Phase 8BI (P1) — coverage for get_germany_payroll_summary_report, the
first Germany-specific reporting capability this project has (Phase 8BH's
audit found none existed at all). Built entirely from real, already-
persisted PayslipItem/PayrollRun rows — never a fabricated figure.

CALCULATED / BLOCKED / UNAVAILABLE are asserted precisely throughout:
a BLOCKED (FAILED) payslip must contribute exactly zero to every
monetary sum, and Solidaritätszuschlag must always report UNAVAILABLE
(no persisted field exists for it anywhere in this codebase).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyPvConfigurationCreate, PayrollRunCreate,
)


def _make_employee(db, org_id, code, gross):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Report test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_contribution_ceiling_approver(db, row.id, actor_id=checker)
    return service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_health_fund(db, health_fund_id, rate=Decimal("1.7000"), maker=1, checker=2):
    source = _make_source(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id=health_fund_id, fund_name="Test Fund (fixture)",
            supplementary_rate_pct=rate, effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, child_category="CHILDLESS", is_saxony=False, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category=child_category, is_saxony=is_saxony,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _make_full_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="REPORT-FUND",
        de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
        de_employment_classification="REGULAR",
    )
    kwargs.update(overrides)
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(**kwargs), actor_id=None,
    )


def _publish_all_registries(db):
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db, "REPORT-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _publish_registries_except_rv_alv_ceiling(db):
    """Phase 8BR: REGULAR no longer blocks on PAP alone once the registry
    is complete (see engine/germany_internal_tax.py) — a genuinely missing
    RV_ALV ceiling is used wherever this file needs a REAL, still-existing
    block for a REGULAR employee. MINIJOB is unaffected (no ceiling use)."""
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_health_fund(db, "REPORT-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _add_attendance(db, org_id, emp_id, day=15, month=1):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(2026, month, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _run_data(employee_ids, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), pay_date=date(2026, 2, 1)):
    return PayrollRunCreate(
        periodStart=period_start, periodEnd=period_end, payDate=pay_date,
        employeeIds=employee_ids, auto_generate_payslips=True,
    )


def test_report_distinguishes_calculated_and_blocked_with_no_fabricated_values(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    minijob_emp = _make_employee(db, organization.id, code="DE-RPT-MINI", gross=520)
    regular_emp = _make_employee(db, organization.id, code="DE-RPT-REG", gross=5000)
    _make_full_profile(db, minijob_emp, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, regular_emp, organization.id, de_employment_classification="REGULAR")
    # regular_emp is blocked by a genuinely missing RV_ALV ceiling (Phase
    # 8BR: REGULAR no longer blocks on PAP alone) — MINIJOB is unaffected.
    _publish_registries_except_rv_alv_ceiling(db)
    _add_attendance(db, organization.id, minijob_emp.id)
    _add_attendance(db, organization.id, regular_emp.id)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([minijob_emp.id, regular_emp.id]), organization_id=organization.id,
    )

    report = service.get_germany_payroll_summary_report(db, organization.id)

    assert report["employeeCounts"]["total"] == 2
    # Phase 8BU: byStatus gained a third PARTIAL bucket — 0 here since
    # neither employee in this scenario hit that path.
    assert report["employeeCounts"]["byStatus"] == {"CALCULATED": 1, "BLOCKED": 1, "PARTIAL": 0}
    assert report["employeeCounts"]["byClassification"]["MINIJOB"] == 1
    assert report["employeeCounts"]["byClassification"]["REGULAR"] == 1

    # Only the Minijob employee's real figures are summed — the blocked
    # employee contributes exactly zero everywhere.
    assert report["grossPay"] == {"status": "CALCULATED", "amount": "520.00"}
    # Phase 8BU: netPay gained excludedPartialCount/note fields (0/None
    # here — no PARTIAL employee in this scenario).
    assert report["netPay"] == {
        "status": "CALCULATED", "amount": "501.28", "excludedPartialCount": 0, "note": None,
    }
    assert report["statutoryContributions"]["pensionInsurance"]["employeeAmount"] == "18.72"

    # Soli is a real persisted field now (PayslipItem.soli) and the blocked
    # employee contributes zero everywhere, so the summed value is an honest
    # CALCULATED 0.00 (the minijob payslip's Soli IS 0 — minijob flat tax
    # carries no employee Soli) — never a fabricated nonzero and never
    # UNAVAILABLE.
    sql = report["statutoryContributions"]["solidaritySurcharge"]
    assert sql["status"] == "CALCULATED"
    assert sql["amount"] == "0.00"

    assert report["wageTaxStatus"] == {
        "calculated": 1, "blocked": 1, "partial": 0,
        "blockedReasonCounts": {"GERMANY_CEILING_NOT_AVAILABLE": 1},
    }
    # Phase 8BR: this specific metric only counts GERMANY_PAP_NOT_AVAILABLE
    # blocks — regular_emp is blocked on a missing ceiling instead (REGULAR
    # itself no longer blocks on PAP alone), so it's correctly 0 here.
    assert report["papBlockedPayrollCount"] == 0

    assert len(report["blockedEmployees"]) == 1
    blocked = report["blockedEmployees"][0]
    assert blocked["employeeId"] == regular_emp.id
    assert blocked["blockedReasonCode"] == "GERMANY_CEILING_NOT_AVAILABLE"

    assert len(report["payrollRuns"]) == 1
    assert report["payrollRuns"][0]["calculatedCount"] == 1
    assert report["payrollRuns"][0]["blockedCount"] == 1


def test_report_period_filter_excludes_runs_outside_the_window(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp_jan = _make_employee(db, organization.id, code="DE-RPT-JAN", gross=520)
    emp_feb = _make_employee(db, organization.id, code="DE-RPT-FEB", gross=520)
    _make_full_profile(db, emp_jan, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, emp_feb, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp_jan.id, day=15, month=1)
    _add_attendance(db, organization.id, emp_feb.id, day=15, month=2)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp_jan.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp_feb.id], date(2026, 2, 1), date(2026, 2, 28), date(2026, 3, 1)),
        organization_id=organization.id,
    )

    jan_only = service.get_germany_payroll_summary_report(
        db, organization.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert jan_only["employeeCounts"]["total"] == 1
    assert jan_only["grossPay"]["amount"] == "520.00"

    all_time = service.get_germany_payroll_summary_report(db, organization.id)
    assert all_time["employeeCounts"]["total"] == 2
    assert all_time["grossPay"]["amount"] == "1040.00"


def test_report_is_tenant_isolated(db, organization, monkeypatch):
    from app.modules.organizations.models import Organization

    _stub_business_code_generation(monkeypatch)
    other_org = Organization(organization_name="Other Org", organization_code="RPTOTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    emp_this_org = _make_employee(db, organization.id, code="DE-RPT-THIS", gross=520)
    emp_other_org = _make_employee(db, other_org.id, code="DE-RPT-OTHER", gross=520)
    _make_full_profile(db, emp_this_org, organization.id, de_employment_classification="MINIJOB")
    _make_full_profile(db, emp_other_org, other_org.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)  # global registries — shared across orgs by design
    _add_attendance(db, organization.id, emp_this_org.id)
    _add_attendance(db, other_org.id, emp_other_org.id)

    service.create_payroll_run(db, created_by=1, data=_run_data([emp_this_org.id]), organization_id=organization.id)
    service.create_payroll_run(db, created_by=1, data=_run_data([emp_other_org.id]), organization_id=other_org.id)

    report = service.get_germany_payroll_summary_report(db, organization.id)
    assert report["employeeCounts"]["total"] == 1
    assert report["blockedEmployees"] == []
    assert all(e["employeeId"] != emp_other_org.id for e in report.get("blockedEmployees", []))
    assert report["grossPay"]["amount"] == "520.00"  # not 1040.00 — the other org's payslip must never leak in

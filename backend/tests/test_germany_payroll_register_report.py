"""
tests/test_germany_payroll_register_report.py
------------------------------------------------
Phase 8BS — regression coverage for the generic Payroll Register
(generate_report_csv_bytes / generate_report_pdf_bytes) Germany column
set. Phase 8BH's own audit found this register mislabeled Lohnsteuer as
"Income Tax" and omitted Kirchensteuer/Soli entirely, even though both
are real, persisted PayslipItem columns — the exact defect class the
payslip PDF's own income_tax_labels/church-tax fix already addressed
elsewhere. This file locks in the fix: real column labels, and no
double-counting of Soli (which is already folded into `tds`).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
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
    source = SourceArtifact(agency="Test Fixture", title="Register report test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_all_registries(db):
    source = _make_source(db)
    for branch, monthly, annual in (("GKV_PV", Decimal("5812.50"), Decimal("69750.00")), ("RV_ALV", Decimal("8450.00"), Decimal("101400.00"))):
        row = service.create_contribution_ceiling_record(
            db, GermanyContributionCeilingCreate(
                branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
                effective_from=date(2026, 1, 1), authority_source_id=source.id,
            ), actor_id=1,
        )
        row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=1)
        row = service.set_contribution_ceiling_approver(db, row.id, actor_id=2)
        service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=2)
    fund = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id="REG-FUND", fund_name="Register Test Fund",
            supplementary_rate_pct=Decimal("1.7000"), effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=1,
    )
    fund = service.set_health_fund_status(db, fund.id, "VERIFIED", actor_id=1)
    fund = service.set_health_fund_approver(db, fund.id, actor_id=2)
    service.set_health_fund_status(db, fund.id, "PUBLISHED", actor_id=2)
    pv = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category="CHILDLESS", is_saxony=False,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=1,
    )
    pv = service.set_pv_configuration_status(db, pv.id, "VERIFIED", actor_id=1)
    pv = service.set_pv_configuration_approver(db, pv.id, actor_id=2)
    service.set_pv_configuration_status(db, pv.id, "PUBLISHED", actor_id=2)


def _make_full_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=True,
        de_church_tax_land="DE-BY", de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="REG-FUND",
        de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
        de_employment_classification="REGULAR",
    )
    kwargs.update(overrides)
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(**kwargs), actor_id=None,
    )


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_de_register_csv_columns_labeled_correctly_and_soli_not_double_counted(db, organization, monkeypatch):
    """A high-earning employee (EUR 15,000/month) whose annual Lohnsteuer
    is well above the SolzG exemption threshold produces a real, nonzero
    Soli — proving both that the register actually surfaces Kirchensteuer/
    Soli (Phase 8BH's own found gap) AND that 'Lohnsteuer' + 'Soli' sum
    to the same total the payslip's own `tds` field carries (no visual
    double-count)."""
    _stub_business_code_generation(monkeypatch)
    # generate_report_csv_bytes picks its statutory-column set from the
    # ORGANIZATION's own jurisdiction (Organization.country /
    # CompanyComplianceDetails.jurisdiction_country), not the individual
    # employee's country_code — the shared `organization` fixture defaults
    # to no country at all, which falls through to the generic column set.
    organization.country = "DE"
    db.add(organization)
    db.commit()
    emp = _make_employee(db, organization.id, code="DE-REG-CSV", gross=15000)
    _make_full_profile(db, emp, organization.id)
    _publish_all_registries(db)
    db.add(PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()

    run = service.create_payroll_run(
        db, created_by=1,
        data=PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        ),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"
    assert item.soli > Decimal("0"), "this test requires a high enough gross to actually trigger nonzero Soli"
    assert item.church_tax > Decimal("0")

    csv_bytes = service.generate_report_csv_bytes(db, run.id, organization_id=organization.id)
    text = csv_bytes.decode("utf-8")
    header = text.splitlines()[0]
    assert "Lohnsteuer" in header
    assert "Kirchensteuer" in header
    assert "Soli" in header
    assert "Income Tax" not in header

    import csv
    import io
    rows = list(csv.reader(io.StringIO(text)))
    header_row, data_row = rows[0], rows[1]
    lohnsteuer_idx = header_row.index("Lohnsteuer")
    soli_idx = header_row.index("Soli")
    kirchensteuer_idx = header_row.index("Kirchensteuer")

    lohnsteuer_only = Decimal(data_row[lohnsteuer_idx])
    soli_value = Decimal(data_row[soli_idx])
    kirchensteuer_value = Decimal(data_row[kirchensteuer_idx])

    assert soli_value == item.soli
    assert kirchensteuer_value == item.church_tax
    # The combined figure the payslip itself persists as `tds` must equal
    # exactly Lohnsteuer-alone + Soli — never double-counted, never lost.
    assert (lohnsteuer_only + soli_value).quantize(Decimal("0.01")) == item.tds.quantize(Decimal("0.01"))

    # Phase 8BX (real-UAT finding): _other_deductions previously omitted
    # church_tax from the fields it subtracts out of total_deductions,
    # silently double-counting a church-tax-liable employee's Kirchensteuer
    # into "Other Deductions" too — so Gross minus every displayed register
    # column never actually equalled Net Pay for this exact scenario. Full
    # gross-to-net reconciliation across every displayed CSV column is now
    # a permanent regression guard.
    gross_idx = header_row.index("Gross Pay")
    pension_idx = header_row.index("Pension Ins.")
    social_idx = header_row.index("Social Ins.")
    other_ded_idx = header_row.index("Other Deductions")
    net_idx = header_row.index("Net Pay")
    other_deductions_value = Decimal(data_row[other_ded_idx])
    assert other_deductions_value == Decimal("0.00"), (
        "this employee's only deductions are Lohnsteuer/Soli/Kirchensteuer/RV/ALV+GKV+PV, "
        "all already shown in their own dedicated columns — Other Deductions must be a real 0"
    )
    reconciled_net = (
        Decimal(data_row[gross_idx]) - lohnsteuer_only - soli_value - kirchensteuer_value
        - Decimal(data_row[pension_idx]) - Decimal(data_row[social_idx]) - other_deductions_value
    )
    assert reconciled_net.quantize(Decimal("0.01")) == Decimal(data_row[net_idx]).quantize(Decimal("0.01"))


def test_de_register_pdf_renders_without_error_for_calculated_employee(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    organization.country = "DE"
    db.add(organization)
    db.commit()
    emp = _make_employee(db, organization.id, code="DE-REG-PDF", gross=4500)
    _make_full_profile(db, emp, organization.id, de_church_tax_liable=False)
    _publish_all_registries(db)
    db.add(PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()

    run = service.create_payroll_run(
        db, created_by=1,
        data=PayrollRunCreate(
            periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
            employeeIds=[emp.id], auto_generate_payslips=True,
        ),
        organization_id=organization.id,
    )
    pdf_bytes = service.generate_report_pdf_bytes(db, run.id, organization_id=organization.id)
    assert pdf_bytes.startswith(b"%PDF-")

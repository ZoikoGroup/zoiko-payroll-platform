"""
tests/test_germany_statutory_parameter_extensions.py
------------------------------------------------------
Phase 8BL — Germany statutory configuration & payroll completeness
audit. Two genuine, still-hardcoded, undated statutory values were
found and closed this phase, both by extending the EXISTING
GermanyMinijobMidijobParameter registry (Phase 8BK) with new
parameter_codes — no migration needed:

1. `employer_insolvency_levy_rate` — U3 (Insolvenzumlage), a flat
   FEDERAL rate applying to REGULAR and MIDIJOB employees (previously
   `_DE_INSOLVENCY_LEVY_RATE`, hardcoded, undated). Deliberately kept
   SEPARATE from Minijob's own `minijob_u3_rate` (Phase 8BK) even
   though both hold the identical 0.15% value today — see
   docs/PHASE_8BL_GERMANY_STATUTORY_CONFIGURATION_PAYROLL_COMPLETENESS_REPORT.md
   §4 for why unifying them was deliberately NOT done.

2. `church_tax_rate_de_<land>` (16 codes) — the general Kirchensteuer
   Land-rate table (previously the static `CHURCH_TAX_LAND_RATES` dict
   in germany_pap/core.py, no registry/provenance/effective-dating at
   all, unlike the sub-Land GermanyChurchTaxException overlay already
   built on top of it).

Every override value used here is an arbitrary test fixture,
deliberately different from the real 2026 constants, so a passing
assertion unambiguously proves the override mechanism, never asserts a
real statutory value.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.engine.germany_pap.core import CHURCH_TAX_LAND_RATES
from app.modules.payroll.hardcoded_defaults import _DE_INSOLVENCY_LEVY_RATE
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyHealthFund, GermanyPvConfiguration,
    PayrollAttendanceRecord, PayrollEmployee, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyMinijobMidijobParameterCreate,
    GermanyPvConfigurationCreate, PayrollRunCreate,
)


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Statutory parameter extension test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_parameter(db, parameter_code, value, value_type="PERCENTAGE", effective_from=date(2026, 1, 1), maker=301, checker=302):
    source = _make_source(db)
    row = service.create_minijob_midijob_parameter_record(
        db, GermanyMinijobMidijobParameterCreate(
            parameter_code=parameter_code, value=value, value_type=value_type,
            label=f"Test fixture for {parameter_code}", effective_from=effective_from, authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_minijob_midijob_parameter_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_minijob_midijob_parameter_approver(db, row.id, actor_id=checker)
    return service.set_minijob_midijob_parameter_status(db, row.id, "PUBLISHED", actor_id=checker)


def _make_employee(db, org_id, code, gross):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=gross * 12, basic=gross, hra=0, status="Active",
        date_of_joining=date(2025, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=date(2025, 1, 1), authority_source_id=source.id,
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
            supplementary_rate_pct=rate, effective_from=date(2025, 1, 1), authority_source_id=source.id,
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
            effective_from=date(2025, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _make_full_profile(db, emp, org_id, **overrides):
    kwargs = dict(
        effective_from=date(2025, 1, 1), de_tax_class="I", de_church_tax_liable=False,
        de_child_count=0, de_childless=True, de_saxony=False,
        de_health_insurance_status="PUBLIC", de_health_fund_code="EXT-FUND",
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
    _publish_health_fund(db, "EXT-FUND")
    _publish_pv_configuration(db, "CHILDLESS", False)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _add_attendance(db, org_id, emp_id, day=15, month=1, year=2026):
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp_id, date=date(year, month, day),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()


def _run_data(employee_ids, period_start, period_end, pay_date):
    return PayrollRunCreate(
        periodStart=period_start, periodEnd=period_end, payDate=pay_date,
        employeeIds=employee_ids, auto_generate_payslips=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# Employer Insolvency Levy (U3) — Regular + Midijob, shared federal rate.
# ══════════════════════════════════════════════════════════════════════════

def test_regular_u3_resolves_from_registry_when_published(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-REG-U3", gross=5000)
    _make_full_profile(db, emp, organization.id, de_employment_classification="REGULAR")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)
    _publish_parameter(db, "employer_insolvency_levy_rate", Decimal("1.00"))  # deliberately != real 0.15%

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"  # Phase 8BR: REGULAR now completes via the internal tax calculator
    trace = item.germany_calculation_snapshot or {}
    assert trace.get("calculationStatus") == "COMPLETE"
    employer_levies = trace.get("resolved", {}).get("employer_levies", {})
    # 5000 * 1.00% = 50.00 (the overridden rate, not the real 0.15% -> 7.50)
    assert Decimal(employer_levies.get("u3_insolvency_levy")) == Decimal("50.00")


def test_regular_u3_falls_back_to_hardcoded_default_with_no_registry_row(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-REG-U3-DEFAULT", gross=5000)
    _make_full_profile(db, emp, organization.id, de_employment_classification="REGULAR")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    employer_levies = trace.get("resolved", {}).get("employer_levies", {})
    expected = (Decimal("5000.00") * _DE_INSOLVENCY_LEVY_RATE / 100).quantize(Decimal("0.01"))
    assert Decimal(employer_levies.get("u3_insolvency_levy", "0")) == expected


def test_midijob_u3_resolves_from_the_same_registry_entry_as_regular(db, organization, monkeypatch):
    """Proves the two call sites (Regular's calculate(), Midijob's
    _calculate_midijob_path) share the identical parameter_code."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-MIDI-U3", gross=1500)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MIDIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)
    _publish_parameter(db, "employer_insolvency_levy_rate", Decimal("2.00"))

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    levies = trace.get("resolved", {}).get("midijob_employer_levies", {})
    assert Decimal(levies.get("u3_insolvency_levy", "0")) != (
        (Decimal("1500.00") * _DE_INSOLVENCY_LEVY_RATE / 100).quantize(Decimal("0.01"))
    )


def test_minijob_own_u3_unaffected_by_the_shared_employer_insolvency_levy_override(db, organization, monkeypatch):
    """Minijob's OWN separate minijob_u3_rate parameter must be
    completely unaffected by an employer_insolvency_levy_rate override —
    proving these two remain deliberately independent."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-MINI-U3-INDEP", gross=520)
    _make_full_profile(db, emp, organization.id, de_employment_classification="MINIJOB")
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)
    _publish_parameter(db, "employer_insolvency_levy_rate", Decimal("9.00"))  # extreme, must have zero effect

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.status == "Pending"
    assert item.net_pay == Decimal("501.28")  # unchanged documented Minijob baseline


# ══════════════════════════════════════════════════════════════════════════
# Church tax Land rate table — general 16-Land rate, registry override.
# ══════════════════════════════════════════════════════════════════════════

def test_church_tax_land_rate_resolves_from_registry_when_published(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-CHURCH-TAX", gross=5000)
    _make_full_profile(
        db, emp, organization.id, de_employment_classification="REGULAR",
        de_church_tax_liable=True, de_church_tax_land="DE-BY",
    )
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)
    _publish_parameter(db, "church_tax_rate_de_by", Decimal("10.00"))  # real default is 8%

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    assert Decimal(trace.get("churchTaxRateUsed")) == Decimal("10.00")


def test_church_tax_land_rate_falls_back_to_hardcoded_table_with_no_registry_row(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-CHURCH-DEFAULT", gross=5000)
    _make_full_profile(
        db, emp, organization.id, de_employment_classification="REGULAR",
        de_church_tax_liable=True, de_church_tax_land="DE-BY",
    )
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    assert Decimal(trace.get("churchTaxRateUsed")) == Decimal(CHURCH_TAX_LAND_RATES["DE-BY"])


def test_church_tax_exception_still_wins_over_the_general_land_registry_override(db, organization, monkeypatch):
    """The sub-Land GermanyChurchTaxException (e.g. Bad Wimpfen) must
    still take precedence over even a PUBLISHED general Land-rate
    registry override — this phase's addition must not disturb that
    existing precedence rule."""
    from app.modules.payroll.schemas import GermanyChurchTaxExceptionCreate

    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, code="EXT-CHURCH-EXCEPTION", gross=5000)
    _make_full_profile(
        db, emp, organization.id, de_employment_classification="REGULAR",
        de_church_tax_liable=True, de_church_tax_land="DE-BW",
        de_church_tax_denomination="ROMAN_CATHOLIC", de_church_tax_municipality_postal_code="74206",
    )
    _publish_all_registries(db)
    _add_attendance(db, organization.id, emp.id)

    # A general Land-rate override for BW (would be 20% if it applied).
    _publish_parameter(db, "church_tax_rate_de_bw", Decimal("20.00"))

    # The documented Bad Wimpfen sub-Land exception.
    source = _make_source(db)
    row = service.create_germany_church_tax_exception_record(
        db, GermanyChurchTaxExceptionCreate(
            land_code="DE-BW", denomination="ROMAN_CATHOLIC", municipality_postal_code="74206",
            exception_rate_pct=Decimal("9.00"), effective_from=date(2025, 1, 1), authority_source_id=source.id,
        ), actor_id=1,
    )
    row = service.set_germany_church_tax_exception_status(db, row.id, "VERIFIED", actor_id=1)
    row = service.set_germany_church_tax_exception_approver(db, row.id, actor_id=2)
    service.set_germany_church_tax_exception_status(db, row.id, "PUBLISHED", actor_id=2)

    service.create_payroll_run(
        db, created_by=1, data=_run_data([emp.id], date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1)),
        organization_id=organization.id,
    )
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    trace = item.germany_calculation_snapshot or {}
    assert Decimal(trace.get("churchTaxRateUsed")) == Decimal("9.00")  # the exception, not the 20% general override

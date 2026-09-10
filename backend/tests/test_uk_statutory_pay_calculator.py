"""
tests/test_uk_statutory_pay_calculator.py
---------------------------------------------
Coverage for service.py's calculate_uk_statutory_pay() (ZP-TAX-UK-2026-27-
001 §11/§12 gap-closure Phase 5, 2026-09-09) — the on-demand SSP/
Statutory Family Pay calculator. DB-integration style: real
PayrollEmployee/ContributionRate rows, exercising the full resolution
chain (employee -> country -> rate_map -> uk.py's calculate_ssp/
calculate_statutory_family_pay/calculate_family_pay_employer_recovery),
not just the pure engine functions already covered elsewhere.

Rates are seeded ORG-SCOPED (organization_id=org_id), not canonical
(organization_id=None) — a fresh test org isn't opted into canonical
tax-pack tracking, and get_contribution_rates' _apply_org_filter only
ever matches organization_id == the given id when one is given (it does
NOT fall back to NULL/canonical rows), so a canonical-only seed would be
invisible here.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, PayrollEmployee, PayrollRun, PayslipItem, PayrollStatus


def _make_uk_employee(db, org_id, code="SPC1", pay_frequency="Monthly"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("60000"), pay_frequency=pay_frequency,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_ssp_rates(db, org_id):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="ssp_weekly_cap", label="SSP Weekly Cap",
        employee_share="—", employer_share="—", total="£123.25",
        flat_amount=Decimal("123.25"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="ssp_awe_pct", label="SSP AWE Percentage",
        employee_share="80%", employer_share="—", total="80%",
        employee_rate_pct=Decimal("80"),
    ))
    db.commit()


def _seed_family_pay_rates(db, org_id):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_awe_pct", label="Family Pay AWE Percentage",
        employee_share="90%", employer_share="—", total="90%",
        employee_rate_pct=Decimal("90"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_flat_rate", label="Family Pay Standard Weekly Rate",
        employee_share="—", employer_share="—", total="£194.32",
        flat_amount=Decimal("194.32"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_recov_thresh", label="Family Pay Recovery Threshold",
        employee_share="—", employer_share="—", total="£45,000",
        flat_amount=Decimal("45000"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_recov_small", label="Family Pay Recovery Rate — Small Employer",
        employee_share="—", employer_share="109%", total="109%",
        employer_rate_pct=Decimal("109"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_recov_std", label="Family Pay Recovery Rate — Standard",
        employee_share="—", employer_share="92%", total="92%",
        employer_rate_pct=Decimal("92"),
    ))
    db.commit()


def _make_run(db, org_id, pay_date, label="Test Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=pay_date, period_end=pay_date, pay_date=pay_date,
        status=PayrollStatus.PAID.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_payslip(db, run, employee, org_id, gross_pay):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=org_id,
        employee_name=employee.name, gross_pay=gross_pay,
    )
    db.add(item)
    db.commit()
    return item


def test_ssp_with_supplied_awe(db, organization):
    _seed_ssp_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SSP1")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SSP", date(2026, 6, 1),
        qualifying_days_in_period=7, qualifying_days_per_week=7,
        average_weekly_earnings=Decimal("500"),
    )
    assert result["eligible"] is True
    # lower of 123.25 and 80% of 500 (=400) -> 123.25, all 7 qualifying days
    assert result["amount"] == Decimal("123.25")
    assert result["average_weekly_earnings_source"] == "supplied"


def test_ssp_derives_awe_from_history_when_not_supplied(db, organization):
    _seed_ssp_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SSP2", pay_frequency="Weekly")
    pay_dates = [date(2026, 6, d) for d in (1, 8, 15, 22, 29)] + [date(2026, 7, d) for d in (6, 13, 20)]
    for pd in pay_dates:
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, Decimal("500"))
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SSP", date(2026, 7, 27),
        qualifying_days_in_period=7, qualifying_days_per_week=7,
    )
    assert result["eligible"] is True
    assert result["average_weekly_earnings_source"] == "derived"
    assert result["average_weekly_earnings"] == Decimal("500.00")
    assert result["amount"] == Decimal("123.25")


def test_ssp_fails_closed_when_awe_cannot_be_derived(db, organization):
    _seed_ssp_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SSP3", pay_frequency="Weekly")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SSP", date(2026, 7, 27),
        qualifying_days_in_period=7, qualifying_days_per_week=7,
    )
    assert result["eligible"] is False
    assert "could not be derived" in result["reason"]


def test_ssp_missing_qualifying_days_raises(db, organization):
    _seed_ssp_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SSP4")
    with pytest.raises(BadRequestException):
        service.calculate_uk_statutory_pay(
            db, organization.id, emp.id, "SSP", date(2026, 6, 1),
            average_weekly_earnings=Decimal("500"),
        )


def test_smp_first_6_weeks_uncapped(db, organization):
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SMP1")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SMP", date(2026, 6, 1),
        week_number=3, average_weekly_earnings=Decimal("300"),
    )
    assert result["eligible"] is True
    # first 6 weeks: 90% of AWE, uncapped -> 270.00 (would be capped at
    # 194.32 in later weeks)
    assert result["amount"] == Decimal("270.00")


def test_spp_standard_rate_capped(db, organization):
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SPP1")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SPP", date(2026, 6, 1),
        week_number=1, average_weekly_earnings=Decimal("500"),
    )
    assert result["eligible"] is True
    # lower of 194.32 and 90% of 500 (=450) -> 194.32
    assert result["amount"] == Decimal("194.32")


def test_smp_with_employer_recovery_small_employer(db, organization):
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SMP2")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SMP", date(2026, 6, 1),
        week_number=1, average_weekly_earnings=Decimal("300"),
        include_employer_recovery=True, prior_year_total_class1_nic=Decimal("40000"),
    )
    assert result["eligible"] is True
    recovery = result["employer_recovery"]
    assert recovery["eligible"] is True
    # 270.00 * 109% = 294.30
    assert recovery["recovery_amount"] == Decimal("294.30")


def test_ssp_never_gets_employer_recovery_even_if_requested(db, organization):
    _seed_ssp_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "SPC-SSP5")
    result = service.calculate_uk_statutory_pay(
        db, organization.id, emp.id, "SSP", date(2026, 6, 1),
        qualifying_days_in_period=7, qualifying_days_per_week=7,
        average_weekly_earnings=Decimal("500"),
        include_employer_recovery=True, prior_year_total_class1_nic=Decimal("40000"),
    )
    assert "employer_recovery" not in result


def test_unknown_payment_type_raises(db, organization):
    emp = _make_uk_employee(db, organization.id, "SPC-BAD1")
    with pytest.raises(BadRequestException):
        service.calculate_uk_statutory_pay(
            db, organization.id, emp.id, "NOT_A_REAL_TYPE", date(2026, 6, 1),
            average_weekly_earnings=Decimal("500"),
        )


def test_nonexistent_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_uk_statutory_pay(
            db, organization.id, 999999, "SSP", date(2026, 6, 1),
            average_weekly_earnings=Decimal("500"),
        )


def test_non_uk_employee_rejected(db, organization):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="SPC-IN1", name="Indian Employee",
        country_code="IN", ctc=Decimal("600000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with pytest.raises(BadRequestException):
        service.calculate_uk_statutory_pay(
            db, organization.id, emp.id, "SSP", date(2026, 6, 1),
            average_weekly_earnings=Decimal("500"),
        )

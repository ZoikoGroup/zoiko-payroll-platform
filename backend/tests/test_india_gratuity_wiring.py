"""
tests/test_india_gratuity_wiring.py
------------------------------------
Coverage for service.py's calculate_india_employee_gratuity (ZP-TAX-IN-
2026-27-001 §11, gap-closure Phase D, 2026-09-10) — the standalone/
on-demand caller that makes engine/countries/india.py's calculate_gratuity
(previously built, tested, but never called from anywhere) reachable via
a real employee record + rate_map, same DB-integration style as
test_uk_court_ordered_deductions.py.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, ContributionRate


def _make_in_employee(db, org_id, code="G1", basic=None, ctc=Decimal("600000"), date_of_joining=None, date_of_leaving=None):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="IN", ctc=ctc, basic=basic,
        date_of_joining=date_of_joining, date_of_leaving=date_of_leaving,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_uk_employee(db, org_id, code="U1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="UK", ctc=Decimal("60000"))
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_gratuity_rates(db, organization_id, min_years=Decimal("5"), max_amt=None):
    # organization_id-scoped (not canonical organization_id=None): the
    # test `organization` fixture hasn't opted into canonical tax-pack
    # tracking, so _resolve_effective_rate_inputs reads this org's own
    # ContributionRate rows — same convention the ESI-wage-ceiling DB
    # integration test above already uses.
    db.add(ContributionRate(
        organization_id=organization_id, jurisdiction_country="IN", component_key="gratuity_min_yrs",
        label="gratuity_min_yrs", employee_share="—", employer_share="—", total="—",
        flat_amount=min_years,
    ))
    if max_amt is not None:
        db.add(ContributionRate(
            organization_id=organization_id, jurisdiction_country="IN", component_key="gratuity_max_amt",
            label="gratuity_max_amt", employee_share="—", employer_share="—", total="—",
            flat_amount=max_amt,
        ))
    db.commit()


def test_gratuity_rejects_non_india_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_india_employee_gratuity(db, organization.id, emp.id)


def test_gratuity_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_india_employee_gratuity(db, organization.id, 999999)


def test_gratuity_fails_closed_without_dates(db, organization):
    emp = _make_in_employee(db, organization.id, basic=Decimal("600000"))
    with pytest.raises(BadRequestException):
        service.calculate_india_employee_gratuity(db, organization.id, emp.id)


def test_gratuity_fails_closed_without_min_years_configured(db, organization):
    emp = _make_in_employee(
        db, organization.id, basic=Decimal("600000"),
        date_of_joining=date(2018, 1, 1), date_of_leaving=date(2026, 1, 1),
    )
    result = service.calculate_india_employee_gratuity(db, organization.id, emp.id)
    assert result["eligible"] is False
    assert result["gratuity_amount"] == Decimal("0")


def test_gratuity_calculates_from_stored_basic(db, organization):
    # 8 completed years, basic 600,000/yr -> monthly 50,000 -> per-day
    # 50,000/26 = 1,923.0769..., *15 = 28,846.1538... per year, *8 = 230,769.23.
    _seed_gratuity_rates(db, organization.id)
    emp = _make_in_employee(
        db, organization.id, basic=Decimal("600000"),
        date_of_joining=date(2018, 1, 1), date_of_leaving=date(2026, 1, 1),
    )
    result = service.calculate_india_employee_gratuity(db, organization.id, emp.id)
    assert result["eligible"] is True
    assert result["gratuity_amount"] == Decimal("230769.23")


def test_gratuity_uses_last_drawn_wage_override(db, organization):
    _seed_gratuity_rates(db, organization.id)
    emp = _make_in_employee(
        db, organization.id, basic=Decimal("600000"),
        date_of_joining=date(2018, 1, 1), date_of_leaving=date(2026, 1, 1),
    )
    default_result = service.calculate_india_employee_gratuity(db, organization.id, emp.id)
    overridden_result = service.calculate_india_employee_gratuity(
        db, organization.id, emp.id, last_drawn_monthly_wage_override=Decimal("100000"),
    )
    assert overridden_result["gratuity_amount"] == default_result["gratuity_amount"] * 2


def test_gratuity_respects_max_amount_ceiling(db, organization):
    _seed_gratuity_rates(db, organization.id, max_amt=Decimal("200000"))
    emp = _make_in_employee(
        db, organization.id, basic=Decimal("600000"),
        date_of_joining=date(2018, 1, 1), date_of_leaving=date(2026, 1, 1),
    )
    result = service.calculate_india_employee_gratuity(db, organization.id, emp.id)
    assert result["gratuity_amount"] == Decimal("200000")


def test_gratuity_date_of_leaving_override_used_before_employee_marked_left(db, organization):
    # Employee record has no date_of_leaving yet (still Active) — an
    # override date lets a payroll operator preview the liability before
    # actually processing the exit.
    _seed_gratuity_rates(db, organization.id)
    emp = _make_in_employee(
        db, organization.id, basic=Decimal("600000"), date_of_joining=date(2018, 1, 1),
    )
    result = service.calculate_india_employee_gratuity(
        db, organization.id, emp.id, date_of_leaving_override=date(2026, 1, 1),
    )
    assert result["eligible"] is True
    assert result["gratuity_amount"] == Decimal("230769.23")

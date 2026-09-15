"""
tests/test_us_supplemental_wages.py
--------------------------------------
Coverage for service.calculate_us_supplemental_wage_withholding (ZP-TAX-
US-2026-001 §3.1, gap-closure 2026-09-12) — IRS Pub. 15's flat-rate
method for supplemental wages: 22% flat, with the mandatory 37% rate
applying instead to whatever portion of cumulative calendar-year
supplemental wages exceeds $1,000,000.

Same test structure as tests/test_ca_special_payment.py: rejection/
not-found tests exercise the real DB path; the arithmetic tests
monkeypatch service._resolve_employee_calc_inputs directly so this file
verifies only THIS function's own threshold-splitting logic, not the
full rate-map resolver stack (already covered elsewhere).
"""
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


def _make_us_employee(db, org_id, code="S1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="US", ctc=Decimal("120000"))
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_ca_employee(db, org_id, code="C1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="CA", ctc=Decimal("60000"))
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _stub_calc_inputs(monkeypatch):
    def _fake(db, organization_id, employee, cache=None, payroll_date=None, org_opted_in=False):
        return ("US", {}, [], None, "CA", {}, [], {}, {}, None, None, "CA")
    monkeypatch.setattr(service, "_resolve_employee_calc_inputs", _fake)


def test_us_supplemental_wages_rejects_non_us_employee(db, organization):
    emp = _make_ca_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_us_supplemental_wage_withholding(db, organization.id, emp.id, Decimal("5000"))


def test_us_supplemental_wages_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_us_supplemental_wage_withholding(db, organization.id, 999999, Decimal("5000"))


def test_us_supplemental_wages_rejects_negative_amounts(db, organization):
    emp = _make_us_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_us_supplemental_wage_withholding(db, organization.id, emp.id, Decimal("-1"))
    with pytest.raises(BadRequestException):
        service.calculate_us_supplemental_wage_withholding(db, organization.id, emp.id, Decimal("5000"), cytd_supplemental_wages_before=Decimal("-1"))


def test_us_supplemental_wages_entirely_under_threshold_uses_flat_22_pct(db, organization, monkeypatch):
    _stub_calc_inputs(monkeypatch)
    emp = _make_us_employee(db, organization.id)
    result = service.calculate_us_supplemental_wage_withholding(db, organization.id, emp.id, Decimal("10000"))
    assert result["amount_at_flat_rate"] == Decimal("10000")
    assert result["amount_at_high_rate"] == Decimal("0")
    assert result["withholding_at_flat_rate"] == Decimal("2200.00")  # 10000 * 22%
    assert result["total_withholding"] == Decimal("2200.00")


def test_us_supplemental_wages_entirely_over_threshold_uses_37_pct(db, organization, monkeypatch):
    _stub_calc_inputs(monkeypatch)
    emp = _make_us_employee(db, organization.id)
    # Already at $1,000,000 CYTD before this payment -- the entire new
    # payment falls above the threshold, mandatory 37% on all of it.
    result = service.calculate_us_supplemental_wage_withholding(
        db, organization.id, emp.id, Decimal("50000"), cytd_supplemental_wages_before=Decimal("1000000"),
    )
    assert result["amount_at_flat_rate"] == Decimal("0")
    assert result["amount_at_high_rate"] == Decimal("50000")
    assert result["withholding_at_high_rate"] == Decimal("18500.00")  # 50000 * 37%
    assert result["total_withholding"] == Decimal("18500.00")


def test_us_supplemental_wages_straddles_threshold_splits_between_both_rates(db, organization, monkeypatch):
    _stub_calc_inputs(monkeypatch)
    emp = _make_us_employee(db, organization.id)
    # $980,000 CYTD before + $50,000 this payment = $1,030,000 CYTD after.
    # $20,000 of this payment falls under the $1,000,000 threshold (22%),
    # $30,000 falls above it (37%, mandatory).
    result = service.calculate_us_supplemental_wage_withholding(
        db, organization.id, emp.id, Decimal("50000"), cytd_supplemental_wages_before=Decimal("980000"),
    )
    assert result["amount_at_flat_rate"] == Decimal("20000")
    assert result["amount_at_high_rate"] == Decimal("30000")
    assert result["withholding_at_flat_rate"] == Decimal("4400.00")   # 20000 * 22%
    assert result["withholding_at_high_rate"] == Decimal("11100.00")  # 30000 * 37%
    assert result["total_withholding"] == Decimal("15500.00")
    assert result["cytd_supplemental_wages_after"] == Decimal("1030000")

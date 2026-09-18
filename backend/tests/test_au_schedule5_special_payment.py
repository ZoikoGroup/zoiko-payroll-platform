"""
tests/test_au_schedule5_special_payment.py
---------------------------------------------
Coverage for service.py's calculate_au_employee_schedule5_withholding
(ZP-TAX-AU-2026-27-001 §9, production-readiness fix plan Tier 3.1,
2026-09-18) — the standalone/on-demand caller that makes engine/
countries/australia.py's calculate_au_schedule5_back_payment_withholding
(previously built, tested, but never called from anywhere) actually
reachable, same architecture as test_ca_special_payment.py.

Same monkeypatch-_resolve_employee_calc_inputs convention as that file:
this suite verifies THIS function's own orchestration (building a real
ctx, calling the engine's incremental-tax comparison), not the DB
resolver stack, which has its own separate coverage.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


@dataclass
class Slab:
    min_amount: Decimal = Decimal("0")
    max_amount: Optional[Decimal] = None
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"
    filing_status: Optional[str] = None
    flat_amount: Optional[Decimal] = None


def _make_au_employee(db, org_id, code="A1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("80000"),
        au_tfn_status="PROVIDED", au_residency_status="RESIDENT", au_tax_free_threshold_claimed=True,
        pay_frequency="Weekly",
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


# Same real Scale 2 coefficient bands as test_engine_standard.py's own
# _AU_PAYG_SCALE2_SLABS, low-income range only (matches this file's own
# test amounts, which stay well under $673/week).
_AU_SCALE2_SLABS = [
    Slab(Decimal("0"), Decimal("362"), Decimal("0"), rule_type="AU_PAYG_COEFFICIENT", filing_status="SCALE_2", flat_amount=Decimal("0")),
    Slab(Decimal("362"), Decimal("538"), Decimal("0.15"), rule_type="AU_PAYG_COEFFICIENT", filing_status="SCALE_2", flat_amount=Decimal("54.3462")),
    Slab(Decimal("538"), Decimal("673"), Decimal("0.25"), rule_type="AU_PAYG_COEFFICIENT", filing_status="SCALE_2", flat_amount=Decimal("108.2135")),
]


def _stub_calc_inputs(monkeypatch, *, slabs):
    def _fake(db, organization_id, employee, cache=None, payroll_date=None, org_opted_in=False):
        return ("AU", {}, slabs, None, None, {}, [], {}, {}, None, None, None)
    monkeypatch.setattr(service, "_resolve_employee_calc_inputs", _fake)


def test_au_schedule5_rejects_non_australia_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_au_employee_schedule5_withholding(db, organization.id, emp.id, Decimal("500"), Decimal("520"))


def test_au_schedule5_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_au_employee_schedule5_withholding(db, organization.id, 999999, Decimal("500"), Decimal("520"))


def test_au_schedule5_rejects_negative_amounts(db, organization):
    emp = _make_au_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_au_employee_schedule5_withholding(db, organization.id, emp.id, Decimal("-1"), Decimal("520"))
    with pytest.raises(BadRequestException):
        service.calculate_au_employee_schedule5_withholding(db, organization.id, emp.id, Decimal("500"), Decimal("-1"))


def test_au_schedule5_incremental_withholding_matches_engine_calc(db, organization, monkeypatch):
    # Same figures independently verified against
    # calculate_au_schedule5_back_payment_withholding directly: $500
    # regular weekly gross withholds $21 alone; averaging a $520 bonus
    # over 52 weeks adds $10/week, pushing withholding to $22 -> $1/week
    # incremental * 52 weeks = $52 total withholding on the bonus.
    emp = _make_au_employee(db, organization.id)
    _stub_calc_inputs(monkeypatch, slabs=_AU_SCALE2_SLABS)

    result = service.calculate_au_employee_schedule5_withholding(
        db, organization.id, emp.id, Decimal("500"), Decimal("520"),
    )
    assert result["periods_per_year"] == 52
    assert result["averaged_amount"] == Decimal("10")
    assert result["withholding_without_payment"] == Decimal("21")
    assert result["withholding_with_averaged_payment"] == Decimal("22")
    assert result["total_withholding"] == Decimal("52")


def test_au_schedule5_zero_bonus_yields_zero_withholding(db, organization, monkeypatch):
    emp = _make_au_employee(db, organization.id)
    _stub_calc_inputs(monkeypatch, slabs=_AU_SCALE2_SLABS)

    result = service.calculate_au_employee_schedule5_withholding(
        db, organization.id, emp.id, Decimal("500"), Decimal("0"),
    )
    assert result["total_withholding"] == Decimal("0")


def test_au_schedule5_unconfigured_bands_yield_zero_not_a_guess(db, organization, monkeypatch):
    emp = _make_au_employee(db, organization.id)
    _stub_calc_inputs(monkeypatch, slabs=[])

    result = service.calculate_au_employee_schedule5_withholding(
        db, organization.id, emp.id, Decimal("500"), Decimal("520"),
    )
    assert result["withholding_without_payment"] == Decimal("0")
    assert result["withholding_with_averaged_payment"] == Decimal("0")
    assert result["total_withholding"] == Decimal("0")

"""
tests/test_ca_special_payment.py
-----------------------------------
Coverage for service.py's Canada non-periodic/special-payment calculators
(ZP-TAX-CA-2026-001 §19, gap-closure 2026-09-11) — standalone/on-demand
calculators, same architecture as calculate_india_employee_gratuity:
calculate_ca_special_payment_withholding (bonus/retroactive-pay/vacation-
not-taken/accumulated-overtime, CRA's real incremental-tax method),
calculate_ca_retiring_allowance_withholding (lump-sum rate-table lookup,
no hardcoded rate), and calculate_ca_td1x_commission_withholding (CRA's
real commission formula).

The rejection/not-found tests exercise the real DB path (they fail before
any rate resolution happens). The arithmetic tests monkeypatch
service._resolve_employee_calc_inputs directly with a hand-built
(rate_map, slabs, state_rate_map, state_slabs) tuple — deliberately NOT
going through the full get_tax_slabs/get_contribution_rates DB resolver,
which has its own separate test coverage (test_engine_standard.py's pure
calc()-level CA tests already exercise that arithmetic with hand-built
Slab/Rate objects the same way) — this file's job is to verify THIS
function's own orchestration (calling the annual-tax functions twice,
federal vs provincial vs Quebec routing, the before/after subtraction),
not to re-prove the resolver stack.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee
import app.modules.payroll.engine.countries.shared as shared


@dataclass
class Slab:
    """Minimal stand-in for a TaxSlab row — only the attributes
    _calculate_annual_tax reads (same shape as test_engine_standard.py's
    own local Slab dataclass)."""
    min_amount: Decimal = Decimal("0")
    max_amount: Optional[Decimal] = None
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"


def _make_ca_employee(db, org_id, code="C1", work_state="ON"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="CA", work_state=work_state, ctc=Decimal("60000"),
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


_FLAT_20_SLAB = [Slab(Decimal("0"), None, Decimal("20"))]
_FLAT_10_SLAB = [Slab(Decimal("0"), None, Decimal("10"))]
_FLAT_14_SLAB = [Slab(Decimal("0"), None, Decimal("14"))]


def _stub_calc_inputs(monkeypatch, *, work_state, state_slabs, state_rate_map=None, slabs=None):
    def _fake(db, organization_id, employee, cache=None, payroll_date=None, org_opted_in=False):
        return (
            "CA", {}, slabs if slabs is not None else _FLAT_20_SLAB, None, work_state, state_rate_map or {}, state_slabs,
            {}, {}, None, None, work_state,
        )
    monkeypatch.setattr(service, "_resolve_employee_calc_inputs", _fake)


def test_ca_special_payment_rejects_non_canada_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_special_payment_withholding(db, organization.id, emp.id, Decimal("60000"), Decimal("10000"))


def test_ca_special_payment_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_ca_special_payment_withholding(db, organization.id, 999999, Decimal("60000"), Decimal("10000"))


def test_ca_special_payment_rejects_negative_amounts(db, organization):
    emp = _make_ca_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_special_payment_withholding(db, organization.id, emp.id, Decimal("-1"), Decimal("10000"))
    with pytest.raises(BadRequestException):
        service.calculate_ca_special_payment_withholding(db, organization.id, emp.id, Decimal("60000"), Decimal("-1"))


def test_ca_special_payment_incremental_tax_matches_flat_marginal_rate(db, organization, monkeypatch):
    # Federal flat 20% (via _FLAT_20_SLAB baked into the stub), ON flat
    # 10% — both well under the federal BPAF threshold (16452, hardcoded
    # fallback since unconfigured) so it applies identically to both the
    # before/after annual figures. The incremental tax on a $10,000 bonus
    # must equal exactly $10,000 * 30% = $3,000, a clean sanity-checkable
    # property of a single flat bracket on both sides.
    emp = _make_ca_employee(db, organization.id, work_state="ON")
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=_FLAT_10_SLAB)

    result = service.calculate_ca_special_payment_withholding(
        db, organization.id, emp.id, Decimal("60000"), Decimal("10000"),
    )
    assert result["federal_withholding"] == Decimal("2000.00")
    assert result["provincial_withholding"] == Decimal("1000.00")
    assert result["total_withholding"] == Decimal("3000.00")
    assert result["is_quebec"] is False


def test_ca_special_payment_zero_bonus_yields_zero_withholding(db, organization, monkeypatch):
    emp = _make_ca_employee(db, organization.id, work_state="ON")
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=_FLAT_10_SLAB)

    result = service.calculate_ca_special_payment_withholding(
        db, organization.id, emp.id, Decimal("60000"), Decimal("0"),
    )
    assert result["total_withholding"] == Decimal("0.00")


def test_ca_special_payment_quebec_routes_through_quebec_module(db, organization, monkeypatch):
    # Quebec must NOT read the generic provincial bracket path at all —
    # its own dedicated module runs instead, same guard
    # test_canada_quebec_provincial_tax_ignores_generic_provincial_bpa_key
    # already proves at the engine-function level. state_rate_map here
    # deliberately has NO "quebec_bpa" key, so Quebec's own BPA resolves
    # to $0 (not the federal/provincial fallback) — same "no inference
    # across programs" contract _calculate_quebec_provincial_tax documents.
    emp = _make_ca_employee(db, organization.id, work_state="QC")
    _stub_calc_inputs(monkeypatch, work_state="QC", state_slabs=_FLAT_14_SLAB)

    result = service.calculate_ca_special_payment_withholding(
        db, organization.id, emp.id, Decimal("60000"), Decimal("10000"),
    )
    assert result["is_quebec"] is True
    assert result["federal_withholding"] == Decimal("2000.00")
    assert result["provincial_withholding"] == Decimal("1400.00")
    assert result["total_withholding"] == Decimal("3400.00")


def test_ca_special_payment_unconfigured_province_yields_zero_provincial_withholding(db, organization, monkeypatch):
    # _calculate_provincial_tax_ca's own contract: `if not state_slabs:
    # return Decimal("0")` — an employee whose province has no TaxSlab
    # rows configured at all must not silently error or guess.
    emp = _make_ca_employee(db, organization.id, work_state="AB")
    _stub_calc_inputs(monkeypatch, work_state="AB", state_slabs=[])

    result = service.calculate_ca_special_payment_withholding(
        db, organization.id, emp.id, Decimal("60000"), Decimal("10000"),
    )
    assert result["provincial_withholding"] == Decimal("0.00")
    assert result["federal_withholding"] == Decimal("2000.00")


# ── Retiring allowance / severance (rate-table lookup, no hardcoded rate) ─

_RETIRING_ALLOWANCE_BANDS = [
    Slab(Decimal("0"), Decimal("5000"), Decimal("10"), rule_type="CA_RETIRING_ALLOWANCE_BAND"),
    Slab(Decimal("5000"), Decimal("15000"), Decimal("20"), rule_type="CA_RETIRING_ALLOWANCE_BAND"),
    Slab(Decimal("15000"), None, Decimal("30"), rule_type="CA_RETIRING_ALLOWANCE_BAND"),
]


def test_ca_retiring_allowance_rejects_non_canada_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("10000"))


def test_ca_retiring_allowance_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_ca_retiring_allowance_withholding(db, organization.id, 999999, Decimal("10000"))


def test_ca_retiring_allowance_rejects_negative_amount(db, organization):
    emp = _make_ca_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("-1"))


def test_ca_retiring_allowance_unconfigured_bands_yield_zero_not_a_guess(db, organization, monkeypatch):
    # No CA_RETIRING_ALLOWANCE_BAND rows configured at all — must resolve
    # to 0%, never a guessed CRA rate (the source document names this
    # payment type but gives no actual percentage figures).
    emp = _make_ca_employee(db, organization.id)
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=[], slabs=_FLAT_20_SLAB)

    result = service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("10000"))
    assert result["configured"] is False
    assert result["rate_pct"] == Decimal("0")
    assert result["withholding"] == Decimal("0.00")


def test_ca_retiring_allowance_selects_correct_band(db, organization, monkeypatch):
    emp = _make_ca_employee(db, organization.id)
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=[], slabs=_FLAT_20_SLAB + _RETIRING_ALLOWANCE_BANDS)

    below = service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("3000"))
    assert below["rate_pct"] == Decimal("10")
    assert below["withholding"] == Decimal("300.00")

    middle = service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("10000"))
    assert middle["rate_pct"] == Decimal("20")
    assert middle["withholding"] == Decimal("2000.00")

    above = service.calculate_ca_retiring_allowance_withholding(db, organization.id, emp.id, Decimal("50000"))
    assert above["rate_pct"] == Decimal("30")
    assert above["withholding"] == Decimal("15000.00")


def test_ca_retiring_allowance_bands_do_not_contaminate_regular_bracket_calc():
    # The exact bug class this feature must NOT introduce: adding
    # CA_RETIRING_ALLOWANCE_BAND rows to the federal slabs list must not
    # get silently summed into a REGULAR _calculate_annual_tax bracket
    # calculation (same guard already in place for ON_EHT_BAND/PT_FLAT/etc).
    from app.modules.payroll.engine.countries.shared import _calculate_annual_tax

    slabs = _FLAT_20_SLAB + _RETIRING_ALLOWANCE_BANDS
    tax = _calculate_annual_tax(Decimal("60000"), slabs)
    assert tax == Decimal("12000.00")  # 60000 * 20%, NOT inflated by the band rows


# ── TD1X commission formula ───────────────────────────────────────────────

def test_ca_td1x_commission_rejects_non_canada_employee(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_td1x_commission_withholding(db, organization.id, emp.id)


def test_ca_td1x_commission_missing_employee_raises_not_found(db, organization):
    with pytest.raises(NotFoundException):
        service.calculate_ca_td1x_commission_withholding(db, organization.id, 999999)


def test_ca_td1x_commission_requires_election_on_file(db, organization):
    # No td1x_estimated_annual_commission set at all — must fail closed,
    # not silently fall back to some other figure.
    emp = _make_ca_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.calculate_ca_td1x_commission_withholding(db, organization.id, emp.id)


def test_ca_td1x_commission_nets_expenses_and_annualizes_correctly(db, organization, monkeypatch):
    # This test's expected figures are the legacy deduction-method math
    # (BPA subtracted from taxable before bracket-summing) - isolate from
    # the credit method (on by default since Phase 1 gap-closure).
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.discard("CA")
    emp = _make_ca_employee(db, organization.id, work_state="ON")
    emp.td1x_estimated_annual_commission = Decimal("100000")
    emp.td1x_estimated_annual_expenses = Decimal("20000")
    db.commit()
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=_FLAT_10_SLAB)

    result = service.calculate_ca_td1x_commission_withholding(db, organization.id, emp.id)
    # Net commission income = 100000 - 20000 = 80000. Federal: taxable =
    # max(0, 80000 - 16452 hardcoded BPAF fallback) = 63548 * 20% =
    # 12709.60, minus CEA credit (1501 * 14% = 210.14) = 12499.46.
    # Provincial (ON, no provincial_bpa configured): 80000 * 10% = 8000.00
    # (no BPA to subtract, unlike federal). Total 20499.46 / 12 = 1708.29.
    assert result["net_annual_commission_income"] == Decimal("80000")
    assert result["federal_annual_tax"] == Decimal("12499.46")
    assert result["provincial_annual_tax"] == Decimal("8000.00")
    assert result["total_annual_tax"] == Decimal("20499.46")
    assert result["pay_periods_per_year"] == 12
    assert result["per_period_withholding"] == Decimal("1708.29")
    assert result["is_quebec"] is False


def test_ca_td1x_commission_expenses_floor_at_zero_net_income(db, organization, monkeypatch):
    # Expenses exceeding the estimated commission must floor net income
    # at 0, never go negative.
    emp = _make_ca_employee(db, organization.id, work_state="ON")
    emp.td1x_estimated_annual_commission = Decimal("10000")
    emp.td1x_estimated_annual_expenses = Decimal("50000")
    db.commit()
    _stub_calc_inputs(monkeypatch, work_state="ON", state_slabs=_FLAT_10_SLAB)

    result = service.calculate_ca_td1x_commission_withholding(db, organization.id, emp.id)
    assert result["net_annual_commission_income"] == Decimal("0")
    assert result["per_period_withholding"] == Decimal("0.00")


def test_ca_td1x_commission_rejects_invalid_pay_periods(db, organization):
    emp = _make_ca_employee(db, organization.id)
    emp.td1x_estimated_annual_commission = Decimal("100000")
    db.commit()
    with pytest.raises(BadRequestException):
        service.calculate_ca_td1x_commission_withholding(db, organization.id, emp.id, pay_periods_per_year=0)

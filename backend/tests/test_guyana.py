"""
tests/test_guyana.py
-----------------------
Validates engine/countries/guyana.py against ZP-GY-ENG-001 §13 fixtures
F1/F2.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import guyana


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class Slab:
    min_amount: Decimal
    max_amount: Optional[Decimal]
    rate_pct: Decimal
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None
    filing_status: Optional[str] = None


def _gy_rate_map():
    return {
        "gy_personal_allowance": Rate(flat_amount=Decimal("140000")),
        "gy_nis": Rate(employee_rate_pct=Decimal("0.056"), employer_rate_pct=Decimal("0.084")),
        "gy_nis_ceiling_monthly": Rate(flat_amount=Decimal("280000")),
        "gy_nis_ceiling_weekly": Rate(flat_amount=Decimal("64615")),
    }


def _gy_slabs():
    return [
        Slab(min_amount=Decimal("0"), max_amount=Decimal("280000"), rate_pct=Decimal("25")),
        Slab(min_amount=Decimal("280000"), max_amount=None, rate_pct=Decimal("35")),
    ]


def _ctx(gross: Decimal, ytd_gy_paye_credit_before: Decimal = None) -> PayrollContext:
    return PayrollContext(
        gross=gross, basic=gross, country="GY", rate_map=_gy_rate_map(), slabs=_gy_slabs(), pay_frequency="Monthly",
        ytd_gy_paye_credit_before=ytd_gy_paye_credit_before,
    )


def test_dispatch_resolves_guyana_to_its_own_calculator():
    assert _COUNTRY_CALC["GY"] is guyana.calculate


def test_fixture_f1_ordinary_monthly_employee():
    result = guyana.calculate(_ctx(Decimal("200000")))
    assert result["social_security"] == Decimal("11200.00")
    assert result["employer_social_security"] == Decimal("16800.00")
    assert result["tds"] == Decimal("12200.00")


def test_fixture_f2_one_third_allowance_and_higher_band():
    result = guyana.calculate(_ctx(Decimal("600000")))
    assert result["social_security"] == Decimal("15680.00")       # capped at 280,000 x 5.6%
    assert result["employer_social_security"] == Decimal("23520.00")  # capped at 280,000 x 8.4%
    assert result["tds"] == Decimal("106512.00")


# ── GY-010 statutory credit ledger (ZP-GY-ENG-001 §13 Fixture F4) ──────────
# "Monthly gross 200,000... March 2026 current tax under approved rules =
# 12,200. Create 5,000 statutory credit; apply against March. Current tax
# liability remains 12,200; employee/GRA cash withholding for March =
# 7,200; credit remaining = 0."

def test_fixture_f4_credit_applied_against_march_liability():
    result = guyana.calculate(_ctx(Decimal("200000"), ytd_gy_paye_credit_before=Decimal("5000")))
    assert result["tds"] == Decimal("7200.00")  # 12,200 liability - 5,000 credit
    assert result["ytd_gy_paye_credit_after"] == Decimal("0.00")


def test_credit_larger_than_liability_only_partially_consumed():
    """A credit that exceeds this period's liability zeroes tds and
    carries the remainder forward, per GY-010's "carry remaining credit
    forward month by month until fully refunded" instruction."""
    result = guyana.calculate(_ctx(Decimal("200000"), ytd_gy_paye_credit_before=Decimal("20000")))
    assert result["tds"] == Decimal("0.00")
    assert result["ytd_gy_paye_credit_after"] == Decimal("7800.00")  # 20,000 - 12,200


def test_no_credit_wired_behaves_identically_to_before_this_feature():
    """None (every employee until a real opening balance is entered) must
    never guess a credit from incomplete data."""
    result = guyana.calculate(_ctx(Decimal("200000")))
    assert result["tds"] == Decimal("12200.00")
    assert result["ytd_gy_paye_credit_after"] is None


def test_zero_credit_before_behaves_identically_to_no_credit():
    """A wired-but-exhausted (0) balance must not be treated as
    "apply nothing changes" differently from unwired — both leave tds at
    the full liability."""
    result = guyana.calculate(_ctx(Decimal("200000"), ytd_gy_paye_credit_before=Decimal("0")))
    assert result["tds"] == Decimal("12200.00")
    assert result["ytd_gy_paye_credit_after"] is None

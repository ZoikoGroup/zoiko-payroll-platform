from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.ireland import (
    IrelandCalculationBlockedError,
    calculate,
    calculate_ax_credit,
    resolve_contribution_weeks,
    resolve_prsi_subclass,
)


class Rate:
    def __init__(self, flat_amount=None, employee_rate_pct=None, employer_rate_pct=None,
                 effective_from=None, effective_to=None, text_value=None):
        self.flat_amount = None if flat_amount is None else Decimal(str(flat_amount))
        self.employee_rate_pct = None if employee_rate_pct is None else Decimal(str(employee_rate_pct))
        self.employer_rate_pct = None if employer_rate_pct is None else Decimal(str(employer_rate_pct))
        self.effective_from = effective_from
        self.effective_to = effective_to
        self.text_value = text_value


def ie_pack(*, prsi_from_1_oct=False, period_overrides=None):
    ee_prsi = 4.35 if prsi_from_1_oct else 4.20
    er_low = 9.15 if prsi_from_1_oct else 9.00
    er_high = 11.40 if prsi_from_1_oct else 11.25
    rows = {
        "ie_tax_standard_pct": Rate(employee_rate_pct=20),
        "ie_tax_higher_pct": Rate(employee_rate_pct=40),
        "ie_usc_band1_limit": Rate(flat_amount=12012),
        "ie_usc_band1_pct": Rate(employee_rate_pct=0.5),
        "ie_usc_band2_limit": Rate(flat_amount=16688),
        "ie_usc_band2_pct": Rate(employee_rate_pct=2),
        "ie_usc_band3_limit": Rate(flat_amount=41344),
        "ie_usc_band3_pct": Rate(employee_rate_pct=3),
        "ie_usc_above_pct": Rate(employee_rate_pct=8),
        "ie_prsi_a0_ee_pct": Rate(employee_rate_pct=0),
        "ie_prsi_a0_er_pct": Rate(employer_rate_pct=9.00),
        "ie_prsi_ax_ee_pct": Rate(employee_rate_pct=ee_prsi),
        "ie_prsi_ax_er_pct": Rate(employer_rate_pct=er_low),
        "ie_prsi_al_ee_pct": Rate(employee_rate_pct=ee_prsi),
        "ie_prsi_al_er_pct": Rate(employer_rate_pct=er_low),
        "ie_prsi_a1_ee_pct": Rate(employee_rate_pct=ee_prsi),
        "ie_prsi_a1_er_pct": Rate(employer_rate_pct=er_high),
        "ie_prsi_band_a0_max": Rate(flat_amount=352),
        "ie_prsi_band_ax_max": Rate(flat_amount=424),
        "ie_prsi_band_al_max": Rate(flat_amount=552),
        "ie_prsi_ax_credit_max": Rate(flat_amount=12),
        "ie_prsi_ax_credit_lower": Rate(flat_amount=352.01),
        "ie_mff_ee_pct": Rate(employee_rate_pct=1.5),
        "ie_mff_er_pct": Rate(employer_rate_pct=1.5),
        "ie_mff_state_topup_pct": Rate(employee_rate_pct=0.5),
        "ie_mff_earnings_threshold": Rate(flat_amount=80000),
        "ie_lpt_exemption_threshold": Rate(flat_amount=54000),
        "ie_emergency_standard_cutoff_initial": Rate(flat_amount=633),
        "ie_emergency_weekly_cutoff_increment": Rate(flat_amount=52),
        "ie_emergency_weeks_per_increment": Rate(flat_amount=1),
        "ie_emergency_weekly_tax_credit": Rate(flat_amount=63.46),
        "ie_nmw_hourly_under_18": Rate(flat_amount=9.91),
        "ie_nmw_hourly_18": Rate(flat_amount=11.32),
        "ie_nmw_hourly_19": Rate(flat_amount=12.74),
        "ie_nmw_hourly_20_plus": Rate(flat_amount=14.15),
        "ie_sick_leave_days": Rate(flat_amount=5),
        "ie_sick_leave_pct": Rate(employee_rate_pct=70),
        "ie_sick_leave_daily_cap": Rate(flat_amount=110),
        "ie_sick_leave_service_weeks": Rate(flat_amount=13),
        "ie_reference_standard_band_single": Rate(flat_amount=44000),
        "ie_reference_credit_single": Rate(flat_amount=2000),
    }
    rows.update(period_overrides or {})
    return rows


def ie_context(employee=None, **overrides):
    ireland_employee = {
        "prsi_class": "A1",
        "usc_status": "Standard",
        "ppsn_supplied": True,
        "sector_wage_order": "NONE",
        "contracted_weekly_hours": Decimal("40"),
    }
    ireland_employee.update(employee or {})
    ctx = PayrollContext(
        country="IE",
        gross=Decimal("4000"),
        basic=Decimal("4000"),
        pay_frequency="Monthly",
        pay_date=date(2026, 9, 15),
        ireland_pay_date=date(2026, 9, 15),
        rate_map=ie_pack(),
        date_of_birth=date(1985, 5, 20),
        ireland_employee=ireland_employee,
        ireland_rpn={
            "snapshot_id": 1,
            "rpn_number": "RPN-2026-0001",
            "issued_at": "2026-01-05",
            "basis": "CUMULATIVE",
            "standard_rate_band": Decimal("44000"),
            "tax_credit": Decimal("4000"),
            "previous_taxable_pay_ytd": Decimal("0"),
            "previous_pay_ytd": Decimal("0"),
            "raw_hash": "abc123",
        },
        ireland_myfuturefund={"status": "ENROLLED", "effective_from": "2026-01-01"},
        ireland_ytd={},
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


def test_f1_monthly_single_employee():
    result = calculate(ie_context())
    assert result["ie_paye_basis"] == "CUMULATIVE"
    assert result["ie_standard_rate_pay"] == Decimal("3666.67")
    assert result["ie_higher_rate_pay"] == Decimal("333.33")
    assert result["ie_employee_prsi"] == Decimal("168.00")
    assert result["ie_employer_prsi"] == Decimal("450.00")
    assert result["ie_prsi_class"] == "A1"
    assert result["ie_mff_employee"] == Decimal("60.00")
    assert result["ie_mff_employer"] == Decimal("60.00")
    assert result["ie_mff_state_topup"] == Decimal("20.00")
    assert result["ie_lpt"] == Decimal("0.00")
    assert result["ie_paye"] == Decimal("533.33")


@pytest.mark.xfail(
    strict=False,
    reason="Open gate G1 content question. ZP-IE-ENG-001 F1 states PAYE 533.32 for a "
           "4000.00 single monthly pay on a 44000 standard band with a 4000 credit, but "
           "Revenue's documented method (20% of the per-period standard allocation, 40% of "
           "the excess, less the per-period credit) yields 533.33, and no per-period band "
           "value produces 533.32. The 1-cent gap is a rounding convention in the spec's "
           "worked example, not a formula difference. Do not close this by editing the "
           "engine; it needs the signed rounding-stage ruling (IE-009) from the tax "
           "specialist before 533.32 is asserted.",
)
def test_spec_f1_paye_figure_divergence_is_tracked():
    result = calculate(ie_context())
    assert result["ie_paye"] == Decimal("533.32")
    assert result["ie_paye"] == Decimal("533.33")


def test_usc_annualised_at_48000_reaches_spec_figure():
    annual_usc = (
        (Decimal("12012") * Decimal("0.005"))
        + (Decimal("16688") * Decimal("0.02"))
        + ((Decimal("48000") - Decimal("28700")) * Decimal("0.03"))
    )
    assert annual_usc == Decimal("972.82")

    ctx = ie_context()
    ytd_payable = Decimal("0")
    ytd_paid = Decimal("0")
    for _ in range(12):
        ctx.ireland_ytd = {"usc_payable_ytd": ytd_payable, "usc_paid_ytd": ytd_paid}
        result = calculate(ctx)
        ytd_payable += Decimal("4000")
        ytd_paid = result["ie_calculation_trace"]["usc"]["usc_paid_ytd_after"]
    assert ytd_payable == Decimal("48000")
    assert ytd_paid == Decimal("972.82")


@pytest.mark.xfail(
    strict=False,
    reason="Open gate G1 content question. The spec's F1 net figure of 3157.61 is built on "
           "an 'annualised USC / 12' approximation of 81.07 per month. A cumulative USC "
           "engine is required to assess a month-1 accumulator, so the correct month-1 "
           "figure is 20.00 (4000.00 at the 0.5% first band) and net is 3218.67. The spec "
           "figure is retained here only so the divergence stays visible.",
)
def test_spec_f1_net_pay_divergence_is_tracked():
    result = calculate(ie_context())
    net = (
        Decimal("4000")
        - result["ie_paye"]
        - result["ie_usc"]
        - result["ie_employee_prsi"]
        - result["ie_mff_employee"]
    )
    assert net == Decimal("3157.61")


@pytest.mark.parametrize(
    "pay_date,expected_employee,expected_employer",
    [
        (date(2026, 9, 30), Decimal("42.00"), Decimal("112.50")),
        (date(2026, 10, 1), Decimal("43.50"), Decimal("114.00")),
    ],
)
def test_f2_prsi_transition_boundary(pay_date, expected_employee, expected_employer):
    ctx = ie_context(
        gross=Decimal("1000"),
        basic=Decimal("1000"),
        pay_frequency="Weekly",
        pay_date=pay_date,
        ireland_pay_date=pay_date,
        rate_map=ie_pack(prsi_from_1_oct=pay_date >= date(2026, 10, 1)),
        ireland_employee={
            "prsi_class": "A1",
            "usc_status": "Standard",
            "ppsn_supplied": True,
            "sector_wage_order": "NONE",
            "contracted_weekly_hours": Decimal("40"),
        },
    )
    result = calculate(ctx)
    assert result["ie_employee_prsi"] == expected_employee
    assert result["ie_employer_prsi"] == expected_employer
    assert result["ie_prsi_contribution_weeks"] == Decimal("1")


def test_f3_no_rpn_ppsn_supplied_uses_emergency_basis():
    ctx = ie_context()
    ctx.ireland_rpn = {}
    ctx.ireland_employee = {
        "prsi_class": "A1",
        "usc_status": "Standard",
        "ppsn_supplied": True,
        "emergency_week": 1,
        "sector_wage_order": "NONE",
        "contracted_weekly_hours": Decimal("40"),
    }
    result = calculate(ctx)
    assert result["ie_paye_basis"] == "EMERGENCY"
    trace = result["ie_calculation_trace"]["paye"]
    assert trace["emergency_basis"] == "PPSN_SUPPLIED"
    assert result["ie_paye"] > 0


def test_f3_no_rpn_no_ppsn_is_higher_rate_with_no_credit():
    ctx = ie_context()
    ctx.ireland_rpn = {}
    ctx.ireland_employee = {
        "prsi_class": "A1",
        "usc_status": "Standard",
        "ppsn_supplied": False,
        "sector_wage_order": "NONE",
        "contracted_weekly_hours": Decimal("40"),
    }
    result = calculate(ctx)
    trace = result["ie_calculation_trace"]["paye"]
    assert trace["emergency_basis"] == "NO_PPSN_HIGHER_RATE"
    assert result["ie_tax_credit_applied"] == Decimal("0.00")
    assert result["ie_higher_rate_pay"] == Decimal("4000.00")


def test_f4_mff_threshold_payroll_exceeding_threshold_stays_contributable():
    ctx = ie_context(ireland_ytd={"mff_earnings_ytd_before": Decimal("78000")})
    result = calculate(ctx)
    assert result["ie_mff_contributory"] is True
    assert result["ie_mff_employee"] == Decimal("60.00")
    assert result["ie_mff_earnings_ytd_after"] == Decimal("82000")


def test_f4_mff_ceases_on_later_payroll_after_threshold():
    ctx = ie_context(ireland_ytd={"mff_earnings_ytd_before": Decimal("82000")})
    result = calculate(ctx)
    assert result["ie_mff_contributory"] is False
    assert result["ie_mff_employee"] == Decimal("0.00")
    assert result["ie_mff_ceased_reason"] == "EARNINGS_THRESHOLD_CEASED"


def test_unsupported_prsi_class_blocks():
    ctx = ie_context()
    ctx.ireland_employee = dict(ctx.ireland_employee, prsi_class="S")
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_PRSI_CLASS_UNSUPPORTED"


def test_missing_statutory_content_blocks_with_all_keys_named():
    ctx = ie_context()
    ctx.rate_map = dict(ctx.rate_map)
    for key in ("ie_usc_band1_limit", "ie_tax_standard_pct", "ie_mff_earnings_threshold"):
        del ctx.rate_map[key]
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_STATUTORY_CONTENT_NOT_CONFIGURED"
    message = excinfo.value.message
    for key in ("ie_usc_band1_limit", "ie_tax_standard_pct", "ie_mff_earnings_threshold"):
        assert key in message


def test_pay_date_selects_tax_year_not_earning_period():
    ctx = ie_context(
        pay_date=date(2026, 1, 5),
        ireland_pay_date=date(2026, 1, 5),
    )
    result = calculate(ctx)
    assert result["ie_tax_year"] == 2026
    assert result["ie_calculation_trace"]["tax_year"] == 2026


def test_missing_pay_date_blocks():
    ctx = ie_context()
    ctx.ireland_pay_date = None
    ctx.pay_date = None
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_PAY_DATE_MISSING"


def test_lpt_deducted_only_when_instructed_and_kept_separate():
    not_instructed = calculate(ie_context(gross=Decimal("6000"), basic=Decimal("6000")))
    assert not_instructed["ie_lpt_instructed"] is False
    assert not_instructed["ie_lpt"] == Decimal("0.00")

    ctx = ie_context(gross=Decimal("6000"), basic=Decimal("6000"))
    ctx.ireland_rpn = dict(ctx.ireland_rpn, lpt_instructed=True, lpt_rate_pct=8)
    result = calculate(ctx)
    assert result["ie_lpt_instructed"] is True
    lpt = result["ie_calculation_trace"]["lpt"]
    assert lpt["exemption"] == Decimal("4500.00")
    assert result["ie_lpt"] > 0


def test_lpt_instructed_without_rate_blocks():
    ctx = ie_context()
    ctx.ireland_rpn = dict(ctx.ireland_rpn, lpt_instructed=True)
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_LPT_RATE_MISSING"


def test_nmw_requires_working_hours_evidence():
    ctx = ie_context()
    ctx.ireland_employee = {k: v for k, v in ctx.ireland_employee.items() if k != "contracted_weekly_hours"}
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_NMW_HOURS_EVIDENCE_MISSING"


def test_nmw_breach_blocks():
    ctx = ie_context(gross=Decimal("1000"), basic=Decimal("1000"))
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_NMW_BREACH"


def test_sector_wage_order_blocks():
    ctx = ie_context()
    ctx.ireland_employee = dict(ctx.ireland_employee, sector_wage_order="ERO")
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_SECTOR_RATE_ORDER_UNCONFIGURED"


def test_week1_basis_requires_rpn_period_allocation():
    ctx = ie_context()
    ctx.ireland_rpn = dict(ctx.ireland_rpn, basis="WEEK_1")
    with pytest.raises(IrelandCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.code == "IE_WEEK1_RPN_ALLOCATION_MISSING"


def test_week1_basis_uses_rpn_period_allocation():
    ctx = ie_context()
    ctx.ireland_rpn = dict(
        ctx.ireland_rpn,
        basis="WEEK_1",
        standard_rate_band_period=Decimal("3666.67"),
        tax_credit_period=Decimal("333.33"),
    )
    result = calculate(ctx)
    assert result["ie_paye_basis"] == "WEEK_1"
    assert result["ie_paye"] == Decimal("533.34")


def test_usc_is_independent_of_paye_base():
    ctx = ie_context(
        ireland_paye_payable=Decimal("4000"),
        ireland_usc_payable=Decimal("0"),
    )
    result = calculate(ctx)
    assert result["ie_usc"] == Decimal("0.00")
    assert result["ie_paye"] == Decimal("533.33")


@pytest.mark.parametrize(
    "weekly,expected",
    [
        (Decimal("350.00"), "A0"),
        (Decimal("352.00"), "A0"),
        (Decimal("352.01"), "AX"),
        (Decimal("424.00"), "AX"),
        (Decimal("424.01"), "AL"),
        (Decimal("552.00"), "AL"),
        (Decimal("552.01"), "A1"),
    ],
)
def test_prsi_subclass_boundaries(weekly, expected):
    assert resolve_prsi_subclass(weekly, Decimal("352"), Decimal("424"), Decimal("552")) == expected


def test_ax_credit_is_tapered_and_capped():
    assert calculate_ax_credit(Decimal("424.00"), Decimal("352.01"), Decimal("424.00"), Decimal("12")) < Decimal("0.01")
    assert calculate_ax_credit(Decimal("352.01"), Decimal("352.01"), Decimal("424.00"), Decimal("12")) == Decimal("12.00")
    assert calculate_ax_credit(Decimal("100.00"), Decimal("352.01"), Decimal("424.00"), Decimal("12")) == Decimal("12.00")


def test_contribution_weeks_by_frequency():
    assert resolve_contribution_weeks("Weekly") == Decimal("1")
    assert resolve_contribution_weeks("Fortnightly") == Decimal("2")
    assert resolve_contribution_weeks("FourWeekly") == Decimal("4")
    assert resolve_contribution_weeks("Monthly") == Decimal("52") / Decimal("12")


def test_ax_credit_applies_to_ax_employee():
    ctx = ie_context(
        gross=Decimal("380"),
        basic=Decimal("380"),
        pay_frequency="Weekly",
        pay_date=date(2026, 9, 15),
        ireland_pay_date=date(2026, 9, 15),
        employee={"contracted_weekly_hours": Decimal("20")},
    )
    result = calculate(ctx)
    assert result["ie_prsi_class"] == "AX"
    assert result["ie_prsi_ax_credit"] > 0

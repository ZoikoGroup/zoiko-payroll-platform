from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    is_parameter_configured,
    resolve_jurisdiction_parameter,
    resolve_periods_per_year,
)

WEEKS_PER_YEAR = Decimal("52")
ZERO = Decimal("0")

PAYE_BASIS_CUMULATIVE = "CUMULATIVE"
PAYE_BASIS_WEEK_1 = "WEEK_1"
PAYE_BASIS_EMERGENCY = "EMERGENCY"
PAYE_BASES = (PAYE_BASIS_CUMULATIVE, PAYE_BASIS_WEEK_1, PAYE_BASIS_EMERGENCY)

PRSI_LAUNCH_SUBCLASSES = ("A0", "AX", "AL", "A1")
MFF_CONTRIBUTORY_STATUSES = ("ENROLLED",)
NMW_BAND_KEYS = {
    "UNDER_18": "ie_nmw_hourly_under_18",
    "18": "ie_nmw_hourly_18",
    "19": "ie_nmw_hourly_19",
    "20_PLUS": "ie_nmw_hourly_20_plus",
}

IE_PARAMETER_KEYS = {
    "ie_tax_standard_pct": "employee_pct",
    "ie_tax_higher_pct": "employee_pct",
    "ie_usc_band1_limit": "amount",
    "ie_usc_band1_pct": "employee_pct",
    "ie_usc_band2_limit": "amount",
    "ie_usc_band2_pct": "employee_pct",
    "ie_usc_band3_limit": "amount",
    "ie_usc_band3_pct": "employee_pct",
    "ie_usc_above_pct": "employee_pct",
    "ie_prsi_a0_ee_pct": "employee_pct",
    "ie_prsi_a0_er_pct": "employer_pct",
    "ie_prsi_ax_ee_pct": "employee_pct",
    "ie_prsi_ax_er_pct": "employer_pct",
    "ie_prsi_al_ee_pct": "employee_pct",
    "ie_prsi_al_er_pct": "employer_pct",
    "ie_prsi_a1_ee_pct": "employee_pct",
    "ie_prsi_a1_er_pct": "employer_pct",
    "ie_prsi_band_a0_max": "amount",
    "ie_prsi_band_ax_max": "amount",
    "ie_prsi_band_al_max": "amount",
    "ie_prsi_ax_credit_max": "amount",
    "ie_prsi_ax_credit_lower": "amount",
    "ie_mff_ee_pct": "employee_pct",
    "ie_mff_er_pct": "employer_pct",
    "ie_mff_state_topup_pct": "employee_pct",
    "ie_mff_earnings_threshold": "amount",
    "ie_lpt_exemption_threshold": "amount",
    "ie_emergency_standard_cutoff_initial": "amount",
    "ie_emergency_weekly_cutoff_increment": "amount",
    "ie_emergency_weeks_per_increment": "amount",
    "ie_emergency_weekly_tax_credit": "amount",
    "ie_nmw_hourly_under_18": "amount",
    "ie_nmw_hourly_18": "amount",
    "ie_nmw_hourly_19": "amount",
    "ie_nmw_hourly_20_plus": "amount",
    "ie_sick_leave_days": "amount",
    "ie_sick_leave_pct": "employee_pct",
    "ie_sick_leave_daily_cap": "amount",
    "ie_sick_leave_service_weeks": "amount",
    "ie_reference_standard_band_single": "amount",
    "ie_reference_credit_single": "amount",
}


class IrelandCalculationBlockedError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ireland_tax_year(pay_date: date) -> int:
    return int(pay_date.year)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def resolve_contribution_weeks(pay_frequency: str | None) -> Decimal:
    periods = resolve_periods_per_year(pay_frequency)
    if periods <= ZERO:
        return Decimal("1")
    return WEEKS_PER_YEAR / periods


def _age_at(date_of_birth, on_date: date):
    if not date_of_birth or not on_date:
        return None
    return on_date.year - date_of_birth.year - (
        (on_date.month, on_date.day) < (date_of_birth.month, date_of_birth.day)
    )


def resolve_nmw_band_key(age) -> str:
    if age is None:
        return "20_PLUS"
    if age < 18:
        return "UNDER_18"
    if age == 18:
        return "18"
    if age == 19:
        return "19"
    return "20_PLUS"


class _Pack:
    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id
        self.missing: list = []

    def amount(self, key: str) -> Decimal:
        if not is_parameter_configured(self.rate_map, key):
            self.missing.append(key)
            return ZERO
        return Decimal(str(resolve_jurisdiction_parameter(
            self.rate_map, key, ZERO, country="IE",
            organization_id=self.organization_id,
        )))

    def employee_pct(self, key: str) -> Decimal:
        return self._side_pct(key, "employee")

    def employer_pct(self, key: str) -> Decimal:
        return self._side_pct(key, "employer")

    def _side_pct(self, key: str, side: str) -> Decimal:
        if not is_parameter_configured(self.rate_map, key, side):
            self.missing.append(key)
            return ZERO
        return Decimal(str(resolve_jurisdiction_parameter(
            self.rate_map, key, ZERO, side=side, country="IE",
            organization_id=self.organization_id,
        ))) / Decimal("100")

    def row(self, key: str):
        return self.rate_map.get(key)

    def assert_complete(self) -> None:
        if self.missing:
            unique = sorted(set(self.missing))
            raise IrelandCalculationBlockedError(
                "IE_STATUTORY_CONTENT_NOT_CONFIGURED",
                "Ireland payroll block: mandatory 2026 statutory content has no configured "
                "value in the active Ireland pack for this pay date (ZP-IE-ENG-001 IE-003): "
                + ", ".join(unique)
                + ". Configure these component keys under Super Admin > Compliance > Ireland, "
                "or run the Ireland canonical pack seed. The engine never substitutes a "
                "hardcoded fallback for missing signed content.",
            )


def _resolve_pay_date(ctx: PayrollContext) -> date:
    pay_date = ctx.ireland_pay_date or ctx.pay_date
    if not pay_date:
        raise IrelandCalculationBlockedError(
            "IE_PAY_DATE_MISSING",
            "Ireland payroll requires a pay date: IE-006 selects the Irish tax year and the "
            "PRSI rate set by pay date, never by earning period.",
        )
    return pay_date


def _annual_paye(
    taxable: Decimal,
    standard_band: Decimal,
    tax_credit: Decimal,
    standard_rate: Decimal,
    higher_rate: Decimal,
) -> Decimal:
    at_standard = min(max(taxable, ZERO), max(standard_band, ZERO))
    at_higher = max(ZERO, taxable - max(standard_band, ZERO))
    gross_tax = (at_standard * standard_rate) + (at_higher * higher_rate)
    return max(ZERO, gross_tax - max(tax_credit, ZERO))


def _resolve_paye_basis(rpn: dict) -> str:
    basis = (rpn or {}).get("basis") or (rpn or {}).get("calculation_basis")
    if basis:
        normalized = str(basis).strip().upper().replace(" ", "_").replace("-", "_")
        if normalized in PAYE_BASES:
            return normalized
        raise IrelandCalculationBlockedError(
            "IE_PAYE_BASIS_UNSUPPORTED",
            f"Ireland payroll block: Revenue supplied an unrecognised PAYE calculation "
            f"basis {basis!r}. Supported bases are {list(PAYE_BASES)}.",
        )
    if not rpn:
        return PAYE_BASIS_EMERGENCY
    raise IrelandCalculationBlockedError(
        "IE_PAYE_BASIS_MISSING",
        "Ireland payroll block: the frozen RPN snapshot carries no calculation basis. "
        "IE-005 requires the current Revenue instruction; the engine never infers a basis.",
    )


def _period_allocation(rpn, ctx, annual_band_key="standard_rate_band", credit_key="tax_credit"):
    """Revenue's own published method divides the RPN's ANNUAL standard-rate
    allocation and annual tax credit by the number of pay periods in the year
    to get the per-period figures the employee is actually assessed on. Doing
    it any other way (applying the annual band/credit to one period directly)
    both over-credits a first payment and mis-splits the 40% excess, so this
    conversion is the statutory mechanic, not a convenience.

    Returns (period_band, period_credit, annual_band, annual_credit). An RPN
    that already carries explicit per-period values wins — the authority
    figure is never recomputed away."""
    periods = resolve_periods_per_year(ctx.pay_frequency)
    annual_band = _dec(rpn.get(annual_band_key))
    annual_credit = _dec(rpn.get(credit_key))
    period_band = rpn.get("standard_rate_band_period")
    period_credit = rpn.get("tax_credit_period")
    band = _dec(period_band) if period_band is not None else (annual_band / periods)
    credit = _dec(period_credit) if period_credit is not None else (annual_credit / periods)
    return band, credit, annual_band, annual_credit


def _periods_elapsed(rpn, ctx) -> Decimal:
    """Number of pay periods already including this one in the current tax
    year for this employment. Authority-supplied on the RPN; a first payment
    with no counter is period 1."""
    elapsed = rpn.get("periods_elapsed")
    if elapsed is None:
        previous_taxable = _dec(rpn.get("previous_taxable_pay_ytd"))
        if previous_taxable > ZERO:
            raise IrelandCalculationBlockedError(
                "IE_PERIODS_ELAPSED_MISSING",
                "Ireland payroll block: this employment already has prior PAYE in the tax year "
                "but the frozen RPN snapshot carries no periods_elapsed counter, so the "
                "cumulative credit position cannot be derived. IE-005 requires the current "
                "Revenue instruction to be the source of the cumulative state.",
            )
        return Decimal("1")
    elapsed = _dec(elapsed)
    if elapsed < 1:
        raise IrelandCalculationBlockedError(
            "IE_PERIODS_ELAPSED_INVALID",
            f"Ireland payroll block: periods_elapsed must be at least 1 (got {elapsed}).",
        )
    return elapsed


def _calculate_paye_cumulative(rpn, ctx, pack, period_taxable, standard_rate, higher_rate) -> dict:
    period_band, period_credit, annual_band, annual_credit = _period_allocation(rpn, ctx)
    elapsed = _periods_elapsed(rpn, ctx)
    previous_taxable = _dec(rpn.get("previous_taxable_pay_ytd"))
    previous_tax = _dec(rpn.get("previous_pay_ytd"))
    cumulative_taxable = previous_taxable + period_taxable
    tax_to_date = _annual_paye(
        cumulative_taxable,
        period_band * elapsed,
        period_credit * elapsed,
        standard_rate,
        higher_rate,
    )
    period_tax = max(ZERO, tax_to_date - previous_tax)
    period_standard_pay = min(max(period_taxable, ZERO), period_band)
    return {
        "paye": period_tax,
        "taxable_pay": period_taxable,
        "standard_band_pay": max(ZERO, period_standard_pay),
        "higher_rate_pay": max(ZERO, period_taxable - period_standard_pay),
        "gross_tax": tax_to_date + (period_credit * elapsed),
        "tax_credit_applied": period_credit * elapsed,
        "standard_band": annual_band,
        "period_standard_band": period_band,
        "period_tax_credit": period_credit,
        "periods_elapsed": elapsed,
        "previous_taxable_pay_ytd": previous_taxable,
        "previous_pay_ytd": previous_tax,
        "taxable_pay_ytd_after": cumulative_taxable,
        "paye_ytd_after": tax_to_date,
    }


def _calculate_paye_week_1(rpn, ctx, pack, period_taxable, standard_rate, higher_rate) -> dict:
    period_band = rpn.get("standard_rate_band_period")
    period_credit = rpn.get("tax_credit_period")
    if period_band is None or period_credit is None:
        raise IrelandCalculationBlockedError(
            "IE_WEEK1_RPN_ALLOCATION_MISSING",
            "Ireland payroll block: Week 1 basis requires the Revenue-issued per-period "
            "standard-rate allocation and tax credit on the RPN snapshot "
            "(standard_rate_band_period / tax_credit_period). IE-004 forbids deriving the "
            "employee's Week 1 entitlement from generic annual values.",
        )
    period_band = _dec(period_band)
    period_credit = _dec(period_credit)
    period_tax = _annual_paye(
        period_taxable, period_band, period_credit, standard_rate, higher_rate,
    )
    period_standard_pay = min(max(period_taxable, ZERO), period_band)
    return {
        "paye": period_tax,
        "taxable_pay": period_taxable,
        "standard_band_pay": period_standard_pay,
        "higher_rate_pay": max(ZERO, period_taxable - period_standard_pay),
        "gross_tax": period_tax + period_credit,
        "tax_credit_applied": period_credit,
        "standard_band": period_band,
        "period_standard_band": period_band,
        "period_tax_credit": period_credit,
        "periods_elapsed": Decimal("1"),
        "taxable_pay_ytd_after": None,
        "paye_ytd_after": None,
    }


def _calculate_paye_emergency(rpn, ctx, pack, period_taxable, standard_rate, higher_rate) -> dict:
    weeks = resolve_contribution_weeks(ctx.pay_frequency)
    weekly_taxable = period_taxable / weeks
    has_ppsn = _truthy((ctx.ireland_employee or {}).get("ppsn_supplied"))
    if not has_ppsn:
        period_tax = weekly_taxable * higher_rate * weeks
        return {
            "paye": period_tax,
            "taxable_pay": period_taxable,
            "standard_band_pay": ZERO,
            "higher_rate_pay": period_taxable,
            "gross_tax": period_tax,
            "tax_credit_applied": ZERO,
            "standard_band": ZERO,
            "taxable_pay_ytd_after": None,
            "paye_ytd_after": None,
            "emergency_basis": "NO_PPSN_HIGHER_RATE",
        }
    emergency_week = int(_dec((ctx.ireland_employee or {}).get("emergency_week")) or ZERO)
    if emergency_week < 1:
        raise IrelandCalculationBlockedError(
            "IE_EMERGENCY_WEEK_MISSING",
            "Ireland payroll block: a PPSN-supplied employee with no Revenue RPN is on the "
            "Emergency basis, which requires the emergency week counter from preflight. "
            "IE-008/IE-031 forbid silently applying emergency tax without a reason and counter.",
        )
    weekly_credit = pack.amount("ie_emergency_weekly_tax_credit")
    initial = pack.amount("ie_emergency_standard_cutoff_initial")
    increment = pack.amount("ie_emergency_weekly_cutoff_increment")
    weeks_per_increment = pack.amount("ie_emergency_weeks_per_increment")
    if weeks_per_increment <= ZERO:
        raise IrelandCalculationBlockedError(
            "IE_EMERGENCY_INCREMENT_INVALID",
            "Ireland payroll block: ie_emergency_weks_per_increment must be greater than zero "
            "in the active Ireland pack.",
        )
    increments = Decimal(emergency_week - 1) / weeks_per_increment
    weekly_cutoff = initial + (increments * increment)
    weekly_tax = _annual_paye(
        weekly_taxable, weekly_cutoff, _dec(weekly_credit), standard_rate, higher_rate,
    )
    standard_rate_pay = min(max(weekly_taxable, ZERO), weekly_cutoff) * weeks
    return {
        "paye": weekly_tax * weeks,
        "taxable_pay": period_taxable,
        "standard_band_pay": standard_rate_pay,
        "higher_rate_pay": max(ZERO, period_taxable - standard_rate_pay),
        "gross_tax": weekly_tax * weeks + _dec(weekly_credit) * weeks,
        "tax_credit_applied": _dec(weekly_credit) * weeks,
        "standard_band": weekly_cutoff,
        "taxable_pay_ytd_after": None,
        "paye_ytd_after": None,
        "emergency_basis": "PPSN_SUPPLIED",
        "emergency_week": emergency_week,
        "weekly_standard_cutoff": weekly_cutoff,
    }


def calculate_paye(rpn, ctx, pack, period_taxable, standard_rate, higher_rate) -> dict:
    basis = _resolve_paye_basis(rpn)
    if basis == PAYE_BASIS_CUMULATIVE:
        result = _calculate_paye_cumulative(rpn, ctx, pack, period_taxable, standard_rate, higher_rate)
    elif basis == PAYE_BASIS_WEEK_1:
        result = _calculate_paye_week_1(rpn, ctx, pack, period_taxable, standard_rate, higher_rate)
    else:
        result = _calculate_paye_emergency(rpn, ctx, pack, period_taxable, standard_rate, higher_rate)
    result["basis"] = basis
    return result


def _usc_annual(payable, band1, band2, band3, rate1, rate2, rate3, rate_above) -> Decimal:
    limit1 = max(band1, ZERO)
    limit2 = limit1 + max(band2, ZERO)
    limit3 = limit2 + max(band3, ZERO)
    at_1 = min(max(payable, ZERO), limit1)
    at_2 = min(max(payable - limit1, ZERO), max(band2, ZERO))
    at_3 = min(max(payable - limit2, ZERO), max(band3, ZERO))
    at_above = max(ZERO, payable - limit3)
    return (at_1 * rate1) + (at_2 * rate2) + (at_3 * rate3) + (at_above * rate_above)


def calculate_usc(rpn, ctx, pack, period_usc_payable) -> dict:
    band1 = pack.amount("ie_usc_band1_limit")
    band2 = pack.amount("ie_usc_band2_limit")
    band3 = pack.amount("ie_usc_band3_limit")
    rate1 = pack.employee_pct("ie_usc_band1_pct")
    rate2 = pack.employee_pct("ie_usc_band2_pct")
    rate3 = pack.employee_pct("ie_usc_band3_pct")
    rate_above = pack.employee_pct("ie_usc_above_pct")
    paye_basis = _resolve_paye_basis(rpn)
    if paye_basis == PAYE_BASIS_WEEK_1:
        periods = resolve_periods_per_year(ctx.pay_frequency)
        band1 = band1 / periods
        band2 = band2 / periods
        band3 = band3 / periods
        period_usc = _usc_annual(period_usc_payable, band1, band2, band3, rate1, rate2, rate3, rate_above)
        return {
            "usc": period_usc, "basis": PAYE_BASIS_WEEK_1,
            "usc_payable_ytd_after": None, "usc_paid_ytd_after": None,
        }
    ytd = ctx.ireland_ytd or {}
    ytd_before = _dec(ytd.get("usc_payable_ytd"))
    ytd_paid_before = _dec(ytd.get("usc_paid_ytd"))
    if ctx.ireland_usc_paid_ytd is not None:
        ytd_paid_before = _dec(ctx.ireland_usc_paid_ytd)
    annual = _usc_annual(ytd_before + period_usc_payable, band1, band2, band3, rate1, rate2, rate3, rate_above)
    period_usc = max(ZERO, annual - ytd_paid_before)
    return {
        "usc": period_usc, "basis": PAYE_BASIS_CUMULATIVE,
        "usc_payable_ytd_after": ytd_before + period_usc_payable,
        "usc_paid_ytd_after": ytd_paid_before + period_usc,
    }


def resolve_prsi_subclass(weekly_reckonable, band_a0_max, band_ax_max, band_al_max) -> str:
    if weekly_reckonable <= max(band_a0_max, ZERO):
        return "A0"
    if weekly_reckonable <= max(band_ax_max, ZERO):
        return "AX"
    if weekly_reckonable <= max(band_al_max, ZERO):
        return "AL"
    return "A1"


def calculate_ax_credit(weekly_reckonable, lower, upper, credit_max) -> Decimal:
    span = max(upper, ZERO) - max(lower, ZERO)
    if span <= ZERO:
        return ZERO
    taper = (max(upper, ZERO) - max(weekly_reckonable, ZERO)) / span
    return min(max(taper, ZERO), Decimal("1")) * max(credit_max, ZERO)


def calculate_prsi(ctx, pack, period_reckonable) -> dict:
    subclass = (ctx.ireland_employee or {}).get("prsi_class")
    if not subclass:
        raise IrelandCalculationBlockedError(
            "IE_PRSI_CLASS_MISSING",
            "Ireland payroll block: no PRSI class/subclass result for this employee. IE-016 "
            "makes the class an eligibility result, not a free-form admin field, so it must be "
            "resolved by preflight before the run proceeds.",
        )
    subclass = str(subclass).strip().upper()
    if subclass not in PRSI_LAUNCH_SUBCLASSES:
        raise IrelandCalculationBlockedError(
            "IE_PRSI_CLASS_UNSUPPORTED",
            f"Ireland payroll block: PRSI class {subclass!r} is outside the certified launch "
            f"cohort {list(PRSI_LAUNCH_SUBCLASSES)} (ZP-IE-ENG-001 §1 defers every non-Class-A "
            "specialist class until separately certified).",
        )
    band_a0 = pack.amount("ie_prsi_band_a0_max")
    band_ax = pack.amount("ie_prsi_band_ax_max")
    band_al = pack.amount("ie_prsi_band_al_max")
    weeks = resolve_contribution_weeks(ctx.pay_frequency)
    weekly_reckonable = period_reckonable / weeks
    resolved_subclass = resolve_prsi_subclass(weekly_reckonable, band_a0, band_ax, band_al)
    employee_pct = pack.employee_pct(f"ie_prsi_{resolved_subclass.lower()}_ee_pct")
    employer_pct = pack.employer_pct(f"ie_prsi_{resolved_subclass.lower()}_er_pct")
    credit = ZERO
    if resolved_subclass == "AX":
        credit_lower = pack.amount("ie_prsi_ax_credit_lower")
        credit_max = pack.amount("ie_prsi_ax_credit_max")
        credit = calculate_ax_credit(weekly_reckonable, credit_lower, band_ax, credit_max) * weeks
    employee_prsi = max(ZERO, (period_reckonable * employee_pct) - credit)
    employer_prsi = period_reckonable * employer_pct
    return {
        "employee_prsi": employee_prsi,
        "employer_prsi": employer_prsi,
        "subclass": resolved_subclass,
        "declared_subclass": subclass,
        "employee_pct": employee_pct,
        "employer_pct": employer_pct,
        "ax_credit": credit,
        "contribution_weeks": weeks,
        "weekly_reckonable": weekly_reckonable,
        "reckonable_ytd_after": _dec((ctx.ireland_ytd or {}).get("prsi_reckonable_ytd")) + period_reckonable,
    }


def calculate_myfuturefund(ctx, pack, period_base, gross) -> dict:
    status_input = (ctx.ireland_myfuturefund or {}).get("status")
    status = str(status_input).strip().upper() if status_input else None
    threshold = pack.amount("ie_mff_earnings_threshold")
    employee_pct = pack.employee_pct("ie_mff_ee_pct")
    employer_pct = pack.employer_pct("ie_mff_er_pct")
    state_topup_pct = pack.employee_pct("ie_mff_state_topup_pct")
    ytd_before = _dec((ctx.ireland_ytd or {}).get("mff_earnings_ytd_before"))
    if not status:
        raise IrelandCalculationBlockedError(
            "IE_MFF_STATUS_MISSING",
            "Ireland payroll block: no NAERSA MyFutureFund authority status for this employee. "
            "IE-018 makes enrolment an authority-status-driven deduction; the engine never "
            "infers eligibility or falls back to a local default.",
        )
    if status not in MFF_CONTRIBUTORY_STATUSES:
        return {
            "status": status, "contributory": False,
            "employee": ZERO, "employer": ZERO, "state_topup": ZERO,
            "employee_pct": employee_pct, "employer_pct": employer_pct,
            "state_topup_pct": state_topup_pct,
            "threshold": threshold, "earnings_ytd_before": ytd_before,
            "earnings_ytd_after": ytd_before + period_base,
            "ceased_reason": status,
        }
    if ytd_before >= threshold:
        return {
            "status": status, "contributory": False,
            "employee": ZERO, "employer": ZERO, "state_topup": ZERO,
            "employee_pct": employee_pct, "employer_pct": employer_pct,
            "state_topup_pct": state_topup_pct,
            "threshold": threshold, "earnings_ytd_before": ytd_before,
            "earnings_ytd_after": ytd_before + period_base,
            "ceased_reason": "EARNINGS_THRESHOLD_CEASED",
        }
    return {
        "status": status, "contributory": True,
        "employee": period_base * employee_pct,
        "employer": period_base * employer_pct,
        "state_topup": period_base * state_topup_pct,
        "employee_pct": employee_pct, "employer_pct": employer_pct,
        "state_topup_pct": state_topup_pct,
        "threshold": threshold, "earnings_ytd_before": ytd_before,
        "earnings_ytd_after": ytd_before + period_base,
    }


def calculate_lpt(rpn, ctx, pack, paye_result) -> dict:
    instructed = _truthy((rpn or {}).get("lpt_instructed")) or bool((rpn or {}).get("lpt_rate_pct"))
    if not instructed:
        return {"lpt": ZERO, "instructed": False, "rate_pct": None, "base": ZERO}
    rate_pct = (rpn or {}).get("lpt_rate_pct")
    if rate_pct is None:
        raise IrelandCalculationBlockedError(
            "IE_LPT_RATE_MISSING",
            "Ireland payroll block: the RPN instructs Local Property Tax but carries no "
            "lpt_rate_pct. IE-003 requires the signed LPT rate; the engine never invents one.",
        )
    rate = Decimal(str(rate_pct)) / Decimal("100")
    base = max(ZERO, paye_result["taxable_pay"] - paye_result["tax_credit_applied"])
    exemption = pack.amount("ie_lpt_exemption_threshold")
    periods = resolve_periods_per_year(ctx.pay_frequency)
    period_exemption = exemption / periods
    taxable = max(ZERO, base - period_exemption)
    return {
        "lpt": taxable * rate, "instructed": True,
        "rate_pct": rate, "base": base, "exemption": period_exemption,
    }


def assert_labour_compliance(ctx, pack, pay_date, gross_payable) -> dict:
    employee = ctx.ireland_employee or {}
    age = _age_at(ctx.date_of_birth, pay_date)
    band_key = resolve_nmw_band_key(age)
    nmw_rate = pack.amount(NMW_BAND_KEYS[band_key])
    sector_order = str(employee.get("sector_wage_order") or "NONE").strip().upper()
    if sector_order in ("ERO", "SEO"):
        raise IrelandCalculationBlockedError(
            "IE_SECTOR_RATE_ORDER_UNCONFIGURED",
            f"Ireland payroll block: this employment is flagged as subject to a {sector_order} "
            "sector wage order and no certified sector rate is configured. ZP-IE-ENG-001 §11 "
            "gates sectoral rates explicitly rather than applying the national minimum wage.",
        )
    weekly_hours = employee.get("contracted_weekly_hours")
    if weekly_hours is None:
        raise IrelandCalculationBlockedError(
            "IE_NMW_HOURS_EVIDENCE_MISSING",
            "Ireland payroll block: the national minimum wage check requires working-hours "
            "evidence (contracted_weekly_hours). IE-035 forbids deriving it from a salary "
            "divided by a generic 40-hour week.",
        )
    weekly_hours = _dec(weekly_hours)
    weeks = resolve_contribution_weeks(ctx.pay_frequency)
    hours_in_payment = weekly_hours * weeks
    if hours_in_payment <= ZERO:
        raise IrelandCalculationBlockedError(
            "IE_NMW_HOURS_EVIDENCE_INVALID",
            "Ireland payroll block: contracted_weekly_hours must be greater than zero.",
        )
    effective_hourly = gross_payable / hours_in_payment
    if effective_hourly < nmw_rate:
        raise IrelandCalculationBlockedError(
            "IE_NMW_BREACH",
            f"Ireland payroll block: effective hourly pay EUR {effective_hourly.quantize(Decimal('0.01'))} "
            f"is below the 2026 {band_key} national minimum wage EUR {nmw_rate.quantize(Decimal('0.01'))} "
            f"for {hours_in_payment.quantize(Decimal('0.01'))} contracted hours in this payment.",
        )
    sick_days = pack.amount("ie_sick_leave_days")
    sick_pct = pack.employee_pct("ie_sick_leave_pct")
    sick_cap = pack.amount("ie_sick_leave_daily_cap")
    sick_service = pack.amount("ie_sick_leave_service_weeks")
    return {
        "age": age, "nmw_band": band_key, "nmw_hourly": nmw_rate,
        "contracted_weekly_hours": weekly_hours,
        "hours_in_payment": hours_in_payment, "effective_hourly": effective_hourly,
        "nmw_breach": False, "sector_wage_order": sector_order,
        "sick_leave_days": sick_days, "sick_leave_pct": sick_pct,
        "sick_leave_daily_cap": sick_cap, "sick_leave_service_weeks": sick_service,
    }


def _pension_amounts(employee: dict) -> tuple:
    employee_pension = _dec(employee.get("pension_employee_amount"))
    employer_pension = _dec(employee.get("pension_employer_amount"))
    employee_pct = _dec(employee.get("pension_employee_pct"))
    employer_pct = _dec(employee.get("pension_employer_pct"))
    if employee_pct:
        employee_pension += _dec(employee.get("pensionable_pay")) * employee_pct / Decimal("100")
    if employer_pct:
        employer_pension += _dec(employee.get("pensionable_pay")) * employer_pct / Decimal("100")
    return max(ZERO, employee_pension), max(ZERO, employer_pension)


def calculate(ctx: PayrollContext) -> dict:
    pay_date = _resolve_pay_date(ctx)
    pack = _Pack(ctx.rate_map, getattr(ctx, "ireland_organization_id", None))
    employee = ctx.ireland_employee or {}
    rpn = ctx.ireland_rpn or {}
    gross = ctx.gross or ZERO

    paye_payable = ctx.ireland_paye_payable if ctx.ireland_paye_payable is not None else gross
    usc_payable = ctx.ireland_usc_payable if ctx.ireland_usc_payable is not None else gross
    prsi_reckonable = ctx.ireland_prsi_reckonable if ctx.ireland_prsi_reckonable is not None else gross
    mff_base = ctx.ireland_mff_base if ctx.ireland_mff_base is not None else gross

    standard_rate = pack.employee_pct("ie_tax_standard_pct")
    higher_rate = pack.employee_pct("ie_tax_higher_pct")
    paye = calculate_paye(rpn, ctx, pack, paye_payable, standard_rate, higher_rate)
    usc = calculate_usc(rpn, ctx, pack, usc_payable)
    prsi = calculate_prsi(ctx, pack, prsi_reckonable)
    mff = calculate_myfuturefund(ctx, pack, mff_base, gross)
    lpt = calculate_lpt(rpn, ctx, pack, paye)
    labour = assert_labour_compliance(ctx, pack, pay_date, paye_payable)
    pack.assert_complete()

    employee_pension, employer_pension = _pension_amounts(employee)
    paye_rounded = _round2(paye["paye"])
    usc_rounded = _round2(usc["usc"])
    prsi_ee_rounded = _round2(prsi["employee_prsi"])
    prsi_er_rounded = _round2(prsi["employer_prsi"])
    mff_ee_rounded = _round2(mff["employee"])
    mff_er_rounded = _round2(mff["employer"])
    lpt_rounded = _round2(lpt["lpt"])
    employee_total = usc_rounded + prsi_ee_rounded + mff_ee_rounded + lpt_rounded

    trace = {
        "country": "IE",
        "tax_year": ireland_tax_year(pay_date),
        "pay_date": pay_date.isoformat(),
        "pay_frequency": ctx.pay_frequency,
        "rpn_number": rpn.get("rpn_number"),
        "rpn_issued_at": rpn.get("issued_at"),
        "rpn_hash": rpn.get("raw_hash"),
        "paye_basis": paye["basis"],
        "paye": paye,
        "usc": usc,
        "prsi": prsi,
        "myfuturefund": mff,
        "lpt": lpt,
        "labour": labour,
        "bases": {
            "gross": gross,
            "paye_payable": paye_payable,
            "usc_payable": usc_payable,
            "prsi_reckonable": prsi_reckonable,
            "mff_base": mff_base,
        },
        "rounded_outputs": {
            "paye": paye_rounded, "usc": usc_rounded,
            "employee_prsi": prsi_ee_rounded, "employer_prsi": prsi_er_rounded,
            "mff_employee": mff_ee_rounded, "mff_employer": mff_er_rounded,
            "lpt": lpt_rounded, "employee_pension": _round2(employee_pension),
            "employer_pension": _round2(employer_pension),
            "employee_total": employee_total,
        },
    }

    return {
        "tds": paye_rounded,
        "ie_employee_total": employee_total,
        "ie_paye": paye_rounded,
        "ie_paye_basis": paye["basis"],
        "ie_paye_unrounded": paye["paye"],
        "ie_standard_rate_pay": _round2(paye["standard_band_pay"]),
        "ie_higher_rate_pay": _round2(paye["higher_rate_pay"]),
        "ie_tax_credit_applied": _round2(paye["tax_credit_applied"]),
        "ie_rpn_number": rpn.get("rpn_number"),
        "ie_rpn_snapshot_id": rpn.get("snapshot_id"),
        "ie_rpn_hash": rpn.get("raw_hash"),
        "ie_rpn_issued_at": rpn.get("issued_at"),
        "ie_usc": usc_rounded,
        "ie_usc_unrounded": usc["usc"],
        "ie_usc_payable_ytd_after": usc.get("usc_payable_ytd_after"),
        "ie_employee_prsi": prsi_ee_rounded,
        "ie_employer_prsi": prsi_er_rounded,
        "ie_prsi_class": prsi["subclass"],
        "ie_prsi_declaration": prsi["declared_subclass"],
        "ie_prsi_ax_credit": _round2(prsi["ax_credit"]),
        "ie_prsi_contribution_weeks": prsi["contribution_weeks"],
        "ie_prsi_weekly_reckonable": prsi["weekly_reckonable"],
        "ie_prsi_reckonable_ytd_after": prsi["reckonable_ytd_after"],
        "ie_mff_employee": mff_ee_rounded,
        "ie_mff_employer": mff_er_rounded,
        "ie_mff_state_topup": _round2(mff["state_topup"]),
        "ie_mff_status": mff["status"],
        "ie_mff_contributory": mff["contributory"],
        "ie_mff_ceased_reason": mff.get("ceased_reason"),
        "ie_mff_earnings_ytd_after": mff.get("earnings_ytd_after"),
        "ie_lpt": lpt_rounded,
        "ie_lpt_instructed": lpt["instructed"],
        "ie_lpt_rate_pct": lpt.get("rate_pct"),
        "ie_employee_pension": _round2(employee_pension),
        "ie_employer_pension": _round2(employer_pension),
        "ie_employer_prsi_total": prsi_er_rounded,
        "ie_nmw_rate": labour["nmw_hourly"],
        "ie_nmw_band": labour["nmw_band"],
        "ie_effective_hourly": _round2(labour["effective_hourly"]),
        "ie_tax_year": trace["tax_year"],
        "ie_calculation_trace": trace,
        "ie_ytd_after": {
            "usc_payable_ytd": usc.get("usc_payable_ytd_after"),
            "usc_paid_ytd": usc.get("usc_paid_ytd_after"),
            "prsi_reckonable_ytd": prsi["reckonable_ytd_after"],
            "mff_earnings_ytd": mff.get("earnings_ytd_after"),
        },
        "employee_pension": _round2(employee_pension),
        "employer_pension": _round2(employer_pension),
        "employer_social_security": prsi_er_rounded,
    }

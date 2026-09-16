"""
modules/payroll/engine/countries/australia.py
-------------------------------------------------
Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001).

Phase 1 of the build (Phase 0 laid the employee-declaration foundation):
ATO Schedule 1 (NAT 1004) PAYG withholding via genuine coefficient-band
selection, Schedule 8 (NAT 3539) STSL, Superannuation Guarantee, and
Medicare Levy Surcharge. Medicare Levy PROPER is deliberately NOT a
separate calculation here — it is embedded directly in the Schedule 1
Scale 1/2/5/6 coefficient bands themselves (that is exactly what
distinguishes Scale 5 "full Medicare exemption" and Scale 6 "half
Medicare exemption" from the standard Scale 1/2 tables) — see §5's own
Core Calculation Contract, which never asks for an independent Medicare
Levy add-on step. This codebase's shared `medicare` PayrollResult field
therefore now holds ONLY the Medicare Levy Surcharge (MLS) for Australia,
a genuinely separate annual calculation unrelated to Schedule 1 scale
selection.

ENGINEERING RULE (§4, AU-D02): ordinary PAYG withholding must NEVER be
computed by annualizing the reference income-tax brackets — the ATO
schedule/coefficient asset is the only production calculation path. The
annual bracket table (§4) is validation/reference data only; if
configured, it feeds the informational `annual_tax` field, never `tds`.

Phase 2 (Payday Super) adds: real YTD-based Maximum Contribution Base
tracking for Superannuation Guarantee (falls back to the current-period-
annualized estimate when no accumulator is wired for this employee yet —
identical dormancy discipline to every other YTD field in this codebase),
and the §11 PAYG-withholding/SG-qualifying-earnings taxability matrix
(falls back to "every named component counts," i.e. plain ctx.gross,
when no TaxabilityRule override is configured). The per-payday
liability/fund-receipt-SLA RECORD itself (§10's "each payday creates a
traceable SG liability") is a service.py/models.SuperGuaranteeLiability
concern, deliberately layered OUTSIDE this pure-function engine module —
this file computes the SG AMOUNT that record wraps around.

Phase 3 (Special PAYG Schedules) adds: the §9 payment-type routing matrix,
real ETP cap classification and genuine-redundancy tax-free formula (§13
gives these in full) — every OTHER named schedule (2/3/4/5/6/12/13, and
WHM's own Scale) routes correctly but raises AuScheduleNotYetImplemented
Error, since the source document names them without ever publishing their
actual rate/coefficient table.

Phase 4 (State/Territory Employer Payroll Tax) adds: all 8 jurisdictions'
liability calculations (§14-18), banded on the ORG's aggregate wages via
the same telescope_period_amount/OrganizationYtdAccumulator mechanism
Canada's Ontario EHT already established — a completely separate
employer-liability plane (AU-D05) that never touches employee net pay.
NSW/TAS/ACT reuse the ordinary MARGINAL_RATE bracket-summing mechanism
(their formulas ARE plain bracket tables once expressed as ranges); VIC/
QLD/WA/NT/SA get dedicated functions for their taper/rate-switch shapes.
SA's $1.5m-$1.7m reduced-rate band has no formula anywhere in the source
document (which explicitly forbids approximating one) and raises
internally, caught and logged rather than blocking the whole payslip.
NOT yet wired in Phase 4 (documented, not dropped): cross-employer group/
interstate wage aggregation (§AU-D07), VIC/QLD's national-payroll-banded
surcharges, and workers-compensation/employer-classification overlays
(§18) beyond the plain regional-rate flag.

Not yet implemented anywhere in this module (disclosed, not silently
wrong): Working Holiday Maker PAYG and Special PAYG Schedules 2/3/4/5/6/
12/13 — see Phase 3 above.
"""

import logging
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_jurisdiction_parameter, resolve_periods_per_year, _calculate_annual_tax,
    _AU_TAXABILITY_MATRIX_ENABLED_COUNTRIES, telescope_period_amount,
)
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _AU_MLS_THRESHOLD, _AU_MLS_RATE, _AU_SUPER_MAX_CONTRIBUTION_BASE,
    _AU_PAYG_SCALE4_RESIDENT_RATE, _AU_PAYG_SCALE4_NONRESIDENT_RATE,
    _AU_ETP_LIFE_CAP, _AU_ETP_DEATH_CAP, _AU_GENUINE_REDUNDANCY_BASE, _AU_GENUINE_REDUNDANCY_PER_YEAR,
    _AU_WA_PT_THRESHOLD, _AU_WA_PT_UPPER_THRESHOLD, _AU_WA_PT_RATE,
    _AU_QLD_PT_THRESHOLD, _AU_QLD_PT_UPPER_THRESHOLD, _AU_QLD_PT_RATE_LOW, _AU_QLD_PT_RATE_HIGH, _AU_QLD_PT_RATE_SWITCH,
    _AU_VIC_PT_PHASE_START, _AU_VIC_PT_PHASE_END, _AU_VIC_PT_BASE_DEDUCTION, _AU_VIC_PT_RATE, _AU_VIC_PT_REGIONAL_RATE,
    _AU_NT_PT_THRESHOLD, _AU_NT_PT_RATE, _AU_NT_PT_RATE_HIGH, _AU_NT_PT_RATE_SWITCH,
    _AU_SA_PT_LOWER_THRESHOLD, _AU_SA_PT_UPPER_THRESHOLD, _AU_SA_PT_RATE,
)

_logger = logging.getLogger("zoiko")


class AuScheduleNotYetImplementedError(Exception):
    """Raised when ordinary Schedule 1 scale selection is asked to
    compute PAYG for a case §9 explicitly routes to a DEDICATED special
    schedule instead (Working Holiday Maker today). Never silently
    substitutes an ordinary resident/foreign-resident scale — AU-D11
    ("special payments are explicit") and §9's own instruction to "use
    WHM schedule/rates rather than resident Scale 2 assumptions" both
    forbid it. Phase 3 replaces this with the real dedicated schedule."""
    def __init__(self, case: str):
        self.case = case
        super().__init__(
            f"AU PAYG case '{case}' requires a dedicated Schedule 1 §9 special schedule "
            "not yet implemented (Phase 3) — refusing to compute an incorrect ordinary-scale amount."
        )


def _au_floor_dollars(amount: Decimal) -> Decimal:
    """§5 step 2/3's "ignore cents" instruction — floor, never round, per
    the ATO's own wording."""
    return amount.to_integral_value(rounding=ROUND_FLOOR)


def _au_round_to_dollar(amount: Decimal) -> Decimal:
    """NAT 1004's withholding-result rounding: nearest dollar, 50 cents
    rounds up."""
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# §5 step 2: weekly-equivalent x conversion, per pay frequency —
# (numerator, denominator) applied to period earnings before the
# floor-then-add-99-cents step. FourWeekly uses the ATO's ordinary /4
# conversion; Monthly uses the ATO's own named "3/13 method."
_AU_WEEKLY_EQUIVALENT_RATIO = {
    "Weekly": (Decimal("1"), Decimal("1")),
    "Fortnightly": (Decimal("1"), Decimal("2")),
    "FourWeekly": (Decimal("1"), Decimal("4")),
    "Monthly": (Decimal("3"), Decimal("13")),
}


def _au_weekly_equivalent(period_gross: Decimal, pay_frequency: str) -> Decimal:
    numerator, denominator = _AU_WEEKLY_EQUIVALENT_RATIO.get(pay_frequency or "Monthly", _AU_WEEKLY_EQUIVALENT_RATIO["Monthly"])
    raw = period_gross * numerator / denominator
    return _au_floor_dollars(raw) + Decimal("0.99")


def _au_convert_weekly_to_period(weekly_amount: Decimal, pay_frequency: str) -> Decimal:
    """§5 step 4 — the exact inverse of _au_weekly_equivalent's ratio."""
    numerator, denominator = _AU_WEEKLY_EQUIVALENT_RATIO.get(pay_frequency or "Monthly", _AU_WEEKLY_EQUIVALENT_RATIO["Monthly"])
    return weekly_amount * denominator / numerator


def _resolve_au_payg_scale(ctx: PayrollContext) -> str:
    """§9's "No TFN -> Scale 4" is checked first since it overrides every
    other declaration. An UNSET au_tfn_status resolves through the
    ORDINARY scale path below (as if a TFN were on file) — same "unset
    means the standard path, not the most punitive edge case" convention
    UK's unset tax_code already uses; Scale 4 applies only when this is
    EXPLICITLY "NOT_PROVIDED", a real recorded fact, never inferred from
    absence. See models.PayrollEmployee.au_tfn_status's own docstring."""
    if ctx.au_tfn_status == "NOT_PROVIDED":
        return "SCALE_4"
    if ctx.au_residency_status == "WORKING_HOLIDAY_MAKER":
        raise AuScheduleNotYetImplementedError("WORKING_HOLIDAY_MAKER")
    if ctx.au_residency_status == "FOREIGN_RESIDENT":
        return "SCALE_3"
    if ctx.au_medicare_levy_exemption == "FULL":
        return "SCALE_5"
    if ctx.au_medicare_levy_exemption == "HALF":
        return "SCALE_6"
    # au_tax_free_threshold_claimed unset/False -> Scale 1 (the
    # conservative default — see that column's own docstring).
    return "SCALE_2" if ctx.au_tax_free_threshold_claimed else "SCALE_1"


def _resolve_au_coefficient_band(x: Decimal, family_key: str, rule_type: str, slabs):
    """Selects the ONE band (not a marginal-bracket sum) whose
    [min_amount, max_amount) contains x, for the given Scale/declaration-
    state family and rule_type (AU_PAYG_COEFFICIENT or
    AU_STSL_COEFFICIENT) — see models.TaxSlab's own rule_type docstring
    for exactly which columns hold a/b/scale here. Returns None (never a
    guessed band) when nothing is configured yet."""
    candidates = [
        s for s in (slabs or [])
        if getattr(s, "rule_type", None) == rule_type and getattr(s, "filing_status", None) == family_key
    ]
    for slab in sorted(candidates, key=lambda s: s.min_amount):
        upper = slab.max_amount
        if x >= slab.min_amount and (upper is None or x < upper):
            return slab
    return None


def _apply_au_coefficient_formula(x: Decimal, band) -> Decimal:
    """y = a·x − b (§5 step 3), rounded to the nearest dollar. `a` lives
    in rate_pct, `b` in flat_amount — see models.TaxSlab's rule_type
    docstring."""
    a = band.rate_pct
    b = band.flat_amount or Decimal("0")
    y = (a * x) - b
    return _au_round_to_dollar(max(Decimal("0"), y))


def _resolve_au_taxability(component_key: str, rules: dict) -> bool:
    if component_key in rules:
        return rules[component_key]
    return True


def _calculate_au_program_wages(ctx: PayrollContext, tax_component: str) -> Decimal:
    """Per-program (payg_withholding/sg_qualifying_earnings) wage base for
    the CURRENT pay period (§11) — which of the employee's own named
    salary components count toward THIS specific program, independently
    of the other one (§11's own table: reimbursements are often non-wage
    for PAYG but never SG/QE; salary-sacrifice-to-super is pre-tax for
    PAYG but never a substitute for the employer's own SG obligation).
    Identical shape/contract to canada.py's _calculate_ca_program_wages —
    `rules` comes from ctx.au_taxability_rules[tax_component] (service.
    get_au_taxability_rules_bundle); every dollar of ctx.gross lands in
    exactly one bucket, so included-total always equals ctx.gross when
    every component is (as by default) included."""
    rules = (ctx.au_taxability_rules or {}).get(tax_component, {})
    named_allowances = max(
        Decimal("0"),
        ctx.gross - ctx.basic - ctx.hra - ctx.special_allowance - ctx.overtime - ctx.additional_compensation,
    )
    components = {
        "basic": ctx.basic, "hra": ctx.hra, "special_allowance": ctx.special_allowance,
        "overtime": ctx.overtime, "additional_compensation": ctx.additional_compensation,
        "named_allowances": named_allowances,
    }
    included = Decimal("0")
    for key, amount in components.items():
        if _resolve_au_taxability(key, rules):
            included += amount
    return included


def _calculate_au_payg_schedule1(ctx: PayrollContext, period_gross: Decimal) -> Decimal:
    """ATO Schedule 1 (NAT 1004) — the Core Calculation Contract, §5.
    `period_gross` is the caller's own PAYG-taxable wage base (§11) —
    plain ctx.gross when the taxability matrix is dormant/unconfigured,
    exactly today's behavior."""
    scale = _resolve_au_payg_scale(ctx)

    if scale == "SCALE_4":
        rate_map = ctx.rate_map
        is_resident = ctx.au_residency_status != "FOREIGN_RESIDENT"
        rate = resolve_jurisdiction_parameter(
            rate_map,
            "payg_scale4_resident_rate" if is_resident else "payg_scale4_nonresident_rate",
            _AU_PAYG_SCALE4_RESIDENT_RATE if is_resident else _AU_PAYG_SCALE4_NONRESIDENT_RATE,
            side="employee", country="AU",
        )
        # Scale 4 is a flat % of actual earnings, not a coefficient band —
        # no weekly-equivalent conversion. §6's own cents treatment:
        # ignore cents in earnings, then ignore cents in the result.
        earnings = _au_floor_dollars(period_gross)
        return _au_floor_dollars(earnings * rate / Decimal("100"))

    x = _au_weekly_equivalent(period_gross, ctx.pay_frequency)
    band = _resolve_au_coefficient_band(x, scale, "AU_PAYG_COEFFICIENT", ctx.slabs)
    if band is None:
        _logger.warning("[au-payg-unconfigured] no AU_PAYG_COEFFICIENT band configured for %s at x=%s", scale, x)
        return Decimal("0")

    weekly_withholding = _apply_au_coefficient_formula(x, band)
    period_withholding = _au_convert_weekly_to_period(weekly_withholding, ctx.pay_frequency)

    # §14's ATO-authorised withholding variation — applied only when on
    # file, never inferred.
    if ctx.au_withholding_variation_pct is not None:
        period_withholding = period_withholding * (Decimal("1") + ctx.au_withholding_variation_pct / Decimal("100"))

    return _au_round_to_dollar(max(Decimal("0"), period_withholding))


def _resolve_au_stsl_family(ctx: PayrollContext) -> str:
    """§8's own declaration-state table: "Tax-free threshold claimed OR
    foreign resident" is one coefficient family, sharing the SAME
    au_tax_free_threshold_claimed/au_residency_status fields Schedule 1
    itself uses — not a separate STSL-only declaration."""
    if ctx.au_tax_free_threshold_claimed or ctx.au_residency_status == "FOREIGN_RESIDENT":
        return "STSL_CLAIMED_OR_FOREIGN"
    return "STSL_NOT_CLAIMED"


def _calculate_au_stsl_schedule8(ctx: PayrollContext, period_gross: Decimal) -> Decimal:
    """ATO Schedule 8 (NAT 3539) — independently calculated and
    independently traced from ordinary PAYG (§8 STSL CONTRACT: "not a
    generic percentage deduction"), returned as its own payslip line via
    the shared study_loan_deduction field. Gated on the SAME
    has-an-outstanding-loan fact UK's Student Loan mechanism already
    gates on — study_loan_plan/study_loan_balance is one field pair
    shared by both jurisdictions (see models.PayrollEmployee.
    study_loan_plan's own docstring), not an AU-only duplicate. The old
    flat HELP-threshold-and-rate approximation this superseded is
    removed, not merely unused — Schedule 8's real coefficient bands are
    the production calculation now. `period_gross` is the same
    PAYG-taxable wage base Schedule 1 itself uses (§11 has no separate
    STSL column — Schedule 8 is a PAYG-style withholding)."""
    if ctx.study_loan_plan != "AU_HELP" or not ctx.study_loan_balance or ctx.study_loan_balance <= 0:
        return Decimal("0")

    family = _resolve_au_stsl_family(ctx)
    x = _au_weekly_equivalent(period_gross, ctx.pay_frequency)
    band = _resolve_au_coefficient_band(x, family, "AU_STSL_COEFFICIENT", ctx.slabs)
    if band is None:
        _logger.warning("[au-stsl-unconfigured] no AU_STSL_COEFFICIENT band configured for %s at x=%s", family, x)
        return Decimal("0")

    weekly_component = _apply_au_coefficient_formula(x, band)
    period_component = _au_convert_weekly_to_period(weekly_component, ctx.pay_frequency)
    return _au_round_to_dollar(max(Decimal("0"), period_component))


def calculate(ctx: PayrollContext) -> dict:
    """Australia: Superannuation Guarantee (employer-only, capped at the
    Maximum Contribution Base, YTD-aware once wired) + ATO Schedule 1 PAYG
    (includes Medicare Levy proper for Scale 1/2/5/6) + Schedule 8 STSL +
    Medicare Levy Surcharge. Frequency-aware throughout via
    ctx.pay_frequency/resolve_periods_per_year — the previous stub's
    hardcoded MONTHS_PER_YEAR assumption silently mis-annualized any
    non-Monthly AU employee (e.g. Weekly gross × 12 instead of × 52);
    fixed here as part of this rebuild, same convention
    engine/countries/uk.py already uses.

    Reused PayrollResult fields: `medicare` is Medicare Levy SURCHARGE
    only for Australia (see this module's own docstring for why Medicare
    Levy proper is not a separate field), `employer_pension` is
    Superannuation, `study_loan_deduction` is the Schedule 8 STSL
    component, `tds` is Schedule 1 PAYG withholding."""
    rate_map = ctx.rate_map
    period_gross = ctx.gross
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    annual_gross = period_gross * periods_per_year

    # §11 Taxability Matrix — dormant-switch + per-org-configuration
    # double gate, identical shape to canada.py's own _ca_taxability_on.
    # OFF (or no TaxabilityRule override configured) means every named
    # component counts toward both programs, i.e. plain ctx.gross —
    # today's exact behavior.
    _au_taxability_on = "AU" in _AU_TAXABILITY_MATRIX_ENABLED_COUNTRIES
    payg_taxable_gross = _calculate_au_program_wages(ctx, "payg_withholding") if _au_taxability_on else period_gross
    sg_qualifying_gross = _calculate_au_program_wages(ctx, "sg_qualifying_earnings") if _au_taxability_on else period_gross

    # Superannuation Guarantee (§10) — the per-payslip SG amount. Payday
    # Super's own liability/fund-receipt-SLA RECORD is a service.py/
    # SuperGuaranteeLiability concern, layered outside this pure-function
    # module; this computes the amount that record wraps around.
    super_cap = resolve_jurisdiction_parameter(rate_map, "super_max_contrib", _AU_SUPER_MAX_CONTRIBUTION_BASE, country="AU")
    super_rate = rate_map.get("super")
    super_employer_rate = super_rate.employer_rate_pct if super_rate else None
    ytd_sg_qualifying_earnings_after = None
    sg_qualifying_earnings_period = None
    sg_mcb_reached = None

    if ctx.ytd_sg_qualifying_earnings_before is not None:
        # Real YTD-based MCB tracking (§10: "track employee YTD qualifying
        # earnings; when annual MCB reached, SG minimum obligation may
        # cease") — direct period calculation on the ACTUAL qualifying
        # earnings capped at whatever MCB room remains this Australian
        # financial year, not a current-period-annualized estimate.
        # Mirrors canada.py's own `ytd_pensionable_earnings is not None`
        # branch shape exactly.
        room = max(Decimal("0"), super_cap - ctx.ytd_sg_qualifying_earnings_before)
        this_period_qualifying_capped = min(sg_qualifying_gross, room)
        ytd_sg_qualifying_earnings_after = ctx.ytd_sg_qualifying_earnings_before + sg_qualifying_gross
        sg_qualifying_earnings_period = this_period_qualifying_capped
        sg_mcb_reached = ytd_sg_qualifying_earnings_after >= super_cap
        employer_pension = (
            _round2(this_period_qualifying_capped * (super_employer_rate / 100))
            if super_employer_rate else Decimal("0")
        )
    else:
        # Dormant fallback — current-period-annualized estimate, exactly
        # today's pre-Phase-2 behavior.
        annual_sg_qualifying = sg_qualifying_gross * periods_per_year
        annual_super_base = min(annual_sg_qualifying, super_cap)
        employer_pension = (
            _round2((annual_super_base * (super_employer_rate / 100)) / periods_per_year)
            if super_employer_rate else Decimal("0")
        )

    # Medicare Levy Surcharge — genuinely separate from Medicare Levy
    # proper (embedded in Schedule 1 below). Unrelated to Scale selection.
    mls_threshold = resolve_jurisdiction_parameter(rate_map, "mls_threshold", _AU_MLS_THRESHOLD, country="AU")
    mls_rate = resolve_jurisdiction_parameter(rate_map, "mls_rate", _AU_MLS_RATE, side="employee", country="AU")
    medicare_levy_surcharge = Decimal("0")
    if annual_gross > mls_threshold:
        medicare_levy_surcharge = _round2((annual_gross * mls_rate / Decimal("100")) / periods_per_year)

    tds = _calculate_au_payg_schedule1(ctx, payg_taxable_gross)
    study_loan_deduction = _calculate_au_stsl_schedule8(ctx, payg_taxable_gross)

    # Reference/validation only (AU-D02) — never a substitute for the
    # Schedule 1 result above. 0 until reference MARGINAL_RATE annual
    # bracket rows are configured (shared._calculate_annual_tax already
    # excludes AU_PAYG_COEFFICIENT/AU_STSL_COEFFICIENT rows from this,
    # so the two calculations can never collide even though they read
    # the same ctx.slabs list).
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)

    # §14-18 state/territory employer payroll tax — a completely separate,
    # employer-liability-only plane (AU-D05). Never affects tds/net pay.
    state_payroll_tax_result = calculate_au_state_payroll_tax(ctx)

    # §19 child support/garnishee — "Execute after tax according to
    # order": applied against what's left AFTER ordinary PAYG/STSL/
    # Medicare Levy Surcharge, exactly like a real take-home-pay
    # garnishee base. A genuine EMPLOYEE deduction (unlike the employer-
    # only state payroll tax above) — see this module's own
    # calculate_au_statutory_deductions docstring.
    attachable_earnings = max(Decimal("0"), period_gross - tds - study_loan_deduction - medicare_levy_surcharge)
    statutory_deductions_result = calculate_au_statutory_deductions(ctx.au_statutory_deduction_orders, attachable_earnings)

    return dict(
        medicare=medicare_levy_surcharge,
        employer_pension=employer_pension,
        study_loan_deduction=study_loan_deduction,
        tds=tds, annual_tax=annual_tax,
        ytd_sg_qualifying_earnings_after=ytd_sg_qualifying_earnings_after,
        sg_qualifying_earnings_period=sg_qualifying_earnings_period,
        sg_rate_pct=super_employer_rate if ytd_sg_qualifying_earnings_after is not None else None,
        employer_payroll_tax=state_payroll_tax_result["employer_payroll_tax"],
        au_state_payroll_tax_ytd_remuneration_after=state_payroll_tax_result["au_state_payroll_tax_ytd_remuneration_after"],
        sg_mcb_reached=sg_mcb_reached,
        au_statutory_deductions_total=statutory_deductions_result["total_deduction"],
        au_statutory_deductions_detail=statutory_deductions_result["orders"],
    )


# ── Special PAYG Schedules (§9 Routing Matrix, §13 caps) — Phase 3 ───────
# AU-D11 ("special payments are explicit... ordinary Scale 1/2 is not
# used as fallback") and §9's own instruction apply to every one of these
# — this section deliberately routes each special-payment TYPE to its own
# named schedule rather than ever running it through _calculate_au_payg_
# schedule1. Two calculators here are REAL, complete implementations
# because §13 gives their actual figures/formula in full: the ETP cap
# classification and the genuine-redundancy tax-free component. Every
# other schedule in §9's table (2/3/4/5/6/12/13, and Working Holiday
# Maker's own Scale) requires a coefficient/rate/method the source
# document names but never actually gives a number or formula for — those
# raise AuScheduleNotYetImplementedError, the same discipline
# _resolve_au_payg_scale already applies to WHM, rather than fabricating
# a plausible-looking withholding amount.

# §9's own routing table, verbatim: payment TYPE -> named schedule. A
# real, complete piece of §9 even though most schedules' downstream math
# isn't buildable yet — the ROUTING itself is fully specified, and
# getting an employee's payment routed to the CORRECT schedule name is
# exactly what AU-D11 requires, independent of whether that schedule's
# own rate table exists yet.
_AU_SPECIAL_PAYMENT_SCHEDULE_BY_TYPE = {
    "UNUSED_LEAVE": "SCHEDULE_2",
    "ENTERTAINER": "SCHEDULE_3",
    "RETURN_TO_WORK": "SCHEDULE_4",
    "BACK_PAYMENT": "SCHEDULE_5",
    "COMMISSION": "SCHEDULE_5",
    "BONUS": "SCHEDULE_5",
    "NON_RESIDENT_SPECIAL_CASE": "SCHEDULE_6",
    "ETP": "SCHEDULE_11",
    "SUPER_LUMP_SUM": "SCHEDULE_12",
    "SUPER_INCOME_STREAM": "SCHEDULE_13",
}

# Which of the routed schedules already have a real, document-given
# withholding calculation available. False for every schedule whose rate/
# coefficient table §9 names but does not actually publish.
_AU_SPECIAL_PAYMENT_SCHEDULE_IMPLEMENTED = {
    "SCHEDULE_2": False, "SCHEDULE_3": False, "SCHEDULE_4": False, "SCHEDULE_5": False,
    "SCHEDULE_6": False, "SCHEDULE_11": False, "SCHEDULE_12": False, "SCHEDULE_13": False,
}


def resolve_au_special_payment_schedule(payment_type: str) -> str:
    """§9 Special PAYG Schedules — Routing Matrix. Raises (never guesses a
    schedule) for an unrecognized payment_type — the caller's own
    classification is wrong/incomplete, not a case to silently drop into
    ordinary Scale 1/2."""
    schedule = _AU_SPECIAL_PAYMENT_SCHEDULE_BY_TYPE.get(payment_type)
    if schedule is None:
        raise ValueError(f"Unrecognized AU special payment type: {payment_type!r}")
    return schedule


def calculate_au_special_payment_withholding(payment_type: str, amount: Decimal) -> Decimal:
    """Routes to the correct §9 schedule and refuses to compute an
    ordinary-Scale withholding amount for it — see this section's own
    module-level comment for why. A real implementation replaces the
    `raise` below, schedule by schedule, once its actual ATO rate/
    coefficient table is entered (Phase 8 territory, not fabricated
    here)."""
    schedule = resolve_au_special_payment_schedule(payment_type)
    if not _AU_SPECIAL_PAYMENT_SCHEDULE_IMPLEMENTED.get(schedule, False):
        raise AuScheduleNotYetImplementedError(schedule)
    raise AuScheduleNotYetImplementedError(schedule)  # unreachable until a schedule flips to True above


def calculate_au_etp_cap_classification(ctx: PayrollContext, etp_amount: Decimal, is_death_benefit: bool = False) -> dict:
    """§13's ETP life/death benefit cap — classifies an Employment
    Termination Payment amount into the portion within cap (eligible for
    concessional ETP tax treatment) versus the portion above cap (taxed
    at the top marginal rate, per general ETP rules). Deliberately does
    NOT compute the actual withholding tax on either portion — the
    concessional ETP tax rate itself is not given anywhere in
    ZP-TAX-AU-2026-27-001, only the cap amount is (§13's own table)."""
    cap = resolve_jurisdiction_parameter(
        ctx.rate_map, "etp_death_cap" if is_death_benefit else "etp_life_cap",
        _AU_ETP_DEATH_CAP if is_death_benefit else _AU_ETP_LIFE_CAP, country="AU",
    )
    amount_within_cap = min(etp_amount, cap)
    amount_above_cap = max(Decimal("0"), etp_amount - cap)
    return {
        "cap_type": "DEATH_BENEFIT" if is_death_benefit else "LIFE_BENEFIT",
        "cap_applied": cap,
        "amount_within_cap": amount_within_cap,
        "amount_above_cap": amount_above_cap,
    }


def _au_linear_taper_deduction(wages: Decimal, base_deduction: Decimal, phase_out_start: Decimal, taper_rate: Decimal, zero_at: Decimal = None) -> Decimal:
    """The 'deduction shrinks linearly as wages rise' shape shared by
    VIC/QLD/WA (§17): full base_deduction up to phase_out_start, then
    reduced by taper_rate per dollar above that, floored at 0 (or exactly
    0 once wages reach zero_at, if given)."""
    if wages <= phase_out_start:
        return base_deduction
    if zero_at is not None and wages >= zero_at:
        return Decimal("0")
    return max(Decimal("0"), base_deduction - (wages - phase_out_start) * taper_rate)


def _au_wa_annual_payroll_tax(wages: Decimal, rate_map: dict) -> Decimal:
    """§17: deductible amount = $1,000,000 − [(wages − $1,000,000) × 2/13], zero at $7.5m."""
    threshold = resolve_jurisdiction_parameter(rate_map, "wa_pt_threshold", _AU_WA_PT_THRESHOLD, country="AU")
    upper = resolve_jurisdiction_parameter(rate_map, "wa_pt_upper_threshold", _AU_WA_PT_UPPER_THRESHOLD, country="AU")
    rate = resolve_jurisdiction_parameter(rate_map, "wa_pt_rate", _AU_WA_PT_RATE, side="employer", country="AU")
    deduction = _au_linear_taper_deduction(wages, threshold, threshold, Decimal("2") / Decimal("13"), upper)
    return max(Decimal("0"), wages - deduction) * rate / Decimal("100")


def _au_qld_annual_payroll_tax(wages: Decimal, rate_map: dict) -> Decimal:
    """§17: deduction reduces $1 per $7 above $1.3m threshold, zero at
    $10.4m; rate itself is chosen by total wages (4.75% at/below $6.5m,
    4.95% above) — a flat rate on the whole excess, not a marginal split."""
    threshold = resolve_jurisdiction_parameter(rate_map, "qld_pt_threshold", _AU_QLD_PT_THRESHOLD, country="AU")
    upper = resolve_jurisdiction_parameter(rate_map, "qld_pt_upper_threshold", _AU_QLD_PT_UPPER_THRESHOLD, country="AU")
    rate_low = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_low", _AU_QLD_PT_RATE_LOW, side="employer", country="AU")
    rate_high = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_high", _AU_QLD_PT_RATE_HIGH, side="employer", country="AU")
    rate_switch = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_switch", _AU_QLD_PT_RATE_SWITCH, country="AU")
    deduction = _au_linear_taper_deduction(wages, threshold, threshold, Decimal("1") / Decimal("7"), upper)
    rate = rate_high if wages > rate_switch else rate_low
    return max(Decimal("0"), wages - deduction) * rate / Decimal("100")


def _au_vic_annual_payroll_tax(wages: Decimal, rate_map: dict, is_regional: bool) -> Decimal:
    """§17: standard $1m deduction, phased out at a linear rate between
    $3m-$5m Australian wages (zero above $5m); regional employers get a
    reduced rate instead of the standard one (§AU-D10 employer overlay,
    read from CompanyComplianceDetails.au_payroll_tax_regional_status).
    Mental-health/COVID-debt surcharges are NOT included here — they are
    a documented, not-yet-wired follow-on (see this module's own Phase 4
    notes), since they band on NATIONAL payroll, a genuinely different
    aggregate than this org's own Victorian wages."""
    phase_start = resolve_jurisdiction_parameter(rate_map, "vic_pt_phase_start", _AU_VIC_PT_PHASE_START, country="AU")
    phase_end = resolve_jurisdiction_parameter(rate_map, "vic_pt_phase_end", _AU_VIC_PT_PHASE_END, country="AU")
    base_deduction = resolve_jurisdiction_parameter(rate_map, "vic_pt_base_deduction", _AU_VIC_PT_BASE_DEDUCTION, country="AU")
    rate = resolve_jurisdiction_parameter(
        rate_map, "vic_pt_regional_rate" if is_regional else "vic_pt_rate",
        _AU_VIC_PT_REGIONAL_RATE if is_regional else _AU_VIC_PT_RATE, side="employer", country="AU",
    )
    taper_range = phase_end - phase_start
    taper_rate = (base_deduction / taper_range) if taper_range > 0 else Decimal("0")
    deduction = _au_linear_taper_deduction(wages, base_deduction, phase_start, taper_rate, phase_end)
    return max(Decimal("0"), wages - deduction) * rate / Decimal("100")


def _au_nt_annual_payroll_tax(wages: Decimal, rate_map: dict) -> Decimal:
    """§17: flat $2.5m deduction; rate itself steps from 5.5% to 6.5% once
    group Australia-wide wages reach $100m — a flat rate on the whole
    excess, not a marginal split."""
    threshold = resolve_jurisdiction_parameter(rate_map, "nt_pt_threshold", _AU_NT_PT_THRESHOLD, country="AU")
    rate_switch = resolve_jurisdiction_parameter(rate_map, "nt_pt_rate_switch", _AU_NT_PT_RATE_SWITCH, country="AU")
    rate_standard = resolve_jurisdiction_parameter(rate_map, "nt_pt_rate", _AU_NT_PT_RATE, side="employer", country="AU")
    rate_high = resolve_jurisdiction_parameter(rate_map, "nt_pt_rate_high", _AU_NT_PT_RATE_HIGH, side="employer", country="AU")
    rate = rate_high if wages >= rate_switch else rate_standard
    return max(Decimal("0"), wages - threshold) * rate / Decimal("100")


def _au_sa_annual_payroll_tax(wages: Decimal, rate_map: dict) -> Decimal:
    """§17 SOURCE LOCK: "Use RevenueSA's 2026-27 reduced-rate asset for
    wages between $1.5m and $1.7m; do not infer/approximate a rate at
    runtime." No such table is given anywhere in the source document, so
    that band raises rather than guesses a rate — literally the one case
    the document itself calls out this explicitly for. Below $1.5m is
    genuinely $0 (not a gap); above $1.7m is the one real flat rate the
    document does give, applied to total wages (no deduction is named for
    this band, unlike every other state — see this function's own
    AuScheduleNotYetImplementedError note in the calling code for how a
    mid-band employer is handled without crashing the whole payslip)."""
    lower = resolve_jurisdiction_parameter(rate_map, "sa_pt_lower_threshold", _AU_SA_PT_LOWER_THRESHOLD, country="AU")
    upper = resolve_jurisdiction_parameter(rate_map, "sa_pt_upper_threshold", _AU_SA_PT_UPPER_THRESHOLD, country="AU")
    rate = resolve_jurisdiction_parameter(rate_map, "sa_pt_rate", _AU_SA_PT_RATE, side="employer", country="AU")
    if wages <= lower:
        return Decimal("0")
    if wages < upper:
        raise AuScheduleNotYetImplementedError("SA_REDUCED_RATE_BAND")
    return wages * rate / Decimal("100")


def _au_bracket_table_annual_payroll_tax(wages: Decimal, state_slabs: list) -> Decimal:
    """NSW/TAS/ACT (§15/§17) — each is a plain marginal bracket table once
    expressed as ranges (NSW: 0% then 5.45% above $1.2m; TAS: three
    bands; ACT: six bands over group Australia-wide wages), so this
    reuses the SAME proven bracket-summing mechanism ordinary income tax
    already uses (shared._calculate_annual_tax) rather than
    reimplementing bracket math. Returns 0 (never a guess) until real
    jurisdiction_state-scoped MARGINAL_RATE TaxSlab rows exist for this
    state — identical 'no rows configured yet' contract every other
    bracket-driven calculation in this codebase already has.

    ACT ASSUMPTION (flag for Phase 8 review): modeled as a genuine
    marginal sum across its 5 published bands, matching ACT's real-world
    'marginal rate scale' design (introduced to remove cliff effects
    between bands) — ZP-TAX-AU-2026-27-001's own §17 note names the
    bands/rates (real, document-given figures) without fully
    disambiguating marginal-vs-flat aggregation; only that AGGREGATION
    METHOD is an engineering judgment call here, never a fabricated rate
    or threshold."""
    return _calculate_annual_tax(wages, state_slabs)


# state -> (annual_amount_fn, needs_ctx) — ctx is needed only where the
# formula reads something beyond wages/rate_map (VIC's regional flag,
# NSW/TAS/ACT's bracket rows).
_AU_STATE_PAYROLL_TAX_ANNUAL_FN = {
    "NSW": lambda wages, ctx: _au_bracket_table_annual_payroll_tax(wages, ctx.state_slabs),
    "VIC": lambda wages, ctx: _au_vic_annual_payroll_tax(wages, ctx.rate_map, ctx.au_payroll_tax_regional_status == "REGIONAL"),
    "QLD": lambda wages, ctx: _au_qld_annual_payroll_tax(wages, ctx.rate_map),
    "WA": lambda wages, ctx: _au_wa_annual_payroll_tax(wages, ctx.rate_map),
    "SA": lambda wages, ctx: _au_sa_annual_payroll_tax(wages, ctx.rate_map),
    "TAS": lambda wages, ctx: _au_bracket_table_annual_payroll_tax(wages, ctx.state_slabs),
    "ACT": lambda wages, ctx: _au_bracket_table_annual_payroll_tax(wages, ctx.state_slabs),
    "NT": lambda wages, ctx: _au_nt_annual_payroll_tax(wages, ctx.rate_map),
}


def calculate_au_state_payroll_tax(ctx: PayrollContext) -> dict:
    """§14-18: employer-liability-only state/territory payroll tax,
    banded on the ORG's aggregate taxable wages in ctx.work_state, not
    this employee's own pay (AU-D05: "must not reduce employee net pay").
    Zero (and no YTD figure reported) unless BOTH ctx.work_state resolves
    to one of the 8 supported jurisdictions AND the org-level accumulator
    is wired — identical dormancy discipline to canada.py's Ontario EHT.

    A schedule-specific gap (currently only SA's reduced-rate band) is
    caught and logged here rather than propagated — this is a separate,
    employer-side reporting plane from the employee's own PAYG/SG/STSL,
    so an unconfigured SA band must never block an unrelated employee's
    entire payslip from calculating.

    NOT yet wired (documented Phase 4 follow-on, not silently dropped):
    cross-employer group/interstate wage aggregation (§AU-D07 — this
    computes each org's own total in isolation), VIC/QLD's national-
    payroll-banded surcharges (mental health/COVID-debt levies), and
    workers compensation/employer-classification overlays (§18)."""
    state = (ctx.work_state or "").strip().upper()
    annual_fn_factory = _AU_STATE_PAYROLL_TAX_ANNUAL_FN.get(state)
    if annual_fn_factory is None or ctx.au_state_payroll_tax_ytd_remuneration_before is None:
        return {"employer_payroll_tax": Decimal("0"), "au_state_payroll_tax_ytd_remuneration_after": None}

    try:
        period_amount = telescope_period_amount(
            ctx.gross, ctx.au_state_payroll_tax_ytd_remuneration_before,
            lambda cumulative_wages: annual_fn_factory(cumulative_wages, ctx),
        )
    except AuScheduleNotYetImplementedError as exc:
        _logger.warning(
            "[au-payroll-tax-unconfigured] %s payroll tax could not be computed (%s) — "
            "reporting $0 for this period rather than blocking the employee's own payslip.",
            state, exc,
        )
        return {"employer_payroll_tax": Decimal("0"), "au_state_payroll_tax_ytd_remuneration_after": None}

    ytd_after = ctx.au_state_payroll_tax_ytd_remuneration_before + ctx.gross
    return {"employer_payroll_tax": period_amount, "au_state_payroll_tax_ytd_remuneration_after": ytd_after}


def calculate_au_genuine_redundancy_tax_free_component(ctx: PayrollContext, complete_years_of_service: int) -> Decimal:
    """§13's genuine redundancy / early retirement tax-free limit —
    $13,598 + $6,801 × complete years of service, a real, fully-specified
    formula (unlike the rest of this section). `complete_years_of_service`
    is the caller's own computed whole-year count from date_of_joining/
    date_of_leaving — this function performs no date arithmetic itself,
    matching india.py's calculate_gratuity's own "caller supplies the
    already-computed service figure" convention."""
    if complete_years_of_service < 0:
        raise ValueError("complete_years_of_service cannot be negative")
    base = resolve_jurisdiction_parameter(ctx.rate_map, "redundancy_base", _AU_GENUINE_REDUNDANCY_BASE, country="AU")
    per_year = resolve_jurisdiction_parameter(ctx.rate_map, "redundancy_per_yr", _AU_GENUINE_REDUNDANCY_PER_YEAR, country="AU")
    return _round2(base + per_year * Decimal(complete_years_of_service))


# ── Child Support / Garnishee (§19) — Phase 5 ────────────────────────────
# Reuses models.CourtOrderedDeduction directly (jurisdiction="AUSTRALIA")
# — the table was already generic (free-text jurisdiction column, no
# UK-only constraint). Unlike UK's THREE separate jurisdiction functions
# (England & Wales / Scotland / Northern Ireland genuinely have different
# published band tables), Australia is ONE jurisdiction with TWO
# order-type categories per §19's own "Section 72A / special notices:
# Allow order types where protected earnings does not apply" instruction
# — so this is a single function branching on order_type, not three.
#
# No published AU banded-percentage table exists anywhere in
# ZP-TAX-AU-2026-27-001 (§19 gives CONTROL requirements — priority,
# protected earnings, arrears/fixed/percentage modes — never an actual
# generic rate table the way UK's own AEO/arrestment tables at least
# NAME). An order therefore MUST specify its own fixed_deduction_amount
# or fixed_deduction_rate_pct — in practice the normal case for a real
# Services Australia child support notice, which always states its own
# periodic amount or percentage, unlike UK's AEO orders which typically
# defer to a published band table instead.
_AU_STATUTORY_DEDUCTION_NO_PROTECTED_EARNINGS_ORDER_TYPES = {"SECTION_72A_NOTICE"}


def calculate_au_statutory_deduction(
    attachable_earnings: Decimal,
    order_type: str,
    fixed_deduction_rate_pct: Decimal | None,
    fixed_deduction_amount: Decimal | None,
    protected_earnings_amount: Decimal | None,
) -> dict:
    """One AU statutory deduction order (§19). Returns `eligible` (bool),
    `reason` (str), `deduction_amount` (Decimal) — same shape as UK's
    calculate_court_order_deduction_england_wales/scotland/
    northern_ireland, minus the generic-band-table fallback tier those
    have (no such table exists in the source document for Australia)."""
    applies_protected_earnings = order_type not in _AU_STATUTORY_DEDUCTION_NO_PROTECTED_EARNINGS_ORDER_TYPES
    protected = (protected_earnings_amount or Decimal("0")) if applies_protected_earnings else Decimal("0")
    headroom = max(Decimal("0"), attachable_earnings - protected)

    if fixed_deduction_amount is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(fixed_deduction_amount, headroom)}
    if fixed_deduction_rate_pct is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * fixed_deduction_rate_pct / Decimal("100")), headroom)}
    return {
        "eligible": False,
        "reason": "order specifies neither a fixed amount nor a fixed rate, and no generic AU statutory-deduction band table exists in the source document",
        "deduction_amount": Decimal("0"),
    }


def calculate_au_statutory_deductions(orders: list, attachable_earnings: Decimal) -> dict:
    """Given every ACTIVE AU statutory deduction order for one employee
    this period, already sorted by the caller with highest priority
    (lowest priority number) first, calculates each order's deduction in
    that sequence — each subsequent order computed against what's LEFT of
    attachable_earnings after every higher-priority order's own
    deduction (§19's own priority-ordering requirement), identical
    sequencing contract to UK's calculate_court_ordered_deductions.
    `orders` — list of dicts with `id`, `order_type`,
    `fixed_deduction_rate_pct`, `fixed_deduction_amount`,
    `protected_earnings_amount`.

    Returns {"total_deduction": Decimal, "orders": [{"order_id",
    "eligible", "reason", "deduction_amount"}, ...]}."""
    remaining_earnings = attachable_earnings
    total = Decimal("0")
    results = []
    for order in orders:
        result = calculate_au_statutory_deduction(
            remaining_earnings, order.get("order_type"),
            order.get("fixed_deduction_rate_pct"), order.get("fixed_deduction_amount"),
            order.get("protected_earnings_amount"),
        )
        results.append({"order_id": order.get("id"), **result})
        if result["eligible"]:
            total += result["deduction_amount"]
            remaining_earnings = max(Decimal("0"), remaining_earnings - result["deduction_amount"])
    return {"total_deduction": _round2(total), "orders": results}

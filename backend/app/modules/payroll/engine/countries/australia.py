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
gives these in full) — every OTHER named schedule (2/3/4/5/6/12/13)
routes correctly but raises AuScheduleNotYetImplementedError, since the
source document names them without ever publishing their actual rate/
coefficient table. (WHM's own Scale, resolved Phase 11, and Schedules 3/6,
resolved Phase 12 below, no longer belong to this list.)

Phase 4 (State/Territory Employer Payroll Tax) adds: all 8 jurisdictions'
liability calculations (§14-18), banded on the ORG's aggregate wages via
the same telescope_period_amount/OrganizationYtdAccumulator mechanism
Canada's Ontario EHT already established — a completely separate
employer-liability plane (AU-D05) that never touches employee net pay.
NSW/TAS/ACT reuse the ordinary MARGINAL_RATE bracket-summing mechanism
(their formulas ARE plain bracket tables once expressed as ranges); VIC/
QLD/WA/NT/SA get dedicated functions for their taper/rate-switch shapes.
SA's $1.5m-$1.7m reduced-rate band was originally a raise-rather-than-
guess gap (no formula in the source document, which explicitly forbids
approximating one) — RESOLVED 2026-09-17 via RevenueSA's own published
structure, cross-checked against a real RevenueSA worked example (see
_au_sa_annual_payroll_tax's own docstring).
Cross-employer group/interstate wage aggregation (§AU-D07) was closed
2026-09-17 (§18 employer-overlay follow-up) — see service.py's
_au_org_payroll_tax_read_inputs, which now sums the org-level YTD
"before" figure across every org sharing this org's Organization.
connected_group_code (the same mechanism CA's EHT/HE Levy/HAPSET and
UK's Apprenticeship Levy already use), gated behind
_CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES now including "AU". VIC/QLD's
national-payroll-banded surcharges (Mental Health and Wellbeing Levy +
COVID-19 Debt Temporary Surcharge for VIC, Mental Health Levy for QLD)
were resolved 2026-09-17 — see _au_apportioned_national_surcharge. NOT yet
wired: workers-compensation/employer-classification overlays (§18)
beyond the plain regional-rate flag and the now-wired workers
compensation premium (see calculate_au_workers_compensation_premium) —
charity/public-benefit
exemption and industry rebates specifically remain unimplemented since
§18 itself describes them as requiring a human authority/legal
eligibility determination with no computable test given.

Phase 12 (§9, 2026-09-17) resolves Schedule 3 (NAT 1023, actors/variety
artists/other entertainers) and Schedule 6 (NAT 3350, annuities) — see
calculate_au_schedule3_entertainer_withholding and calculate_au_
schedule6_annuity_withholding. Schedule 3's TFN-provided coefficient
tables are real ATO-published data (cross-checked: its own no-TFN rates,
47%/45%, exactly match Schedule 1 Scale 4's already-confirmed rates) but
are NOT yet entered into any live canonical pack — the engine mechanism
and tests are built and proven against the published table; live data
entry is a separate, disclosed follow-up, same status as LITO/SAPTO
single above. Schedule 6 needed no new statutory data at all — it is a
pre-processing step (subtract the annuity's deductible amount, then run
the remainder through the existing Schedule 1 machinery), not its own
rate table.

Still not implemented anywhere in this module (disclosed, not silently
wrong): Schedules 2 (unused leave), 4 (return-to-work), 5 (back
payments/commissions/bonuses — full worked mechanics), 12 (super lump
sums — below-preservation-age rates specifically not independently
verified), and 13 (super income streams) — see Phase 3 above. NAT
catalog numbers for the ones identified so far: Schedule 5=NAT 3348,
Schedule 12=NAT 70981, Schedule 13=NAT 70982; Schedule 4's own NAT
number and Schedule 2's are still unidentified. Knowing the catalog
number is not the same as having the formula.

Phase 11 (§9 WHM, 2026-09-17) resolves Working Holiday Maker PAYG:
Schedule 15 (NAT 75331), a real ATO-published flat 15%/45% rate — see
_resolve_au_payg_scale's "SCALE_WHM" branch and
_calculate_au_payg_schedule1's own docstring for the disclosed
limitation (the real $45,000 first-bracket annual cap needs a YTD
accumulator this engine does not have wired yet; every period is taxed
at the in-cap rate regardless of cumulative WHM earnings this year).

Phase 7 (Golden Tests + Gap Closure) adds: the §7 "Extra-pay calendar"
53-week/27-fortnight additional-withholding top-up (real, document-given
dollar amounts — see _resolve_au_extra_pay_withholding and the new
AU_EXTRA_PAY_WITHHOLDING rule_type).

Phase 10 (§5 step 4, AU-AC11 — tax offsets, 2026-09-17) closes the
former "no offset schedule available" gap for LITO, and SINGLE-only for
SAPTO: real ATO-published 2026-27 figures (LITO cross-checked against
two independent citations of the same ATO page; SAPTO single likewise;
both entered as `AU_LITO_OFFSET`/`AU_SAPTO_OFFSET` TaxSlab rows, same
band-lookup shape as the Schedule 1/8 coefficient bands — see
_resolve_au_income_tax_offset). SAPTO's COUPLE/ILLNESS_SEPARATED_COUPLE
categories are NOT entered: two independent lookups produced conflicting
threshold figures for those categories specifically (single matched
exactly both times), so entering them now would risk exactly the
fabricated-adjacent number this project's SOURCE LOCK rule exists to
prevent. `ctx.au_sapto_category` accepts those values and the mechanism
is fully wired — an employee declared as COUPLE/ILLNESS_SEPARATED_COUPLE
today resolves to $0 (no band configured), the same honest "not a
guess" contract every other unconfigured AU band already has, not an
error — real rows can be added the moment those figures are confirmed
directly against the ATO's own SAPTO calculator, no code change needed.

ENGINEERING JUDGMENT CALL (flag for review, not a fabricated value):
§5 step 4 asks offsets to reduce the PERIOD withholding result, but ATO
only ever publishes LITO/SAPTO as ANNUAL tax-return figures — there is
no separate NAT-published PERIOD withholding scale for either in this
codebase's source material. The offset is therefore computed against
this period's own annualized gross (ctx.gross × periods_per_year, the
same annualization already used for annual_tax/MLS above), then divided
back to a period-equivalent and subtracted from Schedule 1's tds result
(floored at $0) — see calculate()'s own comments at the point of use.
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
    _AU_WHM_RATE, _AU_WHM_NO_TFN_RATE, _AU_WHM_CAP_THRESHOLD,
    _AU_ETP_LIFE_CAP, _AU_ETP_DEATH_CAP, _AU_GENUINE_REDUNDANCY_BASE, _AU_GENUINE_REDUNDANCY_PER_YEAR,
    _AU_WA_PT_THRESHOLD, _AU_WA_PT_UPPER_THRESHOLD, _AU_WA_PT_RATE,
    _AU_QLD_PT_THRESHOLD, _AU_QLD_PT_UPPER_THRESHOLD, _AU_QLD_PT_RATE_LOW, _AU_QLD_PT_RATE_HIGH, _AU_QLD_PT_RATE_SWITCH,
    _AU_VIC_PT_PHASE_START, _AU_VIC_PT_PHASE_END, _AU_VIC_PT_BASE_DEDUCTION, _AU_VIC_PT_RATE, _AU_VIC_PT_REGIONAL_RATE,
    _AU_NT_PT_THRESHOLD, _AU_NT_PT_RATE, _AU_NT_PT_RATE_HIGH, _AU_NT_PT_RATE_SWITCH,
    _AU_SA_PT_LOWER_THRESHOLD, _AU_SA_PT_UPPER_THRESHOLD, _AU_SA_PT_RATE,
    _AU_NATIONAL_SURCHARGE_TIER1_THRESHOLD, _AU_NATIONAL_SURCHARGE_TIER2_THRESHOLD,
    _AU_VIC_SURCHARGE_TIER1_RATE, _AU_VIC_SURCHARGE_TIER2_RATE,
    _AU_QLD_SURCHARGE_TIER1_RATE, _AU_QLD_SURCHARGE_TIER2_RATE,
    _AU_SCHEDULE3_FR_THRESHOLD1, _AU_SCHEDULE3_FR_THRESHOLD2,
    _AU_SCHEDULE3_FR_RATE1, _AU_SCHEDULE3_FR_RATE2, _AU_SCHEDULE3_FR_RATE3,
    _AU_SCHEDULE3_FR_BASE2, _AU_SCHEDULE3_FR_BASE3,
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


def _au_trace_json_safe(value):
    """§25 calculation-trace values are Decimal-heavy (coefficients,
    thresholds, weekly-x), but the JSON column that stores the assembled
    trace (models.PayslipItem.au_calculation_trace) cannot serialize
    Decimal directly — same defect Germany's own CalculationTrace.
    resolve_ok already works around by storing str(v) instead of the raw
    Decimal. Recurses through dict/list so every Decimal anywhere in the
    trace is converted, not just top-level values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _au_trace_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_au_trace_json_safe(v) for v in value]
    return value


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
    if ctx.au_tfn_status == "NOT_PROVIDED" and ctx.au_residency_status != "WORKING_HOLIDAY_MAKER":
        return "SCALE_4"
    if ctx.au_residency_status == "WORKING_HOLIDAY_MAKER":
        return "SCALE_WHM"
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


def _apply_au_offset_formula(annual_income: Decimal, band) -> Decimal:
    """LITO/SAPTO offset shape (§5 step 4): the band's own base offset
    (flat_amount) minus rate_pct% for every dollar of annual income above
    THIS band's own min_amount — unlike the PAYG coefficient formula
    (_apply_au_coefficient_formula), which is always anchored at 0, an
    offset band is anchored at its own start so a flat "no shading yet"
    band (rate_pct=0) and a shading band chain continuously. Floored at
    $0, never negative — see models.TaxSlab's AU_LITO_OFFSET/
    AU_SAPTO_OFFSET rule_type docstring for the column mapping."""
    base_offset = band.flat_amount or Decimal("0")
    rate = band.rate_pct or Decimal("0")
    reduction = rate / Decimal("100") * (annual_income - band.min_amount)
    return max(Decimal("0"), base_offset - reduction)


def _calculate_au_income_tax_offset(annual_income: Decimal, rule_type: str, filing_status: str, slabs) -> Decimal:
    """Resolves and applies the one AU_LITO_OFFSET/AU_SAPTO_OFFSET band
    containing `annual_income` for the given filing_status (LITO's is
    always "LITO"; SAPTO's is ctx.au_sapto_category — "SINGLE",
    "COUPLE", or "ILLNESS_SEPARATED_COUPLE"). Returns $0 (never a guess)
    when no matching band is configured — same dormancy discipline as
    every other AU coefficient-band lookup in this module. This is
    deliberately true today for COUPLE/ILLNESS_SEPARATED_COUPLE: two
    independent lookups of the ATO's own published figures for those
    categories produced conflicting thresholds, so no rows are configured
    for them yet (see this module's own docstring) — $0 here for those
    categories means "not yet confirmed," not "not entitled." """
    band = _resolve_au_coefficient_band(annual_income, filing_status, rule_type, slabs)
    if band is None:
        return Decimal("0")
    return _apply_au_offset_formula(annual_income, band)


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


def _calculate_au_payg_schedule1(ctx: PayrollContext, period_gross: Decimal) -> tuple:
    """ATO Schedule 1 (NAT 1004) — the Core Calculation Contract, §5.
    `period_gross` is the caller's own PAYG-taxable wage base (§11) —
    plain ctx.gross when the taxability matrix is dormant/unconfigured,
    exactly today's behavior. Returns (period_withholding, trace) — trace
    is the §25 calculation-trace payload for this component, always a
    dict (never None), so calculate()'s au_calculation_trace has an
    honest record of scale selection even on the $0/unconfigured paths."""
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
        withholding = _au_floor_dollars(earnings * rate / Decimal("100"))
        return withholding, {
            "scale": scale, "method": "FLAT_RATE", "rate_pct": rate,
            "earnings_floored": earnings, "withholding": withholding,
        }

    if scale == "SCALE_WHM":
        # Schedule 15 (NAT 75331, WHM subclass 417/462) — RESOLVED
        # 2026-09-17, real ATO-published rates: flat 15% (has a TFN) or
        # 45% (no TFN) on actual earnings, same "flat % of period
        # earnings, no weekly-equivalent conversion" shape as Scale 4
        # above.
        #
        # YTD cap detection (added as part of the production-readiness fix
        # plan): the real Schedule 15 table is a CUMULATIVE $45,000
        # first-bracket test across the whole income year, and earnings
        # above that use the graduated foreign-resident rates (32.5%/37%/
        # 45%) — those above-cap rates are NOT published anywhere in this
        # codebase, and this engine will not fabricate them. So once
        # ctx.ytd_whm_earnings_before is wired (see PayrollContext's own
        # docstring), this still withholds at the in-cap 15%/45% rate for
        # every period, but DETECTS a YTD crossing of $45,000 and reports
        # it via method="FLAT_RATE_CAP_EXCEEDED_NEEDS_REVIEW" plus the
        # ytd_whm_earnings_after/whm_cap_exceeded trace keys, so
        # calculate() can surface PayrollResult.au_whm_cap_exceeded for a
        # human/compliance workflow (same discipline as India's
        # wage_deduction_cap_exceeded). While ytd_whm_earnings_before is
        # None (every employee until wired), behavior is byte-for-byte
        # identical to before this change — method reports
        # "FLAT_RATE_NO_YTD_CAP", exactly as it always has.
        rate = resolve_jurisdiction_parameter(
            ctx.rate_map,
            "whm_no_tfn_rate" if ctx.au_tfn_status == "NOT_PROVIDED" else "whm_rate",
            _AU_WHM_NO_TFN_RATE if ctx.au_tfn_status == "NOT_PROVIDED" else _AU_WHM_RATE,
            side="employee", country="AU",
        )
        earnings = _au_floor_dollars(period_gross)
        withholding = _au_floor_dollars(earnings * rate / Decimal("100"))
        trace = {
            "scale": scale, "rate_pct": rate,
            "earnings_floored": earnings, "withholding": withholding,
        }
        if ctx.ytd_whm_earnings_before is not None:
            ytd_whm_earnings_after = ctx.ytd_whm_earnings_before + earnings
            whm_cap_exceeded = ytd_whm_earnings_after > _AU_WHM_CAP_THRESHOLD
            trace.update(
                method="FLAT_RATE_CAP_EXCEEDED_NEEDS_REVIEW" if whm_cap_exceeded else "FLAT_RATE_YTD_TRACKED",
                whm_cap_threshold=_AU_WHM_CAP_THRESHOLD,
                ytd_whm_earnings_before=ctx.ytd_whm_earnings_before,
                ytd_whm_earnings_after=ytd_whm_earnings_after,
                whm_cap_exceeded=whm_cap_exceeded,
            )
        else:
            trace["method"] = "FLAT_RATE_NO_YTD_CAP"
        return withholding, trace

    x = _au_weekly_equivalent(period_gross, ctx.pay_frequency)
    band = _resolve_au_coefficient_band(x, scale, "AU_PAYG_COEFFICIENT", ctx.slabs)
    if band is None:
        _logger.warning("[au-payg-unconfigured] no AU_PAYG_COEFFICIENT band configured for %s at x=%s", scale, x)
        return Decimal("0"), {"scale": scale, "method": "COEFFICIENT_BAND", "weekly_equivalent_x": x, "band_configured": False}

    weekly_withholding = _apply_au_coefficient_formula(x, band)
    period_withholding = _au_convert_weekly_to_period(weekly_withholding, ctx.pay_frequency)
    pre_variation_period_withholding = period_withholding

    # §14's ATO-authorised withholding variation — applied only when on
    # file, never inferred.
    if ctx.au_withholding_variation_pct is not None:
        period_withholding = period_withholding * (Decimal("1") + ctx.au_withholding_variation_pct / Decimal("100"))

    period_withholding = _au_round_to_dollar(max(Decimal("0"), period_withholding))

    # §7's own "Extra-pay calendar" — a flat top-up added AFTER ordinary
    # rounding (the document's own table is itself a fixed dollar amount,
    # not a rate), gated on the explicit au_extra_pay_calendar control.
    extra_pay_topup = _resolve_au_extra_pay_withholding(period_gross, ctx.au_extra_pay_calendar, ctx.slabs)
    period_withholding += extra_pay_topup

    trace = {
        "scale": scale, "method": "COEFFICIENT_BAND", "weekly_equivalent_x": x,
        "band_configured": True, "coefficient_a": band.rate_pct, "coefficient_b": band.flat_amount or Decimal("0"),
        "weekly_withholding": weekly_withholding, "period_withholding_pre_variation": pre_variation_period_withholding,
        "withholding_variation_pct": ctx.au_withholding_variation_pct,
        "extra_pay_calendar": ctx.au_extra_pay_calendar, "extra_pay_topup": extra_pay_topup,
        "final_withholding": period_withholding,
    }
    return period_withholding, trace


def _resolve_au_extra_pay_withholding(period_gross: Decimal, calendar: str, slabs) -> Decimal:
    """§7's own "Extra-pay calendar" table — a flat top-up added to the
    ordinary Schedule 1 result, looked up by the ACTUAL period earnings
    (the pay-frequency-native gross the document's own table is
    expressed in, e.g. weekly $875-$2,574 for 53_WEEK), never the
    Schedule 1 weekly-x conversion. Returns $0 (never a guess) when
    `calendar` is unset or no matching AU_EXTRA_PAY_WITHHOLDING band is
    configured — same dormancy discipline as the Schedule 1/8 coefficient
    bands. `slabs` rows are filtered by rule_type + filing_status (the
    calendar identifier), reusing flat_amount for the additional
    withholding dollar figure — see models.TaxSlab's own rule_type
    docstring."""
    if not calendar:
        return Decimal("0")
    candidates = [
        s for s in (slabs or [])
        if getattr(s, "rule_type", None) == "AU_EXTRA_PAY_WITHHOLDING" and getattr(s, "filing_status", None) == calendar
    ]
    for slab in sorted(candidates, key=lambda s: s.min_amount):
        upper = slab.max_amount
        if period_gross >= slab.min_amount and (upper is None or period_gross < upper):
            return slab.flat_amount or Decimal("0")
    return Decimal("0")


def _resolve_au_stsl_family(ctx: PayrollContext) -> str:
    """§8's own declaration-state table: "Tax-free threshold claimed OR
    foreign resident" is one coefficient family, sharing the SAME
    au_tax_free_threshold_claimed/au_residency_status fields Schedule 1
    itself uses — not a separate STSL-only declaration."""
    if ctx.au_tax_free_threshold_claimed or ctx.au_residency_status == "FOREIGN_RESIDENT":
        return "STSL_CLAIMED_OR_FOREIGN"
    return "STSL_NOT_CLAIMED"


def _calculate_au_stsl_schedule8(ctx: PayrollContext, period_gross: Decimal) -> tuple:
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
    STSL column — Schedule 8 is a PAYG-style withholding). Returns
    (period_component, trace) — see _calculate_au_payg_schedule1's own
    docstring for the same §25 trace contract (always a dict, never
    None, even on the "no obligation"/"unconfigured" paths)."""
    if ctx.study_loan_plan != "AU_HELP" or not ctx.study_loan_balance or ctx.study_loan_balance <= 0:
        return Decimal("0"), {"applicable": False, "reason": "no AU_HELP study_loan_plan/balance on file"}

    family = _resolve_au_stsl_family(ctx)
    x = _au_weekly_equivalent(period_gross, ctx.pay_frequency)
    band = _resolve_au_coefficient_band(x, family, "AU_STSL_COEFFICIENT", ctx.slabs)
    if band is None:
        _logger.warning("[au-stsl-unconfigured] no AU_STSL_COEFFICIENT band configured for %s at x=%s", family, x)
        return Decimal("0"), {"applicable": True, "family": family, "weekly_equivalent_x": x, "band_configured": False}

    weekly_component = _apply_au_coefficient_formula(x, band)
    period_component = _au_convert_weekly_to_period(weekly_component, ctx.pay_frequency)
    final_component = _au_round_to_dollar(max(Decimal("0"), period_component))
    trace = {
        "applicable": True, "family": family, "weekly_equivalent_x": x, "band_configured": True,
        "coefficient_a": band.rate_pct, "coefficient_b": band.flat_amount or Decimal("0"),
        "weekly_component": weekly_component, "final_component": final_component,
    }
    return final_component, trace


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
        sg_trace = {
            "method": "YTD_CAPPED", "super_cap": super_cap, "employer_rate_pct": super_employer_rate,
            "ytd_qualifying_before": ctx.ytd_sg_qualifying_earnings_before, "mcb_room": room,
            "qualifying_earnings_period_capped": this_period_qualifying_capped,
            "ytd_qualifying_after": ytd_sg_qualifying_earnings_after, "mcb_reached": sg_mcb_reached,
            "employer_pension": employer_pension,
        }
    else:
        # Dormant fallback — current-period-annualized estimate, exactly
        # today's pre-Phase-2 behavior.
        annual_sg_qualifying = sg_qualifying_gross * periods_per_year
        annual_super_base = min(annual_sg_qualifying, super_cap)
        employer_pension = (
            _round2((annual_super_base * (super_employer_rate / 100)) / periods_per_year)
            if super_employer_rate else Decimal("0")
        )
        sg_trace = {
            "method": "ANNUALIZED_ESTIMATE", "super_cap": super_cap, "employer_rate_pct": super_employer_rate,
            "annual_sg_qualifying_estimate": annual_sg_qualifying, "annual_super_base_capped": annual_super_base,
            "employer_pension": employer_pension,
        }

    # Medicare Levy Surcharge — genuinely separate from Medicare Levy
    # proper (embedded in Schedule 1 below). Unrelated to Scale selection.
    mls_threshold = resolve_jurisdiction_parameter(rate_map, "mls_threshold", _AU_MLS_THRESHOLD, country="AU")
    mls_rate = resolve_jurisdiction_parameter(rate_map, "mls_rate", _AU_MLS_RATE, side="employee", country="AU")
    medicare_levy_surcharge = Decimal("0")
    if annual_gross > mls_threshold:
        medicare_levy_surcharge = _round2((annual_gross * mls_rate / Decimal("100")) / periods_per_year)
    mls_trace = {
        "annual_gross": annual_gross, "threshold": mls_threshold, "rate_pct": mls_rate,
        "applied": annual_gross > mls_threshold, "medicare_levy_surcharge": medicare_levy_surcharge,
    }

    tds, payg_trace = _calculate_au_payg_schedule1(ctx, payg_taxable_gross)
    study_loan_deduction, stsl_trace = _calculate_au_stsl_schedule8(ctx, payg_taxable_gross)

    # §5 step 4 tax offsets — LITO/SAPTO(single), Phase 10 2026-09-17 —
    # computed against this period's own annualized gross (see this
    # module's own docstring for why that periodization is an engineering
    # choice, not a fabricated value) and subtracted from Schedule 1's own
    # tds, floored at $0. LITO applies to every resident/unset-residency
    # employee (not foreign residents — the same "no tax-free threshold
    # either" rule Schedule 1 itself already encodes); SAPTO applies only
    # when ctx.au_sapto_category is declared, and only ever resolves to a
    # real figure for "SINGLE" today (see _calculate_au_income_tax_offset
    # for why COUPLE/ILLNESS_SEPARATED_COUPLE stay at $0).
    lito_annual = (
        _calculate_au_income_tax_offset(annual_gross, "AU_LITO_OFFSET", "LITO", ctx.slabs)
        if ctx.au_residency_status != "FOREIGN_RESIDENT" else Decimal("0")
    )
    sapto_annual = (
        _calculate_au_income_tax_offset(annual_gross, "AU_SAPTO_OFFSET", ctx.au_sapto_category, ctx.slabs)
        if ctx.au_sapto_category else Decimal("0")
    )
    total_offset_annual = lito_annual + sapto_annual
    period_offset = _round2(total_offset_annual / periods_per_year) if total_offset_annual else Decimal("0")
    tds_before_offset = tds
    tds = max(Decimal("0"), tds - period_offset)
    offset_trace = {
        "lito_annual": lito_annual, "sapto_annual": sapto_annual, "sapto_category": ctx.au_sapto_category,
        "total_offset_annual": total_offset_annual, "period_offset": period_offset,
        "tds_before_offset": tds_before_offset, "tds_after_offset": tds,
    }

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

    # §18 workers compensation premium — a completely separate employer
    # overlay from state payroll tax above (different rate, different
    # authority, no YTD/telescoping needed since it's a flat rate on
    # this period's own wages, not a threshold-banded annual figure).
    workers_compensation_premium = calculate_au_workers_compensation_premium(ctx, period_gross)
    workers_comp_profile = (ctx.employer_tax_profiles or {}).get("AU_WORKERS_COMP")
    workers_comp_trace = {
        "configured": workers_comp_profile is not None and workers_comp_profile.employer_rate_pct is not None,
        "employer_rate_pct": workers_comp_profile.employer_rate_pct if workers_comp_profile else None,
        "wages": period_gross, "premium": workers_compensation_premium,
    }

    # §25 "Calculation Trace — Minimum Audit Payload" — see models.
    # PayslipItem.au_calculation_trace's own docstring for the schema
    # decision (AU-only JSON column, chosen 2026-09-17). Persisted
    # verbatim by service.add_payslip_item; always a dict, never None,
    # even where a given component genuinely didn't apply this period.
    calculation_trace = _au_trace_json_safe({
        "payg": payg_trace,
        "stsl": stsl_trace,
        "medicare_levy_surcharge": mls_trace,
        "super_guarantee": sg_trace,
        "state_payroll_tax": state_payroll_tax_result["trace"],
        "workers_compensation": workers_comp_trace,
        "tax_offsets": offset_trace,
    })

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
        au_workers_compensation_premium=workers_compensation_premium,
        au_calculation_trace=calculation_trace,
        # WHM Schedule 15 cumulative cap detection — see
        # _calculate_au_payg_schedule1's own docstring. None/False
        # (payg_trace has no such keys) for every non-WHM employee and
        # every WHM employee whose YTD tracking isn't wired yet.
        ytd_whm_earnings_after=payg_trace.get("ytd_whm_earnings_after"),
        au_whm_cap_exceeded=payg_trace.get("whm_cap_exceeded", False),
    )


# ── Special PAYG Schedules (§9 Routing Matrix, §13 caps) — Phase 3 ───────
# AU-D11 ("special payments are explicit... ordinary Scale 1/2 is not
# used as fallback") and §9's own instruction apply to every one of these
# — this section deliberately routes each special-payment TYPE to its own
# named schedule rather than ever running it through _calculate_au_payg_
# schedule1. Two calculators here are REAL, complete implementations
# because §13 gives their actual figures/formula in full: the ETP cap
# classification and the genuine-redundancy tax-free component. Every
# other schedule in §9's table (2/4/5/12/13) requires a coefficient/
# rate/method the source document names but never actually gives a
# number or formula for — those raise AuScheduleNotYetImplementedError
# rather than fabricating a plausible-looking withholding amount. (WHM's
# own Scale is resolved — see the SCALE_WHM branch in
# _calculate_au_payg_schedule1 above. Schedules 3 and 6 are resolved too
# — see calculate_au_schedule3_entertainer_withholding/calculate_au_
# schedule6_annuity_withholding below, which bypass this section's own
# generic dispatcher entirely since their real inputs don't fit it.)

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


def _resolve_au_schedule3_family(tax_free_threshold_claimed: bool) -> str:
    return "SCHEDULE3_THRESHOLD_CLAIMED" if tax_free_threshold_claimed else "SCHEDULE3_NO_THRESHOLD"


def _au_schedule3_foreign_resident_weekly_tax(weekly_earnings: Decimal) -> Decimal:
    """Schedule 3's own foreign-resident scale (real ATO-published weekly
    bands, resolved 2026-09-17): 30% to $2,595; $779 + 37% over $2,595 to
    $3,652; $1,170 + 45% over $3,652. A standard marginal structure — the
    given base amounts ($779/$1,170) match what summing 30%/37% from $0
    independently produces (2,595*30%=$778.50, +391.09 to $3,652=
    $1,169.59), confirming this is the ordinary cumulative-bracket shape,
    not a separate formula. Implemented as a small dedicated function
    rather than routing through the generic slab-based _calculate_
    annual_tax, since this is a hardcoded, government-fixed weekly scale
    (never configurable per org/pack), same treatment as the ETP caps
    above."""
    if weekly_earnings <= _AU_SCHEDULE3_FR_THRESHOLD1:
        return weekly_earnings * _AU_SCHEDULE3_FR_RATE1 / Decimal("100")
    if weekly_earnings <= _AU_SCHEDULE3_FR_THRESHOLD2:
        return _AU_SCHEDULE3_FR_BASE2 + (weekly_earnings - _AU_SCHEDULE3_FR_THRESHOLD1) * _AU_SCHEDULE3_FR_RATE2 / Decimal("100")
    return _AU_SCHEDULE3_FR_BASE3 + (weekly_earnings - _AU_SCHEDULE3_FR_THRESHOLD2) * _AU_SCHEDULE3_FR_RATE3 / Decimal("100")


def calculate_au_schedule3_entertainer_withholding(
    per_performance_earnings: Decimal, performances_per_week: int, performances_per_day: int,
    tfn_status: str, residency_status: str, tax_free_threshold_claimed: bool, slabs: list,
) -> Decimal:
    """Schedule 3 (NAT 1023) — actors/variety artists/other entertainers,
    resolved 2026-09-17 (real ATO-published coefficients for payments
    from 1 July 2026, cross-checked for internal consistency: its own
    no-TFN rates, 47% resident / 45% foreign resident, exactly match
    Schedule 1 Scale 4's already-confirmed rates in this codebase —
    _AU_PAYG_SCALE4_RESIDENT_RATE/_AU_PAYG_SCALE4_NONRESIDENT_RATE,
    reused directly rather than duplicated).

    Bypasses calculate_au_special_payment_withholding's generic
    (payment_type, amount) dispatcher entirely — same precedent as ETP/
    genuine-redundancy above, since this schedule's real inputs (per-
    performance earnings, performances/week, performances/day,
    declarations) don't fit a single `amount` parameter.

    Method (§9, verbatim from the ATO's own instructions): x =
    (per-performance earnings x performances/week) + $0.99 -> resolve the
    coefficient band for x -> apply y = a*x - b, round to nearest dollar
    -> divide by performances/week -> multiply by performances/day ->
    round to nearest dollar. No-TFN and foreign-resident cases skip the
    coefficient-band step entirely (flat rate / own marginal scale)."""
    if tfn_status == "NOT_PROVIDED":
        is_resident = residency_status != "FOREIGN_RESIDENT"
        rate = _AU_PAYG_SCALE4_RESIDENT_RATE if is_resident else _AU_PAYG_SCALE4_NONRESIDENT_RATE
        per_performance_withholding = _au_floor_dollars(per_performance_earnings * rate / Decimal("100"))
        return per_performance_withholding * Decimal(performances_per_day)

    if residency_status == "FOREIGN_RESIDENT":
        weekly_earnings = per_performance_earnings * Decimal(performances_per_week)
        weekly_withholding = _au_schedule3_foreign_resident_weekly_tax(weekly_earnings)
        per_performance_withholding = _au_round_to_dollar(weekly_withholding / Decimal(performances_per_week))
        return per_performance_withholding * Decimal(performances_per_day)

    family = _resolve_au_schedule3_family(tax_free_threshold_claimed)
    x = (per_performance_earnings * Decimal(performances_per_week)) + Decimal("0.99")
    band = _resolve_au_coefficient_band(x, family, "AU_SCHEDULE3_COEFFICIENT", slabs)
    if band is None:
        _logger.warning("[au-schedule3-unconfigured] no AU_SCHEDULE3_COEFFICIENT band configured for %s at x=%s", family, x)
        return Decimal("0")
    weekly_withholding = _apply_au_coefficient_formula(x, band)
    per_performance_withholding = _au_round_to_dollar(weekly_withholding / Decimal(performances_per_week))
    return per_performance_withholding * Decimal(performances_per_day)


def calculate_au_schedule6_annuity_withholding(ctx: PayrollContext, gross_payment: Decimal, deductible_amount: Decimal) -> tuple:
    """Schedule 6 (NAT 3350) — annuities, resolved 2026-09-17. Confirmed
    off the ATO's own page: this is NOT its own rate table at all — it is
    a pre-processing step. Subtract the annuity's own "deductible amount"
    (the tax-free component, spread evenly across the year's
    instalments — the caller's own responsibility to compute; this
    function takes it as a given, per-instalment figure) from the gross
    payment, then run the remainder through the ordinary Schedule 1
    machinery exactly as if it were regular pay (§5's own Core
    Calculation Contract, including the SAPTO-adjusted Scale 5/6 bands
    when the recipient is SAPTO-eligible via ctx.au_medicare_levy_
    exemption — no separate SAPTO handling needed here, Schedule 1
    already branches on that field). Bypasses calculate_au_special_
    payment_withholding's generic dispatcher — same reasoning as
    Schedule 3 above."""
    taxable_portion = max(Decimal("0"), gross_payment - deductible_amount)
    return _calculate_au_payg_schedule1(ctx, taxable_portion)


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


def _au_apportioned_national_surcharge(
    wages: Decimal, national_wages_ytd_before: Decimal | None, rate_map: dict,
    tier1_rate_default: Decimal, tier2_rate_default: Decimal,
    tier1_param: str, tier2_param: str,
) -> Decimal:
    """VIC/QLD national-payroll-banded surcharges (§17 follow-up).
    REVISED 2026-09-17 (was a flat-rate-once-a-national-threshold-is-
    crossed shape until this revision — see git history for that
    version): both SRO Victoria and QRO independently describe the
    surcharge threshold itself as APPORTIONED by (this state's wages ÷
    national wages) — the exact same "wages-dependent apportioned
    threshold" shape this module's own base QLD/WA/VIC deductions
    already use (_au_linear_taper_deduction), not a fabricated new
    mechanic. Marginal, two-tier: tier1_rate applies to wages between the
    apportioned tier1 and tier2 thresholds; tier2_rate applies
    ADDITIONALLY (stacked) only to wages above the apportioned tier2
    threshold — the most literal reading of "an additional X% on the
    portion above $100m."

    NOT independently verified against a real numeric worked example
    specific to this surcharge (unlike SA's own §17 fix, verified against
    a real RevenueSA worked example) — QRO/SRO both state the formula in
    words, but neither publishes a numbers-in-numbers-out example for the
    $10m/$100m tiers themselves (only for the ordinary, non-surcharge
    threshold). Flagged for review before relying on this for a real
    surcharge liability. Returns $0 (never a guess) when the national
    accumulator isn't wired — same dormancy discipline as every other AU
    YTD field."""
    if not national_wages_ytd_before:
        return Decimal("0")
    tier1_threshold = resolve_jurisdiction_parameter(rate_map, "national_surcharge_tier1_threshold", _AU_NATIONAL_SURCHARGE_TIER1_THRESHOLD, country="AU")
    tier2_threshold = resolve_jurisdiction_parameter(rate_map, "national_surcharge_tier2_threshold", _AU_NATIONAL_SURCHARGE_TIER2_THRESHOLD, country="AU")
    tier1_rate = resolve_jurisdiction_parameter(rate_map, tier1_param, tier1_rate_default, side="employer", country="AU")
    tier2_rate = resolve_jurisdiction_parameter(rate_map, tier2_param, tier2_rate_default, side="employer", country="AU")
    wage_ratio = wages / national_wages_ytd_before
    apportioned_tier1 = tier1_threshold * wage_ratio
    apportioned_tier2 = tier2_threshold * wage_ratio
    tier1_band_wages = max(Decimal("0"), min(wages, apportioned_tier2) - apportioned_tier1)
    tier2_band_wages = max(Decimal("0"), wages - apportioned_tier2)
    # "An additional X% on the portion above $100m (so Y% total in that
    # top band)" — the base tier1_rate continues to apply in the top band
    # too; tier2_rate stacks on top of it there, it does not replace it.
    return tier1_band_wages * tier1_rate / Decimal("100") + tier2_band_wages * (tier1_rate + tier2_rate) / Decimal("100")


def _au_qld_annual_payroll_tax(wages: Decimal, rate_map: dict, national_wages_ytd_before: Decimal | None = None) -> Decimal:
    """§17: deduction reduces $1 per $7 above $1.3m threshold, zero at
    $10.4m; rate itself is chosen by total wages (4.75% at/below $6.5m,
    4.95% above) — a flat rate on the whole excess, not a marginal split.
    Plus the QLD Mental Health Levy surcharge (resolved 2026-09-17,
    revised same day to an apportioned-threshold shape once SRO/QRO
    confirmed it): a marginal, wages-apportioned surcharge on QLD's own
    taxable wages once NATIONAL wages cross $10m/$100m — see
    _au_apportioned_national_surcharge."""
    threshold = resolve_jurisdiction_parameter(rate_map, "qld_pt_threshold", _AU_QLD_PT_THRESHOLD, country="AU")
    upper = resolve_jurisdiction_parameter(rate_map, "qld_pt_upper_threshold", _AU_QLD_PT_UPPER_THRESHOLD, country="AU")
    rate_low = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_low", _AU_QLD_PT_RATE_LOW, side="employer", country="AU")
    rate_high = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_high", _AU_QLD_PT_RATE_HIGH, side="employer", country="AU")
    rate_switch = resolve_jurisdiction_parameter(rate_map, "qld_pt_rate_switch", _AU_QLD_PT_RATE_SWITCH, country="AU")
    deduction = _au_linear_taper_deduction(wages, threshold, threshold, Decimal("1") / Decimal("7"), upper)
    rate = rate_high if wages > rate_switch else rate_low
    surcharge = _au_apportioned_national_surcharge(
        wages, national_wages_ytd_before, rate_map, _AU_QLD_SURCHARGE_TIER1_RATE, _AU_QLD_SURCHARGE_TIER2_RATE,
        "qld_surcharge_tier1_rate", "qld_surcharge_tier2_rate",
    )
    return max(Decimal("0"), wages - deduction) * rate / Decimal("100") + surcharge


def _au_vic_annual_payroll_tax(wages: Decimal, rate_map: dict, is_regional: bool, national_wages_ytd_before: Decimal | None = None) -> Decimal:
    """§17: standard $1m deduction, phased out at a linear rate between
    $3m-$5m Australian wages (zero above $5m); regional employers get a
    reduced rate instead of the standard one (§AU-D10 employer overlay,
    read from CompanyComplianceDetails.au_payroll_tax_regional_status).
    Plus the stacked Mental Health and Wellbeing Levy + COVID-19 Debt
    Temporary Surcharge (resolved 2026-09-17, combined into one pair of
    rates since they share thresholds/mechanics; revised same day to an
    apportioned-threshold shape once SRO/QRO confirmed it): a marginal,
    wages-apportioned surcharge on VIC's own taxable wages once NATIONAL
    wages cross $10m/$100m — see _au_apportioned_national_surcharge."""
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
    surcharge = _au_apportioned_national_surcharge(
        wages, national_wages_ytd_before, rate_map, _AU_VIC_SURCHARGE_TIER1_RATE, _AU_VIC_SURCHARGE_TIER2_RATE,
        "vic_surcharge_tier1_rate", "vic_surcharge_tier2_rate",
    )
    return max(Decimal("0"), wages - deduction) * rate / Decimal("100") + surcharge


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
    """§17 SOURCE LOCK — RESOLVED 2026-09-17: RevenueSA's own published
    structure (revenuesa.sa.gov.au) confirms the $1.5m-$1.7m band uses a
    straight-line reduced RATE (not a separate deduction): rate = 4.95% x
    (wages - $1.5m) / $200,000, applied directly to total wages — the
    same "flat rate on total wages, no deduction" shape this function
    already used for the >$1.7m band, just with a wages-dependent rate
    instead of the flat 4.95%. Independently verified against a real
    RevenueSA worked example (Tiny Pty Ltd, $1,560,000 wages -> 1.48%
    rate): this formula predicts 4.95% x (60,000/200,000) = 1.485%,
    matching within rounding. Below $1.5m is genuinely $0 (not a gap);
    above $1.7m is the flat 4.95% the document already gave.

    SCOPE NOTE (not fabricated, but not yet wired): RevenueSA's Guide to
    Legislation also describes a SEPARATE $600,000 maximum deduction
    mechanism, pro-rated for group membership/part-year/interstate wages
    — that pro-ration needs its own SA-only-vs-Australia-wide wage split
    on PayrollContext, a genuinely separate piece of work from unblocking
    this specific reduced-rate band (which is now real, ATO/RevenueSA-
    sourced data, not an approximation). Flagged for a follow-up pass,
    not silently dropped."""
    lower = resolve_jurisdiction_parameter(rate_map, "sa_pt_lower_threshold", _AU_SA_PT_LOWER_THRESHOLD, country="AU")
    upper = resolve_jurisdiction_parameter(rate_map, "sa_pt_upper_threshold", _AU_SA_PT_UPPER_THRESHOLD, country="AU")
    rate = resolve_jurisdiction_parameter(rate_map, "sa_pt_rate", _AU_SA_PT_RATE, side="employer", country="AU")
    if wages <= lower:
        return Decimal("0")
    if wages < upper:
        reduced_rate = rate * (wages - lower) / (upper - lower)
        return wages * reduced_rate / Decimal("100")
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
    "VIC": lambda wages, ctx: _au_vic_annual_payroll_tax(
        wages, ctx.rate_map, ctx.au_payroll_tax_regional_status == "REGIONAL", ctx.au_national_taxable_wages_ytd_before,
    ),
    "QLD": lambda wages, ctx: _au_qld_annual_payroll_tax(wages, ctx.rate_map, ctx.au_national_taxable_wages_ytd_before),
    "WA": lambda wages, ctx: _au_wa_annual_payroll_tax(wages, ctx.rate_map),
    "SA": lambda wages, ctx: _au_sa_annual_payroll_tax(wages, ctx.rate_map),
    "TAS": lambda wages, ctx: _au_bracket_table_annual_payroll_tax(wages, ctx.state_slabs),
    "ACT": lambda wages, ctx: _au_bracket_table_annual_payroll_tax(wages, ctx.state_slabs),
    "NT": lambda wages, ctx: _au_nt_annual_payroll_tax(wages, ctx.rate_map),
}


def calculate_au_workers_compensation_premium(ctx: PayrollContext, wages: Decimal) -> Decimal:
    """§18: workers compensation premium — a tenant-specific, agency-
    assigned rate (state scheme + industry classification + experience/
    claims history + insurer/authority notice), resolved from
    ctx.employer_tax_profiles["AU_WORKERS_COMP"] exactly like US SUI
    resolves from ctx.employer_tax_profiles["SUI"] (see
    engine/countries/us.py's own sui_profile handling) — never a
    statutory default, since §18's own table explicitly says premiums
    "depend on state scheme, industry classification, wages, experience/
    claims and insurer/authority notice," not a jurisdiction-wide rate.
    Zero when no profile is configured — the correct, honest answer when
    an org hasn't entered its real agency-issued rate yet, never an
    inferred/guessed premium. Employer-liability-only (AU-D05's own
    contract, same as calculate_au_state_payroll_tax) — never touches
    employee net pay."""
    profile = (ctx.employer_tax_profiles or {}).get("AU_WORKERS_COMP")
    if profile is None or profile.employer_rate_pct is None:
        return Decimal("0")
    return _round2(wages * profile.employer_rate_pct / Decimal("100"))


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

    Cross-employer group/interstate wage aggregation (§AU-D07) is now
    wired — see service.py's _au_org_payroll_tax_read_inputs, which sums
    ctx.au_state_payroll_tax_ytd_remuneration_before across every org
    sharing this org's connected_group_code when
    _CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES includes "AU" (this function
    itself is unaffected either way — it only ever reads whatever
    ytd_remuneration_before value the caller resolved). The §18 charity/
    public-benefit exemption (ctx.au_payroll_tax_charity_exempt) is
    checked here too, suppressing liability to $0 while the wage
    accumulator keeps running underneath (this also correctly suppresses
    the VIC/QLD national surcharges below, computed as part of the SAME
    annual_fn_factory call this exemption short-circuits). VIC/QLD's
    national-payroll-banded surcharges were resolved 2026-09-17 — see
    _au_national_surcharge_rate. NOT yet wired (documented, not silently
    dropped): industry rebates (§18) — no computable rebate formula/
    window rule is given anywhere in the source document, unlike the
    exemption flag above, which only ever gates an EXISTING formula
    rather than needing a new one."""
    state = (ctx.work_state or "").strip().upper()
    annual_fn_factory = _AU_STATE_PAYROLL_TAX_ANNUAL_FN.get(state)
    if annual_fn_factory is None or ctx.au_state_payroll_tax_ytd_remuneration_before is None:
        return {
            "employer_payroll_tax": Decimal("0"), "au_state_payroll_tax_ytd_remuneration_after": None,
            "trace": {"state": state or None, "applicable": False, "reason": "state not one of the 8 supported jurisdictions, or no org-level accumulator wired"},
        }

    if ctx.au_payroll_tax_charity_exempt:
        # §18 charity/public-benefit exemption — liability suppressed to
        # $0, but the YTD wage accumulator keeps accruing underneath (see
        # models.CompanyComplianceDetails.au_payroll_tax_charity_exempt's
        # own docstring) so a later loss of exemption starts from the
        # correct cumulative-wages baseline rather than zero.
        return {
            "employer_payroll_tax": Decimal("0"),
            "au_state_payroll_tax_ytd_remuneration_after": ctx.au_state_payroll_tax_ytd_remuneration_before + ctx.gross,
            "trace": {"state": state, "applicable": True, "charity_exempt": True, "employer_payroll_tax": Decimal("0")},
        }

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
        return {
            "employer_payroll_tax": Decimal("0"), "au_state_payroll_tax_ytd_remuneration_after": None,
            "trace": {"state": state, "applicable": True, "charity_exempt": False, "unimplemented_schedule": exc.case},
        }

    ytd_after = ctx.au_state_payroll_tax_ytd_remuneration_before + ctx.gross
    return {
        "employer_payroll_tax": period_amount, "au_state_payroll_tax_ytd_remuneration_after": ytd_after,
        "trace": {
            "state": state, "applicable": True, "charity_exempt": False,
            "ytd_remuneration_before": ctx.au_state_payroll_tax_ytd_remuneration_before,
            "ytd_remuneration_after": ytd_after, "employer_payroll_tax": period_amount,
        },
    }


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

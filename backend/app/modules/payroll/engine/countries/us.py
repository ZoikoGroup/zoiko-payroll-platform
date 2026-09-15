"""
modules/payroll/engine/countries/us.py
-----------------------------------------
US: Social Security + Medicare + Federal Income Tax. Moved verbatim out
of engine/standard.py's _calc_us.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year, _calculate_annual_tax, resolve_jurisdiction_parameter,
    _US_STATE_TAX_ENABLED_STATES, _US_STATE_PROGRAM_ENABLED_STATES,
    _US_TAXABILITY_MATRIX_ENABLED_COUNTRIES,
)
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change. See that file for
# the provenance comments on each (filing-status thresholds, FUTA credit
# convention, etc.).
from app.modules.payroll.hardcoded_defaults import (
    _US_STANDARD_DEDUCTION, _US_SOCIAL_SECURITY_WAGE_BASE, _US_SOCIAL_SECURITY_RATE,
    _US_MEDICARE_RATE, _US_MEDICARE_ADDITIONAL_RATE, _US_MEDICARE_ADDL_THRESHOLD_DEFAULTS,
    _US_MEDICARE_ADDITIONAL_THRESHOLD, _US_FUTA_RATE, _US_FUTA_WAGE_BASE, _US_FUTA_CREDIT_PCT,
    _US_CT_WITHHOLDING_TABLES, _US_WI_WITHHOLDING_PARAMS, _US_W4_PRE_2020_ALLOWANCE_AMOUNT,
    _US_OR_WITHHOLDING_PARAMS, _US_ME_WITHHOLDING_PARAMS,
)


# ── Wisconsin: continuous deduction phase-out ────────────────────────────
# (ZP-TAX-US-2026-001 §4 / WI DOR Publication W-166, gap-closure Phase 8,
# 2026-09-13). Standalone, like Connecticut, because the deduction step
# is a continuous linear phase-out (not a bracket lookup) — but far
# simpler than CT's 5-table system: one phase-out, then the SAME 4-band
# marginal table for every filing status. Verified by hand against
# W-166's own two worked examples before enabling (Single $18,200/yr:
# deduction $6,651.60, matches exactly; Married $26,000/yr: deduction
# $9,406.40, matches exactly) — this function's own $400/exemption
# omission is the only difference from the source's final dollar figure,
# consistent with this whole build's "no per-employee count field"
# pattern.
def _wi_deduction(annual_salary, is_married: bool, rate_map=None):
    # DB-editable (gap-closure Plan Phase 3, 2026-09-14): each of these 8
    # scalar parameters is now resolved through resolve_jurisdiction_
    # parameter — a Super-Admin-configured ContributionRate row (any of
    # the component_keys below) overrides the literal 2026 W-166 figure,
    # same "governed like everything else" convention every other US
    # parameter in this file already uses. No configured row (every
    # employer today) reproduces the exact prior hardcoded behavior,
    # byte-for-byte. The bracket table itself is NOT included here — it's
    # already a plain marginal bracket sum (see _ct_table_b_tax), so it
    # could be represented as ordinary TaxSlab rows in a future pass;
    # only the phase-out CONSTANTS were genuinely inaccessible before.
    p = _US_WI_WITHHOLDING_PARAMS
    if is_married:
        threshold = resolve_jurisdiction_parameter(rate_map, "wi_married_thresh", p["married_threshold"], country="US")
        zero_point = resolve_jurisdiction_parameter(rate_map, "wi_married_zero_pt", p["married_zero_point"], country="US")
        max_deduction = resolve_jurisdiction_parameter(rate_map, "wi_married_ded_max", p["married_deduction_max"], country="US")
        slope = resolve_jurisdiction_parameter(rate_map, "wi_married_slope", p["married_slope"], country="US")
    else:
        threshold = resolve_jurisdiction_parameter(rate_map, "wi_single_thresh", p["single_threshold"], country="US")
        zero_point = resolve_jurisdiction_parameter(rate_map, "wi_single_zero_pt", p["single_zero_point"], country="US")
        max_deduction = resolve_jurisdiction_parameter(rate_map, "wi_single_ded_max", p["single_deduction_max"], country="US")
        slope = resolve_jurisdiction_parameter(rate_map, "wi_single_slope", p["single_slope"], country="US")
    if annual_salary < threshold:
        return max_deduction
    if annual_salary >= zero_point:
        return Decimal("0")
    return max(Decimal("0"), max_deduction - slope * (annual_salary - threshold))


def _calculate_wi_annual_tax(annual_salary, filing_status, rate_map=None):
    is_married = filing_status == "MFJ"
    taxable = max(Decimal("0"), annual_salary - _wi_deduction(annual_salary, is_married, rate_map=rate_map))
    return _ct_table_b_tax(taxable, _US_WI_WITHHOLDING_PARAMS["brackets"])


# ── Oregon: computer formula method ──────────────────────────────────
# (Production-Readiness Plan Phase 4, 2026-09-15 — Oregon DOR Pub.
# 150-206-436). Genuinely bespoke, not a bracket-sum-plus-flat-deduction
# state like the generic TaxSlab path handles: BASE = wages - a
# federal-tax-withheld subtraction (capped, and phased down to $0 for
# high earners) - a flat standard deduction, then a 4-band table that
# differs by BOTH filing status and whether annual wages are under/over
# $50,000, with the personal exemption credit subtracted AFTER the
# bracket lookup. See _US_OR_WITHHOLDING_PARAMS's own docstring for the
# three internal inconsistencies in Oregon's own published PDF this
# module resolves, and for why allowances are not modeled (no
# Oregon-specific allowance field exists — same documented gap
# _wi_deduction already has for its own per-exemption adjustment).
def _or_lookup_phaseout(wages, schedule):
    """Oregon's own phase-out tables are phrased "wages >= floor and <
    ceiling" — a different boundary convention from _ct_lookup_band's
    "floor < x <= ceiling" (CT's own source uses that phrasing instead),
    so this is its own small lookup rather than reusing that helper."""
    for floor, ceiling, value in schedule:
        if ceiling is None:
            if wages >= floor:
                return value
        elif floor <= wages < ceiling:
            return value
    return schedule[-1][2]


def _calculate_or_annual_tax(annual_wages, annual_federal_tax, filing_status, rate_map=None):
    rate_map = rate_map or {}
    p = _US_OR_WITHHOLDING_PARAMS
    is_married = filing_status == "MFJ"
    standard_deduction = resolve_jurisdiction_parameter(
        rate_map, "or_married_std_ded" if is_married else "or_single_std_ded",
        p["married_standard_deduction"] if is_married else p["single_standard_deduction"], country="US",
    )
    phaseout_schedule = p["married_fed_subtraction_phaseout"] if is_married else p["single_fed_subtraction_phaseout"]
    fed_subtraction_cap = _or_lookup_phaseout(annual_wages, phaseout_schedule)
    fed_subtraction = min(max(Decimal("0"), annual_federal_tax), fed_subtraction_cap)
    base = max(Decimal("0"), annual_wages - fed_subtraction - standard_deduction)

    if annual_wages >= Decimal("50000"):
        brackets = p["married_brackets_50k_plus"] if is_married else p["single_brackets_50k_plus"]
    else:
        brackets = p["married_brackets_under_50k"] if is_married else p["single_brackets_under_50k"]
    return max(Decimal("0"), _ct_table_b_tax(base, brackets))


# ── Maine: withholding-specific standard deduction phase-out ────────────
# (Production-Readiness Plan Phase 4, 2026-09-15 — Maine Revenue
# Services, 2026 percentage method). Maine's bracket rates (5.80% /
# 6.75% / 7.15%) ARE a plain marginal table — entered as real, DB-
# editable TaxSlab rows via the Bulk State Tax Import tool, consumed by
# the generic `elif state_slabs:` path exactly like any other state. Only
# the STANDARD DEDUCTION needs this bespoke function: MRS's own 2026
# notice states a flat "$15,300 single / $30,600 married" figure, but
# that is the GENERAL Maine income-tax standard deduction (a filing
# concept) — the WITHHOLDING FORMULA's own Step 3 uses a materially
# different, lower figure that phases out for higher earners. Using the
# flat general figure here would under-withhold every Maine employee.
def _me_standard_deduction_for_status(annual_wages, filing_status):
    p = _US_ME_WITHHOLDING_PARAMS
    is_married = filing_status == "MFJ"
    full = p["married_deduction_full"] if is_married else p["single_deduction_full"]
    full_ceiling = p["married_deduction_full_ceiling"] if is_married else p["single_deduction_full_ceiling"]
    zero_floor = p["married_deduction_zero_floor"] if is_married else p["single_deduction_zero_floor"]
    span = p["married_deduction_phaseout_span"] if is_married else p["single_deduction_phaseout_span"]
    if annual_wages <= full_ceiling:
        return full
    if annual_wages >= zero_floor:
        return Decimal("0")
    # Linear phase-out — MRS's own formula, e.g. married:
    # $27,750 * (354,550 - wages) / 150,000, rounded to 4 decimals.
    return (full * (zero_floor - annual_wages) / span).quantize(Decimal("0.0001"))


# ── Tiered/progressive LOCAL tax ─────────────────────────────────────────
# (Production-Readiness Plan Phase 4, 2026-09-15). LocalityRate's own
# resident_rate_pct/nonresident_rate_pct/flat_amount columns are all
# SINGLE scalars — correct for the overwhelming majority of US localities
# (a flat percentage or a flat LST-style amount), but genuinely wrong for
# the handful that publish their own marginal bracket table: Maryland's
# Anne Arundel and Frederick counties (2026 Comptroller memo, Attachment
# 1), and New York City's own resident tax (NYS-50-T-NYC's "Annual Tax
# Rate Schedule" — identical for Single/Married, only the Table A
# deduction below differs by filing status). Rather than a bespoke
# Python function per locality (the CT/WI/OR pattern above, which only
# makes sense for a handful of STATES), this is one generic mechanism
# any LocalityRate row can opt into via its own `bracket_schedule` JSON
# column — {"SINGLE": {"deduction": N, "brackets": [{"min","max","rate"},
# ...]}, "MFJ": {...}}. `deduction` is a flat pre-bracket subtraction
# (NYC's Table A allowance; 0 for Maryland's two counties, which publish
# no separate local deduction). filing_status "HOH"/"MFJ" both use the
# "MFJ" bucket (Maryland's own "MFJ, HOH, or qualified surviving spouse"
# grouping); everything else (including a missing filing status) falls
# back to "SINGLE" — same "no guess beyond what's on file" convention as
# every other filing-status lookup in this file. Genuinely marginal (each
# tier's rate applies only to the wages within that tier), matching every
# other US bracket table in this codebase — not a single "whichever
# bracket you land in applies to everything" cliff structure.
def _tiered_locality_tax(annual_wages, filing_status, bracket_schedule):
    bucket = "MFJ" if filing_status in ("MFJ", "HOH") else "SINGLE"
    entry = bracket_schedule.get(bucket) or bracket_schedule.get("SINGLE") or {}
    deduction = Decimal(str(entry.get("deduction") or 0))
    taxable = max(Decimal("0"), annual_wages - deduction)
    brackets = entry.get("brackets") or []
    if any("base" in row for row in brackets):
        # A published cumulative "base" figure per bracket (e.g. NYC's own
        # NYS-50-T-NYC Column 5) is honored exactly — the same (floor,
        # ceiling, rate, base) convention _ct_table_b_tax already uses for
        # CT/WI — rather than re-derived from raw rates, which can drift a
        # few cents from the source's own published rounding.
        for row in brackets:
            floor = Decimal(str(row["min"]))
            ceiling = Decimal(str(row["max"])) if row.get("max") is not None else None
            rate = Decimal(str(row["rate"]))
            base = Decimal(str(row.get("base") or 0))
            if ceiling is None:
                if taxable > floor:
                    return base + (taxable - floor) * rate / Decimal("100")
            elif floor < taxable <= ceiling:
                return base + (taxable - floor) * rate / Decimal("100")
        return Decimal("0")
    # No published base figures (e.g. Maryland's own tiered counties,
    # which publish only min/max/rate) — a genuine from-scratch marginal
    # sum across every tier up to `taxable`.
    tax = Decimal("0")
    for row in brackets:
        floor = Decimal(str(row["min"]))
        ceiling = Decimal(str(row["max"])) if row.get("max") is not None else None
        rate = Decimal(str(row["rate"]))
        if taxable <= floor:
            continue
        upper = min(taxable, ceiling) if ceiling is not None else taxable
        tax += (upper - floor) * rate / Decimal("100")
    return tax


# ── Connecticut: CT-W4 Withholding Code calculation ──────────────────────
# (ZP-TAX-US-2026-001 §4 / CT DRS TPG-211, gap-closure Phase 8,
# 2026-09-12). Genuinely NOT a marginal-bracket state — CT's own 16-step
# sequence is: subtract a per-code EXEMPTION (Table A) from annualized
# salary, compute a base tax from Table B (its own floor/ceiling/rate/
# base, used directly rather than re-derived), ADD two more lookups
# (Table C's 2% phase-out add-back, Table D's tax recapture), then
# multiply the whole subtotal by (1 − a Table E credit decimal) that can
# be as high as 0.75 for lower incomes. Deliberately a standalone
# function, not routed through the generic TaxSlab/_calculate_annual_tax
# bracket-sum path at all — that mechanism has no concept of an
# additive-then-multiplicative multi-table calculation like this one.
def _ct_lookup_band(salary, bands):
    """Returns the value for the band where floor < salary <= ceiling (a
    None ceiling means "and up"). Per TPG-211's own column headers: "More
    than [floor], less than or equal to [ceiling]". A salary at or below
    the very first band's floor (e.g. Table E's lookups, which start
    above $0 for every code) returns that first band's own value — safe
    because in every such case the employee's taxable income after the
    Table A exemption is already $0, making this lookup's value
    immaterial to the final result either way."""
    for floor, ceiling, value in bands:
        if ceiling is None:
            if salary > floor:
                return value
        elif floor < salary <= ceiling:
            return value
    return bands[0][2]


def _ct_table_b_tax(taxable, table_b):
    for floor, ceiling, rate, base in table_b:
        if ceiling is None:
            if taxable > floor:
                return base + (taxable - floor) * rate / Decimal("100")
        elif floor < taxable <= ceiling:
            return base + (taxable - floor) * rate / Decimal("100")
    return Decimal("0")


def _calculate_ct_annual_tax(annual_salary, code: str):
    """Returns the full annual CT withholding for this Withholding Code,
    per TPG-211's own 16-step sequence (steps 4-12; annualization/pay-
    period division happen in calculate() below, same as every other
    state)."""
    tables = _US_CT_WITHHOLDING_TABLES.get(code)
    if tables is None:
        return Decimal("0")
    table_c = _US_CT_WITHHOLDING_TABLES["A"]["table_c"] if tables["table_c"] == "SAME_AS_A" else tables["table_c"]
    table_d = _US_CT_WITHHOLDING_TABLES["A"]["table_d"] if tables["table_d"] == "SAME_AS_A" else tables["table_d"]

    exemption = _ct_lookup_band(annual_salary, tables["exemption"])
    taxable = max(Decimal("0"), annual_salary - exemption)
    base_tax = _ct_table_b_tax(taxable, tables["table_b"])
    add_back = _ct_lookup_band(annual_salary, table_c)
    recapture = _ct_lookup_band(annual_salary, table_d)
    subtotal = base_tax + add_back + recapture
    credit_decimal = _ct_lookup_band(annual_salary, tables["table_e"])
    return subtotal * (Decimal("1.00") - credit_decimal)


def _calculate_annual_tax_us(annual_gross: Decimal, slabs, rate_map: dict, filing_status: str | None = None) -> Decimal:
    """`filing_status` (e.g. "SINGLE"/"MFJ"/"MFS"/"HOH"): if Super Admin has
    configured a filing-status-tagged `standard_deduction` ContributionRate
    row for this employee's filing status, it is used (see
    resolve_jurisdiction_parameter/get_contribution_rates — the rate_map
    passed in already reflects the filing-status-preferred row, resolved
    upstream in service.py). No new hardcoded per-filing-status default is
    introduced here: absent a configured row, every filing status falls
    back to the SAME existing _US_STANDARD_DEDUCTION constant as before
    this parameter existed — this is a capability addition, not a change
    in default behavior. `slabs` is filtered by filing_status the same
    way, inside _calculate_annual_tax."""
    standard_deduction = resolve_jurisdiction_parameter(rate_map, "standard_deduction", _US_STANDARD_DEDUCTION, country="US")
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    return _calculate_annual_tax(taxable, slabs, filing_status=filing_status)


# ── Taxability Matrix: per-program wage base (ZP-TAX-US-2026-001 §9.1, ──
# gap-closure Phase 7, 2026-09-12). Reuses the exact same TaxabilityRule-
# backed mechanism canada.py's _resolve_ca_taxability/_calculate_ca_
# program_wages already established for CA — a DIFFERENT default (every
# component counts, i.e. True) unless an admin has explicitly excluded
# it, matching today's single-ctx.gross behavior for every US wage base.
# SUI/state-program employer levies are NOT wired here — each already
# resolves its own base from annual_gross directly and none has a
# documented per-component-differing case; same smaller-follow-up
# scoping decision CA's own Phase 5 made for its employer levies.
def _resolve_us_taxability(component_key: str, rules: dict) -> bool:
    if component_key in rules:
        return rules[component_key]
    return True


def _calculate_us_program_wages(ctx: PayrollContext, tax_component: str) -> Decimal:
    """Per-program (federal_income_tax/social_security/medicare/futa/
    state_income_tax) wage base for the CURRENT pay period — which of the
    employee's own named salary components count toward THIS specific
    program, independently of every other one. `rules` comes from
    ctx.us_taxability_rules[tax_component] (service.
    get_us_taxability_rules_bundle). Every dollar of ctx.gross lands in
    exactly one bucket — named_allowances is whatever remains of gross
    after the other five — same "no dollar double-counted or dropped"
    contract canada.py's own _calculate_ca_program_wages already uses."""
    rules = (ctx.us_taxability_rules or {}).get(tax_component, {})
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
        if _resolve_us_taxability(key, rules):
            included += amount
    return included


def calculate(ctx: PayrollContext) -> dict:
    """US: Social Security + Medicare + Federal Income Tax + FUTA +
    (where a state-scoped TaxSlab set exists) State Income Tax.

    Employee/employer Social Security and Medicare rates come from
    rate_map's "social-security"/"medicare" ContributionRate rows rather
    than being ignored in favour of a hardcoded module constant — editing
    these rates via Compliance has a real calculation effect."""
    rate_map = ctx.rate_map
    # Pay-frequency awareness (ZP-TAX-US-2026-001, gap-closure Plan Phase
    # 2c): previously hardcoded to MONTHS_PER_YEAR regardless of the
    # employee's actual pay_frequency (UK/Canada already vary by this via
    # the same resolve_periods_per_year helper). ctx.pay_frequency
    # defaults to "Monthly", so periods_per_year == MONTHS_PER_YEAR by
    # construction for every employee who has never set a different
    # frequency — completely unaffected. Only a Weekly/BiWeekly/
    # SemiMonthly/etc. employee's annualization actually changes.
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    annual_gross = ctx.gross * periods_per_year

    # Taxability Matrix (ZP-TAX-US-2026-001 §9.1, gap-closure Phase 7):
    # per-program wage base, replacing the single `annual_gross` figure
    # below for the five programs it covers (Social Security, Medicare,
    # FUTA, federal income tax, state income tax). While OFF, or for any
    # program with no TaxabilityRule override configured, these are
    # BYTE-FOR-BYTE identical to annual_gross — see
    # _calculate_us_program_wages's own docstring.
    _us_taxability_on = "US" in _US_TAXABILITY_MATRIX_ENABLED_COUNTRIES
    annual_ss_gross = (_calculate_us_program_wages(ctx, "social_security") if _us_taxability_on else ctx.gross) * periods_per_year
    annual_medicare_gross = (_calculate_us_program_wages(ctx, "medicare") if _us_taxability_on else ctx.gross) * periods_per_year
    annual_futa_gross = (_calculate_us_program_wages(ctx, "futa") if _us_taxability_on else ctx.gross) * periods_per_year
    annual_federal_taxable_gross = (_calculate_us_program_wages(ctx, "federal_income_tax") if _us_taxability_on else ctx.gross) * periods_per_year
    annual_state_taxable_gross = (_calculate_us_program_wages(ctx, "state_income_tax") if _us_taxability_on else ctx.gross) * periods_per_year

    # Federal income tax (ZP-TAX-US-2026-001 §9.2 Stage D) — computed
    # FIRST among the tax components, immediately after gross/wage-base
    # resolution and before FICA (Stage E), matching the standard's
    # mandated A-B-C-D-E-F-G-H-I-J-K order of operations. Moved here
    # 2026-09-13 (gap-closure Plan Phase 2b) — previously computed dead
    # last in this function (right before the final return), which had
    # no actual calculation impact (nothing in this file has ever
    # depended on federal_income_tax's value), but left the code's own
    # structure silently inverted relative to the standard it implements.
    filing_status = ctx.w4_filing_status
    # Form W-4 Step 2 "Multiple Jobs or Spouse Works" checkbox (ZP-TAX-US-
    # 2026-001 §3.3): a genuinely different, narrower-banded bracket table
    # tagged "<status>_STEP2" in hardcoded_defaults.py (e.g. "SINGLE_STEP2"),
    # not a variant of the standard table applied on top of it. False (every
    # employee before this field existed) is a complete no-op — falls
    # through to the existing filing_status exactly as before. No filing
    # status on file means there is no "_STEP2" tag to build either, so the
    # checkbox is silently ignored rather than raising — same permissive
    # convention every other missing-election field in this engine uses.
    effective_filing_status = f"{filing_status}_STEP2" if (ctx.w4_step2_checkbox and filing_status) else filing_status

    # Federal W-4 §3.4 controls (gap-closure Plan Phase 2d) — each is an
    # independent no-op (None/False/0, every employee before these
    # fields existed) that only changes anything once explicitly entered.
    #
    # Pre-2020 (legacy) allowance: 2026 Pub. 15-T's own literal $4,300/
    # allowance figure, ONLY applied on the legacy form path — a 2020+
    # employee's w4_allowances_claimed (if any) is never read here.
    if ctx.w4_form_vintage == "PRE_2020" and ctx.w4_allowances_claimed:
        annual_federal_taxable_gross = max(
            Decimal("0"),
            annual_federal_taxable_gross - (_US_W4_PRE_2020_ALLOWANCE_AMOUNT * ctx.w4_allowances_claimed),
        )
    # Step 4(a) "other income" — added to taxable wages, already an
    # annual figure per the employee's own W-4 certification.
    if ctx.w4_other_income_annual:
        annual_federal_taxable_gross += ctx.w4_other_income_annual
    # Nonresident alien additional-wage amount (§3.4): the document gives
    # no literal dollar figure at all for this one (only "support it as a
    # configuration value by W-4 vintage and pay frequency") — resolved
    # purely from rate_map, defaulting to $0 (no-op) until Tax Ops enters
    # the real current Pub. 15-T amount, same "never guess" discipline as
    # every other Super-Admin-configurable US parameter. Simplified to a
    # single annual figure rather than a full vintage x frequency table,
    # since no real data exists yet to populate one.
    if ctx.is_nonresident_alien:
        nra_addl_wage_annual = resolve_jurisdiction_parameter(rate_map, "w4_nra_addl_wage_amount", Decimal("0"), country="US")
        annual_federal_taxable_gross += nra_addl_wage_annual

    annual_tax = _calculate_annual_tax_us(annual_federal_taxable_gross, ctx.slabs, rate_map, filing_status=effective_filing_status)
    # Step 3 "claim dependents" credit — the employee's own certified
    # annual dollar amount, subtracted directly from the computed tax
    # (never below $0), not a wage adjustment.
    if ctx.w4_dependents_credit_annual:
        annual_tax = max(Decimal("0"), annual_tax - ctx.w4_dependents_credit_annual)
    federal_income_tax = _round2(annual_tax / periods_per_year)
    # Step 4(c) "extra withholding" — a flat PER-PAY-PERIOD amount added
    # directly to withholding, never annualized/de-annualized.
    if ctx.w4_extra_withholding_per_period:
        federal_income_tax += ctx.w4_extra_withholding_per_period

    ss_rate_employee = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employee", country="US")
    ss_rate_employer = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employer", country="US")
    ss_wage_base = resolve_jurisdiction_parameter(rate_map, "ss_wage_base", _US_SOCIAL_SECURITY_WAGE_BASE, country="US")
    # YTD-aware wage-base cap (ZP-TAX-US-2026-001 §3.1, gap-closure Phase
    # 2a): ctx.ytd_ss_wages_before is None for every employee until BOTH
    # shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES has "US" AND
    # service.py's _load_us_ytd finds a real accumulator row — until
    # then this is the EXACT prior current-period-annualized behavior,
    # byte-for-byte unchanged. When wired, this period's ACTUAL
    # (unannualized) SS-taxable gross is capped against real remaining
    # room in the wage base — same "room = cap - ytd_before" pattern
    # canada.py's CPP/QPP first-layer cap already uses.
    period_ss_gross = annual_ss_gross / periods_per_year
    if ctx.ytd_ss_wages_before is not None:
        ss_room = max(Decimal("0"), ss_wage_base - ctx.ytd_ss_wages_before)
        period_ss_wage = max(Decimal("0"), min(period_ss_gross, ss_room))
        ytd_ss_wages_after = ctx.ytd_ss_wages_before + period_ss_wage
        social_security = _round2(period_ss_wage * ss_rate_employee / Decimal("100"))
        employer_ss = _round2(period_ss_wage * ss_rate_employer / Decimal("100"))
    else:
        annual_ss_wage = min(annual_ss_gross, ss_wage_base)
        social_security = _round2((annual_ss_wage * ss_rate_employee / Decimal("100")) / periods_per_year)
        employer_ss = _round2((annual_ss_wage * ss_rate_employer / Decimal("100")) / periods_per_year)
        ytd_ss_wages_after = None

    medicare_rate_employee = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employee", country="US")
    medicare_rate_employer = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employer", country="US")
    medicare_additional_rate = resolve_jurisdiction_parameter(rate_map, "medicare_additional", _US_MEDICARE_ADDITIONAL_RATE, side="employee", country="US")
    medicare_additional_threshold_default = _US_MEDICARE_ADDL_THRESHOLD_DEFAULTS.get(ctx.w4_filing_status, _US_MEDICARE_ADDITIONAL_THRESHOLD)
    medicare_additional_threshold = resolve_jurisdiction_parameter(rate_map, "medicare_addl_thresh", medicare_additional_threshold_default, country="US")

    # Regular 1.45% Medicare has no wage cap at all (§3.1), so this half is
    # completely unaffected by YTD wiring either way — always the plain
    # per-period calculation.
    medicare = _round2((annual_medicare_gross * medicare_rate_employee / Decimal("100")) / periods_per_year)
    period_medicare_gross = annual_medicare_gross / periods_per_year
    # Additional Medicare is a THRESHOLD, not a cap — once cumulative
    # Medicare wages cross it, every dollar above stays taxed at the
    # extra 0.9% for the rest of the year. Same "room before the line is
    # crossed" shape as CPP2's own "period_gross_over_ympe" (canada.py),
    # just for a threshold instead of a corridor.
    if ctx.ytd_medicare_wages_before is not None:
        room_before_threshold = max(Decimal("0"), medicare_additional_threshold - ctx.ytd_medicare_wages_before)
        period_above_threshold = max(Decimal("0"), period_medicare_gross - room_before_threshold)
        ytd_medicare_wages_after = ctx.ytd_medicare_wages_before + period_medicare_gross
        if period_above_threshold > 0:
            medicare += _round2(period_above_threshold * medicare_additional_rate / Decimal("100"))
    else:
        if annual_medicare_gross > medicare_additional_threshold:
            medicare += _round2(((annual_medicare_gross - medicare_additional_threshold) * medicare_additional_rate / Decimal("100")) / periods_per_year)
        ytd_medicare_wages_after = None
    employer_medicare = _round2((annual_medicare_gross * medicare_rate_employer / Decimal("100")) / periods_per_year)

    # SUI: tenant-specific, agency-assigned rate — resolved from
    # EmployerTaxProfile (get_employer_tax_profiles in service.py), NOT
    # from rate_map/resolve_jurisdiction_parameter, since this is
    # explicitly NOT a discretionary org policy choice (see
    # EmployerTaxProfile's model docstring). Absent a configured profile,
    # employer_sui stays 0 and FUTA computes at its full statutory rate
    # below — no SUI is ever inferred or guessed.
    sui_profile = (ctx.employer_tax_profiles or {}).get("SUI")
    employer_sui = Decimal("0")
    if sui_profile is not None:
        annual_sui_wage = min(annual_gross, sui_profile.taxable_wage_base)
        employer_sui = _round2((annual_sui_wage * sui_profile.employer_rate_pct / Decimal("100")) / periods_per_year)

    futa_rate = resolve_jurisdiction_parameter(rate_map, "futa", _US_FUTA_RATE, side="employer", country="US")
    if sui_profile is not None:
        # Real SUI is being paid for this employer/state (a configured,
        # evidence-backed profile exists) — the standard federal credit
        # applies. futa_credit_red_pct (state-scoped, Super-Admin-
        # configurable — named "_red_" rather than the natural
        # "_reduction_" so it fits payroll_contribution_rates.component_key's
        # VARCHAR(20) limit; same reason AU's super_max_contrib and
        # Canada's basic_personal_amt were shortened. The un-shortened
        # name was never actually storable in the DB, silently breaking
        # this exact "Super-Admin-configurable" claim since it was
        # written — found and fixed as part of the Fallback Removal Fix
        # Plan's P6 readiness check) is how much of the 5.4% credit a
        # credit-reduction state has taken away this tax year — 0 (full
        # credit, ~0.6% effective rate) unless Super Admin has explicitly
        # configured otherwise. No list of "which states are credit-reduced"
        # is hardcoded anywhere — that changes yearly and must come from
        # Tax Operations, not a guess baked into application code.
        futa_credit_pct = resolve_jurisdiction_parameter(rate_map, "futa_credit_pct", _US_FUTA_CREDIT_PCT, country="US")
        futa_credit_reduction_pct = resolve_jurisdiction_parameter(rate_map, "futa_credit_red_pct", Decimal("0"), country="US")
        effective_futa_rate = max(Decimal("0"), futa_rate - futa_credit_pct + futa_credit_reduction_pct)
    else:
        effective_futa_rate = futa_rate
    futa_wage_base = resolve_jurisdiction_parameter(rate_map, "futa_wage_base", _US_FUTA_WAGE_BASE, country="US")
    # Same YTD-aware wage-base cap pattern as Social Security above.
    period_futa_gross = annual_futa_gross / periods_per_year
    if ctx.ytd_futa_wages_before is not None:
        futa_room = max(Decimal("0"), futa_wage_base - ctx.ytd_futa_wages_before)
        period_futa_wage = max(Decimal("0"), min(period_futa_gross, futa_room))
        ytd_futa_wages_after = ctx.ytd_futa_wages_before + period_futa_wage
        employer_futa = _round2(period_futa_wage * effective_futa_rate / Decimal("100"))
    else:
        annual_futa_wage = min(annual_futa_gross, futa_wage_base)
        employer_futa = _round2((annual_futa_wage * effective_futa_rate / Decimal("100")) / periods_per_year)
        ytd_futa_wages_after = None

    # State income tax: ctx.state_slabs is only ever non-empty when the
    # employee's work_state resolved a real state-scoped TaxSlab set
    # (California, New York) — states with no income tax (Texas, Florida)
    # or with no configured slabs correctly resolve to 0 here, never a
    # guess. Federal slabs (ctx.slabs) are never reused as a stand-in.
    #
    # Reciprocity (service.py's _resolve_us_reciprocity): when a valid,
    # certificate-satisfied agreement exists for this employee's resident/
    # work state pair, work-state withholding is suppressed and the
    # RESIDENT state's own config is taxed instead — per the standard's
    # §8.1 step 5. ctx.reciprocity_suppresses_work_state is False (and the
    # resident_state_* fields are empty) for every employee today, since no
    # employee has a distinct residence_state and the ReciprocityRule table
    # is empty until Tax Ops configures a real agreement — this is a
    # complete no-op until both are true.
    if ctx.reciprocity_suppresses_work_state:
        state_slabs = ctx.resident_state_slabs or []
    else:
        state_slabs = ctx.state_slabs or []
    # Only states explicitly added to _US_STATE_TAX_ENABLED_STATES compute
    # real state income tax — every other state's TaxSlab rows (configured
    # or not) are inert here, same additive-per-state convention as every
    # other country's rollout switch in shared.py. Filtering by the slab
    # row's OWN jurisdiction_state (rather than ctx.work_state) means this
    # is correct for both the plain work-state path and the reciprocity
    # resident-state path above, without needing a separate ctx field for
    # "which state actually supplied these slabs".
    state_slabs = [s for s in state_slabs if getattr(s, "jurisdiction_state", None) in _US_STATE_TAX_ENABLED_STATES]
    # The bracket-lookup key defaults to the employee's own federal filing
    # status (today's exact behavior for every state) — but two states'
    # own withholding certificates select brackets by something ELSE
    # entirely, still represented as ordinary TaxSlab.filing_status tags
    # (see hardcoded_defaults._US_STATE_GRADUATED_TAX_RATES["NJ"]/["ND"]'s
    # own comments), so this file substitutes a different key for THOSE
    # two states only, gap-closure Level 2 Batch 4, 2026-09-13:
    #   - New Jersey: Form NJ-W4's own Rate Table letter (A-E), read
    #     directly from ctx.nj_rate_table — an employee with none on file
    #     matches no tagged row and no untagged fallback exists for NJ,
    #     so this naturally resolves to $0, never a guessed table.
    #   - North Dakota: the employee's OWN Form W-4 vintage
    #     (ctx.w4_form_vintage — previously collected but never consumed
    #     anywhere in this engine) selects between ND's two genuinely
    #     different bracket tables; unset/anything other than "PRE_2020"
    #     defaults to the current post-2020 table (the common case for a
    #     new hire today), composited onto filing_status as "_ND2020"/
    #     "_NDPRE2020" — every OTHER state is completely unaffected by
    #     this, since the suffix is only ever appended when
    #     ctx.work_state == "ND".
    state_effective_filing_status = ctx.w4_filing_status
    if ctx.work_state == "NJ":
        state_effective_filing_status = ctx.nj_rate_table
    elif ctx.work_state == "ND" and ctx.w4_filing_status:
        vintage_suffix = "NDPRE2020" if ctx.w4_form_vintage == "PRE_2020" else "ND2020"
        state_effective_filing_status = f"{ctx.w4_filing_status}_{vintage_suffix}"
    # Connecticut (ZP-TAX-US-2026-001 §4/CT DRS TPG-211): genuinely NOT a
    # marginal-bracket state (see _calculate_ct_annual_tax's own
    # docstring) — bypasses the generic TaxSlab path entirely. Gated on
    # BOTH "CT" in the enabled-states set AND a real ct_withholding_code
    # on file; an employee with work_state="CT" but no code resolves to
    # $0, same as any other unconfigured-employee case, never a guessed
    # code. reciprocity_suppresses_work_state is checked defensively
    # (always False for CT today — no reciprocity agreement is configured
    # for it) so a future CT reciprocity agreement would correctly route
    # through the resident-state TaxSlab path below instead.
    if "CT" in _US_STATE_TAX_ENABLED_STATES and ctx.work_state == "CT" \
            and not ctx.reciprocity_suppresses_work_state and ctx.ct_withholding_code:
        annual_state_tax = _calculate_ct_annual_tax(annual_state_taxable_gross, ctx.ct_withholding_code)
    # Wisconsin (ZP-TAX-US-2026-001 §4/WI DOR Publication W-166): the
    # deduction step is a continuous linear phase-out, not a bracket
    # lookup — see _calculate_wi_annual_tax's own docstring. Gated on a
    # real w4_filing_status being on file, same "no guess" convention as
    # every filing-status-dependent lookup in this file — an employee
    # with none on file falls through to the generic TaxSlab path below,
    # which (no WI TaxSlab rows exist — WI is handled entirely here, not
    # via the bracket dict) correctly resolves to $0.
    elif "WI" in _US_STATE_TAX_ENABLED_STATES and ctx.work_state == "WI" \
            and not ctx.reciprocity_suppresses_work_state and ctx.w4_filing_status:
        annual_state_tax = _calculate_wi_annual_tax(annual_state_taxable_gross, ctx.w4_filing_status, rate_map=ctx.state_rate_map)
    # Oregon (ZP-TAX-US-2026-001 §4/OR DOR Pub. 150-206-436): a genuinely
    # bespoke formula (federal-tax subtraction, then deduction, then
    # bracket, then a post-bracket exemption credit) — see
    # _calculate_or_annual_tax's own docstring. Gated the same way as
    # CT/WI: enabled-states set + a real filing status on file, never a
    # guess. `annual_tax` here is the ANNUAL federal tax computed earlier
    # in this same function (post dependents-credit) — the "federal tax
    # withheld" figure Oregon's own formula subtracts.
    elif "OR" in _US_STATE_TAX_ENABLED_STATES and ctx.work_state == "OR" \
            and not ctx.reciprocity_suppresses_work_state and ctx.w4_filing_status:
        annual_state_tax = _calculate_or_annual_tax(
            annual_state_taxable_gross, annual_tax, ctx.w4_filing_status, rate_map=ctx.state_rate_map,
        )
    elif state_slabs:
        # State-level standard deduction/allowance (e.g. Colorado's
        # $11,000 MFJ_OR_QSS / $5,500 other, ZP-TAX-US-2026-001 §10.1) —
        # defaults to 0 (no-op: full annual_gross is taxed) for any state
        # that hasn't configured one, exactly like today's behavior before
        # this parameter existed. Filing-status selection happens the same
        # way federal's standard_deduction already does, one level down:
        # ctx.state_rate_map is resolved with the employee's filing_status
        # already applied (get_state_scoped_config), so this single lookup
        # is filing-status-correct with no extra logic here.
        # Maine (ZP-TAX-US-2026-001 §4/Maine Revenue Services 2026
        # percentage method): the ONLY state whose standard deduction is
        # income-phased-out rather than a flat per-status figure — see
        # _me_standard_deduction_for_status's own docstring for why the
        # generic flat-resolve below would silently under-withhold every
        # ME employee if used instead. The bracket table itself (5.80%/
        # 6.75%/7.15%) is a real, DB-editable TaxSlab table, consumed
        # normally by _calculate_annual_tax just below.
        if "ME" in _US_STATE_TAX_ENABLED_STATES and ctx.work_state == "ME" and ctx.w4_filing_status:
            state_standard_deduction = _me_standard_deduction_for_status(annual_state_taxable_gross, ctx.w4_filing_status)
        else:
            state_standard_deduction = resolve_jurisdiction_parameter(
                ctx.state_rate_map, "state_standard_deduction", Decimal("0"), country="US",
            )
        state_taxable = max(Decimal("0"), annual_state_taxable_gross - state_standard_deduction)
        # Employee-elected withholding percentage (currently only Arizona
        # Form A-4, ZP-TAX-US-2026-001 §4 Matrix — statutory range
        # 0.5%-3.5%) overrides the state's own default FLAT_RATE slab when
        # on file. Deliberately scoped to the single-FLAT_RATE-slab shape
        # (AZ's actual shape today) rather than applied unconditionally —
        # a state with real MARGINAL_RATE brackets must never have its
        # whole bracket table replaced by one flat employee-chosen number.
        # None (every employee before this field existed, and every
        # non-AZ employee) is a complete no-op: falls through to the
        # existing bracket-sum path exactly as before.
        if (
            ctx.state_income_tax_election_pct is not None
            and len(state_slabs) == 1
            and getattr(state_slabs[0], "rule_type", None) == "FLAT_RATE"
        ):
            annual_state_tax = state_taxable * ctx.state_income_tax_election_pct / Decimal("100")
        else:
            annual_state_tax = _calculate_annual_tax(state_taxable, state_slabs, filing_status=state_effective_filing_status)
    else:
        annual_state_tax = Decimal("0")
    # New York "Method III" (ZP-TAX-US-2026-001/NYS-50-T-NYS §Batch 7):
    # above $1,077,550 of total annualized wages, NY's own table stops
    # being a marginal continuation — every row above that point has "—"
    # instead of a base-tax number in the source's own table — and
    # instead computes the ENTIRE year's liability as one flat rate on
    # TOTAL annualized wages (not the post-deduction taxable-income figure
    # the ordinary bracket sum above uses), REPLACING annual_state_tax
    # rather than adding to it. Gated on NY's ordinary bracket path
    # actually having run (not CT/WI's bespoke paths, and not suppressed
    # by reciprocity) so no other state's high earners are affected; a
    # near-zero real-world incidence case (well above any wage this
    # platform's own employees are likely to have), implemented for
    # fidelity to the source's own explicit "don't correct this pattern"
    # instruction rather than any live need.
    if ctx.work_state == "NY" and not ctx.reciprocity_suppresses_work_state \
            and annual_state_taxable_gross > Decimal("1077550"):
        if annual_state_taxable_gross > Decimal("25000000"):
            ny_method_iii_rate = Decimal("11.70")
        elif annual_state_taxable_gross > Decimal("5000000"):
            ny_method_iii_rate = Decimal("11.10")
        else:
            ny_method_iii_rate = Decimal("10.45")
        annual_state_tax = annual_state_taxable_gross * ny_method_iii_rate / Decimal("100")
    state_income_tax = _round2(annual_state_tax / periods_per_year)

    # Local (county/municipal/school-district) tax: ctx.locality_rate is
    # only ever non-None when the employee's own work_locality code
    # resolved a real, manually-entered LocalityRate row (Tax Ops types in
    # a real published rate against a known code — see service.py's
    # get_locality_rate/LocalityRatesPanel) — an employee with no
    # work_locality, or a code nothing is configured for, correctly
    # resolves to 0 here, never a guess. flat_amount is a per-payslip
    # LST-style amount applied directly (same convention india.py already
    # uses for Professional Tax's own flat_amount), not annualized. A
    # rate_pct is applied like every other US wage-based tax above:
    # against annual_gross, then divided back to a monthly figure. This
    # module does not yet track locality-level residence (only the
    # coarser US-state-level reciprocity above does) — resident_rate_pct
    # is preferred when configured, falling back to nonresident_rate_pct,
    # since guessing which one applies would violate the "never infer"
    # rule the rest of this file follows.
    locality = ctx.locality_rate
    local_tax = Decimal("0")
    if locality is not None:
        # Tiered/progressive local tax (Production-Readiness Plan Phase 4,
        # 2026-09-15 — Maryland's Anne Arundel/Frederick counties, NYC's
        # own genuine marginal-bracket structure) — see
        # _tiered_locality_tax's own docstring. Checked FIRST: a locality
        # with a real bracket_schedule takes priority over its own
        # resident_rate_pct/flat_amount columns (which stay populated on
        # these rows only as an informational single-number summary, not
        # what's actually applied). getattr guards against the plain
        # dataclass test doubles used elsewhere in this codebase, which
        # don't define this newer attribute.
        bracket_schedule = getattr(locality, "bracket_schedule", None)
        if bracket_schedule:
            annual_local_tax = _tiered_locality_tax(annual_state_taxable_gross, ctx.w4_filing_status or "SINGLE", bracket_schedule)
            local_tax = _round2(annual_local_tax / periods_per_year)
        elif locality.flat_amount is not None:
            local_tax = _round2(locality.flat_amount)
        else:
            locality_rate_pct = locality.resident_rate_pct if locality.resident_rate_pct is not None else locality.nonresident_rate_pct
            if locality_rate_pct is not None:
                local_tax = _round2((annual_gross * locality_rate_pct / Decimal("100")) / periods_per_year)

    # "Higher of" resident-vs-work locality comparison (ZP-TAX-US-2026-001
    # §7.1, gap-closure Plan Phase 3) — a GENERIC mechanism (not
    # PA-specific in code, even though PA's own Act 32 EIT is the
    # motivating example) for LocalityRate rows tagged
    # locality_type="PSD_EIT_LST": when an employee has BOTH a real
    # work-locality rate AND a real residence-locality rate of this
    # type, the plain "one row, resident-else-nonresident" lookup above
    # is WRONG — the correct answer is the higher of the two, comparing
    # the WORK locality's own nonresident rate against the RESIDENCE
    # locality's own resident rate (two DIFFERENT LocalityRate rows, not
    # one row read two ways). Gated on both sides genuinely being
    # PSD_EIT_LST so ordinary municipal/county taxes (Detroit, Kansas
    # City, Yonkers) are completely unaffected — this REPLACES the
    # generic result above rather than adding to it. Currently 100%
    # dormant: zero PSD_EIT_LST LocalityRate rows are seeded anywhere
    # (PA's own real PSD-code registry hasn't been supplied) — this is
    # deliberately a mechanism-only build, proven correct with synthetic
    # data in tests, ready the moment real data arrives.
    if (
        locality is not None and getattr(locality, "locality_type", None) == "PSD_EIT_LST"
        and ctx.residence_locality_rate is not None
        and getattr(ctx.residence_locality_rate, "locality_type", None) == "PSD_EIT_LST"
    ):
        work_locality_rate_pct = locality.nonresident_rate_pct or Decimal("0")
        resident_locality_rate_pct = ctx.residence_locality_rate.resident_rate_pct or Decimal("0")
        higher_locality_rate_pct = max(work_locality_rate_pct, resident_locality_rate_pct)
        local_tax = _round2((annual_gross * higher_locality_rate_pct / Decimal("100")) / periods_per_year)

    # Yonkers (ZP-TAX-US-2026-001/NYS-50-T-Y, gap-closure Level 2 Batch 7):
    # two mutually-exclusive taxes, NEITHER of which fits the generic
    # locality_rate_pct-of-wages shape just above. A Yonkers RESIDENT
    # (ctx.residence_locality == "YONKERS", a new, narrow field — see its
    # own docstring) owes a surcharge equal to 16.75% of their OWN
    # already-computed NY State tax liability (annual_state_tax, not
    # wages at all), never the flat wage-based rate. A Yonkers
    # NONRESIDENT who works there is handled entirely by the generic
    # mechanism above already (the seeded YONKERS LocalityRate row has
    # only nonresident_rate_pct=0.50 set, no resident_rate_pct) — so the
    # only correction needed here is to CANCEL that generic result for an
    # employee whose resolved locality_rate is ALSO the Yonkers row (i.e.
    # they also work in Yonkers) while being a resident (they owe the
    # surcharge, not the flat nonresident tax), then add the surcharge
    # itself. ctx has no raw work_locality code (only the already-resolved
    # locality_rate object — see service.py's get_locality_rate), so the
    # cancellation check reads the resolved row's own locality_code
    # rather than a work_locality field that doesn't exist on this
    # context.
    if ctx.residence_locality == "YONKERS":
        if getattr(locality, "locality_code", None) == "YONKERS":
            local_tax = Decimal("0")
        local_tax += _round2((annual_state_tax * Decimal("16.75") / Decimal("100")) / periods_per_year)

    # State-level statutory payroll programs (CA SDI, WA PFML, NY PFL, ...):
    # a flat employee-side percentage of gross, resolved the same
    # additive way india.py's PT_FLAT-fallback flat rate is (ctx.
    # state_rate_map, populated via get_state_scoped_config regardless of
    # any jurisdiction pack's Active/Draft status — see that function's
    # own docstring). Previously looked up nowhere in this file: a state
    # program could be fully configured by Super Admin and still deduct
    # $0 forever, because nothing here ever read this field. Only "sdi"
    # is wired today (California); a future capped program (e.g. NJ FLI's
    # $171,100 cap) needs its own wage-base handling, not assumed here.
    sdi_rate = (ctx.state_rate_map or {}).get("sdi")
    state_disability_insurance = (
        _round2((annual_gross * sdi_rate.employee_rate_pct / Decimal("100")) / periods_per_year)
        if sdi_rate and sdi_rate.employee_rate_pct else Decimal("0")
    )

    # Every OTHER state-level statutory payroll program beyond SDI above
    # (Paid Leave/TDI/Universal Paid Leave/WA Cares/NJ's worker UI+DI+
    # workforce-dev+FLI/CO FAMLI/DE Paid Leave/ME PFML/WA PFML/etc.,
    # ZP-TAX-US-2026-001 §5) — gated per-state by
    # _US_STATE_PROGRAM_ENABLED_STATES (dormant by default), same
    # additive-per-state convention as _US_STATE_TAX_ENABLED_STATES above.
    # Multiple programs can coexist for one state (each its own
    # component_key in ctx.state_rate_map); optional companion rows:
    #   "<key>_wage_cap"       caps the taxable WAGE the rate applies to
    #   "<key>_annual_max"     caps the resulting DOLLAR amount itself
    #   "<key>_employer_headcount_min"/"_max"
    #       gates ONLY the employer side (never the employee side — Phase
    #       3C's CO FAMLI/ME PFML/WA PFML/DE Paid Leave all have the
    #       employee rate apply unconditionally, only the employer's
    #       share depends on this employer's own covered headcount) to
    #       [min, max) — either bound optional. The employer's actual
    #       headcount comes from EmployerTaxProfile.covered_employee_count
    #       for jurisdiction=ctx.work_state, component_code=this key
    #       uppercased (aliased for Delaware's two tiers, which share one
    #       real headcount fact under "PAID_LEAVE" despite being two
    #       separate rows/rates) — absent a configured profile, the
    #       headcount is unknown and the employer share is never guessed
    #       (stays 0), same "never infer" principle EmployerTaxProfile's
    #       own docstring already establishes for SUI.
    # Absent means uncapped/unconditional, same convention as
    # ss_wage_base/futa_wage_base. "sdi" itself is excluded (its own
    # dedicated field above, unaffected by this switch).
    _headcount_group_aliases = {"paid_leave_parental": "paid_leave"}
    state_program_deductions = Decimal("0")
    employer_state_program_contributions = Decimal("0")
    for key, row in (ctx.state_rate_map or {}).items():
        if key == "sdi" or key.endswith("_wage_cap") or key.endswith("_annual_max") \
                or key.endswith("_employer_headcount_min") or key.endswith("_employer_headcount_max"):
            continue
        if getattr(row, "jurisdiction_state", None) not in _US_STATE_PROGRAM_ENABLED_STATES:
            continue
        wage_cap_row = (ctx.state_rate_map or {}).get(f"{key}_wage_cap")
        wage_cap = wage_cap_row.flat_amount if wage_cap_row is not None else None
        annual_max_row = (ctx.state_rate_map or {}).get(f"{key}_annual_max")
        annual_max = annual_max_row.flat_amount if annual_max_row is not None else None
        taxable = min(annual_gross, wage_cap) if wage_cap is not None else annual_gross
        if row.employee_rate_pct:
            amount = _round2((taxable * row.employee_rate_pct / Decimal("100")) / periods_per_year)
            if annual_max is not None:
                amount = min(amount, _round2(annual_max / periods_per_year))
            state_program_deductions += amount
        if row.employer_rate_pct:
            headcount_min_row = (ctx.state_rate_map or {}).get(f"{key}_employer_headcount_min")
            headcount_max_row = (ctx.state_rate_map or {}).get(f"{key}_employer_headcount_max")
            employer_applies = True
            if headcount_min_row is not None or headcount_max_row is not None:
                headcount_code = _headcount_group_aliases.get(key, key).upper()
                profile = (ctx.employer_tax_profiles or {}).get(headcount_code)
                headcount = profile.covered_employee_count if profile is not None else None
                employer_applies = (
                    headcount is not None
                    and (headcount_min_row is None or headcount >= headcount_min_row.flat_amount)
                    and (headcount_max_row is None or headcount < headcount_max_row.flat_amount)
                )
            if employer_applies:
                employer_state_program_contributions += _round2((taxable * row.employer_rate_pct / Decimal("100")) / periods_per_year)

    # tds is kept as the COMBINED total (federal+state+local) for backward
    # compatibility with any existing code/report that still reads it as
    # one number — federal_income_tax/state_income_tax/local_tax below are
    # the same figures broken out separately so the payslip can finally
    # show a US employee which part is which, instead of a single line
    # mislabeled "Federal Withholding" that silently included state tax.
    tds = federal_income_tax + state_income_tax + local_tax

    return dict(
        social_security=social_security, employer_social_security=employer_ss,
        medicare=medicare, employer_medicare=employer_medicare,
        employer_futa=employer_futa, employer_sui=employer_sui,
        federal_income_tax=federal_income_tax, state_income_tax=state_income_tax, local_tax=local_tax,
        state_disability_insurance=state_disability_insurance,
        state_program_deductions=state_program_deductions,
        employer_state_program_contributions=employer_state_program_contributions,
        tds=tds, annual_tax=annual_tax,
        ytd_ss_wages_after=ytd_ss_wages_after,
        ytd_futa_wages_after=ytd_futa_wages_after,
        ytd_medicare_wages_after=ytd_medicare_wages_after,
    )

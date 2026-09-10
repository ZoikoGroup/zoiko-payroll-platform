"""
modules/payroll/engine/countries/uk.py
-----------------------------------------
UK: National Insurance + Employer/Employee Pension + PAYE (tax-code aware,
sub-jurisdiction data-driven) + Student/Postgraduate Loan.

Genuinely jurisdiction-agnostic: this file never compares ctx.work_state
against a jurisdiction name (no `if ctx.work_state == "Scotland"`). Which
sub-jurisdiction's slabs/rates apply is decided once, upstream, by
service.py's resolve_uk_configuration() — this file only ever reads
whatever ended up in ctx.slabs/ctx.state_slabs/ctx.rate_map.
"""

from datetime import date
from decimal import Decimal, ROUND_DOWN

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    _calculate_annual_tax, resolve_jurisdiction_parameter,
    _param_text, resolve_periods_per_year, resolve_direct_period_threshold,
    _UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES, _UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES,
    _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES, _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES,
    _UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES, _UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES,
)

# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change. See that file for
# the provenance comments on each.
from app.modules.payroll.hardcoded_defaults import (
    _UK_PERSONAL_ALLOWANCE, _UK_PA_TAPER_THRESHOLD, _UK_NI_PRIMARY_THRESHOLD,
    _UK_NI_UPPER_THRESHOLD, _UK_NI_PRIMARY_RATE, _UK_NI_UPPER_RATE,
    _UK_PENSION_MIN_ENPLOYER, _UK_NI_SECONDARY_THRESHOLD, _UK_NI_EMPLOYER_RATE,
    _UK_PENSION_QE_LOWER, _UK_PENSION_QE_UPPER, _UK_STUDENT_LOAN_PLANS, _UK_FLAT_RATE_CODES,
    _UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY, _UK_NI_UPPER_THRESHOLD_BY_FREQUENCY,
    _UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY, _UK_K_CODE_CAP_PCT, _UK_STATE_PENSION_AGE,
    _UK_PENSION_AE_TRIGGER,
)

# Threshold-only override keys for the plans exposed in the Compliance UI's
# Statutory Thresholds tab. Kept to <=20 chars — ContributionRate.component_key
# is varchar(20). This is a DB-key-name registry, not a hardcoded value
# itself, so it stays here rather than moving to hardcoded_defaults.py.
_UK_STUDENT_LOAN_PARAM_KEYS = {
    "UK_PLAN1": "sl_plan1_thresh",
    "UK_PLAN2": "sl_plan2_thresh",
    "UK_PLAN4": "sl_plan4_thresh",
    "UK_PLAN5": "sl_plan5_thresh",
    "UK_POSTGRAD": "pg_loan_thresh",
}

# 2026-09-09 gap-closure Phase 1: the repayment RATE (9%/6%) was the one
# figure in _UK_STUDENT_LOAN_PLANS with no override path at all — the
# threshold half of each tuple already had one (above). Same key-name-
# registry convention.
_UK_STUDENT_LOAN_RATE_PARAM_KEYS = {
    "UK_PLAN1": "sl_plan1_rate",
    "UK_PLAN2": "sl_plan2_rate",
    "UK_PLAN4": "sl_plan4_rate",
    "UK_PLAN5": "sl_plan5_rate",
    "UK_POSTGRAD": "pg_loan_rate",
}

# 2026-09-09 gap-closure Phase 1: each flat-rate code's % was a bare
# Python-dict lookup (_UK_FLAT_RATE_CODES in hardcoded_defaults.py) with
# no resolve_jurisdiction_parameter call at all — the only UK figure left
# with no Super-Admin override path after the K-code-cap fix. Same
# key-name-registry convention as the two dicts above.
_UK_FLAT_RATE_CODE_PARAM_KEYS = {
    "BR": "flat_br_pct", "D0": "flat_d0_pct", "D1": "flat_d1_pct",
    "SBR": "flat_sbr_pct", "SD0": "flat_sd0_pct", "SD1": "flat_sd1_pct",
    "SD2": "flat_sd2_pct", "SD3": "flat_sd3_pct",
    "CBR": "flat_cbr_pct", "CD0": "flat_cd0_pct", "CD1": "flat_cd1_pct",
}

# 2026-09-09 gap-closure Phase 1: the direct-period NI thresholds
# (_UK_NI_*_THRESHOLD_BY_FREQUENCY in hardcoded_defaults.py) had no
# database override path at all, unlike the annual figures they take
# precedence over. Same key-name-registry convention, one dict per
# threshold, keyed by pay_frequency.
_UK_NI_PRIMARY_THRESH_PARAM_KEYS = {"Weekly": "ni_pt_thresh_wk", "Monthly": "ni_pt_thresh_mo"}
_UK_NI_UPPER_THRESH_PARAM_KEYS = {"Weekly": "ni_uel_thresh_wk", "Monthly": "ni_uel_thresh_mo"}
_UK_NI_SECONDARY_THRESH_PARAM_KEYS = {"Weekly": "ni_st_thresh_wk", "Monthly": "ni_st_thresh_mo"}


# ── PAYE tax-code interpretation ────────────────────────────────────────
# Handles standard codes ("1257L"/"S1257L"/"C1257L" -> allowance = digits
# x 10), K-codes (negative allowance -- untaxed benefit added to income,
# never tapered), 0T (zero allowance, still uses the regime's progressive
# bands), NT (no deduction), and the flat-rate override code families
# BR/D0/D1, SBR/SD0-3, CBR/CD0/CD1 (ZP-TAX-UK-2026-27-001 section 6.3).
#
# `region_prefix` ("S"/"C"/None) is the ONE place this file reads the
# code's leading letter — per the doc's non-negotiable control ("operate
# the HMRC-issued tax code prefix, never the worksite"), resolve_uk_
# configuration() in service.py uses this to pick the sub-jurisdiction,
# preferring it over employee.work_state. NT is explicitly never given an
# S/C prefix by HMRC (section 6.1) even though its own letters don't
# start with S/C anyway, so no special-casing is needed here.
#
# Deliberately NOT implementing true cumulative (Week1/Month1 vs
# cumulative YTD) PAYE basis -- that requires year-to-date income
# tracking this engine doesn't have for ANY country yet (same explicit
# deferral already on record for Student Loan balance tracking, below).
# `basis` is recorded on the result but every calculation stays
# period-by-period, as today.
def interpret_tax_code(tax_code: str | None, default_personal_allowance: Decimal, rate_map: dict | None = None) -> dict:
    """`rate_map` is optional (defaults to None, meaning "use the
    hardcoded fallback rate for every flat-rate code") so every existing
    caller/test that only ever passed the first two positional args
    keeps working unchanged. Callers that have a real rate_map in scope
    (both call sites in this file do) pass it through so a Super-Admin-
    configured flat-rate-code % actually takes effect."""
    if not tax_code:
        return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": None}
    code = tax_code.upper().strip()

    # Flat-rate families are matched on the FULL code first: "SD0" and
    # "D0" are different HMRC codes at different rates (21% Scottish
    # intermediate vs 40% rUK higher) — stripping the prefix before this
    # check would wrongly collapse them onto the same rate.
    if code in _UK_FLAT_RATE_CODES:
        region_prefix = code[0] if code[0] in ("S", "C") else None
        flat_rate_pct = _UK_FLAT_RATE_CODES[code]
        if rate_map is not None:
            param_key = _UK_FLAT_RATE_CODE_PARAM_KEYS.get(code)
            if param_key:
                flat_rate_pct = resolve_jurisdiction_parameter(rate_map, param_key, flat_rate_pct, side="employee", country="UK")
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": flat_rate_pct, "basis": "NONCUMULATIVE", "region_prefix": region_prefix}
    if code == "NT":
        return {"personal_allowance": None, "flat_rate_pct": Decimal("0"), "basis": "NONCUMULATIVE", "region_prefix": None}

    region_prefix = None
    body = code
    if code[:1] in ("S", "C") and len(code) > 1:
        region_prefix = code[0]
        body = code[1:]

    if body == "0T":
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    if body.startswith("K") and body[1:].isdigit():
        return {"personal_allowance": -(Decimal(body[1:]) * 10), "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    digits = "".join(ch for ch in body if ch.isdigit())
    if digits:
        return {"personal_allowance": Decimal(digits) * 10, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict, tax_code: str | None = None) -> Decimal:
    default_pa = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
    interpreted = interpret_tax_code(tax_code, default_pa, rate_map)
    if interpreted["flat_rate_pct"] is not None:
        # BR/D0/D1 (flat rate on full income, no allowance) or NT (0%, no tax at all).
        return annual_gross * interpreted["flat_rate_pct"] / Decimal("100")

    pa = interpreted["personal_allowance"]
    # ZP-TAX-UK-2026-27-001 §5.1 PAYE implementation rule: "Zoiko Payroll
    # must not independently recompute an employee's tapered Personal
    # Allowance from payroll earnings. HMRC supplies the tax code that
    # operationalizes allowances..." — HMRC bakes any real taper into the
    # numeric code itself (a >£100k earner is issued a genuinely lower
    # code, not "1257L"), so re-tapering on top of that is exactly the
    # forbidden recompute. Dormant by default
    # (_UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES) — while off, this
    # engine's original independent-taper behavior runs unchanged; once
    # on, `pa` is used exactly as parsed from the code, no taper at all.
    if "UK" not in _UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES:
        taper_threshold = resolve_jurisdiction_parameter(rate_map, "pa_taper_threshold", _UK_PA_TAPER_THRESHOLD, country="UK")
        if pa >= 0 and annual_gross > taper_threshold:
            # Taper only applies to a standard positive allowance — a K-code's
            # negative allowance has nothing to taper.
            taper = (annual_gross - taper_threshold) / Decimal("2")
            pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


# ── NI Category derivation from relief-eligibility facts ────────────────
# (ZP-TAX-UK-2026-27-001 §8.2/§9.1/§9.3 gap-closure Part 2, 2026-09-09).
# `ni_category` has always been a field an admin sets by hand — nothing
# ever checked whether the employee actually qualifies for a Freeport/
# Investment Zone/veteran/apprentice relief category. This derives the
# correct letter from real facts (service.py's _load_uk_ni_relief_facts
# loads them from PayrollNiReliefFact) instead, per §9.3's own
# instruction: "Relief eligibility is not a rate toggle."
_UK_NI_CATEGORY_BY_SITE_AND_SPA = {
    ("FREEPORT", False): "F",
    ("FREEPORT", True): "S",
    ("INVESTMENT_ZONE", False): "N",
    ("INVESTMENT_ZONE", True): "K",
}


def derive_ni_category(date_of_birth, pay_date, relief_facts: list, rate_map: dict) -> str | None:
    """`relief_facts` is a list of {"relief_type": "FREEPORT"|
    "INVESTMENT_ZONE"|"VETERAN"|"APPRENTICE", "effective_from": date,
    "effective_to": date|None} dicts for one employee — this function
    only decides which are ACTIVE on `pay_date` and what letter (if any)
    they imply.

    Returns None (never guesses) whenever date_of_birth/pay_date is
    unavailable or no relief fact is active on `pay_date` — the caller
    must fall back to the employee's own manually-set ni_category in
    that case, exactly as before this function existed.

    Deliberately does NOT derive the married-women/widows reduced-rate
    election (B/E/I) or the "already paying NI elsewhere" deferment
    categories (D/J/K's deferment variant/L/Z) — those require an
    HMRC-issued certificate (CA4139/CA2700), a historical election this
    engine has no fact to derive from; they stay manual-only.

    Precedence when more than one fact could apply — NOT itself specified
    by the document as a single ordered list; this is a disclosed,
    documented engineering judgment call: a Freeport/Investment Zone
    site assignment (the more specific, deliberately-enrolled statutory
    position) takes precedence over age/veteran/apprentice status, with
    State Pension age further selecting the site's own "at SPA" letter
    within it. Outside any site: State Pension age > qualifying veteran >
    apprentice under 25 > under 21 > standard (returns None, meaning "no
    opinion, use whatever's manually set")."""
    if not date_of_birth or not pay_date:
        return None

    def _active(fact):
        ef, et = fact.get("effective_from"), fact.get("effective_to")
        return (ef is None or ef <= pay_date) and (et is None or et >= pay_date)

    active_facts = [f for f in (relief_facts or []) if _active(f)]
    if not active_facts:
        return None

    age = pay_date.year - date_of_birth.year - ((pay_date.month, pay_date.day) < (date_of_birth.month, date_of_birth.day))
    state_pension_age = resolve_jurisdiction_parameter(rate_map, "state_pension_age", _UK_STATE_PENSION_AGE, country="UK")
    at_spa = age >= int(state_pension_age)

    site_fact = next((f for f in active_facts if f.get("relief_type") in ("FREEPORT", "INVESTMENT_ZONE")), None)
    if site_fact:
        return _UK_NI_CATEGORY_BY_SITE_AND_SPA[(site_fact["relief_type"], at_spa)]

    if at_spa:
        return "C"
    if any(f.get("relief_type") == "VETERAN" for f in active_facts):
        return "V"
    if any(f.get("relief_type") == "APPRENTICE" for f in active_facts) and age < 25:
        return "H"
    if age < 21:
        return "M"
    return None


# ── Automatic Enrolment assessment ───────────────────────────────────────
# (ZP-TAX-UK-2026-27-001 §13/Layer 5 gap-closure Part 3, 2026-09-09).
# Whether an employee should be enrolled has always been a plain manual
# yes/no field (PayrollEmployee's compliance_fields
# "auto_enrolment_pension") — nothing ever computed a genuine assessment
# from age and earnings. This derives the real classification (§13.1's
# own worked example: £3,000 monthly -> £2,480 qualifying earnings uses
# the SAME thresholds this function reads).
#
# Deliberately informational/output-only: does NOT change
# employee_pension/employer_pension's own calculation at all (§13's own
# instruction — "not a universal fixed employee tax" — contribution
# amount stays entirely tenant-configured, same as today). This only
# answers "what does the law say this employee's status is," for
# Compliance/Super Admin visibility — an employer still separately
# decides scheme enrolment, exactly like the document's own "auto_
# enrolment_state" field (§13.3) is data, not a trigger.
def assess_auto_enrolment(age: int | None, annual_gross: Decimal, rate_map: dict) -> str | None:
    """Returns "ELIGIBLE_JOBHOLDER" | "NON_ELIGIBLE_JOBHOLDER" |
    "ENTITLED_WORKER", or None when age is unavailable or outside the
    16-74 age range this regime covers at all (never guesses a status
    for someone the law doesn't classify)."""
    if age is None or age < 16 or age >= 75:
        return None
    lower_qualifying_earnings = resolve_jurisdiction_parameter(rate_map, "pension_qe_lower", _UK_PENSION_QE_LOWER, country="UK")
    ae_trigger = resolve_jurisdiction_parameter(rate_map, "pension_ae_trigger", _UK_PENSION_AE_TRIGGER, country="UK")
    state_pension_age = resolve_jurisdiction_parameter(rate_map, "state_pension_age", _UK_STATE_PENSION_AGE, country="UK")

    if annual_gross > ae_trigger:
        if 22 <= age < int(state_pension_age):
            return "ELIGIBLE_JOBHOLDER"
        return "NON_ELIGIBLE_JOBHOLDER"
    if annual_gross > lower_qualifying_earnings:
        return "NON_ELIGIBLE_JOBHOLDER"
    return "ENTITLED_WORKER"


# ── National Insurance category bands ──────────────────────────────────
def _resolve_ni_bands(slabs, ni_category: str | None):
    """TaxSlab rows with rule_type="NI_BAND" for this employee's NI
    category, sorted by band. Returns [] when the employee has no
    category set, or no banded rows exist for it — the caller falls back
    to the flat ContributionRate percentage (today's only mechanism),
    exactly the same fallback shape already proven for India's PT_FLAT
    rows. Zero hardcoded per-category behavior: a new category becomes
    real the moment rows exist for it, no engine change required.

    Gated behind _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES (shared.py):
    ni_category is already a live, employee-configurable field today, with
    every category currently computing via the flat Category-A-shaped
    fallback regardless of what's actually declared — seeding real banded
    data would otherwise silently change a real number for any org that
    already has an employee set to a non-A category. Returns [] (forcing
    the flat fallback) even once rows exist, until deliberately enabled."""
    if "UK" not in _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES:
        return []
    if not ni_category:
        return []
    bands = [
        s for s in slabs
        if getattr(s, "rule_type", None) == "NI_BAND" and getattr(s, "ni_category", None) == ni_category
    ]
    return sorted(bands, key=lambda s: s.min_amount)


# Real, published per-period NI_BAND variants (ZP-TAX-UK-2026-27-001
# §8.1: "must not cause ordinary payroll to annualize NIC" — found on a
# fresh document re-read, 2026-09-10, to be a genuine gap: the banded
# path above always annualizes first even for Weekly/Monthly pay, which
# can differ by a penny or two from HMRC's own independently-published
# per-period thresholds, since £242 (weekly PT) x 52 = £12,584, not the
# real annual PT of £12,570 — confirmed via the doc's own reference
# vectors: Category A weekly £1,000 produced £58.67/£135.58 through the
# annualized banded path instead of the document's published £58.66/
# £135.60). Same "separate rule_type per variant, never guessed" pattern
# already used for Scotland's arrestment tables (ARREST_SCOT_WK/MO,
# Part 8) — Fortnightly/FourWeekly aren't published by the document, so
# only Weekly/Monthly get a per-frequency variant, matching the flat
# direct-period path's own scope boundary exactly.
_UK_NI_BAND_FREQUENCY_RULE_TYPES = {"Weekly": "NI_BAND_WEEKLY", "Monthly": "NI_BAND_MONTHLY"}

# Every rule_type that represents an NI band row rather than an income-tax
# bracket — used to strip these out of the slab list before it reaches any
# income-tax computation. Found missing the two per-frequency variants above
# on 2026-09-10 (income_slabs/state_income_slabs below only excluded literal
# "NI_BAND"): once NI_BAND_WEEKLY/NI_BAND_MONTHLY rows exist in the same live
# pack, they were silently summed in as extra income-tax brackets, massively
# inflating PAYE for every Weekly/Monthly employee. Single set, referenced
# everywhere this filtering happens, so a future NI_BAND variant can't repeat
# this mistake by being added in only one of the two places.
_UK_NI_BAND_RULE_TYPES = {"NI_BAND", *_UK_NI_BAND_FREQUENCY_RULE_TYPES.values()}


def _resolve_ni_bands_by_frequency(slabs, ni_category: str | None, pay_frequency: str | None):
    """Returns [] (never guessed/derived from the annual bands) when no
    per-frequency rows exist for this category+frequency — the caller
    then falls back to _resolve_ni_bands' existing annualize-then-divide
    behavior, completely unchanged from before this function existed.
    Real weekly/monthly figures must be entered as their own TaxSlab
    rows (rule_type NI_BAND_WEEKLY/NI_BAND_MONTHLY) via the Super Admin
    Compliance UI, exactly like every other UK statutory figure in this
    codebase — never hardcoded here."""
    if "UK" not in _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES or not ni_category:
        return []
    rule_type = _UK_NI_BAND_FREQUENCY_RULE_TYPES.get(pay_frequency)
    if not rule_type:
        return []
    bands = [
        s for s in slabs
        if getattr(s, "rule_type", None) == rule_type and getattr(s, "ni_category", None) == ni_category
    ]
    return sorted(bands, key=lambda s: s.min_amount)


def _calculate_ni_from_bands(annual_gross: Decimal, bands: list) -> tuple[Decimal, Decimal]:
    employee_annual = Decimal("0")
    employer_annual = Decimal("0")
    for band in bands:
        lower = band.min_amount
        upper = band.max_amount if band.max_amount is not None else annual_gross
        if annual_gross <= lower:
            continue
        taxable_in_band = min(annual_gross, upper) - lower
        if taxable_in_band > 0:
            employee_annual += taxable_in_band * (band.rate_pct / Decimal("100"))
            employer_annual += taxable_in_band * ((band.employer_rate_pct or Decimal("0")) / Decimal("100"))
    return employee_annual, employer_annual


def _annual_ni_due(cumulative_gross: Decimal, rate_map: dict) -> tuple[Decimal, Decimal]:
    """Employee+employer NIC due on `cumulative_gross`, computed against
    the ANNUAL PT/UEL/ST thresholds and flat Category-A-shaped rates —
    the core of a director's statutory "annual earnings method" (§9.2):
    NIC is assessed against cumulative-to-date earnings and the ANNUAL
    thresholds directly, never a per-period slice. Same threshold/rate
    keys the ordinary employee calculation already resolves — a
    director's NIC rates are not a separately configured statutory
    figure per §9.2, only the earnings-PERIOD method differs."""
    pt = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
    uel = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
    st = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")
    employee_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
    upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")
    employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")

    basicable = max(Decimal("0"), min(cumulative_gross, uel) - pt)
    upperable = max(Decimal("0"), cumulative_gross - uel)
    employee_due = basicable * employee_rate / Decimal("100") + upperable * upper_rate / Decimal("100")
    employer_due = max(Decimal("0"), cumulative_gross - st) * employer_rate / Decimal("100")
    return employee_due, employer_due


def _round_down_pound(value: Decimal) -> Decimal:
    """HMRC's Student/Postgraduate Loan rounding rule (ZP-TAX-UK-2026-27-001
    §10.2: "Round the deduction down to the nearest whole pound") — a
    UK-specific rounding convention, deliberately kept local to this file
    rather than added to engine/base.py's general-purpose _round2, which
    every other UK figure (and every other country) still uses unchanged."""
    return value.quantize(Decimal("1"), rounding=ROUND_DOWN)


def _compute_loan_repayment(plan_key: str | None, annual_gross: Decimal, periods_per_year: Decimal, rate_map: dict) -> Decimal:
    """One plan's period repayment — shared by the main study_loan_plan
    deduction and the concurrent Postgraduate Loan deduction (both draw
    from the same _UK_STUDENT_LOAN_PLANS table and the same rounding
    switch). Returns 0 for an unrecognized/unset plan_key, matching
    today's exact existing behavior for study_loan_plan."""
    plan = _UK_STUDENT_LOAN_PLANS.get(plan_key)
    if not plan:
        return Decimal("0")
    default_threshold, default_rate = plan
    param_key = _UK_STUDENT_LOAN_PARAM_KEYS.get(plan_key)
    threshold = (
        resolve_jurisdiction_parameter(rate_map, param_key, default_threshold, country="UK")
        if param_key else default_threshold
    )
    rate_param_key = _UK_STUDENT_LOAN_RATE_PARAM_KEYS.get(plan_key)
    rate = (
        resolve_jurisdiction_parameter(rate_map, rate_param_key, default_rate, side="employee", country="UK")
        if rate_param_key else default_rate
    )
    annual_repayment = max(Decimal("0"), annual_gross - threshold) * rate / Decimal("100")
    period_repayment = annual_repayment / periods_per_year
    # ZP-TAX-UK-2026-27-001 §10.2: "Round the deduction down to the
    # nearest whole pound." Dormant by default
    # (_UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES) — while off, rounds
    # to the nearest penny (_round2), today's exact existing behavior.
    return (
        _round_down_pound(period_repayment)
        if "UK" in _UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES
        else _round2(period_repayment)
    )


# ── Workplace Pension ────────────────────────────────────────────────────
def _resolve_pensionable_pay(ctx: PayrollContext, basis: str, qe_lower_period: Decimal, qe_upper_period: Decimal) -> Decimal:
    if basis == "BASIC_PAY":
        return ctx.basic
    if basis == "PENSIONABLE_EARNINGS":
        return ctx.gross
    # QUALIFYING_EARNINGS (default): banded slice of gross between the QE limits.
    return max(Decimal("0"), min(ctx.gross, qe_upper_period) - qe_lower_period)


def calculate(ctx: PayrollContext) -> dict:
    """UK: Employee + Employer National Insurance (category-banded where
    configured) + Employer/Employee Workplace Pension + PAYE (tax-code
    aware, sub-jurisdiction bands where configured) + Student/Postgraduate
    Loan. Frequency-aware: annualizes/de-annualizes using ctx.pay_frequency
    (defaults to "Monthly", so every existing employee's numbers are
    unchanged)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    annual_gross = ctx.gross * periods_per_year

    # NI_BAND rows (if any) live in the same TaxSlab list as income-tax
    # brackets — filtered out before either consumer sees the other's rows.
    income_slabs = [s for s in ctx.slabs if getattr(s, "rule_type", None) not in _UK_NI_BAND_RULE_TYPES]
    state_income_slabs = [s for s in ctx.state_slabs if getattr(s, "rule_type", None) not in _UK_NI_BAND_RULE_TYPES]

    # Directors NIC (§9.2: "Do not process a director as an ordinary
    # employee solely because the same percentage rates apply") — takes
    # precedence over every other NI path below. Dormant until REAL
    # cumulative YTD data is actually loaded (ctx.ytd_director_ni_gross is
    # not None): without it, there is no meaningful "annual earnings
    # method" to perform (a single period's gross annualized-as-a-guess
    # is exactly what the ordinary-employee path below already computes),
    # so this deliberately falls through to that unchanged path rather
    # than invent a director-specific number from no real history.
    use_director_annual_method = (
        ctx.is_director and ctx.ytd_director_ni_gross is not None
        and (ctx.director_ni_method != "ALTERNATIVE" or ctx.is_final_ni_period)
    )
    if use_director_annual_method:
        cumulative_gross = ctx.ytd_director_ni_gross + ctx.gross
        ytd_employee_paid = ctx.ytd_director_ni_employee_paid or Decimal("0")
        ytd_employer_paid = ctx.ytd_director_ni_employer_paid or Decimal("0")
        employee_due_to_date, employer_due_to_date = _annual_ni_due(cumulative_gross, rate_map)
        ni_employee = _round2(max(Decimal("0"), employee_due_to_date - ytd_employee_paid))
        employer_ni = _round2(max(Decimal("0"), employer_due_to_date - ytd_employer_paid))
    elif (period_ni_bands := _resolve_ni_bands_by_frequency(ctx.slabs, ctx.ni_category, ctx.pay_frequency)):
        # Direct period band calculation — no annualize/de-annualize
        # round-trip at all, same reasoning as the flat direct-period
        # path below. _calculate_ni_from_bands is generic about what
        # "gross" and "bands" mean — feeding it this period's own gross
        # against period-denominated bands is exactly as valid as
        # feeding it annual figures against annual bands.
        ni_employee_raw, employer_ni_raw = _calculate_ni_from_bands(ctx.gross, period_ni_bands)
        ni_employee = _round2(ni_employee_raw)
        employer_ni = _round2(employer_ni_raw)
    elif (ni_bands := _resolve_ni_bands(ctx.slabs, ctx.ni_category)):
        ni_employee_annual, ni_employer_annual = _calculate_ni_from_bands(annual_gross, ni_bands)
        ni_employee = _round2(ni_employee_annual / periods_per_year)
        employer_ni = _round2(ni_employer_annual / periods_per_year)
    elif "UK" in _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES and (ctx.pay_frequency or "Monthly") in ("Weekly", "Monthly"):
        # Direct period calculation — no annualize/de-annualize round-trip
        # at all (ZP-TAX-UK-2026-27-001 §8.1: "Class 1 NIC is based on the
        # earnings period rather than cumulative annual earnings... must
        # not cause ordinary payroll to annualize NIC"). Real Weekly/
        # Monthly figures (hardcoded_defaults.py) don't derive from the
        # annual ones by division — HMRC rounds each period's table
        # independently. Scoped to Weekly/Monthly only: the document
        # doesn't publish Fortnightly/FourWeekly tables, so those keep
        # the annualize-then-divide fallback below.
        ni_primary_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
        ni_upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")
        ni_employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")
        annual_ni_primary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
        annual_ni_upper_threshold = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
        annual_ni_secondary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")

        period_primary_threshold = resolve_direct_period_threshold(
            _UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY, annual_ni_primary_threshold, ctx.pay_frequency,
            rate_map=rate_map, param_keys_by_frequency=_UK_NI_PRIMARY_THRESH_PARAM_KEYS, country="UK",
        )
        period_upper_threshold = resolve_direct_period_threshold(
            _UK_NI_UPPER_THRESHOLD_BY_FREQUENCY, annual_ni_upper_threshold, ctx.pay_frequency,
            rate_map=rate_map, param_keys_by_frequency=_UK_NI_UPPER_THRESH_PARAM_KEYS, country="UK",
        )
        period_secondary_threshold = resolve_direct_period_threshold(
            _UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY, annual_ni_secondary_threshold, ctx.pay_frequency,
            rate_map=rate_map, param_keys_by_frequency=_UK_NI_SECONDARY_THRESH_PARAM_KEYS, country="UK",
        )

        period_basicable = max(Decimal("0"), min(ctx.gross, period_upper_threshold) - period_primary_threshold)
        period_upperable = max(Decimal("0"), ctx.gross - period_upper_threshold)
        ni_employee = _round2((period_basicable * ni_primary_rate / Decimal("100")) + (period_upperable * ni_upper_rate / Decimal("100")))
        employer_ni = _round2(max(Decimal("0"), ctx.gross - period_secondary_threshold) * ni_employer_rate / Decimal("100"))
    else:
        ni_primary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
        ni_upper_threshold = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
        ni_primary_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
        ni_upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")

        ni_basicable = max(Decimal("0"), min(annual_gross, ni_upper_threshold) - ni_primary_threshold)
        ni_upperable = max(Decimal("0"), annual_gross - ni_upper_threshold)
        ni_employee_annual = (ni_basicable * ni_primary_rate / Decimal("100")) + (ni_upperable * ni_upper_rate / Decimal("100"))
        ni_employee = _round2(ni_employee_annual / periods_per_year)

        ni_secondary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")
        ni_employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")
        ni_employer_annual = max(Decimal("0"), annual_gross - ni_secondary_threshold) * ni_employer_rate / Decimal("100")
        employer_ni = _round2(ni_employer_annual / periods_per_year)

    # Directors NIC YTD — accumulation must continue correctly regardless
    # of WHICH branch above priced this period (annual method, ALTERNATIVE
    # method's ordinary calc, or the fully-dormant fallback when no
    # accumulator was loaded at all): whatever ni_employee/employer_ni
    # ended up being, it's added to the running cumulative totals so
    # service.py can persist the correct "after" state. None (not
    # computed at all) for a non-director, matching every other YTD
    # field's "None means not applicable" contract.
    ytd_director_ni_gross_after = None
    ytd_director_ni_employee_paid_after = None
    ytd_director_ni_employer_paid_after = None
    if ctx.is_director:
        ytd_director_ni_gross_after = (ctx.ytd_director_ni_gross or Decimal("0")) + ctx.gross
        ytd_director_ni_employee_paid_after = (ctx.ytd_director_ni_employee_paid or Decimal("0")) + ni_employee
        ytd_director_ni_employer_paid_after = (ctx.ytd_director_ni_employer_paid or Decimal("0")) + employer_ni

    # Apprenticeship Levy (§14) — banded on the ORG's aggregate annual pay
    # bill, not this employee's own pay; zero and dormant (appr_levy_ytd_pay_bill_after
    # stays None) until the org-level accumulator is wired for this
    # calculation, same "None means not applicable" contract as Ontario
    # EHT (canada.py). calculate_apprenticeship_levy_period_amount itself
    # separately fails closed (returns None) when the rate/allowance
    # aren't configured — treated the same as "not wired" here.
    employer_apprenticeship_levy = Decimal("0")
    appr_levy_ytd_pay_bill_after = None
    if ctx.appr_levy_ytd_pay_bill_before is not None:
        levy_amount = calculate_apprenticeship_levy_period_amount(ctx.gross, ctx.appr_levy_ytd_pay_bill_before, rate_map)
        employer_apprenticeship_levy = levy_amount if levy_amount is not None else Decimal("0")
        appr_levy_ytd_pay_bill_after = ctx.appr_levy_ytd_pay_bill_before + ctx.gross

    # Employment Allowance (§14) — reduces the ORG's CUMULATIVE employer
    # secondary Class 1 NIC liability when remitting to HMRC (claimed via
    # EPS), NOT any individual payslip's own employer_ni figure at all
    # (§14: "Employer eligibility/claim state; reduce eligible secondary
    # Class 1 NIC liability; claim through EPS") — a REPORTING/remittance-
    # level offset, not a payroll deduction. This block only tracks the
    # org's cumulative employer_ni total across every employee (same
    # org-level-accumulator shape as the Levy's pay bill above); the
    # actual net-of-allowance liability is computed separately, on
    # demand, by calculate_employment_allowance_net_liability below —
    # never per payslip, since the allowance is a whole-organization,
    # whole-tax-year concept, not a per-employee one.
    employer_ni_ytd_after = None
    if ctx.employer_ni_ytd_before is not None:
        employer_ni_ytd_after = ctx.employer_ni_ytd_before + employer_ni

    employer_pension_rate = resolve_jurisdiction_parameter(rate_map, "employer-pension", _UK_PENSION_MIN_ENPLOYER, side="employer", country="UK")
    employer_pension = _round2(annual_gross * employer_pension_rate / Decimal("100") / periods_per_year)

    # Employee pension deduction — stays 0 (today's exact behavior) unless
    # an employee-side rate has been explicitly configured on the pension
    # row. Deliberately not defaulted to a nonzero statutory minimum here:
    # doing so would silently start deducting a new amount from every
    # existing UK organization's very next payslip. A Super Admin turns
    # this on explicitly via the Compliance UI when ready.
    employee_pension = Decimal("0")
    employee_pension_rate = resolve_jurisdiction_parameter(rate_map, "employer-pension", Decimal("0"), side="employee", country="UK")
    if employee_pension_rate > 0:
        qe_lower = resolve_jurisdiction_parameter(rate_map, "pension_qe_lower", _UK_PENSION_QE_LOWER, country="UK") / periods_per_year
        qe_upper = resolve_jurisdiction_parameter(rate_map, "pension_qe_upper", _UK_PENSION_QE_UPPER, country="UK") / periods_per_year
        basis = _param_text(rate_map, "pension_basis", "QUALIFYING_EARNINGS")
        pensionable_pay = _resolve_pensionable_pay(ctx, basis, qe_lower, qe_upper)
        employee_pension = _round2(pensionable_pay * employee_pension_rate / Decimal("100"))

    # Automatic Enrolment assessment (§13 gap-closure Part 3) — purely
    # informational, computed independently of the employee_pension
    # deduction above (which stays entirely tenant-configured either
    # way). None unless the switch is on AND date_of_birth is known —
    # never guesses an assessment for an employee with no birth date on
    # record.
    auto_enrolment_status = None
    if "UK" in _UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES and ctx.date_of_birth and ctx.pay_date:
        age = ctx.pay_date.year - ctx.date_of_birth.year - (
            (ctx.pay_date.month, ctx.pay_date.day) < (ctx.date_of_birth.month, ctx.date_of_birth.day)
        )
        auto_enrolment_status = assess_auto_enrolment(age, annual_gross, rate_map)

    # Tax week/month (§18.1 gap-closure Part 6) — pure calendar metadata,
    # zero payroll impact, so computed unconditionally whenever pay_date
    # is known (no rollout switch — there's no "wrong number" risk here
    # the way a money figure would carry). Needed for RTI reporting
    # (a future part of this roadmap) and for FPS's own tax-week field.
    tax_week = tax_month = None
    if ctx.pay_date:
        calendar = resolve_uk_tax_week_and_month(ctx.pay_date)
        tax_week, tax_month = calendar["tax_week"], calendar["tax_month"]

    # Sub-jurisdiction (Scotland/Wales/Northern Ireland) sets its own
    # income tax bands where configured — resolved upstream by
    # service.py's resolve_uk_configuration(), never compared here.
    slabs_for_tax = state_income_slabs if state_income_slabs else income_slabs
    annual_tax = _calculate_annual_tax_uk(annual_gross, slabs_for_tax, rate_map, tax_code=ctx.tax_code)
    tds = _round2(annual_tax / periods_per_year)

    # K-code 50% cap (ZP-TAX-UK-2026-27-001 §6.2: "tax deduction cannot
    # exceed 50% of pre-tax pay/pension for the pay period"). Applied to
    # THIS PERIOD'S actual pay (ctx.gross), not the annual figure — the
    # cap exists specifically to protect a single low/irregular period
    # from a K-code's added notional income, which an annual-level cap
    # would only catch under perfectly uniform pay all year. Dormant by
    # default (_UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES) — while off, a
    # K-code's tax stays uncapped, today's exact existing behavior.
    if "UK" in _UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES:
        default_pa_for_cap = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
        pa_for_cap = interpret_tax_code(ctx.tax_code, default_pa_for_cap, rate_map)["personal_allowance"]
        if pa_for_cap is not None and pa_for_cap < 0:
            k_code_cap_pct = resolve_jurisdiction_parameter(rate_map, "k_code_cap_pct", _UK_K_CODE_CAP_PCT, side="employee", country="UK")
            tds = min(tds, _round2(ctx.gross * k_code_cap_pct / Decimal("100")))

    # Deducted whenever an outstanding balance exists, at the plan's
    # threshold/rate — NOT capped by the balance itself: real Student
    # Loan repayment reduces the balance over time via cumulative YTD
    # tracking, which this engine doesn't yet do. study_loan_balance > 0
    # is only used as "does this employee currently have a loan to
    # repay," not as a per-payslip cap.
    # NOT capped by the balance itself: real Student Loan repayment
    # reduces the balance over time via cumulative YTD tracking, which
    # this engine doesn't yet do. study_loan_balance > 0 is only used as
    # "does this employee currently have a loan to repay."
    study_loan_deduction = Decimal("0")
    if ctx.study_loan_balance and ctx.study_loan_balance > 0:
        study_loan_deduction = _compute_loan_repayment(ctx.study_loan_plan, annual_gross, periods_per_year, rate_map)

    # Concurrent Postgraduate Loan (ZP-TAX-UK-2026-27-001 §10.2's own
    # worked example: Plan 5 + Postgraduate = two separate deduction
    # lines). Only ever additional to an UNDERGRADUATE plan — never
    # double-applied for an employee whose study_loan_plan is ALREADY
    # "UK_POSTGRAD" alone, which is fully handled by study_loan_deduction
    # above via the existing single-field mechanism. False/absent for
    # every employee today, so this is 0 unless explicitly configured.
    postgrad_loan_deduction = Decimal("0")
    if ctx.has_postgrad_loan and ctx.study_loan_plan != "UK_POSTGRAD":
        postgrad_loan_deduction = _compute_loan_repayment("UK_POSTGRAD", annual_gross, periods_per_year, rate_map)

    return dict(
        ni_employee=ni_employee,
        employer_ni=employer_ni,
        ytd_director_ni_gross=ytd_director_ni_gross_after,
        ytd_director_ni_employee_paid=ytd_director_ni_employee_paid_after,
        ytd_director_ni_employer_paid=ytd_director_ni_employer_paid_after,
        employer_apprenticeship_levy=employer_apprenticeship_levy,
        appr_levy_ytd_pay_bill_after=appr_levy_ytd_pay_bill_after,
        employer_ni_ytd_after=employer_ni_ytd_after,
        employer_pension=employer_pension,
        employee_pension=employee_pension,
        auto_enrolment_status=auto_enrolment_status,
        tax_week=tax_week, tax_month=tax_month,
        study_loan_deduction=study_loan_deduction,
        postgrad_loan_deduction=postgrad_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )


# ── Statutory Sick Pay — a per-sickness-episode payment, NOT a recurring ──
# payroll deduction. ZP-TAX-UK-2026-27-001 §12: "SSP is not recoverable" —
# unlike SMP/SPP/etc. (§11.1's 92%/109% employer recovery split), so no
# recovery logic belongs here at all. Deliberately a standalone function,
# same architecture as india.py's calculate_gratuity: this needs inputs
# (Average Weekly Earnings, qualifying-day counts, the illness episode's
# OWN start date) that don't exist in PayrollContext and aren't computed
# every recurring payroll cycle for every employee — only for whichever
# employee is actually off sick.

# 6 April 2026 is the real, fixed legal effective date of THIS specific
# reform (day-one entitlement, LEL test removed) — a historical/legal
# fact, not a jurisdiction-variable rate, same footing as the Payment of
# Gratuity Act's own formula constants in india.py.
_UK_SSP_2026_REFORM_DATE = date(2026, 4, 6)


def calculate_ssp(
    illness_start_date: date,
    qualifying_days_in_period: int,
    qualifying_days_per_week: int,
    average_weekly_earnings: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `ssp_amount` (Decimal, 0 when not eligible/not computable).

    §12: "the payable weekly amount is the LOWER of £123.25 and 80% of
    the employee's Average Weekly Earnings", allocated across qualifying
    days (§12.1 — the reference table there is just this weekly figure
    divided by qualifying_days_per_week, a pure derivation, not
    independent data requiring its own table).

    Both the weekly cap and the AWE percentage are genuinely statutory
    data HMRC republishes most tax years — no hardcoded fallback: fails
    closed (not a guessed rate) whenever either isn't configured.

    Fails closed for any illness_start_date before the 2026 reform too
    (§12.2: "absences beginning before 6 April 2026 can remain subject to
    transitional rules, including prior LEL/waiting-day treatment") —
    this document gives no figures for the PRIOR rules at all, so
    computing them would mean fabricating a number it never supplied;
    Tax Ops must handle any such pre-reform episode outside this
    function until a source document for the prior rules exists."""
    if illness_start_date < _UK_SSP_2026_REFORM_DATE:
        return {"eligible": False, "reason": "pre-6-April-2026 SSP rules are not implemented — no source figures for the prior LEL/waiting-day rules", "ssp_amount": Decimal("0")}

    weekly_cap_row = rate_map.get("ssp_weekly_cap")
    awe_pct_row = rate_map.get("ssp_awe_pct")
    if not weekly_cap_row or weekly_cap_row.flat_amount is None:
        return {"eligible": False, "reason": "ssp_weekly_cap not configured", "ssp_amount": Decimal("0")}
    if not awe_pct_row or awe_pct_row.employee_rate_pct is None:
        return {"eligible": False, "reason": "ssp_awe_pct not configured", "ssp_amount": Decimal("0")}
    if not qualifying_days_per_week:
        return {"eligible": False, "reason": "qualifying_days_per_week must be > 0", "ssp_amount": Decimal("0")}

    weekly_cap = weekly_cap_row.flat_amount
    awe_based_weekly = average_weekly_earnings * awe_pct_row.employee_rate_pct / Decimal("100")
    weekly_amount = min(weekly_cap, awe_based_weekly)
    daily_rate = weekly_amount / Decimal(qualifying_days_per_week)
    ssp_amount = _round2(daily_rate * Decimal(qualifying_days_in_period))

    return {"eligible": True, "reason": "", "ssp_amount": ssp_amount}


# ── Statutory Family Payments — SMP/SPP/SAP/ShPP/SPBP/SNCP (§11) ─────────
# Same standalone-function architecture as calculate_ssp above: each needs
# its own event inputs (an eligibility determination, AWE, which week of
# the claim this is) that PayrollContext doesn't carry and isn't computed
# every recurring cycle for every employee — only for whoever is actually
# on family leave.
#
# All six payment types share ONE published "Standard Rate for statutory
# family pay" each tax year (§11's own table: every type's steady-state
# row is identically "£194.32 or 90% of AWE, whichever is lower") — this
# is a genuine shared legal fact, not a coincidence being assumed
# permanent (contrast Class 1A/1B's four independently-configured rates
# above, which happen to share 15% this year but are stored separately on
# purpose). One shared rate/percentage pair, `fam_pay_flat_rate`/
# `fam_pay_awe_pct`, covers all six.
#
# SMP and SAP alone have a FIRST-6-WEEKS phase at a flat 90% of AWE with
# no flat-rate cap at all (§11's table: "first 6 weeks: 90% of AWE" has no
# "whichever is lower" clause) — SPP/ShPP/SPBP/SNCP have no such phase,
# every week is the standard capped rate.
_UK_FAMILY_PAY_TYPES = {"SMP", "SPP", "SAP", "SHPP", "SPBP", "SNCP"}
_UK_FAMILY_PAY_UNCAPPED_FIRST_WEEKS = {"SMP", "SAP"}
_UK_FAMILY_PAY_FIRST_WEEKS_COUNT = 6


def calculate_statutory_family_pay(
    payment_type: str,
    week_number: int,
    average_weekly_earnings: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `weekly_amount` (Decimal, 0 when not eligible/not computable).
    `payment_type` — one of SMP/SPP/SAP/SHPP/SPBP/SNCP. `week_number` is
    1-indexed within this claim (used only to detect SMP/SAP's first-6-
    weeks phase). No hardcoded fallback for the rate or the AWE
    percentage — fails closed whenever either isn't configured."""
    if payment_type not in _UK_FAMILY_PAY_TYPES:
        return {"eligible": False, "reason": f"unknown payment_type {payment_type!r}", "weekly_amount": Decimal("0")}

    awe_pct_row = rate_map.get("fam_pay_awe_pct")
    if not awe_pct_row or awe_pct_row.employee_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_awe_pct not configured", "weekly_amount": Decimal("0")}
    awe_based_weekly = average_weekly_earnings * awe_pct_row.employee_rate_pct / Decimal("100")

    if payment_type in _UK_FAMILY_PAY_UNCAPPED_FIRST_WEEKS and week_number <= _UK_FAMILY_PAY_FIRST_WEEKS_COUNT:
        return {"eligible": True, "reason": "", "weekly_amount": _round2(awe_based_weekly)}

    flat_rate_row = rate_map.get("fam_pay_flat_rate")
    if not flat_rate_row or flat_rate_row.flat_amount is None:
        return {"eligible": False, "reason": "fam_pay_flat_rate not configured", "weekly_amount": Decimal("0")}
    weekly_amount = min(flat_rate_row.flat_amount, awe_based_weekly)
    return {"eligible": True, "reason": "", "weekly_amount": _round2(weekly_amount)}


def calculate_family_pay_employer_recovery(
    prior_year_total_class1_nic: Decimal,
    payment_amount: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `recovery_amount` (Decimal). §11.1: employer recovers 92% of what
    they paid out, or 109% if their prior-year total Class 1 NIC was
    £45,000 or lower (the "small employer" relief). SSP is explicitly
    EXCLUDED from this — §11.1/AC-20 — never call this for an SSP
    payment; there is no recovery function for SSP at all in this file.
    No hardcoded fallback — fails closed whenever the threshold or either
    rate isn't configured."""
    threshold_row = rate_map.get("fam_pay_recov_thresh")
    small_rate_row = rate_map.get("fam_pay_recov_small")
    standard_rate_row = rate_map.get("fam_pay_recov_std")
    if not threshold_row or threshold_row.flat_amount is None:
        return {"eligible": False, "reason": "fam_pay_recov_thresh not configured", "recovery_amount": Decimal("0")}
    if not small_rate_row or small_rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_recov_small not configured", "recovery_amount": Decimal("0")}
    if not standard_rate_row or standard_rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_recov_std not configured", "recovery_amount": Decimal("0")}

    rate = small_rate_row.employer_rate_pct if prior_year_total_class1_nic <= threshold_row.flat_amount else standard_rate_row.employer_rate_pct
    return {"eligible": True, "reason": "", "recovery_amount": _round2(payment_amount * rate / Decimal("100"))}


# ── Class 1A / Class 1B — employer-only, event/annual charges, NOT a ────
# recurring payroll deduction. §9.3: benefits/termination awards/sporting
# testimonials (Class 1A) and PAYE Settlement Agreement items (Class 1B)
# each need their own event VALUE as input (a P11D benefit valuation, a
# termination package amount, a testimonial committee payment, a PSA
# item) — none of which this engine tracks per payslip, same standalone-
# function architecture as calculate_gratuity/calculate_ssp above.
#
# componentKey max 20 chars (payroll_contribution_rates.component_key is
# VARCHAR(20)) — "class1a_benefits_rate" etc. all exceed it, hence the
# shortened "c1a_*"/"c1b_*" keys below.
#
# All four charge types happen to share the same 15% rate this document
# gives (§9.3's own table lists them as 4 separate line items even
# though the number coincides) — configured as 4 INDEPENDENT rates
# rather than one shared one, same principle as this document's own
# "Preserve the C prefix" instruction for Welsh PAYE (§5.4): a coincidence
# this year is not a reason to assume they'll always move together.
_UK_CLASS_1A_1B_CHARGE_TYPES = {
    "BENEFITS": ("c1a_benefits_rate", None),
    "TERMINATION_AWARDS": ("c1a_term_rate", "c1a_term_thresh"),
    "SPORTING_TESTIMONIAL": ("c1a_testim_rate", "c1a_testim_thresh"),
    "PSA": ("c1b_psa_rate", None),
}


def calculate_class_1a_1b_charge(charge_type: str, amount: Decimal, rate_map: dict) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `charge_amount` (Decimal, 0 when not eligible/not computable).
    `charge_type` — one of BENEFITS/TERMINATION_AWARDS/
    SPORTING_TESTIMONIAL/PSA. TERMINATION_AWARDS and
    SPORTING_TESTIMONIAL charge only the EXCESS above their own
    threshold (§9.3: "above £30,000"/"above £100,000"); BENEFITS and PSA
    charge the full amount, since the document gives no threshold for
    either. No hardcoded fallback for the rate or either threshold —
    fails closed (not a guess) whenever the relevant one isn't
    configured."""
    if charge_type not in _UK_CLASS_1A_1B_CHARGE_TYPES:
        return {"eligible": False, "reason": f"unknown charge_type {charge_type!r}", "charge_amount": Decimal("0")}
    rate_key, threshold_key = _UK_CLASS_1A_1B_CHARGE_TYPES[charge_type]
    rate_row = rate_map.get(rate_key)
    if not rate_row or rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": f"{rate_key} not configured", "charge_amount": Decimal("0")}

    threshold = Decimal("0")
    if threshold_key:
        threshold_row = rate_map.get(threshold_key)
        if not threshold_row or threshold_row.flat_amount is None:
            return {"eligible": False, "reason": f"{threshold_key} not configured", "charge_amount": Decimal("0")}
        threshold = threshold_row.flat_amount

    chargeable = max(Decimal("0"), amount - threshold)
    charge_amount = _round2(chargeable * rate_row.employer_rate_pct / Decimal("100"))
    return {"eligible": True, "reason": "", "charge_amount": charge_amount}


# ── Apprenticeship Levy — banded on the ORGANIZATION's aggregate annual ──
# statutory pay bill, NOT any single employee's own pay (§14: "Cumulative
# charge on statutory pay bill"). Same org-level-accumulator-banded shape
# and cumulative-period-telescoping technique as Canada's Ontario/BC EHT
# (canada.py's _calculate_on_eht_period_amount) — computed as
# annual_levy(cumulative_after) − annual_levy(cumulative_before) so the
# correct annual total accrues exactly once regardless of how many pay
# periods occur or when the allowance is exhausted mid-year. Genuinely
# new statutory data, no hardcoded fallback: an unconfigured rate or
# allowance resolves to "not computable" (returns None, the caller's own
# signal to treat this period's levy as 0 — the levy calculation service.py
# wiring is a separate follow-up, same as this session's other
# standalone-first infrastructure).
def _annual_apprenticeship_levy_amount(total_pay_bill: Decimal, rate: Decimal, allowance: Decimal) -> Decimal:
    gross_levy = total_pay_bill * rate / Decimal("100")
    return max(Decimal("0"), gross_levy - allowance)


def calculate_apprenticeship_levy_period_amount(gross: Decimal, org_ytd_pay_bill_before: Decimal, rate_map: dict) -> Decimal | None:
    """Returns this period's levy charge, or None when
    "appr_levy_rate"/"appr_levy_allowance" aren't configured (fails
    closed rather than guessing 0.5%/£15,000 — this document's own
    figures, but still genuinely statutory data subject to change, same
    footing as every other UK rate/threshold in this file)."""
    rate_row = rate_map.get("appr_levy_rate")
    allowance_row = rate_map.get("appr_levy_allowance")
    if not rate_row or rate_row.employer_rate_pct is None:
        return None
    if not allowance_row or allowance_row.flat_amount is None:
        return None
    rate = rate_row.employer_rate_pct
    allowance = allowance_row.flat_amount
    total_after = org_ytd_pay_bill_before + gross
    return _round2(
        _annual_apprenticeship_levy_amount(total_after, rate, allowance)
        - _annual_apprenticeship_levy_amount(org_ytd_pay_bill_before, rate, allowance)
    )


# ── Employment Allowance — a REPORTING/remittance-level offset, NOT a ───
# per-payslip calculation at all (§14: "Employer eligibility/claim state;
# reduce eligible secondary Class 1 NIC liability; claim through EPS").
# It never changes any individual employee's own employer_ni figure —
# only how much of the ORG's cumulative employer NI bill actually gets
# remitted to HMRC. Deliberately a standalone function, called on demand
# (e.g. by a future EPS/remittance report) against the org's cumulative
# employer_ni_ytd_after accumulator (calculate()'s own tracking above) —
# never wired into calculate()'s per-payslip return dict, since there is
# no per-payslip number for it to produce.
#
# "Employer eligibility/claim state" (§14) is deliberately NOT modeled
# here as an eligibility RULE (e.g. excluded sectors/company sizes) — the
# document names the concept but gives no criteria, so this only reads
# whether the employer has actually CLAIMED it (a plain boolean fact,
# not a computed eligibility test) rather than guessing who qualifies.
def calculate_employment_allowance_net_liability(cumulative_employer_ni: Decimal, employer_has_claimed: bool, rate_map: dict) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str),
    `net_liability` (Decimal — what the org actually owes HMRC after the
    allowance), and `allowance_remaining` (Decimal). No hardcoded
    fallback for the allowance cap — fails closed when unconfigured."""
    if not employer_has_claimed:
        return {"eligible": False, "reason": "employer has not claimed Employment Allowance", "net_liability": cumulative_employer_ni, "allowance_remaining": Decimal("0")}
    allowance_row = rate_map.get("empl_allowance_cap")
    if not allowance_row or allowance_row.flat_amount is None:
        return {"eligible": False, "reason": "empl_allowance_cap not configured", "net_liability": cumulative_employer_ni, "allowance_remaining": Decimal("0")}
    allowance_cap = allowance_row.flat_amount
    net_liability = max(Decimal("0"), cumulative_employer_ni - allowance_cap)
    allowance_remaining = max(Decimal("0"), allowance_cap - cumulative_employer_ni)
    return {"eligible": True, "reason": "", "net_liability": _round2(net_liability), "allowance_remaining": _round2(allowance_remaining)}


# ── Mileage Allowance Payments & Advisory Fuel Rates (§16) ──────────────
# (ZP-TAX-UK-2026-27-001 gap-closure Part 4, 2026-09-09). An expense-
# reimbursement calculator, not a payroll deduction — same standalone,
# on-demand architecture as calculate_ssp/calculate_statutory_family_pay
# above: a mileage claim or a fuel-rate lookup is an event a payroll
# processor triggers when an employee submits an expense, not something
# computed every recurring pay cycle for every employee. §16.1's own
# "Store as separate tax/NI mileage rule asset" and §16.2's "must be
# stored as independent effective-dated tables and not baked into the
# annual tax-year object" are both satisfied by these reading plain
# ContributionRate rows (which Part 1A's row-level effective dating
# already covers) rather than anything hardcoded in this file.
_UK_MILEAGE_CAR_MILE_THRESHOLD = Decimal("10000")


def calculate_mileage_reimbursement(
    vehicle_type: str, business_miles_this_claim: Decimal, ytd_business_miles_before: Decimal, rate_map: dict,
) -> dict:
    """`vehicle_type` — one of CAR/MOTORCYCLE/CYCLE. `ytd_business_miles_
    before` is this employee's cumulative CAR business mileage so far
    this tax year BEFORE this claim (only meaningful for CAR — the
    10,000-mile threshold is the one place tax and NI approved rates
    diverge; Motorcycle/Cycle have no threshold at all, so any value is
    accepted but unused for them).

    Returns a dict with `eligible` (bool), `reason` (str),
    `tax_free_amount` (Decimal — the maximum HMRC-approved amount
    reimbursable free of tax) and `ni_free_amount` (Decimal — the
    maximum free of Class 1 NIC; identical to tax_free_amount for
    Motorcycle/Cycle, diverges from it for Car past the threshold).
    No hardcoded fallback for any rate — fails closed whenever the
    relevant key(s) aren't configured, same discipline as every other
    standalone UK calculator in this file."""
    vehicle_type = (vehicle_type or "").upper()
    if vehicle_type not in ("CAR", "MOTORCYCLE", "CYCLE"):
        return {"eligible": False, "reason": f"unknown vehicle_type {vehicle_type!r}", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}
    if business_miles_this_claim is None or business_miles_this_claim < 0:
        return {"eligible": False, "reason": "business_miles_this_claim must be >= 0", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}

    if vehicle_type in ("MOTORCYCLE", "CYCLE"):
        key = "mileage_motorcycle" if vehicle_type == "MOTORCYCLE" else "mileage_cycle"
        rate_row = rate_map.get(key)
        if not rate_row or rate_row.flat_amount is None:
            return {"eligible": False, "reason": f"{key} not configured", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}
        amount = _round2(business_miles_this_claim * rate_row.flat_amount)
        return {"eligible": True, "reason": "", "tax_free_amount": amount, "ni_free_amount": amount}

    # CAR — tax-approved rate steps down after 10,000 cumulative business
    # miles in the tax year; the NI-approved rate never steps down.
    first_rate_row = rate_map.get("mileage_car_first_10k")
    after_rate_row = rate_map.get("mileage_car_after_10k")
    ni_rate_row = rate_map.get("mileage_car_ni")
    if not first_rate_row or first_rate_row.flat_amount is None:
        return {"eligible": False, "reason": "mileage_car_first_10k not configured", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}
    if not after_rate_row or after_rate_row.flat_amount is None:
        return {"eligible": False, "reason": "mileage_car_after_10k not configured", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}
    if not ni_rate_row or ni_rate_row.flat_amount is None:
        return {"eligible": False, "reason": "mileage_car_ni not configured", "tax_free_amount": Decimal("0"), "ni_free_amount": Decimal("0")}

    ytd_before = ytd_business_miles_before or Decimal("0")
    ytd_after = ytd_before + business_miles_this_claim
    miles_at_first_rate = max(Decimal("0"), min(ytd_after, _UK_MILEAGE_CAR_MILE_THRESHOLD) - ytd_before)
    miles_at_after_rate = business_miles_this_claim - miles_at_first_rate
    tax_free_amount = _round2(miles_at_first_rate * first_rate_row.flat_amount + miles_at_after_rate * after_rate_row.flat_amount)
    ni_free_amount = _round2(business_miles_this_claim * ni_rate_row.flat_amount)
    return {"eligible": True, "reason": "", "tax_free_amount": tax_free_amount, "ni_free_amount": ni_free_amount}


_UK_ADVISORY_FUEL_RATE_KEYS_BY_FUEL_AND_BAND = {
    ("PETROL", "LE_1400"): "afr_petrol_le1400",
    ("PETROL", "1401_2000"): "afr_petrol_1401_2000",
    ("PETROL", "GT_2000"): "afr_petrol_gt2000",
    ("LPG", "LE_1400"): "afr_lpg_le1400",
    ("LPG", "1401_2000"): "afr_lpg_1401_2000",
    ("LPG", "GT_2000"): "afr_lpg_gt2000",
    ("DIESEL", "LE_1600"): "afr_diesel_le1600",
    ("DIESEL", "1601_2000"): "afr_diesel_1601_2000",
    ("DIESEL", "GT_2000"): "afr_diesel_gt2000",
}


def resolve_advisory_fuel_rate(fuel_type: str, engine_band: str, rate_map: dict) -> dict:
    """`fuel_type` — PETROL/LPG/DIESEL/ELECTRIC. `engine_band` — for
    PETROL/LPG: LE_1400/1401_2000/GT_2000; for DIESEL: LE_1600/1601_2000/
    GT_2000 (diesel's own bands are shifted from petrol/LPG's, per §16.2 —
    never conflate them); for ELECTRIC: HOME/PUBLIC (a charger type, not
    an engine size — there is no engine to band by).

    Returns a dict with `eligible` (bool), `reason` (str), and
    `rate_per_mile` (Decimal). No hardcoded fallback — fails closed
    whenever the specific fuel/band combination isn't configured, same
    as every other UK rate in this file. Advisory fuel rates are
    periodically updated (§16.2) — callers resolve a rate_map that has
    already been date-resolved via Part 1A's row-level effective dating,
    this function itself has no notion of "as of which date"."""
    fuel_type = (fuel_type or "").upper()
    engine_band = (engine_band or "").upper()
    if fuel_type == "ELECTRIC":
        key = {"HOME": "afr_electric_home", "PUBLIC": "afr_electric_public"}.get(engine_band)
        if not key:
            return {"eligible": False, "reason": f"unknown charger type {engine_band!r} for ELECTRIC — must be HOME or PUBLIC", "rate_per_mile": Decimal("0")}
    else:
        key = _UK_ADVISORY_FUEL_RATE_KEYS_BY_FUEL_AND_BAND.get((fuel_type, engine_band))
        if not key:
            return {"eligible": False, "reason": f"unknown fuel_type/engine_band combination {fuel_type!r}/{engine_band!r}", "rate_per_mile": Decimal("0")}
    rate_row = rate_map.get(key)
    if not rate_row or rate_row.flat_amount is None:
        return {"eligible": False, "reason": f"{key} not configured", "rate_per_mile": Decimal("0")}
    return {"eligible": True, "reason": "", "rate_per_mile": rate_row.flat_amount}


# ── National Minimum Wage compliance validation (§15) ────────────────────
# (ZP-TAX-UK-2026-27-001 gap-closure Part 5, 2026-09-09). Explicitly a
# PAY-COMPLIANCE check, not a payroll tax — the document's own words:
# "Do not implement NMW as a simple gross-pay comparison... The rate
# table is only one input to a separate minimum-wage compliance
# calculation." This function does the one comparison the document DOES
# give a complete rule for (countable pay ÷ hours worked, against the
# correct age/apprentice-tier rate) — it deliberately does NOT attempt
# accommodation-offset or deduction-eligibility rules, which the document
# flags as real complexity without giving this pack's own figures for.
# service.py's caller is responsible for having already reduced
# nmw_countable_pay by whatever the org's own policy says shouldn't
# count, before calling this.
_UK_APPRENTICE_FIRST_YEAR_DAYS = 365


def resolve_nmw_rate(age: int | None, is_apprentice: bool, apprenticeship_start_date, as_of_date, rate_map: dict) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `rate_per_hour` (Decimal). An apprentice UNDER 19 gets the apprentice
    rate for the whole apprenticeship (no time limit); an apprentice AGED
    19+ only gets it during their first year (§15's own category table),
    then reverts to their ordinary age-band rate. No hardcoded fallback
    for any of the 5 rates — fails closed whenever the relevant key isn't
    configured."""
    if age is None:
        return {"eligible": False, "reason": "age is unknown (no date_of_birth on record)", "rate_per_hour": Decimal("0")}

    key = None
    if is_apprentice and age < 19:
        key = "nmw_apprentice_under_19"
    elif is_apprentice and apprenticeship_start_date and as_of_date and (as_of_date - apprenticeship_start_date).days < _UK_APPRENTICE_FIRST_YEAR_DAYS:
        key = "nmw_apprentice_19plus_yr1"
    elif age >= 21:
        key = "nmw_age_21_plus"
    elif age >= 18:
        key = "nmw_age_18_20"
    else:
        key = "nmw_under_18"

    rate_row = rate_map.get(key)
    if not rate_row or rate_row.flat_amount is None:
        return {"eligible": False, "reason": f"{key} not configured", "rate_per_hour": Decimal("0")}
    return {"eligible": True, "reason": "", "rate_per_hour": rate_row.flat_amount}


def validate_nmw_compliance(
    nmw_countable_pay: Decimal, hours_worked: Decimal, age: int | None,
    is_apprentice: bool, apprenticeship_start_date, as_of_date, rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str),
    `applicable_rate` (Decimal), `effective_hourly_rate` (Decimal),
    `compliant` (bool), and `shortfall_amount` (Decimal — the additional
    amount that would need to be paid this period to reach the
    applicable rate; 0 when compliant). Fails closed (eligible=False,
    compliant left at its default False) whenever hours_worked is zero/
    unknown — a real "0 hours this period" case can't produce a
    meaningful hourly rate, and this never fabricates one."""
    if not hours_worked or hours_worked <= 0:
        return {"eligible": False, "reason": "hours_worked must be greater than 0", "applicable_rate": Decimal("0"), "effective_hourly_rate": Decimal("0"), "compliant": False, "shortfall_amount": Decimal("0")}
    rate_result = resolve_nmw_rate(age, is_apprentice, apprenticeship_start_date, as_of_date, rate_map)
    if not rate_result["eligible"]:
        return {"eligible": False, "reason": rate_result["reason"], "applicable_rate": Decimal("0"), "effective_hourly_rate": Decimal("0"), "compliant": False, "shortfall_amount": Decimal("0")}

    applicable_rate = rate_result["rate_per_hour"]
    effective_hourly_rate = _round2((nmw_countable_pay or Decimal("0")) / hours_worked)
    compliant = effective_hourly_rate >= applicable_rate
    shortfall_amount = Decimal("0") if compliant else _round2((applicable_rate * hours_worked) - nmw_countable_pay)
    return {
        "eligible": True, "reason": "", "applicable_rate": applicable_rate,
        "effective_hourly_rate": effective_hourly_rate, "compliant": compliant, "shortfall_amount": shortfall_amount,
    }


# ── Tax-week/month calendar + week 53/54/56 (§7.2/§18.1) ─────────────────
# (ZP-TAX-UK-2026-27-001 gap-closure Part 6, 2026-09-09). Pure calendar
# arithmetic — no rate_map/jurisdiction dependency at all, unlike every
# other function in this file. Genuinely needed for RTI reporting (Part 9
# of this roadmap) and for the week-53/54/56 non-cumulative-basis rule,
# neither of which any part of this codebase has ever computed before.
def resolve_uk_tax_week_and_month(pay_date: date) -> dict:
    """Returns {"tax_year_start", "tax_year_end", "tax_week", "tax_month"}
    for `pay_date`. Tax week 1 runs 6 Apr-12 Apr, then every 7 days;
    tax week is CAPPED at 53 (§7.2's "odd day(s) after week 52 treated as
    week 53") — Python's own date subtraction already accounts for leap
    years correctly, so this needs no special leap-year branch: a tax
    year with 366 days (a Feb 29 falls inside 6 Apr-5 Apr) simply has 2
    "extra" days past week 52 instead of 1, and both land in week 53 via
    the same floor-division formula. Tax month 1 runs 6 Apr-5 May, then
    every calendar month 6th-to-5th, running 1-12.

    This function alone does NOT know whether `pay_date` is a real
    "extra payday" (the employee's 53rd/27th/14th payment this tax year)
    — that depends on the employee's own payment history, which this
    pure function has no access to. See detect_uk_extra_payday for that,
    driven by an explicit, caller-supplied payment count rather than a
    guess at payday alignment."""
    tax_year_start = date(pay_date.year, 4, 6) if (pay_date.month, pay_date.day) >= (4, 6) else date(pay_date.year - 1, 4, 6)
    tax_year_end = date(tax_year_start.year + 1, 4, 5)

    days_since_start = (pay_date - tax_year_start).days
    tax_week = min(53, (days_since_start // 7) + 1)

    month_offset = (pay_date.year - tax_year_start.year) * 12 + (pay_date.month - tax_year_start.month)
    if pay_date.day < 6:
        month_offset -= 1
    tax_month = (month_offset % 12) + 1

    return {
        "tax_year_start": tax_year_start, "tax_year_end": tax_year_end,
        "tax_week": tax_week, "tax_month": tax_month,
    }


# Weekly's own tax week IS the sequential payment number (each payment
# covers exactly 1 tax week); Fortnightly's Nth payment covers tax weeks
# (2N-1, 2N); Four-weekly's Nth payment covers tax weeks (4N-3..4N). The
# "extra" (53rd/27th/14th) payment is the one whose LAST covered tax week
# would be 53 or higher — i.e. it no longer fits a clean whole number of
# periods into the 52-week body of the tax year.
_UK_EXTRA_PAYDAY_PERIOD_NUMBER = {"Weekly": 53, "Fortnightly": 27, "FourWeekly": 14}
_UK_EXTRA_PAYDAY_REPORTING_IDENTIFIER = {"Weekly": 53, "Fortnightly": 54, "FourWeekly": 56}


def detect_uk_extra_payday(pay_frequency: str, pay_period_sequence_number: int) -> dict:
    """`pay_period_sequence_number` — which sequential payment this is
    for the employee since their tax year started (1st, 2nd, ...) —
    supplied by the caller rather than inferred from the pay date alone:
    a real fortnightly/four-weekly payday doesn't necessarily land on a
    clean multiple-of-14/28-days offset from 6 April (it follows
    whatever cycle the employer actually pays on), so guessing the
    period number from the calendar date risks being wrong for a
    real-world payroll. Only Weekly's own tax week (from
    resolve_uk_tax_week_and_month) IS this number directly, since every
    week has exactly one payment by definition.

    Returns {"is_extra_payday": bool, "reporting_identifier": int|None}
    — 53 (Weekly), 54 (Fortnightly), or 56 (FourWeekly) per §7.2's own
    table, only when this is genuinely the extra period; None for any
    other frequency this document doesn't publish an extra-payday rule
    for (e.g. Monthly, which always has exactly 12 payments and never an
    "extra" one)."""
    extra_at = _UK_EXTRA_PAYDAY_PERIOD_NUMBER.get(pay_frequency)
    if extra_at is None:
        return {"is_extra_payday": False, "reporting_identifier": None}
    is_extra = pay_period_sequence_number == extra_at
    return {
        "is_extra_payday": is_extra,
        "reporting_identifier": _UK_EXTRA_PAYDAY_REPORTING_IDENTIFIER[pay_frequency] if is_extra else None,
    }


# ── Court-Ordered Deductions — England & Wales AEOs, Scottish ───────────
# arrestments, Northern Ireland orders (§17 gap-closure Part 8,
# 2026-09-09). Standalone, on-demand functions — same architecture as
# calculate_ssp/calculate_mileage_reimbursement/validate_nmw_compliance
# above: a court order is an event a payroll processor records, not
# something computed every recurring pay cycle for every employee.
#
# The document is explicit that Scotland's arrestment rules must NOT be
# computed with England & Wales's AEO logic — this is why there are
# THREE separate calculation functions below rather than one function
# with a jurisdiction branch buried inside it. An order's own specified
# rate/amount/protected-earnings value ALWAYS takes precedence over any
# generic published band (§17's own instruction) — every function below
# checks the order's own override fields FIRST, before ever consulting a
# banded slabs table.
#
# IMPORTANT — deliberately shipped with ZERO seed data this pass: the
# source document's own §17 banded-percentage tables (England & Wales
# AEO standard/priority rates, Scotland's Earnings Arrestment table,
# Northern Ireland's equivalent) were not available to re-verify against
# at implementation time (the document was reviewed in an earlier part
# of this engagement and its full text was no longer in hand when this
# part was built). Every lookup below fails closed — same discipline as
# every other genuinely new UK statutory table this session (Mileage/
# AFR/NMW all shipped with zero seed data on day one too) — rather than
# risk transcribing a wrong figure from general knowledge, exactly the
# class of mistake the Part 4 mileage-rate transcription slip (45p vs
# the document's real 55p) already demonstrated can happen. Real band
# data should be entered from the actual source document, as
# TaxSlab rows with rule_type AEO_EW_STANDARD / AEO_NI_STANDARD /
# ARREST_SCOT_WK / ARREST_SCOT_FN / ARREST_SCOT_4W / ARREST_SCOT_MO,
# before this is relied on for any order that doesn't specify its own
# fixed rate/amount.
_UK_COURT_ORDER_JURISDICTIONS = {"ENGLAND_WALES", "SCOTLAND", "NORTHERN_IRELAND"}
_UK_ARRESTMENT_SCOTLAND_FREQUENCY_SUFFIX = {
    "Weekly": "WK", "Fortnightly": "FN", "FourWeekly": "4W", "Monthly": "MO",
}


def _lookup_band_rate(attachable_earnings: Decimal, band_slabs: list) -> Decimal | None:
    for slab in sorted(band_slabs, key=lambda s: s.min_amount):
        if attachable_earnings >= slab.min_amount and (slab.max_amount is None or attachable_earnings <= slab.max_amount):
            return slab.rate_pct
    return None


def calculate_court_order_deduction_england_wales(
    attachable_earnings: Decimal,
    fixed_deduction_rate_pct: Decimal | None,
    fixed_deduction_amount: Decimal | None,
    protected_earnings_amount: Decimal | None,
    slabs: list,
) -> dict:
    """England & Wales Attachment of Earnings Orders. Returns `eligible`
    (bool), `reason` (str), `deduction_amount` (Decimal). Checked in
    order: the order's own fixed_deduction_amount, then its own
    fixed_deduction_rate_pct, then the published AEO_EW_STANDARD band
    table — whichever is set first wins; fails closed only when NONE of
    the three is available."""
    protected = protected_earnings_amount or Decimal("0")
    headroom = max(Decimal("0"), attachable_earnings - protected)

    if fixed_deduction_amount is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(fixed_deduction_amount, headroom)}
    if fixed_deduction_rate_pct is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * fixed_deduction_rate_pct / Decimal("100")), headroom)}

    band_slabs = [s for s in (slabs or []) if getattr(s, "rule_type", None) == "AEO_EW_STANDARD"]
    if not band_slabs:
        return {"eligible": False, "reason": "no order-specific rate set and AEO_EW_STANDARD band table not configured", "deduction_amount": Decimal("0")}
    rate = _lookup_band_rate(attachable_earnings, band_slabs)
    if rate is None:
        return {"eligible": False, "reason": "attachable_earnings did not match any configured AEO_EW_STANDARD band", "deduction_amount": Decimal("0")}
    return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * rate / Decimal("100")), headroom)}


def calculate_court_order_deduction_scotland(
    attachable_earnings: Decimal,
    pay_frequency: str,
    fixed_deduction_rate_pct: Decimal | None,
    fixed_deduction_amount: Decimal | None,
    protected_earnings_amount: Decimal | None,
    slabs: list,
) -> dict:
    """Scottish arrestments (Earnings Arrestment / Current Maintenance
    Arrestment / Conjoined Arrestment Order) — a DELIBERATELY separate
    function from the England & Wales one above, per §17's own
    instruction not to reuse that logic for Scotland. pay_frequency
    matters here because Scotland's own published tables are
    frequency-specific (weekly/fortnightly/four-weekly/monthly bands
    each differ) — the band table is looked up per-frequency for that
    reason, via a dedicated rule_type per frequency."""
    protected = protected_earnings_amount or Decimal("0")
    headroom = max(Decimal("0"), attachable_earnings - protected)

    if fixed_deduction_amount is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(fixed_deduction_amount, headroom)}
    if fixed_deduction_rate_pct is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * fixed_deduction_rate_pct / Decimal("100")), headroom)}

    suffix = _UK_ARRESTMENT_SCOTLAND_FREQUENCY_SUFFIX.get(pay_frequency)
    if suffix is None:
        return {"eligible": False, "reason": f"Scottish arrestment bands are not defined for pay_frequency {pay_frequency!r}", "deduction_amount": Decimal("0")}
    rule_type = f"ARREST_SCOT_{suffix}"
    band_slabs = [s for s in (slabs or []) if getattr(s, "rule_type", None) == rule_type]
    if not band_slabs:
        return {"eligible": False, "reason": f"no order-specific rate set and {rule_type} band table not configured", "deduction_amount": Decimal("0")}
    rate = _lookup_band_rate(attachable_earnings, band_slabs)
    if rate is None:
        return {"eligible": False, "reason": f"attachable_earnings did not match any configured {rule_type} band", "deduction_amount": Decimal("0")}
    return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * rate / Decimal("100")), headroom)}


def calculate_court_order_deduction_northern_ireland(
    attachable_earnings: Decimal,
    fixed_deduction_rate_pct: Decimal | None,
    fixed_deduction_amount: Decimal | None,
    protected_earnings_amount: Decimal | None,
    slabs: list,
) -> dict:
    """Northern Ireland's own order type — again a separate function
    (same reasoning as Scotland above), against its own AEO_NI_STANDARD
    band table, since NI's published rates are a distinct legal
    instrument even where structurally similar to England & Wales's."""
    protected = protected_earnings_amount or Decimal("0")
    headroom = max(Decimal("0"), attachable_earnings - protected)

    if fixed_deduction_amount is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(fixed_deduction_amount, headroom)}
    if fixed_deduction_rate_pct is not None:
        return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * fixed_deduction_rate_pct / Decimal("100")), headroom)}

    band_slabs = [s for s in (slabs or []) if getattr(s, "rule_type", None) == "AEO_NI_STANDARD"]
    if not band_slabs:
        return {"eligible": False, "reason": "no order-specific rate set and AEO_NI_STANDARD band table not configured", "deduction_amount": Decimal("0")}
    rate = _lookup_band_rate(attachable_earnings, band_slabs)
    if rate is None:
        return {"eligible": False, "reason": "attachable_earnings did not match any configured AEO_NI_STANDARD band", "deduction_amount": Decimal("0")}
    return {"eligible": True, "reason": "", "deduction_amount": min(_round2(attachable_earnings * rate / Decimal("100")), headroom)}


def calculate_court_ordered_deductions(orders: list, attachable_earnings: Decimal, pay_frequency: str, slabs: list) -> dict:
    """Given every ACTIVE court order for one employee this period,
    already sorted by the caller with highest priority (lowest priority
    number) first, calculates each order's deduction in that sequence —
    each subsequent order is computed against what's LEFT of
    attachable_earnings after every higher-priority order's own
    deduction (§17's own priority-ordering requirement: a lower-priority
    order can never reach into earnings a higher-priority order already
    claimed). `orders` — list of dicts with `id`, `jurisdiction`,
    `fixed_deduction_rate_pct`, `fixed_deduction_amount`,
    `protected_earnings_amount`.

    Returns {"total_deduction": Decimal, "orders": [{"order_id",
    "eligible", "reason", "deduction_amount"}, ...]} — one entry per
    order in the order given, regardless of eligibility, so a caller can
    see exactly why any individual order didn't produce a deduction."""
    remaining_earnings = attachable_earnings
    total = Decimal("0")
    results = []
    for order in orders:
        jurisdiction = order.get("jurisdiction")
        if jurisdiction == "SCOTLAND":
            result = calculate_court_order_deduction_scotland(
                remaining_earnings, pay_frequency,
                order.get("fixed_deduction_rate_pct"), order.get("fixed_deduction_amount"),
                order.get("protected_earnings_amount"), slabs,
            )
        elif jurisdiction == "ENGLAND_WALES":
            result = calculate_court_order_deduction_england_wales(
                remaining_earnings,
                order.get("fixed_deduction_rate_pct"), order.get("fixed_deduction_amount"),
                order.get("protected_earnings_amount"), slabs,
            )
        elif jurisdiction == "NORTHERN_IRELAND":
            result = calculate_court_order_deduction_northern_ireland(
                remaining_earnings,
                order.get("fixed_deduction_rate_pct"), order.get("fixed_deduction_amount"),
                order.get("protected_earnings_amount"), slabs,
            )
        else:
            result = {"eligible": False, "reason": f"unknown jurisdiction {jurisdiction!r}", "deduction_amount": Decimal("0")}
        results.append({"order_id": order.get("id"), **result})
        if result["eligible"]:
            total += result["deduction_amount"]
            remaining_earnings = max(Decimal("0"), remaining_earnings - result["deduction_amount"])
    return {"total_deduction": _round2(total), "orders": results}

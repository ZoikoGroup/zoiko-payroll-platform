"""
modules/payroll/engine/countries/puerto_rico.py
--------------------------------------------------
Puerto Rico (PR) — Phase 1 statutory build (ZP-PR-ENG-001).

Puerto Rico is a DUAL-JURISDICTION package (local Hacienda withholding +
DTRH unemployment/SINOT PLUS an independently-computed federal-equivalent
layer — Social Security, Medicare/Additional Medicare, FUTA), but it is
architecturally a SIBLING of every other Caribbean country in this
codebase (Barbados/Cayman/DR/Guyana/Jamaica/Bahamas/Trinidad), never a
fork of or dependency on engine/countries/us.py. This module does not
import from us.py and does not touch any `country_code == "US"` branch
anywhere in service.py — every figure below (including the SS/Medicare/
FUTA math, which happens to be numerically identical to mainland federal
rates because it is the same federal law) is computed independently, the
same "one file fully owns its own math" doctrine every Caribbean country
already follows (see cayman_islands.py/trinidad_and_tobago.py's own
docstrings for the identical convention).

Six independent statutory obligations (never blended into one number —
ZP-PR-ENG-001's own "UX law", never a single blended tax %):

  1. Local Hacienda income-tax withholding — annualized bracket method
     (same "annualize this period, run the bracket table, de-annualize"
     shape Barbados/Jamaica/Dominican Republic/Trinidad already use via
     shared._calculate_annual_tax). Bands come from ctx.slabs (5 real
     current Hacienda brackets — 0%/7%/14%/25%/33% at 9,000/25,000/
     41,500/61,500 — reverse-verified against ZP-PR-ENG-001 §13 fixture
     F1's own cross-check: $48,000 annual gross − $3,500 personal
     exemption = $44,500 taxable basis → bracket-summed tax is exactly
     $4,180.00, matching the spec's own published cross-check figure to
     the cent). PR-006/PR-008: the personal exemption is the current
     Form 499 R-4/R-4.1 default (no dependents/deduction-allowance
     modelling yet — Phase 2 scope, same as Trinidad's TD1-driven
     deductions being deferred in its own Phase 1). ZP-PR-ENG-001 itself
     discloses this is an ENGINEERING CROSS-CHECK, not the exact official
     periodic-table/rounding method Hacienda actually publishes — see the
     spec's own §13 F1 note ("Production must use official table output,
     not this cross-check formula"); replacing ctx.slabs with the real
     periodic table (once obtained) requires no code change here, only a
     canonical-pack data update. Reused field: `tds`.

  2. Social Security — employee 6.2% / employer 6.2%, $184,500 2026 wage
     base (SSA 2026 figure, same number mainland federal law uses because
     it IS the same federal law — computed here independently, not read
     from us.py). Reused fields: `social_security` / `employer_social_security`.

  3. Medicare — employee 1.45% / employer 1.45%, no wage ceiling, plus
     Additional Medicare (employee-only 0.9% on employer-paid YTD Medicare
     wages above the $200,000 threshold — PR-015: triggered by employer-
     paid YTD wages, NOT filing status, since no filing-status field for
     this purpose exists on a PR employee yet). Both folded into the one
     `medicare` field (this engine has no separate "additional medicare"
     PayslipItem line item; see cross-check fixture F3's own combined
     framing). Reused fields: `medicare` / `employer_medicare`.

  4. FUTA-equivalent — employer-only, GROSS 6.0% rate on the first $7,000
     of wages per employee/year (PR-016: never hard-coded as a net 0.6% —
     credit/credit-reduction reconciliation is an annual Form 940 filing-
     layer concern, out of scope for this per-period engine). Reused
     field: `employer_futa`.

  5. Puerto Rico Unemployment Insurance (DTRH) — employer-only, $7,000
     wage limit/employee/year, rate is genuinely employer-specific
     (PR-018: "missing rate = BLOCKED for production liability
     calculation; never use a generic statewide percentage"). PR-018's
     literal text calls for a true employer-specific agency-notice
     mechanism (the same EmployerTaxProfile table US SUI/Canada WCB use)
     — DEFERRED here for consistency with every other Caribbean country's
     Phase 1 build, none of which use EmployerTaxProfile yet either; this
     module instead reads the SAME canonical/org-scoped ContributionRate
     row every other Caribbean statutory rate already uses
     (component_key "pr_unemployment"), but with NO hardcoded rate
     default and an explicit `pr_unemployment_rate_configured` flag in
     the returned dict — an org with no rate configured computes $0
     employer PR unemployment rather than a fabricated percentage,
     honoring PR-018's "never guess" intent within today's existing
     mechanism. A true agency-notice-driven EmployerTaxProfile model is
     Phase 2 scope. Reused field (closest existing generic slot — a
     territory-level unemployment-insurance program, the same shape a US
     state's own SUI already occupies): `employer_sui`.

  6. SINOT (temporary non-occupational disability) — total statutory rate
     0.60% of wages up to $9,000/employee/year, employee share capped at
     0.30% by law (PR-019), employer bears the total minus whatever the
     employee share is. Modelled as two independent rate rows so
     PR-019's "employee+employer reconcile to the total" holds by
     construction (not a separately-entered employer number that could
     drift) — `pr_sinot` employee_rate_pct/employer_rate_pct, defaulting
     0.30%/0.30% (the ordinary even split), with the employee share
     defensively clamped at the statutory 0.30% ceiling regardless of
     what's configured. Reused fields (SINOT is literally Puerto Rico's
     own State-Disability-Insurance-shaped program — the closest existing
     generic slot, already used by several US states' own SDI programs):
     `state_disability_insurance` (employee) / `employer_state_program_contributions` (employer).

Wage-base/threshold YTD cap crossing (PR-013/PR-014/PR-015/PR-016/PR-018/
PR-019 — SS $184,500 cap, Additional Medicare $200,000 threshold, FUTA/
PR-unemployment $7,000 caps, SINOT $9,000 cap) needs real cumulative
accumulators across pay periods — wired to PayrollYtdAccumulator via
service.py's _load_pr_ytd/_upsert_pr_ytd_accumulator (own PR-scoped
component keys, never touching _US_YTD_COMPONENTS), gated on "PR" being
in engine/countries/shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES. When
no accumulator has been read yet for this employee (every ctx.ytd_pr_*_
before field is None — the dormant/not-wired state, same contract every
other country's YTD field in this codebase already uses), each cap falls
back to a simple per-period pro-rated share of its annual cap/threshold —
correct for an employee nowhere near any cap (fixture F1), not a genuine
mid-year crossing (fixtures F2-F4, which pass explicit YTD figures and
exercise the real wired path instead). Additional Medicare's fallback is
deliberately $0 (never guess a threshold crossing from one period's
estimate) rather than an annualized guess — the safe, never-over-withhold-
without-real-data direction, same dormancy discipline Guyana's PAYE
credit ledger uses for its own "no data yet" case.

Validated against ZP-PR-ENG-001 §13 fixtures F1 (ordinary month), F2 (SS
cap crossing), F3 (Additional Medicare threshold crossing), F4 (SINOT
cap) — see tests/test_puerto_rico.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
    is_parameter_configured,
    _calculate_annual_tax,
)

_PR_PERSONAL_EXEMPTION = Decimal("3500")

_PR_SS_RATE = Decimal("0.062")
_PR_SS_WAGE_BASE = Decimal("184500")

_PR_MEDICARE_RATE = Decimal("0.0145")
_PR_ADDITIONAL_MEDICARE_RATE = Decimal("0.009")
_PR_ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000")

_PR_FUTA_RATE = Decimal("0.06")
_PR_FUTA_WAGE_BASE = Decimal("7000")

_PR_UNEMPLOYMENT_WAGE_BASE = Decimal("7000")

_PR_SINOT_WAGE_BASE = Decimal("9000")
_PR_SINOT_EMPLOYEE_RATE = Decimal("0.003")
_PR_SINOT_EMPLOYEE_MAX_RATE = Decimal("0.003")  # PR-019 statutory ceiling
_PR_SINOT_EMPLOYER_RATE = Decimal("0.003")


def _capped_wage_base(period_gross: Decimal, periods_per_year: Decimal, wage_base: Decimal, ytd_before):
    """Shared cap-crossing shape for every PR wage-base accumulator (SS/
    FUTA/PR-unemployment/SINOT). Returns (taxable_this_period,
    ytd_after_or_None, wired: bool).

    Unlike cayman_islands.py's own pension cap (whose fallback prorates
    the annual cap evenly across periods — correct there because CI$87,000
    is large relative to ordinary monthly pay), PR's own wage bases are
    LOW ($7,000-$9,000/year) relative to ordinary monthly pay, so an
    evenly-prorated per-period share would incorrectly cap almost every
    ordinary employee's SINOT/FUTA-equivalent/PR-unemployment every single
    period even nowhere near the real annual cap (caught by ZP-PR-ENG-001
    §13 fixture F1's own "first month of SINOT year" case, which expects
    the FULL period amount, not a prorated fraction). The not-wired
    fallback here instead treats ytd_before as $0 (first-period
    assumption) rather than prorating — safe in practice because "PR" is
    in shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES from day one (see that
    set's own comment), so every real production call path
    (preview/generate/manual-payslip, all wired in service.py) always
    supplies a real Decimal (0 or accumulated), never None; this fallback
    is reachable only from a PayrollContext built outside service.py's
    own loader (e.g. an ad hoc script), which does not exist for PR today."""
    effective_before = ytd_before if ytd_before is not None else Decimal("0")
    remaining = max(wage_base - effective_before, Decimal("0"))
    taxable = min(period_gross, remaining)
    ytd_after = (effective_before + taxable) if ytd_before is not None else None
    return taxable, ytd_after, ytd_before is not None


def calculate(ctx: PayrollContext) -> dict:
    """Puerto Rico: local Hacienda withholding + independently-computed
    Social Security/Medicare/Additional Medicare + FUTA-equivalent +
    DTRH unemployment + SINOT. See module docstring for the full
    obligation-by-obligation breakdown and every reused-field mapping."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    # ── 1. Local Hacienda withholding ───────────────────────────────────
    # PR-005/PR-006: a certificate on file (ctx.pr_certificate_personal_
    # exemption is not None) overrides the engine default entirely — its
    # own elected amount, never blended with the default. No certificate
    # on file falls back to the current default treatment.
    personal_exemption = (
        ctx.pr_certificate_personal_exemption
        if ctx.pr_certificate_personal_exemption is not None
        else resolve_jurisdiction_parameter(rate_map, "pr_personal_exemption", _PR_PERSONAL_EXEMPTION, country="PR")
    )
    dependents_exemption = ctx.pr_certificate_dependents_count * ctx.pr_certificate_dependent_exemption_per_dependent
    total_exemption = personal_exemption + dependents_exemption + ctx.pr_certificate_deduction_allowance
    annual_gross = period_gross * periods_per_year
    taxable_annual = max(annual_gross - total_exemption, Decimal("0"))
    # MSRRA (PR-005 table): where validly elected, Puerto Rico wage
    # withholding may be not applicable — routed to specialist validation
    # by the certificate approval workflow itself (see
    # PRWithholdingCertificate's own docstring); this engine only honors
    # an ALREADY-APPROVED election, never independently verifies MSRRA
    # eligibility.
    if ctx.pr_certificate_msrra_election:
        tds = Decimal("0")
    else:
        tds = _round2(_calculate_annual_tax(taxable_annual, ctx.slabs) / periods_per_year) + ctx.pr_certificate_additional_withholding

    # ── 2. Social Security ───────────────────────────────────────────────
    ss_wage_base = resolve_jurisdiction_parameter(rate_map, "pr_ss_wage_base", _PR_SS_WAGE_BASE, country="PR")
    ss_employee_rate = resolve_jurisdiction_parameter(rate_map, "pr_ss", _PR_SS_RATE, side="employee", country="PR")
    ss_employer_rate = resolve_jurisdiction_parameter(rate_map, "pr_ss", _PR_SS_RATE, side="employer", country="PR")
    ss_taxable, ytd_ss_after, _ss_wired = _capped_wage_base(
        period_gross, periods_per_year, ss_wage_base, ctx.ytd_pr_ss_wages_before
    )
    social_security = _round2(ss_taxable * ss_employee_rate)
    employer_social_security = _round2(ss_taxable * ss_employer_rate)

    # ── 3. Medicare + Additional Medicare ────────────────────────────────
    medicare_rate = resolve_jurisdiction_parameter(rate_map, "pr_medicare", _PR_MEDICARE_RATE, side="employee", country="PR")
    medicare_employer_rate = resolve_jurisdiction_parameter(rate_map, "pr_medicare", _PR_MEDICARE_RATE, side="employer", country="PR")
    regular_medicare_employee = _round2(period_gross * medicare_rate)
    employer_medicare = _round2(period_gross * medicare_employer_rate)

    additional_medicare_rate = resolve_jurisdiction_parameter(
        rate_map, "pr_additional_medicare", _PR_ADDITIONAL_MEDICARE_RATE, side="employee", country="PR"
    )
    additional_medicare_threshold = resolve_jurisdiction_parameter(
        rate_map, "pr_additional_medicare_threshold", _PR_ADDITIONAL_MEDICARE_THRESHOLD, country="PR"
    )
    medicare_ytd_before = ctx.ytd_pr_medicare_wages_before
    if medicare_ytd_before is not None:
        medicare_ytd_after = medicare_ytd_before + period_gross
        prior_over = max(medicare_ytd_before - additional_medicare_threshold, Decimal("0"))
        total_over = max(medicare_ytd_after - additional_medicare_threshold, Decimal("0"))
        additional_medicare_wages = total_over - prior_over
    else:
        medicare_ytd_after = None
        additional_medicare_wages = Decimal("0")  # dormant fallback — never guess a threshold crossing
    additional_medicare_employee = _round2(additional_medicare_wages * additional_medicare_rate)

    medicare = regular_medicare_employee + additional_medicare_employee

    # ── 4. FUTA-equivalent ───────────────────────────────────────────────
    futa_wage_base = resolve_jurisdiction_parameter(rate_map, "pr_futa_wage_base", _PR_FUTA_WAGE_BASE, country="PR")
    futa_rate = resolve_jurisdiction_parameter(rate_map, "pr_futa", _PR_FUTA_RATE, side="employer", country="PR")
    futa_taxable, ytd_futa_after, _futa_wired = _capped_wage_base(
        period_gross, periods_per_year, futa_wage_base, ctx.ytd_pr_futa_wages_before
    )
    employer_futa = _round2(futa_taxable * futa_rate)

    # ── 5. DTRH Puerto Rico Unemployment Insurance ───────────────────────
    unemployment_wage_base = resolve_jurisdiction_parameter(
        rate_map, "pr_unemployment_wage_base", _PR_UNEMPLOYMENT_WAGE_BASE, country="PR"
    )
    unemployment_rate_configured = is_parameter_configured(rate_map, "pr_unemployment", side="employer")
    unemployment_rate = (
        resolve_jurisdiction_parameter(rate_map, "pr_unemployment", Decimal("0"), side="employer", country="PR")
        if unemployment_rate_configured else Decimal("0")
    )
    unemployment_taxable, ytd_unemployment_after, _unemployment_wired = _capped_wage_base(
        period_gross, periods_per_year, unemployment_wage_base, ctx.ytd_pr_unemployment_wages_before
    )
    employer_sui = _round2(unemployment_taxable * unemployment_rate) if unemployment_rate_configured else Decimal("0")

    # ── 6. SINOT ──────────────────────────────────────────────────────────
    sinot_wage_base = resolve_jurisdiction_parameter(rate_map, "pr_sinot_wage_base", _PR_SINOT_WAGE_BASE, country="PR")
    sinot_employee_rate = min(
        resolve_jurisdiction_parameter(rate_map, "pr_sinot", _PR_SINOT_EMPLOYEE_RATE, side="employee", country="PR"),
        _PR_SINOT_EMPLOYEE_MAX_RATE,
    )
    sinot_employer_rate = resolve_jurisdiction_parameter(rate_map, "pr_sinot", _PR_SINOT_EMPLOYER_RATE, side="employer", country="PR")
    sinot_taxable, ytd_sinot_after, _sinot_wired = _capped_wage_base(
        period_gross, periods_per_year, sinot_wage_base, ctx.ytd_pr_sinot_wages_before
    )
    state_disability_insurance = _round2(sinot_taxable * sinot_employee_rate)
    employer_state_program_contributions = _round2(sinot_taxable * sinot_employer_rate)

    # ── 7. CFSE workers' compensation (PR-021/PR-022) ────────────────────
    # Employer-policy/risk-class driven — NEVER a universal per-payroll
    # percentage (PR-021's own instruction). No hardcoded default: reads
    # ONLY a real configured org-scoped rate (same "never fabricate a
    # missing employer-specific figure" pattern as DTRH unemployment
    # above), and whatever IS computed is explicitly an employer COST
    # ESTIMATE (reuses the generic au_workers_compensation_premium field —
    # the same "employer-paid workers' compensation" concept Australia's
    # own engine already populates, not an AU-specific figure) to
    # reconcile against the real CFSE policy/billing, never presented as
    # the policy's own authoritative premium.
    cfse_rate_configured = is_parameter_configured(rate_map, "pr_cfse", side="employer")
    cfse_rate = (
        resolve_jurisdiction_parameter(rate_map, "pr_cfse", Decimal("0"), side="employer", country="PR")
        if cfse_rate_configured else Decimal("0")
    )
    au_workers_compensation_premium = _round2(period_gross * cfse_rate) if cfse_rate_configured else Decimal("0")

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
        medicare=medicare,
        employer_medicare=employer_medicare,
        employer_futa=employer_futa,
        employer_sui=employer_sui,
        pr_unemployment_rate_configured=unemployment_rate_configured,
        state_disability_insurance=state_disability_insurance,
        employer_state_program_contributions=employer_state_program_contributions,
        au_workers_compensation_premium=au_workers_compensation_premium,
        pr_cfse_rate_configured=cfse_rate_configured,
        ytd_pr_ss_wages_after=ytd_ss_after,
        ytd_pr_medicare_wages_after=medicare_ytd_after,
        ytd_pr_futa_wages_after=ytd_futa_after,
        ytd_pr_unemployment_wages_after=ytd_unemployment_after,
        ytd_pr_sinot_wages_after=ytd_sinot_after,
    )


# ══════════════════════════════════════════════════════════════════════
# Labour-pay calculators (ZP-PR-ENG-001 §7-§9) — daily/weekly overtime,
# Christmas Bonus, vacation accrual, and tipped-worker minimum-wage
# make-up.
#
# These are DELIBERATELY NOT part of calculate()/_COUNTRY_CALC above:
# each is its own annual/monthly/per-workweek computation with its own
# input shape (a bonus-year wage/hour total, a years-of-service count, a
# workweek's hours/tips), not a per-pay-period statutory deduction the
# standard payroll engine dispatches on every run. They are pure
# functions — given the right inputs they return the exact right
# statutory figure (verified against §13 fixtures F5-F8 below) — but the
# SURROUNDING INFRASTRUCTURE this platform would need to call them
# automatically is explicitly NOT built yet:
#   - Christmas Bonus: no Oct 1-Sep 30 bonus-year wage/qualifying-hours
#     accumulator exists (would need a new YTD-style tracker, a genuinely
#     new persistence concept, not just a new component key); no employer-
#     size/">26 weeks" headcount-history tracker; no UI (§12's "Christmas
#     Bonus" screen/bonus-year-progress tracker, or a bespoke component
#     like Trinidad's NIS modal); no 15% net-profit-limitation exception
#     workflow (PR-033); no payment-window (15 Nov-15 Dec) scheduling.
#   - Vacation accrual: no monthly qualifying-hours-worked aggregator, no
#     employer-size history snapshot, no balance/payout-on-termination
#     persistence (PR-028/PR-030), no mandatory-decree/special-industry
#     override registry (PR-031).
#   - Tipped minimum wage: no per-workweek tip/service-charge data capture
#     from ZoikoTime (PR-025), no automatic minimum-wage-make-up injection
#     into a payslip.
#   - Overtime: no per-workweek hours-worked capture from ZoikoTime
#     (PR-025) — this platform has no time-and-attendance integration for
#     ANY country yet, not a Puerto-Rico-specific gap.
# Wiring any of these into a real, automatic, persisted feature is
# follow-up scope, not attempted here.
# ══════════════════════════════════════════════════════════════════════

_PR_CHRISTMAS_BONUS_WAGE_CAP = Decimal("10000")
_PR_CHRISTMAS_BONUS_HOURS_PRE_2017 = Decimal("700")
_PR_CHRISTMAS_BONUS_HOURS_POST_2017 = Decimal("1350")
_PR_CHRISTMAS_BONUS_RATE_PRE_2017_LARGE = Decimal("0.06")   # >15 employees
_PR_CHRISTMAS_BONUS_RATE_PRE_2017_SMALL = Decimal("0.03")   # <=15 employees
_PR_CHRISTMAS_BONUS_RATE_POST_2017 = Decimal("0.02")
_PR_CHRISTMAS_BONUS_CAP_LARGE = Decimal("600")   # pre-2017 >15 employees, or post-2017 >20 employees
_PR_CHRISTMAS_BONUS_CAP_SMALL = Decimal("300")   # pre-2017 <=15 employees, or post-2017 <=20 employees
_PR_CHRISTMAS_BONUS_FIRST_YEAR_RATE = Decimal("0.5")

_PR_MINIMUM_WAGE = Decimal("10.50")
_PR_TIPPED_CASH_WAGE = Decimal("2.13")


def calculate_pr_christmas_bonus(
    hired_before_2017: bool, employer_size_over_threshold: bool, qualifying_hours: Decimal,
    bonus_year_wages: Decimal, is_first_year: bool = False,
) -> dict:
    """Act 148 (as amended by Act 4-2017) statutory Christmas bonus — §9.

    `employer_size_over_threshold`: >15 employees for a pre-2017 hire,
    >20 employees for >26 weeks for a post-2017 hire (the doc's two
    genuinely different headcount tests, both collapsed into one boolean
    here since only one applies to a given employee's own cohort).
    `is_first_year` only reduces a POST-2017 employee's bonus by 50% (the
    doc's table has no first-year rule for a pre-2017 hire, who by
    definition has already passed their first year long ago).

    Verified against fixtures F5 (2% * $40,000 = $800, capped at $600)
    and F6 (same, then 50% first-year rule -> $300)."""
    hours_threshold = _PR_CHRISTMAS_BONUS_HOURS_PRE_2017 if hired_before_2017 else _PR_CHRISTMAS_BONUS_HOURS_POST_2017
    eligible = qualifying_hours >= hours_threshold
    dollar_cap = _PR_CHRISTMAS_BONUS_CAP_LARGE if employer_size_over_threshold else _PR_CHRISTMAS_BONUS_CAP_SMALL

    if not eligible:
        return dict(eligible=False, bonus_amount=Decimal("0.00"), dollar_cap=dollar_cap, hours_threshold=hours_threshold)

    if hired_before_2017:
        rate = _PR_CHRISTMAS_BONUS_RATE_PRE_2017_LARGE if employer_size_over_threshold else _PR_CHRISTMAS_BONUS_RATE_PRE_2017_SMALL
        wage_base = min(bonus_year_wages, _PR_CHRISTMAS_BONUS_WAGE_CAP)
    else:
        rate = _PR_CHRISTMAS_BONUS_RATE_POST_2017
        wage_base = bonus_year_wages

    bonus = min(_round2(wage_base * rate), dollar_cap)
    if is_first_year and not hired_before_2017:
        bonus = _round2(bonus * _PR_CHRISTMAS_BONUS_FIRST_YEAR_RATE)

    return dict(eligible=True, bonus_amount=bonus, dollar_cap=dollar_cap, hours_threshold=hours_threshold)


_PR_SICK_LEAVE_QUALIFYING_HOURS = Decimal("130")
_PR_SICK_LEAVE_DAYS_PER_MONTH = Decimal("1")


def calculate_pr_sick_leave_accrual(qualifying_hours_in_month: Decimal) -> Decimal:
    """Act 4-2017 sick leave — §8. 1 day/month when the employee works at
    least 130 hours in the month; the current minimum does NOT vary by
    hire date or service (unlike vacation), so there is no cohort
    branching here at all — deliberately simpler than
    calculate_pr_vacation_accrual."""
    if qualifying_hours_in_month < _PR_SICK_LEAVE_QUALIFYING_HOURS:
        return Decimal("0")
    return _PR_SICK_LEAVE_DAYS_PER_MONTH


def calculate_pr_vacation_accrual(
    hired_before_2017: bool, years_of_service: Decimal, qualifying_small_employer: bool,
    qualifying_hours_in_month: Decimal,
) -> Decimal:
    """Act 4-2017 vacation accrual (Law 180) — §8. Returns days accrued
    for the month, or 0 if the 130-hour monthly qualifying test isn't
    met. `qualifying_small_employer`: the PR-resident employer with <=12
    employees exception for a POST-2017 hire only.

    Verified against fixture F8 (post-2017, year 6, standard employer,
    132 qualifying hours -> 1 day)."""
    if qualifying_hours_in_month < Decimal("130"):
        return Decimal("0")
    if hired_before_2017:
        return Decimal("1.25")
    if qualifying_small_employer:
        return Decimal("0.5")
    if years_of_service < Decimal("1"):
        return Decimal("0.5")
    if years_of_service <= Decimal("5"):
        return Decimal("0.75")
    if years_of_service <= Decimal("15"):
        return Decimal("1")
    return Decimal("1.25")


def calculate_pr_tipped_minimum_wage(hours: Decimal, tips_received: Decimal, cash_wage_per_hour: Decimal = None) -> dict:
    """Tip-credit minimum-wage make-up — §7/PR-027. If cash wage + tips
    doesn't reach PR minimum wage * hours worked, the employer must make
    up the difference; the tip credit may never create pay below minimum.

    Verified against fixture F7 (80 hours, $2.13/hr cash, $500 tips ->
    cash $170.40 + tips $500 = $670.40 vs $840 minimum -> $169.60 make-up)."""
    cash_rate = cash_wage_per_hour if cash_wage_per_hour is not None else _PR_TIPPED_CASH_WAGE
    cash_wage = _round2(hours * cash_rate)
    total_received = cash_wage + tips_received
    minimum_required = _round2(hours * _PR_MINIMUM_WAGE)
    make_up_required = max(minimum_required - total_received, Decimal("0.00"))
    return dict(
        cash_wage=cash_wage, tips_received=tips_received, total_received=total_received,
        minimum_required=minimum_required, make_up_required=make_up_required,
    )


_PR_OVERTIME_DAILY_THRESHOLD = Decimal("8")
_PR_OVERTIME_WEEKLY_THRESHOLD = Decimal("40")
_PR_OVERTIME_RATE_MULTIPLIER = Decimal("1.5")


def calculate_pr_overtime(daily_hours: list, hourly_rate: Decimal) -> dict:
    """Daily (>8 hr/day) and weekly (>40 hr/week) overtime at 1.5x, Act
    379/DTRH Opinion 2024-03 — §7/PR-026. `daily_hours` is one Decimal per
    day actually worked in the workweek (any length list — a partial
    week is fine).

    PR-026: "avoid double-counting the same hour when it qualifies under
    more than one rule." An hour already paid as DAILY overtime (the
    portion of a day above 8 hours) is excluded from the weekly 40-hour
    test entirely — only the "regular" (<=8/day) portion of each day
    counts toward the weekly threshold, so a day with real daily overtime
    never also contributes to weekly overtime for those same hours.
    Weekly overtime only arises from days that individually stayed at or
    under 8 hours but which, summed together, still exceed 40.

    Example: 5 days x 9 hours (45 total) -> 5 hours of DAILY overtime (1/
    day), 40 hours of regular time, 0 weekly overtime (the regular pool
    exactly reaches 40, never exceeds it).  6 days x 7 hours (42 total,
    no single day over 8) -> 0 daily overtime, 40 regular + 2 WEEKLY
    overtime."""
    daily_regular_total = Decimal("0")
    daily_overtime_hours = Decimal("0")
    for hours in daily_hours:
        regular = min(hours, _PR_OVERTIME_DAILY_THRESHOLD)
        overtime = max(hours - _PR_OVERTIME_DAILY_THRESHOLD, Decimal("0"))
        daily_regular_total += regular
        daily_overtime_hours += overtime

    weekly_overtime_hours = max(daily_regular_total - _PR_OVERTIME_WEEKLY_THRESHOLD, Decimal("0"))
    regular_hours = daily_regular_total - weekly_overtime_hours
    total_overtime_hours = daily_overtime_hours + weekly_overtime_hours

    overtime_rate = hourly_rate * _PR_OVERTIME_RATE_MULTIPLIER
    regular_pay = _round2(regular_hours * hourly_rate)
    overtime_pay = _round2(total_overtime_hours * overtime_rate)

    return dict(
        regular_hours=regular_hours,
        daily_overtime_hours=daily_overtime_hours,
        weekly_overtime_hours=weekly_overtime_hours,
        total_overtime_hours=total_overtime_hours,
        regular_pay=regular_pay,
        overtime_pay=overtime_pay,
        total_pay=regular_pay + overtime_pay,
    )

"""
modules/payroll/engine/countries/us.py
-----------------------------------------
US: Social Security + Medicare + Federal Income Tax. Moved verbatim out
of engine/standard.py's _calc_us.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change. See that file for
# the provenance comments on each (filing-status thresholds, FUTA credit
# convention, etc.).
from app.modules.payroll.hardcoded_defaults import (
    _US_STANDARD_DEDUCTION, _US_SOCIAL_SECURITY_WAGE_BASE, _US_SOCIAL_SECURITY_RATE,
    _US_MEDICARE_RATE, _US_MEDICARE_ADDITIONAL_RATE, _US_MEDICARE_ADDL_THRESHOLD_DEFAULTS,
    _US_MEDICARE_ADDITIONAL_THRESHOLD, _US_FUTA_RATE, _US_FUTA_WAGE_BASE, _US_FUTA_CREDIT_PCT,
)


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


def calculate(ctx: PayrollContext) -> dict:
    """US: Social Security + Medicare + Federal Income Tax + FUTA +
    (where a state-scoped TaxSlab set exists) State Income Tax.

    Employee/employer Social Security and Medicare rates come from
    rate_map's "social-security"/"medicare" ContributionRate rows rather
    than being ignored in favour of a hardcoded module constant — editing
    these rates via Compliance has a real calculation effect."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ss_rate_employee = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employee", country="US")
    ss_rate_employer = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employer", country="US")
    ss_wage_base = resolve_jurisdiction_parameter(rate_map, "ss_wage_base", _US_SOCIAL_SECURITY_WAGE_BASE, country="US")
    annual_ss_wage = min(annual_gross, ss_wage_base)
    social_security = _round2((annual_ss_wage * ss_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    employer_ss = _round2((annual_ss_wage * ss_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    medicare_rate_employee = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employee", country="US")
    medicare_rate_employer = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employer", country="US")
    medicare_additional_rate = resolve_jurisdiction_parameter(rate_map, "medicare_additional", _US_MEDICARE_ADDITIONAL_RATE, side="employee", country="US")
    medicare_additional_threshold_default = _US_MEDICARE_ADDL_THRESHOLD_DEFAULTS.get(ctx.w4_filing_status, _US_MEDICARE_ADDITIONAL_THRESHOLD)
    medicare_additional_threshold = resolve_jurisdiction_parameter(rate_map, "medicare_addl_thresh", medicare_additional_threshold_default, country="US")

    medicare = _round2((annual_gross * medicare_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    if annual_gross > medicare_additional_threshold:
        medicare += _round2(((annual_gross - medicare_additional_threshold) * medicare_additional_rate / Decimal("100")) / MONTHS_PER_YEAR)
    employer_medicare = _round2((annual_gross * medicare_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

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
        employer_sui = _round2((annual_sui_wage * sui_profile.employer_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)

    futa_rate = resolve_jurisdiction_parameter(rate_map, "futa", _US_FUTA_RATE, side="employer", country="US")
    if sui_profile is not None:
        # Real SUI is being paid for this employer/state (a configured,
        # evidence-backed profile exists) — the standard federal credit
        # applies. futa_credit_reduction_pct (state-scoped, Super-Admin-
        # configurable) is how much of the 5.4% credit a credit-reduction
        # state has taken away this tax year — 0 (full credit, ~0.6%
        # effective rate) unless Super Admin has explicitly configured
        # otherwise. No list of "which states are credit-reduced" is
        # hardcoded anywhere — that changes yearly and must come from
        # Tax Operations, not a guess baked into application code.
        futa_credit_pct = resolve_jurisdiction_parameter(rate_map, "futa_credit_pct", _US_FUTA_CREDIT_PCT, country="US")
        futa_credit_reduction_pct = resolve_jurisdiction_parameter(rate_map, "futa_credit_reduction_pct", Decimal("0"), country="US")
        effective_futa_rate = max(Decimal("0"), futa_rate - futa_credit_pct + futa_credit_reduction_pct)
    else:
        effective_futa_rate = futa_rate
    futa_wage_base = resolve_jurisdiction_parameter(rate_map, "futa_wage_base", _US_FUTA_WAGE_BASE, country="US")
    annual_futa_wage = min(annual_gross, futa_wage_base)
    employer_futa = _round2((annual_futa_wage * effective_futa_rate / Decimal("100")) / MONTHS_PER_YEAR)

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
    # NOTE: state brackets are not yet filing-status-filtered — every state
    # income tax table configured today is filing-status-agnostic, so this
    # is a no-op in practice (see _calculate_annual_tax's early-exit when no
    # slab in the list carries a filing_status), but is explicitly NOT
    # threaded here yet pending real state bracket data that varies by
    # filing status (a follow-up, not silently unhandled).
    annual_state_tax = _calculate_annual_tax(annual_gross, state_slabs) if state_slabs else Decimal("0")
    state_income_tax = _round2(annual_state_tax / MONTHS_PER_YEAR)

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
        if locality.flat_amount is not None:
            local_tax = _round2(locality.flat_amount)
        else:
            locality_rate_pct = locality.resident_rate_pct if locality.resident_rate_pct is not None else locality.nonresident_rate_pct
            if locality_rate_pct is not None:
                local_tax = _round2((annual_gross * locality_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)

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
        _round2((annual_gross * sdi_rate.employee_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)
        if sdi_rate and sdi_rate.employee_rate_pct else Decimal("0")
    )

    filing_status = ctx.w4_filing_status
    annual_tax = _calculate_annual_tax_us(annual_gross, ctx.slabs, rate_map, filing_status=filing_status)
    federal_income_tax = _round2(annual_tax / MONTHS_PER_YEAR)
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
        tds=tds, annual_tax=annual_tax,
    )

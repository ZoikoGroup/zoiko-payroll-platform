"""
modules/payroll/engine/standard
-------------------------------
Standard Payroll strategy — country dispatch + the universal Fixed 30-Day
attendance model.

Formula:
    Net Salary =
        Gross Salary
        − Attendance Deduction
        − PF (Employee + Employer)
        − ESI (Employee + Employer, if gross ≤ ₹21,000)
        − Professional Tax (flat ₹200/mo)
        − TDS (progressive slabs, FY 2025-26 New Regime)

Attendance deduction is ALWAYS computed first via the Fixed 30-Day model,
then statutory deductions are applied on the full gross (not prorated).

Country-specific logic is dispatched from here for "standard" mode — the
same engine serves IN, US, UK, AU, DE, and CA under the Standard policy
(and, via EnterpriseStrategy re-using this dispatch table, under the
Enterprise policy too). Each country's actual formulas now live in their
own file under engine/countries/ (india.py, us.py, uk.py, australia.py,
germany.py, canada.py) plus engine/countries/shared.py for the
genuinely cross-cutting helpers — this file re-exports every one of
those under its original private name (`_calc_india`, `MONTHS_PER_YEAR`,
`_IN_STANDARD_DEDUCTION`, etc.) purely for backward compatibility, since
engine/enterprise.py and this module's own test suite import them
directly from here. Nothing about those contracts changed — only the
implementation moved to make one country's formulas readable/editable
without touching the other five.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)
from app.modules.payroll.engine.countries.shared import (
    MONTHS_PER_YEAR,
    evaluate_tax_formula,
    _param_amount,
    _param_pct,
    _calculate_annual_tax,
)
from app.modules.payroll.engine.countries import india as _india
from app.modules.payroll.engine.countries import us as _us
from app.modules.payroll.engine.countries import uk as _uk
from app.modules.payroll.engine.countries import australia as _australia
from app.modules.payroll.engine.countries import germany as _germany
from app.modules.payroll.engine.countries import canada as _canada
from app.modules.payroll.engine.countries import generic as _generic

# Caribbean production jurisdictions (2026-09-21) — each is its own file
# under engine/countries/, same one-file-per-country doctrine as every
# country above. See each module's own docstring for its statutory scope
# and which generic PayrollResult fields it reuses.
from app.modules.payroll.engine.countries import barbados as _barbados
from app.modules.payroll.engine.countries import cayman_islands as _cayman_islands
from app.modules.payroll.engine.countries import dominican_republic as _dominican_republic
from app.modules.payroll.engine.countries import guyana as _guyana
from app.modules.payroll.engine.countries import jamaica as _jamaica
from app.modules.payroll.engine.countries import bahamas as _bahamas
from app.modules.payroll.engine.countries import trinidad_and_tobago as _trinidad_and_tobago
from app.modules.payroll.engine.countries import puerto_rico as _puerto_rico
from app.modules.payroll.engine.countries import france as _france
from app.modules.payroll.engine.countries import ireland as _ireland
from app.modules.payroll.engine.countries import singapore as _singapore
from app.modules.payroll.engine.countries import sweden as _sweden
from app.modules.payroll.engine.countries import italy as _italy

# ── Backward-compatible re-exports ──────────────────────────────────────
# Every name below existed directly in this file before the engine/
# countries/ split — kept importable from exactly this path, exactly
# these names, so no external caller needs to change.

ESI_MONTHLY_WAGE_CEILING = _india.ESI_MONTHLY_WAGE_CEILING
_IN_STANDARD_DEDUCTION = _india._IN_STANDARD_DEDUCTION
_IN_REBATE_87A_LIMIT = _india._IN_REBATE_87A_LIMIT
_IN_REBATE_87A_MAX = _india._IN_REBATE_87A_MAX
_apply_section_87a_rebate = _india._apply_section_87a_rebate
_calculate_annual_tax_in = _india._calculate_annual_tax_in
_calc_india = _india.calculate

_US_STANDARD_DEDUCTION = _us._US_STANDARD_DEDUCTION
_US_SOCIAL_SECURITY_WAGE_BASE = _us._US_SOCIAL_SECURITY_WAGE_BASE
_US_SOCIAL_SECURITY_RATE = _us._US_SOCIAL_SECURITY_RATE
_US_MEDICARE_RATE = _us._US_MEDICARE_RATE
_US_MEDICARE_ADDITIONAL_RATE = _us._US_MEDICARE_ADDITIONAL_RATE
_US_MEDICARE_ADDITIONAL_THRESHOLD = _us._US_MEDICARE_ADDITIONAL_THRESHOLD
_calculate_annual_tax_us = _us._calculate_annual_tax_us
_calc_us = _us.calculate

_UK_PERSONAL_ALLOWANCE = _uk._UK_PERSONAL_ALLOWANCE
_UK_PA_TAPER_THRESHOLD = _uk._UK_PA_TAPER_THRESHOLD
_UK_NI_PRIMARY_THRESHOLD = _uk._UK_NI_PRIMARY_THRESHOLD
_UK_NI_UPPER_THRESHOLD = _uk._UK_NI_UPPER_THRESHOLD
_UK_NI_PRIMARY_RATE = _uk._UK_NI_PRIMARY_RATE
_UK_NI_UPPER_RATE = _uk._UK_NI_UPPER_RATE
_UK_PENSION_MIN_ENPLOYER = _uk._UK_PENSION_MIN_ENPLOYER
_calculate_annual_tax_uk = _uk._calculate_annual_tax_uk
_calc_uk = _uk.calculate

# _AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD's re-export removed along with
# the constant itself (ZP-TAX-AU-2026-27-001 build) — Medicare Levy
# proper is now embedded in the Schedule 1 Scale 1/2/5/6 coefficient
# bands, not a separate flat-threshold calculation. See
# engine/countries/australia.py's own module docstring.
_AU_MLS_THRESHOLD = _australia._AU_MLS_THRESHOLD
_AU_MLS_RATE = _australia._AU_MLS_RATE
_AU_SUPER_MAX_CONTRIBUTION_BASE = _australia._AU_SUPER_MAX_CONTRIBUTION_BASE
_AU_PAYG_SCALE4_RESIDENT_RATE = _australia._AU_PAYG_SCALE4_RESIDENT_RATE
_AU_PAYG_SCALE4_NONRESIDENT_RATE = _australia._AU_PAYG_SCALE4_NONRESIDENT_RATE
_calc_australia = _australia.calculate

_DE_SOLI_THRESHOLD = _germany._DE_SOLI_THRESHOLD
_DE_SOLI_RATE = _germany._DE_SOLI_RATE
_calc_germany = _germany.calculate

_CA_CPP_YMPE = _canada._CA_CPP_YMPE
_CA_CPP_BASIC_EXEMPTION = _canada._CA_CPP_BASIC_EXEMPTION
_CA_EI_MIE = _canada._CA_EI_MIE
_CA_BASIC_PERSONAL_AMOUNT = _canada._CA_BASIC_PERSONAL_AMOUNT
_calculate_annual_tax_ca = _canada._calculate_annual_tax_ca
_calc_canada = _canada.calculate

_calc_generic = _generic.calculate

_calc_barbados = _barbados.calculate
_calc_cayman_islands = _cayman_islands.calculate
_calc_dominican_republic = _dominican_republic.calculate
_calc_guyana = _guyana.calculate
_calc_jamaica = _jamaica.calculate
_calc_bahamas = _bahamas.calculate
_calc_trinidad_and_tobago = _trinidad_and_tobago.calculate
_calc_puerto_rico = _puerto_rico.calculate
_calc_france = _france.calculate
_calc_ireland = _ireland.calculate
_calc_singapore = _singapore.calculate
_calc_sweden = _sweden.calculate
_calc_italy = _italy.calculate


_COUNTRY_CALC = {
    "IN": _calc_india,
    "US": _calc_us,
    "UK": _calc_uk,
    "AU": _calc_australia,
    "DE": _calc_germany,
    "CA": _calc_canada,
    # Caribbean production jurisdictions (2026-09-21). Every other
    # Caribbean code (see app.core.caribbean_regions — "Coming Soon")
    # is deliberately ABSENT here: it must never resolve to a real
    # calculator, and falls through to _calc_generic only in the
    # theoretical case registration/onboarding somehow failed to block
    # it first (see tests/test_registration_jurisdiction_gate.py).
    "BB": _calc_barbados,
    "KY": _calc_cayman_islands,
    "DO": _calc_dominican_republic,
    "GY": _calc_guyana,
    "JM": _calc_jamaica,
    "BS": _calc_bahamas,
    "TT": _calc_trinidad_and_tobago,
    # Puerto Rico (2026-09-23) — dual-jurisdiction (local Hacienda +
    # independently-computed federal-equivalent layer), but architecturally
    # a sibling of the Caribbean entries above, not a US-dependent variant —
    # see engine/countries/puerto_rico.py's own module docstring.
    "PR": _calc_puerto_rico,
    # France (2026-09-24, ZP-FR-ENG-001) — European expansion, metropolitan
    # private-sector wedge. Engine/countries/france.py; calculation is
    # establishment-aware and returns separate net_social/net_imposable.
    "FR": _calc_france,
    "IE": _calc_ireland,
    # Singapore (ZP-SG-ENG-001) — CPF/SDL/SHG only, never `tds` (not a
    # monthly-PAYE jurisdiction). Fail-closed: see countries/singapore.py.
    "SG": _calc_singapore,
    # Sweden (ZP-SE-ENG-001) — table-lookup preliminary tax (never a
    # national %), component-summed employer contributions with cohorts,
    # SLP from its own pension-cost ledger. Fail-closed: countries/sweden.py.
    "SE": _calc_sweden,
    # Italy (ZP-IT-ENG-001) - INPS classification-matrix contributions (never a
    # national average), progressive IRPEF with the solidarity wedge, regional/
    # municipal additions on the TAX DOMICILE. Fail-closed:
    # countries/italy.py.
    "IT": _calc_italy,
}


# ── Strategy class ─────────────────────────────────────────────────────────

class StandardStrategy(PayrollStrategy):
    """Standard payroll with country-specific statutory compliance.

    Supports IN, US, UK, AU, DE, CA natively.  Unrecognised countries fall
    through to a generic progressive-tax calculator.
    """

    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        payroll_days = ctx.payroll_days or PAYROLL_DAYS
        calendar_days = max(ctx.calendar_days or payroll_days, 0)
        unpaid = max(ctx.unpaid_leave_days, 0)
        payable_days = max(calendar_days - unpaid, 0)

        per_day_salary = _round2(ctx.gross / Decimal(payroll_days)) if payroll_days else Decimal("0")
        attendance_deduction = min(_round2(per_day_salary * Decimal(unpaid)), ctx.gross)

        # Country-specific compliance deductions (computed on full gross)
        calc_fn = _COUNTRY_CALC.get(ctx.country.upper(), _calc_generic)
        deductions = calc_fn(ctx)
        # Singapore only (the key is returned by countries/singapore.py alone):
        # MOM's incomplete-month salary replaces the generic per-day
        # attendance deduction, with MOM working days / days worked.
        if "sgp_incomplete_month_deduction" in deductions:
            attendance_deduction = deductions["sgp_incomplete_month_deduction"]
            per_day_salary = deductions.get("sgp_per_day_gross_rate", per_day_salary)
            payable_days = deductions.get("sgp_days_worked", calendar_days)
            calendar_days = deductions.get("sgp_working_days", calendar_days)

        total_employee_deductions = (
            attendance_deduction
            + deductions.get("employee_pf", Decimal("0"))
            + deductions.get("employee_esi", Decimal("0"))
            + deductions.get("professional_tax", Decimal("0"))
            + deductions.get("employee_lwf", Decimal("0"))
            + deductions.get("tds", Decimal("0"))
            + deductions.get("social_security", Decimal("0"))
            + deductions.get("medicare", Decimal("0"))
            + deductions.get("ni_employee", Decimal("0"))
            + deductions.get("study_loan_deduction", Decimal("0"))
            + deductions.get("postgrad_loan_deduction", Decimal("0"))
            + deductions.get("employee_pension", Decimal("0"))
            + deductions.get("church_tax", Decimal("0"))
            + deductions.get("cpp2", Decimal("0"))
            + deductions.get("state_disability_insurance", Decimal("0"))
            + deductions.get("state_program_deductions", Decimal("0"))
            + deductions.get("au_statutory_deductions_total", Decimal("0"))
            # France: combined employee-side total (all France employee
            # contributions incl. PAS withholding). Same additive mechanism
            # as au_statutory_deductions_total above — every other country's
            # .get() returns the 0 default, so no other calculation changes.
            + deductions.get("fr_employee_total", Decimal("0"))
            + deductions.get("ie_employee_total", Decimal("0"))
            # Singapore Employment Act authorised salary deductions (absent → 0 for every other country).
            + deductions.get("sgp_salary_deductions_total", Decimal("0"))
            # Sweden employee-side statutory total (preliminary tax +
            # occupational-pension employee share) — absent → 0 everywhere
            # else, same additive mechanism as ie_/fr_/sgp_ above.
            + deductions.get("se_employee_total", Decimal("0"))
            # Italy employee-side statutory total: INPS contributions + IRPEF
            # + the §5 local-surtax instalments withheld this period (regional
            # balance, municipal balance, municipal advance). It excludes the
            # surtaxes' annual LIABILITY, which is settled at the next
            # conguaglio, and the §4 wedge non-taxable sum, which is a BENEFIT
            # added below, never a negative deduction (IT-009). Absent -> 0
            # everywhere else, same additive mechanism as ie_/fr_/sgp_/se_ above.
            + deductions.get("it_employee_total", Decimal("0"))
        )

        net_pay = max(_round2(ctx.gross - total_employee_deductions), Decimal("0"))
        # §4 / IT-009: the structural tax-wedge non-taxable sum is money the
        # employee keeps — a separate statutory object with its own YTD state,
        # never netted inside IRPEF. It is added to net pay here, and is 0 for
        # every country whose calculation does not return the key.
        it_wedge_tax_free_sum = deductions.get("it_wedge_tax_free_sum", Decimal("0"))
        if it_wedge_tax_free_sum:
            net_pay = max(_round2(net_pay + it_wedge_tax_free_sum), Decimal("0"))
        # Phase 8BU: a PARTIAL Germany result (wage_tax/soli/church_tax
        # genuinely unavailable, RV/ALV/GKV/PV genuinely computed) must
        # NEVER present a net_pay computed as if the missing tax were
        # zero — that would silently understate the employee's real
        # deduction and overstate net pay as a plausible-looking but
        # false number. Forced to 0.00 here, matching this codebase's
        # existing "0.00 + an explicit non-COMPLETE status is the only
        # honest way to represent an unavailable figure" convention
        # (the same one FAILED payslips already use) — never displayed
        # as a real net pay by the API/frontend/PDF, which all gate on
        # PayslipStatus.PARTIAL instead.
        germany_unavailable_components = deductions.get("_germany_unavailable_components") or []
        if germany_unavailable_components:
            net_pay = Decimal("0.00")

        # India Code on Wages §8.3 (AC-18) — see PayrollResult.
        # wage_deduction_cap_exceeded's own comment for why this is a
        # flag, never a silent recalculation. attendance_deduction is
        # excluded: a loss-of-pay reduction for unpaid days isn't an
        # "authorized deduction" under the Code, it's pay never earned.
        wage_deduction_cap_exceeded = (
            ctx.country.upper() == "IN"
            and ctx.gross > Decimal("0")
            and (total_employee_deductions - attendance_deduction) > (ctx.gross * Decimal("0.5"))
        )

        return PayrollResult(
            payroll_days=payroll_days,
            calendar_days=calendar_days,
            unpaid_leave_days=unpaid,
            payable_days=payable_days,
            per_day_salary=per_day_salary,
            attendance_deduction=attendance_deduction,
            gross=ctx.gross,
            basic=ctx.basic,
            hra=ctx.hra,
            special_allowance=ctx.special_allowance,
            overtime=ctx.overtime,
            additional_compensation=ctx.additional_compensation,
            employee_pf=deductions.get("employee_pf", Decimal("0")),
            employer_pf=deductions.get("employer_pf", Decimal("0")),
            employer_eps=deductions.get("employer_eps", Decimal("0")),
            employer_pf_residual=deductions.get("employer_pf_residual", Decimal("0")),
            employer_edli=deductions.get("employer_edli", Decimal("0")),
            employer_nps=deductions.get("employer_nps", Decimal("0")),
            employee_esi=deductions.get("employee_esi", Decimal("0")),
            employer_esi=deductions.get("employer_esi", Decimal("0")),
            professional_tax=deductions.get("professional_tax", Decimal("0")),
            employee_lwf=deductions.get("employee_lwf", Decimal("0")),
            employer_lwf=deductions.get("employer_lwf", Decimal("0")),
            social_security=deductions.get("social_security", Decimal("0")),
            medicare=deductions.get("medicare", Decimal("0")),
            ni_employee=deductions.get("ni_employee", Decimal("0")),
            ytd_director_ni_gross=deductions.get("ytd_director_ni_gross"),
            ytd_director_ni_employee_paid=deductions.get("ytd_director_ni_employee_paid"),
            ytd_director_ni_employer_paid=deductions.get("ytd_director_ni_employer_paid"),
            study_loan_deduction=deductions.get("study_loan_deduction", Decimal("0")),
            postgrad_loan_deduction=deductions.get("postgrad_loan_deduction", Decimal("0")),
            employee_pension=deductions.get("employee_pension", Decimal("0")),
            church_tax=deductions.get("church_tax", Decimal("0")),
            # Germany: Solidaritätszuschlag — informational, already folded
            # into `tds` above (see PayrollResult.soli's own comment), so it
            # is NOT added to total_employee_deductions. Absent from every
            # non-DE calculator dict, so a .get with a zero default keeps
            # every other country's PayrollResult unchanged.
            soli=deductions.get("soli", Decimal("0")),
            cpp2=deductions.get("cpp2", Decimal("0")),
            employer_social_security=deductions.get("employer_social_security", Decimal("0")),
            employer_medicare=deductions.get("employer_medicare", Decimal("0")),
            employer_pension=deductions.get("employer_pension", Decimal("0")),
            employer_ni=deductions.get("employer_ni", Decimal("0")),
            employer_futa=deductions.get("employer_futa", Decimal("0")),
            employer_sui=deductions.get("employer_sui", Decimal("0")),
            employer_state_program_contributions=deductions.get("employer_state_program_contributions", Decimal("0")),
            employer_cpp2=deductions.get("employer_cpp2", Decimal("0")),
            employer_eht=deductions.get("employer_eht", Decimal("0")),
            on_eht_ytd_remuneration_after=deductions.get("on_eht_ytd_remuneration_after"),
            jm_heart_ytd_remuneration_after=deductions.get("jm_heart_ytd_remuneration_after"),
            employer_apprenticeship_levy=deductions.get("employer_apprenticeship_levy", Decimal("0")),
            auto_enrolment_status=deductions.get("auto_enrolment_status"),
            tax_week=deductions.get("tax_week"),
            tax_month=deductions.get("tax_month"),
            appr_levy_ytd_pay_bill_after=deductions.get("appr_levy_ytd_pay_bill_after"),
            employer_ni_ytd_after=deductions.get("employer_ni_ytd_after"),
            employer_bc_eht=deductions.get("employer_bc_eht", Decimal("0")),
            bc_eht_ytd_remuneration_after=deductions.get("bc_eht_ytd_remuneration_after"),
            employer_mb_he_levy=deductions.get("employer_mb_he_levy", Decimal("0")),
            mb_he_levy_ytd_remuneration_after=deductions.get("mb_he_levy_ytd_remuneration_after"),
            employer_nl_hapset=deductions.get("employer_nl_hapset", Decimal("0")),
            nl_hapset_ytd_remuneration_after=deductions.get("nl_hapset_ytd_remuneration_after"),
            employer_qc_hsf=deductions.get("employer_qc_hsf", Decimal("0")),
            qc_hsf_ytd_remuneration_after=deductions.get("qc_hsf_ytd_remuneration_after"),
            employer_qc_labour_standards=deductions.get("employer_qc_labour_standards", Decimal("0")),
            employer_payroll_tax=deductions.get("employer_payroll_tax", Decimal("0")),
            au_state_payroll_tax_ytd_remuneration_after=deductions.get("au_state_payroll_tax_ytd_remuneration_after"),
            au_statutory_deductions_total=deductions.get("au_statutory_deductions_total", Decimal("0")),
            au_statutory_deductions_detail=deductions.get("au_statutory_deductions_detail", []),
            au_workers_compensation_premium=deductions.get("au_workers_compensation_premium", Decimal("0")),
            au_calculation_trace=deductions.get("au_calculation_trace"),
            # France (ZP-FR-ENG-001, 2026-09-24) — fields returned by
            # engine/countries/france.calculate() and propagated to the result
            fr_net_social=deductions.get("fr_net_social"),
            fr_net_imposable=deductions.get("fr_net_imposable"),
            fr_employee_total=deductions.get("fr_employee_total", Decimal("0")),
            fr_employer_total=deductions.get("fr_employer_total", Decimal("0")),
            fr_contributions=deductions.get("fr_contributions"),
            fr_bases=deductions.get("fr_bases"),
            fr_pas_withheld=deductions.get("fr_pas_withheld", Decimal("0")),
            fr_pas_rate_type=deductions.get("fr_pas_rate_type"),
            fr_pas_rate_pct=deductions.get("fr_pas_rate_pct"),
            fr_pas_rate_id=deductions.get("fr_pas_rate_id"),
            fr_calculation_snapshot=deductions.get("fr_calculation_snapshot"),
            fr_ytd_after=deductions.get("fr_ytd_after"),
            fr_not_configured=deductions.get("fr_not_configured"),
            ie_paye=deductions.get("ie_paye", Decimal("0")),
            ie_employee_total=deductions.get("ie_employee_total", Decimal("0")),
            ie_paye_basis=deductions.get("ie_paye_basis"),
            ie_paye_unrounded=deductions.get("ie_paye_unrounded"),
            ie_standard_rate_pay=deductions.get("ie_standard_rate_pay", Decimal("0")),
            ie_higher_rate_pay=deductions.get("ie_higher_rate_pay", Decimal("0")),
            ie_tax_credit_applied=deductions.get("ie_tax_credit_applied", Decimal("0")),
            ie_rpn_number=deductions.get("ie_rpn_number"),
            ie_rpn_snapshot_id=deductions.get("ie_rpn_snapshot_id"),
            ie_rpn_hash=deductions.get("ie_rpn_hash"),
            ie_rpn_issued_at=deductions.get("ie_rpn_issued_at"),
            ie_usc=deductions.get("ie_usc", Decimal("0")),
            ie_usc_unrounded=deductions.get("ie_usc_unrounded"),
            ie_usc_payable_ytd_after=deductions.get("ie_usc_payable_ytd_after"),
            ie_employee_prsi=deductions.get("ie_employee_prsi", Decimal("0")),
            ie_employer_prsi=deductions.get("ie_employer_prsi", Decimal("0")),
            ie_employer_prsi_total=deductions.get("ie_employer_prsi_total", Decimal("0")),
            ie_prsi_class=deductions.get("ie_prsi_class"),
            ie_prsi_declaration=deductions.get("ie_prsi_declaration"),
            ie_prsi_ax_credit=deductions.get("ie_prsi_ax_credit", Decimal("0")),
            ie_prsi_contribution_weeks=deductions.get("ie_prsi_contribution_weeks"),
            ie_prsi_weekly_reckonable=deductions.get("ie_prsi_weekly_reckonable"),
            ie_prsi_reckonable_ytd_after=deductions.get("ie_prsi_reckonable_ytd_after"),
            ie_mff_employee=deductions.get("ie_mff_employee", Decimal("0")),
            ie_mff_employer=deductions.get("ie_mff_employer", Decimal("0")),
            ie_mff_state_topup=deductions.get("ie_mff_state_topup", Decimal("0")),
            ie_mff_status=deductions.get("ie_mff_status"),
            ie_mff_contributory=deductions.get("ie_mff_contributory", False),
            ie_mff_ceased_reason=deductions.get("ie_mff_ceased_reason"),
            ie_mff_earnings_ytd_after=deductions.get("ie_mff_earnings_ytd_after"),
            ie_lpt=deductions.get("ie_lpt", Decimal("0")),
            ie_lpt_instructed=deductions.get("ie_lpt_instructed", False),
            ie_lpt_rate_pct=deductions.get("ie_lpt_rate_pct"),
            ie_employee_pension=deductions.get("ie_employee_pension", Decimal("0")),
            ie_employer_pension=deductions.get("ie_employer_pension", Decimal("0")),
            ie_nmw_rate=deductions.get("ie_nmw_rate"),
            ie_nmw_band=deductions.get("ie_nmw_band"),
            ie_effective_hourly=deductions.get("ie_effective_hourly"),
            ie_tax_year=deductions.get("ie_tax_year"),
            ie_calculation_trace=deductions.get("ie_calculation_trace"),
            ie_ytd_after=deductions.get("ie_ytd_after"),
            # Sweden (ZP-SE-ENG-001) — everything countries/sweden.py
            # returns; .get with the PayrollResult default keeps every
            # other country's result unchanged.
            se_employer_contribution=deductions.get("se_employer_contribution", Decimal("0")),
            se_employer_contribution_rate=deductions.get("se_employer_contribution_rate"),
            se_employer_contribution_cohort=deductions.get("se_employer_contribution_cohort"),
            se_employer_contribution_components=deductions.get("se_employer_contribution_components", []),
            se_employer_contribution_base=deductions.get("se_employer_contribution_base", Decimal("0")),
            se_youth_applied=deductions.get("se_youth_applied", False),
            se_month_compensation=deductions.get("se_month_compensation"),
            se_preliminary_tax=deductions.get("se_preliminary_tax", Decimal("0")),
            se_tax_strategy=deductions.get("se_tax_strategy"),
            se_withholding_unrounded=deductions.get("se_withholding_unrounded"),
            se_tax_table=deductions.get("se_tax_table"),
            se_tax_column=deductions.get("se_tax_column"),
            se_income_role=deductions.get("se_income_role"),
            se_tax_status=deductions.get("se_tax_status"),
            se_occupational_pension_employee=deductions.get("se_occupational_pension_employee", Decimal("0")),
            se_occupational_pension_employer=deductions.get("se_occupational_pension_employer", Decimal("0")),
            se_pension_plan=deductions.get("se_pension_plan"),
            se_slp=deductions.get("se_slp", Decimal("0")),
            se_employer_total=deductions.get("se_employer_total", Decimal("0")),
            se_employee_total=deductions.get("se_employee_total", Decimal("0")),
            se_calculation_trace=deductions.get("se_calculation_trace"),
            # Italy (ZP-IT-ENG-001) — everything countries/italy.py returns.
            # .get with the PayrollResult default keeps every other country's
            # result unchanged.
            it_employer_social_security=deductions.get("it_employer_social_security", Decimal("0")),
            it_employer_contributions=deductions.get("it_employer_contributions", Decimal("0")),
            it_employee_contributions=deductions.get("it_employee_contributions", Decimal("0")),
            it_contributory_base=deductions.get("it_contributory_base", Decimal("0")),
            it_contributory_capped=deductions.get("it_contributory_capped", False),
            it_contributory_cap_cohort=deductions.get("it_contributory_cap_cohort"),
            it_contributory_cap_amount=deductions.get("it_contributory_cap_amount", Decimal("0")),
            it_contributory_cap_note=deductions.get("it_contributory_cap_note"),
            it_inps_scope=deductions.get("it_inps_scope"),
            it_inps_components=deductions.get("it_inps_components", []),
            it_ivs_additional=deductions.get("it_ivs_additional", Decimal("0")),
            it_fis_employee=deductions.get("it_fis_employee", Decimal("0")),
            it_tfr_amount=deductions.get("it_tfr_amount", Decimal("0")),
            it_tfr_gross_accrual=deductions.get("it_tfr_gross_accrual", Decimal("0")),
            it_tfr_inps_offset=deductions.get("it_tfr_inps_offset", Decimal("0")),
            it_tfr_destination=deductions.get("it_tfr_destination"),
            it_tfr_routing_complete=deductions.get("it_tfr_routing_complete", False),
            it_taxable_income=deductions.get("it_taxable_income", Decimal("0")),
            it_irpef=deductions.get("it_irpef", Decimal("0")),
            it_irpef_annual=deductions.get("it_irpef_annual", Decimal("0")),
            it_irpef_gross_annual=deductions.get("it_irpef_gross_annual", Decimal("0")),
            it_detrazione_lavoro=deductions.get("it_detrazione_lavoro", Decimal("0")),
            it_wedge_additional_deduction=deductions.get(
                "it_wedge_additional_deduction", Decimal("0")),
            it_wedge_tax_free_sum=deductions.get("it_wedge_tax_free_sum", Decimal("0")),
            it_wedge_band_pct=deductions.get("it_wedge_band_pct", Decimal("0")),
            it_regional_tax_annual=deductions.get("it_regional_tax_annual", Decimal("0")),
            it_municipal_tax_annual=deductions.get("it_municipal_tax_annual", Decimal("0")),
            it_local_tax_withheld=deductions.get("it_local_tax_withheld", False),
            it_addreg_saldo_withheld=deductions.get("it_addreg_saldo_withheld", Decimal("0")),
            it_addcom_saldo_withheld=deductions.get("it_addcom_saldo_withheld", Decimal("0")),
            it_addcom_acconto_withheld=deductions.get("it_addcom_acconto_withheld", Decimal("0")),
            it_local_tax_withheld_amount=deductions.get("it_local_tax_withheld_amount", Decimal("0")),
            it_contributory_minimum_applied=deductions.get("it_contributory_minimum_applied", False),
            it_tax_domicile_comune=deductions.get("it_tax_domicile_comune"),
            it_tax_domicile_region=deductions.get("it_tax_domicile_region"),
            it_fringe_amount=deductions.get("it_fringe_amount", Decimal("0")),
            it_fringe_child_declared=deductions.get("it_fringe_child_declared", False),
            it_fringe_taxable=deductions.get("it_fringe_taxable", Decimal("0")),
            it_fringe_ytd_after=deductions.get("it_fringe_ytd_after", Decimal("0")),
            it_meal_voucher_taxable=deductions.get("it_meal_voucher_taxable", Decimal("0")),
            it_conguaglio=deductions.get("it_conguaglio", False),
            it_irpef_refund=deductions.get("it_irpef_refund", Decimal("0")),
            it_wedge_recovery_now=deductions.get("it_wedge_recovery_now", Decimal("0")),
            it_wedge_recovery_new=deductions.get("it_wedge_recovery_new", Decimal("0")),
            it_wedge_recovery_outstanding_after=deductions.get("it_wedge_recovery_outstanding_after", Decimal("0")),
            it_wedge_recovery_instalment_after=deductions.get("it_wedge_recovery_instalment_after", Decimal("0")),
            it_addreg_saldo_determined=deductions.get("it_addreg_saldo_determined", Decimal("0")),
            it_addcom_saldo_determined=deductions.get("it_addcom_saldo_determined", Decimal("0")),
            it_addcom_credit_determined=deductions.get("it_addcom_credit_determined", Decimal("0")),
            it_termination_surtax_withheld=deductions.get("it_termination_surtax_withheld", Decimal("0")),
            it_ytd_after=deductions.get("it_ytd_after"),
            it_employee_total=deductions.get("it_employee_total", Decimal("0")),
            it_calculation_trace=deductions.get("it_calculation_trace"),
            cpp_base_amount=deductions.get("cpp_base_amount", Decimal("0")),
            cpp_first_additional_amount=deductions.get("cpp_first_additional_amount", Decimal("0")),
            employer_cpp_base=deductions.get("employer_cpp_base", Decimal("0")),
            employer_cpp_first_additional=deductions.get("employer_cpp_first_additional", Decimal("0")),
            ytd_pensionable_earnings=deductions.get("ytd_pensionable_earnings"),
            ytd_cpp2_pensionable_earnings=deductions.get("ytd_cpp2_pensionable_earnings"),
            ytd_insurable_earnings=deductions.get("ytd_insurable_earnings"),
            ytd_basic_exemption_used=deductions.get("ytd_basic_exemption_used"),
            ytd_ss_wages_after=deductions.get("ytd_ss_wages_after"),
            ytd_futa_wages_after=deductions.get("ytd_futa_wages_after"),
            ytd_medicare_wages_after=deductions.get("ytd_medicare_wages_after"),
            ytd_sg_qualifying_earnings_after=deductions.get("ytd_sg_qualifying_earnings_after"),
            ytd_whm_earnings_after=deductions.get("ytd_whm_earnings_after"),
            ytd_ky_mandatory_pensionable_earnings_after=deductions.get("ytd_ky_mandatory_pensionable_earnings_after"),
            ytd_cpf_ow_subject_after=deductions.get("ytd_cpf_ow_subject_after"),
            ytd_cpf_aw_subject_after=deductions.get("ytd_cpf_aw_subject_after"),
            ytd_cpf_aw_paid_after=deductions.get("ytd_cpf_aw_paid_after"),
            sgp_calculation_trace=deductions.get("sgp_calculation_trace"),
            ytd_gy_paye_credit_after=deductions.get("ytd_gy_paye_credit_after"),
            ytd_pr_ss_wages_after=deductions.get("ytd_pr_ss_wages_after"),
            ytd_pr_medicare_wages_after=deductions.get("ytd_pr_medicare_wages_after"),
            ytd_pr_futa_wages_after=deductions.get("ytd_pr_futa_wages_after"),
            ytd_pr_unemployment_wages_after=deductions.get("ytd_pr_unemployment_wages_after"),
            ytd_pr_sinot_wages_after=deductions.get("ytd_pr_sinot_wages_after"),
            pr_unemployment_rate_configured=deductions.get("pr_unemployment_rate_configured", True),
            pr_cfse_rate_configured=deductions.get("pr_cfse_rate_configured", True),
            au_whm_cap_exceeded=deductions.get("au_whm_cap_exceeded", False),
            sg_qualifying_earnings_period=deductions.get("sg_qualifying_earnings_period"),
            sg_rate_pct=deductions.get("sg_rate_pct"),
            sg_mcb_reached=deductions.get("sg_mcb_reached"),
            option2_cumulative_gross_after=deductions.get("option2_cumulative_gross_after"),
            option2_periods_elapsed_after=deductions.get("option2_periods_elapsed_after"),
            option2_federal_tax_withheld_after=deductions.get("option2_federal_tax_withheld_after"),
            option2_provincial_tax_withheld_after=deductions.get("option2_provincial_tax_withheld_after"),
            tds=deductions.get("tds", Decimal("0")),
            annual_tax=deductions.get("annual_tax", Decimal("0")),
            surcharge=deductions.get("surcharge", Decimal("0")),
            cess=deductions.get("cess", Decimal("0")),
            federal_income_tax=deductions.get("federal_income_tax", Decimal("0")),
            state_income_tax=deductions.get("state_income_tax", Decimal("0")),
            local_tax=deductions.get("local_tax", Decimal("0")),
            state_disability_insurance=deductions.get("state_disability_insurance", Decimal("0")),
            germany_statutory_profile_id=deductions.get("_germany_statutory_profile_id"),
            germany_calculation_snapshot=deductions.get("_germany_calculation_snapshot"),
            germany_unavailable_components=germany_unavailable_components,
            state_program_deductions=deductions.get("state_program_deductions", Decimal("0")),
            total_deductions=total_employee_deductions,
            net_pay=net_pay,
            wage_deduction_cap_exceeded=wage_deduction_cap_exceeded,
        )

"""
modules/payroll/engine/countries/canada.py
----------------------------------------------
Canada: CPP + EI (each with its own separate cap) + progressive federal
income tax with the income-tapered Basic Personal Amount and the Canada
Employment Amount credit, plus generic province/territory income tax
(consumed only once real state-scoped rows are configured — see
_calculate_provincial_tax_ca).

Quebec is routed through a dedicated split-authority path instead (see
calculate()'s is_quebec branch, _calculate_quebec_provincial_tax): QPP
replaces CPP, QPIP replaces EI, the federal abatement reduces (not
replaces) CRA federal tax, and Quebec's own income tax runs as its own
module rather than the generic provincial bracket path — per
ZP-TAX-CA-2026-001 §9/§12's "do not reconstruct Quebec from the generic
provincial tax table." QPP/QPIP rates and Quebec's own tax
brackets/Basic Personal Amount are genuinely Quebec-specific statutory
data with no hardcoded fallback — same as every other province, entered
via Super Admin, not this file.

NWT/Nunavut employee territorial payroll tax is implemented (reuses the
generic `local_tax` field). Workers' compensation (WSIB/WCB/CNESST) is
implemented as a tenant-specific EmployerTaxProfile rate, exactly like
US SUI (reuses `employer_sui`) — never a global-default rate, per
CA-D06/AC-24. Ontario/BC EHT, Manitoba HE Levy, and NL HAPSET are NOT
implemented: they're banded on an org's AGGREGATE annual remuneration
across every employee (not a per-employee capped rate EmployerTaxProfile
can express), which needs an org-level accumulator this engine doesn't
have yet — a materially different piece of architecture, not a data gap.

TD1X employee-requested additional withholding (td1_additional_tax) and
the CPT30 CPP/QPP stop election (cpp_qpp_election_status) are
implemented. The province-of-employment resolver (service.py's
_resolve_ca_poe_with_source) now covers single-establishment AND
full-time remote-work "reasonable attachment" — multi-establishment
time-weighting still needs real establishment records this schema
doesn't have for any country, and remains unimplemented — see
ZP-TAX-CA-2026-001.
"""

from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _CA_CPP_YMPE, _CA_CPP_BASIC_EXEMPTION, _CA_EI_MIE, _CA_BASIC_PERSONAL_AMOUNT,
    _CA_CPP2_YAMPE, _CA_CPP2_RATE,
    _CA_BPAF_MIN, _CA_BPAF_NI_THRESHOLD_LOW, _CA_BPAF_NI_THRESHOLD_HIGH,
    _CA_CEA, _CA_LOWEST_FEDERAL_RATE, _CA_QUEBEC_FEDERAL_ABATEMENT_PCT,
)


def _resolve_ca_bpaf(net_income: Decimal, rate_map: dict) -> Decimal:
    """Federal Basic Personal Amount (BPAF), income-tapered per
    ZP-TAX-CA-2026-001 §6: flat at the maximum below the low NI
    threshold, linearly reduced to the minimum by the high threshold,
    flat at the minimum above it. `net_income` approximates the doc's
    "NI = A + HD" as annual taxable income before BPA is applied — HD
    (certain additional deductions) isn't modeled anywhere else in this
    engine either."""
    bpaf_max = resolve_jurisdiction_parameter(rate_map, "basic_personal_amt", _CA_BASIC_PERSONAL_AMOUNT, country="CA")
    bpaf_min = resolve_jurisdiction_parameter(rate_map, "bpaf_min", _CA_BPAF_MIN, country="CA")
    threshold_low = resolve_jurisdiction_parameter(rate_map, "bpaf_ni_thresh_lo", _CA_BPAF_NI_THRESHOLD_LOW, country="CA")
    threshold_high = resolve_jurisdiction_parameter(rate_map, "bpaf_ni_thresh_hi", _CA_BPAF_NI_THRESHOLD_HIGH, country="CA")

    if net_income <= threshold_low:
        return bpaf_max
    if net_income >= threshold_high:
        return bpaf_min
    reduction = (net_income - threshold_low) * (bpaf_max - bpaf_min) / (threshold_high - threshold_low)
    return _round2(bpaf_max - reduction)


def _calculate_annual_tax_ca(annual_gross: Decimal, slabs, rate_map: dict, td1_claim_amount: Optional[Decimal] = None) -> Decimal:
    # TD1 on file overrides the dynamic BPAF entirely — the doc's own
    # "Federal TD1 default: Dynamic BPAF. If no TD1 is on file, follow
    # T4127 default logic" (§6) implies the reverse too: an employee's
    # own filed claim amount, not the government default, applies once
    # a TD1 exists. td1_claim_amount is genuinely employee-declared data,
    # so 0 (an employee who explicitly claimed $0) is honored as-is —
    # only None ("no TD1 on file") falls back to the dynamic BPAF.
    bpa = td1_claim_amount if td1_claim_amount is not None else _resolve_ca_bpaf(annual_gross, rate_map)
    taxable = max(Decimal("0"), annual_gross - bpa)
    tax_before_credits = _calculate_annual_tax(taxable, slabs)

    # Canada Employment Amount — a non-refundable credit, converted to a
    # tax reduction at the lowest federal rate (unlike BPA above, which
    # is a deduction from taxable income, not a credit). Quebec
    # abatement and the beyond-province surtax are deliberately not
    # applied here — see the _CA_QUEBEC_FEDERAL_ABATEMENT_PCT /
    # _CA_BEYOND_PROVINCE_SURTAX_PCT comment in hardcoded_defaults.py.
    cea = resolve_jurisdiction_parameter(rate_map, "cea", _CA_CEA, country="CA")
    lowest_rate = resolve_jurisdiction_parameter(rate_map, "lowest_fed_rate", _CA_LOWEST_FEDERAL_RATE, country="CA")
    cea_credit = _round2(cea * lowest_rate / Decimal("100"))
    return max(Decimal("0"), tax_before_credits - cea_credit)


def _calculate_provincial_tax_ca(annual_gross: Decimal, work_state: Optional[str], state_slabs: list, state_rate_map: dict) -> Decimal:
    """Provincial/territorial income tax — only ever non-zero once the
    resolved province has real state-scoped TaxSlab rows configured (see
    service.get_state_scoped_config's own docstring); an unconfigured
    province correctly resolves to 0, never a guess. A province-specific
    Basic Personal Amount is read from state_rate_map's "provincial_bpa"
    row the same way federal BPA is read from rate_map — a province with
    no such row configured gets $0 provincial BPA, not the federal one.

    Quebec is NEVER calculated through this generic bracket path — its
    tax is a Revenu Québec formula, not a marginal-rate table
    (ZP-TAX-CA-2026-001 §9/§12: "do not reconstruct Quebec from the
    generic provincial tax table"). This checks the raw work_state field
    rather than the fully POE-resolved province, so an employee who
    reaches Quebec only via the org-jurisdiction-state fallback (no
    work_state of their own) is NOT caught by this guard — closing that
    gap properly needs the dedicated Quebec resolution path (mirroring
    resolve_uk_configuration) that a future Quebec module should add,
    threading the POE result explicitly rather than this raw field."""
    if (work_state or "").strip().upper() == "QC":
        return Decimal("0")
    if not state_slabs:
        return Decimal("0")
    provincial_bpa_row = (state_rate_map or {}).get("provincial_bpa")
    provincial_bpa = provincial_bpa_row.flat_amount if provincial_bpa_row and provincial_bpa_row.flat_amount else Decimal("0")
    taxable = max(Decimal("0"), annual_gross - provincial_bpa)
    return _calculate_annual_tax(taxable, state_slabs)


def _calculate_quebec_provincial_tax(annual_gross: Decimal, state_slabs: list, state_rate_map: dict) -> Decimal:
    """Quebec's own income tax — an independent Revenu Québec formula
    module, not the generic provincial bracket path above (which
    explicitly excludes Quebec). Reads the same ctx.state_slabs/
    state_rate_map fields the generic path reads, scoped to
    jurisdiction_state "QC" — the two functions never both run for the
    same employee, since calculate() branches on is_quebec before
    choosing which one to call. Quebec's own Basic Personal Amount comes
    from state_rate_map's "quebec_bpa" row — genuinely Quebec-specific
    statutory data with no hardcoded fallback, same as every province's
    own basic amount."""
    if not state_slabs:
        return Decimal("0")
    bpa_row = (state_rate_map or {}).get("quebec_bpa")
    bpa = bpa_row.flat_amount if bpa_row and bpa_row.flat_amount else Decimal("0")
    taxable = max(Decimal("0"), annual_gross - bpa)
    return _calculate_annual_tax(taxable, state_slabs)


_CA_TERRITORIAL_PAYROLL_TAX_KEYS = {"NT": "nwt_payroll_tax", "NU": "nu_payroll_tax"}


def _calculate_territorial_payroll_tax_ca(annual_gross: Decimal, work_state: Optional[str], state_rate_map: dict) -> Decimal:
    """NWT/Nunavut employee-paid territorial payroll tax — an EMPLOYEE
    deduction, never an employer expense (ZP-TAX-CA-2026-001 AC-18).
    Genuinely territory-specific statutory data with no hardcoded
    fallback, same treatment as every province's own rates — resolves
    to 0 for any other jurisdiction or when unconfigured."""
    component_key = _CA_TERRITORIAL_PAYROLL_TAX_KEYS.get((work_state or "").strip().upper())
    if not component_key:
        return Decimal("0")
    rate_row = (state_rate_map or {}).get(component_key)
    if not rate_row or not rate_row.employee_rate_pct:
        return Decimal("0")
    return _round2((annual_gross * rate_row.employee_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)


def calculate(ctx: PayrollContext) -> dict:
    """Canada: CPP/QPP (contributory earnings floored by the Basic
    Exemption Amount, capped at the Year's Maximum Pensionable Earnings)
    + EI/QPIP (capped separately at its own Maximum Insurable Earnings)
    + progressive federal income tax with the income-tapered Basic
    Personal Amount deducted first, then the Canada Employment Amount
    credit applied (and the Quebec federal abatement, for Quebec) +
    provincial/territorial income tax where configured — Quebec routed
    through its own split-authority branch throughout (QPP instead of
    CPP, QPIP instead of EI, Revenu Québec's own tax module instead of
    the generic provincial bracket path) — plus NWT/Nunavut employee
    territorial payroll tax and employer-specific workers' compensation
    where configured. DB-backed rates.

    Reused PayrollResult fields: `social_security`/`employer_social_security`
    (CPP or QPP), `employee_esi`/`employer_esi` (EI or QPIP), `local_tax`
    (NWT/Nunavut territorial tax), `employer_sui` (workers' comp). Canada-
    specific fields: `cpp2`/`employer_cpp2` (CPP2 or QPP2, both sides)."""
    rate_map = ctx.rate_map
    state_rate_map = ctx.state_rate_map or {}
    gross = ctx.gross
    annual_gross = gross * MONTHS_PER_YEAR
    is_quebec = (ctx.work_state or "").strip().upper() == "QC"

    # First-layer pension contribution: CPP everywhere except Quebec,
    # which routes to QPP instead — identical YMPE/basic-exemption
    # mechanics either way (ZP-TAX-CA-2026-001 §12), only the
    # contribution rate/max differs. QPP's rate has no hardcoded
    # fallback — genuinely Quebec-specific statutory data, entered via
    # Super Admin like every other province's own rates.
    cpp_ympe = resolve_jurisdiction_parameter(rate_map, "cpp_ympe", _CA_CPP_YMPE, country="CA")
    cpp_basic_exemption = resolve_jurisdiction_parameter(rate_map, "cpp_basic_exemption", _CA_CPP_BASIC_EXEMPTION, country="CA")

    # ZP-TAX-CA-2026-001 §10: "YTD caps: Employee and employer contribution
    # caps enforced independently with exact year-to-date accumulators."
    # ctx.ytd_pensionable_earnings is None for every employee/country until
    # engine/countries/shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES opts
    # CA in AND service.py's _load_ca_ytd finds a real accumulator row —
    # the `is not None` branch below is net-new; the `else` branch is the
    # EXACT prior current-period-annualized behavior, byte-for-byte
    # unchanged, so nothing changes for anyone until both gates are open.
    if ctx.ytd_pensionable_earnings is not None:
        # The $3,500 basic exemption is allocated pro-rata per pay period
        # against YTD-consumed exemption, not applied once against a
        # single period's annualized figure (§10: "allocated using CRA
        # pay-period rules; store irregular-pay treatment separately").
        ytd_exemption_used = ctx.ytd_basic_exemption_used or Decimal("0")
        period_exemption = min(
            cpp_basic_exemption / MONTHS_PER_YEAR,
            max(Decimal("0"), cpp_basic_exemption - ytd_exemption_used),
        )
        pensionable_room = max(Decimal("0"), cpp_ympe - ctx.ytd_pensionable_earnings)
        period_first_layer_pensionable = max(Decimal("0"), min(gross, pensionable_room) - period_exemption)
        ytd_pensionable_earnings_after = ctx.ytd_pensionable_earnings + period_first_layer_pensionable
        ytd_basic_exemption_used_after = ytd_exemption_used + period_exemption
        # This period's gross beyond first-layer room is the pool eligible
        # for CPP2/QPP2 below — correctly starts CPP2 exactly at the pay
        # period where the employee crosses YMPE mid-period, not before.
        period_gross_over_ympe = max(Decimal("0"), gross - pensionable_room)
    else:
        annual_first_layer_pensionable = max(Decimal("0"), min(annual_gross, cpp_ympe) - cpp_basic_exemption)
        period_first_layer_pensionable = annual_first_layer_pensionable / MONTHS_PER_YEAR
        ytd_pensionable_earnings_after = None
        ytd_basic_exemption_used_after = None
        period_gross_over_ympe = max(Decimal("0"), annual_gross - cpp_ympe) / MONTHS_PER_YEAR

    pension_rate = state_rate_map.get("qpp") if is_quebec else rate_map.get("cpp")
    social_security = (
        _round2(period_first_layer_pensionable * (pension_rate.employee_rate_pct / 100))
        if pension_rate and pension_rate.employee_rate_pct else Decimal("0")
    )
    employer_social_security = (
        _round2(period_first_layer_pensionable * (pension_rate.employer_rate_pct / 100))
        if pension_rate and pension_rate.employer_rate_pct else Decimal("0")
    )

    # CPP2/QPP2 — identical corridor and rate in both cases per the doc
    # ("QPP2 rate/max: 4.00% each on $10,400 corridor; max $416 each" —
    # the same figures as CPP2), so no Quebec branching is needed here.
    # Employee and employer sides are both resolved from the same "cpp2_rate"
    # ContributionRate row (componentKeyOptions now offers Employee %/
    # Employer % — previously employer-side was never resolved at all, so
    # the employer's own CPP2/QPP2 contribution went entirely untracked).
    cpp2_yampe = resolve_jurisdiction_parameter(rate_map, "cpp2_yampe", _CA_CPP2_YAMPE, country="CA")
    cpp2_rate = resolve_jurisdiction_parameter(rate_map, "cpp2_rate", _CA_CPP2_RATE, side="employee", country="CA")
    cpp2_rate_employer = resolve_jurisdiction_parameter(rate_map, "cpp2_rate", _CA_CPP2_RATE, side="employer", country="CA")
    if ctx.ytd_cpp2_pensionable_earnings is not None:
        cpp2_room = max(Decimal("0"), (cpp2_yampe - cpp_ympe) - ctx.ytd_cpp2_pensionable_earnings)
        period_cpp2_pensionable = max(Decimal("0"), min(period_gross_over_ympe, cpp2_room))
        ytd_cpp2_pensionable_earnings_after = ctx.ytd_cpp2_pensionable_earnings + period_cpp2_pensionable
    else:
        annual_cpp2_pensionable = max(Decimal("0"), min(annual_gross, cpp2_yampe) - cpp_ympe)
        period_cpp2_pensionable = annual_cpp2_pensionable / MONTHS_PER_YEAR
        ytd_cpp2_pensionable_earnings_after = None
    cpp2 = _round2(period_cpp2_pensionable * (cpp2_rate / Decimal("100")))
    employer_cpp2 = _round2(period_cpp2_pensionable * (cpp2_rate_employer / Decimal("100")))

    # CPT30 election — an eligible age-65-69 retirement-pension recipient
    # who has filed to STOP CPP/QPP withholding. Applies to the first-
    # layer contribution and CPP2/QPP2 alike (both sides); EI/QPIP is
    # untouched (CPT30 is specifically a CPP/QPP election per
    # ZP-TAX-CA-2026-001 §18). Stopped means no obligation accrues this
    # period at all, so YTD must NOT grow either — not just the withheld
    # amounts — otherwise a later un-stopped period would under-collect
    # against room that was never actually used.
    if (ctx.cpp_qpp_election_status or "").strip().upper() == "STOPPED":
        social_security = Decimal("0")
        employer_social_security = Decimal("0")
        cpp2 = Decimal("0")
        employer_cpp2 = Decimal("0")
        if ytd_pensionable_earnings_after is not None:
            ytd_pensionable_earnings_after = ctx.ytd_pensionable_earnings
            ytd_basic_exemption_used_after = ctx.ytd_basic_exemption_used or Decimal("0")
        if ytd_cpp2_pensionable_earnings_after is not None:
            ytd_cpp2_pensionable_earnings_after = ctx.ytd_cpp2_pensionable_earnings

    if is_quebec:
        # QPIP entirely replaces EI for a Quebec employee. Both its rate
        # and its Maximum Insurable Earnings are genuinely Quebec-
        # specific statutory data with no hardcoded fallback (unlike
        # EI's federal MIE below) — computing anything requires both the
        # rate row AND the cap row to actually be configured; never
        # guess one from the other.
        qpip_rate = state_rate_map.get("qpip")
        qpip_mie_row = state_rate_map.get("qpip_mie")
        insurable_mie = qpip_mie_row.flat_amount if qpip_mie_row and qpip_mie_row.flat_amount else None
        rate_row = qpip_rate
    else:
        insurable_mie = resolve_jurisdiction_parameter(rate_map, "ei_mie", _CA_EI_MIE, country="CA")
        rate_row = rate_map.get("ei")

    if insurable_mie is not None:
        if ctx.ytd_insurable_earnings is not None:
            insurable_room = max(Decimal("0"), insurable_mie - ctx.ytd_insurable_earnings)
            period_insurable = max(Decimal("0"), min(gross, insurable_room))
            ytd_insurable_earnings_after = ctx.ytd_insurable_earnings + period_insurable
        else:
            period_insurable = min(annual_gross, insurable_mie) / MONTHS_PER_YEAR
            ytd_insurable_earnings_after = None
        employee_esi = (
            _round2(period_insurable * (rate_row.employee_rate_pct / 100))
            if rate_row and rate_row.employee_rate_pct else Decimal("0")
        )
        employer_esi = (
            _round2(period_insurable * (rate_row.employer_rate_pct / 100))
            if rate_row and rate_row.employer_rate_pct else Decimal("0")
        )
    else:
        # Quebec with no qpip_mie configured — matches prior behavior
        # exactly (never guess a cap from an unconfigured row).
        employee_esi = Decimal("0")
        employer_esi = Decimal("0")
        ytd_insurable_earnings_after = ctx.ytd_insurable_earnings if ctx.ytd_insurable_earnings is not None else None

    annual_federal_tax = _calculate_annual_tax_ca(annual_gross, ctx.slabs, rate_map, ctx.td1_claim_amount)
    if is_quebec:
        # Quebec federal abatement — CRA federal tax is reduced (not
        # replaced) for a Quebec employee, since Quebec collects its own
        # provincial tax independently of the generic provincial path
        # (ZP-TAX-CA-2026-001 §6/§12). This constant WAS already prepared
        # in Phase 2 specifically for this branch.
        abatement_pct = resolve_jurisdiction_parameter(rate_map, "qc_fed_abatement", _CA_QUEBEC_FEDERAL_ABATEMENT_PCT, country="CA")
        annual_federal_tax = _round2(annual_federal_tax * (Decimal("100") - abatement_pct) / Decimal("100"))
    federal_income_tax = _round2(annual_federal_tax / MONTHS_PER_YEAR)

    if is_quebec:
        annual_provincial_tax = _calculate_quebec_provincial_tax(annual_gross, ctx.state_slabs, state_rate_map)
    else:
        annual_provincial_tax = _calculate_provincial_tax_ca(annual_gross, ctx.work_state, ctx.state_slabs, state_rate_map)
    state_income_tax = _round2(annual_provincial_tax / MONTHS_PER_YEAR)

    # NWT/Nunavut employee territorial payroll tax — reuses the generic
    # `local_tax` field (the same one US locality tax populates). MUST be
    # folded into tds below: engine/standard.py's total_employee_
    # deductions sums `tds`, not `local_tax` separately (exactly why
    # us.py's own tds already includes its local_tax) — leaving it out
    # here would silently never deduct it from net pay.
    local_tax = _calculate_territorial_payroll_tax_ca(annual_gross, ctx.work_state, state_rate_map)

    # TD1X employee-requested additional withholding — additive on top
    # of the statutory calculation, never overwriting it
    # (ZP-TAX-CA-2026-001 §18). A flat per-pay-period amount, not
    # annualized (matches how the employee actually requested it).
    td1_additional_tax = ctx.td1_additional_tax or Decimal("0")

    annual_tax = annual_federal_tax + annual_provincial_tax + (td1_additional_tax * MONTHS_PER_YEAR)
    tds = federal_income_tax + state_income_tax + local_tax + td1_additional_tax

    # Workers' compensation (WSIB/WCB/CNESST) — tenant-specific, agency-
    # assigned rate resolved from EmployerTaxProfile (get_employer_tax_
    # profiles in service.py), NOT from rate_map — exactly like US SUI,
    # and exactly what CA-D06/AC-24 require: never a global-default
    # rate, only an employer-specific notice with its own evidence.
    # Reuses the generic `employer_sui` field. Absent a configured
    # profile, this stays 0 — never inferred or guessed.
    wcb_profile = (ctx.employer_tax_profiles or {}).get("WCB")
    employer_sui = Decimal("0")
    if wcb_profile is not None:
        annual_wcb_wage = min(annual_gross, wcb_profile.taxable_wage_base)
        employer_sui = _round2((annual_wcb_wage * wcb_profile.employer_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)

    return dict(
        social_security=social_security, employer_social_security=employer_social_security,
        employee_esi=employee_esi, employer_esi=employer_esi,
        cpp2=cpp2, employer_cpp2=employer_cpp2,
        # Cumulative YTD state AFTER this period — None unless YTD
        # accumulation was actually wired for this calculation (see the
        # ctx.ytd_* is not None checks above). service.py persists these
        # into PayrollYtdAccumulator/PayslipItem.ytd_snapshot; harmless to
        # return None when dormant, since nothing reads these keys yet.
        ytd_pensionable_earnings=ytd_pensionable_earnings_after,
        ytd_cpp2_pensionable_earnings=ytd_cpp2_pensionable_earnings_after,
        ytd_insurable_earnings=ytd_insurable_earnings_after,
        ytd_basic_exemption_used=ytd_basic_exemption_used_after,
        federal_income_tax=federal_income_tax, state_income_tax=state_income_tax,
        local_tax=local_tax, employer_sui=employer_sui,
        tds=tds, annual_tax=annual_tax,
    )

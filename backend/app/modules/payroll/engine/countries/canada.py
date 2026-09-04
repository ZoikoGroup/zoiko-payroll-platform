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
CA-D06/AC-24. Ontario EHT, BC EHT (both the ordinary and registered-
charity/nonprofit variants), Manitoba HE Levy and NL HAPSET are all
implemented — each banded on the ORGANIZATION's aggregate annual
remuneration across every employee via OrganizationYtdAccumulator (see
service.py's _load_ca_org_levy_ytd/_upsert_ca_org_levy_ytd), not any
single employee's own pay. Ontario uses a genuine rate-TABLE lookup
(_on_eht_rate_for_total); BC/MB/NL instead share one generic exemption/
notch/flat-on-total shape (_annual_notch_levy_amount) per
ZP-TAX-CA-2026-001 §15. All four stay dormant (0) until
engine/countries/shared.py's _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES
opts CA in. BC's ordinary-vs-charity/nonprofit classification is read
from ctx.bc_eht_employer_classification — CompanyComplianceDetails has
the column, but no Super Admin/Org Admin UI sets it yet, a disclosed,
known gap (defaults to ordinary for every org until either a UI is
built or it's set directly).

Quebec's own two employer contributions are also implemented:
_calculate_qc_hsf_period_amount (Health Services Fund — same org-level
accumulator contract as the four levies above, but a SLIDING rate
applied to the org's whole Quebec payroll, not a notch/exemption —
General/Primary-Manufacturing/Public-Sector categories read from
ctx.qc_hsf_employer_category, same "no UI sets it yet" disclosed gap as
BC's classification) and _calculate_qc_labour_standards (a per-EMPLOYEE
capped contribution, no org accumulator needed, annualized like CPP/EI
were before their own YTD wiring existed — no hardcoded rate, since the
document withholds one). WSDRF and the "temporary HSF sector exemption"
(§13) are deliberately NOT implemented: WSDRF is a shortfall computed
from eligible TRAINING EXPENDITURE this schema has no concept of at
all, and the sector exemption needs the same kind of effective-dated
employer-eligibility-with-evidence tracking WCB already has but this
doesn't yet — both are separate, materially larger pieces, the same
reasoning Ontario's associated-employer-group allocation was excluded
for. Quebec's "deduction for workers" ($1,450 cap, §12/§13) IS
implemented, inside _calculate_quebec_provincial_tax. The gratuity/
retroactive-pay method threshold and the RDSP fixed-withholding rule
(§12) are NOT implemented — both are non-periodic/special-payment
routing, which needs a payment-type concept nothing in this schema has;
they're blocked by that same explicitly-out-of-scope initiative, not a
Quebec-specific gap.

TD1X employee-requested additional withholding (td1_additional_tax), the
CPT30 CPP/QPP stop election (cpp_qpp_election_status), and the age 18/70
mandatory CPP/QPP contribution window (ctx.date_of_birth/ctx.pay_date,
gated on shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES — see
_is_age_gated_cpp_stopped for the disclosed calendar-age simplification)
are implemented. The province-of-employment resolver (service.py's
_resolve_ca_poe_with_source) now covers single-establishment AND
full-time remote-work "reasonable attachment" — multi-establishment
time-weighting still needs real establishment records this schema
doesn't have for any country, and remains unimplemented — see
ZP-TAX-CA-2026-001.

CORRECTNESS NOTE (found during Phase 6 review, not introduced by it):
federal/provincial/Quebec tax all apply their own "amount" (BPAF/
provincial_bpa/quebec_bpa) as a DEDUCTION from taxable income before
bracket-summing by default — mathematically identical to CRA's real
credit-based method ONLY while income stays inside the lowest bracket.
The CRA-correct method (§7: "T3 = (R×A) − K", crediting the amount at
the LOWEST rate, not deducting it from income) is implemented as an
alternate path in _calculate_annual_tax_ca/_calculate_provincial_tax_ca/
_calculate_quebec_provincial_tax, gated on
shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES (empty by default — the
legacy method remains byte-for-byte the default until this is
deliberately flipped, since doing so changes the actual withheld amount
on every future Canadian payslip, not just a new dormant feature).

The federal K2/K3 credits (§7's full "T3 = (R×A) − K − K1 − K2 − K3 −
K4" formula — the per-pay-period credit for CPP/QPP and EI/QPIP
premiums actually withheld, converted at the lowest rate) are a
genuinely NEW addition, not a correction — this engine never computed
them at all before. Gated on its own shared._CA_CPP_EI_FEDERAL_CREDIT_
ENABLED_COUNTRIES switch (only meaningful once the credit method above
is also enabled), separate from the BPA fix since it's a materially
different kind of change. This is also what correctly handles a
mid-year province transfer (§10) without any transfer-specific code —
the credit is simply based on whatever was actually withheld this
period, regardless of which plan (CPP vs QPP).

The EI/QPIP employer 1.4x-default premium (§11) is implemented, gated
on shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES: while OFF, the
employer rate reads whatever employer_rate_pct is independently
configured on the same "ei"/"qpip" row (today's behavior); once ON, it
defaults to exactly 1.4x the employee rate unless a reduced-rate
EmployerTaxProfile authorization exists (component_code "EI_REDUCED",
looked up at the country level in service.py since EI is a federal
program, not provincial).

Two Phase 8 federal-tax-remainder items are implemented: the
labour-sponsored funds credit (LCF, §6 — 15% of ctx.lsvcc_investment_amount
capped at $750, gated on shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES,
applies under both the legacy and credit-method tax paths since it's
already a direct dollar credit by statute, not an "amount" needing
lowest-rate conversion) and the beyond-province/outside-Canada surtax
(§6/§7 — 48% of T3 for a "XP" work_state employee, the same formula
step as the Quebec abatement just an increase instead of a reduction,
gated on shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES). Option 2
(cumulative averaging) withholding is NOT implemented — this engine
only ever computes Option 1 (annualization); building Option 2 as a
genuine alternative pay-period-withholding methodology is a separate,
larger initiative, not a small addition to this function."""

from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter,
    _CA_CREDIT_METHOD_ENABLED_COUNTRIES, _CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES,
    _CA_AGE_GATED_CPP_ENABLED_COUNTRIES, _CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES,
    _CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES, _CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES,
    _CA_LSVCC_CREDIT_ENABLED_COUNTRIES, _CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES,
    _CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES,
)
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _CA_CPP_YMPE, _CA_CPP_BASIC_EXEMPTION, _CA_EI_MIE, _CA_BASIC_PERSONAL_AMOUNT,
    _CA_CPP2_YAMPE, _CA_CPP2_RATE,
    _CA_BPAF_MIN, _CA_BPAF_NI_THRESHOLD_LOW, _CA_BPAF_NI_THRESHOLD_HIGH,
    _CA_CEA, _CA_LOWEST_FEDERAL_RATE, _CA_QUEBEC_FEDERAL_ABATEMENT_PCT,
    _CA_BEYOND_PROVINCE_SURTAX_PCT, _CA_LSVCC_CREDIT_RATE, _CA_LSVCC_CREDIT_MAX,
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


def _lowest_bracket_rate(slabs) -> Decimal:
    """The rate of the lowest-starting MARGINAL_RATE bracket in a slab
    table — used by the CRA credit method to convert a claim amount
    (BPA) into a dollar credit, since CRA converts every "amount" at the
    LOWEST rate regardless of the employee's own top bracket. Derived
    directly from whatever brackets are actually configured (never a
    separate, independently-editable config row that could drift out of
    sync with the bracket table itself). Excludes the same non-bracket
    rule_types _calculate_annual_tax already excludes (SURCHARGE/
    PT_FLAT/ON_EHT_BAND). Empty/unconfigured slabs resolve to 0%, never
    a guess."""
    bracket_slabs = [s for s in (slabs or []) if getattr(s, "rule_type", None) not in ("SURCHARGE", "PT_FLAT", "ON_EHT_BAND")]
    if not bracket_slabs:
        return Decimal("0")
    return min(bracket_slabs, key=lambda s: s.min_amount).rate_pct or Decimal("0")


def _calculate_lsvcc_credit(lsvcc_investment_amount: Optional[Decimal], rate_map: dict) -> Decimal:
    """Labour-sponsored funds tax credit (LCF, §6): 15% of the employee's
    declared LSVCC share purchase, capped at $750/year — already
    expressed as a direct dollar credit by statute (unlike BPA/CEA/K2/
    K3, which convert an "amount" at the lowest bracket rate), so it
    applies identically under both the legacy and credit-method tax
    paths. None (no LSVCC purchase declared) resolves to $0. Rate/cap
    are DB-configurable like every other federal parameter here, with
    the documented 2026 values as the hardcoded fallback."""
    if not lsvcc_investment_amount:
        return Decimal("0")
    rate = resolve_jurisdiction_parameter(rate_map, "lsvcc_credit_rate", _CA_LSVCC_CREDIT_RATE, country="CA")
    cap = resolve_jurisdiction_parameter(rate_map, "lsvcc_credit_max", _CA_LSVCC_CREDIT_MAX, country="CA")
    return min(_round2(lsvcc_investment_amount * rate / Decimal("100")), cap)


def _calculate_annual_tax_ca(annual_gross: Decimal, slabs, rate_map: dict, td1_claim_amount: Optional[Decimal] = None,
                              period_cpp_contribution: Decimal = Decimal("0"), period_ei_contribution: Decimal = Decimal("0"),
                              lsvcc_investment_amount: Optional[Decimal] = None) -> Decimal:
    # TD1 on file overrides the dynamic BPAF entirely — the doc's own
    # "Federal TD1 default: Dynamic BPAF. If no TD1 is on file, follow
    # T4127 default logic" (§6) implies the reverse too: an employee's
    # own filed claim amount, not the government default, applies once
    # a TD1 exists. td1_claim_amount is genuinely employee-declared data,
    # so 0 (an employee who explicitly claimed $0) is honored as-is —
    # only None ("no TD1 on file") falls back to the dynamic BPAF.
    bpa = td1_claim_amount if td1_claim_amount is not None else _resolve_ca_bpaf(annual_gross, rate_map)
    cea = resolve_jurisdiction_parameter(rate_map, "cea", _CA_CEA, country="CA")
    lowest_rate = resolve_jurisdiction_parameter(rate_map, "lowest_fed_rate", _CA_LOWEST_FEDERAL_RATE, country="CA")
    lsvcc_credit = (
        _calculate_lsvcc_credit(lsvcc_investment_amount, rate_map)
        if "CA" in _CA_LSVCC_CREDIT_ENABLED_COUNTRIES else Decimal("0")
    )

    if "CA" in _CA_CREDIT_METHOD_ENABLED_COUNTRIES:
        # CRA's actual T4127 method (§7: "T3 = (R × A) − K", where K
        # bakes in lowest_rate × the claim amount): BPA is a
        # non-refundable CREDIT converted at the lowest bracket rate and
        # subtracted from tax payable — NOT a deduction from taxable
        # income applied before bracket-summing (see the legacy branch
        # below, and _CA_CREDIT_METHOD_ENABLED_COUNTRIES's own comment
        # in shared.py for why these two methods diverge once income
        # crosses above the first bracket).
        tax_before_credits = _calculate_annual_tax(annual_gross, slabs)
        bpa_credit = _round2(bpa * lowest_rate / Decimal("100"))
        cea_credit = _round2(cea * lowest_rate / Decimal("100"))
        # K2/K3 — the federal credit for CPP/QPP and EI/QPIP premiums
        # actually withheld THIS PERIOD, converted at the lowest rate
        # (§7: "T3 = (R×A) − K − K1 − K2 − K3 − K4"). Gated on its own
        # switch, separate from the BPA-as-credit fix above: this is a
        # genuinely NEW credit that never existed in this engine at all
        # (not a correction of an existing one), so it's a materially
        # different kind of change an org should decide on independently
        # — see _CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES's own comment
        # in shared.py. This is also what correctly handles a mid-year
        # province transfer (§10) without any special-case logic: the
        # credit is simply based on whatever CPP/QPP + EI/QPIP was
        # actually withheld this period, regardless of which plan.
        k2_k3_credit = (
            _round2((period_cpp_contribution + period_ei_contribution) * MONTHS_PER_YEAR * lowest_rate / Decimal("100"))
            if "CA" in _CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES else Decimal("0")
        )
        return max(Decimal("0"), tax_before_credits - bpa_credit - cea_credit - k2_k3_credit - lsvcc_credit)

    # Legacy/dormant path — byte-for-byte unchanged until
    # _CA_CREDIT_METHOD_ENABLED_COUNTRIES opts CA in.
    taxable = max(Decimal("0"), annual_gross - bpa)
    tax_before_credits = _calculate_annual_tax(taxable, slabs)
    cea_credit = _round2(cea * lowest_rate / Decimal("100"))
    return max(Decimal("0"), tax_before_credits - cea_credit - lsvcc_credit)


def _resolve_mb_bpa(net_income: Decimal, state_rate_map: dict) -> Decimal:
    """Manitoba's income-tapered Basic Personal Amount (BPAMB, §8) — a
    DIFFERENT taper shape from federal BPAF: it floors at exactly $0
    past the high threshold rather than a separate nonzero minimum,
    because the linear reduction reaches the full max exactly at that
    threshold by construction ("if NI >= $400,000, use $0" falls
    straight out of the formula itself, not an independent floor value
    like federal's $14,829). Genuinely Manitoba-specific statutory data
    with no hardcoded fallback — an unconfigured max/threshold row
    resolves this to $0, never a guess."""
    max_row = (state_rate_map or {}).get("mb_bpa_max")
    threshold_low_row = (state_rate_map or {}).get("mb_bpa_ni_thresh_lo")
    threshold_high_row = (state_rate_map or {}).get("mb_bpa_ni_thresh_hi")
    bpa_max = max_row.flat_amount if max_row and max_row.flat_amount is not None else None
    threshold_low = threshold_low_row.flat_amount if threshold_low_row else None
    threshold_high = threshold_high_row.flat_amount if threshold_high_row else None
    if bpa_max is None or threshold_low is None or threshold_high is None or threshold_high <= threshold_low:
        return Decimal("0")
    if net_income <= threshold_low:
        return bpa_max
    if net_income >= threshold_high:
        return Decimal("0")
    reduction = (net_income - threshold_low) * (bpa_max / (threshold_high - threshold_low))
    return max(Decimal("0"), _round2(bpa_max - reduction))


def _calculate_provincial_tax_ca(
    annual_gross: Decimal, work_state: Optional[str], state_slabs: list, state_rate_map: dict,
    provincial_td1_claim_amount: Optional[Decimal] = None, rate_map: Optional[dict] = None,
) -> Decimal:
    """Provincial/territorial income tax — only ever non-zero once the
    resolved province has real state-scoped TaxSlab rows configured (see
    service.get_state_scoped_config's own docstring); an unconfigured
    province correctly resolves to 0, never a guess. A province-specific
    Basic Personal Amount is read from state_rate_map's "provincial_bpa"
    row the same way federal BPA is read from rate_map — a province with
    no such row configured gets $0 provincial BPA, not the federal one.
    Two provinces get their own dynamic formula instead of that flat
    row (§8's "Dynamic basic amounts" note): Manitoba via _resolve_mb_bpa
    (its own income-tapered formula), and Yukon via _resolve_ca_bpaf
    reusing the FEDERAL rate_map — "BPAYT = BPAF" literally means Yukon's
    basic amount always equals whatever the federal BPAF resolves to,
    not a separately-configured Yukon value. Both are gated behind
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES (empty by
    default) — an org that already has a flat provincial_bpa row
    configured for MB/YT must not see its tax silently change the
    moment this ships; the flat-row path remains the default for every
    province, MB/YT included, until deliberately flipped. An employee's
    own filed provincial TD1 claim amount overrides ALL THREE of these
    (flat row, Manitoba's formula, Yukon's federal mirror) entirely,
    mirroring exactly how _calculate_annual_tax_ca's td1_claim_amount
    already overrides the federal BPAF (ZP-TAX-CA-2026-001 §18) — None
    means "no provincial TD1 on file," not "claimed $0."

    BC also gets its own "basic tax reduction" (§9) — a flat dollar
    subtraction from provincial tax payable, gated on shared._CA_BC_TAX_
    REDUCTION_ENABLED_COUNTRIES; see the disclosed simplification in the
    comment at its computation site below (no income-based phase-out,
    and uses the single annual figure since H1-vs-H2 canonical rows
    can't actually be distinguished by this function's own data source).

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
    state = (work_state or "").strip().upper()
    if state == "QC":
        return Decimal("0")
    if not state_slabs:
        return Decimal("0")
    use_dynamic_bpa = "CA" in _CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES
    if provincial_td1_claim_amount is not None:
        provincial_bpa = provincial_td1_claim_amount
    elif state == "MB" and use_dynamic_bpa:
        provincial_bpa = _resolve_mb_bpa(annual_gross, state_rate_map)
    elif state == "YT" and use_dynamic_bpa:
        provincial_bpa = _resolve_ca_bpaf(annual_gross, rate_map or {})
    else:
        # Legacy/dormant path for MB/YT (and every other province always)
        # — byte-for-byte unchanged until
        # _CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES opts CA in.
        provincial_bpa_row = (state_rate_map or {}).get("provincial_bpa")
        provincial_bpa = provincial_bpa_row.flat_amount if provincial_bpa_row and provincial_bpa_row.flat_amount else Decimal("0")

    # BC's own "basic tax reduction" (§9) — a flat dollar SUBTRACTION from
    # provincial tax payable, on top of (not instead of) the BPA credit/
    # deduction above; a third, BC-specific kind of adjustment. Gated on
    # its own switch since it's genuinely new.
    #
    # DISCLOSED SIMPLIFICATION (deliberate, not an oversight): the real
    # BC reduction phases out with income — the document gives only the
    # dollar amount ($690 annual / $575 H1 / $805 H2), never the phase-
    # out formula, so this applies the FULL amount to every BC taxpayer
    # regardless of income, which is WRONG for higher earners the real
    # reduction would already have zeroed out.
    #
    # Uses the single annual "$690" figure (the doc's own "annual/
    # statutory position" row) rather than H1's $575 or H2's $805,
    # because service.get_state_scoped_config (which resolves
    # state_rate_map here) reads canonical rows by (country, state) with
    # NO JurisdictionPack/effective-date filtering at all — it cannot
    # actually distinguish an H1 canonical row from an H2 one today, so
    # entering two different values for the same component_key would
    # just make resolution depend on row insertion order, not the pay
    # date. That gap is real and pre-existing (found while placing this
    # exact feature), not something this function works around.
    bc_reduction = Decimal("0")
    if state == "BC" and "CA" in _CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES:
        bc_reduction_row = (state_rate_map or {}).get("bc_basic_tax_reduction")
        bc_reduction = bc_reduction_row.flat_amount if bc_reduction_row and bc_reduction_row.flat_amount else Decimal("0")

    if "CA" in _CA_CREDIT_METHOD_ENABLED_COUNTRIES:
        # Same CRA-correct credit-method switch as _calculate_annual_tax_ca
        # above (see _CA_CREDIT_METHOD_ENABLED_COUNTRIES's own comment in
        # shared.py) — provincial_bpa becomes a credit at the PROVINCE's
        # own lowest bracket rate, not a deduction from taxable income.
        lowest_rate = _lowest_bracket_rate(state_slabs)
        tax_before_credits = _calculate_annual_tax(annual_gross, state_slabs)
        bpa_credit = _round2(provincial_bpa * lowest_rate / Decimal("100"))
        return max(Decimal("0"), tax_before_credits - bpa_credit - bc_reduction)

    # Legacy/dormant path — byte-for-byte unchanged until
    # _CA_CREDIT_METHOD_ENABLED_COUNTRIES opts CA in.
    taxable = max(Decimal("0"), annual_gross - provincial_bpa)
    return max(Decimal("0"), _calculate_annual_tax(taxable, state_slabs) - bc_reduction)


def _calculate_quebec_provincial_tax(
    annual_gross: Decimal, state_slabs: list, state_rate_map: dict,
    qc_tp1015_claim_amount: Optional[Decimal] = None,
) -> Decimal:
    """Quebec's own income tax — an independent Revenu Québec formula
    module, not the generic provincial bracket path above (which
    explicitly excludes Quebec). Reads the same ctx.state_slabs/
    state_rate_map fields the generic path reads, scoped to
    jurisdiction_state "QC" — the two functions never both run for the
    same employee, since calculate() branches on is_quebec before
    choosing which one to call. Quebec's own Basic Personal Amount comes
    from state_rate_map's "quebec_bpa" row — genuinely Quebec-specific
    statutory data with no hardcoded fallback, same as every province's
    own basic amount. An employee's own filed TP-1015.3-V claim amount
    overrides that canonical quebec_bpa — Quebec's own declaration,
    legally distinct from federal/provincial TD1 (ZP-TAX-CA-2026-001
    §18: "maintain separately from federal TD1"). Also applies Quebec's
    "deduction for workers" (§12/§13 parameter table: "Maximum deduction
    for workers $1,450") as a straight reduction to taxable income, read
    from state_rate_map's "qc_worker_deduction" row — genuinely Quebec-
    specific statutory data with no hardcoded fallback, resolving to $0
    when unconfigured. Disclosed simplification: the document gives only
    the cap, not Revenu Québec's underlying eligible-work-income
    formula, so this assumes every Quebec employee is fully eligible up
    to that cap rather than computing eligibility — never OVER-deducts,
    since it's still capped at the employee's own annual_gross.

    Under _CA_CREDIT_METHOD_ENABLED_COUNTRIES, `bpa` switches to a
    credit at Quebec's own lowest bracket rate (same CRA/Revenu-Québec-
    correct method as the federal/provincial functions) — but
    worker_deduction stays a genuine income deduction in BOTH methods,
    since Revenu Québec's "déduction pour travailleurs" really is a
    line-item deduction from income, not a credit; only the basic-
    personal-amount-equivalent changes treatment."""
    if not state_slabs:
        return Decimal("0")
    if qc_tp1015_claim_amount is not None:
        bpa = qc_tp1015_claim_amount
    else:
        bpa_row = (state_rate_map or {}).get("quebec_bpa")
        bpa = bpa_row.flat_amount if bpa_row and bpa_row.flat_amount else Decimal("0")
    worker_deduction_row = (state_rate_map or {}).get("qc_worker_deduction")
    worker_deduction = (
        min(annual_gross, worker_deduction_row.flat_amount)
        if worker_deduction_row and worker_deduction_row.flat_amount else Decimal("0")
    )

    if "CA" in _CA_CREDIT_METHOD_ENABLED_COUNTRIES:
        lowest_rate = _lowest_bracket_rate(state_slabs)
        taxable = max(Decimal("0"), annual_gross - worker_deduction)
        tax_before_credits = _calculate_annual_tax(taxable, state_slabs)
        bpa_credit = _round2(bpa * lowest_rate / Decimal("100"))
        return max(Decimal("0"), tax_before_credits - bpa_credit)

    # Legacy/dormant path — byte-for-byte unchanged until
    # _CA_CREDIT_METHOD_ENABLED_COUNTRIES opts CA in.
    taxable = max(Decimal("0"), annual_gross - bpa - worker_deduction)
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


# Ontario Employer Health Tax — banded on the ORGANIZATION's aggregate
# annual Ontario remuneration across every employee, not any single
# employee's own pay (ZP-TAX-CA-2026-001 §15/§16). $5M exemption-eligibility
# phaseout threshold is the one number the document treats as a fixed
# statutory fact rather than a versioned rate/threshold row (unlike the
# $1,000,000 exemption itself, which IS configurable — see
# on_eht_exemption below); kept as a plain constant for that reason, same
# footing as MONTHS_PER_YEAR elsewhere in this engine.
_CA_ON_EHT_EXEMPTION_PHASEOUT_THRESHOLD = Decimal("5000000")

# EI/QPIP employer premium multiplier (§11: "Default employer EI is
# 1.4 × employee premium") — a fixed statutory ratio, not a versioned
# rate/threshold row, same footing as the phaseout threshold above.
_CA_EI_EMPLOYER_MULTIPLIER = Decimal("1.4")


def _on_eht_rate_for_total(total: Decimal, eht_bands: list) -> Decimal:
    """ONE flat rate for the whole total — Ontario EHT is a rate-TABLE
    lookup, not a marginal bracket sum (§16: 'Select the rate from total
    Ontario remuneration before exemption'). `eht_bands` are the
    jurisdiction_state="ON" TaxSlab rows with rule_type="ON_EHT_BAND"
    (min_amount/max_amount/rate_pct, max_amount None meaning "and
    above") — genuinely statutory data with no hardcoded fallback; an
    unconfigured band table resolves to 0%, never a guess."""
    for band in eht_bands:
        lower = band.min_amount
        upper = band.max_amount
        if total > lower and (upper is None or total <= upper):
            return band.rate_pct
    return Decimal("0")


def _calculate_on_eht_period_amount(gross: Decimal, ytd_remuneration_before: Decimal, eht_bands: list, exemption: Decimal) -> Decimal:
    """Computed incrementally as annual_EHT(cumulative_after) −
    annual_EHT(cumulative_before) so the correct annual total accrues
    exactly once regardless of how many pay periods occur or when a
    rate-band/exemption-eligibility boundary is crossed mid-year — the
    per-period amounts telescope to the same total a single year-end
    calculation would produce, the same reasoning already used for
    CPP/CPP2/EI's own real YTD accumulator (see calculate() below)."""
    ytd_after = ytd_remuneration_before + gross

    def _annual_amount(total: Decimal) -> Decimal:
        eligible_exemption = exemption if total < _CA_ON_EHT_EXEMPTION_PHASEOUT_THRESHOLD else Decimal("0")
        rate = _on_eht_rate_for_total(total, eht_bands)
        taxable = max(Decimal("0"), total - eligible_exemption)
        return taxable * rate / Decimal("100")

    return _round2(_annual_amount(ytd_after) - _annual_amount(ytd_remuneration_before))


def _annual_notch_levy_amount(total: Decimal, exemption_threshold, notch_rate,
                               upper_threshold, flat_rate) -> Decimal:
    """Generic 'exemption / notch / flat-on-total' employer-levy shape —
    BC EHT (both the ordinary and charity/nonprofit variants), Manitoba
    HE Levy, and NL HAPSET all reduce to this same three-tier formula
    (ZP-TAX-CA-2026-001 §15), just with different thresholds/rates:

        total <= exemption_threshold                -> 0
        exemption_threshold < total <= upper_threshold -> notch_rate% * (total - exemption_threshold)
        total > upper_threshold                     -> flat_rate% * total  (on the WHOLE total, not the excess)

    NL HAPSET has no upper/flat tier (upper_threshold and flat_rate both
    None) — the notch tier simply continues forever above the exemption,
    matching its "2% on remuneration exceeding the threshold" rule (no
    second band). Genuinely statutory data with no hardcoded fallback:
    an unconfigured exemption_threshold or notch_rate (None) means this
    levy isn't configured for this jurisdiction/classification yet, and
    resolves to 0 rather than a guess."""
    if exemption_threshold is None or notch_rate is None:
        return Decimal("0")
    if total <= exemption_threshold:
        return Decimal("0")
    if upper_threshold is not None and flat_rate is not None and total > upper_threshold:
        return total * flat_rate / Decimal("100")
    return (total - exemption_threshold) * notch_rate / Decimal("100")


def _calculate_notch_levy_period_amount(gross: Decimal, ytd_remuneration_before: Decimal,
                                         exemption_threshold, notch_rate,
                                         upper_threshold, flat_rate) -> Decimal:
    """Same annual(after) − annual(before) telescoping as
    _calculate_on_eht_period_amount, for the notch-shaped levies —
    the per-period amount always sums to the correct annual total
    regardless of how many pay periods occur or when a threshold is
    crossed mid-year."""
    ytd_after = ytd_remuneration_before + gross
    return _round2(
        _annual_notch_levy_amount(ytd_after, exemption_threshold, notch_rate, upper_threshold, flat_rate)
        - _annual_notch_levy_amount(ytd_remuneration_before, exemption_threshold, notch_rate, upper_threshold, flat_rate)
    )


def _qc_hsf_rate_for_total(total: Decimal, employer_category, state_rate_map: dict):
    """Quebec Health Services Fund — a DIFFERENT shape from BC/MB/NL's
    notch levies: the RATE itself is a sliding linear function of the
    org's total Quebec payroll, then applied to the WHOLE total (never an
    excess-over-threshold), per ZP-TAX-CA-2026-001 §13:

        total <= threshold_low   -> low_rate% (category-specific flat)
        threshold_low < total <= threshold_high -> mid_base% + mid_slope% * (total / 1,000,000)
        total > threshold_high   -> high_rate% (category-specific flat)

    "Public sector" employers use one flat rate regardless of total.
    Genuinely statutory data with no hardcoded fallback: returns None
    (never a guessed rate) whenever a required row isn't configured,
    which the caller must treat as "this levy resolves to 0", never as
    0%."""
    category = (employer_category or "GENERAL").strip().upper()
    rates = state_rate_map or {}
    if category == "PUBLIC_SECTOR":
        rate_row = rates.get("qc_hsf_public_rate")
        return rate_row.employer_rate_pct if rate_row and rate_row.employer_rate_pct is not None else None

    prefix = "qc_hsf_primary" if category == "PRIMARY_MANUFACTURING" else "qc_hsf_general"
    threshold_low_row = rates.get("qc_hsf_threshold_low")
    threshold_high_row = rates.get("qc_hsf_threshold_high")
    low_row = rates.get(f"{prefix}_low_rate")
    threshold_low = threshold_low_row.flat_amount if threshold_low_row else None
    threshold_high = threshold_high_row.flat_amount if threshold_high_row else None
    if threshold_low is None or low_row is None or low_row.employer_rate_pct is None:
        return None
    if total <= threshold_low:
        return low_row.employer_rate_pct
    if threshold_high is not None and total > threshold_high:
        high_row = rates.get(f"{prefix}_high_rate")
        return high_row.employer_rate_pct if high_row and high_row.employer_rate_pct is not None else None
    base_row = rates.get(f"{prefix}_mid_base")
    slope_row = rates.get(f"{prefix}_mid_slope")
    if base_row is None or slope_row is None or base_row.employer_rate_pct is None or slope_row.employer_rate_pct is None:
        return None
    return base_row.employer_rate_pct + slope_row.employer_rate_pct * (total / Decimal("1000000"))


def _annual_qc_hsf_amount(total: Decimal, employer_category, state_rate_map: dict) -> Decimal:
    rate = _qc_hsf_rate_for_total(total, employer_category, state_rate_map)
    if rate is None:
        return Decimal("0")
    return total * rate / Decimal("100")


def _calculate_qc_hsf_period_amount(gross: Decimal, ytd_remuneration_before: Decimal,
                                     employer_category, state_rate_map: dict) -> Decimal:
    """Same annual(after) − annual(before) telescoping as the other
    org-banded levies — necessary here too, since the sliding rate
    itself changes as the org's cumulative Quebec payroll grows through
    the year, not just the taxable base."""
    ytd_after = ytd_remuneration_before + gross
    return _round2(
        _annual_qc_hsf_amount(ytd_after, employer_category, state_rate_map)
        - _annual_qc_hsf_amount(ytd_remuneration_before, employer_category, state_rate_map)
    )


def _calculate_qc_labour_standards(annual_gross: Decimal, state_rate_map: dict) -> Decimal:
    """Quebec labour standards contribution — an EMPLOYER contribution
    capped per-employee at the configured annual subject-remuneration
    cap ($103,000 for 2026 per §13), not org-banded like HSF. No
    hardcoded rate: the document explicitly withholds one ("rate
    maintained as sourced statutory parameter"), so an unconfigured
    qc_labour_standards_rate resolves to 0, never a guess. Disclosed
    simplification: computed as current-period-annualized (the same
    pre-YTD-accumulator convention every other component in this engine
    used before its own YTD wiring existed), not against a real
    per-employee YTD cap accumulator — a genuinely variable-pay employee
    crossing the $103,000 cap mid-year is not precisely handled, exactly
    like CPP/EI before ctx.ytd_* was wired for them."""
    cap_row = (state_rate_map or {}).get("qc_labour_standards_cap")
    rate_row = (state_rate_map or {}).get("qc_labour_standards_rate")
    if not cap_row or not cap_row.flat_amount or not rate_row or not rate_row.employer_rate_pct:
        return Decimal("0")
    subject_annual = min(annual_gross, cap_row.flat_amount)
    return _round2((subject_annual * rate_row.employer_rate_pct / Decimal("100")) / MONTHS_PER_YEAR)


_CA_CPP_MIN_AGE = 18
_CA_CPP_MAX_AGE = 70


def _is_age_gated_cpp_stopped(date_of_birth, pay_date) -> bool:
    """True when the employee is outside CPP/QPP's mandatory 18-70
    contribution window as of the pay date (§10's "Age 18"/"Age 70"
    controls). Either input missing (every employee/calculation today,
    since date_of_birth is a brand-new column and pay_date is a brand-
    new context field) returns False — never guess an age gate from
    incomplete data.

    DISCLOSED SIMPLIFICATION: this is a plain calendar-age comparison
    (age reaches N on the exact anniversary date), not CRA's more
    granular month-boundary administrative rule — the source document
    names these controls ("Begin/Cease CPP according to statutory month
    rule") without spelling out the exact day-of-month text, and 18/70
    are stable ages (not statutory rates/thresholds that vary by tax
    year), so this approximation is judged safer than inventing rule
    text the document doesn't actually provide."""
    if date_of_birth is None or pay_date is None:
        return False
    age = pay_date.year - date_of_birth.year - (
        (pay_date.month, pay_date.day) < (date_of_birth.month, date_of_birth.day)
    )
    return age < _CA_CPP_MIN_AGE or age >= _CA_CPP_MAX_AGE


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
    #
    # Age 18/70 mandatory window (§10) reuses this exact same freeze —
    # being outside the window has the identical "no obligation accrues,
    # YTD must not grow" consequence as an explicit CPT30 stop election;
    # see _is_age_gated_cpp_stopped for the dormancy gate and disclosed
    # simplification.
    age_gated_stopped = (
        "CA" in _CA_AGE_GATED_CPP_ENABLED_COUNTRIES
        and _is_age_gated_cpp_stopped(ctx.date_of_birth, ctx.pay_date)
    )
    if (ctx.cpp_qpp_election_status or "").strip().upper() == "STOPPED" or age_gated_stopped:
        social_security = Decimal("0")
        employer_social_security = Decimal("0")
        cpp2 = Decimal("0")
        employer_cpp2 = Decimal("0")
        if ytd_pensionable_earnings_after is not None:
            ytd_pensionable_earnings_after = ctx.ytd_pensionable_earnings
            ytd_basic_exemption_used_after = ctx.ytd_basic_exemption_used or Decimal("0")
        if ytd_cpp2_pensionable_earnings_after is not None:
            ytd_cpp2_pensionable_earnings_after = ctx.ytd_cpp2_pensionable_earnings

    # CPP/QPP first-layer BASE vs. FIRST-ADDITIONAL breakdown (AC-11) —
    # computed AFTER the CPT30/age-gating freeze above so a stopped
    # employee's breakdown is correctly $0/$0 too, never stale nonzero
    # values left over from before the freeze. Purely informational: see
    # _CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES's own comment in
    # shared.py — this PROPORTIONS the already-final social_security/
    # employer_social_security by the ratio of two separately-configured
    # rate rows, it never recomputes the deduction itself, so the split
    # can never disagree with (or replace) what was actually withheld.
    cpp_base_amount = Decimal("0")
    employer_cpp_base = Decimal("0")
    cpp_first_additional_amount = Decimal("0")
    employer_cpp_first_additional = Decimal("0")
    if "CA" in _CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES:
        split_rate_source = state_rate_map if is_quebec else rate_map
        base_row = split_rate_source.get("qpp_base" if is_quebec else "cpp_base")
        additional_row = split_rate_source.get("qpp_first_additional" if is_quebec else "cpp_first_additional")
        if base_row and additional_row and base_row.employee_rate_pct and additional_row.employee_rate_pct:
            total_employee_rate = base_row.employee_rate_pct + additional_row.employee_rate_pct
            if total_employee_rate:
                cpp_base_amount = _round2(social_security * base_row.employee_rate_pct / total_employee_rate)
                cpp_first_additional_amount = social_security - cpp_base_amount
        if base_row and additional_row and base_row.employer_rate_pct and additional_row.employer_rate_pct:
            total_employer_rate = base_row.employer_rate_pct + additional_row.employer_rate_pct
            if total_employer_rate:
                employer_cpp_base = _round2(employer_social_security * base_row.employer_rate_pct / total_employer_rate)
                employer_cpp_first_additional = employer_social_security - employer_cpp_base

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
        if "CA" in _CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES and rate_row and rate_row.employee_rate_pct:
            # §11: "Default employer EI is 1.4 × employee premium." A
            # valid reduced employer rate is a tenant-specific, effective-
            # dated authorization — EmployerTaxProfile, component_code
            # "EI_REDUCED", looked up at the FEDERAL/country level in
            # service.py (see its own comment there, since EI is a
            # federal program, not provincial) — and takes priority over
            # the 1.4x default; it must never replace the statutory
            # default globally, only for the specific org that actually
            # holds the authorization. Applies identically to QPIP too
            # (the doc's own Quebec employer rate is 1.820% on a 1.30%
            # employee rate — exactly 1.4x, same ratio as everywhere
            # else), so this is NOT gated on is_quebec.
            ei_reduced_profile = (ctx.employer_tax_profiles or {}).get("EI_REDUCED")
            effective_employer_rate = (
                ei_reduced_profile.employer_rate_pct
                if ei_reduced_profile and ei_reduced_profile.employer_rate_pct is not None
                else rate_row.employee_rate_pct * _CA_EI_EMPLOYER_MULTIPLIER
            )
            employer_esi = _round2(period_insurable * effective_employer_rate / Decimal("100"))
        else:
            # Legacy/dormant path — byte-for-byte unchanged until
            # _CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES opts CA in:
            # reads whatever employer_rate_pct is independently
            # configured on the SAME "ei"/"qpip" row, exactly as before.
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

    annual_federal_tax = _calculate_annual_tax_ca(
        annual_gross, ctx.slabs, rate_map, ctx.td1_claim_amount,
        period_cpp_contribution=social_security + cpp2, period_ei_contribution=employee_esi,
        lsvcc_investment_amount=ctx.lsvcc_investment_amount,
    )
    if is_quebec:
        # Quebec federal abatement — CRA federal tax is reduced (not
        # replaced) for a Quebec employee, since Quebec collects its own
        # provincial tax independently of the generic provincial path
        # (ZP-TAX-CA-2026-001 §6/§12). This constant WAS already prepared
        # in Phase 2 specifically for this branch.
        abatement_pct = resolve_jurisdiction_parameter(rate_map, "qc_fed_abatement", _CA_QUEBEC_FEDERAL_ABATEMENT_PCT, country="CA")
        annual_federal_tax = _round2(annual_federal_tax * (Decimal("100") - abatement_pct) / Decimal("100"))
    elif (ctx.work_state or "").strip().upper() == "XP" and "CA" in _CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES:
        # Beyond-province/outside-Canada surtax (§6/§7: "Federal tax
        # payable (T1): Apply Quebec abatement or beyond-province factor
        # only for the matching jurisdiction branch") — the SAME formula
        # step as the Quebec abatement above, just an INCREASE instead of
        # a reduction, for an employee whose work_state is literally "XP"
        # (§3's CA-XP code — no Canadian establishment at all, so no
        # province collects its own tax; this substitutes for that).
        # Gated on its own switch — see shared._CA_BEYOND_PROVINCE_
        # SURTAX_ENABLED_COUNTRIES for why, even though no automated POE
        # path can produce "XP" yet (that's Phase 9's scope).
        surtax_pct = resolve_jurisdiction_parameter(rate_map, "beyond_province_surtax", _CA_BEYOND_PROVINCE_SURTAX_PCT, country="CA")
        annual_federal_tax = _round2(annual_federal_tax * (Decimal("100") + surtax_pct) / Decimal("100"))
    federal_income_tax = _round2(annual_federal_tax / MONTHS_PER_YEAR)

    if is_quebec:
        annual_provincial_tax = _calculate_quebec_provincial_tax(
            annual_gross, ctx.state_slabs, state_rate_map, qc_tp1015_claim_amount=ctx.qc_tp1015_claim_amount,
        )
    else:
        annual_provincial_tax = _calculate_provincial_tax_ca(
            annual_gross, ctx.work_state, ctx.state_slabs, state_rate_map,
            provincial_td1_claim_amount=ctx.provincial_td1_claim_amount, rate_map=rate_map,
        )
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

    # Quebec Health Services Fund — banded on the ORG's aggregate Quebec
    # payroll, same org-level-accumulator contract as Ontario EHT below,
    # just a sliding-rate (not notch) formula (ZP-TAX-CA-2026-001 §13).
    employer_qc_hsf = Decimal("0")
    qc_hsf_ytd_remuneration_after = None
    if is_quebec and ctx.qc_hsf_ytd_remuneration_before is not None:
        employer_qc_hsf = _calculate_qc_hsf_period_amount(
            gross, ctx.qc_hsf_ytd_remuneration_before, ctx.qc_hsf_employer_category, state_rate_map,
        )
        qc_hsf_ytd_remuneration_after = ctx.qc_hsf_ytd_remuneration_before + gross

    # Quebec labour standards contribution — per-EMPLOYEE capped, not
    # org-banded, so it needs no accumulator wiring at all; resolves to 0
    # until qc_labour_standards_cap/_rate are both configured.
    employer_qc_labour_standards = (
        _calculate_qc_labour_standards(annual_gross, state_rate_map) if is_quebec else Decimal("0")
    )

    # Ontario EHT — only for an Ontario employee, and only once the
    # org-level accumulator is actually wired for this calculation
    # (ctx.on_eht_ytd_remuneration_before is None otherwise — see
    # service.py's _load_ca_org_levy_ytd, gated on
    # engine/countries/shared.py's
    # _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES). employer_eht stays 0 and
    # on_eht_ytd_remuneration_after stays None for every other employee/
    # org, so no existing calculation changes just because this exists.
    employer_eht = Decimal("0")
    on_eht_ytd_remuneration_after = None
    if (ctx.work_state or "").strip().upper() == "ON" and ctx.on_eht_ytd_remuneration_before is not None:
        eht_bands = [s for s in (ctx.state_slabs or []) if getattr(s, "rule_type", None) == "ON_EHT_BAND"]
        exemption_row = (state_rate_map or {}).get("on_eht_exemption")
        exemption = exemption_row.flat_amount if exemption_row and exemption_row.flat_amount else Decimal("0")
        employer_eht = _calculate_on_eht_period_amount(gross, ctx.on_eht_ytd_remuneration_before, eht_bands, exemption)
        on_eht_ytd_remuneration_after = ctx.on_eht_ytd_remuneration_before + gross

    # BC EHT — ordinary vs. registered-charity/nonprofit variant selected
    # by ctx.bc_eht_employer_classification (see this module's own
    # docstring for the disclosed "no UI yet" gap). Same dormancy gate as
    # Ontario: 0/None until the org-level accumulator is actually wired.
    employer_bc_eht = Decimal("0")
    bc_eht_ytd_remuneration_after = None
    if (ctx.work_state or "").strip().upper() == "BC" and ctx.bc_eht_ytd_remuneration_before is not None:
        is_bc_charity = (ctx.bc_eht_employer_classification or "").strip().upper() == "CHARITY_NONPROFIT"
        bc_prefix = "bc_eht_charity" if is_bc_charity else "bc_eht"
        bc_exemption_row = (state_rate_map or {}).get(f"{bc_prefix}_exemption_threshold")
        bc_upper_row = (state_rate_map or {}).get(f"{bc_prefix}_upper_threshold")
        bc_notch_row = (state_rate_map or {}).get(f"{bc_prefix}_notch_rate")
        bc_flat_row = (state_rate_map or {}).get(f"{bc_prefix}_flat_rate")
        employer_bc_eht = _calculate_notch_levy_period_amount(
            gross, ctx.bc_eht_ytd_remuneration_before,
            exemption_threshold=bc_exemption_row.flat_amount if bc_exemption_row else None,
            notch_rate=bc_notch_row.employer_rate_pct if bc_notch_row else None,
            upper_threshold=bc_upper_row.flat_amount if bc_upper_row else None,
            flat_rate=bc_flat_row.employer_rate_pct if bc_flat_row else None,
        )
        bc_eht_ytd_remuneration_after = ctx.bc_eht_ytd_remuneration_before + gross

    # Manitoba HE Levy — same notch shape, no ordinary/charity variant.
    employer_mb_he_levy = Decimal("0")
    mb_he_levy_ytd_remuneration_after = None
    if (ctx.work_state or "").strip().upper() == "MB" and ctx.mb_he_levy_ytd_remuneration_before is not None:
        mb_exemption_row = (state_rate_map or {}).get("mb_he_levy_exemption_threshold")
        mb_upper_row = (state_rate_map or {}).get("mb_he_levy_upper_threshold")
        mb_notch_row = (state_rate_map or {}).get("mb_he_levy_notch_rate")
        mb_flat_row = (state_rate_map or {}).get("mb_he_levy_flat_rate")
        employer_mb_he_levy = _calculate_notch_levy_period_amount(
            gross, ctx.mb_he_levy_ytd_remuneration_before,
            exemption_threshold=mb_exemption_row.flat_amount if mb_exemption_row else None,
            notch_rate=mb_notch_row.employer_rate_pct if mb_notch_row else None,
            upper_threshold=mb_upper_row.flat_amount if mb_upper_row else None,
            flat_rate=mb_flat_row.employer_rate_pct if mb_flat_row else None,
        )
        mb_he_levy_ytd_remuneration_after = ctx.mb_he_levy_ytd_remuneration_before + gross

    # NL HAPSET — same shape again, but with no upper/flat tier: 2% on
    # remuneration exceeding the exemption threshold, with no ceiling.
    employer_nl_hapset = Decimal("0")
    nl_hapset_ytd_remuneration_after = None
    if (ctx.work_state or "").strip().upper() == "NL" and ctx.nl_hapset_ytd_remuneration_before is not None:
        nl_exemption_row = (state_rate_map or {}).get("nl_hapset_exemption_threshold")
        nl_notch_row = (state_rate_map or {}).get("nl_hapset_flat_rate")
        employer_nl_hapset = _calculate_notch_levy_period_amount(
            gross, ctx.nl_hapset_ytd_remuneration_before,
            exemption_threshold=nl_exemption_row.flat_amount if nl_exemption_row else None,
            notch_rate=nl_notch_row.employer_rate_pct if nl_notch_row else None,
            upper_threshold=None, flat_rate=None,
        )
        nl_hapset_ytd_remuneration_after = ctx.nl_hapset_ytd_remuneration_before + gross

    return dict(
        social_security=social_security, employer_social_security=employer_social_security,
        cpp_base_amount=cpp_base_amount, employer_cpp_base=employer_cpp_base,
        cpp_first_additional_amount=cpp_first_additional_amount, employer_cpp_first_additional=employer_cpp_first_additional,
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
        employer_eht=employer_eht, on_eht_ytd_remuneration_after=on_eht_ytd_remuneration_after,
        employer_bc_eht=employer_bc_eht, bc_eht_ytd_remuneration_after=bc_eht_ytd_remuneration_after,
        employer_mb_he_levy=employer_mb_he_levy, mb_he_levy_ytd_remuneration_after=mb_he_levy_ytd_remuneration_after,
        employer_nl_hapset=employer_nl_hapset, nl_hapset_ytd_remuneration_after=nl_hapset_ytd_remuneration_after,
        employer_qc_hsf=employer_qc_hsf, qc_hsf_ytd_remuneration_after=qc_hsf_ytd_remuneration_after,
        employer_qc_labour_standards=employer_qc_labour_standards,
        tds=tds, annual_tax=annual_tax,
    )

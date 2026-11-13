"""Poland PIT advance (ZP-PL-ENG-001 §4, PL-007 / PL-008).

Cumulative withholding from this payment plus the year-to-date taxable income
(PIT_TAXABLE_INCOME accumulator) and the employee's statements — never a flat
percentage of gross.

  revenue        = PIT earning-class base (+ employer PPK when the signed
                   policy makes it employee income)
  PIT-0 relief   = an approved relief statement (no waiver in force) exempts
                   revenue against the signed shared annual limit; the relief
                   reduces PIT only (PL-008). A month that crosses the limit
                   BLOCKS: the split of social contributions and costs between
                   exempt and taxable revenue is not in the specification.
  income         = taxable revenue - employee social contributions (signed
                   rule EMPLOYEE_SOCIAL_ONLY) - deductible costs (standard or
                   commuter statement; one- or multiple-employment annual cap
                   from the PIT_COSTS_USED accumulator)
  taxable base   = income, rounded by the signed PIT rule, never below 0
  tax            = the base split across the scale boundary by cumulative YTD
                   (12% below, 32% above — rates and boundary from PL_PIT_BAND)
  reduction      = the PIT-2 monthly amount from an approved statement
                   (FULL / HALF / THIRD), never assumed
  advance        = max(tax - reduction, 0), rounded by the signed PIT rule

The published top-band base (10,800) nets the 3,600 reducing amount; it is
NOT used here because the reduction is applied monthly through PIT-2 — the
content test pins 120,000 x 12% - 3,600 == 10,800 so the two never drift.
A HIGHER_RATE_REQUEST statement BLOCKS: the specification names it but does
not define its calculation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import declarations as D
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, dec, money, upper


def _ytd(pack: PlPack, ytd: dict, key: str) -> Decimal:
    if ytd is None or ytd.get(key) is None:
        pack.block(E.keyed(E.YTD_MISSING, key), "the year-to-date accumulator is not supplied")
    return dec(ytd[key])


def _relief(pack: PlPack, declarations, pay_date: date):
    reliefs = [r for r in content.PIT0_RELIEFS if D.in_force(pack, declarations, r, pay_date) is not None]
    waiver = D.in_force(pack, declarations, "PIT0_WAIVER", pay_date)
    if not reliefs or waiver is not None:
        return None, waiver
    if len(reliefs) > 1:
        pack.block(E.keyed(E.DECLARATION_CONFLICT, "PIT0"),
                   "several PIT-0 reliefs in force: allocation of the shared limit is not in the specification")
    return reliefs[0], waiver


def compute(pack: PlPack, bases: dict, declarations, ytd: dict, employee_social: Decimal,
            ppk_employer_taxable: Decimal, pay_date: date) -> dict:
    rnd = pack.rounder("pl_rounding_pit")
    social_rule = pack.text("pl_pit_social_deduction_rule", ("EMPLOYEE_SOCIAL_ONLY",))
    if D.in_force(pack, declarations, "HIGHER_RATE_REQUEST", pay_date) is not None:
        pack.block(E.HIGHER_RATE_UNSIGNED, "the higher-rate request is named by the specification but not defined")

    revenue = bases["PIT"]["base"] + ppk_employer_taxable
    relief_code, waiver = _relief(pack, declarations, pay_date)
    exempt, relief_trace = ZERO, None
    if relief_code is not None:
        limit = pack.amount("pl_pit0_annual_limit")
        used = sum((_ytd(pack, ytd, r.replace("PIT0_", "PIT0_EXEMPT_")) for r in content.PIT0_RELIEFS), ZERO)
        remaining = max(limit - used, ZERO)
        if remaining >= revenue:
            exempt = revenue
        elif remaining > ZERO:
            pack.block(E.PIT0_PARTIAL_UNSIGNED,
                       "this month crosses the PIT-0 limit: the split rule is not in the specification")
        relief_trace = {"relief": relief_code, "limit": money(limit), "exemptUsedYtd": money(used),
                        "remainingBefore": money(remaining), "exemptThisPeriod": money(exempt)}
    taxable_revenue = revenue - exempt

    costs_kind, costs, social = None, ZERO, ZERO
    if taxable_revenue > ZERO:
        social = employee_social
        commuter = D.in_force(pack, declarations, "COSTS_COMMUTER", pay_date) is not None
        multiple = D.in_force(pack, declarations, "COSTS_MULTIPLE", pay_date) is not None
        kind = "commuter" if commuter else "standard"
        monthly = pack.amount(f"pl_costs_{kind}_monthly")
        cap = pack.amount(f"pl_costs_{kind}_multi_annual_cap" if multiple else f"pl_costs_{kind}_annual_cap")
        used_costs = _ytd(pack, ytd, "PIT_COSTS_USED")
        costs = min(monthly, max(cap - used_costs, ZERO))
        costs_kind = {"kind": kind.upper(), "multipleEmployments": multiple, "monthly": money(monthly),
                      "annualCap": money(cap), "usedYtd": money(used_costs), "applied": money(costs)}

    income = taxable_revenue - social - costs
    base = rnd(max(income, ZERO))
    (low_min, threshold, low_rate, _b0), (_m1, _x1, high_rate, _b1) = pack.pit_bands()
    ytd_taxable = _ytd(pack, ytd, "PIT_TAXABLE_INCOME")
    after = ytd_taxable + base
    portion_low = max(min(after, threshold) - min(ytd_taxable, threshold), ZERO)
    portion_high = base - portion_low
    tax = portion_low * low_rate / HUNDRED + portion_high * high_rate / HUNDRED

    reduction, pit2_trace = ZERO, None
    pit2 = D.in_force(pack, declarations, "PIT2", pay_date)
    if pit2 is not None:
        allocation = upper(D.value(pit2, "allocation"))
        if allocation not in content.PIT2_ALLOCATIONS:
            pack.block(E.PIT2_INVALID, "the PIT-2 statement must state FULL, HALF or THIRD")
        reduction = pack.amount(content.PIT2_ALLOCATIONS[allocation])
        pit2_trace = {"declaration": D.describe(pit2), "allocation": allocation, "monthlyReduction": money(reduction)}

    pre_rounding = tax - reduction
    advance = max(rnd(pre_rounding), ZERO)
    crossed = portion_low > ZERO and portion_high > ZERO or (ytd_taxable < threshold <= after and portion_high > 0)
    deltas = {"PIT_TAXABLE_INCOME": base, "PIT_ADVANCE": advance, "PIT_COSTS_USED": costs}
    if relief_code is not None:
        deltas[relief_code.replace("PIT0_", "PIT0_EXEMPT_")] = exempt
    return {
        "advance": advance, "base": base, "tax": tax, "reduction": reduction, "deltas": deltas,
        "trace": {
            "incomeClassification": {"pitBase": money(bases["PIT"]["base"]),
                                     "employerPpkAsIncome": money(ppk_employer_taxable),
                                     "revenue": money(revenue), "payDate": pay_date.isoformat()},
            "relief": relief_trace, "waiver": D.describe(waiver),
            "socialDeduction": {"rule": social_rule, "amount": money(social)},
            "employeeCosts": costs_kind,
            "income": money(income),
            "cumulativeTaxableBefore": money(ytd_taxable), "taxableBase": money(base),
            "cumulativeTaxableAfter": money(after),
            "rateTransition": {"threshold": money(threshold), "atLowRate": money(portion_low),
                               "lowRatePct": str(low_rate), "atHighRate": money(portion_high),
                               "highRatePct": str(high_rate), "crossedThisPeriod": bool(crossed)},
            "taxBeforeReduction": str(tax), "taxReducingAmount": pit2_trace,
            "finalAdvance": {"preRounding": str(pre_rounding), "withheld": money(advance)},
        },
    }

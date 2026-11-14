"""Belgium professional withholding tax (bedrijfsvoorheffing / précompte
professionnel) — Annex III, spec §5 stages 1-8 (BE-010 / BE-011 / BE-012;
Block A3). Pure; every figure from signed be_wht_* rows, bands and formulas.

Stage 1  applicability: be_wht_applicability_rule must be signed; a
         non-resident blocks (be_wht_nonresident_rule is read so a signed
         NOT_SUPPORTED is reported as such) — not certified in Block A3.
Stage 2  taxable basis: the regular / exceptional withholding bases minus the
         employee ONSS (after the social work bonus) attributable to each, in
         proportion to the part of the ONSS base each one carries
         (be_wht_taxable_basis_rule must be signed; allocation is gap G-26).
Stage 3  period strategy: be_wht_period_strategy must be signed (recorded).
Stage 4  regular scale: the signed be_wht_annex3_regular_scale band covering
         the regular taxable amount.
Stage 5  family / reduction layer from APPROVED declarations only
         (DEPENDANTS {"count": n} -> be_wht_family_reductions band).
Stage 6  exceptional remuneration through its OWN strategy (BE-011): holiday
         pay -> be_wht_holiday_pay_rule, arrears -> be_wht_arrears_rule, other
         exceptional pay -> be_wht_exceptional_rule band selected by the
         supplied annual reference remuneration. Never through the regular path.
Stage 7  2026 amendment formula, overtime formula (only with overtime pay) and
         the fiscal work bonus as its own line (BE-012).
Stage 8  rounding through be_rounding_withholding only.
The trace records the pack version and the formula interpreter version (BE-010).
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.belgium import declarations as _declarations
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium import formula as F
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, dec, field

_PERCENT = Decimal("100")
HOLIDAY_COMPONENTS = ("HOLIDAY_PAY_SIMPLE", "HOLIDAY_PAY_DOUBLE", "DEPARTURE_HOLIDAY_PAY")
ARREARS_COMPONENTS = ("ARREARS",)


def _allocate(onss_net: Decimal, onss_base: Decimal, part: Decimal) -> Decimal:
    if onss_base == ZERO or part == ZERO:
        return ZERO
    return onss_net * part / onss_base


def compute(pack: BePack, pay: dict, built: dict, decision: dict, approved: dict, onss: dict,
            exceptional_reference, pack_version) -> dict:
    rnd = pack.rounder("be_rounding_withholding")
    bases, detail = built["bases"], built["detail"]
    trace = {"interpreterVersion": F.INTERPRETER_VERSION, "packVersion": pack_version}

    # Stage 1
    trace["applicabilityRule"] = pack.text("be_wht_applicability_rule")
    if decision["worker"]["residency"] == "NON_RESIDENT":
        pack.text("be_wht_nonresident_rule")
        pack.block(E.NON_RESIDENT_UNSUPPORTED, "be_wht_nonresident_rule",
                   "non-resident withholding is not certified in this release")

    # Stage 2: employee ONSS attributable to each base (by ONSS-base share)
    trace["taxableBasisRule"] = pack.text("be_wht_taxable_basis_rule")
    onss_obligation = "ONSS_MANUAL_108" if onss["manual"] else "ONSS_EMPLOYEE"
    onss_components = set(detail[onss_obligation])
    onss_raw_base = bases[onss_obligation]

    def onss_share(obligation: str, codes=None) -> Decimal:
        part = sum((pay[c] for c in detail[obligation] if c in onss_components and (codes is None or c in codes)),
                   ZERO)
        return _allocate(onss["employeeNet"], onss_raw_base, part)

    regular_taxable = max(ZERO, rnd(bases["WITHHOLDING_REGULAR"] - onss_share("WITHHOLDING_REGULAR")))

    # Stage 3
    trace["periodStrategy"] = pack.text("be_wht_period_strategy")

    # Stage 4
    scale = pack.table("be_wht_annex3_regular_scale")
    row = pack.band_for("be_wht_annex3_regular_scale", scale, regular_taxable)
    tax = max(ZERO, pack.band_value("be_wht_annex3_regular_scale", row, regular_taxable))
    trace["scaleTax"] = str(tax)

    # Stage 5 (approved declarations only)
    family = ZERO
    dependants = approved.get("DEPENDANTS")
    if dependants is not None:
        count = Decimal(_declarations.whole_number(pack, dependants, "count"))
        rows = pack.table("be_wht_family_reductions")
        family_row = pack.band_for("be_wht_family_reductions", rows, count)
        family = min(tax, max(ZERO, pack.band_value("be_wht_family_reductions", family_row, count, tax=tax)))
        tax -= family
    trace["familyReduction"] = str(family)
    trace["declarationsUsed"] = sorted(approved)

    # Stage 7: amendment, overtime, fiscal work bonus (its own line)
    tax = max(ZERO, pack.formula("be_wht_annex3_amendment_2026", tax=tax, taxable=regular_taxable))
    overtime = pay.get("OVERTIME_PREMIUM", ZERO)
    if overtime != ZERO and "OVERTIME_PREMIUM" in detail["WITHHOLDING_REGULAR"]:
        tax = max(ZERO, pack.formula("be_wht_overtime_rule", tax=tax, overtime=overtime, taxable=regular_taxable))
    fiscal_bonus = pack.formula("be_wht_fiscal_work_bonus", social_bonus=onss["socialWorkBonus"],
                                taxable=regular_taxable, tax=tax)
    fiscal_bonus = rnd(min(tax, max(ZERO, fiscal_bonus)))
    regular = rnd(tax) - fiscal_bonus
    if regular < ZERO:
        regular = ZERO

    # Stage 6: exceptional remuneration, its own strategy
    exceptional_lines, exceptional_taxable = {}, ZERO
    exceptional_codes = detail["WITHHOLDING_EXCEPTIONAL"]
    groups = {"HOLIDAY_PAY": [c for c in exceptional_codes if c in HOLIDAY_COMPONENTS],
              "ARREARS": [c for c in exceptional_codes if c in ARREARS_COMPONENTS],
              "EXCEPTIONAL": [c for c in exceptional_codes
                              if c not in HOLIDAY_COMPONENTS and c not in ARREARS_COMPONENTS]}
    for group, codes in groups.items():
        gross = sum((pay[c] for c in codes), ZERO)
        if gross == ZERO:
            continue
        amount = max(ZERO, rnd(gross - onss_share("WITHHOLDING_EXCEPTIONAL", set(codes))))
        exceptional_taxable += amount
        if group == "HOLIDAY_PAY":
            value = pack.formula("be_wht_holiday_pay_rule", amount=amount)
        elif group == "ARREARS":
            value = pack.formula("be_wht_arrears_rule", amount=amount)
        else:
            if exceptional_reference is None:
                pack.block(E.FACT_MISSING, "exceptional_reference",
                           "exceptional remuneration needs the annual reference remuneration (spec §5 stage 6)")
            reference = dec(exceptional_reference)
            rows = pack.table("be_wht_exceptional_rule")
            band = pack.band_for("be_wht_exceptional_rule", rows, reference)
            text = field(band, "formula_expression")
            value = (pack.be_evaluate("be_wht_exceptional_rule", text,
                                   {"amount": amount, "reference": reference, "rate": dec(field(band, "rate_pct")),
                                    "flat": dec(field(band, "flat_amount"))})
                     if text else amount * dec(field(band, "rate_pct")) / _PERCENT + dec(field(band, "flat_amount")))
        exceptional_lines[group] = {"taxable": amount, "withholding": rnd(max(ZERO, value))}
    exceptional = sum((line["withholding"] for line in exceptional_lines.values()), ZERO)

    trace.update({"regularTaxable": str(regular_taxable), "fiscalWorkBonus": str(fiscal_bonus),
                  "regular": str(regular),
                  "exceptional": {g: {k: str(v) for k, v in line.items()} for g, line in exceptional_lines.items()}})
    return {"regularTaxable": regular_taxable, "regular": regular, "fiscalWorkBonus": fiscal_bonus,
            "familyReduction": family, "exceptionalTaxable": exceptional_taxable, "exceptional": exceptional,
            "exceptionalLines": exceptional_lines, "total": regular + exceptional, "trace": trace}

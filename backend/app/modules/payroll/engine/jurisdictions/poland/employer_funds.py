"""Poland employer funds (ZP-PL-ENG-001 §6, PL-011 / PL-012).

FP/FS, FGSP and FEP are independent employer liabilities and journal lines —
never one multiplied "employer burden" percentage (PL-011).
  * FEP: only with evidenced qualifying work in force (PL-012, decided in
    applicability); "uses pension-base logic including 30x limitation" (§6) —
    its base is capped by the remaining pension cap.
  * FP/FS and FGSP: whether their base is capped is NOT decided by the spec
    (pl_fund_cap_rule must be signed); FP/FS also needs the signed minimum-base
    test (pl_fp_fs_min_base_rule).
Rounded with the signed ZUS rule (the funds are settled with ZUS, §10).
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, money


def _capped_base(pack: PlPack, base: Decimal, pension_cap: dict, ytd_pension, cap: Decimal) -> Decimal:
    if pension_cap is not None:
        remaining = pension_cap["remainingBefore"]
    else:
        if ytd_pension is None:
            pack.block(E.keyed(E.YTD_MISSING, "ZUS_CAP_PENSION_BASE"),
                       "the pension-cap accumulator is needed for a capped fund base")
        remaining = max(cap - ytd_pension, ZERO)
    return min(base, remaining)


def compute(pack: PlPack, bases: dict, applicability: dict, zus: dict, ytd_pension, rnd) -> dict:
    obligations = applicability["obligations"]
    amounts = {"FP_FS": ZERO, "FGSP": ZERO, "FEP": ZERO}
    trace = {}
    cap = pack.amount("pl_zus_annual_cap")
    cap_rule = None
    if obligations["FP_FS"]["applies"] or obligations["FGSP"]["applies"]:
        cap_rule = pack.text("pl_fund_cap_rule", content.FUND_CAP_RULES)

    for obligation, key in (("FP_FS", "pl_fp_fs"), ("FGSP", "pl_fgsp")):
        if not obligations[obligation]["applies"]:
            trace[obligation] = {"applies": False, "reason": obligations[obligation]["reason"]}
            continue
        base = bases[obligation]["base"]
        if cap_rule == "CAPPED_WITH_PENSION_BASE":
            base = _capped_base(pack, base, zus["pension"], ytd_pension, cap)
        entry = {"applies": True, "capRule": cap_rule, "base": money(base)}
        if obligation == "FP_FS":
            min_rule = pack.text("pl_fp_fs_min_base_rule", content.FP_FS_MIN_BASE_RULES)
            entry["minBaseRule"] = min_rule
            if min_rule == "BASE_AT_LEAST_MIN_WAGE":
                floor = pack.amount("pl_min_wage_monthly")
                entry["minimumWage"] = money(floor)
                if base < floor:
                    entry.update(applies=False, reason="BASE_BELOW_MINIMUM_WAGE")
                    trace[obligation] = entry
                    continue
        rate = pack.pct(key, "employer")
        amounts[obligation] = rnd(base * rate / HUNDRED)
        entry.update(ratePct=str(rate), amount=money(amounts[obligation]))
        trace[obligation] = entry

    if obligations["FEP"]["applies"]:
        base = _capped_base(pack, bases["FEP"]["base"], zus["pension"], ytd_pension, cap)
        rate = pack.pct("pl_fep", "employer")
        amounts["FEP"] = rnd(base * rate / HUNDRED)
        trace["FEP"] = {"applies": True, "base": money(base), "capped": True, "ratePct": str(rate),
                        "amount": money(amounts["FEP"])}
    else:
        trace["FEP"] = {"applies": False, "reason": obligations["FEP"]["reason"]}

    return {"amounts": amounts, "total": sum(amounts.values(), ZERO), "trace": trace}

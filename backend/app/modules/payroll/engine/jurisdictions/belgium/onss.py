"""Belgium social security (ONSS) — employee and employer (ZP-BE-ENG-001 §6,
BE-012 / BE-015 / BE-016 / BE-019; Block A3). Pure.

* Employee contribution on its OWN base. The manual-worker base uplift
  (be_onss_manual_base_uplift, a percentage added to the base) applies ONLY when
  the resolver says the worker category is in the signed
  be_onss_manual_base_categories list (BE-016) — a white-collar worker is never
  on the uplifted base.
* The social work bonus is its own reduction line (BE-012), read from the
  signed be_red_social_work_bonus bands, never larger than the contribution.
* Employer contribution is resolved by employer category x worker code
  (band(key, EC=, WC=)); base, wage moderation, the special (workforce test)
  contribution, the occupational-pension special contribution and every fund
  are SEPARATE lines (BE-019) — never one "all-in" employer rate.
* Manual-worker holiday contributions go to obligation deltas only.
* The special social security contribution (BSSC) is never computed: an
  exception BE_BSSC_PENDING is always emitted (D7, G-06 / G-17).
Rounding only through pack.rounder() (D8).
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, dec, field

_PERCENT = Decimal("100")              # rate_pct values are percentages (structural unit)
SPECIAL_160_RULES = ("APPLIES", "DOES_NOT_APPLY")


def _share(amount: Decimal, pct: Decimal) -> Decimal:
    return amount * pct / _PERCENT


def compute(pack: BePack, bases: dict, decision: dict, pension_premium) -> dict:
    rnd = pack.rounder("be_rounding_onss")
    worker, employer = decision["worker"], decision["employer"]
    manual = worker["onssManualBase"] is True
    factor = None
    if manual:
        factor = (_PERCENT + pack.pct("be_onss_manual_base_uplift", "employee")) / _PERCENT

    # ── employee ──────────────────────────────────────────────────────────
    raw_employee_base = bases["ONSS_MANUAL_108"] if manual else bases["ONSS_EMPLOYEE"]
    employee_base = rnd(raw_employee_base * factor) if manual else raw_employee_base
    employee_rate = pack.pct("be_onss_employee_rate", "employee")
    contribution = rnd(_share(employee_base, employee_rate))
    bonus_rows = pack.table("be_red_social_work_bonus")
    bonus_row = pack.band_for("be_red_social_work_bonus", bonus_rows, employee_base)
    bonus = rnd(max(ZERO, pack.band_value("be_red_social_work_bonus", bonus_row, employee_base,
                                          contribution=contribution)))
    exceptions = []
    if bonus > contribution:
        exceptions.append({"code": E.EXC_REDUCTION_CAPPED, "detail": "social work bonus limited to the contribution"})
        bonus = contribution
    employee_net = contribution - bonus

    # ── employer (separate lines) ─────────────────────────────────────────
    ec, wc = employer["employerCategory"], worker["workerCode"]
    raw_employer_base = bases["ONSS_MANUAL_108"] if manual else bases["ONSS_EMPLOYER"]
    employer_base = rnd(raw_employer_base * factor) if manual else raw_employer_base
    base_rows = pack.band("be_onss_employer_base_rate", EC=ec, WC=wc)
    base_row = pack.band_for("be_onss_employer_base_rate", base_rows, employer_base)
    lines = {"BASE": rnd(pack.band_value("be_onss_employer_base_rate", base_row, employer_base))}
    lines["WAGE_MODERATION"] = rnd(_share(employer_base, pack.pct("be_onss_wage_moderation", "employer")))
    special_rule = pack.text("be_onss_special_160_threshold_rule", allowed=SPECIAL_160_RULES)
    lines["SPECIAL_160"] = (rnd(_share(employer_base, pack.pct("be_onss_special_160", "employer")))
                            if special_rule == "APPLIES" else ZERO)
    funds = {}
    for row in pack.band("be_onss_fund_contributions", EC=ec, WC=wc):
        name = str(field(row, "tax_formula") or "FUND").strip().upper()
        funds[name] = funds.get(name, ZERO) + rnd(pack.band_value("be_onss_fund_contributions", row,
                                                                  employer_base))
    premium = dec(pension_premium)
    pension = (rnd(_share(premium, pack.pct("be_onss_pension_special", "employer"))) if premium > ZERO else ZERO)
    employer_esi = sum(lines.values(), ZERO) + sum(funds.values(), ZERO)

    # ── manual-worker holiday contributions: obligation deltas only ───────
    obligations = {}
    if manual:
        holiday_round = pack.rounder("be_rounding_holiday")
        holiday_base = holiday_round(bases["HOLIDAY_BASE"] * factor)
        obligations["HOLIDAY_FUND_QUARTERLY"] = holiday_round(
            _share(holiday_base, pack.pct("be_hol_manual_quarterly_contribution", "employer")))

    exceptions.append({"code": E.BSSC_PENDING,
                       "detail": "special social security contribution not calculated: awaiting the specialist "
                                 "(D7, G-06 / G-17)"})
    trace = {"manualBase": manual, "employeeBase": str(employee_base), "employeeRatePct": str(employee_rate),
             "employeeContribution": str(contribution), "socialWorkBonus": str(bonus),
             "employerBase": str(employer_base), "employerCategory": ec, "workerCode": wc,
             "employerLines": {k: str(v) for k, v in lines.items()}, "funds": {k: str(v) for k, v in funds.items()},
             "pensionSpecial": str(pension), "special160Rule": special_rule,
             "reductions": "structural / target-group reductions are not applied (not in Block A3 scope)",
             "obligationDeltas": {k: str(v) for k, v in obligations.items()}}
    return {"employeeBase": employee_base, "employeeContribution": contribution, "socialWorkBonus": bonus,
            "employeeNet": employee_net, "employerBase": employer_base, "employerLines": lines, "funds": funds,
            "pensionSpecial": pension, "employerEsi": employer_esi, "obligationDeltas": obligations,
            "exceptions": exceptions, "manual": manual, "trace": trace}

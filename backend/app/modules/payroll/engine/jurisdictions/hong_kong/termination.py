"""Hong Kong termination: severance payment (SP) / long service payment (LSP)
with the abolition of the MPF offsetting arrangement (ZP-HK-ENG-001 §11,
HK-017, HK-018; Labour Department Concise Guide ch.11 and the Abolition of
MPF Offsetting Arrangement pages — SourceArtifacts ld_cg_11, ld_aoa).

Eligibility (continuous contract required for both):
  SP  ≥ 24 months — dismissal / fixed-term non-renewal by reason of
      redundancy, or lay-off;
  LSP ≥ 5 years   — dismissal (not summary, not redundancy), fixed-term
      expiry without renewal, death, resignation on ill health, resignation
      at 65 or above.
  Never both. An unreasonably refused written renewal offer defeats either.

Amount (monthly-rated): (monthly wages × 2/3, capped at 2/3 × HK$22,500 =
HK$15,000) × reckonable years. Daily/piece-rated: (18 days' wages, same
cap) × years. Service of an incomplete year is pro rata (days ÷ 365 —
disclosed day-count convention, G1 certification item).

Transition (1 May 2025): employment that commenced before and terminates on
or after the transition date is split. The pre-transition portion uses the
FROZEN last full month's wages immediately preceding the transition date (or
the employee's 12-month-average election) — never later wages (HK-017); the
post-transition portion uses the last full month's wages before termination
(or the 12-month average election). The two portions together are capped at
HK$390,000 and any excess is deducted from the POST-transition portion.

Offsets: accrued benefits from the employer's MANDATORY MPF contributions may
offset the pre-transition portion only; the employer's VOLUNTARY MPF
contributions and length-of-service gratuities may offset either portion.
Terminations before 1 May 2025 (the old full-offset regime) are out of scope
→ BLOCKED.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, add_months, add_years, canonical_hash, cents, dec, fraction_value, rate_value,
    row_ref, text_value,
)

SP_REASONS = ("REDUNDANCY", "FIXED_TERM_EXPIRY_REDUNDANCY", "LAY_OFF")
LSP_REASONS = ("DISMISSAL", "FIXED_TERM_EXPIRY", "DEATH", "RESIGNATION_ILL_HEALTH", "RESIGNATION_AGE_65")
NO_PAYMENT_REASONS = ("SUMMARY_DISMISSAL", "RESIGNATION")
TERMINATION_REASONS = SP_REASONS + LSP_REASONS + NO_PAYMENT_REASONS
OFFSET_TYPES = ("EMPLOYER_MANDATORY_MPF", "EMPLOYER_VOLUNTARY_MPF", "LENGTH_OF_SERVICE_GRATUITY")
# The pro-rata denominator is the pack row eo_days_per_year, never a literal.
_DAILY_BASES = ("DAILY", "PIECE")


def parameters(rate_map: dict) -> dict:
    values, refs = {}, {}
    values["sp_lsp_wage_fraction"], row = fraction_value(rate_map, "sp_lsp_wage_fraction")
    refs["sp_lsp_wage_fraction"] = row_ref(row)
    for key in ("sp_lsp_monthly_wage_cap", "sp_lsp_overall_cap", "sp_min_months",
                "lsp_min_years", "sp_lsp_daily_rated_days", "lsp_resignation_min_age",
                "eo_days_per_year"):
        values[key], row = rate_value(rate_map, key)
        refs[key] = row_ref(row)
    transition, row = text_value(rate_map, "mpf_offset_transition_date")
    values["transition_date"] = date.fromisoformat(transition)
    refs["mpf_offset_transition_date"] = row_ref(row)
    days = dec(values["eo_days_per_year"])
    if days <= ZERO:
        raise HongKongCalculationBlockedError("eo_days_per_year", "the pro-rata year must be a positive number of days")
    return {"values": values, "refs": refs}


def daily_rated_wages(daily_wage: Decimal, params: dict) -> Decimal:
    """The statutory "18 days' wages" base for a daily- / piece-rated employee,
    from the pack row sp_lsp_daily_rated_days (Concise Guide ch.11) — the
    operator supplies the daily rate, the days come from the rule pack."""
    days = dec(params["values"]["sp_lsp_daily_rated_days"])
    if days <= ZERO:
        raise HongKongCalculationBlockedError(
            "sp_lsp_daily_rated_days", "the daily-rated days' wages must be a positive number of days")
    return cents(dec(daily_wage) * days)


def _years(days: int, params: dict) -> Decimal:
    return Decimal(max(days, 0)) / dec(params["values"]["eo_days_per_year"])


def eligibility(reason: str, start: date, termination: date, cc_status: str, params: dict,
                age_at_termination: int = None, renewal_offer_refused: bool = False) -> dict:
    v = params["values"]
    if reason not in TERMINATION_REASONS:
        raise HongKongCalculationBlockedError("termination_reason", f"unknown termination reason {reason!r}")
    if reason in NO_PAYMENT_REASONS:
        return {"paymentType": "NONE", "eligible": False, "reason": f"{reason}: no SP/LSP entitlement"}
    if renewal_offer_refused:
        return {"paymentType": "NONE", "eligible": False,
                "reason": "a written renewal / re-engagement offer was unreasonably refused"}
    if cc_status != "CONTINUOUS":
        return {"paymentType": "NONE", "eligible": False, "reason": f"continuous contract status is {cc_status}"}
    if reason in SP_REASONS:
        months = int(v["sp_min_months"])
        ok = add_months(start, months) <= termination + timedelta(days=1)
        return {"paymentType": "SP" if ok else "NONE", "eligible": ok,
                "reason": f"severance payment needs ≥ {months} months under a continuous contract"}
    if reason == "RESIGNATION_AGE_65":
        min_age = int(v["lsp_resignation_min_age"])
        if age_at_termination is None or age_at_termination < min_age:
            return {"paymentType": "NONE", "eligible": False,
                    "reason": f"resignation qualifies for LSP only at age {min_age} or above"}
    years = int(v["lsp_min_years"])
    ok = add_years(start, years) <= termination + timedelta(days=1)
    return {"paymentType": "LSP" if ok else "NONE", "eligible": ok,
            "reason": f"long service payment needs ≥ {years} years under a continuous contract"}


def _portion_base(wage: Decimal, pay_basis: str, params: dict) -> tuple:
    v = params["values"]
    cap = cents(v["sp_lsp_monthly_wage_cap"] * v["sp_lsp_wage_fraction"])
    if pay_basis == "MONTHLY":
        raw = dec(wage) * v["sp_lsp_wage_fraction"]
    else:
        raw = dec(wage)          # 18 days' wages already, for daily / piece-rated
    return cents(min(raw, cap)), cents(raw), cap


def calculate(*, start: date, termination: date, reason: str, pay_basis: str, cc_status: str, params: dict,
              post_wage: Decimal, pre_wage: Decimal = None, pre_wage_basis: str = None,
              post_wage_basis: str = "LAST_FULL_MONTH", offsets: list = None,
              age_at_termination: int = None, renewal_offer_refused: bool = False,
              final_wages: Decimal = ZERO, annual_leave_pay: Decimal = ZERO, holiday_pay: Decimal = ZERO,
              active_tax_clearance_hold: bool = False,
              pre_daily_wage: Decimal = None, post_daily_wage: Decimal = None) -> dict:
    """HKTerminationResult payload. `post_wage` / `pre_wage`: monthly wages
    (MONTHLY) or 18 days' wages (DAILY/PIECE). A daily- or piece-rated employee
    may instead supply the daily rate through `pre_daily_wage` /
    `post_daily_wage`: the 18 days come from the pack row, not the caller."""
    v = params["values"]
    transition = v["transition_date"]
    if pay_basis not in ("MONTHLY", "DAILY", "PIECE"):
        raise HongKongCalculationBlockedError("pay_basis", f"SP/LSP needs the pay basis MONTHLY / DAILY / PIECE, got {pay_basis!r}")
    if pay_basis in _DAILY_BASES:
        if post_daily_wage is not None:
            post_wage = daily_rated_wages(post_daily_wage, params)
        if pre_daily_wage is not None:
            pre_wage = daily_rated_wages(pre_daily_wage, params)
    if termination < transition:
        raise HongKongCalculationBlockedError(
            "termination_date", f"termination before {transition} uses the pre-abolition full-offset regime — out of scope")
    elig = eligibility(reason, start, termination, cc_status, params, age_at_termination, renewal_offer_refused)
    out = {"paymentType": elig["paymentType"], "eligibility": elig, "rules": params["refs"],
           "dailyRatedDaysWages": str(v["sp_lsp_daily_rated_days"]),
           "reckonableDaysPerYear": str(v["eo_days_per_year"]),
           "startDate": start.isoformat(), "terminationDate": termination.isoformat(), "reason": reason,
           "payBasis": pay_basis}
    straddles = start < transition
    pre = post = ZERO
    portions = {}
    if elig["eligible"]:
        if straddles:
            if pre_wage is None:
                raise HongKongCalculationBlockedError(
                    "pre_transition_wage",
                    "employment straddles 1 May 2025: the frozen pre-transition wage (last full month before the "
                    "transition date, or the 12-month average election) must be recorded (HK-017)")
            pre_days = (transition - start).days
            base, raw, cap = _portion_base(pre_wage, pay_basis, params)
            pre = cents(base * _years(pre_days, params))
            portions["preTransition"] = {"serviceDays": pre_days, "years": str(_years(pre_days, params).quantize(Decimal("0.0001"))),
                                         "wage": str(cents(dec(pre_wage))), "wageBasis": pre_wage_basis or "LAST_FULL_MONTH",
                                         "base": str(base), "baseUncapped": str(raw), "baseCap": str(cap),
                                         "amount": str(pre), "frozen": True}
        post_start = transition if straddles else start
        post_days = (termination - post_start).days + 1
        base, raw, cap = _portion_base(post_wage, pay_basis, params)
        post = cents(base * _years(post_days, params))
        portions["postTransition"] = {"serviceDays": post_days, "years": str(_years(post_days, params).quantize(Decimal("0.0001"))),
                                      "wage": str(cents(dec(post_wage))), "wageBasis": post_wage_basis,
                                      "base": str(base), "baseUncapped": str(raw), "baseCap": str(cap),
                                      "amount": str(post)}
        overall = v["sp_lsp_overall_cap"]
        if pre + post > overall:
            # The sum may not exceed the cap; the excess comes off the POST
            # portion. A pre portion that alone exceeds the cap is itself
            # capped (the pre-abolition maximum), leaving nothing post.
            excess = pre + post - overall
            capped_pre = min(pre, overall)
            portions["overallCap"] = {"cap": str(overall), "excessDeductedFromPost": str(cents(min(excess, post))),
                                      "preTransitionCappedBy": str(cents(pre - capped_pre))}
            pre, post = capped_pre, overall - capped_pre
            if "preTransition" in portions:
                portions["preTransition"]["amountAfterCap"] = str(cents(pre))
            portions["postTransition"]["amountAfterCap"] = str(cents(post))
    gross = pre + post

    applied, pre_left, post_left = [], pre, post
    for o in offsets or []:
        kind, amount = o.get("type"), dec(o.get("amount"))
        if kind not in OFFSET_TYPES:
            raise HongKongCalculationBlockedError("offset_type", f"unknown offset type {kind!r}")
        if kind == "EMPLOYER_MANDATORY_MPF":
            used = min(amount, pre_left)
            pre_left -= used
            applied.append({"type": kind, "available": str(amount), "applied": str(cents(used)),
                            "appliedTo": {"preTransition": str(cents(used))},
                            "rule": "mandatory-MPF accrued benefits may offset the PRE-transition portion only"})
        else:
            to_post = min(amount, post_left)
            post_left -= to_post
            to_pre = min(amount - to_post, pre_left)
            pre_left -= to_pre
            applied.append({"type": kind, "available": str(amount), "applied": str(cents(to_post + to_pre)),
                            "appliedTo": {"postTransition": str(cents(to_post)), "preTransition": str(cents(to_pre))},
                            "rule": "voluntary-MPF benefits / length-of-service gratuity may offset either portion"})
    total_offsets = cents(gross - pre_left - post_left)
    net_statutory = cents(pre_left + post_left)
    total = cents(net_statutory + dec(final_wages) + dec(annual_leave_pay) + dec(holiday_pay))
    out.update({
        "straddlesTransition": straddles, "portions": portions,
        "grossEntitlement": str(cents(gross)), "offsets": applied, "totalOffsets": str(total_offsets),
        "netStatutoryPayment": str(net_statutory),
        "finalWages": str(cents(dec(final_wages))), "annualLeavePay": str(cents(dec(annual_leave_pay))),
        "holidayPay": str(cents(dec(holiday_pay))), "totalFinalPayment": str(total),
        "postTransitionSubsidyReference": (
            "Post-transition SP/LSP may be eligible for the Government subsidy scheme (www.op.labour.gov.hk) — "
            "operational reference only, never netted here" if post > ZERO else None),
        "paymentHold": ("An IR56G tax-clearance hold is ACTIVE: the final payment is held until release"
                        if active_tax_clearance_hold else None),
    })
    out["evidenceHash"] = canonical_hash(out)
    return out

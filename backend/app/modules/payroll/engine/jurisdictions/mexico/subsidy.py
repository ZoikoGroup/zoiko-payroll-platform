"""
engine/jurisdictions/mexico/subsidy.py
--------------------------------------
Employment subsidy (spec §5, MX-012/MX-013), from the decree content in force
on the pay date:

- eligible when the month's taxable income is at or below the monthly
  ceiling (`mx_subsidy_income_ceiling_monthly`); for a period shorter than a
  month the month-to-date taxable income committed so far is required;
- monthly amount = `mx_subsidy_rate_pct` × the monthly UMA in force;
- a period shorter than a month gets monthly ÷ `mx_subsidy_period_days_divisor`
  × days paid; if the month's applied subsidy would then exceed the monthly
  amount it BLOCKS (no capping rule is transcribed);
- the subsidy is offset against the period's ISR. When it exceeds the ISR the
  remainder follows the transcribed `mx_subsidy_remainder_rule` (Q4):
  NOT_PAYABLE → withholding 0; CASH_PAYABLE → BLOCK (paying it out needs a
  CFDI "otro pago" line, Phase 7); missing → BLOCK.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .errors import MXBlock

_ZERO = Decimal("0")
REMAINDER_RULES = ("NOT_PAYABLE", "CASH_PAYABLE")
# W3-1: how the month's payments are capped at the monthly amount (mx_subsidy_monthly_cap_rule).
MONTHLY_CAP_RULES = ("CAP_AT_MONTHLY_AMOUNT",)


def _mtd(month_to_date, field: str) -> Decimal:
    try:
        out = Decimal(str((month_to_date or {}).get(field, 0) or 0))
    except (InvalidOperation, ValueError):
        raise MXBlock("MX_MONTH_TO_DATE_INVALID", f"month-to-date {field} is not a number")
    if not out.is_finite() or out < 0:
        raise MXBlock("MX_MONTH_TO_DATE_INVALID", f"month-to-date {field} must be zero or more")
    return out


def subsidy(content, tariff: str, days_paid: Decimal, taxable: Decimal, month_to_date) -> dict:
    if tariff != "MONTHLY" and month_to_date is None:
        raise MXBlock("MX_MONTH_TO_DATE_MISSING",
                      "a period shorter than a month needs the month's committed taxable income to test the subsidy "
                      "ceiling (MX-013)")
    ceiling = content.amount("mx_subsidy_income_ceiling_monthly")
    month_income = _mtd(month_to_date, "taxable") + taxable
    if month_income > ceiling:
        return {"eligible": False, "amount": _ZERO, "month_income": month_income, "ceiling": ceiling}
    monthly = content.pct("mx_subsidy_rate_pct") * content.amount("mx_uma_monthly")
    if tariff == "MONTHLY":
        amount, divisor = monthly, None
    else:
        divisor = content.amount("mx_subsidy_period_days_divisor")
        if divisor <= 0:
            raise MXBlock("MX_CONTENT_INVALID", "mx_subsidy_period_days_divisor must be more than zero")
        amount = monthly / divisor * days_paid
    applied = _mtd(month_to_date, "subsidy_applied")
    capped = False
    if applied + amount > monthly:
        if not content.has("mx_subsidy_monthly_cap_rule"):
            raise MXBlock("MX_SUBSIDY_MONTHLY_CAP_RULE_MISSING",
                          "the month's subsidy would exceed the monthly amount and no capping rule is transcribed (S3)")
        rule = content.text("mx_subsidy_monthly_cap_rule").upper()
        if rule not in MONTHLY_CAP_RULES:
            raise MXBlock("MX_RULE_UNRECOGNISED", f"mx_subsidy_monthly_cap_rule {rule!r} is not one of {MONTHLY_CAP_RULES}")
        amount, capped = max(monthly - applied, _ZERO), True             # S3 Art. Segundo ¶4
    return {"eligible": True, "amount": amount, "monthly_amount": monthly, "month_income": month_income,
            "ceiling": ceiling, "divisor": divisor, "capped": capped}


def offset(content, isr: Decimal, subsidy_amount: Decimal) -> dict:
    """{withholding, subsidy_applied, remainder, rule}."""
    if subsidy_amount <= isr:
        return {"withholding": isr - subsidy_amount, "subsidy_applied": subsidy_amount, "remainder": _ZERO,
                "rule": None}
    if not content.has("mx_subsidy_remainder_rule"):
        raise MXBlock("MX_SUBSIDY_REMAINDER_RULE_MISSING",
                      "the subsidy exceeds the ISR and the remainder rule is not transcribed from the decree (S3, Q4)")
    rule = content.text("mx_subsidy_remainder_rule").upper()
    if rule not in REMAINDER_RULES:
        raise MXBlock("MX_RULE_UNRECOGNISED", f"mx_subsidy_remainder_rule {rule!r} is not one of {REMAINDER_RULES}")
    if rule == "CASH_PAYABLE":
        raise MXBlock("MX_SUBSIDY_CASH_REMAINDER_UNSUPPORTED",
                      "a cash-payable subsidy remainder needs a CFDI other-payment line (Phase 7)")
    return {"withholding": _ZERO, "subsidy_applied": isr, "remainder": subsidy_amount - isr, "rule": rule}

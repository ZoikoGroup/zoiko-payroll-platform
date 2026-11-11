"""Japan bonus withholding and the JPS bonus report (ZP-JP-ENG-001, S1/S8).

NTA bonus method: the prior month's pay after social insurance SELECTS the
row of the bonus-rate table (column by declaration class, PRIMARY by
dependant count); the row's rate is applied to the BONUS after its own social
insurance and employment insurance. The prior-month pay is never the taxed
amount.

The special calculation (no prior-month pay, or a bonus above the signed
multiple of it) uses the monthly table on a spread bonus and is not
certified: it BLOCKS. The multiple itself (jp_wht_bonus_special_multiple) is
empty until G1 signs it, so until then every bonus BLOCKS before the rate
table is read.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.japan import withholding as _wht

ZERO = Decimal("0")
HUNDRED = Decimal("100")
_RULE_BONUS = "JP_WHT_BONUS"
SPECIAL_KEY = "JP_WHT_BONUS_SPECIAL"


class BonusWithholdingResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _declaration(declaration_class, dependants, pack):
    declaration = str(declaration_class or "").strip().upper()
    if declaration not in ("PRIMARY", "SECONDARY"):
        _wht._block(pack, "jp_wht_declaration_class",
                    f"declaration class {declaration_class!r} is not PRIMARY or SECONDARY")
    try:
        dep = int(dependants)
    except (TypeError, ValueError):
        _wht._block(pack, "jp_wht_dependants", f"dependant count {dependants!r} is not a whole number")
    if dep < 0 or dep > 7:
        _wht._block(pack, "jp_wht_dependants", f"dependant count {dep} is outside the NTA table (0-7)")
    return declaration, dep


def _rate_rows(slabs, declaration, dependants, as_of):
    """PRIMARY rows are per dependant count; the SECONDARY column has one rate
    per prior-month band whatever the dependants, so its rows carry no
    tax_table_number."""
    rows = []
    for row in slabs or []:
        if str(_wht._field(row, "rule_type") or "") != _RULE_BONUS:
            continue
        if str(_wht._field(row, "tax_column") or "").upper() != declaration:
            continue
        if not _wht._in_force(row, as_of):
            continue
        number = _wht._field(row, "tax_table_number")
        number = "" if number is None else str(number).strip()
        if declaration == "PRIMARY" and number != str(dependants):
            continue
        if declaration == "SECONDARY" and number:
            continue
        rows.append(row)
    return rows


def bonus_withholding(bonus_after_si, prior_month_pay_after_si, declaration_class, dependants,
                      slabs, pack, as_of=None, rounding=None):
    """Return national withholding on a bonus (NTA bonus-rate method)."""
    declaration, dep = _declaration(declaration_class, dependants, pack)
    bonus = _wht._dec(bonus_after_si)
    if bonus < ZERO:
        _wht._block(pack, "jp_bonus_wht_base",
                    f"the bonus is negative ({bonus}) after its social insurance")
    if prior_month_pay_after_si is None:
        _wht._block(pack, "jp_prior_month_pay_after_si",
                    "the prior month's pay after social insurance is required for a bonus")
    prior = _wht._dec(prior_month_pay_after_si)
    if prior < ZERO:
        _wht._block(pack, "jp_prior_month_pay_after_si", f"prior-month pay {prior} is negative")

    multiple = _wht._scalar_amount(pack, "jp_wht_bonus_special_multiple")
    if prior == ZERO:
        _wht._block(pack, SPECIAL_KEY,
                    "no prior-month pay: the NTA special bonus calculation is not certified")
    if bonus > prior * multiple:
        _wht._block(pack, SPECIAL_KEY,
                    f"the bonus exceeds {multiple} times the prior-month pay: "
                    "the NTA special bonus calculation is not certified")

    rows = _rate_rows(slabs, declaration, dep, as_of)
    if not rows:
        _wht._block(pack, _RULE_BONUS,
                    f"no bonus-rate table row for {declaration}"
                    + (f" with {dep} dependants" if declaration == "PRIMARY" else ""))
    row = _wht._band(rows, prior, _RULE_BONUS, pack)
    rate = _wht._field(row, "rate_pct")
    if rate is None:
        _wht._block(pack, _RULE_BONUS, "the selected bonus-rate row has no rate")
    rounder = _wht._rounder(pack, rounding)
    events = []
    tax = _wht._round_value(bonus * _wht._dec(rate) / HUNDRED, rounder, "jp_wht_rounding",
                            "jp_bonus_wht", events)
    return BonusWithholdingResult(tax=tax, rate_pct=_wht._dec(rate), row=row,
                                  rounding_events=events)


def bonus_report_due(paid_on, pack):
    """The JPS bonus payment report is due within jp_bonus_report_days of
    payment (S8). Calendar days; no non-business-day rule is applied."""
    if paid_on is None:
        _wht._block(pack, "pay_date", "payment date is required")
    days = _wht._scalar_amount(pack, "jp_bonus_report_days")
    if days != days.to_integral_value() or days < ZERO:
        _wht._block(pack, "jp_bonus_report_days", f"{days} is not a whole number of days")
    return paid_on + timedelta(days=int(days))

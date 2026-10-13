"""
engine/jurisdictions/saudi_arabia/eos.py
----------------------------------------
Saudi Arabia end-of-service (EOS) award — ZP-SA-ENG-001 §13 (source S13).
Pure: the accrual shape and the resignation fractions are configured rows
(saudi_arabia_content.SA_SCALAR_CONTENT), never hardcoded.

  * Base formula: half a month's wage for each of the first five years and
    one month's wage for each later year, with pro-rata fractions of a year.
    The LAST WAGE is the default basis (the caller supplies it from the EOS
    earning classification); only commission / sales-percentage elements may
    be excluded, and only under a valid arrangement.
  * Resignation scaling (four bands): under 2 years nothing; 2 to 5 years
    one-third; over 5 and under 10 years two-thirds; 10 years or more the full
    award. The fractions are stored EXACTLY as text ("1/3") — flat_amount is
    Numeric(14,2) and would store one-third as 0.33.
  * Termination reason drives the award (the caller decides resignation vs
    employer termination); an exclusion requires a recorded reason upstream.

The award is a statutory liability object, NEVER a monthly deduction.
"""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

_Z = Decimal("0")
_HUNDRED = Decimal("100")
_CENT = Decimal("0.01")

RESIGNATION_BANDS = (
    # (key, band, lower bound inclusive?, test)
    ("sa_eos_resign_frac_under_2", "UNDER_2"),
    ("sa_eos_resign_frac_2_to_5", "TWO_TO_FIVE"),
    ("sa_eos_resign_frac_5_to_10", "FIVE_TO_TEN"),
    ("sa_eos_resign_frac_10_plus", "TEN_PLUS"),
)


def _amount(rates, key):
    row = rates.get(key)
    if row is None or getattr(row, "flat_amount", None) is None:
        return None
    try:
        return Decimal(str(row.flat_amount))
    except Exception:  # noqa: BLE001
        return None


def _fraction(rates, key):
    """An exact fraction from text_value ("1/3", "2/3", "0", "1"). A numeric
    flat_amount is accepted only when it is exactly 0 or 1 — anything else
    would be a rounded fraction and is rejected as not configured."""
    row = rates.get(key)
    if row is None:
        return None
    text = getattr(row, "text_value", None)
    if text not in (None, ""):
        try:
            value = Fraction(str(text).strip())
        except (ValueError, ZeroDivisionError):
            return None
        return value if Fraction(0) <= value <= Fraction(1) else None
    flat = getattr(row, "flat_amount", None)
    if flat is not None and Decimal(str(flat)) in (Decimal(0), Decimal(1)):
        return Fraction(int(Decimal(str(flat))))
    return None


def _years(years_of_service) -> Decimal:
    years = Decimal(str(years_of_service)) if years_of_service is not None else _Z
    if years < _Z:
        raise ValueError("years_of_service must not be negative")
    return years


def eos_award(monthly_wage: Decimal, years_of_service, rates, excluded: bool = False) -> dict:
    """Accrued award = last monthly wage × award months, where award months =
    first-rate × min(years, 5) + after-rate × max(years − 5, 0). Missing rows
    return NOT_EVALUATED (never a guessed rate). `excluded=True` (a recorded,
    evidenced statutory exclusion) yields a zero award."""
    if excluded:
        return {"status": "EXCLUDED", "award": _Z, "months": _Z,
                "reason": "a recorded statutory exclusion applies — no award is due"}
    first = _amount(rates, "sa_eos_first_5_years_months")
    after = _amount(rates, "sa_eos_after_5_years_months")
    if first is None or after is None:
        return {"status": "NOT_EVALUATED", "reason": "EOS accrual rows not configured"}
    years = _years(years_of_service)
    first_years = min(years, Decimal(5))
    beyond_years = max(years - Decimal(5), _Z)
    months = first * first_years + after * beyond_years
    award = (Decimal(str(monthly_wage)) * months).quantize(_CENT, rounding=ROUND_HALF_UP)
    return {"status": "OK", "months": months, "award": award,
            "firstYearsMonthsPerYear": str(first), "afterYearsMonthsPerYear": str(after),
            "yearsOfService": str(years), "firstYears": str(first_years), "beyondYears": str(beyond_years)}


def resignation_band(years_of_service) -> tuple:
    """Spec §13: <2 → UNDER_2; 2 ≤ y ≤ 5 → TWO_TO_FIVE; 5 < y < 10 →
    FIVE_TO_TEN; y ≥ 10 → TEN_PLUS."""
    years = _years(years_of_service)
    if years < Decimal(2):
        return RESIGNATION_BANDS[0]
    if years <= Decimal(5):
        return RESIGNATION_BANDS[1]
    if years < Decimal(10):
        return RESIGNATION_BANDS[2]
    return RESIGNATION_BANDS[3]


def resignation_fraction(years_of_service, rates) -> dict:
    """The fraction of the accrued award payable on resignation, by band. A
    missing or non-exact row returns NOT_EVALUATED."""
    key, band = resignation_band(years_of_service)
    frac = _fraction(rates, key)
    if frac is None:
        return {"status": "NOT_EVALUATED", "reason": f"{key} not configured as an exact fraction", "band": band}
    return {"status": "OK", "band": band, "key": key, "fraction": frac,
            "fractionText": f"{frac.numerator}/{frac.denominator}",
            "percent": (Decimal(frac.numerator) * _HUNDRED / Decimal(frac.denominator))}


def settlement_amount(eos_award_result: dict, is_resignation: bool, years_of_service, rates) -> dict:
    """The final-settlement EOS figure: the full award on employer termination;
    the award × the exact band fraction on resignation. An EXCLUDED /
    NOT_EVALUATED award keeps that status."""
    if eos_award_result.get("status") != "OK":
        return eos_award_result
    if not is_resignation:
        return {**eos_award_result, "fraction": Fraction(1), "fractionText": "1/1",
                "payable": eos_award_result["award"]}
    frac = resignation_fraction(years_of_service, rates)
    if frac["status"] != "OK":
        return frac
    award = eos_award_result["award"]
    payable = (award * Decimal(frac["fraction"].numerator) / Decimal(frac["fraction"].denominator)).quantize(
        _CENT, rounding=ROUND_HALF_UP)
    return {**eos_award_result, "fraction": frac["fraction"], "fractionText": frac["fractionText"],
            "band": frac["band"], "payable": payable}

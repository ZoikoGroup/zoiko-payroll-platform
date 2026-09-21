"""
modules/payroll/engine/countries/trinidad_and_tobago.py
--------------------------------------------------------------
Trinidad and Tobago (TT) — Phase 1 statutory build (ZP-TT-ENG-001).

Three independent statutory obligations (never folded into one number):
  1. PAYE — TT$90,000 annual personal allowance, then 25% up to
     TT$1,000,000 chargeable income, 30% above. Bands come from
     `ctx.slabs` via the generic `_calculate_annual_tax` bracket engine,
     annualized/de-annualized like Barbados/Jamaica/Dominican Republic.
     TD1-driven deductions/credits and irregular-pay handling (TT-006/
     TT-007) are deferred — Phase 1 models the ordinary allowance-only
     employee. Reused field: `tds`.
  2. Health Surcharge — a flat WEEKLY amount (TT$8.25 if monthly
     emoluments > TT$469.99 OR weekly emoluments > TT$109 for a
     Weekly-paid employee, else TT$4.80), not a percentage of pay.
     TT-008's age exemptions (under 16, or 60 and over) are wired via
     `ctx.date_of_birth`/`ctx.pay_date`, same calendar-age comparison
     and same "either input missing means no exemption" dormancy
     discipline as Canada's CPP age gate
     (`canada._is_age_gated_cpp_stopped`) — see `_is_hs_age_exempt`.
     TT-008's third exemption ("only source of income is pension") is
     still deferred: it needs a new per-employee fact this codebase
     does not carry today (not derivable from date_of_birth or any
     existing field), unlike the two age exemptions. Phase 1 assumes 4
     contribution weeks per Monthly pay period — the exact same
     simplifying assumption the spec's own §12 worked fixtures use
     ("Health Surcharge and NIS examples assume four liable/
     contribution weeks in the illustrated month"); a real
     Monday-count/contribution-week ledger (TT-009) is not built yet.
     Reused field (repurposed — a flat per-period fee, the closest
     existing generic slot, same shape India's flat Professional Tax
     already uses): `professional_tax`.
  3. NIS — a fixed 16-earnings-class table (TT-011/TT-013), not a
     percentage: each class has its own flat WEEKLY employee/employer
     dollar amount. Represented as `TaxSlab` rows with
     `rule_type="TT_NIS_CLASS"` (see shared.py's own docstring for the
     column-reuse convention: `flat_amount` = weekly employee amount,
     `adjustment_amount` = weekly employer amount — NOT
     `employer_rate_pct`, which is `Numeric(6,4)` and overflows on any
     class-XVI-sized employer figure ($339.00); `adjustment_amount` is
     `Numeric(10,2)`, plenty of room, and otherwise unused by this
     rule_type — both are plain dollar figures, not percentages).
     `min_amount`/
     `max_amount` hold the class's earnings-band boundaries; `filing_status`
     (repurposed, same convention AU's own coefficient-band family tag
     already establishes) is "MONTHLY" or "WEEKLY" — the spec's own
     table gives genuinely different boundary numbers for each, and a
     Monthly- vs Weekly-paid employee is classified against the matching
     set (see `_resolve_tt_nis_class`). A row with no filing_status is
     treated as MONTHLY, so the original seeded set keeps working
     unchanged. Reused fields: `social_security` / `employer_social_security`.
     Editable in Super Admin via its own dedicated tab
     (components/jurisdiction/trinidad/TTNisClassPanel.jsx) — the
     generic Tax Slabs table excludes these rows (slabsFilter in
     TTCompliancePage.jsx) since it would otherwise render the unused
     ratePct=0 as a misleading "0% rate".

Validated against ZP-TT-ENG-001 §12 fixtures F1 (TT$10,000/mo, Class XII)
and F2 (TT$15,000/mo, Class XVI) — see tests/test_trinidad_and_tobago.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
    _calculate_annual_tax,
)

_TT_ANNUAL_ALLOWANCE = Decimal("90000")

_TT_HS_HIGH_RATE_WEEKLY = Decimal("8.25")
_TT_HS_LOW_RATE_WEEKLY = Decimal("4.80")
_TT_HS_MONTHLY_THRESHOLD = Decimal("469.99")
_TT_HS_WEEKLY_THRESHOLD = Decimal("109")
_TT_HS_WEEKS_PER_MONTH = Decimal("4")  # see module docstring — matches the spec's own fixture assumption


def _resolve_tt_nis_class(slabs, earnings: Decimal, band_variant: str):
    """`band_variant` is "MONTHLY" or "WEEKLY" — TaxSlab.filing_status
    (repurposed for TT_NIS_CLASS rows, same "reuse an existing generic
    column per rule_type" convention AU's own SCALE_1.."SCALE_6"
    coefficient-band family tag already establishes) tags which of the
    two band sets a row belongs to, since the class boundaries are
    genuinely different numbers depending on whether the employee's
    earnings are being measured monthly or weekly. A row with no
    filing_status at all is treated as MONTHLY (the original seeded set,
    before weekly bands existed) so existing canonical data keeps working
    unchanged."""
    class_rows = [
        s for s in slabs
        if getattr(s, "rule_type", None) == "TT_NIS_CLASS"
        and (getattr(s, "filing_status", None) or "MONTHLY") == band_variant
    ]
    if not class_rows:
        return None
    for row in sorted(class_rows, key=lambda s: s.min_amount):
        upper = row.max_amount if row.max_amount is not None else earnings
        if row.min_amount <= earnings <= upper or (row.max_amount is None and earnings >= row.min_amount):
            return row
    # Below the lowest seeded class — fail safe to the lowest class rather
    # than silently returning $0 NIS.
    return sorted(class_rows, key=lambda s: s.min_amount)[0]


def _is_hs_age_exempt(date_of_birth, pay_date) -> bool:
    """True when the employee is under 16 or 60-or-over as of the pay
    date (TT-008's age exemptions). Either input missing returns False —
    never guess an age exemption from incomplete data, same dormancy
    discipline as Canada's CPP age gate (_is_age_gated_cpp_stopped)."""
    if date_of_birth is None or pay_date is None:
        return False
    age = pay_date.year - date_of_birth.year - (
        (pay_date.month, pay_date.day) < (date_of_birth.month, date_of_birth.day)
    )
    return age < 16 or age >= 60


def calculate(ctx: PayrollContext) -> dict:
    """Trinidad and Tobago: PAYE (annualized bracket lookup) + Health
    Surcharge (flat weekly fee) + NIS (fixed 16-class weekly table)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    allowance_annual = resolve_jurisdiction_parameter(rate_map, "tt_personal_allowance", _TT_ANNUAL_ALLOWANCE, country="TT")
    period_allowance = allowance_annual / periods_per_year
    taxable_annualized = max(period_gross - period_allowance, Decimal("0")) * periods_per_year
    tds = _round2(_calculate_annual_tax(taxable_annualized, ctx.slabs) / periods_per_year)

    is_weekly = (ctx.pay_frequency or "Monthly") == "Weekly"
    high_rate = resolve_jurisdiction_parameter(rate_map, "tt_health_surcharge_high", _TT_HS_HIGH_RATE_WEEKLY, country="TT")
    low_rate = resolve_jurisdiction_parameter(rate_map, "tt_health_surcharge_low", _TT_HS_LOW_RATE_WEEKLY, country="TT")
    monthly_threshold = resolve_jurisdiction_parameter(rate_map, "tt_hs_monthly_threshold", _TT_HS_MONTHLY_THRESHOLD, country="TT")
    weekly_threshold = resolve_jurisdiction_parameter(rate_map, "tt_hs_weekly_threshold", _TT_HS_WEEKLY_THRESHOLD, country="TT")
    weeks_in_period = Decimal("1") if is_weekly else _TT_HS_WEEKS_PER_MONTH
    # Spec: "monthly emoluments > TT$469.99 OR weekly emoluments > TT$109"
    # — a Weekly-paid employee is tested against the weekly threshold, not
    # the monthly one.
    hs_threshold = weekly_threshold if is_weekly else monthly_threshold
    weekly_rate = high_rate if period_gross > hs_threshold else low_rate
    hs_age_exempt = _is_hs_age_exempt(ctx.date_of_birth, ctx.pay_date)
    professional_tax = Decimal("0") if hs_age_exempt else _round2(weekly_rate * weeks_in_period)  # Health Surcharge — see module docstring

    nis_class = _resolve_tt_nis_class(ctx.slabs, period_gross, "WEEKLY" if is_weekly else "MONTHLY")
    if nis_class is not None:
        social_security = _round2((nis_class.flat_amount or Decimal("0")) * weeks_in_period)
        employer_social_security = _round2((nis_class.adjustment_amount or Decimal("0")) * weeks_in_period)
    else:
        social_security = Decimal("0")
        employer_social_security = Decimal("0")

    return dict(
        tds=tds,
        professional_tax=professional_tax,
        social_security=social_security,
        employer_social_security=employer_social_security,
    )

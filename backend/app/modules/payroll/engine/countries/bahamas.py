"""
modules/payroll/engine/countries/bahamas.py
------------------------------------------------
The Bahamas (BS) — Phase 1 statutory build (ZP-BS-ENG-001).

No domestic personal income tax (BS-005) — `tds` is always Decimal("0"),
the same value every other country returns when no tax is due, never a
fabricated 0% tax band. The Super Admin Compliance page / payslip copy
for BS must label this "No Bahamian personal income-tax withholding
applies."

NIB — employee 4.65% / employer 6.65% of insurable earnings, capped at
the current weekly (B$830 from 1 Jul 2026, B$810 before) or monthly
(B$3,597) ceiling per BS-010/BS-011/BS-012. The July 2026 B$810→B$830
weekly boundary is now wired via `ctx.pay_date` — a Weekly-paid contribution
week before 1 Jul 2026 uses the certified prior B$810 ceiling; on/after
that date uses B$830 (BS-010: "Do not decide the ceiling solely from
payroll payment date when a pay period spans the change" — Phase 1 uses
the payroll's own pay_date, matching every other date-gated country
content boundary in this codebase, e.g. TT's 2026/2027 NIS pack
boundary). `ctx.pay_date is None` falls back to the current B$830 value,
unchanged from before this boundary was wired. The MONTHLY ceiling has
no equivalent date boundary here: the spec gives only the current
B$3,597 working value, no distinct pre-2026 monthly figure, so it is
not fabricated — monthly stays a single undated value.

Gratuity/tip NIB treatment (BS-013) and age/retirement-benefit
contribution categories (BS-009) are deliberately NOT modelled here —
each requires either signed content this build doesn't have yet
(gratuity's exact contribution split/rate), or a real per-employee
category fact this codebase's context doesn't carry for BS today
(retirement-benefit-received status). This module always applies the
ordinary employee category rate.

Validated against ZP-BS-ENG-001 §12 fixtures F1 (B$700/wk) and F2
(B$1,000/wk, above ceiling) — see tests/test_bahamas.py.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import resolve_jurisdiction_parameter

_BS_NIB_EMPLOYEE_RATE = Decimal("0.0465")
_BS_NIB_EMPLOYER_RATE = Decimal("0.0665")
_BS_NIB_WEEKLY_CEILING = Decimal("830")
_BS_NIB_WEEKLY_CEILING_PRE_2026_07 = Decimal("810")  # weekly ceiling before 1 Jul 2026 — see module docstring
_BS_NIB_MONTHLY_CEILING = Decimal("3597")
_BS_CEILING_BOUNDARY = date(2026, 7, 1)


def _resolve_nib_ceiling(rate_map: dict, pay_frequency: str | None, pay_date) -> Decimal:
    if (pay_frequency or "Monthly") == "Weekly":
        if pay_date is not None and pay_date < _BS_CEILING_BOUNDARY:
            return resolve_jurisdiction_parameter(
                rate_map, "bs_nib_ceiling_weekly_pre_2026_07", _BS_NIB_WEEKLY_CEILING_PRE_2026_07, country="BS",
            )
        return resolve_jurisdiction_parameter(rate_map, "bs_nib_ceiling_weekly", _BS_NIB_WEEKLY_CEILING, country="BS")
    return resolve_jurisdiction_parameter(rate_map, "bs_nib_ceiling_monthly", _BS_NIB_MONTHLY_CEILING, country="BS")


def calculate(ctx: PayrollContext) -> dict:
    """Bahamas: no income tax + NIB (capped, weekly ceiling date-gated at
    1 Jul 2026)."""
    rate_map = ctx.rate_map
    period_gross = ctx.gross

    nib_ceiling = _resolve_nib_ceiling(rate_map, ctx.pay_frequency, ctx.pay_date)
    nib_base = min(period_gross, nib_ceiling)
    employee_rate = resolve_jurisdiction_parameter(rate_map, "bs_nib", _BS_NIB_EMPLOYEE_RATE, side="employee", country="BS")
    employer_rate = resolve_jurisdiction_parameter(rate_map, "bs_nib", _BS_NIB_EMPLOYER_RATE, side="employer", country="BS")
    social_security = _round2(nib_base * employee_rate)
    employer_social_security = _round2(nib_base * employer_rate)

    return dict(
        tds=Decimal("0"),
        social_security=social_security,
        employer_social_security=employer_social_security,
    )

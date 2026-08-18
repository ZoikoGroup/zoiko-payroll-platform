"""
modules/payroll/engine/countries/generic.py
-----------------------------------------------
Fallback calculator for a country with no dedicated compliance module —
progressive tax only, no country-specific contributions. Moved verbatim
out of engine/standard.py's _calc_generic.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax


def calculate(ctx: PayrollContext) -> dict:
    """Fallback: progressive tax only (no country-specific contributions)."""
    annual_gross = ctx.gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)
    return dict(tds=tds, annual_tax=annual_tax)

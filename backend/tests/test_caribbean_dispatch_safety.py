"""
tests/test_caribbean_dispatch_safety.py
-------------------------------------------
Guards the "no Coming Soon jurisdiction ever reaches a real calculator or
falls back to another country's statutory rules" invariant (Rule 9/29 of
the approved Caribbean implementation plan, 2026-09-21).
"""

from decimal import Decimal

from app.core.caribbean_regions import (
    ACTIVE_CARIBBEAN_CODES,
    COMING_SOON_CARIBBEAN_CODES,
    CARIBBEAN_JURISDICTIONS,
)
from app.core.jurisdiction import get_jurisdiction_code
from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC, _calc_generic


def test_every_active_caribbean_code_has_a_real_dispatch_entry():
    for code in ACTIVE_CARIBBEAN_CODES:
        assert code in _COUNTRY_CALC, f"{code} is ACTIVE but has no _COUNTRY_CALC entry"
        assert _COUNTRY_CALC[code] is not _calc_generic


def test_no_coming_soon_caribbean_code_has_a_dispatch_entry():
    for code in COMING_SOON_CARIBBEAN_CODES:
        assert code not in _COUNTRY_CALC, f"{code} is COMING_SOON but has a real _COUNTRY_CALC entry"


def test_every_active_caribbean_code_resolves_via_core_jurisdiction():
    """core/jurisdiction.py is what registration actually gates on — an
    ACTIVE code here must also be real there, or a registered org could
    exist for a country the engine can't compute."""
    for code in ACTIVE_CARIBBEAN_CODES:
        name = CARIBBEAN_JURISDICTIONS[code][0]
        assert get_jurisdiction_code(name) == code
        assert get_jurisdiction_code(code) == code


def test_coming_soon_caribbean_code_falls_through_to_generic_if_ever_reached():
    """This is the safety net, not the primary control — registration
    should block a Coming Soon jurisdiction long before payroll
    calculation runs (see test_registration_jurisdiction_gate.py). This
    test only proves that IF one somehow reached calculation, it would
    get the honest no-country-specific-contributions fallback rather
    than silently borrowing another Caribbean country's real rules."""
    sample_code = next(iter(COMING_SOON_CARIBBEAN_CODES))
    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country=sample_code, rate_map={}, slabs=[])
    calc_fn = _COUNTRY_CALC.get(ctx.country.upper(), _calc_generic)
    assert calc_fn is _calc_generic

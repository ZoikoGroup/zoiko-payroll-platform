"""New Zealand (ZP-NZ-ENG-001) Phase 0: identity, dormancy and fail-closed dispatch."""
import pytest


# ── jurisdiction identity ──────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["NZ", "nz", "New Zealand", " new zealand ", "Aotearoa", "NZL"])
def test_new_zealand_resolves_to_nz(value):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    assert get_jurisdiction_code(value) == "NZ"
    assert "New Zealand" in REGISTRATION_COUNTRIES                    # registrable since the gate removal


@pytest.mark.parametrize("value", ["New Zealand", "new zealand", "NZ", "Aotearoa"])
def test_payroll_normaliser_never_truncates_to_nebraska(value):
    from app.modules.payroll.service import _normalize_country

    assert _normalize_country(value) == "NZ"


def test_schema_holds_only_the_public_nzbn():
    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers

    schema = JURISDICTION_TAX_SCHEMAS["NZ"]
    assert schema["currency"] == "NZD"
    assert [f["key"] for f in schema["fields"]] == ["nzbn"]          # IRD number lives in the vault
    assert validate_tax_identifiers("NZ", {"nzbn": "9429041234567"}) == ({"nzbn": "9429041234567"}, [])
    assert validate_tax_identifiers("NZ", {"nzbn": "94290412"})[1]


@pytest.mark.parametrize("value", ["49091850", "49-091-850", "35901981", "49098576", "136410132", "136 410 132"])
def test_ird_number_check_digit_accepts_valid_numbers(value):
    from app.core.jurisdiction import nz_ird_number_valid

    assert nz_ird_number_valid(value) is True


@pytest.mark.parametrize("value", ["136410133", "9125568", "150000000", "1234567890", "4909185A", "", None])
def test_ird_number_check_digit_rejects_invalid_numbers(value):
    from app.core.jurisdiction import nz_ird_number_valid

    assert nz_ird_number_valid(value) is False


# ── dormancy ───────────────────────────────────────────────────────────────
# ── fail-closed calculation dispatch ───────────────────────────────────────
def test_nz_never_falls_through_to_the_generic_calculator():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import new_zealand

    assert standard._COUNTRY_CALC["NZ"] is new_zealand.calculate
    assert standard._COUNTRY_CALC["NZ"] is not standard._calc_generic


def test_nz_calculation_is_blocked():
    from decimal import Decimal

    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.new_zealand import NZCalculationBlockedError, calculate
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    # Phase 3: the engine exists but an input with no payday, pack or profiles
    # is refused with a named reason - never calculated, never a generic result.
    with pytest.raises(NZCalculationBlockedError) as raised:
        calculate(PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country="NZ"))
    assert isinstance(raised.value, MissingComplianceConfigurationError)
    assert raised.value.key == "NZ_PAY_DATE_MISSING"


def test_nz_registered_with_shared_gates():
    from app.modules.payroll.engine.countries.shared import _VALIDATION_ENABLED_COUNTRIES
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    assert "NZ" in _VALIDATION_ENABLED_COUNTRIES
    assert "NZ" not in _REGISTRY_ROW_REQUIRED_COUNTRIES                # gate removal 2026-11-25


@pytest.mark.parametrize("mode", ["simple", "standard", "enterprise"])
def test_every_calculation_mode_is_blocked(mode):
    from decimal import Decimal

    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.new_zealand import NZCalculationBlockedError
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(NZCalculationBlockedError) as raised:
        calculate_payroll(PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country="NZ"), mode)
    expected = "NZ_SIMPLE_MODE_UNSUPPORTED" if mode == "simple" else "NZ_PAY_DATE_MISSING"
    assert raised.value.key == expected

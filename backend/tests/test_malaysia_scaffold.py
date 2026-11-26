"""Malaysia (ZP-MY-ENG-001) Phase 0: identity, identifiers, dormancy and fail-closed dispatch."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

# Synthetic NRIC vectors (YYMMDD + place code + 4 digits; MyKad has no check
# digit). Mirrored in frontend/scripts/my-compliance-ui-validation.mjs.
VALID_NRIC = ["900101145678",           # 1 Jan 1990
              "000229105555",           # 29 Feb 2000 (leap year)
              "880531-08-1234", "990101 01 0001"]
INVALID_NRIC = ["900101005678",         # place-of-birth code 00
                "901301145678",         # month 13
                "900230145678",         # 30 Feb
                "010229145678",         # 29 Feb 1901 / 2001 - neither is a leap year
                "90010114567", "9001011456789", "90010114567A", "", None]
BIC = "MBBEMYKL"
ACCOUNT = "514123456789"


# ── jurisdiction identity ──────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["MY", "Malaysia", " MALAYSIA ", "malaysia", "MYS", "Persekutuan Malaysia",
                                   "Federation of Malaysia"])
def test_malaysia_resolves_to_my(value):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    assert get_jurisdiction_code(value) == "MY"
    assert "Malaysia" in REGISTRATION_COUNTRIES                         # registrable since the gate removal


@pytest.mark.parametrize("value", ["Malaysia", "malaysia", "MYS", "MY"])
def test_payroll_normaliser_never_truncates_malaysia_to_morocco(value):
    from app.modules.payroll.service import _normalize_country

    assert _normalize_country(value) == "MY"                            # not "MA"


def test_bare_my_is_not_a_free_text_alias():
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE, COUNTRY_NAME_TO_CODE

    assert "my" not in COUNTRY_NAME_TO_CODE and "my" not in ALL_COUNTRY_NAME_TO_CODE


def test_country_name_round_trip():
    from app.core.jurisdiction import CODE_TO_COUNTRY_NAME

    assert CODE_TO_COUNTRY_NAME["MY"] == "Malaysia"


def test_schema_holds_employer_references_only():
    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers

    schema = JURISDICTION_TAX_SCHEMAS["MY"]
    assert schema["currency"] == "MYR"
    fields = {f["key"]: f for f in schema["fields"]}
    assert list(fields) == ["hasil_employer_no", "epf_employer_no", "perkeso_employer_code", "hrd_registration_no"]
    assert fields["hasil_employer_no"]["primary"] is True
    assert not any(k in fields for k in ("nric", "passport_number", "tin", "epf_member_no", "socso_no"))
    examples = {k: f["example"] for k, f in fields.items()}
    assert validate_tax_identifiers("MY", examples) == (examples, [])
    assert validate_tax_identifiers("MY", {"hasil_employer_no": "E!"})[1]


# ── identifier formats ─────────────────────────────────────────────────────
@pytest.mark.parametrize("value", VALID_NRIC)
def test_nric_accepts_valid_numbers(value):
    from app.modules.payroll.employee_validation import my_nric_is_valid

    assert my_nric_is_valid(value) is True


@pytest.mark.parametrize("value", INVALID_NRIC)
def test_nric_rejects_invalid_numbers(value):
    from app.modules.payroll.employee_validation import my_nric_is_valid

    assert my_nric_is_valid(value) is False


def test_nric_date_is_ambiguous_across_centuries_and_never_guessed():
    from datetime import date

    from app.modules.payroll.employee_validation import my_nric_birth_date_candidates

    assert my_nric_birth_date_candidates("900101145678") == (date(1990, 1, 1), date(2090, 1, 1))
    assert my_nric_birth_date_candidates("000229105555") == (date(2000, 2, 29),)   # 1900 was not a leap year


@pytest.mark.parametrize("value, ok", [("SG10234567890", True), ("IG12345678", True), ("C2584563202", True),
                                       ("12345678", False), ("SG1", False), ("", False)])
def test_tin_format_only(value, ok):
    from app.modules.payroll.employee_validation import my_tin_format_ok

    assert my_tin_format_ok(value) is ok


# ── employee validation strategy (dormant) ────────────────────────────────
@pytest.fixture
def my_strategy(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import MYEmployeeValidation, get_employee_validation_strategy

    strategy = get_employee_validation_strategy("MY")
    assert strategy is MYEmployeeValidation
    return strategy


def test_valid_malaysian_employee_is_cleaned(my_strategy):
    cleaned = my_strategy.validate({"passport_number": "a12345678", "swift_bic": "mbbe mykl",
                                    "bank_account": "5141-2345-6789"})
    assert cleaned == {"passport_number": "A12345678", "swift_bic": BIC, "bank_account": ACCOUNT}


def test_no_identifier_is_required_on_the_employee_record(my_strategy):
    assert my_strategy.validate({}) == {}


@pytest.mark.parametrize("key", ["national_id", "NRIC", "mykad", "tin", "tax_id", "epf_no", "socso_no",
                                 "work_pass_no"])
def test_personal_identifiers_are_vault_only(my_strategy, key):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        my_strategy.validate({key: "900101145678"})
    text = str(raised.value.detail if hasattr(raised.value, "detail") else raised.value)
    assert "identifier vault" in text and "900101145678" not in text         # never echoed


@pytest.mark.parametrize("payload, message", [
    ({"bank_account": "12AB"}, "Bank account number"),
    ({"swift_bic": "MBBEMY"}, "SWIFT/BIC"),
    ({"passport_number": "A1"}, "Passport number"),
])
def test_invalid_malaysian_employee_fields_are_refused(my_strategy, payload, message):
    # Format errors follow the platform's field-validation convention; the
    # identifiers that must never be echoed (NRIC, TIN, EPF / SOCSO numbers)
    # never reach this path - they are refused as vault-only above.
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        my_strategy.validate(payload)
    text = str(raised.value.detail if hasattr(raised.value, "detail") else raised.value)
    assert message in text


def test_identifiers_are_masked(my_strategy):
    assert set(my_strategy.SENSITIVE_FIELDS) == {"passport_number", "bank_account"}
    assert my_strategy.duplicate_field == "passport_number"


# ── bank routing ──────────────────────────────────────────────────────────
def test_bank_routing_uses_swift_and_account():
    from app.modules.payroll import bank_routing

    assert "MY" in bank_routing.ROUTING_COUNTRIES
    assert [f["key"] for f in bank_routing.ROUTING_FIELDS["MY"]] == ["swift_bic", "bank_account"]
    assert bank_routing.BTF_ROUTING_LABEL["MY"] == "SWIFT / Account"
    employee = SimpleNamespace(country="MY", compliance_fields={"swift_bic": BIC, "bank_account": ACCOUNT})
    assert bank_routing.btf_routing_value(employee, "MY") == f"{BIC} {ACCOUNT}"
    only_account = SimpleNamespace(country="MY", compliance_fields={"bank_account": ACCOUNT})
    assert bank_routing.btf_routing_value(only_account, "MY") == ACCOUNT


# ── dormancy ───────────────────────────────────────────────────────────────
# ── fail-closed calculation dispatch ───────────────────────────────────────
def test_malaysia_never_falls_through_to_the_generic_calculator():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import malaysia

    assert standard._COUNTRY_CALC["MY"] is malaysia.calculate
    assert standard._COUNTRY_CALC["MY"] is not standard._calc_generic


@pytest.mark.parametrize("mode", ["simple", "standard", "enterprise"])
def test_every_calculation_mode_is_blocked(mode):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.malaysia import MYCalculationBlockedError
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(MYCalculationBlockedError) as raised:
        calculate_payroll(PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country="MY"), mode)
    assert isinstance(raised.value, MissingComplianceConfigurationError)
    expected = "MY_SIMPLE_MODE_UNSUPPORTED" if mode == "simple" else "MY_PAY_DATE_MISSING"
    assert raised.value.key == expected


def test_registry_row_not_required():
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    assert "MY" not in _REGISTRY_ROW_REQUIRED_COUNTRIES                     # gate removal 2026-11-25

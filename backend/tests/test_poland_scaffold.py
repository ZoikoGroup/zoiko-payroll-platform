"""Poland (ZP-PL-ENG-001) Phase 0: identity, identifiers, dormancy and fail-closed dispatch."""
from decimal import Decimal

import pytest

# Vectors: 44051401359 and NIP 5261040828 are widely published valid examples;
# the rest were derived with the weighted check digit and cross-checked against
# the frontend mirror (scripts/pl-compliance-ui-validation.mjs).
VALID_PESEL = ["44051401359", "80010101230", "02270803624", "02322900013", "00222900016", "00810101232",
               "440514 01359", "4405-1401-359"]
# ISO 13616 / bank-published example IBANs (not real accounts). Defined once so
# the privacy scanner allowance covers exactly these two values.
PL_IBAN = "PL61109010140000071219812874"  # privacy-scan: allow
DE_IBAN = "DE89370400440532013000"  # privacy-scan: allow
PL_IBAN_BAD_CHECK = PL_IBAN[:-1] + "5"
INVALID_PESEL = ["44051401358",        # wrong check digit
                 "99022900010",        # 29 Feb 1999 does not exist
                 "44133101359",        # month 13 (no century band)
                 "4405140135",         # 10 digits
                 "4405140135A", "", None]


# ── jurisdiction identity ──────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["PL", "pl", "Poland", " POLAND ", "Polska", "Rzeczpospolita Polska",
                                   "Republic of Poland", "POL"])
def test_poland_resolves_to_pl(value):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    assert get_jurisdiction_code(value) == "PL"
    assert "Poland" not in REGISTRATION_COUNTRIES                     # never registrable while dormant


@pytest.mark.parametrize("value", ["Poland", "poland", "Polska", "PL"])
def test_payroll_normaliser_never_truncates_poland_to_po(value):
    from app.modules.payroll.service import _normalize_country

    assert _normalize_country(value) == "PL"


def test_bare_pl_is_not_a_free_text_alias():
    # "pl" is the paid-leave attendance code; Poland resolves via the schema key only.
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE

    assert "pl" not in ALL_COUNTRY_NAME_TO_CODE


def test_country_name_round_trip():
    from app.core.jurisdiction import CODE_TO_COUNTRY_NAME

    assert CODE_TO_COUNTRY_NAME["PL"] == "Poland"


def test_schema_examples_match_patterns_and_checksums():
    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers
    from app.modules.payroll.employee_validation import pl_nip_is_valid, pl_regon_is_valid

    schema = JURISDICTION_TAX_SCHEMAS["PL"]
    assert schema["currency"] == "PLN"
    fields = {f["key"]: f for f in schema["fields"]}
    assert list(fields) == ["nip", "regon", "krs"]                    # PESEL is never an org field
    assert fields["nip"]["primary"] is True
    assert pl_nip_is_valid(fields["nip"]["example"])
    assert pl_regon_is_valid(fields["regon"]["example"])
    examples = {k: f["example"] for k, f in fields.items()}
    assert validate_tax_identifiers("PL", examples) == (examples, [])
    assert validate_tax_identifiers("PL", {"nip": "12345"})[1]


# ── identifier checksums ──────────────────────────────────────────────────
@pytest.mark.parametrize("value", VALID_PESEL)
def test_pesel_accepts_valid_numbers(value):
    from app.modules.payroll.employee_validation import pl_pesel_is_valid

    assert pl_pesel_is_valid(value) is True


@pytest.mark.parametrize("value", INVALID_PESEL)
def test_pesel_rejects_invalid_numbers(value):
    from app.modules.payroll.employee_validation import pl_pesel_is_valid

    assert pl_pesel_is_valid(value) is False


@pytest.mark.parametrize("value, born", [("44051401359", "1944-05-14"), ("02270803624", "2002-07-08"),
                                         ("00222900016", "2000-02-29"), ("00810101232", "1800-01-01")])
def test_pesel_century_encoding(value, born):
    from app.modules.payroll.employee_validation import pl_pesel_birth_date

    assert pl_pesel_birth_date(value).isoformat() == born


@pytest.mark.parametrize("value, ok", [("1234563218", True), ("5261040828", True), ("526-104-08-28", True),
                                       ("526 104 08 28", True), ("5261040827", False),
                                       ("1234567890", False),   # weighted sum % 11 == 10: never valid
                                       ("123456321", False), ("", False), (None, False)])
def test_nip_check_digit(value, ok):
    from app.modules.payroll.employee_validation import pl_nip_is_valid

    assert pl_nip_is_valid(value) is ok


@pytest.mark.parametrize("value, ok", [("123456785", True), ("123456786", False),
                                       ("12345678512347", True), ("12345678500000", False),
                                       ("12345678612347", False),  # first nine invalid
                                       ("1234567", False), (None, False)])
def test_regon_check_digit(value, ok):
    from app.modules.payroll.employee_validation import pl_regon_is_valid

    assert pl_regon_is_valid(value) is ok


# ── employee validation strategy (dormant) ────────────────────────────────
def test_poland_is_not_an_employee_country_while_dormant():
    from app.modules.payroll.employee_validation import _STRATEGIES, _dormant_strategy, is_supported_employee_country

    assert "PL" not in _STRATEGIES
    assert _dormant_strategy("PL") is None
    assert is_supported_employee_country("PL") is False


@pytest.fixture
def pl_strategy(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import PLEmployeeValidation, get_employee_validation_strategy

    monkeypatch.setattr(settings, "PL_TENANT_ONBOARDING_ENABLED", True)
    strategy = get_employee_validation_strategy("PL")
    assert strategy is PLEmployeeValidation
    return strategy


def test_valid_polish_employee_is_cleaned(pl_strategy):
    cleaned = pl_strategy.validate({"passport_number": "ab1234567",
                                    "iban": " ".join(PL_IBAN.lower()[i:i + 4] for i in range(0, 28, 4))})
    assert cleaned == {"passport_number": "AB1234567", "iban": PL_IBAN}


def test_no_identifier_is_required_on_the_employee_record(pl_strategy):
    # PESEL lives in the vault; the run preflight (Phase 4) requires it there.
    assert pl_strategy.validate({}) == {}


@pytest.mark.parametrize("key", ["national_id", "PESEL", "tax_number", "nip", "tax_id"])
def test_pesel_and_nip_are_vault_only(pl_strategy, key):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        pl_strategy.validate({key: "44051401359"})
    text = str(raised.value.detail if hasattr(raised.value, "detail") else raised.value)
    assert "identifier vault" in text and "44051401359" not in text          # PL-025: never echoed


@pytest.mark.parametrize("payload, message", [
    ({"passport_number": "AB1234567", "iban": PL_IBAN_BAD_CHECK}, "Polish IBAN"),
    ({"passport_number": "AB1234567", "iban": DE_IBAN}, "Polish IBAN"),
])
def test_invalid_polish_employee_is_refused_without_echoing_the_value(pl_strategy, payload, message):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        pl_strategy.validate(payload)
    text = str(raised.value.detail if hasattr(raised.value, "detail") else raised.value)
    assert message in text
    assert payload["iban"] not in text


def test_identifiers_are_masked(pl_strategy):
    assert set(pl_strategy.SENSITIVE_FIELDS) == {"passport_number"}
    assert pl_strategy.duplicate_field == "passport_number"


# ── bank routing ──────────────────────────────────────────────────────────
def test_bank_routing_uses_the_polish_iban():
    from types import SimpleNamespace

    from app.modules.payroll import bank_routing

    assert "PL" in bank_routing.ROUTING_COUNTRIES
    assert bank_routing.ROUTING_FIELDS["PL"] == [{"key": "iban", "label": "IBAN"}]
    assert bank_routing.BTF_ROUTING_LABEL["PL"] == "IBAN"
    employee = SimpleNamespace(country="PL", compliance_fields={"iban": PL_IBAN})
    assert bank_routing.btf_routing_value(employee, "PL") == PL_IBAN


# ── dormancy ───────────────────────────────────────────────────────────────
def test_entering_poland_is_refused_while_dormant(monkeypatch):
    from app.config import settings
    from app.modules.payroll import poland_dormancy as d

    assert settings.PL_TENANT_ONBOARDING_ENABLED is False
    assert d.entering_poland_refusal("India", "Poland") == d.DORMANT_MESSAGE
    assert d.entering_poland_refusal(None, "PL") == d.DORMANT_MESSAGE
    assert d.entering_poland_refusal("PL", "Poland") is None                     # already Polish
    assert d.entering_poland_refusal("India", "Japan") is None                   # not Poland
    monkeypatch.setattr(settings, "PL_TENANT_ONBOARDING_ENABLED", True)
    assert d.entering_poland_refusal("India", "Poland") is None


def test_country_change_into_poland_is_blocked(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert "Poland is not open" in get_jurisdiction_change_block_reason(db, "India", "Poland")


@pytest.mark.parametrize("value", ["PL", "Poland"])
def test_company_jurisdiction_cannot_become_poland(db, value):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CompanyDetailsUpdate
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="PL Test Org", code="PLTEST", country=None)
    service.get_company_details(db, t.org.id)
    with pytest.raises(BadRequestException, match="Poland is not open"):
        service.update_company_details(db, t.org.id, CompanyDetailsUpdate(jurisdictionCountry=value))
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("PL", "Poland")


def test_backfill_never_makes_an_org_polish(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="PL Backfill Org", code="PLBACK", country=None)
    db.get(Organization, t.org.id).country = "Poland"
    db.commit()
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("PL", "Poland")


# ── fail-closed calculation dispatch ───────────────────────────────────────
def test_poland_never_falls_through_to_the_generic_calculator():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import poland

    assert standard._COUNTRY_CALC["PL"] is poland.calculate
    assert standard._COUNTRY_CALC["PL"] is not standard._calc_generic


@pytest.mark.parametrize("mode", ["simple", "standard", "enterprise"])
def test_every_calculation_mode_is_blocked(mode):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(PLCalculationBlockedError) as raised:
        calculate_payroll(PayrollContext(gross=Decimal("8000"), basic=Decimal("8000"), country="PL"), mode)
    assert isinstance(raised.value, MissingComplianceConfigurationError)
    # Phase 3: the engine exists, but a bare context (no pay date, profile or
    # pack) is refused with a named reason - never a generic result.
    expected = "PL_SIMPLE_MODE_UNSUPPORTED" if mode == "simple" else "PL_PAY_DATE_MISSING"
    assert raised.value.key == expected


def test_registry_row_required():
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    assert "PL" in _REGISTRY_ROW_REQUIRED_COUNTRIES


def test_poland_has_a_statutory_module_from_phase_4():
    # Phase 4 registers the Poland service with all 13 hooks (fail-closed).
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks.has_module("PL")

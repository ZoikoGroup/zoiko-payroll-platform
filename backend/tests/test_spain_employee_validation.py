"""Spain (ZP-ES-ENG-001, docs/spain) Phase 6: employee fields and banking.

ESEmployeeValidation: the facts countries/spain.py routes on, identifiers
(NIF/NIE with the official mod-23 check letter, NAF/NUSS 12 digits, both
masked), combination rules, the Spanish IBAN and SEPA routing. Synthetic
identifiers only (12345678Z / X1234567L are the textbook check-letter examples;
the IBAN is the ISO 13616 registry example)."""
from types import SimpleNamespace

import pytest

ES_IBAN = "ES9121000418450200051332"  # privacy-scan: allow (ISO 13616 registry example)
ES_IBAN_BAD_CHECK = ES_IBAN[:-1] + "3"
BASE = {"contract_type": "INDEFINITE", "contribution_group": "5", "extra_pay_policy": "PRORATED_12"}


def _validate(**fields):
    from app.modules.payroll.employee_validation import ESEmployeeValidation

    return ESEmployeeValidation.validate({**BASE, **fields})


def _refused(**fields):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        _validate(**fields)
    return str(raised.value)


def test_registered_as_an_ordinary_strategy():
    from app.modules.payroll.employee_validation import _DORMANT_STRATEGIES, _STRATEGIES, ESEmployeeValidation, \
        is_supported_employee_country

    assert _STRATEGIES["ES"] is ESEmployeeValidation and "ES" not in _DORMANT_STRATEGIES
    assert is_supported_employee_country("ES") is True


def test_minimal_record_and_normalisation():
    assert _validate(contract_type="indefinite", extra_pay_policy="prorated_12") == BASE
    full = _validate(extra_pay_policy="separate_14", extra_pay_annual_amount="4,000", extra_pay_months="6, 12",
                     work_pattern="full_time", overtime_kind="force_majeure", at_ep_rate="0.015",
                     family_situation="2", children_count="2", children_under_3="1", ascendants_count="0",
                     disability_degree="none", irpf_voluntary_rate="15")
    assert full["extra_pay_annual_amount"] == "4000" and full["extra_pay_months"] == "6,12"
    assert (full["overtime_kind"], full["disability_degree"]) == ("FORCE_MAJEURE", "NONE")


@pytest.mark.parametrize("missing", ["contract_type", "contribution_group", "extra_pay_policy"])
def test_routing_facts_are_required(missing):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import ESEmployeeValidation

    with pytest.raises(BadRequestException):
        ESEmployeeValidation.validate({k: v for k, v in BASE.items() if k != missing})


@pytest.mark.parametrize("value, expected", [("12345678Z", "12345678Z"), ("12345678-z", "12345678Z"),
                                             ("X1234567L", "X1234567L"), ("x-1234567-l", "X1234567L")])
def test_nif_nie_with_a_valid_check_letter(value, expected):
    assert _validate(nif_nie=value)["nif_nie"] == expected


@pytest.mark.parametrize("value", ["12345678A", "X1234567A", "1234567Z", "A1234567L", "123456789"])
def test_nif_nie_wrong_letter_or_shape_is_refused_without_echoing_it(value):
    message = _refused(nif_nie=value)
    assert value not in message


def test_naf_nuss_is_twelve_digits():
    assert _validate(naf_nuss="28/12345678/40")["naf_nuss"] == "281234567840"
    _refused(naf_nuss="2812345678")


@pytest.mark.parametrize("fields, needle", [
    ({"contract_type": "TEMPORARY"}, "contract_end_date"),
    ({"short_contract_exception": "YES"}, "short_contract_exception"),
    ({"extra_pay_policy": "SEPARATE_14", "extra_pay_months": "6,12"}, "extra_pay_annual_amount"),
    ({"extra_pay_policy": "SEPARATE_14", "extra_pay_annual_amount": "4000"}, "extra_pay_months"),
    ({"extra_pay_months": "6,13"}, "between 1 and 12"),
    ({"children_count": "1", "children_under_3": "2"}, "children_under_3"),
    ({"contribution_group": "12"}, "contribution_group"),
    ({"at_ep_rate": "1.5"}, "at_ep_rate"),
    ({"at_ep_rate": "15%"}, "at_ep_rate"),
])
def test_combination_and_format_rules(fields, needle):
    assert needle in _refused(**fields)


def test_temporary_contract_with_end_date_and_exception_is_accepted():
    cleaned = _validate(contract_type="TEMPORARY", contract_end_date="2026-07-20", short_contract_exception="no")
    assert cleaned["short_contract_exception"] == "NO"


def test_iban():
    grouped = " ".join(ES_IBAN[i:i + 4] for i in range(0, len(ES_IBAN), 4))
    assert _validate(iban=grouped.lower())["iban"] == ES_IBAN
    for bad in (ES_IBAN_BAD_CHECK, "BE68539007547034"):  # privacy-scan: allow
        assert bad not in _refused(iban=bad)


def test_identifiers_are_masked():
    from app.modules.payroll.employee_validation import ESEmployeeValidation, mask_compliance_fields

    assert ESEmployeeValidation.SENSITIVE_FIELDS == ("nif_nie", "naf_nuss")
    assert ESEmployeeValidation.duplicate_field == "nif_nie"
    masked = mask_compliance_fields({"nif_nie": "12345678Z", "naf_nuss": "281234567840", "contract_type": "TEMPORARY"})
    assert masked["nif_nie"] != "12345678Z" and masked["naf_nuss"] != "281234567840"
    assert masked["contract_type"] == "TEMPORARY"


def test_bank_routing_uses_the_spanish_iban_and_sepa():
    from app.modules.payroll import bank_routing

    assert bank_routing.ROUTING_COUNTRIES[-1] == "ES"
    assert bank_routing.ROUTING_FIELDS["ES"] == [{"key": "iban", "label": "IBAN"}]
    assert (bank_routing.BTF_ROUTING_LABEL["ES"], bank_routing.PAYMENT_MODE_LABEL["ES"]) == ("IBAN", "SEPA")
    employee = SimpleNamespace(country="ES", compliance_fields={"iban": ES_IBAN})
    assert bank_routing.btf_routing_value(employee, "ES") == ES_IBAN


def test_validated_record_feeds_the_calculator_facts():
    """The keys the validator produces are exactly what countries/spain.py reads."""
    import inspect

    from app.modules.payroll.engine.countries import spain

    source = inspect.getsource(spain)
    for key in ("contract_type", "contribution_group", "extra_pay_policy", "extra_pay_annual_amount",
                "extra_pay_months", "overtime_kind", "at_ep_rate", "short_contract_exception", "work_pattern"):
        assert f'"{key}"' in source, key

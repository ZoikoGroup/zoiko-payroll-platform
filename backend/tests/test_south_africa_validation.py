"""South Africa (ZP-ZA-ENG-001 Phase 5) - identity and bank validation.

The ZAEmployeeValidation strategy is exercised directly; its dormancy gate
(ZA_TENANT_ONBOARDING_ENABLED via south_africa_dormancy) keeps the strategy
out of production onboarding until the release gates are signed.
"""
import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_dormancy
from app.modules.payroll.bank_routing import (
    PAYMENT_MODE_LABEL, ROUTING_FIELDS, btf_routing_label, payment_mode_label,
    resolve_routing,
)
from app.modules.payroll.employee_validation import (
    ZAEmployeeValidation, mask_routing, za_national_id_is_valid,
)

VALID_ID = "8001015009087"
VALID_PASSPORT = "AB123456"


def test_za_validation_is_registered_and_dormant(monkeypatch):
    assert ZAEmployeeValidation.country_code == "ZA"
    assert ZAEmployeeValidation.duplicate_field == "national_id"
    assert {"national_id", "passport_number", "tax_number"} <= set(
        ZAEmployeeValidation.SENSITIVE_FIELDS)

    monkeypatch.setattr(south_africa_dormancy, "onboarding_enabled", lambda: False)
    from app.modules.payroll import employee_validation
    assert employee_validation._dormant_strategy("ZA") is None
    monkeypatch.setattr(south_africa_dormancy, "onboarding_enabled", lambda: True)
    assert employee_validation._dormant_strategy("ZA") is ZAEmployeeValidation


@pytest.mark.parametrize("value", [VALID_ID, "800101-5009-087", "800101 5009 087"])
def test_national_id_accepts_real_date_and_luhn(value):
    assert za_national_id_is_valid(value) is True


@pytest.mark.parametrize("value", [
    "", "800101500908", "80010150090870", "9913325009087",
    "8001015009088", "800101500908A", "0000000000000",
])
def test_national_id_rejects_bad_length_date_or_check_digit(value):
    assert za_national_id_is_valid(value) is False


def test_strategy_accepts_national_id_and_optional_fields():
    cleaned = ZAEmployeeValidation.validate({
        "national_id": "800101-5009-087",
        "tax_number": "12345 67890",
        "branch_code": "123456",
        "account_number": "123456789",
    })
    assert cleaned["national_id"] == VALID_ID
    assert cleaned["tax_number"] == "1234567890"


def test_strategy_accepts_passport_instead_of_national_id():
    cleaned = ZAEmployeeValidation.validate({"passport_number": " ab123456 "})
    assert cleaned["passport_number"] == VALID_PASSPORT


@pytest.mark.parametrize("payload", [
    {},
    {"national_id": VALID_ID, "passport_number": VALID_PASSPORT},
    {"passport_number": "AB1"},
    {"national_id": VALID_ID, "tax_number": "12345"},
    {"national_id": VALID_ID, "branch_code": "12345"},
    {"national_id": VALID_ID, "account_number": "123456"},
])
def test_strategy_rejects_missing_duplicate_or_malformed_fields(payload):
    with pytest.raises(BadRequestException):
        ZAEmployeeValidation.validate(payload)


def test_za_bank_routing_and_masking():
    assert ROUTING_FIELDS["ZA"] == [
        {"key": "branch_code", "label": "Branch Code"},
        {"key": "account_number", "label": "Account Number"},
    ]
    assert payment_mode_label("ZA") == "EFT"
    assert btf_routing_label("ZA") == "Branch Code / Account"
    assert PAYMENT_MODE_LABEL["ZA"] == "EFT"

    employee = type("E", (), {
        "country_code": "ZA",
        "compliance_fields": {
            "branch_code": "123456",
            "account_number": "123456789",
        },
    })()
    rows = resolve_routing(employee)
    assert [r["value"] for r in rows] == ["123456", "123456789"]
    masked = {r["key"]: r["value"] for r in mask_routing(rows)}
    assert masked["branch_code"] == "123456"
    assert masked["account_number"] != "123456789"
    assert masked["account_number"].endswith("6789")

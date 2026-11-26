"""Gate removal P4b (owner decision 2026-11-25): Japan has an ordinary employee validator.

The My Number is vault-only (japan_my_number): any compliance field carrying it is refused and the refusal never
echoes the value. Every statutory fact lives on the payroll_jp_* records, so there is no plain employee field.
"""
import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import employee_validation as ev

MY_NUMBER = "123456789018"  # privacy-scan: allow (synthetic TEST ONLY value)


def test_japan_is_a_supported_employee_country():
    assert ev.is_supported_employee_country("JP") is True
    assert ev.get_employee_validation_strategy("JP") is ev.JPEmployeeValidation
    assert "JP" in ev._STRATEGIES and "JP" not in ev._DORMANT_STRATEGIES


def test_an_employee_without_compliance_fields_validates():
    assert ev.JPEmployeeValidation.validate({}) == {}


@pytest.mark.parametrize("key", ["my_number", "MyNumber", "individual_number", "kojin_bango", "tax_number"])
def test_the_my_number_is_refused_as_an_employee_field_without_echo(key):
    with pytest.raises(BadRequestException, match="encrypted vault") as refused:
        ev.JPEmployeeValidation.validate({key: MY_NUMBER})
    assert MY_NUMBER not in str(refused.value)


def test_the_my_number_is_masked_if_ever_supplied():
    assert "my_number" in ev.SENSITIVE_COMPLIANCE_FIELDS

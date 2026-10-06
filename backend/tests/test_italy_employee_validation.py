"""Italy employee validation (ZP-IT-ENG-001 §18, IT-052)."""
import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import employee_validation as ev


@pytest.mark.parametrize("cf", ["RSSMRA85T10A562S", "MRTMTT25D09F205Z", "BNCLRA80A41H501D"])
def test_published_and_derived_codici_fiscali_pass(cf):
    assert ev.italian_codice_fiscale_is_valid(cf)


@pytest.mark.parametrize("cf", ["RSSMRA85T10A562T",      # wrong check character
                                "BNCLRA80A41H501Y",      # wrong check character
                                "RSSMRA85Z10A562S",      # Z is not a month letter
                                "RSSMRA85T10A56"])       # too short
def test_a_wrong_codice_fiscale_is_rejected(cf):
    assert not ev.italian_codice_fiscale_is_valid(cf)


def test_italy_has_a_registered_strategy_with_a_sensitive_codice_fiscale():
    strategy = ev._STRATEGIES["IT"]
    assert strategy.duplicate_field == "codice_fiscale"
    assert "codice_fiscale" in strategy.SENSITIVE_FIELDS


def test_check_character_mismatch_blocks_entry():
    with pytest.raises(BadRequestException):
        ev.ITEmployeeValidation._validate_combination({"codice_fiscale": "RSSMRA85T10A562T"})


def test_pension_fund_destination_needs_a_named_fund():
    with pytest.raises(BadRequestException):
        ev.ITEmployeeValidation._validate_combination({"tfr_destination": "FONDO_PENSIONE"})
    ev.ITEmployeeValidation._validate_combination({"tfr_destination": "FONDO_PENSIONE",
                                                   "pension_fund": "FONTE"})


@pytest.mark.parametrize("key,value,ok", [
    ("tax_domicile_region", "03", True), ("tax_domicile_region", "21", False),
    ("tax_domicile_comune", "F205", True), ("tax_domicile_comune", "MILANO", False),
    ("contractual_weekly_hours", "24.5", True), ("contractual_weekly_hours", "forty", False),
])
def test_field_formats(key, value, ok):
    spec = ev.ITEmployeeValidation.FIELD_SPECS[key]
    assert bool(spec["pattern"].match(value)) is ok

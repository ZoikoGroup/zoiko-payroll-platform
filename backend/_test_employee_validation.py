"""Unit tests for app/modules/payroll/employee_validation.py — the
jurisdiction-specific compliance validator used by employee create/update,
bulk import and the frontend's validateRow() parity checks.

Pure, DB-free. Run:  python _test_employee_validation.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.exceptions import BadRequestException
from app.modules.payroll.employee_validation import (
    get_employee_validation_strategy,
)

results = []


def check(name, fn):
    try:
        fn()
        results.append(("PASS", name))
    except AssertionError as exc:
        results.append(("FAIL", f"{name}: {exc}"))


def expect_valid(country, compliance, cleaned=None):
    out = get_employee_validation_strategy(country).validate(compliance)
    if cleaned is not None:
        assert out == cleaned, f"expected cleaned {cleaned}, got {out}"
    return out


def expect_invalid(country, compliance, fragment):
    try:
        get_employee_validation_strategy(country).validate(compliance)
    except BadRequestException as exc:
        assert fragment in str(exc), f"expected {fragment!r} in {exc}"
        return
    raise AssertionError(f"expected failure containing {fragment!r}, but validation passed")


# ── IN: only optional esi_number + tax_regime choices ─────────────────
def t_in_optional_empty():
    assert expect_valid("IN", {}) == {}
    assert expect_valid("in", {"tax_regime": "New"}) == {"tax_regime": "New"}


def t_in_bad_choice():
    expect_invalid("IN", {"tax_regime": "Old Regime"}, "must be one of")


def t_in_bad_esi():
    expect_invalid("IN", {"esi_number": "12ab"}, "ESI number")


# ── US: required ssn / flsa_status / state_tax_jurisdiction ───────────
def t_us_valid():
    out = expect_valid("US", {
        "ssn": "123-45-6789",
        "flsa_status": "Exempt",
        "state_tax_jurisdiction": "ca",
    }, {"ssn": "123-45-6789", "flsa_status": "Exempt", "state_tax_jurisdiction": "CA"})
    assert out["state_tax_jurisdiction"] == "CA"  # normalized to upper


def t_us_missing_ssn():
    expect_invalid("US", {"flsa_status": "Non-Exempt", "state_tax_jurisdiction": "NY"}, "ssn is required")


def t_us_bad_ssn_format():
    expect_invalid("US", {"ssn": "123-45-67", "flsa_status": "Exempt", "state_tax_jurisdiction": "NY"}, "123-45-6789")


def t_us_bad_state():
    expect_invalid("US", {"ssn": "123-45-6789", "flsa_status": "Exempt", "state_tax_jurisdiction": "California"}, "2-letter")


# ── UK: required nino / paye_tax_code / sort_code ─────────────────────
def t_uk_valid():
    out = expect_valid("UK", {
        "nino": "ab 123456 c",
        "paye_tax_code": "1257L",
        "sort_code": "12-34-56",
    })
    assert out["nino"] == "AB123456C", out  # stripped + upper


def t_uk_missing_nino():
    expect_invalid("UK", {"paye_tax_code": "BR", "sort_code": "123456"}, "nino is required")


def t_uk_bad_paye():
    expect_invalid("UK", {"nino": "AB123456C", "paye_tax_code": "ZZZZZ", "sort_code": "123456"}, "PAYE")


# ── AU: required tfn / bsb_code ────────────────────────────────────────
def t_au_valid():
    out = expect_valid("AU", {"tfn": "123 456 789", "bsb_code": "123-456"}, {"tfn": "123456789", "bsb_code": "123456"})
    assert out == {"tfn": "123456789", "bsb_code": "123456"}, out


def t_au_bad_tfn():
    expect_invalid("AU", {"tfn": "12345", "bsb_code": "123456"}, "TFN")


# ── CA: required sin / province ────────────────────────────────────────
def t_ca_valid():
    out = expect_valid("CA", {"sin": "123-456-789", "province": "on"}, {"sin": "123456789", "province": "ON"})
    assert out == {"sin": "123456789", "province": "ON"}, out


def t_ca_bad_province():
    expect_invalid("CA", {"sin": "123456789", "province": "XX"}, "must be one of")


# ── DE: required steuer_id / steuerklasse / krankenkasse / iban ────────
def t_de_valid():
    out = expect_valid("DE", {
        "steuer_id": "123 456 789 01",
        "steuerklasse": "i",
        "krankenkasse": "AOK",
        "iban": "de12 3456 7890 1234 5678 90",
        "bic": "AARGDEFF",
    })
    assert out["steuer_id"] == "12345678901", out
    assert out["steuerklasse"] == "I", out
    assert out["iban"] == "DE12345678901234567890", out
    assert out["bic"] == "AARGDEFF", out


def t_de_missing_required():
    expect_invalid("DE", {"krankenkasse": "AOK"}, "steuer_id is required")
    expect_invalid("DE", {"steuer_id": "12345678901", "krankenkasse": "AOK", "iban": "DE12345678901234567890"}, "steuerklasse is required")


def t_de_bad_iban():
    expect_invalid("DE", {
        "steuer_id": "12345678901", "steuerklasse": "I", "krankenkasse": "AOK", "iban": "FR00",
    }, "German IBAN")


# ── duplicate identifier extraction ────────────────────────────────────
def t_duplicate_fields():
    assert get_employee_validation_strategy("US").get_duplicate_identifier({"ssn": "123-45-6789"}) == ("ssn", "123-45-6789")
    assert get_employee_validation_strategy("UK").get_duplicate_identifier({"nino": "AB123456C"}) == ("nino", "AB123456C")
    assert get_employee_validation_strategy("AU").get_duplicate_identifier({"tfn": "123456789"}) == ("tfn", "123456789")
    assert get_employee_validation_strategy("CA").get_duplicate_identifier({"sin": "123456789"}) == ("sin", "123456789")
    assert get_employee_validation_strategy("DE").get_duplicate_identifier({"steuer_id": "12345678901"}) == ("steuer_id", "12345678901")
    assert get_employee_validation_strategy("IN").get_duplicate_identifier({}) is None
    assert get_employee_validation_strategy("US").get_duplicate_identifier({"ssn": ""}) is None


# ── factory / normalization ────────────────────────────────────────────
def t_factory_case_insensitive():
    for code in ("in", "us", "uk", "au", "ca", "de"):
        assert get_employee_validation_strategy(code).country_code == code.upper()


def t_factory_unsupported():
    try:
        get_employee_validation_strategy("XX")
    except BadRequestException as exc:
        assert "Unsupported country code" in str(exc)
        return
    raise AssertionError("expected BadRequestException for unsupported country")


check("IN: empty payload ok + choice normalization", t_in_optional_empty)
check("IN: bad tax_regime choice rejected", t_in_bad_choice)
check("IN: bad esi_number rejected", t_in_bad_esi)
check("US: valid row normalized (ssn kept, state uppercased)", t_us_valid)
check("US: missing required ssn rejected", t_us_missing_ssn)
check("US: malformed ssn rejected", t_us_bad_ssn_format)
check("US: non-code state rejected", t_us_bad_state)
check("UK: valid nino stripped+uppercased, sort code normalized", t_uk_valid)
check("UK: missing nino rejected", t_uk_missing_nino)
check("UK: bad PAYE code rejected", t_uk_bad_paye)
check("AU: valid tfn/bsb stripped of spaces/dashes", t_au_valid)
check("AU: short tfn rejected", t_au_bad_tfn)
check("CA: valid sin/province normalized", t_ca_valid)
check("CA: invalid province rejected", t_ca_bad_province)
check("DE: full valid row normalized (uppercased, stripped)", t_de_valid)
check("DE: missing required fields rejected", t_de_missing_required)
check("DE: non-German IBAN rejected", t_de_bad_iban)
check("duplicate-field extraction per jurisdiction", t_duplicate_fields)
check("factory is case-insensitive", t_factory_case_insensitive)
check("factory rejects unsupported country", t_factory_unsupported)

fails = [r for r in results if r[0] == "FAIL"]
for status, name in results:
    print(f"{status}: {name}")
if fails:
    print(f"RESULT: FAIL - {len(fails)} test(s) failed")
    sys.exit(1)
print("RESULT: PASS - employee validation strategies ok")

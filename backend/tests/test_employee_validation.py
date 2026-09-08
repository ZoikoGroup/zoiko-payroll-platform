"""
tests/test_employee_validation.py
----------------------------------
Coverage for app/modules/payroll/employee_validation.py's UK
has_postgrad_loan field — its choice validation, its FIELD_COLUMN_MAP/
FIELD_VALUE_MAP wiring into a real boolean, and the guard against
combining it with student_loan_plan == "Postgraduate" (which would
double-deduct the same loan via two separate mechanisms).
"""

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll.employee_validation import UKEmployeeValidation

# nino/paye_tax_code/sort_code are required for every UK employee —
# included in every payload below so each test isolates the ONE thing
# it's actually checking (has_postgrad_loan) rather than tripping the
# unrelated required-field checks.
_REQUIRED_BASE = {
    "nino": "AB123456C",
    "paye_tax_code": "1257L",
    "sort_code": "123456",
}


def _payload(**extra):
    return {**_REQUIRED_BASE, **extra}


def test_has_postgrad_loan_accepts_true_false_choices():
    cleaned = UKEmployeeValidation.validate(_payload(has_postgrad_loan="true"))
    assert cleaned["has_postgrad_loan"] == "true"


def test_has_postgrad_loan_rejects_invalid_choice():
    with pytest.raises(BadRequestException):
        UKEmployeeValidation.validate(_payload(has_postgrad_loan="yes"))


def test_has_postgrad_loan_syncs_to_real_boolean_column():
    cleaned = UKEmployeeValidation.validate(_payload(has_postgrad_loan="true"))
    columns = UKEmployeeValidation.sync_to_columns(cleaned)
    assert columns["has_postgrad_loan"] is True

    cleaned_false = UKEmployeeValidation.validate(_payload(has_postgrad_loan="false"))
    columns_false = UKEmployeeValidation.sync_to_columns(cleaned_false)
    assert columns_false["has_postgrad_loan"] is False


def test_has_postgrad_loan_absent_when_not_submitted():
    cleaned = UKEmployeeValidation.validate(_payload())
    columns = UKEmployeeValidation.sync_to_columns(cleaned)
    assert "has_postgrad_loan" not in columns


def test_postgrad_loan_flag_rejected_alongside_standalone_postgraduate_plan():
    # ZP-TAX-UK-2026-27-001 §10.2's own combination is Plan + Postgraduate
    # — but student_loan_plan == "Postgraduate" ALONE already represents a
    # standalone Postgraduate-only employee; setting the concurrent flag
    # too would double-deduct.
    with pytest.raises(BadRequestException, match="has_postgrad_loan cannot be enabled"):
        UKEmployeeValidation.validate(_payload(
            student_loan_plan="Postgraduate",
            has_postgrad_loan="true",
        ))


def test_standalone_postgraduate_plan_alone_is_still_valid():
    cleaned = UKEmployeeValidation.validate(_payload(student_loan_plan="Postgraduate"))
    assert cleaned["student_loan_plan"] == "Postgraduate"


def test_undergraduate_plan_with_postgrad_flag_is_a_valid_combination():
    # The document's own worked example: an undergraduate plan PLUS the
    # concurrent Postgraduate Loan flag is exactly the intended usage.
    cleaned = UKEmployeeValidation.validate(_payload(
        student_loan_plan="Plan 5",
        has_postgrad_loan="true",
    ))
    columns = UKEmployeeValidation.sync_to_columns(cleaned)
    assert columns["study_loan_plan"] == "UK_PLAN5"
    assert columns["has_postgrad_loan"] is True

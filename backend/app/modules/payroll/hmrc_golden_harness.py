"""
app/modules/payroll/hmrc_golden_harness.py
--------------------------------------------
Runs one normalized golden-test case through the REAL production UK
engine (engine/countries/uk.py via calculate_payroll) and compares the
result against HMRC's own expected figures, exactly — no tolerance, no
rounding leniency (ZP-TAX-UK-2026-27-001 §7.2's own rule).

Lives in the app package (not under tests/) because Super Admin UI
Part 11's "Test Certification" tab needs to trigger a real run of this
harness from a live API call (service.py's run_golden_test_
certification), not just from pytest — application code importing from
the test tree would be backwards. tests/hmrc_golden/runner.py re-exports
everything from here unchanged, so pytest usage is unaffected.

Deliberately calls the SAME `calculate_payroll(ctx, "standard")` entry
point a real payroll run uses, rather than reaching into uk.py's private
helper functions — a golden test is only meaningful if it validates the
actual assembled pipeline an employee's real payslip goes through, not
an isolated internal function that could pass while the real pipeline
still gets the answer wrong.

Case JSON schema (see tests/fixtures/hmrc_golden/README.md for the full
spec and tests/fixtures/hmrc_golden/_sample_student_loan.json for a
worked, mechanically-verified example):

{
  "description": "free text — which HMRC scenario this reproduces",
  "source": "e.g. income-tax-26-27.xlsx, sheet 'Tax Code L', row 12",
  "context": {
    "gross": "2500.00",            // required, this period's gross pay
    "pay_frequency": "Monthly",     // Weekly | Fortnightly | FourWeekly | Monthly
    "pay_date": "2026-06-30",       // optional, YYYY-MM-DD
    "tax_code": "1257L",            // optional
    "ni_category": "A",             // optional
    "study_loan_plan": "UK_PLAN2",  // optional
    "study_loan_balance": "1000",   // required alongside study_loan_plan —
                                     // the engine gates the whole
                                     // calculation on "balance > 0", not
                                     // on study_loan_plan alone; the
                                     // actual number never caps the
                                     // deduction, only its presence matters
    "has_postgrad_loan": false,     // optional
    "is_director": false,           // optional
    "date_of_birth": "1990-01-01",  // optional
    "rate_map": {                   // optional — omit to use the engine's
                                     // own real 2026-27 Python fallback
                                     // constants (hardcoded_defaults.py)
      "some_component_key": {"employee_rate_pct": "9", "flat_amount": null}
    },
    "slabs": [                      // optional — needed only for NI_BAND
                                     // (per-category banded NI) cases
      {"min_amount": "0", "max_amount": "12570", "rate_pct": "0",
       "rule_type": "NI_BAND", "ni_category": "A", "employer_rate_pct": "0"}
    ]
  },
  "expected": {
    // any subset of calculate_payroll's PayrollResult fields, e.g.:
    "tds": "391.60",
    "ni_employee": "204.69",
    "study_loan_deduction": "27.00"
  }
}
"""
from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.resolver import calculate_payroll


@dataclass
class GoldenRate:
    component_key: str = ""
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class GoldenSlab:
    min_amount: Decimal = Decimal("0")
    max_amount: Optional[Decimal] = None
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"
    ni_category: Optional[str] = None
    employer_rate_pct: Optional[Decimal] = None
    formula_expression: Optional[str] = None
    flat_amount: Optional[Decimal] = None
    filing_status: Optional[str] = None
    jurisdiction_state: Optional[str] = None


def _to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _to_date(value):
    if value is None:
        return None
    return date.fromisoformat(value)


def _build_rate_map(raw: Optional[dict]) -> dict:
    if not raw:
        return {}
    rate_map = {}
    for key, spec in raw.items():
        rate_map[key] = GoldenRate(
            component_key=key,
            employee_rate_pct=_to_decimal(spec.get("employee_rate_pct")),
            employer_rate_pct=_to_decimal(spec.get("employer_rate_pct")),
            flat_amount=_to_decimal(spec.get("flat_amount")),
        )
    return rate_map


def _build_slabs(raw: Optional[list]) -> list:
    if not raw:
        return []
    return [
        GoldenSlab(
            min_amount=_to_decimal(s.get("min_amount")) or Decimal("0"),
            max_amount=_to_decimal(s.get("max_amount")),
            rate_pct=_to_decimal(s.get("rate_pct")) or Decimal("0"),
            rule_type=s.get("rule_type", "MARGINAL_RATE"),
            ni_category=s.get("ni_category"),
            employer_rate_pct=_to_decimal(s.get("employer_rate_pct")),
            flat_amount=_to_decimal(s.get("flat_amount")),
            filing_status=s.get("filing_status"),
            jurisdiction_state=s.get("jurisdiction_state"),
        )
        for s in raw
    ]


def build_context(case_context: dict) -> PayrollContext:
    gross = _to_decimal(case_context["gross"])
    return PayrollContext(
        gross=gross,
        basic=gross,
        country="UK",
        pay_frequency=case_context.get("pay_frequency", "Monthly"),
        pay_date=_to_date(case_context.get("pay_date")),
        tax_code=case_context.get("tax_code"),
        ni_category=case_context.get("ni_category"),
        study_loan_plan=case_context.get("study_loan_plan"),
        study_loan_balance=_to_decimal(case_context.get("study_loan_balance")),
        has_postgrad_loan=case_context.get("has_postgrad_loan", False),
        is_director=case_context.get("is_director", False),
        date_of_birth=_to_date(case_context.get("date_of_birth")),
        rate_map=_build_rate_map(case_context.get("rate_map")),
        slabs=_build_slabs(case_context.get("slabs")),
    )


class GoldenCaseMismatch(AssertionError):
    def __init__(self, description: str, diffs: list):
        self.diffs = diffs
        lines = "\n".join(f"  {d['field']}: expected {d['expected']!r}, got {d['actual']!r}" for d in diffs)
        super().__init__(f"HMRC golden-test mismatch — {description}:\n{lines}")


def run_golden_case(case: dict) -> None:
    """Raises GoldenCaseMismatch (with every mismatched field, not just
    the first) if any expected figure doesn't match exactly. Passes
    silently otherwise."""
    ctx = build_context(case["context"])
    result = calculate_payroll(ctx, "standard")

    diffs = []
    for field_name, expected_raw in case["expected"].items():
        expected = _to_decimal(expected_raw)
        actual = getattr(result, field_name, None)
        if actual is None:
            diffs.append({"field": field_name, "expected": expected, "actual": None})
            continue
        actual_dec = Decimal(str(actual))
        if actual_dec != expected:
            diffs.append({"field": field_name, "expected": expected, "actual": actual_dec})

    if diffs:
        raise GoldenCaseMismatch(case.get("description", "(no description)"), diffs)

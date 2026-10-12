"""
tests/hmrc_golden
------------------
HMRC golden-test integration harness (ZP-TAX-UK-2026-27-001 §7.2/§22.1/
AC-31 gap-closure Part 10, 2026-09-09).

BLOCKED on Venu: HMRC's own "Software developers: payroll test data
2026 to 2027" files (published on GOV.UK, covering PAYE Tax, National
Insurance, Directors NI, and Student Loans) are real government files
this session cannot fetch on its own — see tests/fixtures/hmrc_golden/
README.md for the exact publication URL pattern and how to get them.

This package is the CI import harness that runs the moment those files
(converted to this harness's normalized JSON case format — see
scripts/convert_hmrc_test_data.py) are dropped into tests/fixtures/
hmrc_golden/. Per §7.2's own "no tolerance" rule, every comparison is
an exact Decimal equality check — never an approximate/rounded match.
"""

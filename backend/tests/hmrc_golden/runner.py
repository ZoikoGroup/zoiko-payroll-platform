"""
tests/hmrc_golden/runner.py
----------------------------
Thin re-export of app/modules/payroll/hmrc_golden_harness.py — the
actual harness now lives in the app package so Super Admin UI Part 11's
"Test Certification" tab can trigger a real run from a live API call
(service.py's run_golden_test_certification), not just from pytest.
Kept here, at this same import path, so nothing using
`from tests.hmrc_golden.runner import ...` had to change.
"""
from app.modules.payroll.hmrc_golden_harness import (  # noqa: F401
    GoldenRate, GoldenSlab, GoldenCaseMismatch,
    build_context, run_golden_case,
)

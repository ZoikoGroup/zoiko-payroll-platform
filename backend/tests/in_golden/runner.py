"""
tests/in_golden/runner.py
----------------------------
Thin re-export of app/modules/payroll/hmrc_golden_harness.py — the
actual harness lives in the app package so Super Admin UI's "Test
Certification" tab can trigger a real run from a live API call
(service.py's run_golden_test_certification), not just from pytest.
Mirrors tests/cra_golden/runner.py's own re-export shim exactly; see
that file's docstring for why.
"""
from app.modules.payroll.hmrc_golden_harness import (  # noqa: F401
    GoldenRate, GoldenSlab, GoldenCaseMismatch,
    build_context, run_golden_case,
)

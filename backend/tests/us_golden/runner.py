"""
tests/us_golden/runner.py
---------------------------
Thin re-export of app/modules/payroll/hmrc_golden_harness.py — the US
counterpart to tests/cra_golden/runner.py's own re-export shim. Same
generalized harness (build_context/run_golden_case), no US-specific
changes needed: it already forwards work_state/state_rate_map/state_slabs
generically, which is all these US cases require.
"""
from app.modules.payroll.hmrc_golden_harness import (  # noqa: F401
    GoldenRate, GoldenSlab, GoldenCaseMismatch,
    build_context, run_golden_case,
)

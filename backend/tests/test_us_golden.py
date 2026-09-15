"""
tests/test_us_golden.py
--------------------------
CI entry point for the US golden-test harness (ZP-TAX-US-2026-001 §13,
gap-closure Phase 8, 2026-09-12) — the US counterpart to
tests/test_cra_golden.py, running the exact same underlying harness
(app/modules/payroll/hmrc_golden_harness.py) against
tests/fixtures/us_golden/ instead. Discovers every *.json case file there
(excluding files starting with "_", the illustrative-sample convention)
and runs each through the real production engine, failing the build on
any penny mismatch — no tolerance, matching the UK/CA harnesses' own rule.
"""
import json
from pathlib import Path

import pytest

from tests.us_golden.runner import run_golden_case, GoldenCaseMismatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "us_golden"


def _load_cases(prefix_filter):
    cases = []
    if not FIXTURES_DIR.exists():
        return cases
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        is_sample = path.name.startswith("_")
        if prefix_filter == "real" and is_sample:
            continue
        if prefix_filter == "sample" and not is_sample:
            continue
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
        cases.append(pytest.param(case, id=f"{path.stem}"))
    return cases


@pytest.mark.parametrize("case", _load_cases("real"))
def test_us_golden_case(case):
    """Cases derived from ZP-TAX-US-2026-001's own §13 test table and
    Appendix A's verified figures — see tests/fixtures/us_golden/README.md
    for the exact provenance of each. Every one must match exactly."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)


@pytest.mark.parametrize("case", _load_cases("sample"))
def test_us_golden_harness_sample(case):
    """Illustrative samples ONLY (filenames starting with "_") — prove
    the harness mechanism itself works end-to-end for the US. None exist
    yet; this parametrization simply collects 0 until one is added."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)

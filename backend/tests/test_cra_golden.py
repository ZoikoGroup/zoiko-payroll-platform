"""
tests/test_cra_golden.py
---------------------------
CI entry point for the CRA/Revenu Quebec golden-test harness (ZP-TAX-
CA-2026-001 §20/AC-29, gap-closure Phase 8, 2026-09-11) — the Canada
counterpart to tests/test_hmrc_golden.py, running the exact same
underlying harness (app/modules/payroll/hmrc_golden_harness.py) against
tests/fixtures/cra_golden/ instead. Discovers every *.json case file
there (excluding files starting with "_", the illustrative-sample
convention) and runs each through the real production engine, failing
the build on any penny mismatch — no tolerance, matching the UK
harness's own rule.
"""
import json
from pathlib import Path

import pytest

from tests.cra_golden.runner import run_golden_case, GoldenCaseMismatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cra_golden"


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
def test_cra_golden_case(case):
    """Cases derived from ZP-TAX-CA-2026-001's own published rate
    tables, hand-verified and cross-checked against the real engine at
    authoring time — see tests/fixtures/cra_golden/README.md for the
    exact provenance of each. Every one must match exactly."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)


@pytest.mark.parametrize("case", _load_cases("sample"))
def test_cra_golden_harness_sample(case):
    """Illustrative samples ONLY (filenames starting with "_") — prove
    the harness mechanism itself works end-to-end for Canada. None exist
    yet; this parametrization simply collects 0 until one is added."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)

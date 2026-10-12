"""
tests/test_hmrc_golden.py
---------------------------
CI entry point for the HMRC golden-test harness (ZP-TAX-UK-2026-27-001
§7.2/§22.1/AC-31 gap-closure Part 10, 2026-09-09). Discovers every
*.json case file under tests/fixtures/hmrc_golden/ (excluding files
starting with "_", which are illustrative samples — see that directory's
README) and runs each through the real UK engine, failing the build on
any penny mismatch.

Currently collects ZERO real cases (BLOCKED — see package docstring and
tests/fixtures/hmrc_golden/README.md for why) and therefore reports
"no tests ran" for the real-case parametrization, which is the correct,
honest state until Venu supplies the actual HMRC files. This file does
NOT xfail/skip silently — an empty real-case set is visible in the test
report as "0 collected", not hidden.
"""
import json
from pathlib import Path

import pytest

from tests.hmrc_golden.runner import run_golden_case, GoldenCaseMismatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hmrc_golden"


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
def test_hmrc_golden_case(case):
    """Real, HMRC-sourced test vectors — every one must match exactly.
    Collects 0 cases until real files are converted and dropped in (see
    scripts/convert_hmrc_test_data.py)."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)


@pytest.mark.parametrize("case", _load_cases("sample"))
def test_hmrc_golden_harness_sample(case):
    """Illustrative samples ONLY (filenames starting with "_") — prove
    the harness mechanism itself works end-to-end. These are NOT
    HMRC-sourced values and must never be mistaken for real validation;
    see the README for why."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)

"""
tests/test_in_golden.py
---------------------------
CI entry point for the India golden-test harness (ZP-TAX-IN-2026-27-001
§20/§21, gap-closure Phase F, 2026-09-11) — the India counterpart to
tests/test_cra_golden.py, running the exact same underlying harness
(app/modules/payroll/hmrc_golden_harness.py) against
tests/fixtures/in_golden/ instead. Discovers every *.json case file
there (excluding files starting with "_", the illustrative-sample
convention) and runs each through the real production engine, failing
the build on any penny mismatch — no tolerance, matching the UK/Canada
harnesses' own rule.
"""
import json
from pathlib import Path

import pytest

from tests.in_golden.runner import run_golden_case, GoldenCaseMismatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "in_golden"


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
def test_in_golden_case(case):
    """Cases derived from ZP-TAX-IN-2026-27-001's own §21 golden test IDs
    and/or the engine's real seeded statutory data, hand-verified and
    cross-checked against the real engine at authoring time — see
    tests/fixtures/in_golden/README.md for the exact provenance of each.
    Every one must match exactly."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)


@pytest.mark.parametrize("case", _load_cases("sample"))
def test_in_golden_harness_sample(case):
    """Illustrative samples ONLY (filenames starting with "_") — prove
    the harness mechanism itself works end-to-end for India. None exist
    yet; this parametrization simply collects 0 until one is added."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)

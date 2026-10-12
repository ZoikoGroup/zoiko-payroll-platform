"""
tests/test_au_golden.py
---------------------------
CI entry point for the Australia golden-test harness (ZP-TAX-AU-2026-
27-001 §26-27, Phase 7, 2026-09-17) — the Australia counterpart to
tests/test_hmrc_golden.py/tests/test_cra_golden.py, running the exact
same underlying harness (app/modules/payroll/hmrc_golden_harness.py)
against tests/fixtures/au_golden/ instead. Discovers every *.json case
file there (excluding files starting with "_", the illustrative-sample
convention) and runs each through the real production engine, failing
the build on any penny mismatch — no tolerance, matching every other
jurisdiction's own golden-test rule.
"""
import json
from pathlib import Path

import pytest

from tests.au_golden.runner import run_golden_case, GoldenCaseMismatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "au_golden"


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
def test_au_golden_case(case):
    """Cases derived from ZP-TAX-AU-2026-27-001's own published §6/§7/§8
    coefficient and threshold tables, computed by hand against the
    document's own y = a·x − b formula and boundary rules, then
    cross-checked against the real engine at authoring time — see
    tests/fixtures/au_golden/README.md for the exact provenance of each.
    Every one must match exactly."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)


@pytest.mark.parametrize("case", _load_cases("sample"))
def test_au_golden_harness_sample(case):
    """Illustrative samples ONLY (filenames starting with "_") — prove
    the harness mechanism itself works end-to-end for Australia. None
    exist yet; this parametrization simply collects 0 until one is
    added."""
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as e:
        pytest.fail(str(e), pytrace=False)

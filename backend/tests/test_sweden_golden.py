"""Sweden golden vectors (ZP-SE-ENG-001 §15) through the shared harness —
see tests/fixtures/se_golden/README.md for what these do and do not cover."""
import json
from pathlib import Path

import pytest

from app.modules.payroll.hmrc_golden_harness import run_golden_case

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "se_golden"
CASES = sorted(p for p in FIXTURES.glob("*.json") if not p.name.startswith("_"))


def test_fixtures_exist():
    assert len(CASES) >= 14


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_se_golden_case(path):
    run_golden_case(json.loads(path.read_text(encoding="utf-8")))


def test_certification_console_runs_se_golden_vectors(db):
    from app.modules.payroll import service

    run = service.run_golden_test_certification(db, jurisdiction_country="SE", actor_id=202)
    assert (run.jurisdiction_country, run.status) == ("SE", "PASS")
    assert run.real_case_count == run.total_cases == run.passed_cases == len(CASES)

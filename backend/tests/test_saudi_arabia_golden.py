"""Saudi Arabia golden vectors (ZP-SA-ENG-001 §3) through the shared harness —
see tests/fixtures/sa_golden/README.md for what these do and do not cover."""
import json
from pathlib import Path

import pytest

from app.modules.payroll.hmrc_golden_harness import run_golden_case

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sa_golden"
CASES = sorted(p for p in FIXTURES.glob("*.json") if not p.name.startswith("_"))


def test_fixtures_exist():
    assert len(CASES) >= 8


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_sa_golden_case(path):
    run_golden_case(json.loads(path.read_text(encoding="utf-8")))


def test_certification_console_runs_sa_golden_vectors(db):
    from app.modules.payroll import service

    run = service.run_golden_test_certification(db, jurisdiction_country="SA", actor_id=202)
    assert (run.jurisdiction_country, run.status) == ("SA", "PASS")
    assert run.real_case_count == run.total_cases == run.passed_cases == len(CASES)

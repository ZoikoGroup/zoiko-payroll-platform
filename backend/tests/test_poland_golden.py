"""Poland golden fixtures (ZP-PL-ENG-001 Phase 3; spec §14 QA matrix).

Each tests/fixtures/pl_golden/*.json holds HAND-computed expected values (see its
`hand` list). The engine must reproduce every figure exactly, and the platform
strategy must arrive at the same net pay through tds + pl_employee_total.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests._pl_engine_helpers import ctx, declaration

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "pl_golden"
FIXTURES = sorted(GOLDEN.glob("*.json"))


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _context(fixture):
    inputs = fixture["inputs"]
    kwargs = {"gross": inputs["gross"], "pay_date": date.fromisoformat(fixture["payDate"])}
    if "ytd" in inputs:
        kwargs["ytd_overrides"] = inputs["ytd"]
    if "declarations" in inputs:
        kwargs["declarations"] = [declaration(kind, value, ident=i + 1)
                                  for i, (kind, value) in enumerate(inputs["declarations"])]
    if "ppk_state" in inputs:
        kwargs["ppk_state"] = inputs["ppk_state"]
    if "profile" in inputs:
        kwargs["profile_overrides"] = {k: (date.fromisoformat(v) if k.endswith("_from") else v)
                                       for k, v in inputs["profile"].items()}
    return ctx(**kwargs)


def test_there_are_golden_fixtures_and_each_shows_its_working():
    assert len(FIXTURES) >= 8
    for path in FIXTURES:
        fixture = _load(path)
        assert fixture["name"] == path.stem and fixture["hand"] and fixture["spec"] == "ZP-PL-ENG-001 v1.0"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_engine_reproduces_the_hand_computed_result(path):
    from app.modules.payroll.engine.countries.poland import calculate

    fixture = _load(path)
    expected = fixture["expected"]
    result = calculate(_context(fixture))
    pl = result["pl_result"]
    assert pl["pl_pit_advance"] == expected["pit"]
    assert pl["pl_pit_base"] == expected["pit_base"]
    assert pl["pl_zus_employee"] == expected["zus_employee"]
    assert pl["pl_zus_employer"] == expected["zus_employer"]
    assert pl["pl_health"] == expected["health"]
    assert sum(Decimal(v) for v in pl["pl_ppk_employee"].values()) == Decimal(expected["ppk_employee"])
    assert sum(Decimal(v) for v in pl["pl_ppk_employer"].values()) == Decimal(expected["ppk_employer"])
    assert pl["pl_funds"] == expected["funds"]
    assert pl["pl_employee_total"] == expected["employee_total"]
    assert pl["pl_employer_total"] == expected["employer_total"]
    assert pl["pl_net"] == expected["net"]
    assert [e["code"] for e in pl["exceptions"]] == expected["exceptions"]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_platform_net_pay_matches(path):
    from app.modules.payroll.engine.resolver import calculate_payroll

    fixture = _load(path)
    result = calculate_payroll(_context(fixture), "standard")
    expected = fixture["expected"]
    assert result.net_pay == Decimal(expected["net"])
    assert result.tds == Decimal(expected["pit"])
    assert result.pl_result["pl_net"] == expected["net"]
    # Employer-side figures are visible but never deducted from the employee.
    employer = sum(Decimal(v) for v in fixture["expected"]["zus_employer"].values())
    assert result.employer_esi == employer
    assert result.employer_pension == Decimal(expected["ppk_employer"])
    assert result.employer_payroll_tax == sum(Decimal(v) for v in expected["funds"].values())
    # employee_esi / employee_pension are deliberately unused (no double count).
    assert result.employee_esi == Decimal("0") and result.employee_pension == Decimal("0")

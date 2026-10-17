"""Mexico engine (Phase 5) is deployed but unreachable in production:
calc_inputs (the only hook that builds a real Mexican context) still blocks,
no Mexican employee can be created with the flag off, and mx_golden stays
empty so the national pack's golden gate (gate 4) still refuses."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "mx_golden"
# Fields every future Mexico golden vector must record (spec §21, MX-063).
GOLDEN_CONTEXT_FIELDS = ("pay_date", "rate_map", "slabs")
GOLDEN_RECORD_FIELDS = ("tariff_version", "uma_version", "min_wage_version", "independent_reference")


def test_calc_inputs_still_blocks():
    from app.modules.payroll import mexico_service
    from app.modules.payroll.engine.countries.mexico import MXBlock

    with pytest.raises(MXBlock) as exc:
        mexico_service.calc_inputs(None, None, SimpleNamespace(organization_id=3))
    assert exc.value.key == "MX_ENGINE_NOT_IMPLEMENTED" and exc.value.organization_id == 3


def test_flag_off_no_mexican_employee_strategy():
    from app.modules.payroll import employee_validation as ev

    assert "MX" not in ev._STRATEGIES


def test_mx_golden_is_empty_in_phase5():
    assert not [p for p in GOLDEN.glob("*.json") if not p.name.startswith("_")]


def test_golden_gate_finds_no_vector():
    from app.modules.payroll import mexico_service

    out = mexico_service.pack_golden_check(None, SimpleNamespace(effective_from=None, effective_to=None))
    assert out["casesInWindow"] == 0


def test_golden_fixture_schema():
    """Vacuous today; binds every vector added after transcription."""
    for path in GOLDEN.glob("*.json"):
        if path.name.startswith("_"):
            continue
        case = json.loads(path.read_text(encoding="utf-8"))
        assert all(k in case["context"] for k in GOLDEN_CONTEXT_FIELDS), path.name
        assert all(case.get("record", {}).get(k) for k in GOLDEN_RECORD_FIELDS), path.name
        assert "mx_result" in case.get("expected", {}), path.name

"""Inland Revenue official calculation examples (AC-NZ-01, gate G1).

Each NZ_IRD_EXAMPLE row's formula_expression is JSON:
  {"inputs": {...ctx overrides...}, "expected": {"paye": "...", "accLevy": "...", ...}}
and every expected amount must match exactly - no tolerance. Until the
signed examples are loaded the test is skipped with the gate reason.
"""
import json

import pytest

from app.modules.payroll.engine.countries import new_zealand_content as content

EXAMPLES = content.NZ_EMPTY_TABLES["ird_official_examples"]["rows"]


@pytest.mark.skipif(not EXAMPLES, reason="G1: Inland Revenue official examples are not loaded (AC-NZ-01)")
@pytest.mark.parametrize("example", EXAMPLES)
def test_ird_official_example(example):
    from app.modules.payroll.engine.countries import new_zealand as engine
    from tests._nz_engine_helpers import ctx

    spec = json.loads(example["formula_expression"])
    obligations = engine.calculate(ctx(**spec["inputs"]))["nz_result"]["obligations"]
    for key, value in spec["expected"].items():
        assert obligations[key] == value, key

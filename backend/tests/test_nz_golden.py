"""Inland Revenue official calculation examples (AC-NZ-01, gate G1).

Each NZ_IRD_EXAMPLE row's tax_formula holds one example in the compact format
nz_golden.parse_example reads:
  F=FORTNIGHTLY;C=M SL;G=3000;D=2026-04-08;KS=3.5;ESCT=30;EB=80730 => payeTotal=653.29;...
and every expected figure must match exactly - no tolerance. The live check
is nz_golden.nz_golden_check (Super Admin "Run golden check" and readiness
gate G1); until signed examples ship in the content this test is skipped with
the gate reason.
"""
from datetime import date

import pytest

from app.modules.payroll.engine.countries import new_zealand_content as content

EXAMPLES = content.NZ_EMPTY_TABLES["ird_official_examples"]["rows"]


@pytest.mark.skipif(not EXAMPLES, reason="G1: Inland Revenue official examples are not loaded (AC-NZ-01)")
@pytest.mark.parametrize("example", EXAMPLES)
def test_ird_official_example(example):
    from app.modules.payroll import nz_golden
    from app.modules.payroll.engine.countries import new_zealand as engine
    from tests._nz_engine_helpers import build_pack

    rate_map, slabs = build_pack()
    spec = nz_golden.parse_example(example["tax_formula"])
    result = engine.calculate(nz_golden.example_context(spec, rate_map, slabs, date(2026, 4, 1)))["nz_result"]
    figures = {**result["obligations"], "netPay": result["netPay"]}
    for key, value in spec["expected"].items():
        assert figures[key] == str(value), key

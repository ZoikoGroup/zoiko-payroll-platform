"""
tests/test_switzerland_engine.py
--------------------------------
CH Step 7 — federal calculator: split components, ALV cap, admin cost not in
employee total, missing rate blocks, determinism, NO hardcoded literals.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.switzerland import (
    calculate, SwitzerlandCalculationBlockedError, CH_PARAMETER_KEYS, _round_chf,
)
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_QST, CH_UVG, CH_YTD_COMPONENTS,
)

# Forbidden hardcoded literals that must NEVER appear in switzerland.py
FORBIDDEN_LITERALS = {
    "10.6", "5.3", "2.2", "1.1", "148200", "22680", "26460", "90720",
    "64260", "3780", "215", "268", "630", "7560", "24.59", "220",
}


def _ctx(**overrides):
    """Minimal PayrollContext with CH federal pack rates + required context."""
    rate_map = {
        "ch_ahv": SimpleNamespace(employee_rate_pct=Decimal("4.35"), employer_rate_pct=Decimal("4.35")),
        "ch_iv": SimpleNamespace(employee_rate_pct=Decimal("0.70"), employer_rate_pct=Decimal("0.70")),
        "ch_eo": SimpleNamespace(employee_rate_pct=Decimal("0.25"), employer_rate_pct=Decimal("0.25")),
        "ch_alv": SimpleNamespace(employee_rate_pct=Decimal("1.10"), employer_rate_pct=Decimal("1.10")),
        "ch_alv_ceiling": SimpleNamespace(flat_amount=Decimal("148200")),
        "ch_fak_child_min": SimpleNamespace(flat_amount=Decimal("215")),
        "ch_fak_education_min": SimpleNamespace(flat_amount=Decimal("268")),
        "ch_rounding_rule": SimpleNamespace(flat_amount=Decimal("0.05")),
    }
    ctx = PayrollContext(
        gross=Decimal("10000"), basic=Decimal("10000"), country="CH",
        rate_map=rate_map, slabs=[],
        ch_federal_pack_id=1, ch_federal_pack_version="1.0",
        ch_children_count=0, ch_students_count=0,
        ytd={}, earnings={},
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def _rate_row(ee, er):
    return SimpleNamespace(employee_rate_pct=Decimal(str(ee)), employer_rate_pct=Decimal(str(er)))


def _amount_row(amt):
    return SimpleNamespace(flat_amount=Decimal(str(amt)))


def _text_row(val):
    return SimpleNamespace(text_value=str(val))


# ── Helper to build a full context with all required rates ──────────────────

def _full_ctx(earnings=None, ytd=None, scheme_rules=None, classification=None, proration_rule="monthly"):
    rate_map = {
        "ch_ahv": _rate_row("4.35", "4.35"),
        "ch_iv": _rate_row("0.70", "0.70"),
        "ch_eo": _rate_row("0.25", "0.25"),
        "ch_alv": _rate_row("1.10", "1.10"),
        "ch_alv_ceiling": _amount_row("148200"),
        "ch_fak_child_min": _amount_row("215"),
        "ch_fak_education_min": _amount_row("268"),
        "ch_rounding_rule": _amount_row("0.05"),
    }
    ctx = PayrollContext(
        gross=Decimal("10000"), basic=Decimal("10000"), country="CH",
        rate_map=rate_map, slabs=[],
    )
    ctx.earnings = earnings or {}
    ctx.ytd = ytd or {}
    ctx.ch_federal_pack_id = 1
    ctx.ch_federal_pack_version = "1.0"
    ctx.ch_children_count = 2
    ctx.ch_students_count = 1
    ctx.ch_alv_proration_rule = proration_rule
    if classification is not None:
        ctx.ch_classification = classification
    if scheme_rules is not None:
        ctx.ch_scheme_rules = scheme_rules
    return ctx


# ── Rounding tests ──────────────────────────────────────────────────────────

def test_swiss_rounding_5_rappen():
    assert _round_chf(Decimal("100.00")) == Decimal("100.00")
    assert _round_chf(Decimal("100.01")) == Decimal("100.00")
    assert _round_chf(Decimal("100.02")) == Decimal("100.00")
    assert _round_chf(Decimal("100.03")) == Decimal("100.05")
    assert _round_chf(Decimal("100.04")) == Decimal("100.05")
    assert _round_chf(Decimal("100.05")) == Decimal("100.05")
    assert _round_chf(Decimal("100.06")) == Decimal("100.05")
    assert _round_chf(Decimal("100.07")) == Decimal("100.05")
    assert _round_chf(Decimal("100.08")) == Decimal("100.10")
    # Large value
    assert _round_chf(Decimal("123456.78")) == Decimal("123456.80")


# ── Component split: AHV, IV, EO, ALV are separate lines ────────────────────

def test_components_are_separate_lines():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    # Each obligation has its own employee + employer line
    assert out["ch_ahv_employee"] == Decimal("435.00")
    assert out["ch_ahv_employer"] == Decimal("435.00")
    assert out["ch_iv_employee"] == Decimal("70.00")
    assert out["ch_iv_employer"] == Decimal("70.00")
    assert out["ch_eo_employee"] == Decimal("25.00")
    assert out["ch_eo_employer"] == Decimal("25.00")
    assert out["ch_alv_employee"] == Decimal("110.00")
    assert out["ch_alv_employer"] == Decimal("110.00")
    # Employee total is sum of employee shares only
    assert out["ch_employee_total"] == Decimal("640.00")
    # Employer total includes admin cost (1% of AHV base = 100)
    assert out["ch_admin_cost_employer"] == Decimal("100.00")
    assert out["ch_employer_total"] == Decimal("740.00")


# ── ALV cap reached mid-year: ALV stops, AHV continues ──────────────────────

def test_alv_cap_stops_alv_ahv_continues():
    # YTD ALV wages already at 140000, ceiling 148200 -> 8200 remaining
    ytd = {CH_ALV: {"wages": Decimal("140000"), "withheld": Decimal("3080"), "recorded": True}}
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    ytd=ytd,
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    # ALV insurable = min(10000, 148200-140000) = 8200
    assert out["ch_alv_employee"] == Decimal("90.20")   # 8200 * 1.10%
    assert out["ch_alv_employer"] == Decimal("90.20")
    # AHV/IV/EO still on full 10000
    assert out["ch_ahv_employee"] == Decimal("435.00")
    assert out["ch_ahv_employer"] == Decimal("435.00")


def test_alv_cap_fully_reached_zero_alv():
    ytd = {CH_ALV: {"wages": Decimal("148200"), "withheld": Decimal("3260"), "recorded": True}}
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    ytd=ytd,
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    # ALV insurable = min(10000, 0) = 0
    assert out["ch_alv_employee"] == Decimal("0")
    assert out["ch_alv_employer"] == Decimal("0")
    # AHV/IV/EO continue
    assert out["ch_ahv_employee"] == Decimal("435.00")


# ── Admin cost is employer-only, not in employee total ──────────────────────

def test_admin_cost_employer_only_not_in_employee_total():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    assert out["ch_admin_cost_employer"] == Decimal("100.00")
    assert out["ch_employer_total"] == out["ch_ahv_employer"] + out["ch_iv_employer"] + \
                                       out["ch_eo_employer"] + out["ch_alv_employer"] + \
                                       out["ch_admin_cost_employer"]
    # Employee total does NOT include admin cost
    assert out["ch_employee_total"] == out["ch_ahv_employee"] + out["ch_iv_employee"] + \
                                       out["ch_eo_employee"] + out["ch_alv_employee"]
    assert out["ch_admin_cost_employer"] not in [out["ch_ahv_employee"], out["ch_iv_employee"],
                                                  out["ch_eo_employee"], out["ch_alv_employee"]]


# ── Missing rate blocks calculation ─────────────────────────────────────────

@pytest.mark.parametrize("missing_key", [
    "ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_alv_ceiling",
    "ch_fak_child_min", "ch_fak_education_min",
])
def test_missing_rate_blocks(missing_key):
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    # Remove the key from rate_map
    del ctx.rate_map[missing_key]
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert missing_key in str(exc.value.key)


def test_missing_classification_blocks():
    # classification missing for base_salary under AHV
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_classification" in str(exc.value.key)
    assert CH_AHV in str(exc.value.key)


def test_missing_scheme_admin_cost_blocks():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={})  # missing admin_cost_pct
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_scheme_admin_cost_pct" in str(exc.value.key)


def test_missing_alv_proration_rule_blocks():
    # proration rule read from ctx.ch_alv_proration_rule
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"},
                    proration_rule=None)
    # ch_alv_proration_rule not set
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_alv_proration_rule" in str(exc.value.key)


# ── Determinism: same input -> same hashes ──────────────────────────────────

def test_deterministic_hashes():
    ctx1 = _full_ctx(earnings={"base_salary": Decimal("10000")},
                     classification={CH_AHV: {"base_salary": True},
                                     CH_IV: {"base_salary": True},
                                     CH_EO: {"base_salary": True},
                                     CH_ALV: {"base_salary": True}},
                     scheme_rules={"admin_cost_pct": "1.0"})
    ctx2 = _full_ctx(earnings={"base_salary": Decimal("10000")},
                     classification={CH_AHV: {"base_salary": True},
                                     CH_IV: {"base_salary": True},
                                     CH_EO: {"base_salary": True},
                                     CH_ALV: {"base_salary": True}},
                     scheme_rules={"admin_cost_pct": "1.0"})
    out1 = calculate(ctx1)
    out2 = calculate(ctx2)
    assert out1["ch_calculation_trace"]["input_hash"] == out2["ch_calculation_trace"]["input_hash"]
    assert out1["ch_calculation_trace"]["rule_hash"] == out2["ch_calculation_trace"]["rule_hash"]
    # Changing input changes hash
    ctx3 = _full_ctx(earnings={"base_salary": Decimal("20000")},
                     classification={CH_AHV: {"base_salary": True},
                                     CH_IV: {"base_salary": True},
                                     CH_EO: {"base_salary": True},
                                     CH_ALV: {"base_salary": True}},
                     scheme_rules={"admin_cost_pct": "1.0"})
    out3 = calculate(ctx3)
    assert out1["ch_calculation_trace"]["input_hash"] != out3["ch_calculation_trace"]["input_hash"]


# ── Family allowances added to net (not deducted) ───────────────────────────

def test_family_allowances_added_to_net():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    # 2 children * 215 + 1 student * 268 = 430 + 268 = 698
    assert out["ch_fak_child_total"] == Decimal("430.00")
    assert out["ch_fak_education_total"] == Decimal("268.00")
    assert out["ch_family_allowance_total"] == Decimal("698.00")
    # Family allowance is NOT in employee_total
    assert out["ch_employee_total"] == Decimal("640.00")


# ── Snapshot structure ──────────────────────────────────────────────────────

def test_snapshot_structure():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    trace = out["ch_calculation_trace"]
    assert "lines" in trace
    assert "bases" in trace
    assert "accumulators_before" in trace
    assert "accumulators_after" in trace
    assert "resolved_versions" in trace
    assert "input_hash" in trace
    assert "rule_hash" in trace
    # 9 lines: AHV ee/er, IV ee/er, EO ee/er, ALV ee/er, admin, FAK child, FAK education
    assert len(trace["lines"]) == 9
    for line in trace["lines"]:
        assert "obligation" in line
        assert "side" in line
        assert "base" in line
        assert "rate_or_rule" in line
        assert "scope_id" in line
        assert "scope_version" in line
        assert "source_label" in line
        assert "rule_version" in line


# ── No fallback: grep for forbidden literals in switzerland.py ──────────────

def test_no_hardcoded_literals_in_calculator():
    import pathlib
    path = pathlib.Path(__file__).parent.parent / "app" / "modules" / "payroll" / "engine" / "countries" / "switzerland.py"
    content = path.read_text()
    for lit in FORBIDDEN_LITERALS:
        # Allow in comments/docstrings only — the actual values must come from rate_map
        # We check that the literal does NOT appear outside a comment/docstring context
        # Simple heuristic: not in an executable line (not starting with # or inside """ """)
        lines = content.splitlines()
        found_in_code = False
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
            if not in_docstring and not stripped.startswith("#"):
                if lit in line:
                    found_in_code = True
                    break
        assert not found_in_code, f"Forbidden literal '{lit}' found in executable code in switzerland.py"


# ── CH_PARAMETER_KEYS parity ────────────────────────────────────────────────

def test_ch_parameter_keys_parity():
    from app.modules.payroll.engine.countries.switzerland_content import CH_PARAMETER_KEYS as CONTENT_KEYS
    assert CH_PARAMETER_KEYS == CONTENT_KEYS


# ── Integration: CH in standard strategy ────────────────────────────────────

def test_ch_registered_in_standard_strategy():
    from app.modules.payroll.engine.standard import _COUNTRY_CALC
    assert "CH" in _COUNTRY_CALC
    assert _COUNTRY_CALC["CH"].__name__ == "calculate"


# ── CH in validation enabled countries ──────────────────────────────────────

def test_ch_in_validation_enabled():
    from app.modules.payroll.engine.countries.shared import _VALIDATION_ENABLED_COUNTRIES
    assert "CH" in _VALIDATION_ENABLED_COUNTRIES


# ── Fallback registry NO FALLBACK entries ───────────────────────────────────

def test_fallback_registry_ch_no_fallback():
    from app.modules.payroll.engine.fallback_registry import _ENGINE_CONSTANT_REGISTRY
    ch_entries = [e for e in _ENGINE_CONSTANT_REGISTRY if e["country"] == "CH"]
    assert len(ch_entries) >= 7  # AHV, IV, EO, ALV, ceiling, admin, proration, FAK child/edu, rounding
    for e in ch_entries:
        assert "NO FALLBACK" in e["note"]


# ── Employee total only includes employee shares ────────────────────────────

def test_employee_total_excludes_employer_shares():
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    out = calculate(ctx)
    # Employee total = 4.35 + 0.70 + 0.25 + 1.10 = 6.40% of 10000 = 640
    assert out["ch_employee_total"] == Decimal("640.00")
    # Employer total includes admin cost
    assert out["ch_employer_total"] == Decimal("740.00")
"""
tests/test_switzerland_engine.py
--------------------------------
CH Step 7 — federal calculator: split components, ALV cap, admin cost not in
employee total, missing rate blocks, determinism, NO hardcoded literals.
CH Step 8 — BVG engine: eligibility, coordination guardrails, age bands, two
plans, extra-mandatory separation, no threshold retroactivity, employer <50%.
CH Step 9 — UVG/NBU/KTG: BU employer-only at the policy risk-class rate, NBU
only when weekly hours meet the pack minimum, CH_UVG ceiling accumulator,
KTG on its own classified base at the policy rate/split, missing policy blocks.
CH Step 10 — QST: canton model selects MONTHLY/ANNUAL strategy from content
arithmetic, PERIODIC/APERIODIC split by treatment, tariff row passed in ctx
(rate/min_tax/row_id), min_tax floor, canton/file change at boundary never
blends rates, superseded file replayable but never reused, multiple employment
flag path, review state and missing facts BLOCK (annual model is PENDING G1).
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.switzerland import (
    calculate, SwitzerlandCalculationBlockedError, CH_PARAMETER_KEYS, _round_chf,
    _validate_bvg_scheme_employer_share,
)
from app.modules.payroll.engine.countries import switzerland as sw
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_QST, CH_UVG, CH_YTD_COMPONENTS,
)
from app.modules.payroll.switzerland_schemas import validate_scheme_rules
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

_DEFAULT_UVG_RULES = {
    "insurer": "TEST-UVR-INSURER",
    "risk_classes": [{"code": "A1", "bu_employer_pct": "0.3", "nbu_pct": "0.9", "nbu_employee_share_pct": "0.45"}],
}


def _full_ctx(earnings=None, ytd=None, scheme_rules={"admin_cost_pct": "1.0"}, classification=None,
              proration_rule="monthly", uvg_rules=None, uvg_policy_id=3, uvg_risk_class="A1",
              weekly_hours="9", ktg_rules=None, ktg_policy_id=4):
    rate_map = {
        "ch_ahv": _rate_row("4.35", "4.35"),
        "ch_iv": _rate_row("0.70", "0.70"),
        "ch_eo": _rate_row("0.25", "0.25"),
        "ch_alv": _rate_row("1.10", "1.10"),
        "ch_alv_ceiling": _amount_row("148200"),
        "ch_uvg_ceiling": _amount_row("148200"),
        "ch_nbu_min_weekly_hours": _amount_row("8"),
        "ch_bvg_entry_threshold": _amount_row("22680"),
        "ch_bvg_coordination_deduction": _amount_row("26460"),
        "ch_bvg_upper_salary": _amount_row("90720"),
        "ch_bvg_min_coordinated": _amount_row("3780"),
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
    ctx.payroll_date = date(2026, 3, 31)
    ctx.ch_annual_salary = Decimal("20000")  # Below BVG threshold (22680) -> not eligible
    ctx.ch_date_of_birth = date(1990, 5, 1)
    # Classification: an explicit dict has full control (a missing AHV entry in
    # a test really is missing); CH_UVG is compulsory for every employee, so it
    # is the only component ever defaulted for base_salary.
    merged_classification = dict(classification or {})
    merged_classification.setdefault(CH_UVG, {"base_salary": True})
    ctx.ch_classification = merged_classification
    if scheme_rules is not None:
        ctx.ch_scheme_rules = scheme_rules
    # UVG — compulsory for every employee: policy, risk class and weekly hours
    ctx.ch_uvg_policy_scheme_id = uvg_policy_id
    ctx.ch_uvg_scheme_rules = uvg_rules if uvg_rules is not None else _DEFAULT_UVG_RULES
    ctx.ch_uvg_risk_class = uvg_risk_class
    ctx.ch_weekly_hours = Decimal(str(weekly_hours))
    # KTG — elected via a LIVE KTG_POLICY scheme assignment
    if ktg_rules is not None:
        ctx.ch_ktg_policy_scheme_id = ktg_policy_id
        ctx.ch_ktg_scheme_rules = ktg_rules
    # QST — off by default: an unchosen worker is recorded NO, and the QST
    # engine skips them. Only the STEP 10 contexts flip it to YES.
    ctx.ch_qst_subject = "NO"
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
    # UVG — BU employer-only; NBU split (worker at 9 h/week >= the min)
    assert out["ch_uvg_bu_employer"] == Decimal("30.00")
    assert out["ch_uvg_nbu_employee"] == Decimal("45.00")
    assert out["ch_uvg_nbu_employer"] == Decimal("45.00")
    assert out["ch_uvg_employee"] == Decimal("45.00")
    assert out["ch_uvg_employer"] == Decimal("75.00")
    # Employee total is sum of employee shares only (includes NBU employee)
    assert out["ch_employee_total"] == Decimal("685.00")
    # Employer total includes admin cost + BU + NBU employer
    assert out["ch_admin_cost_employer"] == Decimal("100.00")
    assert out["ch_employer_total"] == Decimal("815.00")


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
                                       out["ch_uvg_employer"] + out["ch_ktg_employer"] + \
                                       out["ch_admin_cost_employer"]
    # Employee total does NOT include admin cost or employer shares
    assert out["ch_employee_total"] == out["ch_ahv_employee"] + out["ch_iv_employee"] + \
                                       out["ch_eo_employee"] + out["ch_alv_employee"] + \
                                       out["ch_uvg_employee"] + out["ch_ktg_employee"]
    assert out["ch_admin_cost_employer"] not in [out["ch_ahv_employee"], out["ch_iv_employee"],
                                                  out["ch_eo_employee"], out["ch_alv_employee"]]


# ── Missing rate blocks calculation ─────────────────────────────────────────

@pytest.mark.parametrize("missing_key", [
    "ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_alv_ceiling",
    "ch_uvg_ceiling", "ch_nbu_min_weekly_hours",
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
    assert out["ch_employee_total"] == Decimal("685.00")


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
    # AHV ee/er, IV ee/er, EO ee/er, ALV ee/er, UVG BU er, UVG NBU ee/er, admin
    assert len(trace["lines"]) == 12
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
    # Employee total = 4.35 + 0.70 + 0.25 + 1.10 = 6.40% of 10000 = 640, + NBU
    # employee share 0.45% (45.00) = 685
    assert out["ch_employee_total"] == Decimal("685.00")
    # Employer total includes BU (30.00) + NBU employer (45.00) + admin cost
    assert out["ch_employer_total"] == Decimal("815.00")


# ── CH Step 8: BVG (occupational pension) engine ─────────────────────────────

def _bvg_scheme(bands):
    return {"entry_rules": {}, "insured_salary_def": "annual",
            "coordination": {"mode": "STATUTORY"}, "bands": bands}


def _bvg_ctx(annual_salary="100000", bands=None, scheme_id=5, dob=None, exempt=False):
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000")},
                    classification={CH_AHV: {"base_salary": True},
                                    CH_IV: {"base_salary": True},
                                    CH_EO: {"base_salary": True},
                                    CH_ALV: {"base_salary": True}},
                    scheme_rules={"admin_cost_pct": "1.0"})
    ctx.ch_annual_salary = Decimal(annual_salary)
    if dob is not None:
        ctx.ch_date_of_birth = dob
    if scheme_id is not None:
        ctx.ch_bvg_plan_scheme_id = scheme_id
    if bands is not None:
        ctx.ch_bvg_scheme_rules = _bvg_scheme(bands)
    if exempt:
        ctx.ch_bvg_exempt = True
    return ctx


_STD_BANDS = [
    {"component": "MANDATORY", "age_from": 25, "age_to": 44, "employee_pct": "5.0", "employer_pct": "5.0"},
]


def test_bvg_below_entry_threshold_no_contribution():
    ctx = _bvg_ctx(annual_salary="20000", bands=_STD_BANDS, scheme_id=5)
    out = calculate(ctx)
    assert out["ch_bvg_mandatory_employee"] == Decimal("0")
    assert out["ch_bvg_mandatory_employer"] == Decimal("0")
    assert out["ch_bvg_employee"] == Decimal("0")
    assert out["ch_bvg_employer"] == Decimal("0")


def test_bvg_exempt_skips_contributions():
    ctx = _bvg_ctx(annual_salary="100000", bands=_STD_BANDS, scheme_id=5, exempt=True)
    out = calculate(ctx)
    assert out["ch_bvg_mandatory_employee"] == Decimal("0")
    assert out["ch_bvg_mandatory_employer"] == Decimal("0")


def test_bvg_eligible_without_plan_blocks():
    ctx = _bvg_ctx(annual_salary="100000", bands=_STD_BANDS, scheme_id=None)
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_bvg_plan:not_assigned" in str(exc.value.key)


def test_bvg_threshold_crossing_no_retroactive_ytd():
    # Annual salary crossed the entry threshold mid-year: the CH_BVG accumulator
    # starts this period with only the current month's insured wage — no catch-up
    # for the earlier, under-threshold months and no annualised backfill.
    ctx = _bvg_ctx(annual_salary="100000", bands=_STD_BANDS, scheme_id=5)
    out = calculate(ctx)
    # coordinated = min(max(100000 - 26460, 3780), 90720) = 73540; monthly 6128.35
    assert out["ch_bvg_mandatory_employee"] == Decimal("306.40")
    assert out["ch_bvg_mandatory_employer"] == Decimal("306.40")
    trace = out["ch_calculation_trace"]
    assert trace["accumulators_before"][CH_BVG]["wages"] == "0"
    assert trace["accumulators_after"][CH_BVG]["wages"] == "6128.35"
    assert trace["accumulators_after"][CH_BVG]["withheld"] == "612.8"
    mandatory_lines = [l for l in trace["lines"] if l["obligation"] == "ch_bvg_mandatory"]
    assert len(mandatory_lines) == 2
    for line in mandatory_lines:
        assert line["base"] == "6128.35"


def test_bvg_age_band_change_applies_new_rates():
    bands = [
        {"component": "MANDATORY", "age_from": 25, "age_to": 34, "employee_pct": "6.0", "employer_pct": "8.0"},
        {"component": "MANDATORY", "age_from": 35, "age_to": 44, "employee_pct": "7.0", "employer_pct": "9.5"},
    ]
    # born 1991-05-01 -> age 34 on 2026-03-31 -> applies the 25-34 band
    ctx34 = _bvg_ctx(annual_salary="100000", bands=bands, scheme_id=5, dob=date(1991, 5, 1))
    out34 = calculate(ctx34)
    assert out34["ch_bvg_mandatory_employee"] == Decimal("367.70")   # 6128.35 * 6%
    assert out34["ch_bvg_mandatory_employer"] == Decimal("490.25")   # 6128.35 * 8%
    # born 1990-05-01 -> age 35 on 2026-03-31 -> applies the 35-44 band
    ctx35 = _bvg_ctx(annual_salary="100000", bands=bands, scheme_id=5, dob=date(1990, 5, 1))
    out35 = calculate(ctx35)
    assert out35["ch_bvg_mandatory_employee"] == Decimal("429.00")   # 6128.35 * 7%
    assert out35["ch_bvg_mandatory_employer"] == Decimal("582.20")   # 6128.35 * 9.5%


def test_bvg_two_different_plans_different_rates():
    plan_a = [{"component": "MANDATORY", "age_from": 25, "age_to": 44, "employee_pct": "5.0", "employer_pct": "5.0"}]
    plan_b = [{"component": "MANDATORY", "age_from": 25, "age_to": 44, "employee_pct": "6.5", "employer_pct": "8.0"}]
    out_a = calculate(_bvg_ctx(annual_salary="100000", bands=plan_a, scheme_id=5))
    out_b = calculate(_bvg_ctx(annual_salary="100000", bands=plan_b, scheme_id=6))
    assert out_a["ch_bvg_mandatory_employee"] == Decimal("306.40")   # 6128.35 * 5%
    assert out_a["ch_bvg_mandatory_employer"] == Decimal("306.40")
    assert out_b["ch_bvg_mandatory_employee"] == Decimal("398.35")   # 6128.35 * 6.5%
    assert out_b["ch_bvg_mandatory_employer"] == Decimal("490.25")   # 6128.35 * 8%


def test_bvg_coordination_floor():
    # annual 25000 >= entry threshold, but 25000 - 26460 < 0 -> floored at
    # the statutory minimum coordinated salary (3780), never negative/zero.
    bands = [{"component": "MANDATORY", "age_from": 25, "age_to": 64, "employee_pct": "5.0", "employer_pct": "5.0"}]
    ctx = _bvg_ctx(annual_salary="25000", bands=bands, scheme_id=5)
    out = calculate(ctx)
    # monthly insured = 3780 / 12 = 315.00; 5% each side = 15.75
    assert out["ch_bvg_mandatory_employee"] == Decimal("15.75")
    assert out["ch_bvg_mandatory_employer"] == Decimal("15.75")
    bvg_lines = [l for l in out["ch_calculation_trace"]["lines"] if l["obligation"] == "ch_bvg_mandatory"]
    assert len(bvg_lines) == 2
    for line in bvg_lines:
        assert line["base"] == "315.00"


def test_bvg_extra_mandatory_separate_line():
    bands = [
        {"component": "MANDATORY", "age_from": 25, "age_to": 44, "employee_pct": "5.0", "employer_pct": "5.0"},
        {"component": "EXTRA_MANDATORY", "age_from": 25, "age_to": 44,
         "salary_from": "90720", "salary_to": "150000", "employee_pct": "7.0", "employer_pct": "9.0"},
    ]
    ctx = _bvg_ctx(annual_salary="100000", bands=bands, scheme_id=5)
    out = calculate(ctx)
    # mandatory on coordinated salary 73540/12 = 6128.35 @ 5%
    assert out["ch_bvg_mandatory_employee"] == Decimal("306.40")
    assert out["ch_bvg_mandatory_employer"] == Decimal("306.40")
    # extra-mandatory on the slice (100000 - 90720) = 9280/12 = 773.35 @ 7%/9%
    assert out["ch_bvg_extra_mandatory_employee"] == Decimal("54.15")
    assert out["ch_bvg_extra_mandatory_employer"] == Decimal("69.60")
    assert out["ch_bvg_employee"] == out["ch_bvg_mandatory_employee"] + out["ch_bvg_extra_mandatory_employee"]
    assert out["ch_bvg_employer"] == out["ch_bvg_mandatory_employer"] + out["ch_bvg_extra_mandatory_employer"]
    obligations = {l["obligation"] for l in out["ch_calculation_trace"]["lines"]}
    assert "ch_bvg_mandatory" in obligations
    assert "ch_bvg_extra_mandatory" in obligations
    extra_lines = [l for l in out["ch_calculation_trace"]["lines"] if l["obligation"] == "ch_bvg_extra_mandatory"]
    assert len(extra_lines) == 2
    for line in extra_lines:
        assert line["base"] == "773.35"


def test_bvg_employer_share_below_50_rejected():
    bad = {"bands": [{"component": "MANDATORY", "age_from": 25, "age_to": 64,
                      "employee_pct": "60.0", "employer_pct": "40.0"}]}
    okay, idx = _validate_bvg_scheme_employer_share(bad)
    assert okay is False and idx == 0
    # The real enforcement is at scheme validation (create/update): the payload
    # is refused, so a below-50% plan can never reach a calculation.
    with pytest.raises(Exception) as exc:
        validate_scheme_rules("BVG_PLAN", {
            "entry_rules": {}, "insured_salary_def": "annual",
            "coordination": {"mode": "STATUTORY"},
            "bands": [{"component": "MANDATORY", "age_from": 25, "age_to": 64,
                       "employee_pct": "60.0", "employer_pct": "40.0"}],
        })
    assert "employer share" in str(exc.value)
    # A compliant band (employer >= employee) validates cleanly.
    validate_scheme_rules("BVG_PLAN", {
        "entry_rules": {}, "insured_salary_def": "annual",
        "coordination": {"mode": "STATUTORY"},
        "bands": [{"component": "MANDATORY", "age_from": 25, "age_to": 64,
                   "employee_pct": "5.0", "employer_pct": "5.0"}],
    })


# ── CH Step 9: UVG (accident insurance) — BU employer-only, NBU split ────────

_BASE_CLASSIFICATION = {CH_AHV: {"base_salary": True}, CH_IV: {"base_salary": True},
                        CH_EO: {"base_salary": True}, CH_ALV: {"base_salary": True},
                        CH_UVG: {"base_salary": True}}


def _uvg_ctx(ktg_classified=False, **kwargs):
    """A full context with a real classified earning base (base_salary 10000).
    When ktg_classified is set, CH_KTG is also classified so a KTG policy's own
    base resolves (otherwise the missing-classification guard rightly blocks)."""
    kwargs.setdefault("earnings", {"base_salary": Decimal("10000")})
    if "classification" not in kwargs:
        classification = dict(_BASE_CLASSIFICATION)
        if ktg_classified:
            classification[CH_KTG] = {"base_salary": True}
        kwargs["classification"] = classification
    return _full_ctx(**kwargs)


def test_uvg_bu_is_employer_only():
    # At 7.5 h/week NBU does not apply, so the ONLY UVG item is the employer's
    # BU premium on the risk class rate; the employee never pays BU.
    ctx = _uvg_ctx(weekly_hours="7.5")
    out = calculate(ctx)
    assert out["ch_uvg_bu_employer"] == Decimal("30.00")    # 10000 * 0.3%
    assert out["ch_uvg_nbu_employee"] == Decimal("0")
    assert out["ch_uvg_nbu_employer"] == Decimal("0")
    assert out["ch_uvg_employee"] == Decimal("0")
    assert out["ch_uvg_employer"] == Decimal("30.00")
    obligations = {l["obligation"] for l in out["ch_calculation_trace"]["lines"]}
    assert "ch_uvg_bu" in obligations
    assert "ch_uvg_nbu" not in obligations


def test_uvg_nbu_weekly_hours_75h_vs_9h():
    # NBU applies only when ch_weekly_hours meets the pack minimum (8 h/week):
    # 7.5 h -> BU only; 9 h -> NBU total (0.9%) split employee 0.45/employer 0.45.
    low = calculate(_uvg_ctx(weekly_hours="7.5"))
    high = calculate(_uvg_ctx(weekly_hours="9"))
    assert low["ch_uvg_nbu_employee"] == Decimal("0")
    assert low["ch_uvg_nbu_employer"] == Decimal("0")
    assert high["ch_uvg_nbu_employee"] == Decimal("45.00")
    assert high["ch_uvg_nbu_employer"] == Decimal("45.00")
    # BU is identical either way — NBU never touches the BU premium
    assert low["ch_uvg_bu_employer"] == high["ch_uvg_bu_employer"] == Decimal("30.00")
    # CH_UVG withheld accumulator only carries the shares actually charged
    assert low["ch_calculation_trace"]["accumulators_after"][CH_UVG]["withheld"] == "30"
    assert high["ch_calculation_trace"]["accumulators_after"][CH_UVG]["withheld"] == "120"


def test_uvg_insurer_specific_risk_rates():
    # Two policies from different insurers, same base (10000) and risk class
    # code, different rates: the amounts follow the assigned policy only.
    policy_a = {"insurer": "INSTITUTION-A", "risk_classes": [
        {"code": "A1", "bu_employer_pct": "0.2", "nbu_pct": "0.6", "nbu_employee_share_pct": "0.3"}]}
    policy_b = {"insurer": "INSTITUTION-B", "risk_classes": [
        {"code": "A1", "bu_employer_pct": "0.5", "nbu_pct": "1.4", "nbu_employee_share_pct": "0.7"}]}
    out_a = calculate(_uvg_ctx(uvg_rules=policy_a))
    out_b = calculate(_uvg_ctx(uvg_rules=policy_b))
    assert out_a["ch_uvg_bu_employer"] == Decimal("20.00")   # 10000 * 0.2%
    assert out_a["ch_uvg_nbu_employee"] == Decimal("30.00")  # 10000 * 0.3%
    assert out_a["ch_uvg_nbu_employer"] == Decimal("30.00")  # 10000 * 0.3%
    assert out_b["ch_uvg_bu_employer"] == Decimal("50.00")   # 10000 * 0.5%
    assert out_b["ch_uvg_nbu_employee"] == Decimal("70.00")  # 10000 * 0.7%
    assert out_b["ch_uvg_nbu_employer"] == Decimal("70.00")  # 10000 * (1.4-0.7)%
    # The trace line carries the insurer's scope, not a federal source
    bu_scope = {l["scope_id"] for l in out_a["ch_calculation_trace"]["lines"]
                if l["obligation"] == "ch_uvg_bu"}
    assert bu_scope == {"scheme:uvg_policy:3"}


def test_uvg_ceiling_caps_insured_earnings():
    # CH_UVG accumulator near the ceiling: only the remaining allowance is
    # insured, so BU and NBU shrink this period (no catch-up beyond the cap).
    ytd = {CH_UVG: {"wages": Decimal("148000"), "withheld": Decimal("1000"), "recorded": True}}
    out = calculate(_uvg_ctx(ytd=ytd))
    # remaining allowance = 148200 - 148000 = 200
    assert out["ch_uvg_insurable"] == Decimal("200.00")
    assert out["ch_uvg_bu_employer"] == Decimal("0.60")     # 200 * 0.30%
    assert out["ch_uvg_nbu_employee"] == Decimal("0.90")    # 200 * 0.45%
    assert out["ch_uvg_nbu_employer"] == Decimal("0.90")
    trace = out["ch_calculation_trace"]
    assert trace["accumulators_before"][CH_UVG]["wages"] == "148000"
    assert trace["accumulators_after"][CH_UVG]["wages"] == "148200"
    bu_line = [l for l in trace["lines"] if l["obligation"] == "ch_uvg_bu"][0]
    assert bu_line["base"] == "200.00" and bu_line["cap"] == "148200.00"


def test_uvg_missing_policy_blocks():
    ctx = _full_ctx()
    ctx.ch_uvg_policy_scheme_id = None
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_uvg_policy:not_assigned" in str(exc.value.key)


def test_uvg_policy_without_rules_blocks():
    ctx = _full_ctx()
    ctx.ch_uvg_scheme_rules = None
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_uvg_policy:rules_missing" in str(exc.value.key)


def test_uvg_unknown_risk_class_blocks():
    ctx = _full_ctx(uvg_risk_class="B9")
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_uvg_risk_class:not_found" in str(exc.value.key)


def test_uvg_missing_weekly_hours_blocks():
    ctx = _full_ctx()
    ctx.ch_weekly_hours = None
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_weekly_hours" in str(exc.value.key)


# ── CH Step 9: KTG (sickness) — elected policy on its own classified base ────

def test_ktg_not_elected_no_contribution():
    out = calculate(_uvg_ctx())
    assert out["ch_ktg_employee"] == Decimal("0")
    assert out["ch_ktg_employer"] == Decimal("0")
    obligations = {l["obligation"] for l in out["ch_calculation_trace"]["lines"]}
    assert "ch_ktg" not in obligations


def test_ktg_elected_contribution_and_split():
    # KTG on its own classified base (10000): employee 0.4%, employer 0.8% of
    # the 1.2% total policy rate.
    ctx = _uvg_ctx(ktg_classified=True, ktg_rules={"rate_pct": "1.2", "employee_share_pct": "0.4",
                              "base_def": "AHV base"})
    out = calculate(ctx)
    assert out["ch_ktg_employee"] == Decimal("40.00")
    assert out["ch_ktg_employer"] == Decimal("80.00")
    ktg_lines = [l for l in out["ch_calculation_trace"]["lines"] if l["obligation"] == "ch_ktg"]
    assert len(ktg_lines) == 2
    assert {l["scope_id"] for l in ktg_lines} == {"scheme:ktg_policy:4"}
    acc = out["ch_calculation_trace"]["accumulators_after"][CH_KTG]
    assert acc["wages"] == "10000.00"
    assert acc["withheld"] == "120"


def test_ktg_base_differs_from_uvg():
    # KTG is charged on its OWN classified base: overtime is UVG-insurable but
    # not KTG-insurable, so the two bases differ for the same period.
    classification = {
        CH_AHV: {"base_salary": True, "overtime": True},
        CH_IV: {"base_salary": True, "overtime": True},
        CH_EO: {"base_salary": True, "overtime": True},
        CH_ALV: {"base_salary": True, "overtime": True},
        CH_UVG: {"base_salary": True, "overtime": True},
        CH_KTG: {"base_salary": True, "overtime": False},
    }
    ctx = _full_ctx(earnings={"base_salary": Decimal("10000"), "overtime": Decimal("1000")},
                    classification=classification,
                    ktg_rules={"rate_pct": "1.0", "employee_share_pct": "0.5", "base_def": "base salary"})
    out = calculate(ctx)
    assert out["ch_uvg_insurable"] == Decimal("11000.00")
    assert out["ch_ktg_employee"] == Decimal("50.00")    # 10000 * 0.5%
    assert out["ch_ktg_employer"] == Decimal("50.00")
    # the KTG trace line sits on KTG's own base, distinct from the UVG base
    ktg_lines = [l for l in out["ch_calculation_trace"]["lines"] if l["obligation"] == "ch_ktg"]
    assert {l["base"] for l in ktg_lines} == {"10000.00"}
    uvgb_lines = [l for l in out["ch_calculation_trace"]["lines"] if l["obligation"] == "ch_uvg_bu"]
    assert {l["base"] for l in uvgb_lines} == {"11000.00"}


def test_ktg_assigned_without_rate_blocks():
    ctx = _uvg_ctx(ktg_classified=True, ktg_rules={})
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_ktg_policy:rate_missing" in str(exc.value.key)


def test_ktg_assigned_without_share_blocks():
    ctx = _uvg_ctx(ktg_classified=True, ktg_rules={"rate_pct": "1.2"})
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_ktg_policy:share_missing" in str(exc.value.key)


# ── CH Step 10: QST (Quellensteuer) — canton model + tariff row from context ─

def _qst_ctx(earnings=None, model="MONTHLY", rate=None, aperiodic_rate=None, subject="YES",
             treatment=None, classification=None, extra_classification=None, canton="CH-ZH",
             qst_children=1, church_tax=False, tariff_code="A0N", tariff_file_id=17,
             file_sha256="sha-mont-test", multiple=False, other_pct=None, **kwargs):
    """QST-liable context. All earnings are CH_QST-classified by default and
    PERIODIC by default; the aperiodic test flips the treatment of the bonus /
    13th so the engine sees an APERIODIC determination income. The tariff ROW
    (rate_pct / min_tax / row_id) is passed in exactly as the service's
    lookup_qst_rate hands it to the engine."""
    earnings = earnings if earnings is not None else {"base_salary": Decimal("10000")}
    if classification is None:
        merged = dict(_BASE_CLASSIFICATION)
        for obl in (CH_AHV, CH_IV, CH_EO, CH_ALV, CH_UVG):
            merged.setdefault(obl, {}).update({etype: True for etype in earnings})
    else:
        merged = dict(classification)
        merged.setdefault(CH_UVG, {"base_salary": True})
    merged.setdefault(CH_QST, {etype: True for etype in earnings})
    if extra_classification:
        merged.update(extra_classification)
    ctx = _uvg_ctx(earnings=earnings, classification=merged, **kwargs)
    ctx.ch_qst_subject = subject
    ctx.ch_qst_canton = canton
    ctx.ch_qst_model = model
    ctx.ch_qst_tariff_file_id = tariff_file_id
    ctx.ch_qst_tariff_file_sha256 = file_sha256
    ctx.ch_qst_tariff_code = tariff_code
    ctx.ch_qst_children = qst_children
    ctx.ch_qst_church_tax = church_tax
    ctx.ch_qst_treatment = dict(treatment) if treatment else {etype: "PERIODIC" for etype in earnings}
    ctx.ch_qst_rate = rate if rate is not None else {"rate_pct": "5.0", "min_tax": None, "row_id": 111}
    if aperiodic_rate is not None:
        ctx.ch_qst_aperiodic_rate = aperiodic_rate
    ctx.ch_multiple_employment = multiple
    ctx.ch_other_employment_pct = other_pct
    return ctx


def test_qst_not_subject_no_tax():
    # ch_qst_subject NO (the default) means the worker is not QST-liable: the
    # engine emits no QST line, no tax, and a trace that says it does not apply.
    out = calculate(_uvg_ctx())
    assert out["ch_qst_total"] == Decimal("0")
    assert out["ch_qst_periodic"] == Decimal("0")
    assert out["ch_qst_model"] is None
    assert out["ch_qst_determination_periodic"] == Decimal("0")
    trace = out["ch_calculation_trace"]
    assert trace["qst"]["applies"] is False
    assert trace["accumulators_after"][CH_QST]["wages"] == "0"
    assert trace["accumulators_after"][CH_QST]["withheld"] == "0"


def test_qst_monthly_periodic_tax():
    # MONTHLY model: QST = 10000 monthly determination income * 5% tariff row.
    ctx = _qst_ctx(rate={"rate_pct": "5.0", "min_tax": None, "row_id": 111})
    out = calculate(ctx)
    assert out["ch_qst_periodic"] == Decimal("500.00")
    assert out["ch_qst_aperiodic"] == Decimal("0")
    assert out["ch_qst_total"] == Decimal("500.00")
    assert out["ch_qst_model"] == "MONTHLY"
    assert out["ch_qst_determination_periodic"] == Decimal("10000.00")
    # QST is an employee withholding — it lands in the employee total
    assert out["ch_employee_total"] == Decimal("1185.00")   # 685 federal + 500 QST
    trace = out["ch_calculation_trace"]
    q = trace["qst"]
    assert q["applies"] is True
    assert q["canton"] == "CH-ZH"
    assert q["model"] == "MONTHLY"
    assert q["tariff_file_id"] == 17
    assert q["file_sha256"] == "sha-mont-test"
    assert q["tariff_code"] == "A0N"
    assert q["children"] == 1
    assert q["church_tax"] is False
    assert q["row_id"] == 111
    assert q["periodic_determination_income"] == "10000.00"
    assert q["aperiodic_determination_income"] == "0.00"
    assert q["min_tax"] is None
    assert q["multiple_employment"] is False
    assert q["combined_determination_income"] is None
    assert q["annual_determination_income"] is None
    acc = trace["accumulators_after"][CH_QST]
    assert acc["wages"] == "10000.00"
    assert acc["withheld"] == "500"
    line = [l for l in trace["lines"] if l["obligation"] == "ch_qst_periodic"][0]
    assert line["base"] == "10000.00"
    assert line["rate_or_rule"] == "0.05"
    assert line["cap"] is None
    assert line["scope_id"] == "qst_tariff:17"


def test_qst_min_tax_floor_applied():
    # The tariff row sets a CHF 50 minimum: 2000 * 2% = 40 < 50, so the floor
    # raises the withholding to the row's minimum tax.
    ctx = _qst_ctx(earnings={"base_salary": Decimal("2000")},
                   rate={"rate_pct": "2.0", "min_tax": "50", "row_id": 111})
    out = calculate(ctx)
    assert out["ch_qst_periodic"] == Decimal("50.00")
    assert out["ch_calculation_trace"]["qst"]["min_tax"] == "50"


def test_qst_bonus_and_thirteenth_aperiodic_separate_rate():
    # Bonus + 13th month are APERIODIC (TaxabilityRule.treatment): taxed on
    # their own combined amount with their OWN tariff row, separate from the
    # periodic salary's row.
    earnings = {"base_salary": Decimal("10000"), "bonus": Decimal("2000"), "thirteen": Decimal("1000")}
    ctx = _qst_ctx(earnings=earnings,
                   treatment={"base_salary": "PERIODIC", "bonus": "APERIODIC", "thirteen": "APERIODIC"},
                   rate={"rate_pct": "5.0", "min_tax": None, "row_id": 111},
                   aperiodic_rate={"rate_pct": "8.0", "min_tax": None, "row_id": 222})
    out = calculate(ctx)
    assert out["ch_qst_periodic"] == Decimal("500.00")      # 10000 * 5%
    assert out["ch_qst_aperiodic"] == Decimal("240.00")     # (2000 + 1000) * 8%
    assert out["ch_qst_total"] == Decimal("740.00")
    trace = out["ch_calculation_trace"]
    obligations = {l["obligation"] for l in trace["lines"]}
    assert "ch_qst_periodic" in obligations
    assert "ch_qst_aperiodic" in obligations
    ap = [l for l in trace["lines"] if l["obligation"] == "ch_qst_aperiodic"][0]
    assert ap["base"] == "3000.00"
    assert ap["rate_or_rule"] == "0.08"
    assert ap["scope_id"] == "qst_tariff:17"
    q = trace["qst"]
    assert q["aperiodic_row_id"] == 222
    assert q["aperiodic_rate_pct"] == "8.0"
    assert q["aperiodic_determination_income"] == "3000.00"


def test_qst_annual_model_arithmetic():
    # ANNUAL (Jahresmodell): the 10000 monthly determination income annualises
    # to 120000; 4% annual tariff = 4800 annual tax; back-apportioned /12 = 400
    # monthly withholding. Arithmetic parameters come from content, not the engine.
    ctx = _qst_ctx(model="ANNUAL", canton="CH-VD", tariff_file_id=18, file_sha256="sha-annual-test",
                   rate={"rate_pct": "4.0", "min_tax": None, "row_id": 333})
    out = calculate(ctx)
    assert out["ch_qst_periodic"] == Decimal("400.00")
    assert out["ch_qst_model"] == "ANNUAL"
    assert out["ch_qst_determination_periodic"] == Decimal("10000.00")
    q = out["ch_calculation_trace"]["qst"]
    assert q["canton"] == "CH-VD"
    assert q["annual_determination_income"] == "120000.00"
    assert q["annual_tax"] == "4800.00"


def test_qst_annual_model_pending_g1_sign_off():
    # The annual-model arithmetic is not yet confirmed by the statutory review —
    # the marker lives in the strategy docstring so the gap stays visible.
    assert sw._qst_annual.__doc__ is not None
    assert "PENDING G1 SIGN-OFF" in sw._qst_annual.__doc__


def test_qst_canton_change_at_boundary_no_blended_rate():
    # January under CH-ZH (MONTHLY, file 10, 3.0%) is tariffed by ITS row; the
    # worker moves to CH-VD (ANNUAL, file 11, 4.0%) in February. The February
    # result must come ONLY from the new canton's model/rate row — the old
    # canton's rate is never blended or carried over.
    jan = _qst_ctx(canton="CH-ZH", model="MONTHLY", tariff_file_id=10, file_sha256="sha-z",
                   rate={"rate_pct": "3.0", "min_tax": None, "row_id": 1001})
    feb = _qst_ctx(canton="CH-VD", model="ANNUAL", tariff_file_id=11, file_sha256="sha-vd",
                   rate={"rate_pct": "4.0", "min_tax": None, "row_id": 2002})
    out_jan = calculate(jan)
    out_feb = calculate(feb)
    assert out_jan["ch_qst_periodic"] == Decimal("300.00")   # 10000 * 3%
    assert out_feb["ch_qst_periodic"] == Decimal("400.00")   # annualised 4% -> 400/mo
    q_feb = out_feb["ch_calculation_trace"]["qst"]
    assert q_feb["model"] == "ANNUAL"
    assert q_feb["canton"] == "CH-VD"
    assert q_feb["tariff_file_id"] == 11
    assert q_feb["row_id"] == 2002
    assert q_feb["file_sha256"] == "sha-vd"


def test_qst_superseded_file_not_used_new_period_but_replayable():
    # April runs against ACTIVE file 20 (sha-a, 3.0%). The canton then activates
    # file 21 (sha-b, 3.5%) which SUPERSEDES 20. May must use ONLY the new
    # file's row; April stays replayable because its trace pins file_sha256 and
    # row_id (the engine replays a payslip by those, never by 'latest').
    apr = _qst_ctx(tariff_file_id=20, file_sha256="sha-a", rate={"rate_pct": "3.0", "min_tax": None, "row_id": 401})
    may = _qst_ctx(tariff_file_id=21, file_sha256="sha-b", rate={"rate_pct": "3.5", "min_tax": None, "row_id": 501})
    out_apr = calculate(apr)
    out_may = calculate(may)
    assert out_apr["ch_qst_periodic"] == Decimal("300.00")
    assert out_may["ch_qst_periodic"] == Decimal("350.00")
    for out, f, rid in ((out_apr, "sha-a", 401), (out_may, "sha-b", 501)):
        q = out["ch_calculation_trace"]["qst"]
        assert q["file_sha256"] == f
        assert q["row_id"] == rid


def test_qst_missing_tariff_code_blocks():
    ctx = _qst_ctx(tariff_code=None)
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_qst_tariff_code" in str(exc.value.key)


@pytest.mark.parametrize("subject", ["REVIEW_REQUIRED", None, ""])
def test_qst_review_required_or_unknown_subject_blocks(subject):
    # A review state (or missing) subject never calculates: it BLOCKS with the
    # same key the resolver's ch_qst_subject_review check would raise.
    ctx = _qst_ctx(subject=subject)
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_qst_subject_review" in str(exc.value.key)


def test_qst_multiple_employment_flag_path():
    # Multiple employment (KS 45): the tariff is determined on the worker's
    # TOTAL determination income (combined = own salary / (1 - other share)),
    # while this employer withholds on the salary IT pays. 10000/0.5 = 20000
    # combined for the record; tax stays 10000 * 4% = 400 on the own base.
    ctx = _qst_ctx(rate={"rate_pct": "4.0", "min_tax": None, "row_id": 601},
                   multiple=True, other_pct="0.5")
    out = calculate(ctx)
    assert out["ch_qst_periodic"] == Decimal("400.00")
    q = out["ch_calculation_trace"]["qst"]
    assert q["multiple_employment"] is True
    assert q["other_employment_pct"] == "0.5"
    assert q["combined_determination_income"] == "20000.00"


def test_qst_multiple_employment_missing_share_blocks():
    ctx = _qst_ctx(multiple=True, other_pct=None)
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_other_employment_pct" in str(exc.value.key)


def test_qst_aperiodic_without_rate_row_blocks():
    # A bonus classified APERIODIC needs its OWN tariff row in context — a
    # missing aperiodic row BLOCKS rather than reusing the periodic rate.
    ctx = _qst_ctx(earnings={"base_salary": Decimal("10000"), "bonus": Decimal("1000")},
                   treatment={"base_salary": "PERIODIC", "bonus": "APERIODIC"},
                   rate={"rate_pct": "5.0", "min_tax": None, "row_id": 111})
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_qst_aperiodic_rate" in str(exc.value.key)


def test_ktg_assigned_without_rules_blocks():
    ctx = _uvg_ctx(ktg_classified=True, ktg_rules={"rate_pct": "1.2", "employee_share_pct": "0.4"})
    ctx.ch_ktg_scheme_rules = None
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert "ch_ktg_policy:rules_missing" in str(exc.value.key)
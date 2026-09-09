"""
tests/test_germany_pap_golden_vector.py
-------------------------------------
Phase 8C-3 — coverage for germany_pap_golden_vector.py: the certification
data model (`GermanyPapGoldenVector`) and the exact-comparison mechanism
(`compare_exact`/`all_exact`) used to certify Zoiko's mechanical
reproduction of the official BMF PAP against BMF's own published
check-table values.

Deliberately synthetic throughout (no real BMF-derived content is
embedded in this committed suite, per the standing project convention —
see the module docstring). The actual certification run against the
real, independently-verified `Lohnsteuer2026.xml` (31 official
check-table rows, all 6 tax classes, both the "Allgemeine" and
"Besondere" tables) was performed as a one-off, non-committed session
script; its full results are recorded in
docs/PHASE_8C_3_GERMANY_PAP_GOLDEN_VECTOR_CERTIFICATION_REPORT.md.
"""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.germany_pap.golden_vector import (
    GermanyPapGoldenVector,
    GoldenVectorComparison,
    all_exact,
    compare_exact,
)


def _synthetic_vector(**expected_outputs_kwargs):
    expected_outputs = {name: Decimal(value) for name, value in expected_outputs_kwargs.items()}
    return GermanyPapGoldenVector(
        vector_id="SYNTH-001",
        source_document="synthetic-test-fixture, not a real BMF publication",
        source_page=0,
        source_hash_sha256="0" * 64,
        description="Synthetic vector for mechanics-only testing",
        inputs={"STKL": 1, "RE4": Decimal("2000000")},
        expected_outputs=expected_outputs,
    )


# ── GermanyPapGoldenVector: data model ──────────────────────────────────

def test_golden_vector_is_frozen_and_carries_full_provenance():
    vector = _synthetic_vector(LSTLZZ="38000")
    assert vector.vector_id == "SYNTH-001"
    assert vector.source_page == 0
    assert len(vector.source_hash_sha256) == 64
    assert vector.inputs["STKL"] == 1
    with pytest.raises(Exception):
        vector.vector_id = "changed"  # frozen dataclass


def test_golden_vector_expected_outputs_are_decimal():
    vector = _synthetic_vector(LSTLZZ="38000")
    assert isinstance(vector.expected_outputs["LSTLZZ"], Decimal)


# ── compare_exact: exact Decimal comparison, no tolerance ───────────────

def test_compare_exact_reports_exact_match():
    comparisons = compare_exact({"LSTLZZ": Decimal("38000")}, {"LSTLZZ": Decimal("38000")})
    assert len(comparisons) == 1
    assert isinstance(comparisons[0], GoldenVectorComparison)
    assert comparisons[0].exact_match is True
    assert comparisons[0].actual == Decimal("38000")
    assert comparisons[0].expected == Decimal("38000")


def test_compare_exact_reports_mismatch_for_any_difference():
    comparisons = compare_exact({"LSTLZZ": Decimal("38001")}, {"LSTLZZ": Decimal("38000")})
    assert comparisons[0].exact_match is False


def test_compare_exact_uses_no_tolerance_even_for_one_cent():
    """The phase's mismatch policy explicitly forbids tolerance/approximation
    — a 1-unit difference must never be treated as a pass."""
    comparisons = compare_exact({"LSTLZZ": Decimal("38000.01")}, {"LSTLZZ": Decimal("38000.00")})
    assert comparisons[0].exact_match is False


def test_compare_exact_is_scale_insensitive_but_value_exact():
    """Decimal.compare treats 380 and 380.00 as numerically equal (scale
    does not affect exactness) — this is intentional: the certification
    cares about the numeric value, not the string representation."""
    comparisons = compare_exact({"LSTLZZ": Decimal("380.00")}, {"LSTLZZ": Decimal("380")})
    assert comparisons[0].exact_match is True


def test_compare_exact_raises_if_expected_output_never_produced():
    with pytest.raises(KeyError):
        compare_exact({}, {"LSTLZZ": Decimal("38000")})


def test_compare_exact_handles_multiple_outputs_independently():
    comparisons = compare_exact(
        {"LSTLZZ": Decimal("38000"), "SOLZLZZ": Decimal("0")},
        {"LSTLZZ": Decimal("38000"), "SOLZLZZ": Decimal("1")},
    )
    by_name = {c.output_name: c for c in comparisons}
    assert by_name["LSTLZZ"].exact_match is True
    assert by_name["SOLZLZZ"].exact_match is False


# ── all_exact: aggregate pass/fail ───────────────────────────────────────

def test_all_exact_true_only_when_every_comparison_matches():
    all_match = compare_exact({"LSTLZZ": Decimal("1")}, {"LSTLZZ": Decimal("1")})
    assert all_exact(all_match) is True

    one_mismatch = compare_exact({"LSTLZZ": Decimal("1"), "BK": Decimal("2")}, {"LSTLZZ": Decimal("1"), "BK": Decimal("3")})
    assert all_exact(one_mismatch) is False


def test_all_exact_true_for_empty_comparison_list():
    assert all_exact([]) is True


# ── Production-safety: this module is a standalone certification tool ──

def test_module_is_not_imported_by_production_calculation_path():
    """germany.py (the one registered DE entry point) and
    germany_pap.py's resolve_pap_executor() must have zero knowledge of
    this certification-only module."""
    import inspect

    from app.modules.payroll.engine.countries import germany
    from app.modules.payroll.engine.germany_pap import core

    assert "germany_pap_golden_vector" not in inspect.getsource(germany)
    assert "germany_pap_golden_vector" not in inspect.getsource(core)

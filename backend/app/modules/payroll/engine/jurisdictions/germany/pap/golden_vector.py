"""
modules/payroll/engine/jurisdictions/germany/pap/golden_vector.py
------------------------------------------------------------------
Phase 8C-3 — the data model and exact-comparison mechanics used to
certify Zoiko's mechanical reproduction of the official BMF 2026 PAP
against BMF's own published check-table values (Programmablaufplan
2026, Anlage 1, "Allgemeine maschinelle Jahreslohnsteuer 2026" and
"Besondere maschinelle Jahreslohnsteuer 2026" — Prüftabellen, pp. 39-40).

(Relocated from `engine/countries/germany_pap_golden_vector.py` in Phase
8E-0A into the `engine/germany_pap/` subsystem package.)

LAYERING: this module knows nothing about Zoiko payroll data
(EmployeeStatutoryProfile, PayrollContext) — it only knows the PAP's own
raw field names, exactly like `germany_pap_interpreter.py`. It is a
CERTIFICATION TOOL, not a production code path: nothing here is
imported by `germany.py`, `germany_pap.py`'s `resolve_pap_executor()`,
or `germany_pap_adapter.py`'s `InterpreterPapExecutor`.

DELIBERATELY NOT PRE-POPULATED with real BMF check-table figures: per
the standing project convention (Phases 8C-1/8C-2), no real BMF-derived
content is embedded in committed source — this module is only the
generic data model and the exact-comparison mechanism. The actual 31
golden vectors run against the real, independently-verified
`Lohnsteuer2026.xml` this phase are a one-off, non-committed session
script; their full results (inputs, expected, actual, exact match) are
recorded in docs/PHASE_8C_3_GERMANY_PAP_GOLDEN_VECTOR_CERTIFICATION_REPORT.md,
consistent with the same pattern used for the real-artifact runs in the
Phase 8C-1/8C-2 reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

# Phase 8BG — governance classification for a golden vector's evidentiary
# weight. A vector's `source_classification` is the ONLY thing this module
# (or the release-governance gate in service.py) trusts to decide whether
# a vector can ever count as authoritative statutory validation evidence.
# Engineering test fixtures must always be SYNTHETIC; only a vector
# actually transcribed from a published BMF Prüftabelle may be
# AUTHORITATIVE_BMF. Nothing in this codebase upgrades a vector from one
# classification to the other automatically — it is set once, by
# whoever constructs the vector, and is part of what the release gate
# (service.record_pap_release_golden_vectors) checks before accepting it.
SYNTHETIC = "SYNTHETIC"
AUTHORITATIVE_BMF = "AUTHORITATIVE_BMF"
_VALID_CLASSIFICATIONS = frozenset({SYNTHETIC, AUTHORITATIVE_BMF})


@dataclass(frozen=True)
class GermanyPapGoldenVector:
    """One official BMF check-table row, with full source provenance and
    every PAP input the row implies (never relying on interpreter/adapter
    defaults for a certification vector — the whole point is to prove the
    mechanical result against a fully-specified, independently-traceable
    input set).

    `source_classification` must be exactly one of SYNTHETIC or
    AUTHORITATIVE_BMF (enforced in `__post_init__`) — this is the field
    the production release gate uses to refuse engineering/test data as
    statutory evidence; see service.record_pap_release_golden_vectors."""

    vector_id: str
    source_document: str
    source_page: int
    source_hash_sha256: str
    description: str
    inputs: Dict[str, object]
    expected_outputs: Dict[str, Decimal]
    source_classification: str

    def __post_init__(self) -> None:
        if self.source_classification not in _VALID_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid source_classification {self.source_classification!r} for golden vector "
                f"{self.vector_id!r}: must be one of {sorted(_VALID_CLASSIFICATIONS)}."
            )


@dataclass(frozen=True)
class GoldenVectorComparison:
    output_name: str
    expected: Decimal
    actual: Decimal
    exact_match: bool


def compare_exact(actual_outputs: Dict[str, Decimal], expected_outputs: Dict[str, Decimal]) -> list:
    """Exact `Decimal` comparison of every expected output against the
    corresponding actual output — no tolerance, no rounding, no
    approximation, per the certification phase's explicit mismatch
    policy. Raises `KeyError` if an expected output was never produced
    (fail closed rather than silently skip it)."""
    results = []
    for name, expected in expected_outputs.items():
        actual = Decimal(actual_outputs[name])
        results.append(
            GoldenVectorComparison(
                output_name=name,
                expected=expected,
                actual=actual,
                exact_match=actual.compare(expected) == 0,
            )
        )
    return results


def all_exact(comparisons: list) -> bool:
    return all(c.exact_match for c in comparisons)

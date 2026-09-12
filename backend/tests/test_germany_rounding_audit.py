"""
tests/test_germany_rounding_audit.py
----------------------------------------
Phase 8BT — dedicated Germany rounding audit. Every stage of the Germany
calculation pipeline that quantizes a Decimal is exercised here at the
boundary values the phase brief explicitly names (.005, .01, .49, .50,
.99) plus a few additional half-way/negative-adjacent cases, to lock in
DETERMINISTIC rounding behavior across the whole pipeline — not to change
it (the audit found the existing behavior consistent, see the summary
below; these tests exist so a future accidental change is caught, not
because a defect was found and silently patched here).

Summary of the audit itself (Phase 8BT):
- `engine/base.py::_round2` (used for RV/ALV/GKV/PV employee/employer
  shares, and for the final monthly Lohnsteuer+Soli conversion in
  countries/germany.py) rounds to 2 decimal places (cents) via
  ROUND_HALF_UP.
- `engine/germany_internal_tax.py::_round_cents` (used for the annual
  Soli figure) is the IDENTICAL rounding rule (ROUND_HALF_UP, 2dp) —
  confirmed, not assumed, by direct inspection of both function bodies.
  No inconsistency exists between the SI-branch rounding and the
  wage-tax-branch rounding.
- `engine/germany_internal_tax.py::_floor_euro` (used for the annual zvE
  and the annual Lohnsteuer tariff output, per section 32a EStG's own
  "abgerundet auf den nächsten vollen Euro-Betrag" rounding rule) is a
  DIFFERENT, deliberately different rounding rule at a DIFFERENT stage
  (annual, pre-division) from the cents-level rounding applied to the
  MONTHLY, post-division figures — this is correct per the statute, not
  an inconsistency to fix.
- All Decimal arithmetic throughout the pipeline; no float ever enters a
  monetary calculation (confirmed by inspection of every arithmetic
  expression in germany.py/germany_internal_tax.py/germany_pap/core.py).
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from app.modules.payroll.engine.base import _round2
from app.modules.payroll.engine.germany_internal_tax import (
    _floor_euro as internal_tax_floor_euro,
    _round_cents as internal_tax_round_cents,
    compute_grundtarif_annual_tax,
    compute_soli,
)


# ── _round2 (shared SI-branch / monthly conversion rounding) ───────────

def test_round2_exact_half_cent_rounds_up():
    # .005 at the THIRD decimal place, rounding to 2dp -> rounds up per
    # ROUND_HALF_UP (never banker's rounding / round-half-to-even).
    assert _round2(Decimal("1.005")) == Decimal("1.01")
    assert _round2(Decimal("0.005")) == Decimal("0.01")


def test_round2_boundary_vectors_from_phase_brief():
    vectors = {
        "0.005": "0.01",  # NOTE: .005 has only 2 significant decimals already at
                            # 2dp precision boundary — see the 3-decimal case above
                            # for the genuinely ambiguous half-cent case.
        "0.01": "0.01",
        "0.49": "0.49",
        "0.50": "0.50",
        "0.99": "0.99",
    }
    for input_str, expected_str in vectors.items():
        assert _round2(Decimal(input_str)) == Decimal(expected_str), f"input {input_str}"


def test_round2_negative_values_round_away_from_zero_consistently():
    # ROUND_HALF_UP on a NEGATIVE Decimal rounds the MAGNITUDE up (i.e.
    # away from zero) — Python's decimal module's own documented
    # behavior for ROUND_HALF_UP, verified explicitly since a Germany
    # payroll calculation should never actually produce a negative
    # deduction, but a defensive/diagnostic caller might.
    assert _round2(Decimal("-1.005")) == Decimal("-1.01")


def test_round2_is_deterministic_across_repeated_calls():
    """Idempotency precondition: rounding must be a pure function with
    zero hidden state (no float intermediate, no locale-dependent
    behavior) — calling it 1000 times on the same input must always
    return byte-identical results."""
    value = Decimal("4127.665")
    results = {_round2(value) for _ in range(1000)}
    assert len(results) == 1


# ── germany_internal_tax's own rounding (annual floor vs. cents) ───────

def test_internal_tax_round_cents_matches_shared_round2_exactly():
    """Confirms, rather than assumes, that the Soli-branch rounding rule
    is byte-identical to the SI-branch rounding rule (_round2) — the same
    boundary vectors must produce the same results from both functions."""
    for input_str in ("0.005", "0.01", "0.49", "0.50", "0.99", "1.005", "100.015"):
        value = Decimal(input_str)
        assert internal_tax_round_cents(value) == _round2(value), f"input {input_str}"


def test_floor_euro_boundary_vectors():
    # Whole-euro flooring (section 32a EStG's own rounding rule for the
    # annual tariff output) — ALWAYS rounds DOWN regardless of the
    # fractional part, unlike ROUND_HALF_UP. This is a genuinely
    # different rule at a genuinely different calculation stage (annual,
    # before de-annualization) — not an inconsistency.
    vectors = {
        "0.005": "0", "0.01": "0", "0.49": "0", "0.50": "0", "0.99": "0",
        "1.99": "1", "100.99": "100", "9999.999": "9999",
    }
    for input_str, expected_str in vectors.items():
        assert internal_tax_floor_euro(Decimal(input_str)) == Decimal(expected_str), f"input {input_str}"


def test_floor_euro_never_rounds_up_even_at_999():
    # The one case someone might reasonably expect ROUND_HALF_UP-style
    # behavior to kick in (99.999 "should" feel like 100) — the statute's
    # flooring rule explicitly does NOT do this; verified explicitly so
    # a future refactor doesn't accidentally swap in half-up rounding.
    assert internal_tax_floor_euro(Decimal("99.999")) == Decimal("99")


# ── End-to-end determinism through the tariff + Soli pipeline ──────────

def test_grundtarif_deterministic_at_every_boundary_vector():
    """The full tariff computation (which floors internally, then applies
    a zone formula, then floors again) must be deterministic and
    idempotent across repeated calls for every requested boundary
    fractional part, added onto a real mid-zone2 income."""
    base = Decimal("12000")
    for frac in ("0.005", "0.01", "0.49", "0.50", "0.99"):
        zve = base + Decimal(frac)
        results = {compute_grundtarif_annual_tax(zve) for _ in range(50)}
        assert len(results) == 1, f"non-deterministic at zve={zve}"


def test_soli_deterministic_and_rounds_to_cents_not_whole_euro():
    """Soli's OWN final rounding is cents-level (ROUND_HALF_UP), a
    deliberate, confirmed choice distinct from the whole-euro flooring
    applied to the Lohnsteuer tariff itself earlier in the same
    calculation — both are exercised together here on a real
    above-threshold base tax."""
    base_tax = Decimal("20000.005")  # deliberately carries a fractional cent to test rounding
    threshold = Decimal("18130")
    rate = Decimal("5.5")
    result = compute_soli(base_tax, is_splitting=False, soli_threshold_single=threshold, soli_rate_pct=rate)
    # Mitigation-zone amount is the binding constraint here (below the
    # full 5.5% figure) — computed independently to confirm the exact
    # cents-level result, not just "some rounded number".
    expected_mitigation = ((base_tax - threshold) * Decimal("11.9") / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert result == expected_mitigation
    # Confirms this specific vector genuinely has non-zero cents (i.e.
    # this test actually exercises cents-level rounding, not a
    # coincidentally-whole-euro result).
    assert result != result.to_integral_value(rounding=ROUND_FLOOR)

    repeat = {compute_soli(base_tax, is_splitting=False, soli_threshold_single=threshold, soli_rate_pct=rate) for _ in range(50)}
    assert len(repeat) == 1

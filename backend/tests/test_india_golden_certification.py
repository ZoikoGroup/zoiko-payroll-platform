"""
tests/test_india_golden_certification.py
--------------------------------------------
ZP-TAX-IN-2026-27-001 §21's golden test IDs that do NOT fit the JSON
golden-fixture harness shape (tests/fixtures/in_golden/, covered by
tests/test_in_golden.py instead) — gap-closure Phase F, 2026-09-11.

Two distinct reasons a case lands here instead of a JSON fixture, each
documented on the relevant test below:

1. IN-TAX-002/003/004 are specified by the document as *annual* figures
   that aren't evenly divisible by 12 once the standard deduction is
   added back — routing them through the JSON harness's monthly-gross
   -> x12 pipeline would introduce rounding noise unrelated to the tax
   logic itself. These call `_calculate_annual_tax_in` directly (the
   same function `india.py::calculate()` calls) with the document's own
   exact annual figures.
2. IN-WAGE-001/IN-CAP-001/IN-RETRO-001/IN-SOURCE-001 are behavioral/
   integration assertions, not numeric golden vectors the JSON harness's
   `expected: {field: Decimal}` shape can express.

Also includes a Phase G verification test proving the new EPF/ESI/PT
TaxabilityRule-backed wage-base classification is a genuine zero-
behavior-change no-op for every org until explicitly configured (the
same non-negotiable constraint Phase B's Code Wages rewrite proved).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.india import (
    _calculate_annual_tax_in, _calculate_code_wages, _classify_wage_base,
)
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.hmrc_golden_harness import GoldenSlab


_NEW_REGIME_SLABS = [
    GoldenSlab(min_amount=Decimal("0"), max_amount=Decimal("400000"), rate_pct=Decimal("0")),
    GoldenSlab(min_amount=Decimal("400000"), max_amount=Decimal("800000"), rate_pct=Decimal("5")),
    GoldenSlab(min_amount=Decimal("800000"), max_amount=Decimal("1200000"), rate_pct=Decimal("10")),
    GoldenSlab(min_amount=Decimal("1200000"), max_amount=Decimal("1600000"), rate_pct=Decimal("15")),
    GoldenSlab(min_amount=Decimal("1600000"), max_amount=Decimal("2000000"), rate_pct=Decimal("20")),
    GoldenSlab(min_amount=Decimal("2000000"), max_amount=Decimal("2400000"), rate_pct=Decimal("25")),
    GoldenSlab(min_amount=Decimal("2400000"), max_amount=None, rate_pct=Decimal("30")),
]
_OLD_REGIME_SLABS = [
    GoldenSlab(min_amount=Decimal("0"), max_amount=Decimal("250000"), rate_pct=Decimal("0")),
    GoldenSlab(min_amount=Decimal("250000"), max_amount=Decimal("500000"), rate_pct=Decimal("5")),
    GoldenSlab(min_amount=Decimal("500000"), max_amount=Decimal("1000000"), rate_pct=Decimal("20")),
    GoldenSlab(min_amount=Decimal("1000000"), max_amount=None, rate_pct=Decimal("30")),
]


def test_in_tax_002_new_regime_marginal_relief():
    """IN-TAX-002: New Regime, taxable ₹1,250,000. Pre-relief bracket tax
    = 20,000 (4-8L@5%) + 40,000 (8-12L@10%) + 7,500 (12-12.5L@15%) =
    ₹67,500 — matches the doc's own stated 'pre-relief tax 67,500'.
    Marginal relief caps (tax) at (excess income above the rebate limit)
    = 1,250,000 - 1,200,000 = ₹50,000 — matches the doc's own stated
    'relief reduces to 50,000'. Cess = 4% of 50,000 = ₹2,000 — matches
    the doc's own stated 'cess 2,000'. Total = 52,000 — matches the
    doc's own stated 'total 52,000'.

    annual_gross is derived as taxable + standard_deduction =
    1,250,000 + 75,000 = 1,325,000 — an annual figure the JSON harness's
    monthly-gross pipeline can't represent exactly (1,325,000/12 is a
    repeating decimal), so this calls the real annual-tax function
    directly instead."""
    result = _calculate_annual_tax_in(
        annual_gross=Decimal("1325000"), slabs=_NEW_REGIME_SLABS, rate_map={}, tax_regime="New",
    )
    assert result["annual_tax"] == Decimal("50000")
    assert result["annual_surcharge"] == Decimal("0")
    assert result["annual_cess"] == Decimal("2000.00")
    assert result["annual_net_liability"] == Decimal("52000.00")


def test_in_tax_003_old_regime_non_senior_no_surcharge():
    """IN-TAX-003: Old Regime, non-senior, taxable ₹1,500,000, no
    surcharge threshold crossed. Bracket tax = 12,500 (2.5-5L@5%) +
    100,000 (5-10L@20%) + 150,000 (10-15L@30%) = ₹262,500 — matches the
    doc's own stated 'tax 262,500'. Marginal relief doesn't reduce this
    (income far exceeds tax at every crossed threshold). Cess = 4% of
    262,500 = ₹10,500 — matches the doc's own stated 'cess 10,500'.
    Total = 273,000 — matches the doc's own stated 'total 273,000'.

    annual_gross = taxable + standard_deduction_old = 1,500,000 +
    50,000 = 1,550,000 — again not evenly divisible by 12, so this calls
    the annual-tax function directly (see test_in_tax_002 above for the
    same rationale)."""
    result = _calculate_annual_tax_in(
        annual_gross=Decimal("1550000"), slabs=_OLD_REGIME_SLABS, rate_map={}, tax_regime="Old",
    )
    assert result["annual_tax"] == Decimal("262500")
    assert result["annual_surcharge"] == Decimal("0")
    assert result["annual_cess"] == Decimal("10500.00")
    assert result["annual_net_liability"] == Decimal("273000.00")


def test_in_tax_004_pt_reduces_old_regime_but_not_new_regime_taxable():
    """IN-TAX-004: 'same PT input, new regime doesn't reduce taxable
    salary, old regime does' (§4.2's 'critical regime separation',
    AC-08) — a behavioral assertion, not a single numeric vector, so
    this directly compares TWO calls per regime (with vs. without the
    same annual_professional_tax) rather than a single golden figure.

    New Regime: identical annual_gross (₹1,500,000) with
    annual_professional_tax=24,000 vs. 0 must produce the EXACT SAME
    annual_tax (₹93,750) — proving New Regime ignores the PT deduction
    entirely, per §4.2.

    Old Regime: the SAME comparison must produce a STRICTLY LOWER
    annual_tax when professional_tax > 0 (₹240,300 vs. ₹247,500) —
    proving Old Regime's own salary-deduction framework genuinely
    subtracts PT from taxable salary before computing tax."""
    new_with_pt = _calculate_annual_tax_in(
        annual_gross=Decimal("1500000"), slabs=_NEW_REGIME_SLABS, rate_map={}, tax_regime="New",
        annual_professional_tax=Decimal("24000"),
    )
    new_without_pt = _calculate_annual_tax_in(
        annual_gross=Decimal("1500000"), slabs=_NEW_REGIME_SLABS, rate_map={}, tax_regime="New",
        annual_professional_tax=Decimal("0"),
    )
    assert new_with_pt["annual_tax"] == new_without_pt["annual_tax"] == Decimal("93750")

    old_with_pt = _calculate_annual_tax_in(
        annual_gross=Decimal("1500000"), slabs=_OLD_REGIME_SLABS, rate_map={}, tax_regime="Old",
        annual_professional_tax=Decimal("24000"),
    )
    old_without_pt = _calculate_annual_tax_in(
        annual_gross=Decimal("1500000"), slabs=_OLD_REGIME_SLABS, rate_map={}, tax_regime="Old",
        annual_professional_tax=Decimal("0"),
    )
    assert old_with_pt["annual_tax"] == Decimal("240300")
    assert old_without_pt["annual_tax"] == Decimal("247500")
    assert old_with_pt["annual_tax"] < old_without_pt["annual_tax"]


def test_in_wage_001_code_wages_add_back():
    """IN-WAGE-001: remuneration ₹100,000, core wages ₹40,000, excluded
    ₹60,000 -> add-back = max(0, 60,000 - 50%-of-gross(50,000)) =
    ₹10,000 -> statutory wages = 40,000 + 10,000 = ₹50,000 — matches the
    doc's own stated figures exactly.

    Calls `_calculate_code_wages` directly (the real per-payslip
    function india.py::calculate() invokes when the Code Wages switch is
    on) rather than a JSON fixture — the JSON harness only asserts
    `PayrollResult` fields, and the intermediate code-wages figure isn't
    one (it feeds INTO the PF wage base, it isn't itself exposed)."""
    ctx = PayrollContext(gross=Decimal("100000"), basic=Decimal("40000"), hra=Decimal("60000"))
    statutory_wages = _calculate_code_wages(ctx, {})
    assert statutory_wages == Decimal("50000")


def test_in_cap_001_wage_deduction_cap_flags_not_silently_erases():
    """IN-CAP-001: 'deductions exceed 50% wage-period cap -> compliance
    blocker, not silent liability erasure' (§8.3/AC-18). Engineers a
    heavy PF employee rate (60%) so total statutory deductions exceed
    half of gross, and asserts:
      1. `wage_deduction_cap_exceeded` is True (the compliance blocker
         fires) — a boolean PayrollResult field, so this is an ordinary
         pytest assertion rather than a JSON-harness Decimal comparison.
      2. The underlying deduction figures are NOT zeroed/erased to force
         the cap — employee_pf and net_pay still reflect the real
         (uncapped) statutory calculation, i.e. the flag is advisory,
         never a silent recalculation.
    A light-deduction control case (ordinary 12% PF) proves the flag
    does NOT fire when the cap genuinely isn't exceeded."""
    heavy_ctx = PayrollContext(
        gross=Decimal("10000"), basic=Decimal("10000"), country="IN",
        rate_map={"pf": _rate(employee_pct=Decimal("60"), employer_pct=Decimal("12"))},
    )
    heavy_result = calculate_payroll(heavy_ctx, "standard")
    assert heavy_result.wage_deduction_cap_exceeded is True
    # Not erased: the real 60% PF deduction is still the actual figure used.
    assert heavy_result.employee_pf == Decimal("6000.00")
    assert heavy_result.net_pay == Decimal("4000.00")

    light_ctx = PayrollContext(
        gross=Decimal("10000"), basic=Decimal("10000"), country="IN",
        rate_map={"pf": _rate(employee_pct=Decimal("12"), employer_pct=Decimal("12"))},
    )
    light_result = calculate_payroll(light_ctx, "standard")
    assert light_result.wage_deduction_cap_exceeded is False


def _rate(employee_pct=None, employer_pct=None, flat=None):
    from app.modules.payroll.hmrc_golden_harness import GoldenRate
    return GoldenRate(employee_rate_pct=employee_pct, employer_rate_pct=employer_pct, flat_amount=flat)


def test_in_retro_001_historical_payroll_replays_from_original_pack_version(db):
    """IN-RETRO-001: 'retro May 2026 run recalculates against the
    version effective for the original May event, not a later version'
    — proves the SAME generic date-based JurisdictionPack resolution
    mechanism CA's own historical-replay test
    (test_ca_historical_payroll_replays_from_h1_after_h2_is_published in
    tests/test_engine_jurisdiction_db_integration.py) already relies on
    extends correctly to India: it is country-generic
    (resolve_tax_configuration), not CA-specific, so this is a real
    verification (it would have caught a regression), not a rebuild."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import JurisdictionPack

    original = JurisdictionPack(
        pack_id="IN-2026-ORIGINAL-RETRO-TEST", jurisdiction_country="IN", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
    )
    db.add(original)
    db.commit()

    # The original May 2026 payroll run resolves this pack (the only one that exists yet).
    _, _, original_pack = resolve_tax_configuration(db, "IN", state=None, payroll_date=date(2026, 5, 15))
    assert original_pack.pack_id == "IN-2026-ORIGINAL-RETRO-TEST"

    # A later statutory update is published (simulating a mid-year CBDT notification).
    later = JurisdictionPack(
        pack_id="IN-2027-LATER-RETRO-TEST", jurisdiction_country="IN", jurisdiction_state=None,
        pack_type="tax", version="1.0", status="Active",
        effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31),
    )
    db.add(later)
    db.commit()

    # Retroactively re-running the SAME May 2026 event must still resolve the ORIGINAL
    # pack, never the newer one — a retro run keys off the original event's own date.
    replayed_pack = resolve_tax_configuration(db, "IN", state=None, payroll_date=date(2026, 5, 15))[2]
    assert replayed_pack.pack_id == "IN-2026-ORIGINAL-RETRO-TEST"


def test_in_source_001_state_pt_readiness_registry_reflects_source_required(db):
    """IN-SOURCE-001 as literally specified ('mandatory state PT source
    missing/stale at activation -> activation blocked, no zero-tax
    fallback') describes an ENFORCEMENT gate at JurisdictionPack
    activation time. No such gate exists yet — set_jurisdiction_pack_
    status's own maker-checker check (service.py) verifies a distinct
    approver, but never checks StateLocalProgramReadiness.legal_status
    or SourceArtifact presence before allowing Active. Building that
    gate would mean adding a new blocking rule to the pack status-
    transition state machine, which is explicitly out of scope for this
    phase (maker-checker/status-machine changes are reserved for a
    separate pass) — so this test verifies what genuinely exists today
    instead: the StateLocalProgramReadiness registry (§16) correctly
    represents a state/program as SOURCE_REQUIRED (the model's own
    documented default) when no source has been linked, which is the
    data half of what an eventual enforcement gate would need to read.
    See this project's gap-closure report for this disclosed, dormant
    gap — same "registry exists, enforcement is a separate deliberate
    decision" convention as _VALIDATION_ENABLED_COUNTRIES."""
    from app.modules.payroll.models import StateLocalProgramReadiness

    row = StateLocalProgramReadiness(
        jurisdiction_country="IN", jurisdiction_state="Gujarat", program="STATE_PT",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Model default, unconfigured source -> SOURCE_REQUIRED, not APPLICABLE.
    assert row.legal_status == "SOURCE_REQUIRED"
    assert row.source_document_id is None


# ── Phase G: EPF/ESI/PT TaxabilityRule wage-base classification ─────────
# must be a byte-for-byte no-op when unconfigured (every org today) —
# the same non-negotiable constraint Phase B's Code Wages rewrite had to
# satisfy.

def test_epf_base_classification_unconfigured_matches_basic_only_default():
    ctx = PayrollContext(gross=Decimal("50000"), basic=Decimal("30000"), hra=Decimal("15000"), special_allowance=Decimal("5000"))
    assert _classify_wage_base(ctx, {}, default_included={"basic"}) == ctx.basic


def test_esi_and_pt_base_classification_unconfigured_matches_gross():
    ctx = PayrollContext(
        gross=Decimal("50000"), basic=Decimal("20000"), hra=Decimal("10000"),
        special_allowance=Decimal("8000"), overtime=Decimal("2000"), additional_compensation=Decimal("1000"),
    )
    assert _classify_wage_base(ctx, {}, default_included=None) == ctx.gross


def test_epf_esi_pt_classification_overrides_change_the_base_only_when_configured():
    """A configured override DOES change the wage base (proving the
    mechanism is genuinely live, not inert), while every other unrelated
    component still falls back to its default."""
    ctx = PayrollContext(gross=Decimal("50000"), basic=Decimal("20000"), hra=Decimal("30000"))
    # EPF default (basic only) = 20,000; excluding basic explicitly -> 0.
    assert _classify_wage_base(ctx, {"basic": False}, default_included={"basic"}) == Decimal("0")
    # ESI/PT default (everything) = gross; excluding hra explicitly -> gross - hra.
    assert _classify_wage_base(ctx, {"hra": False}, default_included=None) == ctx.gross - ctx.hra

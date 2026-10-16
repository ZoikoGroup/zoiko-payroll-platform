"""
tests/test_brazil_phase2_engine.py
-----------------------------------
Phase 2 golden-fixture and boundary tests for the Brazil CLT payroll engine
(ZP-BR-ENG-001 v1.0).

Golden Fixtures (spec §22):
  F1  — R$5,000 salary → progressive INSS R$501.51 (D1: rounded once)
  F2  — Salary above ceiling R$8,475.55 → INSS capped at R$951.62
  F3  — Taxable base ≤ R$5,000 → IRRF zero (2026 reduction zeroes it)
  F4  — Salary R$6,000 → IRRF phase-out reduction, deduction competition
  F5  — Salary within R$1,980.38, 1 dependent → Salário-Família R$67.54
  F6  — Apprentice R$1,621 → FGTS 2%, net pay unaffected

Additional boundary tests:
  T1  — INSS bracket boundary cents (exactly at R$1,621.00, R$2,902.84, etc.)
  T2  — IRRF simplified vs legal deduction competition
  T3  — 2026 IRRF reduction curve (R$5k zero-tax, R$5k–R$7.35k phase-out, above)
  T4  — CPRB transition 50% CPP reduction (10% instead of 20%)
  T5  — Fail-closed: simple mode blocked (BR_SIMPLE_MODE_UNSUPPORTED)
  T6  — Employer charges: RAT × FAP composition
  T7  — Salário-Família not awarded above ceiling
  T8  — Vale-Transporte deduction capped at 6% of base salary
  T9  — Concurrent employment: INSS bracket offset
  T10 — Standard engine dispatch routes BR employees correctly

Phase 0 status: the production dispatch (_COUNTRY_CALC["BR"] -> brazil.calculate)
BLOCKS every Brazilian calculation — see tests/test_brazil_scaffolding.py. This
file exercises the DRAFT calculation (_calculate_draft) and its helpers, which
no payroll path can reach. Phase 1 fixed BR-K1 (INSS maximum), BR-K10 (rounding
once) and BR-K2 (IRRF reduction on gross) — their former strict-xfail tests now
pass as ordinary tests. The IRRF reduction-basis tests reproduce the official
Receita Federal worked examples (docs/brazil/sources/S3).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
import pytest

from app.modules.payroll.engine.countries.brazil import (
    _calculate_inss_employee,
    _calculate_irrf,
    _apply_2026_irrf_reduction,
    _calculate_employer_charges,
    _calculate_fgts,
    _calculate_salario_familia,
    _calculate_vale_transporte_deduction,
    _calculate_draft,
    BrazilCalculationBlockedError,
)
from app.modules.payroll.engine import standard as _standard
from app.modules.payroll.engine.base import PayrollContext, PayrollResult
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.engine.resolver import calculate_payroll


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def D(s):
    return Decimal(str(s))


def make_ctx(gross, basic=None, country="BR", brazil_inputs=None, brazil_is_apprentice=False):
    return PayrollContext(
        gross=D(gross),
        basic=D(basic or gross),
        country=country,
        brazil_inputs=brazil_inputs or {},
        brazil_is_apprentice=brazil_is_apprentice,
    )


# ─────────────────────────────────────────────────────────────────────────────
# INSS unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestINSS:
    """Decision D1 (2026-10-16): INSS is rounded ONCE, on the exact progressive
    total — not per bracket. The draft rounds each bracket (known defect
    BR-K10, fixed in Phase 1), which is off by one cent on some salaries."""
    def test_F1_salary_5000(self):
        """F1: R$5,000 salary → INSS = R$501.51 (exact total rounded once)."""
        result = _calculate_inss_employee(D("5000.00"))
        # 121.575 + 115.3656 + 174.1716 + 90.4022 = 501.5144 → 501.51
        # (the draft rounds each bracket: 121.58 + 115.37 + 174.17 + 90.40 = 501.52)
        assert result["inss_employee"] == D("501.51"), (
            f"F1 failed: expected R$501.51, got {result['inss_employee']}"
        )
        assert result["ceiling_reached"] is False
        assert result["cap_applied"] is False

    # Known defect BR-K1: MAX_INSS_CONTRIBUTION = 951.62 contradicts the 2026
    # brackets, which sum to 988.0914 → 988.09 (D1: rounded once) at the
    # R$8,475.55 ceiling. Phase 1 fixes.
    _CORRECT_INSS_MAX = (D("988.09"),)
    def test_F2_above_ceiling(self):
        """F2: Salary > R$8,475.55 → INSS stops at the 2026 ceiling contribution."""
        result = _calculate_inss_employee(D("15000.00"))
        assert result["inss_employee"] in self._CORRECT_INSS_MAX, (
            f"F2 failed: expected the 2026 ceiling contribution, got {result['inss_employee']}"
        )
        assert result["ceiling_reached"] is True
    def test_exactly_at_ceiling(self):
        """INSS at exactly the ceiling salary R$8,475.55 → the full four-bracket sum."""
        result = _calculate_inss_employee(D("8475.55"))
        assert result["inss_employee"] in self._CORRECT_INSS_MAX
        assert result["ceiling_reached"] is True

    def test_inss_keeps_growing_up_to_the_ceiling(self):
        """BR-K1 fixed: INSS grows through band 4 all the way to R$8,475.55
        (the old 951.62 cap stopped it at about R$8,215), then stops."""
        at_8200 = _calculate_inss_employee(D("8200.00"))["inss_employee"]
        at_8400 = _calculate_inss_employee(D("8400.00"))["inss_employee"]
        at_ceiling = _calculate_inss_employee(D("8475.55"))["inss_employee"]
        above = _calculate_inss_employee(D("8475.56"))["inss_employee"]
        assert at_8200 < at_8400 < at_ceiling == above == D("988.09")

    def test_bracket_boundary_1621(self):
        """Exactly R$1,621.00 → only first bracket applies: 1621 × 7.5% = 121.58."""
        result = _calculate_inss_employee(D("1621.00"))
        assert result["inss_employee"] == D("121.58")
    def test_bracket_boundary_2902_84(self):
        """Exactly R$2,902.84 → first + second bracket."""
        result = _calculate_inss_employee(D("2902.84"))
        # 121.575 + 115.3656 = 236.9406 → 236.94 (draft per-bracket: 236.95)
        expected = D("236.94")
        assert result["inss_employee"] == expected, (
            f"Boundary 2902.84 failed: expected {expected}, got {result['inss_employee']}"
        )

    def test_minimum_wage(self):
        """Minimum wage R$1,621.00 is exactly the top of bracket 1."""
        result = _calculate_inss_employee(D("1621.00"))
        assert result["inss_employee"] == D("121.58")
    def test_concurrent_employment_offset(self):
        """T9: Concurrent employment that consumed bracket 1 means bracket 2 starts at 0."""
        # Worker earned R$1,621 elsewhere; own salary R$2,000
        result = _calculate_inss_employee(
            gross_inss=D("2000.00"),
            concurrent_base=D("1621.00"),
            concurrent_deducted=D("121.58"),
        )
        # Own portion only in bracket 2: (2000+1621) → combined 3621 sits in bracket 2
        # Own bracket 2 portion: (3621 - 2902.84) = 718.16 → no, bracket 2 upper is 2902.84
        # Combined 3621 > 2902.84, so also into bracket 3
        # Bracket 1: fully consumed by concurrent (1621.00), own portion = 0
        # Bracket 2: bracket top = min(3621, 2902.84)=2902.84; bracket bottom = max(1621, 1621)=1621
        #   own = 2902.84 - 1621 = 1281.84 × 9% = 115.37
        # Bracket 3: bracket top = min(3621, 4354.27)=3621; bracket bottom = max(2902.84, 1621)=2902.84
        #   own = 3621 - 2902.84 = 718.16 × 12% = 86.18
        # Exact own = 115.3656 + 86.1792 = 201.5448 → 201.54 (D1: rounded once;
        # the draft rounds each bracket: 115.37 + 86.18 = 201.55)
        # Combined contribution = 201.54 + 121.58 = 323.12 < the ceiling maximum → no cap
        assert result["inss_employee"] == D("201.54"), (
            f"Concurrent offset failed: got {result['inss_employee']}"
        )
        assert result["cap_applied"] is False


# ─────────────────────────────────────────────────────────────────────────────
# IRRF unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIRRF:

    def test_F3_5000_taxable_zero_irrf(self):
        """F3: Taxable base ≤ R$5,000 → after reduction IRRF = R$0.00."""
        # Salary R$5,000, INSS ~R$501.52, 0 dependents
        # Simplified deduction R$607.20 > legal (501.52)
        # Taxable = 5000 - 607.20 = 4392.80
        # Rate band 22.5%: 4392.80 × 22.5% - 675.49 = 988.38 - 675.49 = 312.89
        # Reduction: taxable 4392.80 ≤ 5000 → reduce up to 312.89 → net IRRF = 0
        result = _calculate_irrf(
            gross_irrf=D("5000.00"),
            inss_deducted=D("501.52"),
        )
        assert result["irrf"] == D("0.00"), (
            f"F3 failed: expected R$0.00 IRRF, got {result['irrf']}"
        )
        assert result["deduction_method"] == "SIMPLIFIED"
        assert result["irrf_reduction"] > D("0")

    def test_F4_6000_irrf_phase_out(self):
        """F4: Salary R$6,000 → phase-out reduction applies, trace preserved."""
        # INSS on R$6,000: 121.58 + 115.37 + 174.17 + (6000-4354.27)*14%
        # (6000 - 4354.27) = 1645.73 × 14% = 230.40
        # INSS = 121.58 + 115.37 + 174.17 + 230.40 = 641.52
        inss = D("641.52")
        result = _calculate_irrf(
            gross_irrf=D("6000.00"),
            inss_deducted=inss,
        )
        # Simplified R$607.20 vs Legal R$641.52 → Legal wins (larger)
        # Taxable = 6000 - 641.52 = 5358.48
        # Rate 27.5%: 5358.48 × 27.5% - 908.73 = 1473.58 - 908.73 = 564.85
        # Reduction: 5000 < 5358.48 ≤ 7350 → 978.62 - 0.133145 × 5358.48
        #   = 978.62 - 713.52 = 265.10
        # Net IRRF = 564.85 - 265.10 = 299.75
        assert result["irrf"] > D("0"), "F4: IRRF should be positive"
        assert result["irrf_reduction"] > D("0"), "F4: reduction should apply"
        assert result["deduction_method"] == "LEGAL", (
            "F4: legal deduction should win over simplified for R$6,000"
        )
        # Trace fields present
        assert "taxable_base" in result
        assert "raw_tax" in result
        assert result["taxable_base"] > D("5000")

    def test_simplified_wins_over_legal(self):
        """T2: When simplified R$607.20 > legal deductions, simplified wins."""
        # If INSS = R$100 and 0 dependents: legal = 100, simplified = 607.20 → simplified wins
        result = _calculate_irrf(
            gross_irrf=D("2500.00"),
            inss_deducted=D("100.00"),
            dependents=0,
        )
        assert result["deduction_method"] == "SIMPLIFIED"
        assert result["chosen_deduction"] == D("607.20")

    def test_legal_wins_when_larger(self):
        """T2: When legal deductions > R$607.20, legal method wins."""
        # INSS 400 + 2 dependents (2×189.59=379.18) + alimony 500 = 1279.18 > 607.20
        result = _calculate_irrf(
            gross_irrf=D("5000.00"),
            inss_deducted=D("400.00"),
            dependents=2,
            alimony=D("500.00"),
        )
        assert result["deduction_method"] == "LEGAL"
        assert result["chosen_deduction"] == D("1279.18")

    def test_opt_out_simplified_always_legal(self):
        """opt_out_simplified=True → always use legal regardless."""
        result = _calculate_irrf(
            gross_irrf=D("2500.00"),
            inss_deducted=D("100.00"),
            dependents=0,
            opt_out_simplified=True,
        )
        assert result["deduction_method"] == "LEGAL"
        assert result["opt_out_simplified"] is True

    def test_irrf_zero_band(self):
        """Income below R$2,428.80 tax-free band → IRRF = R$0."""
        result = _calculate_irrf(
            gross_irrf=D("2000.00"),
            inss_deducted=D("150.00"),
        )
        assert result["irrf"] == D("0.00")
        assert result["raw_tax"] == D("0.00")


class TestIRRFReductionBasis:
    """Known defect BR-K2: Law 15.270/2025 computes the reduction from monthly
    taxable INCOME (gross), not from the base after deductions — the R$312.89
    cap is exactly the table tax on R$5,000 − R$607.20, which only holds on the
    gross reading. The draft feeds the post-deduction base, so it under-withholds
    for gross between about R$5,000 and R$8,500. Pending tax-team sign-off (D2)."""
    def test_gross_5500(self):
        # Simplified (607.20) beats INSS 571.52 → base 4,892.80 → table tax 436.79;
        # reduction = 978.62 − 0.133145 × 5,500 = 246.32 → IRRF 190.47 (draft: 123.90).
        result = _calculate_irrf(gross_irrf=D("5500.00"), inss_deducted=D("571.52"))
        assert result["irrf"] == D("190.47")
    def test_gross_7350_gets_no_reduction(self):
        # Legal (INSS 830.52) → base 6,519.48 → table tax 884.13; reduction on
        # gross 7,350 = 978.62 − 978.62 = 0.00 → IRRF 884.13 (draft: 773.54).
        result = _calculate_irrf(gross_irrf=D("7350.00"), inss_deducted=D("830.52"))
        assert result["irrf"] == D("884.13")


class TestReceitaOfficialExamples:
    """The five monthly worked examples published by Receita Federal for Lei
    15.270/2025 (saved: docs/brazil/sources/S3_Receita_Exemplos_Lei_15270_2025.html).
    The examples take their INSS amount as an input (Receita used the 2025 INSS
    figures), so INSS is passed in exactly as published."""

    @pytest.mark.parametrize("gross,inss,method,base,raw_tax,reduction,irrf", [
        ("3036.00", "257.73", "SIMPLIFIED", "2428.80", "0.00", "0.00", "0.00"),       # Ex. 1
        ("4000.00", "373.41", "SIMPLIFIED", "3392.80", "114.76", "114.76", "0.00"),   # Ex. 2
        ("5000.00", "509.60", "SIMPLIFIED", "4392.80", "312.89", "312.89", "0.00"),   # Ex. 3
        ("6000.00", "649.60", "LEGAL", "5350.40", "562.63", "179.75", "382.88"),      # Ex. 4
        ("7607.20", "0.00", "SIMPLIFIED", "7000.00", "1016.27", "0.00", "1016.27"),   # Ex. 5
    ])
    def test_receita_example(self, gross, inss, method, base, raw_tax, reduction, irrf):
        result = _calculate_irrf(gross_irrf=D(gross), inss_deducted=D(inss))
        assert result["deduction_method"] == method
        assert result["taxable_base"] == D(base)
        assert result["raw_tax"] == D(raw_tax)
        assert result["irrf_reduction"] == D(reduction)
        assert result["irrf"] == D(irrf)
        assert result["reduction_basis"] == D(gross)    # gross, "e não o da base de cálculo"


class TestIRRFReduction:

    def test_below_5000_zeroed(self):
        """T3: Taxable ≤ R$5,000 → reduction zeroes the tax."""
        r = _apply_2026_irrf_reduction(D("4000.00"), D("200.00"))
        assert r["irrf_after_reduction"] == D("0.00")
        assert r["reduction"] == D("200.00")  # capped at raw_tax = 200

    def test_exactly_5000_zeroed(self):
        """T3: Taxable exactly R$5,000 → still zeroed."""
        r = _apply_2026_irrf_reduction(D("5000.00"), D("312.89"))
        assert r["irrf_after_reduction"] == D("0.00")

    def test_phase_out_at_6000(self):
        """T3: Taxable R$6,000 → phase-out formula applies."""
        # reduction = 978.62 - 0.133145 × 6000 = 978.62 - 798.87 = 179.75
        r = _apply_2026_irrf_reduction(D("6000.00"), D("500.00"))
        expected_reduction = D("978.62") - D("0.133145") * D("6000.00")
        from decimal import ROUND_HALF_UP
        expected_reduction = expected_reduction.quantize(D("0.01"), rounding=ROUND_HALF_UP)
        assert r["reduction"] == expected_reduction
        assert r["irrf_after_reduction"] == D("500.00") - expected_reduction

    def test_above_7350_no_reduction(self):
        """T3: Taxable > R$7,350 → no reduction at all."""
        r = _apply_2026_irrf_reduction(D("8000.00"), D("1000.00"))
        assert r["reduction"] == D("0.00")
        assert r["irrf_after_reduction"] == D("1000.00")

    def test_phase_out_capped_at_raw_tax(self):
        """T3: Phase-out reduction never exceeds raw_tax."""
        # Very low raw_tax in the phase range
        r = _apply_2026_irrf_reduction(D("5100.00"), D("10.00"))
        assert r["reduction"] <= D("10.00")
        assert r["irrf_after_reduction"] >= D("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# Employer Contribution tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEmployerCharges:

    def test_standard_cpp_20pct(self):
        """Standard CPP: 20% of gross."""
        result = _calculate_employer_charges(
            gross_cp=D("5000.00"),
            rat_pct=D("2"),
            fap_factor=D("1.0"),
            third_party_pct=D("5.8"),
        )
        assert result["cpp_employer"] == D("1000.00")  # 5000 × 20%
        assert result["cpp_regime"] == "STANDARD"

    def test_T4_cprb_transition_10pct(self):
        """T4: CPRB transition → CPP 10% (not 20%)."""
        result = _calculate_employer_charges(
            gross_cp=D("5000.00"),
            rat_pct=D("2"),
            fap_factor=D("1.0"),
            third_party_pct=D("5.8"),
            cprb_opted=True,
        )
        assert result["cpp_employer"] == D("500.00")  # 5000 × 10%
        assert "CPRB_TRANSITION" in result["cpp_regime"]

    def test_T6_rat_fap_composition(self):
        """T6: RAT × FAP correctly multiplies: 2% × 1.5 = 3%."""
        result = _calculate_employer_charges(
            gross_cp=D("10000.00"),
            rat_pct=D("2"),
            fap_factor=D("1.5"),
            third_party_pct=D("0"),
        )
        # RAT adjusted rate = 2% × 1.5 = 3%
        # RAT amount = 10000 × 3% = 300.00
        assert result["rat_adjusted"] == D("300.00")

    def test_financial_sector_addon(self):
        """Financial sector: +2.5% on top of standard 20% = 22.5%."""
        result = _calculate_employer_charges(
            gross_cp=D("4000.00"),
            rat_pct=D("1"),
            fap_factor=D("1.0"),
            third_party_pct=D("0"),
            financial_sector=True,
        )
        assert result["cpp_employer"] == D("900.00")  # 4000 × 22.5%
        assert "FINANCIAL" in result["cpp_regime"]

    def test_third_parties_calculation(self):
        """Third parties at FPAS rate 5.8%."""
        result = _calculate_employer_charges(
            gross_cp=D("5000.00"),
            rat_pct=D("2"),
            fap_factor=D("1.0"),
            third_party_pct=D("5.8"),
        )
        assert result["third_parties"] == D("290.00")  # 5000 × 5.8%


# ─────────────────────────────────────────────────────────────────────────────
# FGTS tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFGTS:

    def test_F6_apprentice_2pct(self):
        """F6: Apprentice at R$1,621 → FGTS 2%, not 8%."""
        result = _calculate_fgts(D("1621.00"), is_apprentice=True)
        assert result["fgts_deposit"] == D("32.42")  # 1621 × 2%
        assert result["is_apprentice"] is True
        assert result["rate_pct"] in ("2", "2.00")  # Decimal string representation

    def test_ordinary_8pct(self):
        """Standard worker: FGTS 8%."""
        result = _calculate_fgts(D("5000.00"))
        assert result["fgts_deposit"] == D("400.00")  # 5000 × 8%
        assert result["is_apprentice"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Salário-Família tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSalarioFamilia:

    def test_F5_eligible_one_dependent(self):
        """F5: Salary within R$1,980.38, 1 dependent → R$67.54."""
        result = _calculate_salario_familia(
            gross_remuneration=D("1621.00"),
            dependents=1,
        )
        assert result["salario_familia"] == D("67.54")
        assert result["eligible"] is True

    def test_T7_above_ceiling_not_eligible(self):
        """T7: Salary above R$1,980.38 → Salário-Família not awarded."""
        result = _calculate_salario_familia(
            gross_remuneration=D("2500.00"),
            dependents=2,
        )
        assert result["salario_familia"] == D("0.00")
        assert result["eligible"] is False

    def test_two_dependents(self):
        """Two eligible dependents → R$67.54 × 2 = R$135.08."""
        result = _calculate_salario_familia(
            gross_remuneration=D("1500.00"),
            dependents=2,
        )
        assert result["salario_familia"] == D("135.08")

    def test_zero_dependents(self):
        """Zero dependents → no benefit regardless of salary."""
        result = _calculate_salario_familia(
            gross_remuneration=D("1000.00"),
            dependents=0,
        )
        assert result["salario_familia"] == D("0.00")
        assert result["eligible"] is False

    def test_combined_remuneration_exceeds_ceiling(self):
        """Own salary below ceiling but concurrent pushes combined over — not eligible."""
        result = _calculate_salario_familia(
            gross_remuneration=D("1000.00"),
            dependents=1,
            concurrent_base=D("1500.00"),  # combined = 2500 > 1980.38
        )
        assert result["eligible"] is False
        assert result["salario_familia"] == D("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# Vale-Transporte tests
# ─────────────────────────────────────────────────────────────────────────────

class TestValeTransporte:

    def test_T8_capped_at_6pct(self):
        """T8: VT benefit exceeds 6% of base → deduction capped at 6%."""
        # base salary = 5000, 6% = 300; VT benefit = 500
        deduction = _calculate_vale_transporte_deduction(D("5000.00"), D("500.00"))
        assert deduction == D("300.00")

    def test_below_6pct_deducts_actual(self):
        """VT benefit below 6% of base → deduct actual benefit amount."""
        # base = 5000, 6% = 300; VT benefit = 200 < 300
        deduction = _calculate_vale_transporte_deduction(D("5000.00"), D("200.00"))
        assert deduction == D("200.00")

    def test_zero_vt_benefit(self):
        """No VT benefit → zero deduction."""
        deduction = _calculate_vale_transporte_deduction(D("5000.00"), D("0.00"))
        assert deduction == D("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# Full engine integration tests (via calculate() and StandardStrategy)
# ─────────────────────────────────────────────────────────────────────────────

class TestBrazilEngineIntegration:

    @pytest.fixture(autouse=True)
    def _route_br_to_draft(self, monkeypatch):
        """Production dispatch BLOCKS Brazil (Phase 0). These tests exercise how
        StandardStrategy sums the DRAFT result (VT deduction, Salário-Família
        net addition, employer liabilities kept out of net), so they route BR
        to _calculate_draft for the duration of each test only."""
        monkeypatch.setitem(_standard._COUNTRY_CALC, "BR", _calculate_draft)

    def test_T10_standard_strategy_routes_br(self):
        """T10: StandardStrategy dispatches BR to brazil.calculate correctly."""
        ctx = make_ctx("5000.00", basic="5000.00", brazil_inputs={
            "rat_pct": "2",
            "fap_factor": "1.0",
            "third_party_pct": "5.8",
        })
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        # Employee INSS flows into employee_pf (the amount itself is pinned by
        # TestINSS.test_F1_salary_5000; this test checks routing only)
        assert result.employee_pf == result.br_inss_employee > D("0"), (
            f"INSS via employee_pf: expected {result.br_inss_employee}, got {result.employee_pf}"
        )
        # IRRF = 0 (reduction zeroes it for R$5,000)
        assert result.tds == D("0.00"), (
            f"IRRF via tds: expected 0.00, got {result.tds}"
        )
        # FGTS is employer only, does NOT reduce net pay
        assert result.br_fgts_deposit == D("400.00")  # 5000 × 8%
        # CPP employer liability
        assert result.br_cpp_employer == D("1000.00")  # 5000 × 20%
        # br_result trace present
        assert result.br_result is not None
        assert result.br_result["spec"] == "ZP-BR-ENG-001 v1.0"

    def test_F6_apprentice_net_pay_unaffected(self):
        """F6: Apprentice FGTS 2% — net pay should NOT include FGTS as a deduction."""
        ctx = make_ctx("1621.00", basic="1621.00", brazil_is_apprentice=True)
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        # FGTS deposit exists as employer liability
        assert result.br_fgts_deposit == D("32.42")  # 1621 × 2%
        # FGTS does NOT appear in total_deductions
        # Net pay: gross - INSS - IRRF (no FGTS in net calc)
        assert result.net_pay > D("0")
        # Verify FGTS is NOT reducing net
        inss = result.employee_pf
        irrf = result.tds
        expected_net = D("1621.00") - inss - irrf
        assert result.net_pay == expected_net, (
            f"F6 net pay check: expected {expected_net}, got {result.net_pay}"
        )

    def test_F5_salario_familia_adds_to_net(self):
        """F5: Salário-Família adds to net pay (not a deduction)."""
        ctx = make_ctx("1621.00", basic="1621.00", brazil_inputs={"dependents": 1})
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        assert result.br_salario_familia == D("67.54")
        # Net pay is increased by Salário-Família
        inss = result.employee_pf
        irrf = result.tds
        net_without_sf = D("1621.00") - inss - irrf
        assert result.net_pay == net_without_sf + D("67.54"), (
            f"F5 net pay with SF: expected {net_without_sf + D('67.54')}, got {result.net_pay}"
        )
    def test_F2_ceiling_integration(self):
        """F2: High salary → INSS stops at the 2026 ceiling contribution via integration."""
        ctx = make_ctx("20000.00", basic="20000.00")
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        assert result.br_inss_employee in TestINSS._CORRECT_INSS_MAX
        assert result.employee_pf == result.br_inss_employee

    def test_cprb_transition_integration(self):
        """CPRB transition: CPP employer at 10%, verified via br_cpp_employer."""
        ctx = make_ctx("10000.00", basic="10000.00", brazil_inputs={
            "rat_pct": "2",
            "fap_factor": "1.0",
            "third_party_pct": "5.8",
            "cprb_opted": True,
        })
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        assert result.br_cpp_employer == D("1000.00")  # 10000 × 10%

    def test_T5_simple_mode_blocked(self):
        """T5: BR simple mode must raise the handled blocked error (clean 4xx)."""
        ctx = make_ctx("5000.00")
        with pytest.raises(BrazilCalculationBlockedError) as exc_info:
            calculate_payroll(ctx, calculation_mode="simple")
        assert exc_info.value.key == "BR_SIMPLE_MODE_UNSUPPORTED"

    def test_non_br_countries_unaffected(self):
        """All br_* result fields default to zero for non-BR countries."""
        ctx = PayrollContext(
            gross=D("5000.00"),
            basic=D("5000.00"),
            country="IN",
        )
        strategy = StandardStrategy()
        result = strategy.calculate(ctx)

        assert result.br_result is None
        assert result.br_inss_employee == D("0")
        assert result.br_irrf == D("0")
        assert result.br_fgts_deposit == D("0")
        assert result.br_cpp_employer == D("0")

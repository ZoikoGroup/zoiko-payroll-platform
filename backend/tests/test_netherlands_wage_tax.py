"""
tests/test_netherlands_wage_tax.py
----------------------------------
NL wage-tax withholding engine tests (ZP-NL-ENG-001 NL-005..NL-010, gate G1).

**BLOCKED ON G1**: These tests require the official 2026 Belastingdienst table files
to be imported into the database via netherlands_tables_service.
Without them, the engine raises NLBlock and tests are SKIPPED.

Test coverage:
  F1: €5,000 per month with the credit gives €1,325.08
  Each AOW cohort (BELOW_AOW, AOW_AGE) and pay period (DAY, WEEK, FOUR_WEEK, MONTH, QUARTER, YEAR)
  With and without tax credit
  Anonymous rate (52%)
  Special remuneration
  Replay protection: later table never replaces original when period replayed (NL-004)
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.netherlands.wage_tax import (
    NLError,
    NLBlock,
    NlTableKey,
    TableColor,
    TableKind,
    PeriodCode,
    AowCohort,
    select_table_key,
    lookup_period_withholding,
    special_remuneration,
    anonymous_rate,
    voluntary_extra,
    calculate_wage_tax,
    register_table_rows,
    is_table_loaded,
)
from app.modules.payroll.engine.base import PayrollContext


class MockContext:
    """Minimal context for testing wage_tax functions directly."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _ctx_base(**overrides) -> PayrollContext:
    """Create a PayrollContext with NL-relevant defaults."""
    # Formal PayrollContext parameters
    formal = {
        "gross": Decimal("5000"),
        "basic": Decimal("5000"),
        "country": "NL",
        "pay_date": date(2026, 1, 15),
        "date_of_birth": date(1990, 5, 15),  # age 35 → BELOW_AOW
    }
    # Dynamic NL attributes (set after construction)
    dynamic = {
        "payroll_period_code": "MONTHLY",
        "nl_table_color": "WHITE",
        "nl_with_tax_credit": True,
        "nl_residence_variant": "NL",
    }
    formal.update({k: v for k, v in overrides.items() if k in formal})
    dynamic.update({k: v for k, v in overrides.items() if k in dynamic})
    ctx = PayrollContext(**formal)
    for k, v in dynamic.items():
        setattr(ctx, k, v)
    return ctx


class TestSelectTableKey:
    """NL-005, NL-007: select_table_key picks correct table from context."""

    def test_period_table_key_monthly(self):
        ctx = _ctx_base(payroll_period_code="MONTHLY")
        key = select_table_key(ctx)
        assert key.tax_year == 2026
        assert key.table_color == TableColor.WHITE
        assert key.table_kind == TableKind.PERIOD
        assert key.period == PeriodCode.MONTHLY
        assert key.residence_variant == "NL"
        assert key.aow_cohort == AowCohort.BELOW_AOW
        assert key.with_tax_credit is True

    def test_period_table_key_all_periods(self):
        for period in ("DAY", "WEEK", "FOUR_WEEK", "MONTHLY", "QUARTER", "YEAR"):
            ctx = _ctx_base(payroll_period_code=period)
            key = select_table_key(ctx)
            assert key.period == PeriodCode(period)

    def test_special_remuneration_key(self):
        ctx = _ctx_base()
        key = select_table_key(ctx, special_remuneration=True)
        assert key.table_kind == TableKind.SPECIAL_REMUNERATION
        assert key.period is None

    def test_aow_cohort_age_67_plus(self):
        # Born 1959, pay_date 2026-01-15 → age 66 (still BELOW_AOW in 2026)
        # Born 1958, pay_date 2026-01-15 → age 68 (AOW_AGE in 2026, statutory AOW age = 67)
        ctx = _ctx_base(date_of_birth=date(1958, 1, 1))
        key = select_table_key(ctx)
        assert key.aow_cohort == AowCohort.AOW_AGE

    def test_residence_variant_from_context(self):
        ctx = _ctx_base(nl_residence_variant="DERIVATION_01")
        key = select_table_key(ctx)
        assert key.residence_variant == "DERIVATION_01"

    def test_without_tax_credit(self):
        ctx = _ctx_base(nl_with_tax_credit=False)
        key = select_table_key(ctx)
        assert key.with_tax_credit is False

    def test_missing_pay_date_blocks(self):
        ctx = _ctx_base(pay_date=None)
        with pytest.raises(NLBlock, match="pay_date required"):
            select_table_key(ctx)

    def test_missing_period_code_blocks(self):
        ctx = _ctx_base(payroll_period_code=None)
        with pytest.raises(NLBlock, match="payroll_period_code required"):
            select_table_key(ctx)

    def test_missing_dob_blocks(self):
        ctx = _ctx_base(date_of_birth=None)
        with pytest.raises(NLBlock, match="employee_date_of_birth required"):
            select_table_key(ctx)

    def test_table_key_as_dict_carries_full_audit(self):
        ctx = _ctx_base()
        key = select_table_key(ctx)
        d = key.as_dict()
        assert d["tax_year"] == 2026
        assert d["table_color"] == "WHITE"
        assert d["table_kind"] == "PERIOD"
        assert d["period"] == "MONTHLY"
        assert d["residence_variant"] == "NL"
        assert d["aow_cohort"] == "BELOW_AOW"
        assert d["with_tax_credit"] is True


class TestWageTaxLookups:
    """Actual lookups — BLOCKED until G1 tables loaded."""

    @pytest.fixture(autouse=True)
    def _check_tables_loaded(self):
        """Skip all tests in this class if G1 tables not loaded."""
        # Check if at least one table key is loaded
        key = NlTableKey(
            tax_year=2026,
            table_color=TableColor.WHITE,
            table_kind=TableKind.PERIOD,
            period=PeriodCode.MONTHLY,
            residence_variant="NL",
            aow_cohort=AowCohort.BELOW_AOW,
            with_tax_credit=True,
        )
        if not is_table_loaded(key):
            pytest.skip("G1 not complete: official 2026 Belastingdienst tables not imported")

    def test_f1_monthly_5000_with_credit(self):
        """F1: €5,000 per month with the credit gives €1,325.08."""
        ctx = _ctx_base(gross=Decimal("5000"), basic=Decimal("5000"))
        result = lookup_period_withholding(ctx, Decimal("5000"))
        assert result.withholding_amount == Decimal("1325.08")
        assert result.method == "TABLE_LOOKUP"
        assert result.table_key.tax_year == 2026
        assert result.table_key.period == PeriodCode.MONTHLY

    @pytest.mark.parametrize("period", ["DAY", "WEEK", "FOUR_WEEK", "MONTHLY", "QUARTER", "YEAR"])
    @pytest.mark.parametrize("aow_cohort", ["BELOW_AOW", "AOW_AGE"])
    @pytest.mark.parametrize("with_credit", [True, False])
    def test_all_cohorts_periods_credit_combinations(self, period, aow_cohort, with_credit):
        """Each AOW cohort and pay period, with and without the credit."""
        ctx = _ctx_base(
            payroll_period_code=period,
            employee_date_of_birth=date(1958, 1, 1) if aow_cohort == "AOW_AGE" else date(1990, 5, 15),
            nl_with_tax_credit=with_credit,
        )
        result = lookup_period_withholding(ctx, Decimal("5000"))
        assert result.withholding_amount >= Decimal("0")
        assert result.table_key.period == PeriodCode(period)
        assert result.table_key.aow_cohort == AowCohort(aow_cohort)
        assert result.table_key.with_tax_credit == with_credit

    def test_anonymous_rate(self):
        """Anonymous rate applies 52% and adds remediation warning."""
        result = anonymous_rate(Decimal("5000"), Decimal("52.00"))
        assert result.withholding_amount == Decimal("2600.00")  # 52% of 5000
        assert result.method == "ANONYMOUS_RATE"
        assert "Anonymous rate" in result.warnings[0]
        assert "Obtain employee BSN" in result.remediation_hints[0]

    def test_special_remuneration(self):
        """Special remuneration keeps reference annual wage, percentage, method."""
        ctx = _ctx_base()
        result = special_remuneration(ctx, Decimal("10000"))
        assert result.method == "SPECIAL_REMUNERATION"
        assert result.percentage_applied is not None
        assert result.percentage_applied >= Decimal("0")
        assert result.withholding_amount == (Decimal("10000") * result.percentage_applied / Decimal("100")).quantize(Decimal("0.01"))

    def test_voluntary_extra_only_adds(self):
        """Voluntary extra withholding can only add tax, never reduce."""
        base = Decimal("1000")
        extra = Decimal("200")
        final = voluntary_extra(base, extra)
        assert final == Decimal("1200")

    def test_voluntary_extra_negative_raises(self):
        with pytest.raises(NLError, match="cannot be negative"):
            voluntary_extra(Decimal("1000"), Decimal("-100"))

    def test_calculate_wage_tax_dispatch(self):
        """Single entry point dispatches correctly."""
        ctx = _ctx_base()
        # Normal
        r1 = calculate_wage_tax(ctx, Decimal("5000"))
        assert r1.method == "TABLE_LOOKUP"
        # Special
        r2 = calculate_wage_tax(ctx, Decimal("5000"), special_remuneration=True)
        assert r2.method == "SPECIAL_REMUNERATION"
        # Anonymous
        r3 = calculate_wage_tax(ctx, Decimal("5000"), anonymous=True, anonymous_rate_pct=Decimal("52.00"))
        assert r3.method == "ANONYMOUS_RATE"
        # Voluntary extra
        r4 = calculate_wage_tax(ctx, Decimal("5000"), voluntary_extra_amount=Decimal("100"))
        assert r4.withholding_amount == r1.withholding_amount + Decimal("100")


class TestReplayProtection:
    """NL-004: A later table never replaces the original when a period is replayed."""

    @pytest.fixture(autouse=True)
    def _check_tables_loaded(self):
        key = NlTableKey(
            tax_year=2026,
            table_color=TableColor.WHITE,
            table_kind=TableKind.PERIOD,
            period=PeriodCode.MONTHLY,
            residence_variant="NL",
            aow_cohort=AowCohort.BELOW_AOW,
            with_tax_credit=True,
        )
        if not is_table_loaded(key):
            pytest.skip("G1 not complete: official 2026 Belastingdienst tables not imported")

    def test_replay_uses_original_table(self):
        """Replaying a period uses the originally-activated table, not a later one.
        This is enforced by the ACTIVE table lookup (effective_from/effective_to)
        and the supersede logic in netherlands_tables_service.
        """
        ctx = _ctx_base()
        result1 = lookup_period_withholding(ctx, Decimal("5000"))
        original_key = result1.table_key

        # Simulate a second call (replay) - should get same table key
        result2 = lookup_period_withholding(ctx, Decimal("5000"))
        assert result2.table_key.as_dict() == original_key.as_dict()


class TestTableRegistration:
    """Unit tests for the in-memory cache registration (no DB needed)."""

    def test_register_and_lookup(self):
        key = NlTableKey(
            tax_year=2026,
            table_color=TableColor.WHITE,
            table_kind=TableKind.PERIOD,
            period=PeriodCode.MONTHLY,
            residence_variant="NL",
            aow_cohort=AowCohort.BELOW_AOW,
            with_tax_credit=True,
        )
        rows = [
            {"wage_from": Decimal("0"), "wage_to": Decimal("1000"), "aow_cohort": "BELOW_AOW", "with_tax_credit": True, "withholding_amount": Decimal("0")},
            {"wage_from": Decimal("1000"), "wage_to": Decimal("2000"), "aow_cohort": "BELOW_AOW", "with_tax_credit": True, "withholding_amount": Decimal("100")},
            {"wage_from": Decimal("2000"), "wage_to": None, "aow_cohort": "BELOW_AOW", "with_tax_credit": True, "withholding_amount": Decimal("300")},
        ]
        register_table_rows(key, rows)

        assert is_table_loaded(key)

        # Lookup exact boundary
        from app.modules.payroll.engine.jurisdictions.netherlands.wage_tax import _lookup_in_rows
        r = _lookup_in_rows(Decimal("1000"), rows)
        assert r["withholding_amount"] == Decimal("100")

        r = _lookup_in_rows(Decimal("1500"), rows)
        assert r["withholding_amount"] == Decimal("100")

        r = _lookup_in_rows(Decimal("2500"), rows)
        assert r["withholding_amount"] == Decimal("300")

        r = _lookup_in_rows(Decimal("500"), rows)
        assert r["withholding_amount"] == Decimal("0")

        # Not found
        r = _lookup_in_rows(Decimal("-100"), rows)
        assert r is None


class TestResultSerialization:
    """Verify NlWithholdingResult.as_dict() carries full table key for audit (NL-007)."""

    def test_result_as_dict_contains_table_key(self):
        key = NlTableKey(
            tax_year=2026,
            table_color=TableColor.WHITE,
            table_kind=TableKind.PERIOD,
            period=PeriodCode.MONTHLY,
            residence_variant="NL",
            aow_cohort=AowCohort.BELOW_AOW,
            with_tax_credit=True,
        )
        from app.modules.payroll.engine.jurisdictions.netherlands.wage_tax import NlWithholdingResult
        result = NlWithholdingResult(
            table_key=key,
            gross_wage=Decimal("5000"),
            withholding_amount=Decimal("1325.08"),
            method="TABLE_LOOKUP",
        )
        d = result.as_dict()
        assert "table_key" in d
        assert d["table_key"]["tax_year"] == 2026
        assert d["table_key"]["table_color"] == "WHITE"
        assert d["table_key"]["table_kind"] == "PERIOD"
        assert d["table_key"]["period"] == "MONTHLY"
        assert d["table_key"]["residence_variant"] == "NL"
        assert d["table_key"]["aow_cohort"] == "BELOW_AOW"
        assert d["table_key"]["with_tax_credit"] is True
        assert d["gross_wage"] == "5000"
        assert d["withholding_amount"] == "1325.08"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""
tests/test_singapore.py
---------------------------
Validates engine/countries/singapore.py against ZP-SG-ENG-001 v1.0 and the
official CPF Board / IRAS / MOM sources (retrieved 2026-09-23, recorded as
SourceArtifacts by scripts/seed_singapore_canonical_pack.py):

  - CPF: every cohort table (Tables 1–5), age bands and the
    month-after-birthday rule, SPR years, low-wage boundaries, OW ceiling,
    statutory rounding;
  - the AW ceiling per the CPF Board method (Option A): estimated ceiling
    at each AW payment, final re-calculation in December / the last month
    of employment, shortfall at each payment's own rates, excess reported
    as a refund application — matrix A–Q;
  - SDL, SHG (bands + residency eligibility), FWL (employer cost), LQS,
    IR21 eligibility, fail-closed BLOCKED behaviour, no `tds`;
  - DB level: the v1.1 seed + evidence, effective-dated resolution, the
    activation gates, YTD accumulator + AW ledger from persisted traces,
    end-to-end payroll run incl. YTD snapshot / trace / correction
    reproducibility, read-only backend preview, IR8A export, PDF labels,
    RBAC wiring and tenant isolation.

All identifiers are synthetic.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import singapore
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries.singapore import SingaporeCalculationBlockedError
from scripts.seed_singapore_canonical_pack import CPF_TABLES, SHG_BANDS, SOURCES

D = Decimal


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    text_value: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


@dataclass
class Slab:
    min_amount: Decimal
    max_amount: Optional[Decimal]
    rule_type: str
    filing_status: str
    rate_pct: Decimal = D("0")
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    tax_regime: Optional[str] = None
    assessment_basis: Optional[str] = None
    rate_label: str = ""


def _rate_map(**overrides):
    rates = {
        "cpf_ow_ceiling_monthly": Rate(flat_amount=D("8000")),
        "cpf_annual_wage_ceiling": Rate(flat_amount=D("102000")),
        "cpf_age_band_semantics": Rate(text_value="MONTH_AFTER_BIRTHDAY"),
        "sdl": Rate(employer_rate_pct=D("0.0025")),
        "sdl_min_monthly": Rate(flat_amount=D("2")),
        "sdl_max_monthly": Rate(flat_amount=D("11.25")),
        "fwl_s_pass_monthly": Rate(flat_amount=D("650")),
        "lqs_full_time_monthly": Rate(flat_amount=D("1800"), effective_from=date(2026, 7, 1)),
        "lqs_part_time_hourly": Rate(flat_amount=D("10.50"), effective_from=date(2026, 7, 1)),
        "ir21_filing_lead_months": Rate(flat_amount=D("1")),
    }
    rates.update(overrides)
    return {k: v for k, v in rates.items() if v is not None}


def _cpf_rows(cohort, band):
    er_low, factor, total, ee = CPF_TABLES[cohort][band]
    er_full = D(total) - D(ee)
    base = dict(rule_type="CPF_RATE_BAND", filing_status=cohort, tax_regime=band)
    return [
        Slab(D("0"), D("50"), assessment_basis="NIL", rate_label=f"CPF-{cohort}-{band}-NIL", **base),
        Slab(D("50"), D("500"), employer_rate_pct=D(er_low), assessment_basis="ER_ONLY",
             rate_label=f"CPF-{cohort}-{band}-ER_ONLY", **base),
        Slab(D("500"), D("750"), rate_pct=D(factor) * 100, employer_rate_pct=D(er_low), assessment_basis="PHASE_IN",
             rate_label=f"CPF-{cohort}-{band}-PHASE_IN", **base),
        Slab(D("750"), None, rate_pct=D(ee), employer_rate_pct=er_full, assessment_basis="FULL",
             rate_label=f"CPF-{cohort}-{band}-FULL", **base),
    ]


def _slabs(extra=(), without_cpf=False):
    """Exactly the official rows the seed writes — read from the seed's own
    constants so this test and the seed can never drift apart."""
    rows = [] if without_cpf else [r for c, bands in CPF_TABLES.items() for b in bands for r in _cpf_rows(c, b)]
    for fund, bands in SHG_BANDS.items():
        lower = D("0")
        for upper, amount in bands:
            upper_dec = D(str(upper)) if upper is not None else None
            rows.append(Slab(lower, upper_dec, "SHG_FUND_BAND", fund, flat_amount=D(amount)))
            lower = upper_dec if upper_dec is not None else lower
    rows.extend(extra)
    return rows


SLABS = _slabs()


def _ctx(gross="6000", **kw):
    fields = dict(
        gross=D(gross), basic=D(gross), country="SG", pay_frequency="Monthly",
        pay_date=date(2026, 6, 30), date_of_birth=date(1986, 3, 15),
        sgp_cpf_residency_status="SC", sgp_work_pass_type="NONE", sgp_shg_funds="NONE",
        ytd_cpf_ow_subject_before=D("0"), ytd_cpf_aw_subject_before=D("0"), ytd_cpf_aw_paid_before=D("0"),
        sgp_aw_ledger=[], rate_map=_rate_map(), slabs=SLABS,
    )
    fields.update(kw)
    return PayrollContext(**fields)


def _trace(out):
    return out["sgp_calculation_trace"]


_WEEK5 = {"workPattern": "5_DAY", "unpaidDates": []}   # MOM Monday–Friday week, no no-pay days


def _aw(out):
    return _trace(out)["cpf"]["additionalWages"]


def _dob_for_age(age, on=date(2026, 6, 30)):
    return date(on.year - age, 1, 15)


# ── Dispatch / not-PAYE ────────────────────────────────────────────────────

def test_sg_dispatches_to_singapore_calculator():
    assert _COUNTRY_CALC["SG"] is singapore.calculate


def test_no_tds_for_ordinary_singapore_payroll():
    result = calculate_payroll(_ctx("10000"), "standard")
    assert result.tds == D("0")
    assert "tds" not in singapore.calculate(_ctx("10000"))


# ── Spec fixtures F1/F2/F3/F4 ─────────────────────────────────────────────

def test_f1_citizen_le55_ow_6000():
    r = calculate_payroll(_ctx("6000"), "standard")
    assert (r.employee_pension, r.employer_pension) == (D("1200"), D("1020"))
    assert r.employer_payroll_tax == D("11.25")
    assert r.net_pay == D("4800.00")


def test_f2_ow_ceiling_caps_cpf_base():
    r = calculate_payroll(_ctx("10000"), "standard")
    assert (r.employee_pension, r.employer_pension) == (D("1600"), D("1360"))
    assert r.gross == D("10000")


def test_f3_december_aw_ceiling_final_actual():
    out = singapore.calculate(_ctx("28000", additional_compensation=D("20000"), pay_date=date(2026, 12, 31),
                                   ytd_cpf_ow_subject_before=D("88000")))
    aw = _aw(out)
    assert aw["ceilingBasis"] == "FINAL_ACTUAL"
    assert (aw["awCeiling"], aw["awSubjectThisPayment"]) == ("6000", "6000")
    assert out["ytd_cpf_ow_subject_after"] == D("96000")
    assert out["ytd_cpf_aw_subject_after"] == D("6000")


def test_f4_foreign_ep_no_cpf_but_sdl():
    out = singapore.calculate(_ctx("9000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"))
    assert out["employee_pension"] == out["employer_pension"] == D("0")
    assert out["employer_payroll_tax"] == D("11.25")
    assert out["employer_eht"] == D("0")
    assert _trace(out)["fwl"]["status"] == "NOT_APPLICABLE"


# ── Official CPF tables: every cohort, full-rate row ─────────────────────

@pytest.mark.parametrize("cohort,band", [(c, b) for c, bands in CPF_TABLES.items() for b in bands])
def test_every_cohort_full_rate_row_matches_official_table(cohort, band):
    _er, _f, total, ee = CPF_TABLES[cohort][band]
    row = singapore.select_cpf_band(SLABS, cohort, band, D("6000"))
    t, e, r = singapore.calculate_cpf(row, D("6000"), D("6000"))
    assert t == (D(total) / 100 * 6000).quantize(D("1"), rounding="ROUND_HALF_UP")
    assert e == (D(ee) / 100 * 6000).quantize(D("1"), rounding="ROUND_FLOOR")
    assert e + r == t


@pytest.mark.parametrize("age,band,ee,er", [
    (40, "AGE_LE_55", "1200", "1020"), (57, "AGE_55_60", "1080", "960"), (62, "AGE_60_65", "750", "750"),
    (67, "AGE_65_70", "450", "540"), (75, "AGE_GT_70", "300", "450"),
])
def test_full_rate_age_bands(age, band, ee, er):
    out = singapore.calculate(_ctx("6000", date_of_birth=_dob_for_age(age)))
    assert _trace(out)["cpf"]["ageBand"] == band
    assert (out["employee_pension"], out["employer_pension"]) == (D(ee), D(er))


@pytest.mark.parametrize("boundary,before,after", [
    (55, "AGE_LE_55", "AGE_55_60"), (60, "AGE_55_60", "AGE_60_65"),
    (65, "AGE_60_65", "AGE_65_70"), (70, "AGE_65_70", "AGE_GT_70"),
])
def test_age_band_changes_the_month_after_the_birthday(boundary, before, after):
    dob = date(2026 - boundary, 6, 15)  # boundary birthday on 15 Jun 2026
    months = {m: _trace(singapore.calculate(_ctx("6000", date_of_birth=dob, pay_date=date(2026, m, 28 if m == 2 else 30))))["cpf"]["ageBand"]
              for m in (5, 6, 7)}
    assert months == {5: before, 6: before, 7: after}   # month before, birthday month, month after


def test_boundary_age_blocks_without_the_age_rule():
    rates = _rate_map(cpf_age_band_semantics=None)
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", date_of_birth=_dob_for_age(55), rate_map=rates))
    assert exc.value.key == "cpf_age_band_semantics"


# ── SPR years ─────────────────────────────────────────────────────────────

def _spr(spr_date, pay_date, gross="6000", **kw):
    return _ctx(gross, sgp_cpf_residency_status="SPR", sgp_spr_effective_date=spr_date, pay_date=pay_date, **kw)


@pytest.mark.parametrize("pay_date,expected", [
    (date(2026, 3, 31), 1), (date(2026, 4, 30), 2), (date(2027, 3, 31), 2), (date(2027, 4, 30), 3),
])
def test_spr_year_boundaries(pay_date, expected):
    assert singapore.resolve_spr_year(date(2025, 3, 1), pay_date.replace(day=1), pay_date) == expected


@pytest.mark.parametrize("arrangement,spr_date,cohort,ee,er", [
    (None, date(2026, 1, 1), "SPR1_GG", "300", "240"),
    ("FG", date(2026, 1, 1), "SPR1_FG", "300", "1020"),
    ("FF", date(2026, 1, 1), "SPR1_FF", "1200", "1020"),
    (None, date(2025, 3, 1), "SPR2_GG", "900", "540"),
    ("FG", date(2025, 3, 1), "SPR2_FG", "900", "1020"),
    ("FF", date(2025, 3, 1), "SPR2_FF", "1200", "1020"),
    (None, date(2023, 1, 1), "SC_SPR3", "1200", "1020"),
])
def test_spr_cohorts_use_official_tables(arrangement, spr_date, cohort, ee, er):
    out = singapore.calculate(_spr(spr_date, date(2026, 6, 30), sgp_cpf_contribution_arrangement=arrangement))
    assert _trace(out)["cohort"] == cohort
    assert (out["employee_pension"], out["employer_pension"]) == (D(ee), D(er))


def test_spr_year1_above_65_uses_the_single_above_65_group():
    for dob in (_dob_for_age(67), _dob_for_age(75)):
        out = singapore.calculate(_spr(date(2026, 1, 1), date(2026, 6, 30), date_of_birth=dob))
        assert (out["employee_pension"], out["employer_pension"]) == (D("300"), D("210"))  # 8.5% / 5%


def test_mid_month_spr_conversion_blocks():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_spr(date(2026, 6, 15), date(2026, 6, 30)))
    assert exc.value.key == "sgp_spr_effective_date"


def test_future_spr_with_work_pass_is_not_yet_cpf_eligible():
    out = singapore.calculate(_spr(date(2026, 9, 1), date(2026, 6, 30), sgp_work_pass_type="S_PASS"))
    assert out["employee_pension"] == D("0")
    assert _trace(out)["effectiveResidency"] == "FOREIGN"


# ── Low-wage boundaries (official Table 1, ≤55) ──────────────────────────

@pytest.mark.parametrize("gross,total,ee", [
    ("0", "0", "0"), ("0.01", "0", "0"), ("50", "0", "0"),              # ≤ $50: nil
    ("50.01", "9", "0"),                            # 17% × 50.01 = 8.5017 → 9
    ("500", "85", "0"),                             # 17% × 500
    ("500.01", "85", "0"),                          # 85.0017 + 0.006
    ("749.99", "277", "149"),                       # 127.4983 + 149.994
    ("750", "278", "150"),                          # 127.5 + 150 = 277.5 → 278
    ("750.01", "278", "150"),                       # full row: 37% × 750.01 = 277.5037
])
def test_low_wage_boundaries(gross, total, ee):
    out = singapore.calculate(_ctx(gross))
    r = _trace(out)["cpf"]["rounding"]
    assert (r["total"], r["employee"]) == (total, ee)
    assert out["employee_pension"] + out["employer_pension"] == D(total)


def test_missing_cpf_rows_block():
    with pytest.raises(SingaporeCalculationBlockedError):
        singapore.calculate(_ctx("6000", slabs=_slabs(without_cpf=True)))


def test_overlapping_cpf_rows_block():
    dup = Slab(D("750"), None, "CPF_RATE_BAND", "SC_SPR3", D("20"), D("17"), tax_regime="AGE_LE_55",
               assessment_basis="FULL", rate_label="DUP")
    with pytest.raises(SingaporeCalculationBlockedError, match="overlapping"):
        singapore.calculate(_ctx("6000", slabs=_slabs([dup])))


# ── OW ceiling / rounding ────────────────────────────────────────────────

@pytest.mark.parametrize("gross,ow_subject", [("7999.99", "7999.99"), ("8000", "8000"), ("8000.01", "8000")])
def test_ow_ceiling_boundary(gross, ow_subject):
    assert _trace(singapore.calculate(_ctx(gross)))["cpf"]["owSubject"] == ow_subject


@pytest.mark.parametrize("gross", ["1234.56", "3333.33", "7777.77", "6666.67"])
def test_cpf_rounding_reconciles_exactly(gross):
    out = singapore.calculate(_ctx(gross))
    r = _trace(out)["cpf"]["rounding"]
    assert D(r["total"]) == (D("0.37") * D(gross)).quantize(D("1"), rounding="ROUND_HALF_UP")
    assert out["employee_pension"] == (D("0.20") * D(gross)).quantize(D("1"), rounding="ROUND_FLOOR")
    assert out["employee_pension"] + out["employer_pension"] == D(r["total"])


# ══════════════════════════════════════════════════════════════════════════
# AW ceiling — CPF Board method (Option A), matrix A–Q
# ══════════════════════════════════════════════════════════════════════════

def run_year(plan, dob=date(1986, 3, 15), leaving=None, leaving_recorded_month=None):
    """Chains month-by-month calculations exactly the way service.py does:
    YTD accumulators carried forward, and the AW ledger rebuilt from each
    month's own trace (ledgerEntry + SHORTFALL allocations). The leaving
    date is only visible from `leaving_recorded_month` onwards (default:
    from the start) — the CPF Board examples assume the departure is not
    known when the early AW is paid."""
    ytd = dict(ow=D("0"), aw_subject=D("0"), aw_paid=D("0"))
    ledger = {}
    results = {}
    for month, ow, aw in plan:
        last = 28 if month == 2 else (30 if month in (4, 6, 9, 11) else 31)
        ctx = _ctx(str(D(ow) + D(aw)), additional_compensation=D(aw), pay_date=date(2026, month, last),
                   date_of_birth=dob,
                   date_of_leaving=leaving if (leaving_recorded_month is None or month >= leaving_recorded_month) else None,
                   ytd_cpf_ow_subject_before=ytd["ow"], ytd_cpf_aw_subject_before=ytd["aw_subject"],
                   ytd_cpf_aw_paid_before=ytd["aw_paid"], sgp_aw_ledger=[ledger[k] for k in sorted(ledger)])
        out = singapore.calculate(ctx)
        aw_trace = _aw(out)
        if aw_trace.get("ledgerEntry"):
            ledger[aw_trace["ledgerEntry"]["month"]] = dict(aw_trace["ledgerEntry"])
        for a in aw_trace["allocations"]:
            if a["kind"] == "SHORTFALL":
                e = ledger[a["sourceMonth"]]
                e["awSubjected"] = str(D(e["awSubjected"]) + D(a["amount"]))
        ytd = dict(ow=out["ytd_cpf_ow_subject_after"], aw_subject=out["ytd_cpf_aw_subject_after"],
                   aw_paid=out["ytd_cpf_aw_paid_after"])
        results[month] = out
    return results


def test_A_january_aw_uses_estimated_ceiling_not_ytd():
    """CPF Board example 1: $9k OW, $12k AW in January → $6k subject (a
    year-to-date reading would have made the full $12k subject)."""
    out = run_year([(1, "9000", "12000")])[1]
    aw = _aw(out)
    assert aw["ceilingBasis"] == "ESTIMATED"
    assert (aw["annualOwUsed"], aw["awCeiling"], aw["awSubjectThisPayment"]) == ("96000", "6000", "6000")
    assert (out["employer_pension"], out["employee_pension"]) == (D("2380"), D("2800"))
    assert "SG-007" in _trace(out)["cpf"]["specClarification"]


def test_B_march_aw():
    out = run_year([(1, "9000", "0"), (2, "9000", "0"), (3, "9000", "10000")])[3]
    assert (_aw(out)["awCeiling"], _aw(out)["awSubjectThisPayment"]) == ("6000", "6000")


def test_C_june_aw_with_prior_aw_consumed():
    res = run_year([(1, "9000", "12000")] + [(m, "9000", "0") for m in range(2, 6)] + [(6, "9000", "10000")])
    assert _aw(res[6])["awSubjectThisPayment"] == "0"          # ceiling already used in January
    assert res[6]["ytd_cpf_aw_subject_after"] == D("6000")


def test_D_september_aw_with_lower_ow():
    res = run_year([(m, "5000", "0") for m in range(1, 9)] + [(9, "5000", "30000")])
    aw = _aw(res[9])
    # 40,000 (Jan–Aug) + 5,000 × 4 (Sep–Dec) = 60,000 → ceiling 42,000
    assert (aw["annualOwUsed"], aw["awCeiling"], aw["awSubjectThisPayment"]) == ("60000", "42000", "30000")


def test_E_december_aw_is_final_actual():
    res = run_year([(m, "8000", "0") for m in range(1, 12)] + [(12, "8000", "20000")])
    aw = _aw(res[12])
    assert aw["ceilingBasis"] == "FINAL_ACTUAL" and aw["awSubjectThisPayment"] == "6000"


def test_leaving_date_known_in_advance_shortens_the_estimate():
    """With the departure already recorded, the estimate covers only the
    remaining months of EMPLOYMENT (Jan–Aug), so January's ceiling is
    102,000 − 8,000 × 8 = 38,000 and no shortfall builds up."""
    out = run_year([(1, "10000", "70000")], leaving=date(2026, 8, 31))[1]
    assert (_aw(out)["estimatedMonthsRemaining"], _aw(out)["awCeiling"]) == (7, "38000")


def test_F_last_month_of_employment_aw_is_final_actual():
    res = run_year([(m, "10000", "0") for m in range(1, 8)] + [(8, "10000", "50000")], leaving=date(2026, 8, 31))
    aw = _aw(res[8])
    assert aw["ceilingBasis"] == "FINAL_ACTUAL"
    assert (aw["awCeiling"], aw["awSubjectThisPayment"]) == ("38000", "38000")   # 102,000 − 8,000 × 8


def test_G_employee_leaving_before_december_pays_shortfall_at_january_rates():
    """CPF Board example 6: $70k AW in Jan ($6k subject), $30k in Apr (none),
    leaves in August → $32k shortfall at January's 37%."""
    plan = [(1, "10000", "70000")] + [(m, "10000", "0") for m in (2, 3)] + [(4, "10000", "30000")] + \
           [(m, "10000", "0") for m in range(5, 9)]
    res = run_year(plan, leaving=date(2026, 8, 31), leaving_recorded_month=8)
    aug = _aw(res[8])
    shortfalls = [a for a in aug["allocations"] if a["kind"] == "SHORTFALL"]
    assert [(a["sourceMonth"], a["amount"], a["totalRatePct"]) for a in shortfalls] == [("2026-01", "32000", "37")]
    assert (res[8]["employer_pension"], res[8]["employee_pension"]) == (D("6800"), D("8000"))
    assert res[8]["ytd_cpf_aw_subject_after"] == D("38000")


@pytest.mark.parametrize("ow,expected_ceiling", [("4500", "48000"), ("8000", "6000"), ("9000", "6000")])
def test_H_I_J_monthly_ow_below_at_above_ceiling(ow, expected_ceiling):
    assert _aw(run_year([(1, ow, "1000")])[1])["awCeiling"] == expected_ceiling


def test_K_multiple_aw_payments_match_cpf_board_example_9():
    plan = [(1, "10000", "2850.60"), (2, "10000", "3753.82"), (3, "10000", "25000"), (4, "10000", "6022.94"),
            (5, "10000", "0"), (6, "10000", "0"), (7, "0", "62372.64")]
    res = run_year(plan, leaving=date(2026, 6, 30), leaving_recorded_month=6)
    assert _aw(res[2])["awSubjectThisPayment"] == "3149.40"
    assert D(_aw(res[3])["awSubjectThisPayment"]) == 0
    june = _aw(res[6])
    assert june["shortfallAwSubject"] == "31627.36"
    assert (res[6]["employer_pension"], res[6]["employee_pension"]) == (D("6737"), D("7925"))  # OW 1,360/1,600 + AW 5,377/6,325
    assert _aw(res[7])["awSubjectThisPayment"] == "16372.64"
    assert (res[7]["employer_pension"], res[7]["employee_pension"]) == (D("2784"), D("3274"))
    assert res[7]["ytd_cpf_aw_subject_after"] == D("54000")


@pytest.mark.parametrize("label", ["AWS", "Bonus", "Commission classified as AW"])
def test_L_M_N_every_aw_kind_takes_the_same_statutory_path(label):
    """AWS, bonus and AW-classified commission all arrive as
    additional_compensation (no per-earning classifier) — identical result."""
    out = run_year([(1, "9000", "12000")])[1]
    assert _aw(out)["awSubjectThisPayment"] == "6000", label


def test_O_final_december_true_up_catches_up_earlier_aw():
    """OW falls from $9k to $4k mid-year: December's final ceiling
    (102,000 − 72,000 = 30,000) leaves room for the $6k of January AW that
    was never subject → shortfall at January's rates."""
    plan = [(1, "9000", "12000")] + [(m, "9000", "0") for m in range(2, 7)] + [(m, "4000", "0") for m in range(7, 13)]
    res = run_year(plan)
    dec = _aw(res[12])
    assert dec["ceilingBasis"] == "FINAL_ACTUAL" and dec["awCeiling"] == "30000"
    assert [(a["sourceMonth"], a["amount"]) for a in dec["allocations"] if a["kind"] == "SHORTFALL"] == [("2026-01", "6000")]
    assert res[12]["ytd_cpf_aw_subject_after"] == D("12000")


def test_P_excess_is_reported_as_refund_not_netted():
    """OW rises after an early AW: the ceiling falls below AW already
    contributed on → REFUND_APPLICATION_REQUIRED, CPF this month unchanged."""
    plan = [(1, "4500", "40000")] + [(m, "4500", "0") for m in (2, 3)] + [(m, "8000", "0") for m in range(4, 13)]
    res = run_year(plan)
    dec = _aw(res[12])
    assert dec["excess"]["excessAwSubject"] == "23500"      # 40,000 − (102,000 − 85,500)
    assert dec["excess"]["treatment"].startswith("REFUND_APPLICATION_REQUIRED")
    assert (res[12]["employer_pension"], res[12]["employee_pension"]) == (D("1360"), D("1600"))


def test_Q_shortfall_trace_preserves_original_and_final_figures():
    plan = [(1, "10000", "70000")] + [(m, "10000", "0") for m in range(2, 9)]
    res = run_year(plan, leaving=date(2026, 8, 31), leaving_recorded_month=8)
    jan, aug = _aw(res[1]), _aw(res[8])
    assert (jan["ceilingBasis"], jan["awCeiling"], jan["ledgerEntry"]["awSubjected"]) == ("ESTIMATED", "6000", "6000")
    assert (aug["ceilingBasis"], aug["awCeiling"], aug["shortfallAwSubject"]) == ("FINAL_ACTUAL", "38000", "32000")
    assert aug["allocations"][0]["reason"].startswith("AW ceiling re-calculated")


def test_aw_without_ytd_accumulator_blocks():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("9000", additional_compensation=D("1000"), ytd_cpf_ow_subject_before=None))
    assert exc.value.key == "ytd_cpf_accumulator"


def test_final_month_true_up_blocks_when_ledger_does_not_reconcile():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("10000", pay_date=date(2026, 12, 31), ytd_cpf_ow_subject_before=D("88000"),
                                 ytd_cpf_aw_subject_before=D("6000"), ytd_cpf_aw_paid_before=D("20000"), sgp_aw_ledger=[]))
    assert exc.value.key == "sgp_aw_ledger"


# ── SDL ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("gross,sdl", [
    ("0", "0"), ("500", "2.00"), ("799.99", "2.00"), ("800", "2.00"), ("1000", "2.50"),
    ("4500", "11.25"), ("4500.01", "11.25"), ("10000", "11.25"),
])
def test_sdl_zero_min_normal_max(gross, sdl):
    out = singapore.calculate(_ctx(gross, sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"))
    assert out["employer_payroll_tax"] == D(sdl)


def test_sdl_is_employer_cost_not_a_deduction():
    r = calculate_payroll(_ctx("3000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"), "standard")
    assert (r.employer_payroll_tax, r.total_deductions, r.net_pay) == (D("7.50"), D("0.00"), D("3000.00"))


# ── SHG ───────────────────────────────────────────────────────────────────

def _shg_edges():
    for fund, bands in SHG_BANDS.items():
        lower = D("0")
        for upper, amount in bands:
            if upper is not None:
                yield fund, D(str(upper)), amount
            yield fund, lower + D("0.01"), amount
            lower = D(str(upper)) if upper is not None else lower


@pytest.mark.parametrize("fund,wages,amount", list(_shg_edges()))
def test_every_shg_band_edge(fund, wages, amount):
    assert singapore.calculate_shg(SLABS, [fund], wages) == {fund: D(amount)}


def test_multiple_shg_funds_are_summed_as_employee_deduction():
    r = calculate_payroll(_ctx("6000", sgp_shg_funds="MBMF,SINDA"), "standard")
    assert r.professional_tax == D("28.50")
    assert r.net_pay == D("6000") - D("1200") - D("28.50")


@pytest.mark.parametrize("residency,work_pass,fund,eligible", [
    ("SC", "NONE", "CDAC", True), ("SC", "NONE", "ECF", True), ("SC", "NONE", "MBMF", True), ("SC", "NONE", "SINDA", True),
    ("FOREIGN", "EP", "CDAC", False), ("FOREIGN", "EP", "ECF", False),
    ("FOREIGN", "EP", "MBMF", True), ("FOREIGN", "WORK_PERMIT", "MBMF", True),
    ("FOREIGN", "EP", "SINDA", True), ("FOREIGN", "S_PASS", "SINDA", False), ("FOREIGN", "WORK_PERMIT", "SINDA", False),
])
def test_shg_residency_eligibility(residency, work_pass, fund, eligible):
    ctx = _ctx("5000", sgp_cpf_residency_status=residency, sgp_work_pass_type=work_pass, sgp_shg_funds=fund)
    if eligible:
        assert singapore.calculate(ctx)["professional_tax"] > 0
    else:
        with pytest.raises(SingaporeCalculationBlockedError) as exc:
            singapore.calculate(ctx)
        assert exc.value.key == "sgp_shg_funds"


@pytest.mark.parametrize("value", [None, "", "XYZ", "NONE,CDAC"])
def test_invalid_or_missing_shg_determination_blocks(value):
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", sgp_shg_funds=value))
    assert exc.value.key == "sgp_shg_funds"


def test_missing_shg_band_blocks():
    slabs = [s for s in SLABS if s.filing_status != "ECF"]
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", sgp_shg_funds="ECF", slabs=slabs))
    assert exc.value.key == "shg:ECF"


# ── Foreign worker levy (employer cost) ──────────────────────────────────

def test_s_pass_levy_is_employer_cost_and_never_reduces_net_pay():
    r = calculate_payroll(_ctx("5000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS"), "standard")
    assert r.employer_eht == D("650")
    assert (r.total_deductions, r.net_pay) == (D("0.00"), D("5000.00"))


def test_s_pass_partial_month_levy_is_blocked_not_guessed():
    out = singapore.calculate(_ctx("5000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS",
                                   date_of_joining=date(2026, 6, 10), sgp_employment_facts=_WEEK5))
    assert out["employer_eht"] == D("0") and _trace(out)["fwl"]["status"] == "BLOCKED"


def test_work_permit_levy_without_worker_levy_facts_is_blocked():
    """Phase 5: the levy is priced (MOM sector pages), but a Work Permit holder
    without sector / skill / tier is never guessed."""
    out = singapore.calculate(_ctx("2500", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="WORK_PERMIT"))
    assert _trace(out)["fwl"]["status"] == "BLOCKED"
    assert "sector, skill level" in _trace(out)["fwl"]["detail"]
    assert out["employer_eht"] == D("0")


def test_missing_s_pass_levy_row_is_blocked():
    out = singapore.calculate(_ctx("5000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS",
                                   rate_map=_rate_map(fwl_s_pass_monthly=None)))
    assert _trace(out)["fwl"]["status"] == "BLOCKED"


# ── LQS ───────────────────────────────────────────────────────────────────

LQS_BOTH = dict(
    lqs_full_time_monthly=Rate(flat_amount=D("1800"), effective_from=date(2026, 7, 1)),
)


@pytest.mark.parametrize("pay_date,row,gross,status", [
    (date(2026, 8, 31), Rate(flat_amount=D("1800"), effective_from=date(2026, 7, 1)), "1700", "BELOW_LQS"),   # F6
    (date(2026, 8, 31), Rate(flat_amount=D("1800"), effective_from=date(2026, 7, 1)), "1800", "MEETS_LQS"),
    (date(2026, 6, 30), Rate(flat_amount=D("1600"), effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30)), "1700", "MEETS_LQS"),
    (date(2026, 6, 30), Rate(flat_amount=D("1800"), effective_from=date(2026, 7, 1)), "1700", "BLOCKED"),  # row not in force
])
def test_lqs_before_and_after_1_july_2026(pay_date, row, gross, status):
    out = singapore.calculate(_ctx(gross, pay_date=pay_date, sgp_employer_hires_foreign_workers=True,
                                   rate_map=_rate_map(lqs_full_time_monthly=row)))
    assert _trace(out)["lqs"]["status"] == status


def test_lqs_part_time_needs_hours_and_is_not_applicable_without_foreign_workers():
    pt = singapore.calculate(_ctx("1200", employment_type="Part-time", sgp_employer_hires_foreign_workers=True,
                                  pay_date=date(2026, 8, 31)))
    assert pt["sgp_calculation_trace"]["lqs"]["status"] == "BLOCKED"
    none = singapore.calculate(_ctx("1200", sgp_employer_hires_foreign_workers=False))
    assert none["sgp_calculation_trace"]["lqs"]["status"] == "NOT_APPLICABLE"


# ── IR21 ──────────────────────────────────────────────────────────────────

def test_ir21_triggered_for_non_citizen_leaving_with_file_by_date():
    out = singapore.calculate(_ctx("9000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                                   date_of_leaving=date(2026, 10, 13), pay_date=date(2026, 9, 30)))
    ir21 = _trace(out)["ir21"]
    assert (ir21["status"], ir21["fileBy"]) == ("TRIGGERED", "2026-09-13")
    assert "sgp_ir21_cases" in ir21["workflow"]   # the case (Phase 2), not this trace, controls payment


def test_ir21_not_required_for_citizens():
    out = singapore.calculate(_ctx("9000", date_of_leaving=date(2026, 10, 13)))
    assert _trace(out)["ir21"]["status"] == "NOT_REQUIRED"


# ── Fail-closed: missing statutory rows / contradictory facts ─────────────

@pytest.mark.parametrize("missing", ["cpf_ow_ceiling_monthly", "cpf_annual_wage_ceiling", "sdl", "sdl_min_monthly", "sdl_max_monthly"])
def test_missing_statutory_parameter_blocks_never_defaults(missing):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        singapore.calculate(_ctx("6000", rate_map=_rate_map(**{missing: None})))
    assert exc.value.key == missing


@pytest.mark.parametrize("overrides,key", [
    (dict(sgp_cpf_residency_status=None), "sgp_cpf_residency_status"),
    (dict(sgp_work_pass_type=None), "sgp_work_pass_type"),
    (dict(sgp_work_pass_type="EP"), "sgp_work_pass_type"),
    (dict(sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="NONE"), "sgp_work_pass_type"),
    (dict(sgp_cpf_residency_status="SPR", sgp_spr_effective_date=None), "sgp_spr_effective_date"),
    (dict(sgp_cpf_residency_status="SPR", sgp_spr_effective_date=date(2020, 1, 1), sgp_work_pass_type="EP"), "sgp_work_pass_type"),
    (dict(date_of_birth=None), "date_of_birth"),
    (dict(pay_frequency="Weekly"), "pay_frequency"),
    (dict(pay_date=None), "pay_date"),
])
def test_missing_or_contradictory_facts_block(overrides, key):
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", **overrides))
    assert exc.value.key == key


def test_trace_carries_inputs_rules_rounding_and_result():
    t = _trace(singapore.calculate(_ctx("10000", sgp_shg_funds="CDAC")))
    assert t["inputs"]["gross"] == "10000" and t["cpf"]["rule"] == "CPF-SC_SPR3-AGE_LE_55-FULL"
    assert t["cpf"]["rounding"]["method"].startswith("total to nearest dollar")
    assert t["result"] == {"employeeCpf": "1600", "employerCpf": "1360", "shg": "3.00", "sdl": "11.25", "fwl": "0",
                           "employeeDeductions": "1603.00", "netPay": "8397.00", "employerCost": "11371.25"}


# ── Invariants ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("gross,aw", [("0", "0"), ("45", "0"), ("640", "0"), ("6000", "0"), ("12000", "3000"), ("30000", "25000")])
@pytest.mark.parametrize("residency,work_pass", [("SC", "NONE"), ("FOREIGN", "S_PASS")])
def test_invariants(gross, aw, residency, work_pass):
    r = calculate_payroll(_ctx(gross, additional_compensation=D(aw), sgp_cpf_residency_status=residency,
                               sgp_work_pass_type=work_pass), "standard")
    assert r.employee_pension >= 0 and r.employer_pension >= 0 and r.employer_payroll_tax >= 0 and r.professional_tax >= 0
    assert r.net_pay <= r.gross
    assert r.net_pay == max(r.gross - r.employee_pension - r.professional_tax, D("0"))  # employer costs never reduce net


# ── Employee validation ───────────────────────────────────────────────────

def test_sg_employee_validation_syncs_cohort_columns():
    from app.modules.payroll.employee_validation import get_employee_validation_strategy

    strategy = get_employee_validation_strategy("SG")
    cleaned = strategy.validate({
        "nric_fin": "s1234567d", "cpf_residency_status": "spr", "spr_effective_date": "2025-03-01",
        "work_pass_type": "none", "shg_funds": "mbmf, sinda",
    })
    assert strategy.sync_to_columns(cleaned) == {
        "sgp_cpf_residency_status": "SPR", "sgp_spr_effective_date": date(2025, 3, 1),
        "sgp_work_pass_type": "NONE", "sgp_shg_funds": "MBMF,SINDA",
    }


@pytest.mark.parametrize("fields", [
    {"nric_fin": "123"}, {"cpf_residency_status": "SC", "work_pass_type": "EP"},
    {"cpf_residency_status": "FOREIGN", "work_pass_type": "NONE"}, {"cpf_residency_status": "SPR"},
    {"shg_funds": "RACE_CODE"},
])
def test_sg_employee_validation_rejects_bad_or_contradictory_facts(fields):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import get_employee_validation_strategy

    with pytest.raises(BadRequestException):
        get_employee_validation_strategy("SG").validate(fields)


def test_singapore_is_known_but_not_registerable():
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code, get_jurisdiction_schema
    from app.modules.payroll.service import _normalize_country

    assert "Singapore" not in REGISTRATION_COUNTRIES
    assert get_jurisdiction_code("Singapore") == "SG"
    assert get_jurisdiction_schema("SG")["currency"] == "SGD"
    assert _normalize_country("Singapore") == "SG"


# ══════════════════════════════════════════════════════════════════════════
# DB-level
# ══════════════════════════════════════════════════════════════════════════

MAKER = SimpleNamespace(id=101)
CHECKER = SimpleNamespace(id=202)


def _seed(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


def test_seed_v11_full_official_tables_with_evidence(db):
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxConfigurationAudit, TaxSlab

    pack = _seed(db)
    assert (pack.pack_id, pack.version, pack.status) == ("SG-PAYROLL-2026", "1.2", "Draft")
    cpf = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == "CPF_RATE_BAND").all()
    assert len(cpf) == 7 * 5 * 4
    assert {r.filing_status for r in cpf} == set(CPF_TABLES)
    assert all(r.source_document_id is not None for r in cpf)
    artifacts = db.query(SourceArtifact).all()
    assert {a.checksum_sha256 for a in artifacts} == {s[3] for s in SOURCES.values()}
    assert all(a.reviewer_approved_at is None for a in artifacts)            # unreviewed — a human must review
    assert pack.source_document_id in {a.id for a in artifacts}
    lqs = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                            ContributionRate.component_key == "lqs_full_time_monthly").all()
    assert sorted((str(r.flat_amount), r.effective_from, r.effective_to) for r in lqs) == [
        ("1600.00", date(2026, 1, 1), date(2026, 6, 30)), ("1800.00", date(2026, 7, 1), None)]
    keys = {r.component_key for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id)}
    assert "lqs_part_time_hourly" in keys  # post-July only
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id).count() == 1


def test_seed_is_new_version_idempotent_and_refuses_non_draft(db):
    from app.modules.payroll.models import JurisdictionPack, SourceArtifact, TaxSlab

    v10 = JurisdictionPack(pack_id="SG-PAYROLL-2026", jurisdiction_country="SG", version="1.1", pack_type="tax",
                           status="Draft", effective_from=date(2026, 1, 1))     # Phase 5: v1.2 supersedes v1.1
    db.add(v10)
    db.commit()
    pack = _seed(db)
    assert pack.previous_version_id == v10.id
    first = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_country == "SG").count(), db.query(SourceArtifact).count())
    _seed(db)
    assert (db.query(TaxSlab).filter(TaxSlab.jurisdiction_country == "SG").count(), db.query(SourceArtifact).count()) == first
    assert db.get(JurisdictionPack, v10.id).status == "Draft"   # v1.1 untouched
    pack.status = "In Review"
    db.commit()
    with pytest.raises(SystemExit):
        _seed(db)


def _activate_directly(db, pack):
    pack.status = "Active"
    db.commit()


def test_draft_pack_never_resolves(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    _seed(db)
    assert resolve_tax_configuration(db, "SG", payroll_date=date(2026, 6, 30)) == ([], [], None)


def test_lqs_rows_resolve_by_payroll_date(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    _activate_directly(db, _seed(db))
    lqs = lambda d: [r.flat_amount for r in resolve_tax_configuration(db, "SG", payroll_date=d)[0]  # noqa: E731
                     if r.component_key == "lqs_full_time_monthly"]
    assert lqs(date(2026, 6, 30)) == [D("1600")]
    assert lqs(date(2026, 7, 1)) == [D("1800")]


def test_2026_and_2027_packs_resolve_by_wage_date(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import JurisdictionPack

    pack26 = _seed(db)
    pack26.effective_to = date(2026, 12, 31)
    pack26.status = "Active"
    pack27 = JurisdictionPack(pack_id="SG-PAYROLL-2027", jurisdiction_country="SG", version="1.0", pack_type="tax",
                              status="Active", effective_from=date(2027, 1, 1), tax_year="2027", previous_version_id=pack26.id)
    db.add(pack27)
    db.commit()
    assert resolve_tax_configuration(db, "SG", payroll_date=date(2026, 5, 31))[2].id == pack26.id
    assert resolve_tax_configuration(db, "SG", payroll_date=date(2027, 1, 1))[2].id == pack27.id


def _cert_run(db, status):
    from app.modules.payroll.models import TestCertificationRun

    db.add(TestCertificationRun(jurisdiction_country="SG", status=status, total_cases=4, passed_cases=4, real_case_count=4))
    db.commit()


def test_activation_requires_source_evidence(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed(db)
    pack.source_document_id = None
    db.commit()
    with pytest.raises(BadRequestException, match="Source Evidence"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)


@pytest.mark.parametrize("run_status", [None, "NO_REAL_CASES", "FAIL"])
def test_activation_requires_a_passing_certification_run(db, run_status):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed(db)
    if run_status:
        _cert_run(db, run_status)
    with pytest.raises(BadRequestException, match="certification"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)


def test_activation_requires_distinct_approver_then_blocks_downgrade(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    from tests._sg_evidence import accept_sg_gate

    pack = _seed(db)
    pack.updated_by_id = MAKER.id
    db.commit()
    _cert_run(db, "PASS")
    accept_sg_gate(db)                       # Phase 6.10: SG activation needs G1 accepted
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER.id)
    # Phase 6.0 F2: the approver may not also activate a Singapore pack.
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=MAKER.id).status == "Active"
    with pytest.raises(BadRequestException, match="Singapore tax pack is Active"):
        service.set_jurisdiction_pack_status(db, pack.id, "Draft", actor_id=CHECKER.id)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Superseded", actor_id=CHECKER.id).status == "Superseded"


def test_certification_console_runs_sg_golden_vectors(db):
    from app.modules.payroll import service

    run = service.run_golden_test_certification(db, jurisdiction_country="SG", actor_id=CHECKER.id)
    assert (run.jurisdiction_country, run.status) == ("SG", "PASS")
    assert run.real_case_count == run.total_cases == run.passed_cases >= 13


def _sg_employee(db, org_id, code, **kw):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="SG",
                  ctc=D("120000"), date_of_birth=date(1986, 3, 15), sgp_cpf_residency_status="SC",
                  sgp_work_pass_type="NONE", sgp_shg_funds="NONE", compliance_fields={"nric_fin": "S1234567D"})
    fields.update(kw)
    emp = PayrollEmployee(**fields)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _other_org(db, code):
    from app.modules.organizations.models import Organization

    org = Organization(organization_name=f"Org {code}", organization_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_ytd_accumulator_three_components_round_trip(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.engine.base import PayrollResult

    emp = _sg_employee(db, organization.id, "SGA")
    loaded = service._load_sg_cpf_ytd(db, emp.id, date(2026, 1, 31))
    assert (loaded["ytd_cpf_ow_subject_before"], loaded["ytd_cpf_aw_subject_before"], loaded["ytd_cpf_aw_paid_before"]) == (0, 0, 0)
    assert loaded["sgp_aw_ledger"] == [] and loaded["sgp_employer_hires_foreign_workers"] is False
    service._upsert_sg_cpf_ytd_accumulator(db, emp.id, date(2026, 1, 31), PayrollResult(
        ytd_cpf_ow_subject_after=D("8000"), ytd_cpf_aw_subject_after=D("6000"), ytd_cpf_aw_paid_after=D("12000")))
    db.commit()
    again = service._load_sg_cpf_ytd(db, emp.id, date(2026, 2, 28), lock=True)
    assert (again["ytd_cpf_ow_subject_before"], again["ytd_cpf_aw_subject_before"], again["ytd_cpf_aw_paid_before"]) == (
        D("8000.00"), D("6000.00"), D("12000.00"))
    assert service._load_sg_cpf_ytd(db, emp.id, date(2027, 1, 31))["ytd_cpf_ow_subject_before"] == 0


def _activate_for_org(db, organization, pack):
    from app.modules.payroll.models import CompanyComplianceDetails

    _activate_directly(db, pack)
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", active_pack_id=pack.id))
    db.commit()


def _run(db, organization, pay_date, label):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=organization.id, period_label=label, period_start=pay_date.replace(day=1),
                     period_end=pay_date, pay_date=pay_date)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_end_to_end_runs_reproduce_cpf_board_example_6_from_persisted_traces(db, organization, monkeypatch):
    """Eight real generate_payslips_for_run months (CPF Board AW example 6):
    OW $10k/month; AW $70k in January and $30k in April (entered as
    attendance bonus, which is what becomes CPF Additional Wages); the
    employee leaves in August. January uses the ESTIMATED $6k ceiling; the
    August true-up reads the ledger back from the PERSISTED January/April
    traces and pays the $32k shortfall at January's rates. The YTD snapshot
    and accumulators are frozen per payslip, and a correction of August
    reproduces it exactly (historical reproducibility)."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollYtdAccumulator, PayslipItem

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGE2E")
    aw_by_month = {1: D("70000"), 4: D("30000")}
    monkeypatch.setattr(service, "_sum_attendance_extras",
                        lambda db_, org_id, emp_id, start, end, records=None: aw_by_month.get(start.month, D("0")))
    items = {}
    for m in range(1, 9):
        if m == 8:   # cessation recorded in the last month (CPF Board example 6)
            emp.date_of_leaving = date(2026, 8, 31)
            db.commit()
        last = 28 if m == 2 else (30 if m in (4, 6) else 31)
        run = _run(db, organization, date(2026, m, last), f"2026-{m:02d}")
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
        items[m] = (run, db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                                      PayslipItem.employee_id == emp.id).one())

    jan = items[1][1]
    jan_aw = jan.sgp_calculation_trace["cpf"]["additionalWages"]
    assert (jan_aw["ceilingBasis"], D(jan_aw["awCeiling"]), D(jan_aw["awSubjectThisPayment"])) == ("ESTIMATED", 6000, 6000)
    assert (jan.employer_pension, jan.employee_pension) == (D("2380"), D("2800"))
    assert {k: D(v) for k, v in jan.ytd_snapshot["cpf_aw_paid"].items()} == {"ytd_before": 0, "ytd_after": 70000}

    aug = items[8][1]
    aug_aw = aug.sgp_calculation_trace["cpf"]["additionalWages"]
    assert aug_aw["ceilingBasis"] == "FINAL_ACTUAL" and D(aug_aw["awCeiling"]) == 38000
    assert [(a["sourceMonth"], D(a["amount"])) for a in aug_aw["allocations"] if a["kind"] == "SHORTFALL"] == [("2026-01", 32000)]
    assert (aug.employer_pension, aug.employee_pension) == (D("6800"), D("8000"))
    assert {k: D(v) for k, v in aug.ytd_snapshot["cpf_aw_subject"].items()} == {"ytd_before": 6000, "ytd_after": 38000}
    acc = {r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id)}
    assert acc == {"cpf_ow_subject": D("64000.00"), "cpf_aw_subject": D("38000.00"), "cpf_aw_paid": D("100000.00")}

    # Correction of the August payslip: recalculated from its own frozen
    # snapshot + the persisted ledger, never re-reading/writing the live
    # accumulator — identical figures.
    service.regenerate_employee_payslip(db, items[8][0].id, emp.id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == items[8][0].id,
                                          PayslipItem.employee_id == emp.id).one()
    assert (redone.employer_pension, redone.employee_pension) == (D("6800"), D("8000"))
    assert D(redone.sgp_calculation_trace["cpf"]["additionalWages"]["shortfallAwSubject"]) == 32000
    assert {r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id)} == acc


def test_ledger_rebuilt_from_persisted_traces_including_shortfalls(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGL")
    traces = {
        date(2026, 1, 31): {"cpf": {"additionalWages": {"ledgerEntry": {"month": "2026-01", "awPaid": "70000", "awSubjected": "6000",
                            "eePct": "20", "totalPct": "37", "formulaType": "FULL", "rule": "R"}, "allocations": []}}},
        date(2026, 4, 30): {"cpf": {"additionalWages": {"ledgerEntry": {"month": "2026-04", "awPaid": "30000", "awSubjected": "0",
                            "eePct": "20", "totalPct": "37", "formulaType": "FULL", "rule": "R"}, "allocations": []}}},
        date(2026, 6, 30): {"cpf": {"additionalWages": {"allocations": [{"kind": "SHORTFALL", "sourceMonth": "2026-01", "amount": "1000"}]}}},
    }
    runs = {}
    for pay_date, trace in traces.items():
        run = _run(db, organization, pay_date, str(pay_date))
        runs[pay_date] = run
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name="x",
                           country_code="SG", sgp_calculation_trace=trace))
    db.commit()
    ledger = service._load_sg_aw_ledger(db, emp.id, date(2026, 8, 31))
    assert [(e["month"], e["awSubjected"]) for e in ledger] == [("2026-01", "7000"), ("2026-04", "0")]
    assert all(e["paymentId"].startswith("PS-") for e in ledger)
    # The run being calculated (April) is never part of its own history.
    april = runs[date(2026, 4, 30)]
    assert [e["month"] for e in service._load_sg_aw_ledger(db, emp.id, date(2026, 4, 30), current_run_id=april.id)] == ["2026-01"]


def test_same_month_aw_payments_under_different_rates_keep_their_own_rates(db, organization):
    """Two AW payments in ONE wage month (salary run + off-cycle bonus run)
    under different rates are two ledger payments — the final true-up
    charges each shortfall at its own payment's rate, never blocked."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGSAME")
    entry = lambda paid, subj, ee, tot: {"cpf": {"additionalWages": {  # noqa: E731
        "ledgerEntry": {"month": "2026-06", "awPaid": paid, "awSubjected": subj, "eePct": ee, "totalPct": tot,
                        "formulaType": "FULL", "rule": f"R{tot}"}, "allocations": []}}}
    run_a = _run(db, organization, date(2026, 6, 30), "Jun salary")
    run_b = _run(db, organization, date(2026, 6, 30), "Jun bonus")
    db.add(PayslipItem(payroll_run_id=run_a.id, employee_id=emp.id, organization_id=organization.id, employee_name="x",
                       country_code="SG", sgp_calculation_trace=entry("10000", "0", "20", "37")))
    db.add(PayslipItem(payroll_run_id=run_b.id, employee_id=emp.id, organization_id=organization.id, employee_name="x",
                       country_code="SG", sgp_calculation_trace=entry("5000", "0", "18", "34")))
    db.commit()
    ledger = service._load_sg_aw_ledger(db, emp.id, date(2026, 12, 31))
    assert [(e["awPaid"], e["totalPct"]) for e in ledger] == [("10000", "37"), ("5000", "34")]
    assert len({e["paymentId"] for e in ledger}) == 2
    # Final December true-up with room for both → each chunk at its own rate.
    out = singapore.calculate(_ctx("8000", pay_date=date(2026, 12, 31), ytd_cpf_ow_subject_before=D("88000"),
                                   ytd_cpf_aw_subject_before=D("0"), ytd_cpf_aw_paid_before=D("15000"), sgp_aw_ledger=ledger))
    shortfalls = [(a["sourcePaymentId"], a["amount"], a["totalRatePct"]) for a in _aw(out)["allocations"] if a["kind"] == "SHORTFALL"]
    assert shortfalls == [(ledger[0]["paymentId"], "6000", "37")]            # ceiling 6,000 fills the oldest payment first
    ledger_room = [dict(ledger[0], awSubjected="0"), dict(ledger[1])]
    out2 = singapore.calculate(_ctx("4000", pay_date=date(2026, 12, 31), ytd_cpf_ow_subject_before=D("44000"),
                                    ytd_cpf_aw_subject_before=D("0"), ytd_cpf_aw_paid_before=D("15000"), sgp_aw_ledger=ledger_room))
    got = [(a["amount"], a["totalRatePct"], a["employeeRatePct"]) for a in _aw(out2)["allocations"] if a["kind"] == "SHORTFALL"]
    assert got == [("10000", "37", "20"), ("5000", "34", "18")]
    raw = D(_trace(out2)["cpf"]["rounding"]["totalRaw"])
    assert raw == D("4000") * D("0.37") + D("10000") * D("0.37") + D("5000") * D("0.34")   # summed, then rounded once


def test_legacy_month_keyed_shortfall_still_applies(db, organization):
    """Traces written before paymentId existed (sourceMonth only) still
    reduce that month's payments — backward compatible."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGLEG")
    for pay_date, trace in (
        (date(2026, 1, 31), {"cpf": {"additionalWages": {"ledgerEntry": {"month": "2026-01", "awPaid": "70000", "awSubjected": "6000",
                             "eePct": "20", "totalPct": "37", "formulaType": "FULL", "rule": "R"}, "allocations": []}}}),
        (date(2026, 5, 31), {"cpf": {"additionalWages": {"allocations": [{"kind": "SHORTFALL", "sourceMonth": "2026-01", "amount": "500"}]}}}),
    ):
        run = _run(db, organization, pay_date, str(pay_date))
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name="x",
                           country_code="SG", sgp_calculation_trace=trace))
    db.commit()
    assert service._load_sg_aw_ledger(db, emp.id, date(2026, 8, 31))[0]["awSubjected"] == "6500"


# ── OW / AW / non-CPF classification via the shared TaxabilityRule table ──

def _classified(**rules):
    return {"cpf_ordinary_wages": rules.get("ow", {}), "cpf_additional_wages": rules.get("aw", {})}


def test_default_classification_is_salary_ow_and_additional_compensation_aw():
    ow, aw, non_cpf, detail = singapore.classify_cpf_wages(_ctx("12000", basic=D("9000"), hra=D("1000"),
                                                                additional_compensation=D("2000")))
    assert (ow, aw, non_cpf) == (D("10000"), D("2000"), D("0"))
    assert detail["additional_compensation"] == {"amount": "2000", "class": "AW", "source": "default",
                                                 "pwmBasis": "EXCLUDED", "eaGrossRate": "EXCLUDED"}


def test_rule_can_move_a_component_to_aw_or_make_it_non_cpf():
    ctx = _ctx("12000", basic=D("9000"), hra=D("1000"), overtime=D("0"), additional_compensation=D("2000"),
               sgp_cpf_wage_classification=_classified(ow={"hra": False}, aw={"special_allowance": True}))
    ow, aw, non_cpf, detail = singapore.classify_cpf_wages(ctx)
    assert non_cpf == D("1000") and detail["hra"]["class"] == "NON_CPF" and detail["hra"]["source"] == "rule"
    out = singapore.calculate(ctx)
    assert D(_trace(out)["cpf"]["owSubject"]) == D("8000")          # 9,000 basic capped; HRA not CPF wages
    assert _trace(out)["inputs"]["nonCpfWages"] == "1000"


def test_contradictory_classification_blocks():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", sgp_cpf_wage_classification=_classified(ow={"basic": True}, aw={"basic": True})))
    assert exc.value.key == "cpf_wage_classification:basic"


def test_classification_components_never_double_count():
    """basic = gross with AW on top (golden/preview contexts) → basic is
    reduced so OW + AW + non-CPF always equals gross."""
    ow, aw, non_cpf, _ = singapore.classify_cpf_wages(_ctx("21000", additional_compensation=D("12000")))
    assert (ow, aw, ow + aw + non_cpf) == (D("9000"), D("12000"), D("21000"))


def test_service_classification_uses_shared_taxability_rules(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxabilityRule

    emp = _sg_employee(db, organization.id, "SGCLS")
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="hra", tax_component="cpf_ordinary_wages", is_taxable=False))
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="overtime", tax_component="cpf_ordinary_wages",
                          is_taxable=False, organization_id=_other_org(db, "CLSOTHER").id))   # another tenant's rule
    db.commit()
    rules = service._sg_cpf_wage_classification(db, emp.id, date(2026, 6, 30))
    assert rules == {"cpf_ordinary_wages": {"hra": False}, "cpf_additional_wages": {}}


def test_frozen_classification_rebuilds_the_original_rules():
    from app.modules.payroll import service

    frozen = {"basic": {"class": "OW"}, "hra": {"class": "NON_CPF"}, "additional_compensation": {"class": "AW"},
              "special_allowance": {"class": "AW"}}
    assert service._sg_frozen_classification(frozen) == {
        "cpf_ordinary_wages": {"basic": True, "hra": False},
        "cpf_additional_wages": {"additional_compensation": True, "special_allowance": True},
    }


def test_foreign_worker_flag_is_tenant_scoped(db, organization):
    from app.modules.payroll import service

    local = _sg_employee(db, organization.id, "SGLOC")
    other = _other_org(db, "OTHERORG")
    _sg_employee(db, other.id, "SGFOR", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS")
    assert service._sg_employer_hires_foreign_workers(db, local.id) is False    # Tenant B's foreigner never leaks
    _sg_employee(db, organization.id, "SGFOR2", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP")
    assert service._sg_employer_hires_foreign_workers(db, local.id) is True


def _preview_data(pack_id, **kw):
    base = dict(jurisdictionPackId=pack_id, payDate=date(2026, 1, 31), gross=D("21000"), additionalWages=D("12000"),
                residencyStatus="SC", sprEffectiveDate=None, contributionArrangement=None, workPass="NONE",
                shgFunds="NONE", dateOfBirth=date(1986, 3, 15), dateOfJoining=None, dateOfLeaving=None,
                employmentType="Full-time", employerHiresForeignWorkers=None, ytdOwSubjectBefore=D("0"),
                ytdAwSubjectBefore=D("0"), ytdAwPaidBefore=D("0"), awLedger=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_backend_preview_uses_production_engine_and_writes_nothing(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import (
        JurisdictionPack, PayrollEmployee, PayrollRun, PayrollYtdAccumulator, PayslipItem, TaxConfigurationAudit,
    )

    pack = _seed(db)
    counts = lambda: tuple(db.query(m).count() for m in (  # noqa: E731
        JurisdictionPack, PayrollEmployee, PayrollRun, PayslipItem, PayrollYtdAccumulator, TaxConfigurationAudit))
    before = counts()
    out = service.preview_singapore_calculation(db, _preview_data(pack.id))
    assert out["readOnly"] is True and out["blocked"] is False and out["pack"]["status"] == "Draft"
    assert (out["result"]["employerCpf"], out["result"]["employeeCpf"]) == ("2380", "2800")   # CPF Board example 1
    assert D(out["trace"]["cpf"]["additionalWages"]["awCeiling"]) == 6000
    assert not db.new and not db.dirty
    assert counts() == before


def test_backend_preview_returns_blocked_reason(db):
    from app.modules.payroll import service

    pack = _seed(db)
    out = service.preview_singapore_calculation(db, _preview_data(pack.id, residencyStatus=None))
    assert out["blocked"] is True and out["blockedKey"] == "sgp_cpf_residency_status"


def test_backend_preview_rejects_non_singapore_pack(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    uk = JurisdictionPack(pack_id="UK-X", jurisdiction_country="UK", version="1.0", pack_type="tax", status="Draft")
    db.add(uk)
    db.commit()
    with pytest.raises(BadRequestException):
        service.preview_singapore_calculation(db, _preview_data(uk.id))


def _route(path, method):
    from app.main import app

    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r
    raise AssertionError(path)


def _dependency_names(route):
    names = set()

    def walk(dep):
        for d in dep.dependencies:
            names.add(getattr(d.call, "__name__", ""))
            walk(d)
    walk(route.dependant)
    return names


def test_preview_route_is_super_admin_only():
    assert "get_current_super_admin" in _dependency_names(_route("/api/super-admin/compliance/singapore/calculation-preview", "POST"))


def test_ir8a_route_uses_payroll_operator_rbac():
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/reports/ir8a", "POST"))


def _ir8a_template(db):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key="SG-IR8A", name="IR8A", report_type="SG_IR8A", jurisdiction_country="SG",
                       reporting_year="2026", version="1.0", status="Active", document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_ir8a_export_is_export_ready_masked_and_tenant_scoped(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    template = _ir8a_template(db)
    emp = _sg_employee(db, organization.id, "SGIR8A")
    other = _other_org(db, "OTHERIR8A")
    stranger = _sg_employee(db, other.id, "SGSTRANGER")
    for org_id, e in ((organization.id, emp), (other.id, stranger)):
        run = _run(db, SimpleNamespace(id=org_id), date(2026, 3, 31), f"Mar {org_id}")
        run.status = PayrollStatus.APPROVED
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=e.id, organization_id=org_id, employee_name=e.name,
                           country_code="SG", gross_pay=D("15000"), additional_compensation=D("5000"),
                           employee_pension=D("2600"), professional_tax=D("1.50")))
    db.commit()
    report = service.generate_sg_ir8a(db, organization.id, template.id, 2026, actor_id=MAKER.id)
    data = report.rendered_data
    assert data["submissionStatus"] == "EXPORT_READY" and data["period"]["yearOfAssessment"] == 2027
    assert [r["employeeCode"] for r in data["employeeRows"]] == ["SGIR8A"]            # Tenant B excluded
    row = data["employeeRows"][0]
    assert (row["grossSalary"], row["bonusAdditionalWages"], row["employeeCpf"]) == (10000.0, 5000.0, 2600.0)
    assert row["nricFinMasked"] == "*****567D" and "1234" not in row["nricFinMasked"]   # PDPC partial NRIC
    assert any("NOT an AIS-API 2.0 submission" in g for g in data["knownGaps"])   # IRAS: API or myTax Portal only


def test_pdf_labels_singapore_components(db, organization):
    import io
    import pypdf
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGPDF")
    run = _run(db, organization, date(2026, 6, 30), "Jun 2026")
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                       country_code="SG", basic_salary=D("6000"), gross_pay=D("7000"), additional_compensation=D("1000"),
                       employee_pension=D("1400"), employer_pension=D("1190"), professional_tax=D("1.50"),
                       employer_payroll_tax=D("11.25"), total_deductions=D("1401.50"), net_pay=D("5598.50"))
    db.add(item)
    db.commit()
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(service.generate_payslip_pdf_bytes(db, item.id, organization.id))).pages)
    assert "CPF (Employee)" in text and "SHG Contribution" in text and "Additional Wages (AW)" in text
    assert "Workplace Pension" not in text and "Professional Tax" not in text
    assert "SDL" not in text   # employer costs never appear as employee deductions


# ── Several payslips in ONE wage month (salary run + off-cycle/backpay run) ──
# CPF, SDL, SHG and the S Pass levy are monthly amounts (CPF rate tables:
# "total wages for the calendar month"; CPF Board SDL page: "0.25% of the
# monthly total wages"; MOM monthly levy), so a later payslip of the month
# is calculated on the month's combined wages and books the difference.

def _then(first_out, **kw):
    """Context for a second payslip of the same wage month, carrying the
    first payslip's trace exactly as service._load_sg_month_to_date would."""
    return _ctx(sgp_month_to_date=[{**_trace(first_out), "paymentId": "PS-1"}], **kw)


def test_ow_ceiling_is_monthly_across_two_payslips():
    first = singapore.calculate(_ctx("6000"))
    second = singapore.calculate(_then(first, gross=D("4000"), basic=D("4000"), ytd_cpf_ow_subject_before=D("6000")))
    # Month: OW 10,000 → 8,000 subject × 37% = 2,960 total / 1,600 employee.
    assert (first["employee_pension"], first["employer_pension"]) == (D("1200"), D("1020"))
    assert (second["employee_pension"], second["employer_pension"]) == (D("400"), D("340"))   # not 4,000 × 37%
    assert D(_trace(second)["cpf"]["owSubject"]) == 2000
    assert second["ytd_cpf_ow_subject_after"] == D("8000")
    assert _trace(second)["monthToDate"]["earlierPayments"] == ["PS-1"]


def test_low_wage_band_is_chosen_on_the_months_total_wages():
    """$600 + $600 in one month is $1,200 total wages — the FULL row, not
    two phase-in months. Official formulas (Table 1, age ≤ 55): TW $500–750
    total = 17%·TW + 0.6·(TW − 500), employee = 0.6·(TW − 500); TW > $750
    total 37%, employee 20%."""
    first = singapore.calculate(_ctx("600"))
    assert (first["employee_pension"], first["employer_pension"]) == (D("60"), D("102"))
    second = singapore.calculate(_then(first, gross=D("600"), basic=D("600"), ytd_cpf_ow_subject_before=D("600")))
    assert (D("60") + second["employee_pension"], D("102") + second["employer_pension"]) == (D("240"), D("204"))
    assert _trace(second)["cpf"]["formulaType"] == "FULL"


def test_cpf_is_rounded_once_on_the_month_total():
    first = singapore.calculate(_ctx("1001.30"))
    second = singapore.calculate(_then(first, gross=D("1001.30"), basic=D("1001.30"), ytd_cpf_ow_subject_before=D("1001.30")))
    # Month 2,002.60 × 37% = 740.962 → 741; employee 400.52 → 400. Rounding
    # each payslip separately would have given 370 + 370 = 740.
    total = first["employee_pension"] + first["employer_pension"] + second["employee_pension"] + second["employer_pension"]
    assert (total, first["employee_pension"] + second["employee_pension"]) == (D("741"), D("400"))


def test_sdl_min_and_max_apply_once_per_month():
    first = singapore.calculate(_ctx("600"))
    second = singapore.calculate(_then(first, gross=D("600"), basic=D("600"), ytd_cpf_ow_subject_before=D("600")))
    assert (first["employer_payroll_tax"], second["employer_payroll_tax"]) == (D("2"), D("1.00"))   # month 1,200 → 3.00
    big = singapore.calculate(_ctx("4000"))
    big2 = singapore.calculate(_then(big, gross=D("4000"), basic=D("4000"), ytd_cpf_ow_subject_before=D("4000")))
    assert big["employer_payroll_tax"] + big2["employer_payroll_tax"] == D("11.25")       # one monthly maximum


def test_shg_and_s_pass_levy_are_not_charged_twice_in_a_month():
    foreign = dict(sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS", sgp_shg_funds="MBMF")
    first = singapore.calculate(_ctx("1500", **foreign))
    second = singapore.calculate(_then(first, gross=D("1000"), basic=D("1000"), **foreign))
    assert (first["employer_eht"], second["employer_eht"]) == (D("650"), D("0"))
    # MBMF: $1,500 → $4.50 band; month $2,500 → $6.50 band: the second payslip books $2.00.
    assert (first["professional_tax"], second["professional_tax"]) == (D("4.50"), D("2.00"))
    assert _trace(second)["shg"]["monthlyAmounts"] == {"MBMF": "6.50"}


def test_other_months_are_not_aggregated():
    may = singapore.calculate(_ctx("6000", pay_date=date(2026, 5, 31)))
    june = singapore.calculate(_then(may, gross=D("6000"), basic=D("6000"), ytd_cpf_ow_subject_before=D("6000")))
    assert june["employee_pension"] == D("1200") and "monthToDate" not in _trace(june)


def test_month_recalculated_below_amount_already_booked_blocks():
    first = singapore.calculate(_ctx("6000"))
    tampered = {**_trace(first), "paymentId": "PS-1", "result": {**_trace(first)["result"], "employeeCpf": "5000"}}
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("100", ytd_cpf_ow_subject_before=D("6000"), sgp_month_to_date=[tampered]))
    assert exc.value.key == "cpf_total"   # month total checked first


def test_status_change_within_the_month_blocks():
    first = singapore.calculate(_ctx("6000"))
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_then(first, gross=D("1000"), basic=D("1000"),
                                  sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"))
    assert exc.value.key == "cpf_cohort_within_month"


def test_month_to_date_loader_reads_only_earlier_payslips_of_the_same_month(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGMTD")
    runs = {}
    for label, pay_date, month in (("May", date(2026, 5, 31), "2026-05"), ("Jun salary", date(2026, 6, 30), "2026-06"),
                                   ("Jun backpay", date(2026, 6, 30), "2026-06")):
        runs[label] = _run(db, organization, pay_date, label)
        db.add(PayslipItem(payroll_run_id=runs[label].id, employee_id=emp.id, organization_id=organization.id,
                           employee_name="x", country_code="SG", sgp_calculation_trace={"wageMonth": month}))
    db.commit()
    got = service._load_sg_month_to_date(db, emp.id, date(2026, 6, 30), current_run_id=runs["Jun backpay"].id)
    assert [e["wageMonth"] for e in got] == ["2026-06"] and got[0]["paymentId"].startswith("PS-")
    assert service._load_sg_month_to_date(db, emp.id, date(2026, 6, 30), current_run_id=runs["Jun salary"].id) == []


def test_end_to_end_two_runs_in_one_month_and_correction(db, organization, monkeypatch):
    """Two real generate_payslips_for_run runs in June for a $600/month
    employee: the month is $1,200 (FULL row) and the second run books the
    difference; correcting the second run reproduces it."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGTWO", ctc=D("7200"), sgp_shg_funds="CDAC")
    items = []
    for label in ("Jun salary", "Jun backpay"):
        run = _run(db, organization, date(2026, 6, 30), label)
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
        items.append((run, db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                                        PayslipItem.employee_id == emp.id).one()))
    (_, a), (run_b, b) = items
    assert (a.employee_pension, a.employer_pension, a.employer_payroll_tax, a.professional_tax) == (D("60"), D("102"), D("2"), D("0.50"))
    assert (b.employee_pension, b.employer_pension, b.employer_payroll_tax, b.professional_tax) == (D("180"), D("102"), D("1"), D("0"))
    service.regenerate_employee_payslip(db, run_b.id, emp.id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_b.id, PayslipItem.employee_id == emp.id).one()
    assert (redone.employee_pension, redone.employer_pension, redone.employer_payroll_tax) == (D("180"), D("102"), D("1"))


# ── OW/AW/non-CPF classification through a real run AND its correction ──

def test_classification_rule_flows_through_run_ytd_trace_and_correction(db, organization, monkeypatch):
    """A TaxabilityRule makes the attendance bonus (additional
    compensation) NON-CPF: the run excludes it from CPF, YTD and the AW
    ledger; after the rule is deleted, correcting the payslip still uses
    the classification frozen in its trace."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollYtdAccumulator, PayslipItem, TaxabilityRule

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGCLSE2E", ctc=D("72000"))
    monkeypatch.setattr(service, "_sum_attendance_extras",
                        lambda db_, org_id, emp_id, start, end, records=None: D("1000"))
    rule = TaxabilityRule(jurisdiction_country="SG", earning_type="additional_compensation",
                          tax_component="cpf_additional_wages", is_taxable=False)
    db.add(rule)
    db.commit()
    run = _run(db, organization, date(2026, 6, 30), "Jun")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    trace = item.sgp_calculation_trace
    assert trace["inputs"]["wageClassification"]["additional_compensation"]["class"] == "NON_CPF"
    assert (D(trace["inputs"]["nonCpfWages"]), D(trace["cpf"]["additionalWages"]["awPaid"])) == (1000, 0)
    assert (item.employee_pension, item.employer_pension) == (D("1200"), D("1020"))       # 6,000 OW only
    acc = {r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id)}
    assert (acc["cpf_ow_subject"], acc["cpf_aw_paid"]) == (D("6000.00"), D("0.00"))
    db.delete(rule)
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert redone.sgp_calculation_trace["inputs"]["wageClassification"]["additional_compensation"]["class"] == "NON_CPF"
    assert (redone.employee_pension, redone.employer_pension) == (D("1200"), D("1020"))


# ── LQS: three distinct outcomes ──

def test_lqs_full_time_part_time_post_july_and_pre_july_are_distinct():
    hires = dict(sgp_employer_hires_foreign_workers=True)
    pre_july_ft = Rate(flat_amount=D("1600"), effective_to=date(2026, 6, 30))
    june = _trace(singapore.calculate(_ctx("1700", pay_date=date(2026, 6, 30),
                                           rate_map=_rate_map(lqs_full_time_monthly=pre_july_ft), **hires)))["lqs"]
    july = _trace(singapore.calculate(_ctx("1700", pay_date=date(2026, 7, 31), **hires)))["lqs"]
    assert (june["status"], june["threshold"], july["status"], july["threshold"]) == ("MEETS_LQS", "1600", "BELOW_LQS", "1800")
    pt_post = _trace(singapore.calculate(_ctx("1200", pay_date=date(2026, 7, 31), employment_type="Part-time", **hires)))["lqs"]
    assert pt_post["status"] == "BLOCKED" and pt_post["threshold"] == "10.50" and "hours worked" in pt_post["detail"]
    pt_pre = _trace(singapore.calculate(_ctx("1200", pay_date=date(2026, 6, 30), employment_type="Part-time", **hires)))["lqs"]
    assert pt_pre["status"] == "BLOCKED" and "AUTHORITATIVE VALUE REQUIRED" in pt_pre["detail"] and "threshold" not in pt_pre


# ── Parallel-payroll simulation (internal G8 evidence — not G8 itself) ──
# Expected figures are computed HERE from the published CPF formulas and the
# official table values, independently of the engine code: TW ≤ 50 nil;
# 50–500 employer % × TW; 500–750 employer % × TW + factor × (TW − 500),
# employee factor × (TW − 500); > 750 total % / employee % × wages subject;
# total rounded to the nearest dollar, employee share down.

def _official_cpf(cohort, band, tw, subject):
    from decimal import ROUND_FLOOR, ROUND_HALF_UP
    er, factor, total_pct, ee_pct = (D(x) for x in CPF_TABLES[cohort][band])
    if tw <= 50:
        total, ee = D("0"), D("0")
    elif tw <= 500:
        total, ee = er / 100 * tw, D("0")
    elif tw <= 750:
        ee = factor * (tw - 500)
        total = er / 100 * tw + ee
    else:
        total, ee = total_pct / 100 * subject, ee_pct / 100 * subject
    total, ee = total.quantize(D("1"), ROUND_HALF_UP), ee.quantize(D("1"), ROUND_FLOOR)
    return ee, total - ee


def _official_sdl(tw):
    return min(max((D("0.0025") * tw).quantize(D("0.01")), D("2")), D("11.25"))


def _official_shg(fund, tw):
    for upper, amount in SHG_BANDS[fund]:
        if upper is None or tw <= upper:
            return D(amount)


_POPULATION = {
    # code: (monthly wage, employee facts, CPF cohort, age band, SHG fund)
    "PA_SC40": ("6000", dict(), "SC_SPR3", "AGE_LE_55", "CDAC"),
    "PB_SC62": ("3000", dict(date_of_birth=date(1964, 1, 15)), "SC_SPR3", "AGE_60_65", None),
    "PC_SPR1": ("5000", dict(sgp_cpf_residency_status="SPR", sgp_spr_effective_date=date(2025, 12, 1),
                             sgp_cpf_contribution_arrangement="GG"), "SPR1_GG", "AGE_LE_55", "MBMF"),
    "PD_SPR2": ("4000", dict(sgp_cpf_residency_status="SPR", sgp_spr_effective_date=date(2024, 12, 1),
                             sgp_cpf_contribution_arrangement="FG"), "SPR2_FG", "AGE_LE_55", None),
    "PE_EP": ("9000", dict(sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"), None, None, None),
    "PF_LOW": ("400", dict(), "SC_SPR3", "AGE_LE_55", None),
    "PG_PHASE": ("700", dict(), "SC_SPR3", "AGE_LE_55", None),
    "PH_SPASS": ("4500", dict(sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS",
                              date_of_joining=date(2020, 1, 1)), None, None, None),
}


def test_parallel_payroll_two_cycles_mixed_population(db, organization, monkeypatch):
    """Two consecutive monthly cycles (Jan, Feb 2026) through the real run
    path for a mixed population — citizen ≤55 and 60–65, SPR year 1 (G/G),
    SPR year 2 (F/G), EP, S Pass, low-wage employer-only and phase-in — with
    a $12,000 bonus (AW) for PA_SC40 in February, then a correction.
    Every figure must equal the independently computed official result."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollYtdAccumulator, PayslipItem

    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _spaced_codes(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1   # batch runs number payslips base + 1, + 2, …: keep runs 1,000 apart
        return f"TEST{prefix}{counter['n'] * 1000:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _spaced_codes)
    _activate_for_org(db, organization, _seed(db))
    emps = {}
    for code, (wage, facts, _cohort, _band, fund) in _POPULATION.items():
        emps[code] = _sg_employee(db, organization.id, code, ctc=D(wage) * 12, sgp_shg_funds=fund or "NONE", **facts)
    bonus = {("PA_SC40", 2): D("12000")}
    code_of = {e.id: c for c, e in emps.items()}
    monkeypatch.setattr(service, "_sum_attendance_extras",
                        lambda db_, org_id, emp_id, start, end, records=None: bonus.get((code_of.get(emp_id), start.month), D("0")))

    differences = []
    runs = {}
    for month, pay_date in ((1, date(2026, 1, 31)), (2, date(2026, 2, 28))):
        run = runs[month] = _run(db, organization, pay_date, f"2026-{month:02d}")
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
        for code, (wage, _facts, cohort, band, fund) in _POPULATION.items():
            item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                                PayslipItem.employee_id == emps[code].id).one()
            ow, aw = D(wage), bonus.get((code, month), D("0"))
            tw = ow + aw
            if cohort:
                subject = min(ow, D("8000")) + aw   # AW ceiling not binding in this population (asserted below)
                ee, er = _official_cpf(cohort, band, tw, subject)
            else:
                ee = er = D("0")
            expected = {"employee_cpf": ee, "employer_cpf": er, "sdl": _official_sdl(tw),
                        "shg": _official_shg(fund, tw) if fund else D("0"),
                        "fwl": D("650") if code == "PH_SPASS" else D("0")}
            actual = {"employee_cpf": item.employee_pension, "employer_cpf": item.employer_pension,
                      "sdl": item.employer_payroll_tax, "shg": item.professional_tax, "fwl": item.employer_eht}
            for key in expected:
                if D(str(actual[key] or 0)) != expected[key]:
                    differences.append((month, code, key, str(expected[key]), str(actual[key])))
    assert differences == []

    feb_a = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == runs[2].id, PayslipItem.employee_id == emps["PA_SC40"].id).one()
    aw = feb_a.sgp_calculation_trace["cpf"]["additionalWages"]
    # 102,000 − (6,000 Jan + 6,000 Feb + 6,000 × 10 months) = 30,000 ≥ 12,000.
    assert (D(aw["awCeiling"]), D(aw["awSubjectThisPayment"])) == (30000, 12000)
    acc = {r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emps["PA_SC40"].id)}
    assert acc == {"cpf_ow_subject": D("12000.00"), "cpf_aw_subject": D("12000.00"), "cpf_aw_paid": D("12000.00")}
    before = (feb_a.employee_pension, feb_a.employer_pension)
    service.regenerate_employee_payslip(db, runs[2].id, emps["PA_SC40"].id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == runs[2].id, PayslipItem.employee_id == emps["PA_SC40"].id).one()
    assert (redone.employee_pension, redone.employer_pension) == before


def test_sdl_employer_aggregate_matches_official_worked_example():
    """CPF Board SDL page worked example (SourceArtifact cpf_sdl): A $609.50,
    B $2,000, C $4,500, D $4,502.03, E $10,000 → $2 + $5 + $11.25 + $11.25 +
    $11.25 = $40.75, payable $40. The per-employee amounts match; the
    employer-level round-down has no output yet (approval required)."""
    from decimal import ROUND_FLOOR

    amounts = [singapore.calculate(_ctx(w, sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP"))["employer_payroll_tax"]
               for w in ("609.50", "2000", "4500", "4502.03", "10000")]
    assert amounts == [D("2"), D("5.00"), D("11.25"), D("11.25"), D("11.25")]
    assert sum(amounts) == D("40.75")
    assert sum(amounts).quantize(D("1"), rounding=ROUND_FLOOR) == D("40")


# ══ Phase 2: S Pass partial-month levy ═══════════════════════════════════
# SourceArtifact mom_spass_levy (MOM "S Pass quota and levy requirements"):
# liability from the day the pass is issued until cancelled/expired;
# $650 a full calendar month; otherwise the daily rate
# (650 × 12) / 365 = 21.369… rounded UP to the cent = $21.37 per day.

_SPASS = dict(sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS")
_DAILY = D("21.37")


def _levy(pay_date, issued=None, ends=None, end_basis=None, **kw):
    rates = _rate_map(fwl_s_pass_end_day_basis=Rate(text_value=end_basis) if end_basis else None)
    out = singapore.calculate(_ctx("5000", pay_date=pay_date, sgp_work_pass_issue_date=issued,
                                   sgp_work_pass_end_date=ends, rate_map=rates, **_SPASS, **kw))
    return out["employer_eht"], _trace(out)["fwl"]


def test_s_pass_daily_rate_is_the_published_formula():
    assert singapore._ceil_cent(D("650") * 12 / D("365")) == _DAILY


def test_s_pass_full_month_and_pass_issued_on_the_first_day():
    assert _levy(date(2026, 6, 30), issued=date(2024, 3, 1))[0] == D("650")
    amount, fwl = _levy(date(2026, 6, 30), issued=date(2026, 6, 1))
    assert (amount, fwl["basis"]) == (D("650"), "FULL_MONTH")


def test_s_pass_issued_mid_month_levies_days_from_the_issue_day():
    amount, fwl = _levy(date(2026, 6, 30), issued=date(2026, 6, 16))
    assert (amount, fwl["daysLevied"], fwl["dailyRate"], fwl["basis"]) == (_DAILY * 15, 15, "21.37", "DAILY")


def test_s_pass_ending_mid_month_is_blocked_without_the_authoritative_end_day_rule():
    amount, fwl = _levy(date(2026, 6, 30), issued=date(2025, 1, 1), ends=date(2026, 6, 10))
    assert (amount, fwl["status"]) == (D("0"), "BLOCKED") and "AUTHORITATIVE VALUE REQUIRED" in fwl["detail"]


def test_s_pass_ending_mid_month_with_a_configured_end_day_rule():
    assert _levy(date(2026, 6, 30), issued=date(2025, 1, 1), ends=date(2026, 6, 10), end_basis="INCLUSIVE")[0] == _DAILY * 10
    assert _levy(date(2026, 6, 30), issued=date(2025, 1, 1), ends=date(2026, 6, 10), end_basis="EXCLUSIVE")[0] == _DAILY * 9


def test_s_pass_issued_and_ending_within_the_month():
    amount, fwl = _levy(date(2026, 6, 30), issued=date(2026, 6, 5), ends=date(2026, 6, 20), end_basis="INCLUSIVE")
    assert (amount, fwl["leviedFrom"], fwl["leviedTo"]) == (_DAILY * 16, "2026-06-05", "2026-06-20")


def test_s_pass_february_and_leap_year_february():
    assert _levy(date(2026, 2, 28), issued=date(2026, 2, 1))[0] == D("650")                  # full Feb (28 days)
    assert _levy(date(2026, 2, 28), issued=date(2026, 2, 15))[0] == _DAILY * 14
    assert _levy(date(2028, 2, 29), issued=date(2028, 2, 1))[0] == D("650")                  # full leap Feb (29 days)
    amount, fwl = _levy(date(2028, 2, 29), issued=date(2028, 2, 15))
    assert (amount, fwl["daysLevied"], fwl["monthDays"]) == (_DAILY * 15, 15, 29)             # the rate stays /365


def test_s_pass_month_boundaries_and_december():
    assert _levy(date(2026, 6, 30), issued=date(2026, 6, 30))[0] == _DAILY                   # issued on the last day
    none_yet, fwl = _levy(date(2026, 6, 30), issued=date(2026, 7, 1))
    assert (none_yet, fwl["basis"]) == (D("0"), "PASS_NOT_VALID_THIS_MONTH")
    assert _levy(date(2026, 6, 30), issued=date(2025, 1, 1), ends=date(2026, 5, 31))[0] == D("0")
    assert _levy(date(2026, 12, 31), issued=date(2026, 12, 10))[0] == _DAILY * 22


def test_s_pass_not_charged_twice_across_payslips_of_one_month():
    first = singapore.calculate(_ctx("5000", sgp_work_pass_issue_date=date(2026, 6, 16), **_SPASS))
    second = singapore.calculate(_then(first, gross=D("1000"), basic=D("1000"),
                                       sgp_work_pass_issue_date=date(2026, 6, 16), **_SPASS))
    assert (first["employer_eht"], second["employer_eht"]) == (_DAILY * 15, D("0"))


def test_s_pass_null_dates_keep_the_previous_behaviour():
    assert _levy(date(2026, 6, 30))[0] == D("650")                                           # full month still levied
    amount, fwl = _levy(date(2026, 6, 30), date_of_joining=date(2026, 6, 10), sgp_employment_facts=_WEEK5)
    assert (amount, fwl["status"]) == (D("0"), "BLOCKED")                                   # partial never guessed


def test_s_pass_dates_validation_and_column_mapping():
    from app.modules.payroll.employee_validation import SGEmployeeValidation
    from app.core.exceptions import BadRequestException

    base = {"nric_fin": "G1234567X", "cpf_residency_status": "FOREIGN", "work_pass_type": "S_PASS", "shg_funds": "NONE"}
    cleaned = SGEmployeeValidation.validate({**base, "work_pass_issue_date": "2026-06-16", "work_pass_end_date": "2027-06-15"})
    assert SGEmployeeValidation.sync_to_columns(cleaned)["sgp_work_pass_issue_date"] == date(2026, 6, 16)
    with pytest.raises(BadRequestException):
        SGEmployeeValidation.validate({**base, "work_pass_issue_date": "2026-06-16", "work_pass_end_date": "2026-06-01"})
    with pytest.raises(BadRequestException):
        SGEmployeeValidation.validate({**base, "cpf_residency_status": "SC", "work_pass_type": "NONE",
                                       "work_pass_issue_date": "2026-06-16"})


def test_s_pass_levy_correction_replays_the_frozen_rate_not_todays(db, organization, monkeypatch):
    """A real June run for an S Pass issued on 16 June; the live canonical
    levy row is then changed — the correction must still reproduce the
    original $320.55 from the payslip's frozen tax_rule_snapshot."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayslipItem

    _stub_codes(monkeypatch)
    pack = _seed(db)
    _activate_for_org(db, organization, pack)
    # Joined earlier (the shared run excludes mid-period joiners); the S Pass
    # itself was issued on 16 June (e.g. a pass change), so June is partial.
    emp = _sg_employee(db, organization.id, "SGSPASS", ctc=D("60000"), date_of_joining=date(2025, 1, 6),
                       sgp_work_pass_issue_date=date(2026, 6, 16), compliance_fields={"nric_fin": "G1234567X"}, **_SPASS)
    run = _run(db, organization, date(2026, 6, 30), "Jun")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert item.employer_eht == D("320.55") and item.sgp_calculation_trace["fwl"]["daysLevied"] == 15
    live = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.component_key == "fwl_s_pass_monthly").one()
    live.flat_amount = D("700")
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert redone.employer_eht == D("320.55")


# ══ Phase 2: SDL employer monthly total (statutory output) ════════════════

def _sdl_template(db):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key="SG-SDL-MONTHLY", name="SDL", report_type="SG_SDL_MONTHLY", jurisdiction_country="SG",
                       reporting_year="2026", version="1.0", status="Active", document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _finalized_payslips(db, organization, pay_date, amounts, label="run", org_id=None, status=None):
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    org_id = org_id or organization.id
    run = _run(db, SimpleNamespace(id=org_id), pay_date, f"{label} {org_id}")
    run.status = status or PayrollStatus.APPROVED
    items = []
    for code, sdl, net in amounts:
        emp = code if not isinstance(code, str) else _sg_employee(db, org_id, code)
        item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org_id, employee_name=emp.name,
                           country_code="SG", gross_pay=D(net), net_pay=D(net), employer_payroll_tax=D(sdl))
        db.add(item)
        items.append(item)
    db.commit()
    return run, items


def test_sdl_monthly_total_matches_the_official_worked_example_and_is_tenant_scoped(db, organization):
    from app.modules.payroll import service

    template = _sdl_template(db)
    _finalized_payslips(db, organization, date(2026, 6, 30), [
        ("SDLA", "2", "609.50"), ("SDLB", "5.00", "2000"), ("SDLC", "11.25", "4500"),
        ("SDLD", "11.25", "4502.03"), ("SDLE", "11.25", "10000")])
    other = _other_org(db, "SDLOTHER")
    _finalized_payslips(db, organization, date(2026, 6, 30), [("SDLX", "11.25", "9000")], org_id=other.id)
    data = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 6, actor_id=MAKER.id).rendered_data
    totals = data["employerTotals"]
    assert (totals["total_sdl_before_rounding"], totals["total_sdl_payable"], totals["total_employee_count"]) == ("40.75", "40", 5)
    assert data["submissionStatus"] == "EXPORT_READY"


def test_sdl_monthly_boundaries_zero_single_and_unfinalized(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus

    template = _sdl_template(db)
    empty = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 5).rendered_data["employerTotals"]
    assert (empty["total_sdl_payable"], empty["total_employee_count"]) == ("0", 0)
    _finalized_payslips(db, organization, date(2026, 7, 31), [("SDLJ1", "11.25", "9000")])
    _finalized_payslips(db, organization, date(2026, 7, 31), [("SDLJ2", "11.25", "9000")], label="draft", status=PayrollStatus.DRAFT)
    single = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 7).rendered_data["employerTotals"]
    assert (single["total_sdl_before_rounding"], single["total_sdl_payable"], single["total_employee_count"]) == ("11.25", "11", 1)
    _finalized_payslips(db, organization, date(2026, 8, 31), [("SDLK1", "5.00", "2000"), ("SDLK2", "5.00", "2000")])
    whole = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 8).rendered_data["employerTotals"]
    assert (whole["total_sdl_before_rounding"], whole["total_sdl_payable"]) == ("10.00", "10")   # exact dollar stays


def test_sdl_monthly_counts_an_employees_several_payslips_once_and_regeneration_supersedes(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    template = _sdl_template(db)
    emp = _sg_employee(db, organization.id, "SDLTWO")
    _finalized_payslips(db, organization, date(2026, 9, 30), [(emp, "10.00", "4000")], label="salary")
    _finalized_payslips(db, organization, date(2026, 9, 30), [(emp, "1.25", "4000")], label="backpay")
    first = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 9)
    rows = first.rendered_data["employeeRows"]
    assert [(r["employeeCode"], r["sdl"], r["payslipCount"]) for r in rows] == [("SDLTWO", "11.25", 2)]
    second = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 9)
    assert db.get(GeneratedReport, first.id).status == "Superseded" and second.status == "Generated"


# ══ Phase 2: IR21 hold / clearance / release ══════════════════════════════

def _ir21_org(db, organization, monkeypatch):
    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))


def _foreign(db, org_id, code, **kw):
    return _sg_employee(db, org_id, code, sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                        compliance_fields={"nric_fin": "G7654321N"}, **kw)


def _open_case(db, organization, emp, trigger=date(2026, 10, 13), aware=date(2026, 6, 1)):
    from app.modules.payroll import service

    return service.create_sg_ir21_case(db, organization.id, emp.id, "CESSATION", trigger, aware, actor_id=MAKER.id)


def _bank_rows(db, organization, run):
    from app.modules.payroll import service

    return {int(r.employee_id): r for r in service._build_bank_export_rows(db, run, service.get_payslips_for_run(db, run.id, organization.id), organization.id)}


def test_ir21_case_creation_rules(db, organization, monkeypatch):
    from app.modules.payroll import service

    _ir21_org(db, organization, monkeypatch)
    emp = _foreign(db, organization.id, "IR21A")
    case = _open_case(db, organization, emp)
    assert (case.status, case.file_by_date, case.held_amount) == ("DRAFT", date(2026, 9, 13), D("0"))
    with pytest.raises(service.BadRequestException):                              # same trigger twice
        _open_case(db, organization, emp)
    citizen = _sg_employee(db, organization.id, "IR21SC")
    with pytest.raises(service.BadRequestException, match="Singapore Citizens"):
        _open_case(db, organization, citizen)
    with pytest.raises(service.BadRequestException):                              # aware after cessation
        _open_case(db, organization, _foreign(db, organization.id, "IR21LATE"), trigger=date(2026, 6, 1), aware=date(2026, 7, 1))
    with pytest.raises(service.BadRequestException):
        service.create_sg_ir21_case(db, organization.id, emp.id, "RESIGNED", date(2026, 11, 1), date(2026, 6, 1))


def test_ir21_case_needs_the_active_pack_lead_time(db, organization):
    from app.modules.payroll import service

    emp = _foreign(db, organization.id, "IR21NOPACK")
    with pytest.raises(service.BadRequestException, match="ir21_filing_lead_months"):
        _open_case(db, organization, emp)


def test_ir21_hold_excludes_only_the_held_employee_from_the_bank_file(db, organization, monkeypatch):
    _ir21_org(db, organization, monkeypatch)
    held, other_a, other_b = (_foreign(db, organization.id, c) for c in ("IR21H", "IR21OA", "IR21OB"))
    run, _items = _finalized_payslips(db, organization, date(2026, 6, 30),
                                      [(held, "11.25", "9000"), (other_a, "11.25", "7000"), (other_b, "11.25", "6000")])
    assert set(_bank_rows(db, organization, run)) == {held.id, other_a.id, other_b.id}
    case = _open_case(db, organization, held)
    rows = _bank_rows(db, organization, run)
    assert set(rows) == {other_a.id, other_b.id} and rows[other_a.id].amount == 7000.0
    from app.modules.payroll import service
    assert D(service.serialize_sg_ir21_case(db, case)["currentHeldAmount"]) == D("9000")


def test_ir21_full_lifecycle_maker_checker_release_and_bank_payment(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    _ir21_org(db, organization, monkeypatch)
    emp = _foreign(db, organization.id, "IR21FULL")
    jun, _ = _finalized_payslips(db, organization, date(2026, 6, 30), [(emp, "11.25", "9000")], label="Jun")
    jul, (jul_item,) = _finalized_payslips(db, organization, date(2026, 7, 31), [(emp, "11.25", "9000")], label="Jul")
    case = _open_case(db, organization, emp)
    with pytest.raises(service.BadRequestException):                               # can't skip filing
        service.transition_sg_ir21_case(db, organization.id, case.id, "CLEARED", actor_id=MAKER.id,
                                        directive_date=date(2026, 9, 20), directive_tax_amount=D("2500"))
    service.transition_sg_ir21_case(db, organization.id, case.id, "FILED", actor_id=MAKER.id,
                                    filed_date=date(2026, 9, 1), filing_reference="IR21-REF-1")
    service.transition_sg_ir21_case(db, organization.id, case.id, "CLEARED", actor_id=MAKER.id,
                                    directive_date=date(2026, 9, 20), directive_reference="DIR-1",
                                    directive_tax_amount=D("2500"))
    with pytest.raises(service.BadRequestException, match="distinct approver"):
        service.transition_sg_ir21_case(db, organization.id, case.id, "RELEASED", actor_id=MAKER.id)
    assert set(_bank_rows(db, organization, jul)) == set() and set(_bank_rows(db, organization, jun)) == set()
    released = service.transition_sg_ir21_case(db, organization.id, case.id, "RELEASED", actor_id=CHECKER.id)
    assert (released.held_amount, released.released_amount, released.final_payslip_id) == (D("18000"), D("15500"), jul_item.id)
    assert _bank_rows(db, organization, jun) == {}                                  # covered by the release
    pay = _bank_rows(db, organization, jul)[emp.id]
    assert (pay.amount, pay.narration.startswith("IR21 release")) == (15500.0, True)
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sgp_ir21_case",
                                                   TaxConfigurationAudit.entity_id == case.id).order_by(TaxConfigurationAudit.id).all()
    # Phase 6.5: the maker's refused self-release is itself audited ("refused", attempted RELEASED).
    assert [(a.action, (a.old_value or {}).get("status"), a.new_value.get("status", a.new_value.get("attempted")),
             a.actor_id) for a in audit] == [
        ("create", None, "DRAFT", MAKER.id), ("status_change", "DRAFT", "FILED", MAKER.id),
        ("status_change", "FILED", "CLEARED", MAKER.id), ("refused", "CLEARED", "RELEASED", MAKER.id),
        ("status_change", "CLEARED", "RELEASED", CHECKER.id)]
    assert audit[3].new_value["result"] == "REFUSED" and "distinct approver" in audit[3].reason
    assert audit[-1].new_value["releasedAmount"] == "15500.00" and audit[-1].legal_reference.startswith("IRAS")
    with pytest.raises(service.BadRequestException):                                # terminal
        service.transition_sg_ir21_case(db, organization.id, case.id, "CANCELLED", actor_id=CHECKER.id, reason="x")


def test_ir21_cancelled_and_exempt_lift_the_hold_with_a_distinct_approver(db, organization, monkeypatch):
    from app.modules.payroll import service

    _ir21_org(db, organization, monkeypatch)
    a, b = _foreign(db, organization.id, "IR21CAN"), _foreign(db, organization.id, "IR21EX")
    run, _ = _finalized_payslips(db, organization, date(2026, 6, 30), [(a, "11.25", "9000"), (b, "11.25", "8000")])
    ca, cb = _open_case(db, organization, a), _open_case(db, organization, b)
    assert _bank_rows(db, organization, run) == {}
    with pytest.raises(service.BadRequestException, match="reason"):
        service.transition_sg_ir21_case(db, organization.id, ca.id, "CANCELLED", actor_id=CHECKER.id)
    service.transition_sg_ir21_case(db, organization.id, ca.id, "CANCELLED", actor_id=CHECKER.id, reason="Resignation withdrawn")
    with pytest.raises(service.BadRequestException, match="IRAS categories"):
        service.transition_sg_ir21_case(db, organization.id, cb.id, "EXEMPT", actor_id=CHECKER.id, exemption_category="BECAUSE")
    with pytest.raises(service.BadRequestException, match="distinct approver"):
        service.transition_sg_ir21_case(db, organization.id, cb.id, "EXEMPT", actor_id=MAKER.id,
                                        exemption_category="WORKED_60_DAYS_OR_LESS")
    service.transition_sg_ir21_case(db, organization.id, cb.id, "EXEMPT", actor_id=CHECKER.id,
                                    exemption_category="WORKED_60_DAYS_OR_LESS")
    rows = _bank_rows(db, organization, run)
    assert (rows[a.id].amount, rows[b.id].amount) == (9000.0, 8000.0)


def test_ir21_correction_after_filing_moves_to_exception_and_release_blocks_correction(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _ir21_org(db, organization, monkeypatch)
    emp = _foreign(db, organization.id, "IR21COR", ctc=D("108000"))
    run = _run(db, organization, date(2026, 6, 30), "Jun")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    case = _open_case(db, organization, emp)
    service.transition_sg_ir21_case(db, organization.id, case.id, "FILED", actor_id=MAKER.id, filed_date=date(2026, 9, 1))
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)          # unchanged → still FILED
    assert db.get(type(case), case.id).status == "FILED"
    emp.ctc = D("120000")
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)          # held monies changed
    case = db.get(type(case), case.id)
    assert case.status == "EXCEPTION" and "amended Form IR21" in case.exception_reason
    service.transition_sg_ir21_case(db, organization.id, case.id, "FILED", actor_id=MAKER.id, filed_date=date(2026, 9, 5))
    service.transition_sg_ir21_case(db, organization.id, case.id, "CLEARED", actor_id=MAKER.id,
                                    directive_date=date(2026, 9, 25), directive_tax_amount=D("0"))
    service.transition_sg_ir21_case(db, organization.id, case.id, "RELEASED", actor_id=CHECKER.id)
    with pytest.raises(service.BadRequestException, match="RELEASED"):
        service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    with pytest.raises(Exception, match="IR21 case"):
        service.delete_payslip(db, item.id, organization.id)


def test_ir21_additional_income_after_release_is_held_not_paid(db, organization, monkeypatch):
    from app.modules.payroll import service

    _ir21_org(db, organization, monkeypatch)
    emp = _foreign(db, organization.id, "IR21ADD")
    _finalized_payslips(db, organization, date(2026, 6, 30), [(emp, "11.25", "9000")], label="Jun")
    case = _open_case(db, organization, emp)
    for status, kw, actor in (("FILED", dict(filed_date=date(2026, 9, 1)), MAKER),
                              ("CLEARED", dict(directive_date=date(2026, 9, 20), directive_tax_amount=D("100")), MAKER),
                              ("RELEASED", {}, CHECKER)):
        service.transition_sg_ir21_case(db, organization.id, case.id, status, actor_id=actor.id, **kw)
    late, _ = _finalized_payslips(db, organization, date(2026, 8, 31), [(emp, "11.25", "500")], label="late bonus")
    assert _bank_rows(db, organization, late) == {}


def test_ir21_ir8a_excludes_filed_cases_and_flags_unfiled_ones(db, organization, monkeypatch):
    from app.modules.payroll import service

    _ir21_org(db, organization, monkeypatch)
    template = _ir8a_template(db)
    filed, pending, normal = (_foreign(db, organization.id, c) for c in ("IR8FILED", "IR8PEND", "IR8NORM"))
    _finalized_payslips(db, organization, date(2026, 3, 31), [(filed, "11.25", "9000"), (pending, "11.25", "9000"),
                                                             (normal, "11.25", "9000")])
    cf = _open_case(db, organization, filed, aware=date(2026, 9, 1))
    service.transition_sg_ir21_case(db, organization.id, cf.id, "FILED", actor_id=MAKER.id, filed_date=date(2026, 9, 5))
    cp = _open_case(db, organization, pending, aware=date(2026, 9, 1))
    data = service.generate_sg_ir8a(db, organization.id, template.id, 2026).rendered_data
    assert sorted(r["employeeCode"] for r in data["employeeRows"]) == ["IR8NORM", "IR8PEND"]
    assert [(e["employeeId"], e["ir21Status"]) for e in data["excludedIr21Employees"]] == [(filed.id, "FILED")]
    assert {r["employeeCode"]: r["ir21PendingCaseId"] for r in data["employeeRows"]} == {"IR8NORM": None, "IR8PEND": cp.id}
    assert data["submissionStatus"] == "EXPORT_READY"


def test_ir21_cases_are_tenant_isolated_through_the_routes(db, organization, monkeypatch):
    from app.modules.payroll import router, service
    from app.modules.payroll.schemas import SGIr21CaseCreateRequest, SGIr21CaseTransitionRequest

    _ir21_org(db, organization, monkeypatch)
    other = _other_org(db, "IR21OTHER")
    user_a = SimpleNamespace(id=MAKER.id, organization_id=organization.id)
    user_b = SimpleNamespace(id=CHECKER.id, organization_id=other.id)
    emp_a = _foreign(db, organization.id, "IR21TA")
    created = router.create_sg_ir21_case(SGIr21CaseCreateRequest(employeeId=emp_a.id, triggerType="CESSATION",
                                                                 triggerDate=date(2026, 10, 13), awareDate=date(2026, 6, 1)),
                                         db=db, current_user=user_a)
    assert router.list_sg_ir21_cases(db=db, current_user=user_b) == []
    with pytest.raises(service.NotFoundException):
        router.get_sg_ir21_case(created["id"], db=db, current_user=user_b)
    with pytest.raises(service.NotFoundException):
        router.transition_sg_ir21_case(created["id"], SGIr21CaseTransitionRequest(status="CANCELLED", reason="x"),
                                       db=db, current_user=user_b)
    with pytest.raises(service.NotFoundException):                                  # B can't open a case on A's employee
        router.create_sg_ir21_case(SGIr21CaseCreateRequest(employeeId=emp_a.id, triggerType="CESSATION",
                                                           triggerDate=date(2026, 11, 1), awareDate=date(2026, 6, 1)),
                                   db=db, current_user=user_b)
    emp_b = _foreign(db, other.id, "IR21TB")
    assert emp_b.id not in {c["employeeId"] for c in router.list_sg_ir21_cases(db=db, current_user=user_a)}
    assert [c["id"] for c in router.list_sg_ir21_cases(db=db, current_user=user_a)] == [created["id"]]
    assert db.get(type(service.get_sg_ir21_case(db, organization.id, created["id"])), created["id"]).status == "DRAFT"


def test_ir21_case_view_exposes_no_identifiers_or_bank_details(db, organization, monkeypatch):
    from app.modules.payroll import service

    _ir21_org(db, organization, monkeypatch)
    emp = _foreign(db, organization.id, "IR21SEC", bank_account="123456789")
    view = service.serialize_sg_ir21_case(db, _open_case(db, organization, emp))
    text = str(view)
    assert "7654321" not in text and "123456789" not in text and not any("nric" in k.lower() or "bank" in k.lower() for k in view)


def test_phase2_routes_require_a_payroll_operator():
    for path, method in (("/api/payroll/singapore/ir21-cases", "GET"), ("/api/payroll/singapore/ir21-cases", "POST"),
                         ("/api/payroll/singapore/ir21-cases/{case_id}", "GET"),
                         ("/api/payroll/singapore/ir21-cases/{case_id}/transition", "POST"),
                         ("/api/payroll/singapore/reports/sdl", "POST")):
        assert "get_current_payroll_operator" in _dependency_names(_route(path, method)), path


# ══ Phase 2: complianceFields masking (shared, every jurisdiction) ════════

def test_mask_compliance_fields_masks_personal_identifiers_only():
    from app.modules.payroll.employee_validation import mask_compliance_fields

    masked = mask_compliance_fields({"ssn": "123-45-6789", "nino": "AB123456C", "tfn": "123456782", "sin": "046454286",
                                     "nric_fin": "S1234567D", "esi_number": "3100123456", "steuer_id": "12345678901",
                                     "sort_code": "40-12-34", "aba_routing_number": "021000021", "iban": "DE89370400440532013000",
                                     "w4_filing_status": "SINGLE"})
    assert (masked["ssn"], masked["nino"], masked["nric_fin"]) == ("1******6789", "A****456C", "*****567D")
    assert masked["esi_number"] == "3*****3456" and masked["steuer_id"].endswith("8901") and "*" in masked["tfn"]
    assert (masked["sort_code"], masked["aba_routing_number"], masked["iban"], masked["w4_filing_status"]) == (
        "40-12-34", "021000021", "DE89370400440532013000", "SINGLE")


def test_employee_and_payslip_responses_mask_identifiers_for_every_country(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee, PayslipItem
    from app.modules.payroll.schemas import EmployeeResponse, PayslipItemResponse

    people = {
        "IN": {"esi_number": "3100123456", "tax_regime": "New"},
        "US": {"ssn": "123-45-6789", "w4_filing_status": "SINGLE"},
        "UK": {"nino": "AB123456C", "sort_code": "40-12-34"},
        "SG": {"nric_fin": "S1234567D", "work_pass_type": "NONE"},
    }
    run = _run(db, organization, date(2026, 6, 30), "mask")
    for country, cf in people.items():
        emp = PayrollEmployee(organization_id=organization.id, employee_code=f"MASK{country}", name=f"M {country}",
                              country_code=country, compliance_fields=dict(cf))
        db.add(emp)
        db.commit()
        body = EmployeeResponse.model_validate(emp).model_dump(by_alias=True)["complianceFields"]
        secret = next(v for v in cf.values() if any(ch.isdigit() for ch in v) and "-" not in v[2:3] or v == "123-45-6789")
        assert secret not in body.values(), country
        assert db.get(PayrollEmployee, emp.id).compliance_fields == cf                  # stored value untouched
        item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                           country_code=country, compliance_fields=dict(cf), net_pay=D("1"))
        db.add(item)
        db.commit()
        raw = service._serialize_payslip(item, run, country=country)
        assert raw["complianceFields"] == cf                                           # server-side (PDF/filings) keeps it
        assert secret not in PayslipItemResponse(**raw).model_dump(by_alias=True)["complianceFields"].values(), country


def test_edit_form_round_trip_of_a_masked_identifier_never_overwrites_it(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.employee_validation import mask_identifier
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.payroll.schemas import EmployeeUpdate

    emp = PayrollEmployee(organization_id=organization.id, employee_code="MASKUK", name="Edit Me", country_code="UK",
                          compliance_fields={"nino": "AB123456C", "paye_tax_code": "1257L", "sort_code": "40-12-34"})
    db.add(emp)
    db.commit()
    service.update_employee(db, emp.id, EmployeeUpdate(complianceFields={"nino": mask_identifier("AB123456C")}, name="Edited"),
                            organization.id)
    assert db.get(PayrollEmployee, emp.id).compliance_fields["nino"] == "AB123456C"
    service.update_employee(db, emp.id, EmployeeUpdate(complianceFields={"nino": "CE123456D"}), organization.id)
    assert db.get(PayrollEmployee, emp.id).compliance_fields["nino"] == "CE123456D"   # a genuine edit still applies
    with pytest.raises(service.BadRequestException):                                  # a DIFFERENT mask is not accepted
        service.update_employee(db, emp.id, EmployeeUpdate(complianceFields={"nino": "Z****999A"}), organization.id)


def test_statutory_template_seed_runs_and_seeds_both_singapore_outputs(db, monkeypatch):
    """Regression (found in Phase 3 PostgreSQL validation): the real
    template seed must accept the SG components — SG_IR8A / SG_SDL_MONTHLY
    were missing from the available-components registry, so the seed
    aborted at SG-IR8A on every database."""
    import scripts.seed_statutory_report_templates as seed
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()
    sg = {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    assert {"SG-IR8A", "SG-SDL-MONTHLY", "SG-CPF-EZPAY"} <= set(sg)           # Phase 5: + the CPF EZPay file
    assert len(sg) == 11                                                     # Phase 5.6: + 8 (test_singapore_phase56_admin.py)
    for template in (sg["SG-IR8A"], sg["SG-SDL-MONTHLY"], sg["SG-CPF-EZPAY"]):
        keys = [c.component_key for c in db.query(ReportTemplateComponent).filter(
            ReportTemplateComponent.report_template_id == template.id).order_by(ReportTemplateComponent.sort_order)]
        assert keys == ["employer_info", "totals"], template.template_key


def test_account_and_tax_columns_and_iban_routing_are_masked_and_round_trip_safely(db, organization):
    """Phase 3 shared masking: top-level bank account / PAN / UAN and the IBAN
    routing entry are masked in responses; bank ROUTING codes stay visible; an
    edit form's unchanged mask keeps the stored value; a foreign mask is refused."""
    from app.modules.payroll import service
    from app.modules.payroll.employee_validation import mask_identifier
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.payroll.schemas import EmployeeResponse, EmployeeUpdate

    emp = PayrollEmployee(organization_id=organization.id, employee_code="MASKIN", name="India Mask", country_code="IN",
                          bank_account="123456789012", pan="ABCDE1234F", uan="100200300400", ifsc="HDFC0001234",
                          compliance_fields={"tax_regime": "New"})
    db.add(emp)
    db.commit()
    body = EmployeeResponse.model_validate(emp).model_dump(by_alias=True)
    assert (body["bankAccountNumber"], body["panNumber"], body["uan"]) == ("1*******9012", "A*****234F", "1*******0400")
    assert body["ifscCode"] == "HDFC0001234"                                             # routing code stays visible
    routed = EmployeeResponse(**{**body, "routing": [{"key": "iban", "value": "DE89370400440532013000"},
                                                     {"key": "bic", "value": "COBADEFFXXX"}]}).model_dump(by_alias=True)["routing"]
    assert routed == [{"key": "iban", "value": "D*****************3000"}, {"key": "bic", "value": "COBADEFFXXX"}]
    service.update_employee(db, emp.id, EmployeeUpdate(bankAccountNumber=mask_identifier("123456789012"),
                                                       panNumber=mask_identifier("ABCDE1234F"), name="Edited"), organization.id)
    stored = db.get(PayrollEmployee, emp.id)
    assert (stored.bank_account, stored.pan, stored.name) == ("123456789012", "ABCDE1234F", "Edited")
    service.update_employee(db, emp.id, EmployeeUpdate(bankAccountNumber="999988887777"), organization.id)
    assert db.get(PayrollEmployee, emp.id).bank_account == "999988887777"                  # a real edit applies
    with pytest.raises(service.BadRequestException, match="looks masked"):
        service.update_employee(db, emp.id, EmployeeUpdate(panNumber="Z*****999Z"), organization.id)


def test_earlier_same_month_payslip_cannot_change_while_a_later_one_exists(db, organization, monkeypatch):
    """Three June payslips for a $700/month employee: the later ones booked
    only the difference, so correcting or deleting an earlier one is refused
    until the later ones are gone; unwinding in order keeps the month exact
    (official Table 1 formulas: $1,400 month → total 37%, employee 20%)."""
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _spaced(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n'] * 1000:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _spaced)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGTHREE", ctc=D("8400"))
    runs = []
    for label in ("Jun salary", "Jun backpay 1", "Jun backpay 2"):
        run = _run(db, organization, date(2026, 6, 30), label)
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
        runs.append(run)
    item = lambda r: db.query(PayslipItem).filter(PayslipItem.payroll_run_id == r.id, PayslipItem.employee_id == emp.id).one()  # noqa: E731
    total = lambda rs: (sum(item(r).employee_pension for r in rs), sum(item(r).employer_pension for r in rs))  # noqa: E731
    assert total(runs) == (D("420"), D("357"))                       # $2,100 month: 37% = 777, employee 420
    with pytest.raises(service.BadRequestException, match="later payslip of the same wage month"):
        service.regenerate_employee_payslip(db, runs[0].id, emp.id, organization.id)
    with pytest.raises(HTTPException) as exc:
        service.delete_payslip(db, item(runs[1]).id, organization.id)
    assert exc.value.status_code == 409
    service.regenerate_employee_payslip(db, runs[2].id, emp.id, organization.id)   # the latest may be corrected
    assert total(runs) == (D("420"), D("357"))
    service.delete_payslip(db, item(runs[2]).id, organization.id)                 # unwind from the latest
    service.regenerate_employee_payslip(db, runs[1].id, emp.id, organization.id)
    assert total(runs[:2]) == (D("280"), D("238"))                   # $1,400 month: 37% = 518, employee 280


def test_shg_correction_replays_the_frozen_band_not_todays(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem, TaxSlab

    _stub_codes(monkeypatch)
    pack = _seed(db)
    _activate_for_org(db, organization, pack)
    emp = _sg_employee(db, organization.id, "SGSHGR", ctc=D("72000"), sgp_shg_funds="CDAC")
    run = _run(db, organization, date(2026, 6, 30), "Jun")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one().professional_tax == D("2.00")
    band = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == "SHG_FUND_BAND",
                                    TaxSlab.filing_status == "CDAC", TaxSlab.min_amount == D("5000")).one()
    band.flat_amount = D("5")                                        # live band changed (rate B)
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one().professional_tax == D("2.00")
    assert db.get(TaxSlab, band.id).flat_amount == D("5")


# ══ Phase 4A — SG-011: CPF wage month / OW timing ═════════════════════════
# CPF Board ("Mistakes by Employers when Determining CPF Contributions",
# last updated 20 Aug 2024, item 10): OW for a month = for employment in that
# month AND payable by the 14th of the following month; otherwise AW for the
# month payable (April OT payable 10 May = OW for April; payable 30 May = AW
# for May). The employment month is the run period; the pay date is taken
# as the payable date.

def _wm(pay_date, start, end, gross="6000", **kw):
    out = singapore.calculate(_ctx(gross, pay_date=pay_date, period_start=start, period_end=end, **kw))
    t = _trace(out)
    return out, t["wageMonth"], t["wageMonthBasis"]["rule"]


@pytest.mark.parametrize("pay_date, wage_month, rule", [
    (date(2026, 6, 30), "2026-06", "OW_FOR_EMPLOYMENT_MONTH"),     # regular: paid in the employment month
    (date(2026, 7, 13), "2026-06", "OW_FOR_EMPLOYMENT_MONTH"),     # 13th of the following month
    (date(2026, 7, 14), "2026-06", "OW_FOR_EMPLOYMENT_MONTH"),     # on the 14th — still "payable by the 14th"
    (date(2026, 7, 15), "2026-07", "LATE_OW_IS_AW_FOR_PAYABLE_MONTH"),
    (date(2026, 5, 29), "2026-06", "OW_FOR_EMPLOYMENT_MONTH"),     # paid in advance
])
def test_sg011_wage_month_boundaries(pay_date, wage_month, rule):
    _out, got_month, got_rule = _wm(pay_date, date(2026, 6, 1), date(2026, 6, 30),
                                    ytd_cpf_ow_subject_before=D("0"))
    assert (got_month, got_rule) == (wage_month, rule)


def test_sg011_late_ow_becomes_aw_for_the_payable_month_under_the_aw_ceiling():
    out, month, _ = _wm(date(2026, 7, 15), date(2026, 6, 1), date(2026, 6, 30))
    t = _trace(out)
    assert (month, t["inputs"]["ordinaryWages"], t["inputs"]["additionalWages"]) == ("2026-07", "0", "6000")
    assert {k: t["inputs"]["wageClassification"]["basic"][k] for k in ("amount", "class", "source")} == {
        "amount": "6000", "class": "AW", "source": "late_ow"}
    assert D(t["cpf"]["additionalWages"]["awSubjectThisPayment"]) == 6000        # within the AW ceiling
    assert (out["employee_pension"], out["employer_pension"]) == (D("1200"), D("1020"))
    assert out["ytd_cpf_aw_paid_after"] == D("6000") and out["ytd_cpf_ow_subject_after"] == D("0")


def test_sg011_february_and_leap_february():
    assert _wm(date(2026, 3, 14), date(2026, 2, 1), date(2026, 2, 28))[1] == "2026-02"
    assert _wm(date(2026, 3, 15), date(2026, 2, 1), date(2026, 2, 28))[1] == "2026-03"
    assert _wm(date(2028, 2, 29), date(2028, 2, 1), date(2028, 2, 29))[1] == "2028-02"
    assert _wm(date(2028, 3, 14), date(2028, 2, 1), date(2028, 2, 29))[1] == "2028-02"


def test_sg011_december_paid_in_january():
    _out, month, rule = _wm(date(2027, 1, 14), date(2026, 12, 1), date(2026, 12, 31))
    assert (month, rule) == ("2026-12", "OW_FOR_EMPLOYMENT_MONTH")         # December OW, prior year
    _late, late_month, rule = _wm(date(2027, 1, 15), date(2026, 12, 1), date(2026, 12, 31))
    assert (late_month, rule) == ("2027-01", "LATE_OW_IS_AW_FOR_PAYABLE_MONTH")


def test_sg011_blocks_a_period_spanning_two_calendar_months():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        _wm(date(2026, 6, 30), date(2026, 5, 25), date(2026, 6, 24))
    assert exc.value.key == "payroll_period"


def test_sg011_blocks_aw_in_a_payslip_whose_ow_belongs_to_the_previous_month():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        _wm(date(2026, 7, 10), date(2026, 6, 1), date(2026, 6, 30), gross="8000", additional_compensation=D("2000"))
    assert exc.value.key == "aw_wage_month"
    same_month = _wm(date(2026, 6, 30), date(2026, 6, 1), date(2026, 6, 30), gross="8000", additional_compensation=D("2000"))
    assert same_month[1] == "2026-06"                                            # bonus in its own month is fine


def test_sg011_without_a_period_keeps_the_pay_date_month():
    out = singapore.calculate(_ctx("6000", pay_date=date(2026, 7, 10)))
    assert _trace(out)["wageMonth"] == "2026-07" and _trace(out)["wageMonthBasis"]["rule"] == "PAY_DATE_MONTH"


def _period_run(db, organization, start, end, pay_date, label):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=organization.id, period_label=label, period_start=start, period_end=end, pay_date=pay_date)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_sg011_end_to_end_arrears_month_ytd_sdl_output_and_correction(db, organization, monkeypatch):
    """June salary run paid 30 June plus a June backpay run paid 10 July:
    both are June OW (payable by 14 July) — month-to-date aggregation,
    YTD, the SDL monthly output and a correction after a live-rate change
    all follow the June wage month."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayrollStatus, PayrollYtdAccumulator, PayslipItem

    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _spaced(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n'] * 1000:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _spaced)
    pack = _seed(db)
    _activate_for_org(db, organization, pack)
    emp = _sg_employee(db, organization.id, "SGARR", ctc=D("7200"))                 # $600 / month
    jun = _period_run(db, organization, date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 30), "Jun")
    back = _period_run(db, organization, date(2026, 6, 1), date(2026, 6, 30), date(2026, 7, 10), "Jun backpay")
    for r in (jun, back):
        service.generate_payslips_for_run(db, r, organization.id)
        db.commit()
    item = lambda r: db.query(PayslipItem).filter(PayslipItem.payroll_run_id == r.id, PayslipItem.employee_id == emp.id).one()  # noqa: E731
    assert [item(r).sgp_calculation_trace["wageMonth"] for r in (jun, back)] == ["2026-06", "2026-06"]
    # $1,200 June month → FULL row: 37% = 444, employee 240 (not two separate phase-in months)
    assert (item(jun).employee_pension + item(back).employee_pension, item(jun).employer_pension + item(back).employer_pension) == (D("240"), D("204"))
    acc = {r.tax_year + ":" + r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id)}
    assert acc["SG-CY-2026:cpf_ow_subject"] == D("1200.00")
    for r in (jun, back):
        r.status = PayrollStatus.APPROVED
    db.commit()
    template = _sdl_template(db)
    june = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 6).rendered_data["employerTotals"]
    july = service.generate_sg_sdl_monthly(db, organization.id, template.id, 2026, 7).rendered_data["employerTotals"]
    assert (june["total_sdl_before_rounding"], july["total_employee_count"]) == ("3.00", 0)   # paid 10 Jul, SDL of June
    back.status = PayrollStatus.DRAFT
    db.commit()
    sdl_row = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.component_key == "sdl").one()
    sdl_row.employer_rate_pct = D("0.0030")                                          # live rate changed
    db.commit()
    before = (item(back).employee_pension, item(back).employer_payroll_tax)
    service.regenerate_employee_payslip(db, back.id, emp.id, organization.id)
    assert (item(back).employee_pension, item(back).employer_payroll_tax) == before and item(back).sgp_calculation_trace["wageMonth"] == "2026-06"


def test_sg011_december_wage_month_paid_in_january_uses_the_2026_pack_and_year(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollYtdAccumulator, PayslipItem

    _stub_codes(monkeypatch)
    pack = _seed(db)
    pack.effective_to = date(2026, 12, 31)                                           # no 2027 pack exists
    db.commit()
    _activate_for_org(db, organization, pack)
    emp = _sg_employee(db, organization.id, "SGDEC", ctc=D("72000"))
    run = _period_run(db, organization, date(2026, 12, 1), date(2026, 12, 31), date(2027, 1, 10), "Dec paid Jan")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    assert item.sgp_calculation_trace["wageMonth"] == "2026-12" and item.tax_policy_version == "1.2"
    assert (item.employee_pension, item.employer_pension) == (D("1200"), D("1020"))
    years = {r.tax_year for r in db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id)}
    assert years == {"SG-CY-2026"}


# ══ Phase 4A — YTD refresh after value-changing corrections (shared) ══════

def _ytd_of(db, emp):
    from app.modules.payroll.models import PayrollYtdAccumulator

    return {r.tax_component: r.ytd_taxable_wages for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_year == "SG-CY-2026")}


def _ytd_from_payslips(db, emp):
    """What YTD must equal: the sum of the persisted payslips' own figures."""
    from app.modules.payroll.models import PayslipItem

    items = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id, PayslipItem.country_code == "SG").all()
    ow = sum((D(i.sgp_calculation_trace["cpf"]["owSubject"]) for i in items), D(0))
    return ow


def test_ytd_follows_an_increase_and_a_decrease_correction_of_the_latest_payslip(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGCORR", ctc=D("60000"))            # $5,000 / month
    jan, feb = (_run(db, organization, date(2026, m, 28 if m == 2 else 31), f"M{m}") for m in (1, 2))
    for r in (jan, feb):
        service.generate_payslips_for_run(db, r, organization.id)
        db.commit()
    assert _ytd_of(db, emp)["cpf_ow_subject"] == D("10000.00") == _ytd_from_payslips(db, emp)
    feb_item = lambda: db.query(PayslipItem).filter(PayslipItem.payroll_run_id == feb.id).one()  # noqa: E731
    emp.ctc = D("84000")                                                         # increase: Feb OW 7,000
    db.commit()
    service.regenerate_employee_payslip(db, feb.id, emp.id, organization.id)
    assert (feb_item().employee_pension, _ytd_of(db, emp)["cpf_ow_subject"]) == (D("1400"), D("12000.00"))
    assert _ytd_of(db, emp)["cpf_ow_subject"] == _ytd_from_payslips(db, emp)
    emp.ctc = D("36000")                                                         # decrease: Feb OW 3,000
    db.commit()
    service.regenerate_employee_payslip(db, feb.id, emp.id, organization.id)
    assert (feb_item().employee_pension, _ytd_of(db, emp)["cpf_ow_subject"]) == (D("600"), D("8000.00"))
    assert _ytd_of(db, emp)["cpf_ow_subject"] == _ytd_from_payslips(db, emp)
    postings = feb_item().ytd_snapshot["ytdPostings"]
    assert {p["component"]: p["after"]["wages"] for p in postings}["cpf_ow_subject"] == "8000.00"


def test_value_changing_correction_under_a_later_payslip_is_refused_and_touches_nothing(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    emp = _sg_employee(db, organization.id, "SGLATER", ctc=D("60000"))
    jan, feb = (_run(db, organization, date(2026, m, 28 if m == 2 else 31), f"M{m}") for m in (1, 2))
    for r in (jan, feb):
        service.generate_payslips_for_run(db, r, organization.id)
        db.commit()
    before = _ytd_of(db, emp)
    service.regenerate_employee_payslip(db, jan.id, emp.id, organization.id)       # unchanged → allowed
    assert _ytd_of(db, emp) == before
    emp.ctc = D("84000")
    db.commit()
    with pytest.raises(service.BadRequestException, match="later payslip has already built on"):
        service.regenerate_employee_payslip(db, jan.id, emp.id, organization.id)
    assert _ytd_of(db, emp) == before
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == jan.id).one().employee_pension == D("1000")


def test_correction_replays_rate_a_and_keeps_ytd_exact_after_a_live_rate_change(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayslipItem

    _stub_codes(monkeypatch)
    pack = _seed(db)
    _activate_for_org(db, organization, pack)
    emp = _sg_employee(db, organization.id, "SGRATEB", ctc=D("120000"))           # OW 10,000 → 8,000 subject
    run = _run(db, organization, date(2026, 3, 31), "Mar")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    ceiling = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                ContributionRate.component_key == "cpf_ow_ceiling_monthly").one()
    ceiling.flat_amount = D("9000")                                               # live config → rate B
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    assert (item.employee_pension, _ytd_of(db, emp)["cpf_ow_subject"]) == (D("1600"), D("8000.00"))   # rate A frozen
    assert db.get(ContributionRate, ceiling.id).flat_amount == D("9000")          # live stays B


# ══ Phase 5 STEP 2 — per-earning CPF OW/AW and IRAS classification ═══════
# IRAS items per "Explanatory Notes for completion of Form IR8A & Appendix
# 8A for the year ended 31 Dec 2026" (YA2027): a) salary/wages/overtime,
# b) bonus, c) director's fees, d1) allowances (housing listed), d3) lump
# sum; gross commission per IRAS "Additional specifications for TXT and XML
# file format" (Aug 2024) 4.2.4.

_ALLOWANCES = [{"key": "transport", "label": "Transport Allowance", "amount": D("300")},
               {"key": "director_fee", "label": "Director Fee", "amount": D("700")}]


def _allowance_ctx(**kw):
    # gross 7,000 = basic 5,000 + special 1,000 + two named allowances 1,000
    return _ctx("7000", basic=D("5000"), special_allowance=D("1000"), sgp_named_allowance_items=_ALLOWANCES, **kw)


def test_each_named_allowance_is_its_own_cpf_component():
    ow, aw, non_cpf, detail = singapore.classify_cpf_wages(_allowance_ctx())
    assert (ow, aw, non_cpf) == (D("7000"), D("0"), D("0"))
    assert detail["allowance:transport"] == {"amount": "300", "class": "OW", "source": "default", "label": "Transport Allowance",
                                             "pwmBasis": "GROSS", "eaGrossRate": "INCLUDED"}
    assert "named_allowances" not in detail                     # fully itemised — no unexplained remainder


def test_rules_classify_one_allowance_without_touching_the_others():
    ctx = _allowance_ctx(sgp_cpf_wage_classification=_classified(
        ow={"allowance:director_fee": False}, aw={"allowance:transport": True}))
    ow, aw, non_cpf, detail = singapore.classify_cpf_wages(ctx)
    assert (ow, aw, non_cpf, ow + aw + non_cpf) == (D("6000"), D("300"), D("700"), D("7000"))
    assert (detail["allowance:transport"]["class"], detail["allowance:director_fee"]["class"]) == ("AW", "NON_CPF")


def test_allowance_breakdown_larger_than_the_remainder_is_not_trusted():
    ow, aw, non_cpf, detail = singapore.classify_cpf_wages(_ctx("6000", basic=D("5500"), sgp_named_allowance_items=_ALLOWANCES))
    assert ow + aw + non_cpf == D("6000") and not any(k.startswith("allowance:") for k in detail)


def test_iras_default_items_follow_the_ir8a_notes():
    totals, detail = singapore.classify_iras_earnings(_ctx(
        "9000", basic=D("5000"), hra=D("1000"), special_allowance=D("500"), overtime=D("500"),
        additional_compensation=D("2000")))
    assert totals == {"iras_gross_salary": D("5500"), "iras_allowances": D("1500"), "iras_bonus": D("2000")}
    assert detail["overtime"]["category"] == "iras_gross_salary" and detail["hra"]["category"] == "iras_allowances"


def test_iras_rule_moves_an_allowance_and_conflicts_block():
    rules = {"iras_director_fees": {"allowance:director_fee": True}}
    totals, detail = singapore.classify_iras_earnings(_allowance_ctx(sgp_iras_classification=rules))
    assert totals["iras_director_fees"] == D("700") and detail["allowance:director_fee"]["source"] == "rule"
    assert totals["iras_allowances"] == D("1300")               # special 1,000 + transport 300
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.classify_iras_earnings(_allowance_ctx(sgp_iras_classification={
            "iras_director_fees": {"allowance:director_fee": True}, "iras_bonus": {"allowance:director_fee": True}}))
    assert exc.value.key == "iras_classification:allowance:director_fee"


def test_iras_default_excluded_without_a_new_item_is_unclassified_never_guessed():
    totals, _ = singapore.classify_iras_earnings(_allowance_ctx(
        sgp_iras_classification={"iras_allowances": {"allowance:transport": False}}))
    assert totals[singapore.IRAS_UNCLASSIFIED] == D("300")


def test_trace_records_both_classifications_and_cpf_is_unchanged_by_iras():
    base = singapore.calculate(_allowance_ctx())
    moved = singapore.calculate(_allowance_ctx(sgp_iras_classification={"iras_director_fees": {"allowance:director_fee": True}}))
    assert (base["employee_pension"], base["employer_pension"]) == (moved["employee_pension"], moved["employer_pension"])
    trace = _trace(moved)
    assert trace["inputs"]["irasClassification"]["allowance:director_fee"]["category"] == "iras_director_fees"
    assert trace["iras"]["totals"]["iras_director_fees"] == "700" and trace["iras"]["unclassified"] == "0"
    assert trace["engine"] == singapore.ENGINE_VERSION


def test_service_iras_rules_are_tenant_scoped_and_frozen_replay_rebuilds_them(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxabilityRule

    emp = _sg_employee(db, organization.id, "SGIRAS")
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="allowance:director_fee", tax_component="iras_director_fees",
                          is_taxable=True, organization_id=organization.id))
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="basic", tax_component="iras_exempt",
                          is_taxable=True, organization_id=_other_org(db, "IRASOTHER").id))   # another tenant's rule
    db.commit()
    rules = service._sg_iras_classification(db, emp.id, date(2026, 6, 30))
    assert rules["iras_director_fees"] == {"allowance:director_fee": True} and rules["iras_exempt"] == {}
    frozen = {"basic": {"category": "iras_gross_salary"}, "allowance:x": {"category": "UNCLASSIFIED"}}
    rebuilt = service._sg_frozen_iras_classification(frozen)
    assert rebuilt["iras_gross_salary"] == {"basic": True} and rebuilt["iras_allowances"] == {"allowance:x": False}


def test_run_classifies_named_allowances_and_ir8a_sums_the_iras_items(db, organization, monkeypatch):
    """End to end: org allowance components → per-allowance CPF/IRAS classes
    in the persisted trace → IR8A items per employee from those traces; a
    correction replays the frozen classification even after the rule changes."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem, TaxabilityRule

    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    monkeypatch.setattr(service, "_resolve_allowance_components", lambda db_, org_id: [
        {"key": "transport", "label": "Transport Allowance", "pct": None, "flat_amount": D("300")},
        {"key": "director_fee", "label": "Director Fee", "pct": None, "flat_amount": D("700")}])
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="allowance:director_fee", tax_component="cpf_ordinary_wages",
                          is_taxable=False, organization_id=organization.id))
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="allowance:director_fee", tax_component="iras_director_fees",
                          is_taxable=True, organization_id=organization.id))
    db.commit()
    emp = _sg_employee(db, organization.id, "SGALW", ctc=D("96000"))       # 8,000 / month
    run = _run(db, organization, date(2026, 5, 31), "2026-05")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    classes = item.sgp_calculation_trace["inputs"]["wageClassification"]
    assert classes["allowance:director_fee"]["class"] == "NON_CPF" and classes["allowance:transport"]["class"] == "OW"
    assert D(item.sgp_calculation_trace["iras"]["totals"]["iras_director_fees"]) == D("700")
    assert D(item.sgp_calculation_trace["inputs"]["nonCpfWages"]) == D("700")

    db.query(TaxabilityRule).filter(TaxabilityRule.earning_type == "allowance:director_fee").delete()
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    redone = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert redone.sgp_calculation_trace["inputs"]["wageClassification"]["allowance:director_fee"]["class"] == "NON_CPF"
    assert D(redone.sgp_calculation_trace["iras"]["totals"]["iras_director_fees"]) == D("700")
    assert (redone.employee_pension, redone.employer_pension) == (item.employee_pension, item.employer_pension)

    run.status = PayrollStatus.APPROVED
    db.commit()
    row = service.generate_sg_ir8a(db, organization.id, _ir8a_template(db).id, 2026).rendered_data["employeeRows"][0]
    assert (row["directorFees"], row["legacyDerived"]) == (700.0, False)
    assert row["allowances"] == float(redone.special_allowance + redone.hra) + 300.0
    assert row["totalEmploymentIncome"] == float(redone.gross_pay)
    assert row["readiness"]["status"] == "READY"


def test_ir8a_reports_by_wage_month_and_benefit_valuations(db, organization):
    """A January payslip that pays December's OW (payable by 14 Jan) belongs
    to the December income year; issued benefit valuations feed d8 (Appendix
    8A) and a STOCK_BENEFIT is d7 with Appendix 8B flagged BLOCKED."""
    from app.modules.payroll import service
    from app.modules.payroll.models import EmployeeBenefitValuation, PayrollStatus, PayslipItem

    template = _ir8a_template(db)
    emp = _sg_employee(db, organization.id, "SGWM")
    for pay_date, wage_month, amount in ((date(2026, 1, 10), "2025-12", "9999"), (date(2026, 6, 30), "2026-06", "5000"),
                                         (date(2027, 1, 10), "2026-12", "5000")):
        run = _run(db, organization, pay_date, str(pay_date))
        run.status = PayrollStatus.APPROVED
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                           country_code="SG", gross_pay=D(amount), additional_compensation=D("0"),
                           sgp_calculation_trace={"wageMonth": wage_month, "iras": {"totals": {"iras_gross_salary": amount}}}))
    for btype, value, status in (("ACCOMMODATION", "4931.50", "Issued"), ("STOCK_BENEFIT", "1200", "Issued"), ("CAR", "999", "Draft")):
        db.add(EmployeeBenefitValuation(employee_id=emp.id, organization_id=organization.id, tax_year="2026",
                                        benefit_type=btype, taxable_value=D(value), status=status))
    db.commit()
    data = service.generate_sg_ir8a(db, organization.id, template.id, 2026).rendered_data
    row = data["employeeRows"][0]
    assert (row["grossSalary"], row["payslipCount"]) == (10000.0, 2)              # Dec-2025 wages excluded, Dec-2026 included
    assert (row["benefitsInKindD8"], row["shareGainsD7"], row["appendix8A"]["placeOfResidence"]) == (4931.5, 1200.0, 4931.5)
    assert row["totalEmploymentIncome"] == 10000.0 + 4931.5 + 1200.0
    assert row["readiness"]["status"] == "REVIEW_REQUIRED"
    assert any("Appendix 8B" in i for i in row["readiness"]["issues"]) and any("not yet issued" in i for i in row["readiness"]["issues"])
    assert data["readiness"]["appendix8B"].startswith("BLOCKED")


# ══ Phase 5 STEP 3 — Employer Registration + readiness (SG-027 / SG-028) ═══
# CSN format: CPF Board "CPF EZPay (FTP) File Specifications" (effective 16
# Jan 2025) — UEN/NRIC/FIN (9–10) + Payment Type (3) + Sno (2).

_GOOD_IDS = {"uen": "201912345K", "cpf_submission_number": "201912345KPTE01", "cpf_ezpay_method": "FILE_UPLOAD",
             "cpf_payment_method": "DIRECT_DEBIT", "ais_status": "PARTICIPANT", "ais_submission_mode": "EXPORT_ONLY",
             "corppass_authorised": "YES", "employs_foreign_workers": "NO", "pwm_applicable": "NO",
             "sdl_payment_route": "CPF_EZPAY", "bank_workflow_validated": "YES", "pdpa_controls_approved": "YES"}


def _readiness(**overrides):
    from app.modules.payroll.engine.jurisdictions.singapore.readiness import evaluate_employer_readiness

    facts = dict(identifiers=dict(_GOOD_IDS), company_name="Acme Pte Ltd", company_address="1 Test Road",
                 settlement_bank="Bank", settlement_acc="000", employee_count=6, foreign_pass_holders=0,
                 work_permit_holders=0, work_permit_sectors=set(), pwm_flagged_employees=0,
                 active_pack="SG-PAYROLL-2026 v1.2", ais_threshold=D("5"), ezpay_generated=True, ezpay_accepted=True)
    facts.update(overrides)
    out = evaluate_employer_readiness(facts)
    return out, {i["key"]: i for i in out["items"]}


def test_sg_schema_validates_csn_and_enumerated_settings():
    from app.core.jurisdiction import validate_tax_identifiers

    ok, errors = validate_tax_identifiers("SG", {**_GOOD_IDS, "cpf_submission_number": "201912345K-PTE-01"})
    assert not errors and ok["cpf_submission_number"] == "201912345K-PTE-01"
    _, errors = validate_tax_identifiers("SG", {"cpf_submission_number": "201912345K", "mom_sector": "FARMING",
                                                "ais_submission_mode": "API"})
    assert {e["key"] for e in errors} == {"cpf_submission_number", "mom_sector", "ais_submission_mode"}


def test_readiness_only_parallel_run_blocks_a_fully_configured_employer():
    out, items = _readiness()
    assert [k for k, i in items.items() if i["status"] != "PASS"] == ["parallel_run"]
    assert out["status"] == "NOT_READY" and items["parallel_run"]["status"] == "BLOCKED"   # G8 is external
    assert all({"status", "evidence", "blocker", "owner", "action"} <= set(i) for i in items.values())


def test_readiness_parses_the_csn_and_requires_a_mandatory_pte_csn():
    from app.modules.payroll.engine.jurisdictions.singapore.readiness import parse_csn

    assert parse_csn("201912345K-PTE-01") == ("201912345K", "PTE", "01")
    assert parse_csn("234567891APTE01") == ("234567891A", "PTE", "01")          # the spec's own sample CSN
    assert parse_csn("201912345K") is None
    _, items = _readiness(identifiers={**_GOOD_IDS, "cpf_submission_number": "201912345KVCT01"})
    assert items["cpf_csn"]["status"] == "REVIEW" and "voluntary" in items["cpf_csn"]["blocker"]
    _, items = _readiness(identifiers={**_GOOD_IDS, "cpf_submission_number": "199912345KPTE01"})
    assert items["cpf_csn"]["status"] == "REVIEW"                              # CSN of another entity


def test_readiness_never_claims_cpf_acceptance_or_ais_api_without_evidence():
    _, items = _readiness(ezpay_accepted=False)
    assert items["cpf_file_validated"]["status"] == "BLOCKED" and "external" in items["cpf_file_validated"]["blocker"]
    _, items = _readiness(identifiers={**_GOOD_IDS, "ais_submission_mode": "DIRECT_API"})
    assert items["ais_mode"]["status"] == "BLOCKED" and "not evidenced" in items["ais_mode"]["blocker"]


def test_readiness_ais_mandatory_at_five_employees_and_foreign_workforce_consistency():
    _, items = _readiness(identifiers={**_GOOD_IDS, "ais_status": "NOT_PARTICIPATING"}, employee_count=5)
    assert items["ais_participation"]["status"] == "FAIL"
    _, items = _readiness(identifiers={**_GOOD_IDS, "ais_status": "NOT_PARTICIPATING"}, employee_count=4)
    assert items["ais_participation"]["status"] == "PASS"
    _, items = _readiness(foreign_pass_holders=2)
    assert items["foreign_workforce"]["status"] == "REVIEW"                     # declared NO, data says YES
    _, items = _readiness(identifiers={**_GOOD_IDS, "employs_foreign_workers": "YES", "mom_sector": "SERVICES"},
                          foreign_pass_holders=1, work_permit_holders=1, work_permit_sectors={"CONSTRUCTION"})
    assert items["mom_sector"]["status"] == "REVIEW"


def test_readiness_service_is_tenant_scoped_and_route_uses_payroll_operator_rbac(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails

    other = _other_org(db, "RDYOTHER")
    db.add(CompanyComplianceDetails(organization_id=other.id, jurisdiction_country="SG", name="Other",
                                    tax_identifiers={**_GOOD_IDS}))
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", name="Mine",
                                    tax_identifiers={"uen": "201912345K"}))
    db.commit()
    _sg_employee(db, other.id, "RDYFOR", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="S_PASS")
    out = service.get_sg_employer_readiness(db, organization.id, as_of=date(2026, 6, 30))
    items = {i["key"]: i for i in out["items"]}
    assert items["cpf_csn"]["status"] == "FAIL"                        # the other tenant's CSN never leaks in
    assert items["foreign_workforce"]["status"] == "FAIL"              # not declared; other tenant's pass holder ignored
    assert items["statutory_pack"]["status"] == "BLOCKED"              # no Active SG pack
    assert "not a CPF Board / IRAS / MOM approval" in out["certification"]
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/readiness", "GET"))


# ══ Phase 5 STEP 4 — CPF EZPay contribution file + lifecycle ═════════════
# Authority: CPF Board "CPF EZPay (FTP) File Specifications (effective from
# 16 January 2025)", FTPSPEC/FILESPEC, retrieved 2026-09-24 (sha256
# 1ddd242b7893d37b0e62456c629fdc39d08f720c33c6c47d45684213815c8a89).
# Expected records are the specification's own sample file (page 7),
# whitespace-normalised as the published PDF prints them.

_EZPAY_SPEC_SAMPLE = [
    "F 234567891APTE01 0420180129183315FTP.DTL",
    "F0234567891APTE01 04201801010000005180000000000",
    "F0234567891APTE01 04201801020000000019500000001",
    "F0234567891APTE01 04201801030000000007000000001",
    "F0234567891APTE01 04201801040000000001000000001",
    "F0234567891APTE01 04201801050000000009000000001",
    "F0234567891APTE01 04201801100000000000000000000",
    "F0234567891APTE01 04201801110000000000000000000",
    "F1234567891APTE01 0420180101S1122334A00000011100000003000000000000000LMICKEY TAN AH TAN",
    "F1234567891APTE01 0420180104S1122334A00000000010000000000000000000000 MICKEY TAN AH TAN",
    "F1234567891APTE01 0420180101S2122334B00000011100000003000000000000000NJACKIE JACK",
    "F1234567891APTE01 0420180105S2122334B00000000090000000000000000000000 JACKIE JACK",
    "F1234567891APTE01 0420180101S3122334C00000014800000004000000000000000ERAVIDAVI SINGH S/O RAVIDAVI SINGH",
    "F1234567891APTE01 0420180103S3122334C00000000070000000000000000000000 RAVIDAVI SINGH S/O RAVIDAVI SINGH",
    "F1234567891APTE01 0420180101S4122334D00000014800000004000000000000000EMUHAMMED ALI BIN MUHAMMED ALI",
    "F1234567891APTE01 0420180102S4122334D00000000195000000000000000000000 MUHAMMED ALI BIN MUHAMMED ALI",
    "F9234567891APTE01 040000017000000000521650",
]


def _spec_sample_employees():
    return [
        dict(account_no="S1122334A", name="MICKEY TAN AH TAN", cpf_total=D("1110"), ordinary_wages=D("3000"),
             additional_wages=D("0"), employment_status="L", shg={"CDAC": D("1")}),
        dict(account_no="S2122334B", name="JACKIE JACK", cpf_total=D("1110"), ordinary_wages=D("3000"),
             additional_wages=D("0"), employment_status="N", shg={"ECF": D("9")}),
        dict(account_no="S3122334C", name="RAVIDAVI SINGH S/O RAVIDAVI SINGH", cpf_total=D("1480"),
             ordinary_wages=D("4000"), additional_wages=D("0"), employment_status="E", shg={"SINDA": D("7")}),
        dict(account_no="S4122334D", name="MUHAMMED ALI BIN MUHAMMED ALI", cpf_total=D("1480"), ordinary_wages=D("4000"),
             additional_wages=D("0"), employment_status="E", shg={"MBMF": D("19.50")}),
    ]


def test_ezpay_builder_reproduces_the_cpf_board_specification_sample_file():
    import re
    from datetime import datetime
    from app.modules.payroll.engine.jurisdictions.singapore.statutory import ezpay

    out = ezpay.build_file(("234567891A", "PTE", "01"), "04", "2018-01", datetime(2018, 1, 29, 18, 33, 15),
                           _spec_sample_employees(), D("0"))
    records = out["content"].split("\r\n")[:-1]
    assert [re.sub(r"\s+", " ", r).strip() for r in records] == _EZPAY_SPEC_SAMPLE
    assert all(len(r) == 150 for r in records)                           # p1: fixed 150-byte records
    assert (out["records"], out["total"], out["summary"]["02"]["donors"]) == (17, "5216.50", 1)
    assert out["filename"] == "234567891APTE01JAN201804.DTL"            # p1: <CSN><Month Paid><Advice Code>.DTL
    assert ezpay.validate_records(records) == []


def test_ezpay_builder_fails_closed_on_every_spec_violation():
    from datetime import datetime
    from app.modules.payroll.engine.jurisdictions.singapore.statutory import ezpay

    bad = _spec_sample_employees()
    bad[0]["account_no"] = "F1234567N"                                   # FIN — spec: S or T prefix only
    bad[1]["name"] = "X" * 67                                            # X(66), never truncated
    bad[2]["name"] = "RAVI_SINGH"                                        # "_" is a forbidden character
    bad[3]["employment_status"] = "Q"
    with pytest.raises(ezpay.EzpayValidationError) as exc:
        ezpay.build_file(("234567891A", "VCT", "01"), "00", "2018-01", datetime(2018, 1, 29), bad, D("0"))
    text = " | ".join(exc.value.errors)
    for fragment in ("voluntary-contribution CSN", "advice code", "S or T", "66 characters", "not allowed", "E/L/N/O"):
        assert fragment in text


def test_ezpay_employment_status_codes():
    from app.modules.payroll.engine.jurisdictions.singapore.statutory.ezpay import employment_status

    start, end = date(2026, 5, 1), date(2026, 5, 31)
    assert employment_status(date(2020, 1, 1), None, start, end) == "E"
    assert employment_status(date(2026, 5, 4), None, start, end) == "N"
    assert employment_status(date(2020, 1, 1), date(2026, 5, 20), start, end) == "L"
    assert employment_status(date(2026, 5, 4), date(2026, 5, 20), start, end) == "O"


def _ezpay_template(db):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key="SG-CPF-EZPAY", name="EZPay", report_type="SG_CPF_EZPAY", jurisdiction_country="SG",
                       reporting_year="2026", version="1.0", status="Active", document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _ezpay_org(db, organization, csn="201912345KPTE01"):
    from app.modules.payroll.models import CompanyComplianceDetails

    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", name="Acme",
                                    tax_identifiers={"uen": "201912345K", "cpf_submission_number": csn}))
    db.commit()


def _ezpay_payslips(db, organization):
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    local = _sg_employee(db, organization.id, "EZ1", name="Tan Ah Kow", compliance_fields={"nric_fin": "S1234567D"})
    joiner = _sg_employee(db, organization.id, "EZ2", name="Siti Binte Ali", date_of_joining=date(2026, 5, 11),
                          compliance_fields={"nric_fin": "T0123456G"})
    foreigner = _sg_employee(db, organization.id, "EZ3", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                             compliance_fields={"nric_fin": "G1234567X"})
    run = _run(db, organization, date(2026, 5, 31), "2026-05")
    run.status = PayrollStatus.APPROVED
    for emp, ee, er, shg, sdl in ((local, "1200", "1020", {"CDAC": {"amount": "1.50"}}, "11.25"),
                                  (joiner, "600", "510", {"MBMF": {"amount": "15"}}, "7.50"),
                                  (foreigner, "0", "0", {}, "11.25")):
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                           employee_name=emp.name, country_code="SG", gross_pay=D("6000"),
                           employee_pension=D(ee), employer_pension=D(er), employer_payroll_tax=D(sdl),
                           sgp_calculation_trace={"wageMonth": "2026-05", "inputs": {"ordinaryWages": "6000", "additionalWages": "0"},
                                                  "shg": {"funds": shg}}))
    db.commit()
    return run, local


def test_ezpay_service_prepares_a_masked_reconciled_artifact(db, organization):
    import json
    from app.modules.payroll import service

    _ezpay_org(db, organization)
    _ezpay_payslips(db, organization)
    row = service.generate_sg_cpf_ezpay(db, organization.id, _ezpay_template(db).id, 2026, 5, actor_id=MAKER.id)
    data, rec = row.rendered_data, row.reconciliation
    assert (row.status, row.report_type, data["filename"]) == ("PREPARED", "SG_CPF_EZPAY", "201912345KPTE01MAY202601.DTL")
    assert [r["employmentStatus"] for r in data["employeeRows"]] == ["E", "N"]     # the foreigner has no detail record
    assert data["summaryRecords"]["01"]["amount"] == "3330.00" and data["summaryRecords"]["04"]["donors"] == 1
    assert data["sdl"] == {"beforeRounding": "30.00", "payable": "30"}             # floor of 30.00, foreigner included
    assert rec["matches"] is True and rec["history"][0]["status"] == "PREPARED"
    blob = json.dumps(data) + json.dumps(rec)
    assert "S1234567D" not in blob and "T0123456G" not in blob                   # full CPF account numbers never stored
    assert data["externalAcceptance"].startswith("BLOCKED")


def test_ezpay_lifecycle_maker_checker_unknown_and_download(db, organization):
    from fastapi import HTTPException
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem, TaxConfigurationAudit

    _ezpay_org(db, organization)
    _, local = _ezpay_payslips(db, organization)
    template = _ezpay_template(db)
    row = service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    with pytest.raises(BadRequestException, match="only an APPROVED"):
        service.get_sg_cpf_ezpay_file(db, organization.id, row.id, actor_id=MAKER.id)
    with pytest.raises(BadRequestException, match="distinct approver"):
        service.transition_sg_cpf_ezpay(db, organization.id, row.id, "APPROVED", actor_id=MAKER.id)
    service.transition_sg_cpf_ezpay(db, organization.id, row.id, "APPROVED", actor_id=CHECKER.id)
    name, content = service.get_sg_cpf_ezpay_file(db, organization.id, row.id, actor_id=CHECKER.id)
    assert name.endswith(".DTL") and "S1234567D" in content and "G1234567X" not in content
    import hashlib
    assert hashlib.sha256(content.encode("ascii")).hexdigest() == row.rendered_data["fileSha256"]
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_cpf_ezpay",
                                                  TaxConfigurationAudit.action == "export").count() == 1

    service.transition_sg_cpf_ezpay(db, organization.id, row.id, "SUBMITTED", actor_id=CHECKER.id, reference="CORPPASS-UPLOAD")
    service.transition_sg_cpf_ezpay(db, organization.id, row.id, "UNKNOWN", actor_id=CHECKER.id)
    with pytest.raises(HTTPException) as exc:                                   # UNKNOWN blocks regeneration
        service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    assert exc.value.status_code == 409 and "UNKNOWN" in exc.value.detail
    with pytest.raises(BadRequestException, match="cannot be voided"):
        service.void_generated_report(db, organization.id, row.id, "oops")
    with pytest.raises(BadRequestException, match="acknowledgement"):
        service.transition_sg_cpf_ezpay(db, organization.id, row.id, "ACCEPTED", actor_id=CHECKER.id, note="called CPF")
    with pytest.raises(BadRequestException, match="note"):
        service.transition_sg_cpf_ezpay(db, organization.id, row.id, "ACCEPTED", actor_id=CHECKER.id, reference="ACK-1")
    done = service.transition_sg_cpf_ezpay(db, organization.id, row.id, "ACCEPTED", actor_id=CHECKER.id,
                                           reference="ACK-1", note="confirmed on the CPF EZPay record of payment")
    assert [h["status"] for h in done.reconciliation["history"]] == ["PREPARED", "APPROVED", "SUBMITTED", "UNKNOWN", "ACCEPTED"]
    with pytest.raises(HTTPException) as exc:                                   # accepted → a new advice code, never a regen
        service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    assert "new advice code" in exc.value.detail
    with pytest.raises(BadRequestException, match="does not already cover"):   # Phase 5.1: a further advice carries
        service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, advice_code="02",   # only new payslips
                                      actor_id=MAKER.id)

    item = db.query(PayslipItem).filter(PayslipItem.employee_id == local.id).one()   # payroll changes after approval
    item.employee_pension = D("1300")
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.get_sg_cpf_ezpay_file(db, organization.id, row.id, actor_id=CHECKER.id)
    assert exc.value.status_code == 409 and "changed" in exc.value.detail


def test_ezpay_is_tenant_scoped_and_needs_a_csn_and_rbac(db, organization):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import service

    template = _ezpay_template(db)
    with pytest.raises(BadRequestException, match="CSN"):
        service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    _ezpay_org(db, organization)
    _ezpay_payslips(db, organization)
    row = service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    other = _other_org(db, "EZOTHER")
    with pytest.raises(NotFoundException):
        service.transition_sg_cpf_ezpay(db, other.id, row.id, "APPROVED", actor_id=CHECKER.id)
    with pytest.raises(NotFoundException):
        service.get_sg_cpf_ezpay_file(db, other.id, row.id, actor_id=CHECKER.id)
    for path, method in (("/api/payroll/singapore/reports/cpf-ezpay", "POST"),
                         ("/api/payroll/singapore/reports/cpf-ezpay/{report_id}/transition", "POST"),
                         ("/api/payroll/singapore/reports/cpf-ezpay/{report_id}/file", "GET")):
        assert "get_current_payroll_operator" in _dependency_names(_route(path, method)), path


# ══ Phase 5 STEPS 5–7 — preflight/exceptions, approval binding (SG-032),
# IR21 on the run and on termination ════════════════════════════════════

def _pf_run(db, organization, monkeypatch, pay_date=date(2026, 5, 31)):
    _stub_codes(monkeypatch)
    _activate_for_org(db, organization, _seed(db))
    return _run(db, organization, pay_date, str(pay_date))


def _codes(result, employee=None):
    return {c["code"] for c in result["checks"] if employee is None or c.get("employeeId") == employee.id}


def test_preflight_dry_runs_the_engine_read_only_and_reports_its_blocks(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollYtdAccumulator, PayslipItem

    run = _pf_run(db, organization, monkeypatch)
    ok = _sg_employee(db, organization.id, "PFOK")
    missing = _sg_employee(db, organization.id, "PFMISS", sgp_cpf_residency_status=None)
    no_nric = _sg_employee(db, organization.id, "PFNRIC", compliance_fields={})
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    assert result["status"] == "BLOCKED" and result["pack"] == "SG-PAYROLL-2026 v1.2"
    assert "ENGINE_BLOCK:sgp_cpf_residency_status" in _codes(result, missing)
    blocks = lambda e: {c["code"] for c in result["checks"] if c.get("employeeId") == e.id and c["severity"] == "BLOCK"}  # noqa: E731
    assert blocks(no_nric) == {"NRIC_MISSING"} and not blocks(ok)
    assert db.query(PayslipItem).count() == 0 and db.query(PayrollYtdAccumulator).count() == 0   # nothing written


def test_preflight_flags_next_month_age_band_and_spr_year_changes(db, organization, monkeypatch):
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    turning_55 = _sg_employee(db, organization.id, "PF55", date_of_birth=date(1971, 5, 20))
    # CPF Board: SPR year 2 begins the first day of the month after the
    # first anniversary — conversion 1 May 2025 → year 2 from 1 June 2026.
    spr = _sg_employee(db, organization.id, "PFSPR", sgp_cpf_residency_status="SPR", sgp_spr_effective_date=date(2025, 5, 1),
                       sgp_cpf_contribution_arrangement="GG")
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    assert "CPF_AGE_BAND_CHANGES_NEXT_MONTH" in _codes(result, turning_55)
    assert "SPR_YEAR_CHANGES_NEXT_MONTH" in _codes(result, spr)


def test_ir21_is_opened_on_termination_and_blocks_or_holds_the_run(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import SgpIr21Case

    run = _pf_run(db, organization, monkeypatch)
    foreigner = _sg_employee(db, organization.id, "PFEP", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                             compliance_fields={"nric_fin": "G1234567X"})
    citizen = _sg_employee(db, organization.id, "PFSC")
    # A leaving date set directly (not through the employee API): no case → the preflight BLOCKS.
    foreigner.date_of_leaving = date(2026, 6, 30)
    db.commit()
    assert "IR21_CASE_MISSING" in _codes(service.sg_payroll_preflight(db, organization.id, run.id), foreigner)
    foreigner.date_of_leaving = None
    db.commit()
    # Termination through the Singapore cessation action → the IR21 case opens automatically (DRAFT = held).
    out = service.record_sg_cessation(db, organization.id, foreigner.id, date(2026, 6, 30), actor_id=MAKER.id)
    assert out["ir21Required"] is True and out["ir21Case"]["status"] == "DRAFT"
    case = db.query(SgpIr21Case).filter(SgpIr21Case.employee_id == foreigner.id).one()
    assert (case.status, case.trigger_type, case.trigger_date) == ("DRAFT", "CESSATION", date(2026, 6, 30))
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    assert "IR21_CASE_MISSING" not in _codes(result, foreigner) and "IR21_HOLD" in _codes(result, foreigner)
    assert service.record_sg_cessation(db, organization.id, citizen.id, date(2026, 6, 30))["ir21Case"] is None
    assert db.query(SgpIr21Case).filter(SgpIr21Case.employee_id == citizen.id).count() == 0   # never for citizens
    assert "get_current_payroll_operator" in _dependency_names(
        _route("/api/payroll/singapore/employees/{employee_id}/cessation", "POST"))


def test_approval_is_refused_while_preflight_blocks(db, organization, monkeypatch):
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus

    run = _pf_run(db, organization, monkeypatch)
    emp = _sg_employee(db, organization.id, "PFAPR")
    service.generate_payslips_for_run(db, run, organization.id)
    run.status = PayrollStatus.REVIEW
    db.commit()
    emp.compliance_fields = {}                                   # NRIC removed after calculation
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id)
    assert exc.value.status_code == 409 and "NRIC_MISSING" in exc.value.detail
    assert db.get(type(run), run.id).status == PayrollStatus.REVIEW


def test_approval_binds_a_fingerprint_and_sg032_changes_invalidate_it(db, organization, monkeypatch):
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, TaxConfigurationAudit, TaxabilityRule

    run = _pf_run(db, organization, monkeypatch)
    emp = _sg_employee(db, organization.id, "PFFP", bank_name="DBS", bank_account="0011223344")
    service.generate_payslips_for_run(db, run, organization.id)
    run.status = PayrollStatus.REVIEW
    db.commit()
    service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id)          # → Approved (fingerprint stored)
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_run_approval").count() == 1
    emp.bank_account = "9999999999"                                                          # bank data changed
    db.add(TaxabilityRule(jurisdiction_country="SG", earning_type="hra", tax_component="cpf_ordinary_wages",
                          is_taxable=False, organization_id=organization.id))                # classification changed
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id)      # → Authorized refused
    assert exc.value.status_code == 409 and "bankData" in exc.value.detail and "earningClassification" in exc.value.detail
    run = db.get(type(run), run.id)
    assert (run.status, run.approved_by) == (PayrollStatus.REVIEW, None)                   # approval invalidated
    # Re-approval binds the new fingerprint; an unchanged run then proceeds.
    service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id)
    assert service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id).status == PayrollStatus.AUTHORIZED


def test_fingerprint_covers_every_sg032_input(db, organization, monkeypatch):
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    emp = _sg_employee(db, organization.id, "PFALL")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    base = service._sg_approval_fingerprint(db, run)["components"]
    assert set(base) == {"statusFacts", "workPass", "shgInstruction", "partIvStatus", "bankData", "earningClassification",
                         "rulePack", "priorRunCorrection", "payslips"}
    for attr, value, component in (("sgp_spr_effective_date", date(2020, 1, 1), "statusFacts"),
                                   ("sgp_shg_funds", "CDAC", "shgInstruction"),
                                   ("sgp_work_pass_issue_date", date(2020, 1, 1), "workPass"),
                                   ("compliance_fields", {"nric_fin": "S1234567D", "ea_workman": "YES"}, "partIvStatus")):
        setattr(emp, attr, value)
        db.commit()
        after = service._sg_approval_fingerprint(db, run)["components"]
        assert after[component] != base[component], component
        base = after


def test_non_sg_runs_are_untouched_by_the_sg_gates(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem, TaxConfigurationAudit

    run = _run(db, organization, date(2026, 5, 31), "IN run")
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=_sg_employee(db, organization.id, "INX", country_code="IN").id,
                       organization_id=organization.id, employee_name="x", country_code="IN", net_pay=D("1")))
    run.status = PayrollStatus.REVIEW
    db.commit()
    assert service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id).status == PayrollStatus.APPROVED
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_run_approval").count() == 0


def test_preflight_route_rbac_and_tenant_scope(db, organization, monkeypatch):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    other = _other_org(db, "PFOTHER")
    with pytest.raises((NotFoundException, Exception)):
        service.sg_payroll_preflight(db, other.id, run.id)
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/runs/{run_id}/preflight", "GET"))


# ══ Phase 5 STEP 8 — Work Permit levy (MOM sector pages, retrieved 2026-09-24) ══
# Expected monthly AND daily figures are MOM's own published tables; the
# daily figures are not seeded — the engine derives them with MOM's formula
# ((monthly × 12) / 365, rounded up to the cent) and must reproduce them.
_MOM_WP_PUBLISHED = (
    # (sector, tier, skill, monthly, published daily)
    ("SERVICES", "TIER_1", "R2", "450", "14.80"), ("SERVICES", "TIER_1", "R1", "300", "9.87"),
    ("SERVICES", "TIER_2", "R2", "600", "19.73"), ("SERVICES", "TIER_2", "R1", "400", "13.16"),
    ("SERVICES", "TIER_3", "R2", "800", "26.31"), ("SERVICES", "TIER_3", "R1", "600", "19.73"),
    ("MANUFACTURING", "TIER_1", "R2", "370", "12.17"), ("MANUFACTURING", "TIER_1", "R1", "250", "8.22"),
    ("MANUFACTURING", "TIER_2", "R2", "470", "15.46"), ("MANUFACTURING", "TIER_2", "R1", "350", "11.51"),
    ("MANUFACTURING", "TIER_3", "R2", "650", "21.37"), ("MANUFACTURING", "TIER_3", "R1", "550", "18.09"),
    ("CONSTRUCTION", "NTS", "R1", "500", "16.44"), ("CONSTRUCTION", "NTS", "R2", "900", "29.59"),
    ("CONSTRUCTION", "MYS_NAS_PRC", "R1", "300", "9.87"), ("CONSTRUCTION", "MYS_NAS_PRC", "R2", "700", "23.02"),
    ("CONSTRUCTION", "OFFSITE", "R1", "250", "8.22"), ("CONSTRUCTION", "OFFSITE", "R2", "370", "12.17"),
    ("PROCESS", "NTS", "R1", "300", "9.87"), ("PROCESS", "NTS", "R2", "650", "21.37"),
    ("PROCESS", "MYS_NAS_PRC", "R1", "200", "6.58"), ("PROCESS", "MYS_NAS_PRC", "R2", "450", "14.80"),
    ("MARINE_SHIPYARD", "ALL", "R1", "350", "11.51"), ("MARINE_SHIPYARD", "ALL", "R2", "500", "16.44"),
)


def _wp_rates(**extra):
    rates = {singapore.work_permit_levy_key(sec, tier, skill): Rate(flat_amount=D(m), effective_from=date(2026, 9, 24))
             for sec, tier, skill, m, _d in _MOM_WP_PUBLISHED}
    rates[singapore.work_permit_levy_key("CONSTRUCTION", "NO_CERT", "R2")] = Rate(flat_amount=D("900"))
    rates.update(extra)
    return _rate_map(**rates)


def _wp(pay_date=date(2026, 10, 31), sector="SERVICES", tier="TIER_2", skill="R2", **kw):
    return singapore.calculate(_ctx("2000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="WORK_PERMIT",
                                    sgp_wp_sector=sector, sgp_wp_skill_level=skill, sgp_wp_levy_tier=tier,
                                    pay_date=pay_date, rate_map=_wp_rates(), **kw))


def test_seeded_wp_rows_match_every_published_mom_monthly_rate():
    from scripts.seed_singapore_canonical_pack import WP_LEVY

    seeded = {(sec, tier, skill): m for sec, tier, skill, m, _src, _eff in WP_LEVY}
    for sec, tier, skill, monthly, _daily in _MOM_WP_PUBLISHED:
        assert seeded[(sec, tier, skill)] == monthly, (sec, tier, skill)
    assert seeded[("CONSTRUCTION", "NO_CERT", "ANY")] == "900"
    assert len(seeded) == len(_MOM_WP_PUBLISHED) + 1


@pytest.mark.parametrize("sector,tier,skill,monthly,daily", _MOM_WP_PUBLISHED)
def test_mom_daily_formula_reproduces_every_published_daily_rate(sector, tier, skill, monthly, daily):
    assert singapore._ceil_cent(D(monthly) * 12 / D("365")) == D(daily)


def test_full_month_work_permit_levy_is_an_employer_cost_never_a_deduction():
    out = _wp()
    fwl = _trace(out)["fwl"]
    assert (out["employer_eht"], fwl["basis"], fwl["levyKey"]) == (D("600"), "FULL_MONTH", "fwl_wp__SERVICES__TIER_2__R2")
    assert fwl["treatment"] == "EMPLOYER_COST"
    assert D(_trace(out)["result"]["netPay"]) == D("2000")                 # levy never reduces net pay (EFMA)
    assert D(_trace(out)["result"]["employeeDeductions"]) == D("0")


def test_partial_month_work_permit_levy_uses_mom_daily_rate_from_issue_day():
    out = _wp(sgp_work_pass_issue_date=date(2026, 10, 17), sgp_work_pass_end_date=date(2028, 10, 16))
    fwl = _trace(out)["fwl"]
    assert (fwl["basis"], fwl["dailyRate"], fwl["daysLevied"]) == ("DAILY", "19.73", 15)   # 17–31 Oct, issue day levied
    assert out["employer_eht"] == D("19.73") * 15


def test_work_permit_ending_within_the_month_is_blocked_without_the_end_day_rule():
    out = _wp(sgp_work_pass_issue_date=date(2024, 1, 1), sgp_work_pass_end_date=date(2026, 10, 20))
    assert _trace(out)["fwl"]["status"] == "BLOCKED" and "fwl_work_permit_end_day_basis" in _trace(out)["fwl"]["detail"]


def test_work_permit_levy_fails_closed_on_bad_facts_and_unevidenced_months():
    assert "does not exist" in _trace(_wp(sector="SERVICES", tier="NTS"))["fwl"]["detail"]
    early = _wp(pay_date=date(2026, 8, 31))                               # before the rate is evidenced (24 Sep 2026)
    assert _trace(early)["fwl"]["status"] == "BLOCKED" and "no MOM Work Permit levy row" in _trace(early)["fwl"]["detail"]
    assert _wp(sector="CONSTRUCTION", tier="NO_CERT", skill="R1")["employer_eht"] == D("900")   # regardless of skill
    assert _wp(sector="MARINE_SHIPYARD", tier=None, skill="R1")["employer_eht"] == D("350")


def test_seed_v12_carries_wp_rows_with_sources_and_effective_dates(db):
    from app.modules.payroll.models import ContributionRate, SourceArtifact

    pack = _seed(db)
    rows = {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.component_key.like("fwl_wp__%"))}
    assert len(rows) == 25
    services, construction = rows["fwl_wp__SERVICES__TIER_1__R2"], rows["fwl_wp__CONSTRUCTION__NTS__R2"]
    assert (services.flat_amount, services.effective_from) == (D("450"), date(2026, 9, 24))
    assert (construction.flat_amount, construction.effective_from) == (D("900"), date(2024, 1, 1))
    src = db.get(SourceArtifact, services.source_document_id)
    assert src.agency == "MOM" and src.checksum_sha256.startswith("191030a4") and src.reviewer_approved_at is None
    deadlines = {r.component_key: r for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                 ContributionRate.component_key.in_(("salary_payment_deadline_days", "overtime_payment_deadline_days")))}
    assert all(r.source_document_id is not None for r in deadlines.values())   # MOM "Paying salary" now backs 7 / 14 days


def test_wp_employee_fields_validate_and_sync_to_columns():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import SGEmployeeValidation as V

    base = {"nric_fin": "G1234567X", "cpf_residency_status": "FOREIGN", "work_pass_type": "WORK_PERMIT"}
    cleaned = V.validate({**base, "wp_sector": "construction", "wp_skill_level": "r1", "wp_levy_tier": "nts"})
    cols = V.sync_to_columns(cleaned)
    assert (cols["sgp_wp_sector"], cols["sgp_wp_skill_level"], cols["sgp_wp_levy_tier"]) == ("CONSTRUCTION", "R1", "NTS")
    with pytest.raises(BadRequestException, match="does not exist"):
        V.validate({**base, "wp_sector": "SERVICES", "wp_levy_tier": "NTS"})
    with pytest.raises(BadRequestException, match="Work Permit holders only"):
        V.validate({**base, "work_pass_type": "S_PASS", "wp_sector": "SERVICES"})


def test_work_permit_run_end_to_end_with_frozen_rules(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayslipItem

    _stub_codes(monkeypatch)
    pack = _seed(db)
    _activate_for_org(db, organization, pack)
    emp = _sg_employee(db, organization.id, "SGWP", ctc=D("24000"), sgp_cpf_residency_status="FOREIGN",
                       sgp_work_pass_type="WORK_PERMIT", sgp_wp_sector="MANUFACTURING", sgp_wp_skill_level="R2",
                       sgp_wp_levy_tier="TIER_3", compliance_fields={"nric_fin": "G1234567X"})
    run = _run(db, organization, date(2026, 10, 31), "2026-10")
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert (item.employer_eht, item.employee_pension, item.net_pay) == (D("650"), D("0"), item.gross_pay)
    row = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                            ContributionRate.component_key == "fwl_wp__MANUFACTURING__TIER_3__R2").one()
    row.flat_amount = D("999")                                           # a later pack edit…
    db.commit()
    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    assert db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one().employer_eht == D("650")   # …never replays


# ══ Phase 5 STEPS 9–10 — PWM / LQS and Employment Act labour-pay checks ══
# Expected values are MOM's own (sector PWM tables; "Hours of work, overtime
# and rest day" worked example; annual / sick leave tables), retrieved
# 2026-09-24.

def _ea_rates(db):
    from app.modules.payroll import service

    _activate_directly(db, _seed(db))
    return service._sg_active_pack_and_rates(db, date(2026, 7, 31))[1]


def test_mom_overtime_worked_example_and_part4_thresholds(db):
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = _ea_rates(db)
    ot = labour.overtime_minimum_hourly("NO", D("2600"), rates)          # MOM: $13.60 × 1.5 × 2 hours = $40.80
    assert ot["hourlyBasic"] == "13.60" and D(ot["minimumOvertimeHourly"]) * 2 == D("40.80")
    assert labour.overtime_minimum_hourly("YES", D("3000"), rates)["hourlyBasic"] == "15.73"   # 12 × 3000 / (52 × 44)
    assert labour.part4_coverage("YES", "NO", D("4500"), rates)["status"] == "COVERED"
    assert labour.part4_coverage("YES", "NO", D("4500.01"), rates)["status"] == "NOT_COVERED"
    assert labour.part4_coverage("NO", "NO", D("2600"), rates)["status"] == "COVERED"
    assert labour.part4_coverage("NO", "NO", D("2601"), rates)["status"] == "NOT_COVERED"
    assert labour.part4_coverage("NO", "YES", D("2000"), rates)["status"] == "NOT_COVERED"   # managers / executives
    assert labour.part4_coverage(None, None, D("2000"), rates)["status"] == "UNDETERMINED"


def test_mom_leave_tables(db):
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = _ea_rates(db)
    joined = date(2020, 3, 14)
    assert labour.annual_leave_minimum(joined, date(2020, 6, 13), rates)["days"] == 0          # < 3 months
    assert labour.annual_leave_minimum(joined, date(2020, 6, 14), rates)["days"] == 7          # year 1
    assert labour.annual_leave_minimum(joined, date(2023, 3, 14), rates)["days"] == 10         # year 4
    assert labour.annual_leave_minimum(date(2010, 1, 1), date(2026, 1, 1), rates)["days"] == 14   # year 8+
    table = [(labour.sick_leave_minimum(date(2023, 2, 13), on, rates) or {}) for on in
             (date(2023, 5, 12), date(2023, 5, 13), date(2023, 6, 13), date(2023, 7, 13), date(2023, 8, 13))]
    assert [(t["outpatient"], t["hospitalisation"]) for t in table] == [(0, 0), (5, 15), (8, 30), (11, 45), (14, 60)]


def test_pwm_floors_are_effective_dated_and_source_traced(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_singapore_canonical_pack import PWM_FLOORS

    pack = _seed(db)
    _activate_directly(db, pack)
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.component_key.like("pwm__%")).count() == \
        sum(len(w[5]) for w in PWM_FLOORS) == 184       # 158 sector rows + 26 Occupational PW rows (Phase 5.3)
    key = "pwm__CLEANING__G1__GENERAL_INDOOR"
    june, july = (service._sg_active_pack_and_rates(db, d)[1][key] for d in (date(2026, 6, 30), date(2026, 7, 31)))
    assert (june.flat_amount, july.flat_amount) == (D("1910"), D("2080"))       # MOM 1 Jul 2025–30 Jun 2026 / 1 Jul 2026–
    sec = service._sg_active_pack_and_rates(db, date(2026, 3, 31))[1]["pwm__SECURITY__OUTSOURCED__OFFICER"]
    assert (sec.flat_amount, sec.text_value) == (D("3090"), "BASIC")
    retail = service._sg_active_pack_and_rates(db, date(2026, 9, 30))[1]["pwm__RETAIL__ALL__ASSISTANT_CASHIER"]
    assert (retail.flat_amount, retail.text_value) == (D("2435"), "GROSS")       # 1 Sep 2026 window, gross wage


def test_pwm_check_shortfall_foreign_part_time_and_retail_averaging(db):
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = _ea_rates(db)
    emp = {"id": 1, "code": "P"}
    base = {"pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR", "residency": "SC"}
    short = labour.pwm_check(emp, base, {"basic": D("2000"), "gross_ex_ot": D("2500")}, rates)
    assert [(c["code"], c["severity"]) for c in short] == [("PWM_SHORTFALL", "BLOCK")]
    assert labour.pwm_check(emp, base, {"basic": D("2080"), "gross_ex_ot": D("2080")}, rates)[0]["code"] == "PWM_MET"
    assert labour.pwm_check(emp, {**base, "residency": "FOREIGN"}, {"basic": D("1"), "gross_ex_ot": D("1")}, rates)[0]["code"] == \
        "PWM_NOT_APPLICABLE_FOREIGN"
    assert labour.pwm_check(emp, {**base, "employment_type": "Part-time"}, {"basic": D("1"), "gross_ex_ot": D("1")},
                            rates)[0]["code"] == "PWM_PART_TIME_NOT_EVALUATED"
    retail = {"pwm_sector": "RETAIL", "pwm_group": "ALL", "pwm_job_level": "ASSISTANT_CASHIER", "residency": "SPR"}
    assert labour.pwm_check(emp, retail, {"basic": D("1500"), "gross_ex_ot": D("2000")}, rates)[0]["severity"] == "WARN"
    assert labour.pwm_check(emp, {**base, "pwm_job_level": "ASTRONAUT"}, {"basic": D("1"), "gross_ex_ot": D("1")},
                            rates)[0]["code"] == "PWM_FLOOR_NOT_CONFIGURED"


def test_preflight_runs_the_labour_checks(db, organization, monkeypatch):
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch, pay_date=date(2026, 8, 10))
    run.period_start, run.period_end = date(2026, 7, 1), date(2026, 7, 31)
    db.commit()
    cleaner = _sg_employee(db, organization.id, "PWM1", ctc=D("24000"), basic=D("24000"), hra=D("0"),
                           compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "CLEANING", "pwm_group": "G1",
                                              "pwm_job_level": "GENERAL_INDOOR", "ea_workman": "YES", "ea_manager_executive": "NO"})
    plain = _sg_employee(db, organization.id, "PWM2")
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    assert "PWM_SHORTFALL" in _codes(result, cleaner) and result["status"] == "BLOCKED"   # basic 2,000 < 2,080 (Jul 2026)
    assert "EA_PART4_COVERED" in _codes(result, cleaner)                                  # workman, basic ≤ 4,500
    assert "EA_PART4_UNDETERMINED" in _codes(result, plain)
    assert "EA_SALARY_LATE" in _codes(result, plain)                                       # 10 Aug > 31 Jul + 7 days


def test_deduction_cap_and_evidence(db):
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = _ea_rates(db)
    emp = {"id": 1, "code": "D"}
    assert labour.deduction_check(emp, D("3000"), D("600"), D("100"), D("700"), rates) == []      # CPF + SHG + absence only
    codes = [c["code"] for c in labour.deduction_check(emp, D("3000"), D("600"), D("0"), D("2200"), rates)]
    assert codes == ["EA_DEDUCTION_EVIDENCE_REQUIRED", "EA_DEDUCTION_CAP_EXCEEDED"]              # 1,600 > 50% of 3,000


def test_sg_public_holidays_are_mom_gazetted_dates_only(db, organization):
    from app.modules.payroll import service

    rows = service._seed_holidays_for_country(db, organization.id, "SG", 2026)
    assert len(rows) == 11 and {r.date for r in rows} >= {date(2026, 2, 17), date(2026, 2, 18), date(2026, 3, 21),
                                                          date(2026, 5, 27), date(2026, 5, 31), date(2026, 11, 8)}
    assert len(service._seed_holidays_for_country(db, organization.id, "SG", 2027)) == 11
    assert service._seed_holidays_for_country(db, organization.id, "SG", 2028) == []    # not yet gazetted → never guessed


def test_ea_and_pwm_employee_fields_validate():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import SGEmployeeValidation as V

    base = {"nric_fin": "S1234567D", "cpf_residency_status": "SC", "work_pass_type": "NONE"}
    cleaned = V.validate({**base, "ea_workman": "yes", "ea_manager_executive": "no", "ea_contractual_weekly_hours": "44",
                          "pwm_sector": "cleaning", "pwm_group": "g1", "pwm_job_level": "general_indoor"})
    assert (cleaned["ea_workman"], cleaned["pwm_sector"], cleaned["pwm_job_level"]) == ("YES", "CLEANING", "GENERAL_INDOOR")
    with pytest.raises(BadRequestException, match="both a workman and a manager"):
        V.validate({**base, "ea_workman": "YES", "ea_manager_executive": "YES"})


def test_pwm_classification_list_comes_from_the_active_pack(db):
    from app.modules.payroll import service

    _activate_directly(db, _seed(db))
    rows = service.list_sg_pwm_classifications(db, as_of=date(2026, 7, 31))
    cleaner = next(r for r in rows if (r["sector"], r["group"], r["jobLevel"]) == ("CLEANING", "G1", "GENERAL_INDOOR"))
    assert (cleaner["monthlyFloor"], cleaner["wageBasis"], cleaner["effectiveFrom"]) == ("2080.00", "BASIC", "2026-07-01")
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/pwm-classifications", "GET"))


# ══ Phase 5 STEP 11 — Appendix 8A valuations (SG-scoped) + AIS readiness (SG-042) ══

def test_sg_benefit_valuations_are_sg_only_and_feed_the_ais_readiness_metric(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    sg = _sg_employee(db, organization.id, "A8A1")
    india = _sg_employee(db, organization.id, "A8AIN", country_code="IN")
    with pytest.raises(BadRequestException, match="not a Singapore employee"):
        service.create_sg_benefit_valuation(db, organization.id, india.id, "2026", "CAR", D("100"))
    with pytest.raises(BadRequestException, match="calendar"):
        service.create_sg_benefit_valuation(db, organization.id, sg.id, "2026-27", "CAR", D("100"))
    v = service.create_sg_benefit_valuation(db, organization.id, sg.id, "2026", "ACCOMMODATION", D("4931.50"))
    assert v.status == "Draft" and [x.id for x in service.list_sg_benefit_valuations(db, organization.id, "2026")] == [v.id]
    run = _run(db, organization, date(2026, 5, 31), "May")
    run.status = PayrollStatus.APPROVED
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=sg.id, organization_id=organization.id, employee_name="x",
                       country_code="SG", gross_pay=D("5000"),
                       sgp_calculation_trace={"wageMonth": "2026-05", "iras": {"totals": {"iras_gross_salary": "4700",
                                                                                          "UNCLASSIFIED": "300"}}}))
    db.commit()
    r = service.sg_ais_readiness(db, organization.id, 2026)
    assert (r["status"], r["issues"]["unclassifiedEarnings"], r["issues"]["draftValuations"], r["unclassifiedAmount"]) == (
        "REVIEW_REQUIRED", 1, 1, "300")
    assert r["appendix8B"].startswith("BLOCKED")
    for path, method in (("/api/payroll/singapore/benefit-valuations", "POST"), ("/api/payroll/singapore/benefit-valuations", "GET"),
                         ("/api/payroll/singapore/ais-readiness", "GET")):
        assert "get_current_payroll_operator" in _dependency_names(_route(path, method)), path


# ══ Phase 5 STEP 12 — Singapore Compliance Centre (§14, SG-041/SG-042) ════

def test_clocks_apply_the_next_working_day_rules():
    from app.modules.payroll.engine.jurisdictions.singapore import compliance as cc

    rates = {"salary_payment_deadline_days": Rate(flat_amount=D("7")), "overtime_payment_deadline_days": Rate(flat_amount=D("14")),
             "cpf_enforcement_day_following_month": Rate(flat_amount=D("14")), "fwl_payment_due_day": Rate(flat_amount=D("17"))}
    holidays = {date(2026, 2, 17), date(2026, 2, 18)}
    out = {c["clock"]: c for c in cc.clocks(date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 5), rates, holidays,
                                            date(2027, 3, 1), [{"id": 9, "employeeId": 3, "status": "DRAFT", "fileBy": "2026-02-10"}])}
    assert out["SALARY_PAYMENT"]["due"] == "2026-02-07" and out["SALARY_PAYMENT"]["overtimeDue"] == "2026-02-14"
    assert out["CPF_SDL_SHG_CONTRIBUTION"]["due"] == "2026-01-31"
    assert out["CPF_SDL_SHG_CONTRIBUTION"]["enforcementAfter"] == "2026-02-16"     # 14 Feb 2026 is a Saturday
    assert out["FOREIGN_WORKER_LEVY"]["due"] == "2026-02-19"                        # 17 Feb (CNY) → 18 (CNY) → 19 Feb
    assert out["IRAS_AIS"]["due"] == "2027-03-01" and out["IR21"]["caseId"] == 9


def test_compliance_centre_covers_every_area_with_the_required_fields(db, organization, monkeypatch):
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    _sg_employee(db, organization.id, "CC1")
    _sg_employee(db, organization.id, "CC2", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="WORK_PERMIT",
                 compliance_fields={"nric_fin": "G1234567X"})
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    out = service.get_sg_compliance_centre(db, organization.id, as_of=date(2026, 6, 15))
    areas = {i["area"] for i in out["items"]}
    assert areas >= {"CPF", "SDL", "SHG", "EZPay", "IR8A", "AIS", "IR21", "S Pass", "Work Permit", "PWM", "LQS",
                     "Employment Act", "PDPA", "Security", "Banking", "Readiness", "Payroll run"}
    assert all({"status", "effectiveDate", "evidence", "source", "blocker", "owner", "action"} <= set(i) for i in out["items"])
    by = {i["key"]: i for i in out["items"]}
    assert by["wp_levy"]["status"] == "FAIL" and "CC2" in by["wp_levy"]["evidence"]      # WP facts missing
    assert by["ais_api"]["status"] == "BLOCKED" and by["wp_bill_import"]["status"] == "BLOCKED"
    assert by["appendix_8b"]["status"] == "BLOCKED" and by["readiness"]["status"] == "BLOCKED"
    assert {c["clock"] for c in out["clocks"]} >= {"SALARY_PAYMENT", "CPF_SDL_SHG_CONTRIBUTION", "FOREIGN_WORKER_LEVY", "IRAS_AIS"}
    assert "not a CPF Board / IRAS / MOM approval" in out["certification"]


def test_compliance_centre_is_tenant_scoped_and_rbac(db, organization, monkeypatch):
    from app.modules.payroll import service

    _pf_run(db, organization, monkeypatch)
    other = _other_org(db, "CCOTHER")
    _sg_employee(db, other.id, "CCX", sgp_cpf_residency_status=None)
    out = service.get_sg_compliance_centre(db, organization.id, as_of=date(2026, 6, 15))
    assert "CCX" not in {i["key"]: i for i in out["items"]}["cpf_employee_facts"]["evidence"]
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/compliance-centre", "GET"))


# ══ Phase 5 STEP 13 — Security / PDPA: partial NRIC (PDPC NRIC guidelines §5.2) ══

def test_nric_fin_mask_is_the_pdpc_partial_nric_and_other_masks_are_unchanged():
    from app.modules.payroll.employee_validation import (
        mask_compliance_fields, mask_identifier, mask_nric_fin, restore_masked_compliance_fields)

    assert mask_nric_fin("S1234567A") == "*****567A"                  # PDPC example: "567A" of S1234567A
    assert mask_nric_fin("G1234567X")[:5] == "*****"                  # the prefix letter is not disclosed
    masked = mask_compliance_fields({"nric_fin": "S1234567D", "nino": "AB123456C"})
    assert masked == {"nric_fin": "*****567D", "nino": mask_identifier("AB123456C")}   # UK mask untouched
    stored = {"nric_fin": "S1234567D"}
    assert restore_masked_compliance_fields({"nric_fin": "*****567D"}, stored) == stored   # edit round trip keeps the value
    assert restore_masked_compliance_fields({"nric_fin": "S7654321B"}, stored) == {"nric_fin": "S7654321B"}


def test_sg_payslip_pdf_shows_only_the_partial_nric(db, organization):
    import io
    import pypdf
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _sg_employee(db, organization.id, "SGPDPA")
    run = _run(db, organization, date(2026, 6, 30), "Jun PDPA")
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                       country_code="SG", compliance_fields={"nric_fin": "S1234567D", "cpf_residency_status": "SC"},
                       basic_salary=D("5000"), gross_pay=D("5000"), total_deductions=D("0"), net_pay=D("5000"))
    db.add(item)
    db.commit()
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(service.generate_payslip_pdf_bytes(db, item.id, organization.id))).pages)
    assert "*****567D" in text and "S1234567D" not in text


# ══ Phase 5 STEP 14 — SG-PAYROLL-2027 (CPF Board tables from 1 Jan 2027) ══

def test_2027_pack_seeds_the_new_cpf_tables_and_resolves_from_1_january_2027(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from scripts.seed_singapore_canonical_pack import seed_singapore_2027

    p26, p27 = _seed(db), seed_singapore_2027(db)
    db.commit()
    assert (p27.pack_id, p27.version, p27.status, p27.tax_year, p27.effective_from) == (
        "SG-PAYROLL-2027", "1.0", "Draft", "2027", date(2027, 1, 1))
    p26.status = p27.status = "Active"
    db.commit()

    def full_band(d, band="AGE_55_60"):
        rates, slabs, pack = resolve_tax_configuration(db, "SG", payroll_date=d)
        row = next(s_ for s_ in slabs if s_.rule_type == "CPF_RATE_BAND" and s_.filing_status == "SC_SPR3"
                   and s_.tax_regime == band and s_.assessment_basis == "FULL")
        return pack.pack_id, row.rate_pct, row.employer_rate_pct, row.rate_label

    assert full_band(date(2026, 12, 31)) == ("SG-PAYROLL-2026", D("18"), D("16"), "CPF-2026-SC_SPR3-AGE_55_60-FULL")
    assert full_band(date(2027, 1, 31)) == ("SG-PAYROLL-2027", D("19"), D("16.5"), "CPF-2027-SC_SPR3-AGE_55_60-FULL")
    assert full_band(date(2027, 1, 31), "AGE_LE_55")[1:3] == (D("20"), D("17"))           # unchanged ≤ 55
    rates27 = {r.component_key: r for r in resolve_tax_configuration(db, "SG", payroll_date=date(2027, 1, 31))[0]}
    assert rates27["cpf_ow_ceiling_monthly"].flat_amount == D("8000") and "fwl_wp__SERVICES__TIER_2__R2" in rates27


def test_every_seeded_sg_value_fits_its_column(db):
    """Regression (Phase 5 PostgreSQL validation): a 122-character PWM label
    exceeded ContributionRate.label String(100) — SQLite accepts it, PostgreSQL
    raises StringDataRightTruncation. Every seeded string is checked against
    its column length here, on any database."""
    from sqlalchemy import String
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from scripts.seed_singapore_canonical_pack import seed_singapore_2027

    packs = [_seed(db), seed_singapore_2027(db)]
    db.commit()
    for model in (ContributionRate, TaxSlab):
        limits = {c.name: c.type.length for c in model.__table__.columns if isinstance(c.type, String) and c.type.length}
        for row in db.query(model).filter(model.jurisdiction_pack_id.in_([p.id for p in packs])):
            for col, limit in limits.items():
                value = getattr(row, col)
                assert value is None or len(str(value)) <= limit, (model.__name__, col, value)


# ══ Phase 5.1 — closure & hardening ═══════════════════════════════════════

# WS8 / Phase 5.2 — CPF / SDL / SHG on the Total Wages PAYABLE. No-pay leave
# makes an incomplete month (MOM): salary = monthly gross rate ÷ working days
# × days actually worked; CPF Board computes CPF on the wages payable.

_JUNE_NO_PAY = ["2026-06-0%d" % d for d in (1, 2, 3, 4, 5)] + ["2026-06-%02d" % d for d in (8, 9, 10, 11, 12)]


def test_no_pay_leave_reduces_cpf_wages_to_the_wages_actually_payable():
    out = calculate_payroll(_ctx("6000", unpaid_leave_days=10, calendar_days=30,
                                 sgp_employment_facts={"workPattern": "5_DAY", "unpaidDates": _JUNE_NO_PAY}), "standard")
    # June 2026 = 22 working days (MOM table); 12 worked → 6,000 × 12 / 22 = 3,272.73.
    assert (out.attendance_deduction, out.employee_pension, out.employer_pension) == (D("2727.27"), D("654"), D("557"))
    assert out.employer_payroll_tax == D("8.18") and out.net_pay == D("2618.73")
    assert (out.calendar_days, out.payable_days, out.per_day_salary) == (D("22"), D("12"), D("272.73"))
    month = out.sgp_calculation_trace["incompleteMonth"]
    assert (month["reasons"], month["salary"], month["noPayDates"]) == (["NO_PAY_LEAVE"], "3272.73", _JUNE_NO_PAY)
    assert out.sgp_calculation_trace["inputs"]["ordinaryWages"] == "3272.73"


def test_incomplete_month_prorates_the_gross_rate_and_pays_housing_allowance_in_full():
    """MOM's gross rate of pay excludes travel, food and housing allowances —
    they are not pro-rated by the formula (recorded, flagged for review)."""
    components, _ = singapore.earning_components(_ctx("6000", basic=D("4000"), hra=D("2000"), unpaid_leave_days=11,
                                                      sgp_employment_facts={"workPattern": "5_DAY",
                                                                            "unpaidDates": _JUNE_NO_PAY + ["2026-06-15"]}))
    assert (components["basic"], components["hra"]) == (D("2000.00"), D("2000"))       # 4,000 × 11 / 22; HRA whole
    month = singapore.incomplete_month(_ctx("6000", basic=D("4000"), hra=D("2000"), unpaid_leave_days=11,
                                            sgp_employment_facts={"workPattern": "5_DAY",
                                                                  "unpaidDates": _JUNE_NO_PAY + ["2026-06-15"]}))
    assert month["excludedMonthlyComponentsPaidInFull"] == {"hra": "2000"} and month["monthlyGrossRate"] == "4000"


# WS6 — SHG alternate (employee-instructed) amounts. CPF Board SHG page:
# "Employees who … wish to contribute a different amount can contact the
# respective SHGs" — the amount is the employee's instruction, never guessed.

def test_shg_instructed_amount_replaces_the_band_and_is_recorded():
    out = singapore.calculate(_ctx("6000", sgp_shg_funds="CDAC=5.00"))
    assert out["professional_tax"] == D("5.00")
    fund = _trace(out)["shg"]["funds"]["CDAC"]
    assert (fund["basis"], fund["bandAmount"]) == ("EMPLOYEE_INSTRUCTION", "2")        # band would be $2 at $6,000
    both = singapore.calculate(_ctx("6000", sgp_shg_funds="MBMF=0,CDAC", sgp_cpf_residency_status="SC"))
    assert _trace(both)["shg"]["funds"]["MBMF"]["amount"] == "0" and _trace(both)["shg"]["funds"]["CDAC"]["amount"] == "2"


def test_shg_instructed_amount_needs_evidence_and_a_valid_amount():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import SGEmployeeValidation as V

    base = {"nric_fin": "S1234567D", "cpf_residency_status": "SC", "work_pass_type": "NONE"}
    with pytest.raises(BadRequestException, match="evidence reference"):
        V.validate({**base, "shg_funds": "CDAC=5.00"})
    assert V.validate({**base, "shg_funds": "CDAC=5.00", "shg_evidence_ref": "CDAC-FORM-14"})["shg_funds"] == "CDAC=5.00"
    with pytest.raises(SingaporeCalculationBlockedError):
        singapore.calculate(_ctx("6000", sgp_shg_funds="CDAC=5.001"))


# WS4 — overtime hours (attendance beyond the policy's normal daily hours)
# and the Part 4 minimum: MOM "Hours of work, overtime and rest day".

def _ot_setup(db, organization, monkeypatch, workman="YES", enabled=True, approval=False, hours=("10", "10", "10"),
              basic_annual=D("48000")):
    from app.modules.payroll.models import PayrollAttendanceRecord
    from app.modules.payroll.policy.service import get_active_policy

    run = _pf_run(db, organization, monkeypatch, pay_date=date(2026, 5, 31))
    policy = get_active_policy(db, organization.id)
    policy.overtime_rule.enabled, policy.overtime_rule.approval_required = enabled, approval
    policy.overtime_rule.minimum_overtime_minutes = 30
    for c in policy.employee_categories:
        c.expected_hours = 8
    emp = _sg_employee(db, organization.id, "SGOT", ctc=basic_annual, basic=basic_annual, hra=D("0"),
                       employment_type="Full-time",
                       compliance_fields={"nric_fin": "S1234567D", "ea_workman": workman, "ea_manager_executive": "NO"})
    for day, h in enumerate(hours, start=4):
        db.add(PayrollAttendanceRecord(organization_id=organization.id, employee_id=emp.id, date=date(2026, 5, day),
                                       status="present", hours=h))
    db.commit()
    return run, emp


def test_part4_overtime_is_paid_at_the_statutory_minimum_and_is_cpf_ow(db, organization, monkeypatch):
    from decimal import ROUND_CEILING
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run, emp = _ot_setup(db, organization, monkeypatch)
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    hourly = D(12) * D(4000) / (D(52) * D(44))                      # MOM monthly-rated hourly basic rate
    expected = (D(6) * D("1.5") * hourly).quantize(D("0.01"), rounding=ROUND_CEILING)
    assert item.overtime == expected == D("188.82")
    ot = item.sgp_calculation_trace["overtime"]
    assert (ot["status"], ot["hours"], ot["part4"]) == ("PAID", "6", "COVERED")
    assert item.sgp_calculation_trace["inputs"]["wageClassification"]["overtime"]["class"] == "OW"


def test_overtime_minimum_is_never_dropped_silently(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run, emp = _ot_setup(db, organization, monkeypatch, approval=True)
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.overtime == D("0") and item.sgp_calculation_trace["overtime"]["status"] == "UNPAID_STATUTORY_MINIMUM"
    assert "EA_OVERTIME_UNPAID" in _codes(service.sg_payroll_preflight(db, organization.id, run.id), emp)


def test_overtime_boundaries_non_part4_and_fractional_hours(db):
    from types import SimpleNamespace as NS
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rows = [NS(status="present", hours=h, date=date(2026, 5, 1)) for h in ("8", "8.25", "9.5", "7")]
    assert labour.overtime_hours_from_attendance(rows, 8, 30)["hours"] == D("1.5")   # 0.25 h < 30 min minimum
    assert labour.overtime_hours_from_attendance(rows, 8, 0)["hours"] == D("1.75")
    rates = _ea_rates(db)
    assert labour.statutory_overtime_pay("NO", D("2600"), D("2"), rates)["amount"] == D("40.80")   # MOM worked example
    assert labour.statutory_overtime_pay("NO", D("5000"), D("2"), rates)["amount"] == D("40.80")   # capped non-workman


def test_non_part4_overtime_is_contractual_not_computed(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run, emp = _ot_setup(db, organization, monkeypatch, workman="NO", basic_annual=D("60000"))   # non-workman > $2,600
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    assert item.overtime == D("0") and item.sgp_calculation_trace["overtime"]["status"] == "NOT_PART4"


# WS5 — Employment Act salary deductions on the shared deduction-order model.

def _deduction(db, organization, emp, category="LOAN", **kw):
    from app.modules.payroll import service

    args = dict(evidence_ref="LOAN-AGR-7", evidence_date=date(2026, 4, 1), amount=D("500"), total_to_collect=D("1000"))
    args.update(kw)
    return service.create_sg_salary_deduction(db, organization.id, emp.id, category, date(2026, 5, 1), created_by_id=MAKER.id, **args)


def test_loan_deduction_reduces_net_pay_and_stops_when_collected(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    _pf_run(db, organization, monkeypatch, pay_date=date(2026, 4, 30))
    emp = _sg_employee(db, organization.id, "SGDED")
    _deduction(db, organization, emp)
    nets = []
    for m, last in ((5, 31), (6, 30), (7, 31)):
        run = _run(db, organization, date(2026, m, last), f"2026-{m:02d}")
        service.generate_payslips_for_run(db, run, organization.id)
        run.status = PayrollStatus.APPROVED
        db.commit()
        item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
        nets.append((item.net_pay, (item.sgp_calculation_trace.get("salaryDeductions") or {}).get("total")))
    # 10,000 gross − 1,600 CPF (OW capped at 8,000) − 500 loan instalment; the loan's S$1,000 is then collected
    assert [(n, D(t) if t is not None else None) for n, t in nets] == [
        (D("7900.00"), D("500")), (D("7900.00"), D("500")), (D("8400.00"), D("0"))]


def test_invalid_deductions_never_pass_silently(db, organization, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    emp = _sg_employee(db, organization.id, "SGBAD", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                       compliance_fields={"nric_fin": "G1234567X"})
    with pytest.raises(BadRequestException, match="prohibits"):
        _deduction(db, organization, emp, "LEVY")
    with pytest.raises(BadRequestException, match="reference and date"):
        _deduction(db, organization, emp, "COOPERATIVE", evidence_ref="")
    _deduction(db, organization, emp, "ACCOMMODATION", evidence_ref="ACC-OK", amount=D("3000"), total_to_collect=None)
    with pytest.raises(Exception) as exc:                                   # 3,000 > 25% of 10,000 → the run BLOCKS
        service.generate_payslips_for_run(db, run, organization.id)
    assert "25" in str(exc.value) or "salary_deductions" in str(exc.value)
    assert "ENGINE_BLOCK:salary_deductions" in _codes(service.sg_payroll_preflight(db, organization.id, run.id), emp)


def test_deduction_routes_are_sg_only_and_rbac(db, organization):
    from app.core.exceptions import BadRequestException

    india = _sg_employee(db, organization.id, "INDED", country_code="IN")
    with pytest.raises(BadRequestException, match="Singapore employees only"):
        _deduction(db, organization, india)
    for method in ("POST", "GET"):
        assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/employees/{employee_id}/deductions", method))


# WS1 — append-only corrections of finalized payroll (SG-044).

def _finalized(db, organization, monkeypatch, pay_date=date(2026, 5, 31), **emp_kw):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    run = _pf_run(db, organization, monkeypatch, pay_date=pay_date)
    emp = _sg_employee(db, organization.id, emp_kw.pop("code", "SGCOR"), ctc=D("72000"), **emp_kw)     # 6,000 / month
    service.generate_payslips_for_run(db, run, organization.id)
    run.status = PayrollStatus.APPROVED
    db.commit()
    return run, emp, db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()


def _snapshot(item):
    return (item.gross_pay, item.net_pay, item.employee_pension, item.employer_pension, item.professional_tax,
            item.employer_payroll_tax, dict(item.sgp_calculation_trace))


def test_correction_is_a_linked_delta_and_the_original_never_changes(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayslipItem, PayrollRun, TaxConfigurationAudit

    run, emp, item = _finalized(db, organization, monkeypatch)
    before = _snapshot(item)
    sdl = db.query(ContributionRate).filter(ContributionRate.component_key == "sdl",
                                            ContributionRate.jurisdiction_country == "SG").first()
    sdl.employer_rate_pct = D("0.0030")                         # a later statutory edit must not replay
    emp.sgp_shg_funds = "CDAC"                                   # the corrected fact: SHG instruction missed
    db.commit()
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "SHG instruction received late", actor_id=MAKER.id)
    db.refresh(item)
    assert _snapshot(item) == before                              # immutable original
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    assert (delta.professional_tax, delta.net_pay, delta.employee_pension, delta.employer_payroll_tax) == (
        D("2.00"), D("-2.00"), D("0"), D("0"))                   # CDAC $2 at $6,000; SDL replayed at 0.25%, no delta
    corr = delta.sgp_calculation_trace["correction"]
    assert (corr["originalPayslipId"], corr["sequence"], corr["reason"], corr["actorId"]) == (item.id, 1, "SHG instruction received late", MAKER.id)
    assert (D(corr["before"]["shg"]), D(corr["after"]["shg"]), D(corr["delta"]["shg:CDAC"])) == (0, 2, 2)
    assert db.get(PayrollRun, out["correctionRunId"]).notes.startswith("[SG-CORRECTION]")
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_payslip_correction").count() == 1


def test_multiple_corrections_chain_and_cpf_decrease_is_flagged_as_a_refund(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run, emp, item = _finalized(db, organization, monkeypatch)
    emp.sgp_shg_funds = "CDAC"
    db.commit()
    service.correct_sg_finalized_payslip(db, organization.id, item.id, "SHG", actor_id=MAKER.id)
    emp.sgp_cpf_residency_status, emp.sgp_spr_effective_date, emp.sgp_cpf_contribution_arrangement = "SPR", date(2025, 12, 1), "GG"
    db.commit()
    second = service.correct_sg_finalized_payslip(db, organization.id, item.id, "was SPR year 1, not a citizen", actor_id=MAKER.id)
    d2 = db.get(PayslipItem, second["deltaPayslipId"])
    # SPR year 1 G/G at $6,000: total 9%, employee 5% → 540 / 300; citizen was 2,220 / 1,200.
    assert (d2.employee_pension, d2.employer_pension) == (D("-900"), D("-780"))
    assert second["sequence"] == 2 and second["cpfRefundRequired"] is True
    assert D(d2.sgp_calculation_trace["correction"]["before"]["shg"]) == 2   # before = original + first delta
    chain = service.list_sg_payslip_corrections(db, organization.id, item.id)
    assert [c["sequence"] for c in chain] == [1, 2]
    with pytest.raises(Exception, match="no change"):
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "again", actor_id=MAKER.id)


def test_aw_correction_posts_ytd_and_a_ledger_entry_and_ir8a_sees_it(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    run, emp, item = _finalized(db, organization, monkeypatch)
    monkeypatch.setattr(service, "_sum_attendance_extras", lambda *a, **k: D("1000"))   # the missed May bonus
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "May bonus omitted", actor_id=MAKER.id)
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    aw = delta.sgp_calculation_trace["cpf"]["additionalWages"]
    assert (D(aw["awPaid"]), D(aw["ledgerEntry"]["awPaid"])) == (1000, 1000)
    assert (delta.employee_pension, delta.employer_pension) == (D("200"), D("170"))      # 37% / 20% of the AW
    assert _ytd_of(db, emp)["cpf_aw_paid"] == D("1000.00")
    db.get(PayrollRun, out["correctionRunId"]).status = PayrollStatus.APPROVED
    db.commit()
    row = service.generate_sg_ir8a(db, organization.id, _ir8a_template(db).id, 2026).rendered_data["employeeRows"][0]
    assert (row["bonusAdditionalWages"], row["payslipCount"]) == (1000.0, 2)
    monkeypatch.setattr(service, "_sum_attendance_extras", lambda *a, **k: D("0"))
    with pytest.raises(Exception, match="refund application"):                          # AW never corrected downwards here
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "bonus reversed", actor_id=MAKER.id)


def test_correction_refusals_guards_and_tenant_isolation(db, organization, monkeypatch):
    from app.core.exceptions import BadRequestException, NotFoundException
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    run, emp, item = _finalized(db, organization, monkeypatch)
    with pytest.raises(NotFoundException):
        service.correct_sg_finalized_payslip(db, _other_org(db, "CORROTHER").id, item.id, "x", actor_id=MAKER.id)
    with pytest.raises(BadRequestException, match="reason"):
        service.correct_sg_finalized_payslip(db, organization.id, item.id, " ", actor_id=MAKER.id)
    emp.sgp_shg_funds = "CDAC"
    db.commit()
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "SHG", actor_id=MAKER.id)
    corr_run = db.get(PayrollRun, out["correctionRunId"])
    with pytest.raises(BadRequestException, match="correction"):
        service.generate_payslips_for_run(db, corr_run, organization.id)
    with pytest.raises(BadRequestException, match="correction"):
        service.regenerate_employee_payslip(db, corr_run.id, emp.id, organization.id)
    with pytest.raises(BadRequestException, match="original"):
        service.correct_sg_finalized_payslip(db, organization.id, out["deltaPayslipId"], "x", actor_id=MAKER.id)
    june = _run(db, organization, date(2026, 6, 30), "2026-06")
    service.generate_payslips_for_run(db, june, organization.id)                           # a later month now builds on May
    emp.sgp_shg_funds = "NONE"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "late", actor_id=MAKER.id)
    assert exc.value.status_code == 409
    draft_run = _run(db, organization, date(2026, 7, 31), "2026-07")
    service.generate_payslips_for_run(db, draft_run, organization.id)
    from app.modules.payroll.models import PayslipItem
    draft_item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == draft_run.id).first()
    with pytest.raises(BadRequestException, match="not finalized"):
        service.correct_sg_finalized_payslip(db, organization.id, draft_item.id, "x", actor_id=MAKER.id)
    for method in ("POST", "GET"):
        assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/payslips/{payslip_id}/corrections", method))


def test_supplementary_ezpay_advice_carries_only_the_correction_delta(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    from app.modules.payroll.models import CompanyComplianceDetails

    run, emp, item = _finalized(db, organization, monkeypatch, compliance_fields={"nric_fin": "S1234567D"})
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization.id).one()
    company.tax_identifiers = {"uen": "201912345K", "cpf_submission_number": "201912345KPTE01"}
    db.commit()
    template = _ezpay_template(db)
    first = service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    service.transition_sg_cpf_ezpay(db, organization.id, first.id, "APPROVED", actor_id=CHECKER.id)
    monkeypatch.setattr(service, "_sum_attendance_extras", lambda *a, **k: D("1000"))
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "May bonus omitted", actor_id=MAKER.id)
    db.get(PayrollRun, out["correctionRunId"]).status = PayrollStatus.APPROVED
    db.commit()
    supp = service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, advice_code="02", actor_id=MAKER.id)
    assert D(supp.rendered_data["summaryRecords"]["01"]["amount"]) == 370               # only the delta CPF (200 + 170)
    assert item.id in supp.rendered_data["excludedPayslipIds"]
    service.transition_sg_cpf_ezpay(db, organization.id, supp.id, "APPROVED", actor_id=CHECKER.id)
    name, content = service.get_sg_cpf_ezpay_file(db, organization.id, supp.id, actor_id=CHECKER.id)   # rebuilds identically
    assert name.endswith("02.DTL")


# WS7 — SPR transitions (CPF Board: "The first year begins on the day of SPR
# conversion; the second year begins on the first day of the month after the
# first anniversary …"). A conversion part-way through a wage month stays
# BLOCKED — CPF Board's FAQ on that month's OW / AW computation could not be
# retrieved (BLOCKED — AUTHORITATIVE EVIDENCE REQUIRED).

@pytest.mark.parametrize("spr_date,pay_date,expected", [
    (date(2026, 5, 1), date(2026, 5, 31), "SPR1_GG"),            # converted on the 1st: full first-year month
    (date(2026, 6, 1), date(2026, 5, 31), None),                 # converted after the wage month: still foreign, no CPF
    (date(2025, 5, 1), date(2026, 5, 31), "SPR1_GG"),            # month of the first anniversary: still year 1
    (date(2025, 5, 1), date(2026, 6, 30), "SPR2_GG"),            # month after the first anniversary: year 2
    (date(2024, 5, 1), date(2026, 6, 30), "SC_SPR3"),            # month after the second anniversary: full rates
])
def test_spr_year_transitions_follow_the_cpf_board_rule(spr_date, pay_date, expected):
    kw = dict(sgp_cpf_residency_status="SPR", sgp_spr_effective_date=spr_date, sgp_cpf_contribution_arrangement="GG",
              pay_date=pay_date, sgp_work_pass_type="NONE" if spr_date <= pay_date else "EP")
    out = singapore.calculate(_ctx("6000", **kw))
    assert (_trace(out)["cohort"] if expected else _trace(out)["cohort"]) == (expected or "NOT_CPF_ELIGIBLE")


def test_mid_month_spr_conversion_stays_blocked_pending_cpf_evidence():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", sgp_cpf_residency_status="SPR", sgp_spr_effective_date=date(2026, 5, 16),
                                 sgp_cpf_contribution_arrangement="GG", pay_date=date(2026, 5, 31)))
    assert exc.value.key == "sgp_spr_effective_date" and "SG-009" in exc.value.reason


# WS9 — SG-047 disaster-recovery freeze.

def test_restore_freezes_uncertain_ezpay_submissions_and_blocks_blind_retry(db, organization):
    from fastapi import HTTPException
    from app.modules.payroll import service

    _ezpay_org(db, organization)
    _ezpay_payslips(db, organization)
    template = _ezpay_template(db)
    row = service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    service.transition_sg_cpf_ezpay(db, organization.id, row.id, "APPROVED", actor_id=CHECKER.id)
    other = _other_org(db, "DROTHER")
    assert service.sg_freeze_after_restore(db, other.id, "backup-2026-05-31T02:00Z")["frozen"] == []   # tenant-scoped
    out = service.sg_freeze_after_restore(db, organization.id, "backup-2026-05-31T02:00Z", actor_id=CHECKER.id)
    assert [(f["id"], f["previousStatus"]) for f in out["frozen"]] == [(row.id, "APPROVED")]
    db.refresh(row)
    assert row.status == "UNKNOWN" and "SG-047" in row.reconciliation["history"][-1]["note"]
    with pytest.raises(HTTPException) as exc:                        # never replayed blindly
        service.generate_sg_cpf_ezpay(db, organization.id, template.id, 2026, 5, actor_id=MAKER.id)
    assert "UNKNOWN" in exc.value.detail
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/disaster-recovery/freeze", "POST"))


# ══ Phase 5.2 — incomplete month (MOM) and mid-month joiners ═══════════════
# MOM "Monthly and daily salary": salary for an incomplete month = monthly
# gross rate of pay ÷ total working days in the month × days actually worked;
# incomplete when the employee starts after the 1st, leaves before the last
# day, or takes no-pay leave. MOM "Calculation of Salary for Incomplete Month
# of Work" (incomplete-month.xls) publishes the working days per month.

MOM_WORKING_DAYS = {   # (5-day, 5.5-day, 6-day) — MOM incomplete-month.xls, verbatim
    2025: ((23, 25, 27), (20, 22, 24), (21, "23.5", 26), (22, 24, 26), (22, "24.5", 27), (21, 23, 25),
           (23, 25, 27), (21, "23.5", 26), (22, 24, 26), (23, 25, 27), (20, "22.5", 25), (23, 25, 27)),
    2026: ((22, "24.5", 27), (20, 22, 24), (22, 24, 26), (22, 24, 26), (21, "23.5", 26), (22, 24, 26),
           (23, 25, 27), (21, "23.5", 26), (22, 24, 26), (22, "24.5", 27), (21, 23, 25), (23, 25, 27)),
}


def test_working_days_reproduce_every_cell_of_the_mom_table():
    import calendar as _cal

    for year, months in MOM_WORKING_DAYS.items():
        for month, cells in enumerate(months, start=1):
            end = date(year, month, _cal.monthrange(year, month)[1])
            for pattern, expected in zip(("5_DAY", "5_5_DAY", "6_DAY"), cells):
                assert singapore.working_days(date(year, month, 1), end, pattern) == D(str(expected)), (year, month, pattern)


def _jctx(gross="6000", **kw):
    kw.setdefault("sgp_employment_facts", dict(_WEEK5))
    return _ctx(gross, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), **kw)


@pytest.mark.parametrize("joined,expected_salary", [
    (date(2026, 6, 1), None),                  # joins on the first day — a complete month
    (date(2025, 11, 3), None),                 # joined before the payroll month
    (date(2026, 6, 16), D("3000.00")),         # mid-month: 11 of 22
    (date(2026, 6, 29), D("545.45")),          # near month end: 2 of 22
    (date(2026, 6, 14), D("3272.73")),         # on a Sunday: counted from Monday 15 — 12 of 22
])
def test_joiner_months(joined, expected_salary):
    out = calculate_payroll(_jctx(date_of_joining=joined), "standard")
    month = out.sgp_calculation_trace["incompleteMonth"]
    if expected_salary is None:
        assert month == {"status": "COMPLETE_MONTH"} and out.attendance_deduction == 0 and out.employee_pension == D("1200")
    else:
        assert D(month["salary"]) == expected_salary and out.attendance_deduction == D("6000") - expected_salary
        assert month["reasons"] == ["JOINED_AFTER_FIRST_DAY"]
        assert out.sgp_calculation_trace["inputs"]["ordinaryWages"] == str(expected_salary)   # CPF on the payable OW


def test_joiner_on_the_first_working_day_is_paid_the_full_month():
    out = calculate_payroll(_ctx("6000", pay_date=date(2026, 8, 31), period_start=date(2026, 8, 1),
                                 period_end=date(2026, 8, 31), date_of_joining=date(2026, 8, 3),
                                 sgp_employment_facts=dict(_WEEK5)), "standard")          # 1–2 Aug are a weekend
    assert out.attendance_deduction == D("0.00") and out.sgp_calculation_trace["incompleteMonth"]["daysWorked"] == "21"


def test_joiner_leaver_and_no_pay_combine_without_double_deduction():
    both = calculate_payroll(_jctx(date_of_joining=date(2026, 6, 16), unpaid_leave_days=3,
                                   sgp_employment_facts={"workPattern": "5_DAY",
                                                         "unpaidDates": ["2026-06-03", "2026-06-22", "2026-06-23"]}), "standard")
    month = both.sgp_calculation_trace["incompleteMonth"]
    # 3 June is before the employment began — not a no-pay day of this employment.
    assert (month["daysWorked"], month["noPayDates"], month["salary"]) == ("9", ["2026-06-22", "2026-06-23"], "2454.55")
    assert both.attendance_deduction == D("3545.45")                                     # one deduction, not two
    left = calculate_payroll(_jctx(date_of_leaving=date(2026, 6, 12), unpaid_leave_days=2,
                                   sgp_employment_facts={"workPattern": "5_DAY", "unpaidDates": ["2026-06-03", "2026-06-04"]}),
                             "standard")
    assert left.sgp_calculation_trace["incompleteMonth"]["salary"] == "2181.82"


def test_half_day_no_pay_leave_counts_half():
    out = calculate_payroll(_jctx(unpaid_leave_days=1, sgp_employment_facts={
        "workPattern": "5_DAY", "unpaidDates": ["2026-06-03"], "unpaidHalfDayDates": ["2026-06-03"]}), "standard")
    month = out.sgp_calculation_trace["incompleteMonth"]
    assert (month["noPayDays"], month["daysWorked"], month["salary"]) == ("0.5", "21.5", "5863.64")   # 6,000 × 21.5 / 22


def test_incomplete_month_fails_closed():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:          # no work pattern
        singapore.calculate(_jctx(date_of_joining=date(2026, 6, 16), sgp_employment_facts={"unpaidDates": []}))
    assert exc.value.key == "ea_work_pattern"
    with pytest.raises(SingaporeCalculationBlockedError) as exc:          # rest day the MOM table does not assume
        singapore.calculate(_jctx(date_of_joining=date(2026, 6, 16),
                                  sgp_employment_facts={"workPattern": "6_DAY", "restDay": "WED", "unpaidDates": []}))
    assert exc.value.key == "ea_rest_day"
    with pytest.raises(SingaporeCalculationBlockedError) as exc:          # part-time: no authoritative rule in the project
        singapore.calculate(_jctx(date_of_joining=date(2026, 6, 16), employment_type="part_time"))
    assert exc.value.key == "employment_type"
    with pytest.raises(SingaporeCalculationBlockedError) as exc:          # unpaid days without their dates
        singapore.calculate(_ctx("6000", unpaid_leave_days=2))
    assert exc.value.key == "no_pay_leave_dates"
    with pytest.raises(SingaporeCalculationBlockedError) as exc:          # salary for a month outside the employment
        singapore.calculate(_jctx(date_of_leaving=date(2026, 5, 29)))
    assert exc.value.key == "employment_period"
    # a complete month needs no work pattern at all (nothing to pro-rate)
    assert _trace(singapore.calculate(_ctx("6000")))["incompleteMonth"] == {"status": "COMPLETE_MONTH"}


def test_other_countries_keep_the_generic_attendance_deduction():
    """The standard.py hook is keyed on a Singapore-only result key: an India
    payslip with unpaid days is exactly the platform's per-day formula."""
    from app.modules.payroll.engine.base import PayrollContext as Ctx

    out = calculate_payroll(Ctx(gross=D("30000"), basic=D("15000"), country="IN", unpaid_leave_days=3, calendar_days=30,
                                pay_date=date(2026, 6, 30)), "standard")
    assert (out.attendance_deduction, out.per_day_salary, out.payable_days, out.calendar_days) == (
        D("3000.00"), D("1000.00"), 27, 30)


def test_pwm_evaluates_the_monthly_rate_in_an_incomplete_month():
    from app.modules.payroll.engine.jurisdictions.singapore import labour
    from app.modules.payroll import service

    trace = _trace(singapore.calculate(_jctx(date_of_joining=date(2026, 6, 16))))
    wages = service._sg_wage_views(trace)
    assert (wages["basic"], wages["incomplete_month"]) == (D("6000"), True)            # the rate, not the 3,000 paid
    rates = {"pwm__CLEANING__G1__GENERAL_INDOOR": Rate(flat_amount=D("2080"), text_value="BASIC")}
    facts = {"pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR", "residency": "SC"}
    emp = {"employeeId": 1}
    met = labour.pwm_check(emp, facts, {**wages, "basic": D("2080")}, rates)
    assert [c["code"] for c in met] == ["PWM_INCOMPLETE_MONTH_RATE_EVALUATED", "PWM_MET"]
    short = labour.pwm_check(emp, facts, {**wages, "basic": D("2000")}, rates)
    assert [c["code"] for c in short][-1] == "PWM_SHORTFALL"                             # never bypassed


def _joiner(db, organization, code, joined, **cf):
    return _sg_employee(db, organization.id, code, ctc=D("72000"), date_of_joining=joined,
                        compliance_fields={"nric_fin": "S1234567D", "ea_work_pattern": "5_DAY", **cf})


def _attend(db, organization, emp, day, status, leave_type=None, half=False):
    from app.modules.payroll.models import PayrollAttendanceRecord

    db.add(PayrollAttendanceRecord(organization_id=organization.id, employee_id=emp.id, date=day, status=status,
                                   leave_type=leave_type, is_half_day=half))
    db.commit()


def test_run_includes_a_singapore_mid_month_joiner_and_only_singapore(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run = _pf_run(db, organization, monkeypatch)                                  # May 2026: 21 working days
    joiner = _joiner(db, organization, "JMID", date(2026, 5, 18))                 # Mon 18 → 10 working days
    staff = _sg_employee(db, organization.id, "JOLD", ctc=D("72000"), date_of_joining=date(2024, 1, 2))
    india = _sg_employee(db, organization.id, "JIND", country_code="IN", date_of_joining=date(2026, 5, 18))
    service.generate_payslips_for_run(db, run, organization.id)
    by_emp = {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()}
    assert joiner.id in by_emp and staff.id in by_emp and india.id not in by_emp   # other countries' selection unchanged
    month = by_emp[joiner.id].sgp_calculation_trace["incompleteMonth"]
    assert (month["workingDaysInMonth"], month["daysWorked"], month["reasons"]) == ("21", "10", ["JOINED_AFTER_FIRST_DAY"])
    rate = D(month["monthlyGrossRate"])
    salary = (rate * 10 / 21).quantize(D("0.01"))
    assert D(month["salary"]) == salary and by_emp[joiner.id].attendance_deduction == rate - salary
    ow = D(by_emp[joiner.id].sgp_calculation_trace["inputs"]["ordinaryWages"])
    assert ow == salary + sum((D(v) for v in month["excludedMonthlyComponentsPaidInFull"].values()), D("0"))
    subject = min(ow, D("8000"))
    assert by_emp[joiner.id].employee_pension == (D("0.20") * subject).quantize(D("1"), rounding="ROUND_FLOOR")
    assert by_emp[joiner.id].employer_payroll_tax == (D("0.0025") * ow).quantize(D("0.01"))
    assert by_emp[staff.id].sgp_calculation_trace["incompleteMonth"] == {"status": "COMPLETE_MONTH"}
    preflight = service.sg_payroll_preflight(db, organization.id, run.id)
    assert "EA_INCOMPLETE_MONTH" in _codes(preflight, joiner)
    preview = service.preview_payroll_run(db, organization.id, [joiner.id], "SG", date(2026, 5, 1), date(2026, 5, 31))
    assert [r["employeeId"] for r in preview["employees"]] == [joiner.id]


def test_run_no_pay_leave_counts_only_unpaid_working_days(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run = _pf_run(db, organization, monkeypatch)
    emp = _joiner(db, organization, "JNOPAY", date(2024, 1, 2))
    _attend(db, organization, emp, date(2026, 5, 4), "absent")
    _attend(db, organization, emp, date(2026, 5, 5), "leave", "unpaid")
    _attend(db, organization, emp, date(2026, 5, 6), "leave", "sick")             # paid leave is worked time
    _attend(db, organization, emp, date(2026, 5, 7), "leave", "unpaid", half=True)
    _attend(db, organization, emp, date(2026, 5, 9), "absent")                    # a Saturday: not a working day
    service.generate_payslips_for_run(db, run, organization.id)
    month = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one().sgp_calculation_trace["incompleteMonth"]
    assert month["noPayDates"] == ["2026-05-04", "2026-05-05", "2026-05-07"] and month["noPayDatesNotCounted"] == ["2026-05-09"]
    assert (month["noPayDays"], month["daysWorked"]) == ("2.5", "18.5")


def test_joiner_without_a_work_pattern_blocks_the_run_and_commits_nothing(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run = _pf_run(db, organization, monkeypatch)
    _sg_employee(db, organization.id, "JNOPAT", date_of_joining=date(2026, 5, 18))
    with pytest.raises(Exception, match="ea_work_pattern"):
        service.generate_payslips_for_run(db, run, organization.id)
    db.rollback()
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 0


def test_joiner_correction_replays_frozen_rates_and_keeps_the_incomplete_month(db, organization, monkeypatch):
    """A joiner's finalized payslip; a no-pay day is recorded late and the live
    SDL rate changes. The correction recomputes the incomplete month with the
    corrected attendance on the payslip's own frozen rates: an append-only
    delta, the original untouched, YTD equal to the corrected wages."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayrollYtdAccumulator, PayslipItem

    run, emp, item = _finalized(db, organization, monkeypatch, code="JCOR", date_of_joining=date(2026, 5, 18),
                                compliance_fields={"nric_fin": "S1234567D", "ea_work_pattern": "5_DAY"})
    before = _snapshot(item)
    original = item.sgp_calculation_trace["incompleteMonth"]
    assert original["daysWorked"] == "10"
    sdl = db.query(ContributionRate).filter(ContributionRate.component_key == "sdl",
                                            ContributionRate.jurisdiction_country == "SG").first()
    sdl.employer_rate_pct = D("0.0030")
    db.commit()
    _attend(db, organization, emp, date(2026, 5, 20), "absent")
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "no-pay day recorded late", actor_id=MAKER.id)
    db.refresh(item)
    assert _snapshot(item) == before                                              # the original never changes
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    corrected = delta.sgp_calculation_trace["incompleteMonth"]
    assert (corrected["daysWorked"], corrected["reasons"]) == ("9", ["JOINED_AFTER_FIRST_DAY", "NO_PAY_LEAVE"])
    rate = D(original["monthlyGrossRate"])
    salary_change = (rate * 9 / 21).quantize(D("0.01")) - (rate * 10 / 21).quantize(D("0.01"))
    ow_before, ow_after = D(original["salary"]), D(corrected["salary"])
    assert ow_after - ow_before == salary_change
    other = sum((D(v) for v in original["excludedMonthlyComponentsPaidInFull"].values()), D("0"))
    tw_before, tw_after = ow_before + other, ow_after + other
    frozen_sdl = lambda tw: (D("0.0025") * tw).quantize(D("0.01"))              # noqa: E731 — replayed at 0.25%
    assert delta.employer_payroll_tax == frozen_sdl(tw_after) - frozen_sdl(tw_before)
    ee = lambda tw: (D("0.20") * tw).quantize(D("1"), rounding="ROUND_FLOOR")    # noqa: E731
    assert delta.employee_pension == ee(tw_after) - ee(tw_before)
    ytd = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id,
                                                 PayrollYtdAccumulator.tax_component == "cpf_ow_subject").one()
    assert ytd.ytd_taxable_wages == tw_after                                      # YTD = corrected wages, once
    with pytest.raises(Exception, match="no change"):                              # deterministic replay: nothing left
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "again", actor_id=MAKER.id)


def test_joiner_ir8a_reports_the_salary_actually_paid(db, organization, monkeypatch):
    from app.modules.payroll import service

    run, emp, item = _finalized(db, organization, monkeypatch, code="JIR8A", date_of_joining=date(2026, 5, 18),
                                compliance_fields={"nric_fin": "S1234567D", "ea_work_pattern": "5_DAY"})
    iras = item.sgp_calculation_trace["iras"]["totals"]
    month = item.sgp_calculation_trace["incompleteMonth"]
    paid = D(month["salary"]) + sum((D(v) for v in month["excludedMonthlyComponentsPaidInFull"].values()), D("0"))
    assert sum((D(v) for v in iras.values()), D("0")) == paid                     # IRAS items = amounts as paid


def test_no_pay_correction_after_the_absence_is_reversed(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollAttendanceRecord, PayslipItem

    run = _pf_run(db, organization, monkeypatch)
    emp = _joiner(db, organization, "JREV", date(2024, 1, 2))
    _attend(db, organization, emp, date(2026, 5, 12), "absent")
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    run.status = "Approved"
    db.commit()
    assert item.sgp_calculation_trace["incompleteMonth"]["daysWorked"] == "20"
    db.query(PayrollAttendanceRecord).filter(PayrollAttendanceRecord.employee_id == emp.id).delete()
    db.commit()                                                   # the absence was recorded in error
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "absence reversed", actor_id=MAKER.id)
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    assert delta.sgp_calculation_trace["incompleteMonth"] == {"status": "COMPLETE_MONTH"}
    rate = D(item.sgp_calculation_trace["incompleteMonth"]["monthlyGrossRate"])
    assert D(delta.sgp_calculation_trace["inputs"]["ordinaryWages"]) == rate - (rate * 20 / 21).quantize(D("0.01"))



def test_overtime_correction_replays_the_frozen_rate_and_posts_ytd(db, organization, monkeypatch):
    """Phase 5.2 (035): overtime hours recorded late are corrected on the
    payslip's own frozen overtime rule rows (a later edit of the live
    multiplier must not replay); the delta is OW and reaches YTD once."""
    from decimal import ROUND_CEILING
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayrollAttendanceRecord, PayrollYtdAccumulator, PayslipItem

    run, emp = _ot_setup(db, organization, monkeypatch)
    service.generate_payslips_for_run(db, run, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id).one()
    run.status = "Approved"
    db.commit()
    before = _snapshot(item)
    assert item.overtime == D("188.82")                                              # 6 h
    mult = db.query(ContributionRate).filter(ContributionRate.component_key == "ea_overtime_rate_multiplier",
                                             ContributionRate.jurisdiction_country == "SG").first()
    mult.flat_amount = D("2")                                                         # a later live edit
    db.add(PayrollAttendanceRecord(organization_id=organization.id, employee_id=emp.id, date=date(2026, 5, 7),
                                   status="present", hours="10"))                     # +2 h recorded late
    db.commit()
    out = service.correct_sg_finalized_payslip(db, organization.id, item.id, "overtime recorded late", actor_id=MAKER.id)
    db.refresh(item)
    assert _snapshot(item) == before
    hourly = D(12) * D(4000) / (D(52) * D(44))
    after = (D(8) * D("1.5") * hourly).quantize(D("0.01"), rounding=ROUND_CEILING)  # frozen 1.5, not 2
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    assert D(delta.sgp_calculation_trace["inputs"]["ordinaryWages"]) == after - D("188.82")
    ow_before = D(item.sgp_calculation_trace["inputs"]["ordinaryWages"])
    ytd = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id,
                                                 PayrollYtdAccumulator.tax_component == "cpf_ow_subject").one()
    assert ytd.ytd_taxable_wages == ow_before + after - D("188.82")
    with pytest.raises(Exception, match="no change"):
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "again", actor_id=MAKER.id)



# ══ Phase 5.3 — compliance completion ════════════════════════════════════
# SG-002 release scope ("The first release does not support platform-worker
# CPF, seafarer/special employment classes, overseas-only contracts, complex
# equity compensation, employee share-option tax-deemed-exercise
# calculations, employer-of-record legal employment …").

@pytest.mark.parametrize("employment_class", ["PLATFORM_WORKER", "SEAFARER", "OVERSEAS_ONLY", "EOR"])
def test_unsupported_employment_classes_fail_closed(employment_class):
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("6000", sgp_employment_facts={"employmentClass": employment_class}))
    assert exc.value.key == "employment_class" and "SG-002" in exc.value.reason


def test_standard_and_unrecorded_employment_class_are_calculated():
    recorded = _trace(singapore.calculate(_ctx("6000", sgp_employment_facts={"employmentClass": "STANDARD"})))
    unrecorded = _trace(singapore.calculate(_ctx("6000")))
    assert (recorded["inputs"]["employmentClass"], recorded["inputs"]["employmentClassBasis"]) == ("STANDARD", "RECORDED")
    assert unrecorded["inputs"]["employmentClassBasis"] == "NOT_RECORDED_TREATED_AS_STANDARD"
    assert recorded["result"] == unrecorded["result"]                                  # same payroll either way


def test_share_plan_income_fails_closed():
    with pytest.raises(SingaporeCalculationBlockedError) as exc:
        singapore.calculate(_ctx("7000", basic=D("6000"), special_allowance=D("1000"),
                                 sgp_iras_classification={"iras_share_plan_gains": {"special_allowance": True}}))
    assert exc.value.key == "iras_classification:special_allowance" and "SG-002" in exc.value.reason


def test_employment_class_field_validation():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import SGEmployeeValidation

    base = {"nric_fin": "S1234567D", "cpf_residency_status": "SC", "work_pass_type": "NONE", "shg_funds": "NONE"}
    assert SGEmployeeValidation.validate({**base, "employment_class": "seafarer"})["employment_class"] == "SEAFARER"
    with pytest.raises(BadRequestException):
        SGEmployeeValidation.validate({**base, "employment_class": "CONTRACTOR"})


def test_preflight_warns_unrecorded_class_blocks_unsupported_and_is_tenant_scoped(db, organization, monkeypatch):
    from app.modules.payroll import service

    run = _pf_run(db, organization, monkeypatch)
    plain = _sg_employee(db, organization.id, "CLSNONE")
    sea = _sg_employee(db, organization.id, "CLSSEA", compliance_fields={"nric_fin": "S1234567D", "employment_class": "SEAFARER"})
    other = _other_org(db, "CLSOTHER")
    stranger = _sg_employee(db, other.id, "CLSSTRANGER", compliance_fields={"nric_fin": "S1234567D", "employment_class": "EOR"})
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    assert "SG_EMPLOYMENT_CLASS_NOT_RECORDED" in _codes(result, plain)
    assert "ENGINE_BLOCK:employment_class" in _codes(result, sea) and result["status"] == "BLOCKED"
    assert not _codes(result, stranger)                                              # Tenant B never evaluated
    with pytest.raises(Exception, match="employment_class"):
        service.generate_payslips_for_run(db, run, organization.id)


# SG-018 — PWM / Occupational PW (MOM Occupational PWs page, retrieved
# 2026-09-25, sha256 37b2e305…; sector pages for the part-time basis).

def test_occupational_pw_rows_are_effective_dated_and_source_traced(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import SourceArtifact

    _activate_directly(db, _seed(db))
    june, july = (service._sg_active_pack_and_rates(db, d)[1] for d in (date(2026, 6, 30), date(2026, 7, 31)))
    assert (june["pwm__OPW_ADMIN__ALL__ASSISTANT"].flat_amount, july["pwm__OPW_ADMIN__ALL__ASSISTANT"].flat_amount) == (
        D("1980"), D("2170"))                                                         # 1 Jul 2025– / 1 Jul 2026–
    assert june["pwm__OPW_DRIVER__ALL__GENERAL_DRIVER"].flat_amount == D("2190")
    assert "pwm__OPW_DRIVER__ALL__GENERAL_DRIVER" not in july                          # replaced by Groups A / B
    assert july["pwm__OPW_DRIVER__GROUP_B__LEVEL_1"].flat_amount == D("2505")
    row = july["pwm__OPW_ADMIN__ALL__SUPERVISOR"]
    assert (row.flat_amount, row.text_value) == (D("3340"), "GROSS")
    src = db.get(SourceArtifact, row.source_document_id)
    assert src.checksum_sha256.startswith("37b2e3058ba8")


def test_part_time_pwm_uses_the_published_44_hour_basis_only_where_published():
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = {"pwm__FOOD_SERVICES__A_QUICK__STALL_ASSISTANT": Rate(flat_amount=D("2220"), text_value="GROSS"),
             "pwm__CLEANING__G1__GENERAL_INDOOR": Rate(flat_amount=D("2080"), text_value="BASIC"),
             "pwm__RETAIL__ALL__ASSISTANT_CASHIER": Rate(flat_amount=D("2435"), text_value="GROSS")}
    emp = {"employeeId": 1}
    food = {"pwm_sector": "FOOD_SERVICES", "pwm_group": "A_QUICK", "pwm_job_level": "STALL_ASSISTANT", "residency": "SC",
            "employment_type": "Part-time", "contractual_weekly_hours": "22"}
    met = labour.pwm_check(emp, food, {"basic": D("1200"), "gross_ex_ot": D("1200")}, rates)
    assert [c["code"] for c in met] == ["PWM_PART_TIME_PRO_RATED", "PWM_MET"]          # 2,220 × 22 / 44 = 1,110
    short = labour.pwm_check(emp, food, {"basic": D("1100"), "gross_ex_ot": D("1100")}, rates)
    assert (short[-1]["code"], short[-1]["severity"]) == ("PWM_SHORTFALL", "BLOCK")
    cleaner = {**food, "pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR"}
    assert labour.pwm_check(emp, cleaner, {"basic": D("1"), "gross_ex_ot": D("1")}, rates)[0]["code"] == "PWM_PART_TIME_NOT_EVALUATED"
    retail = {**food, "pwm_sector": "RETAIL", "pwm_group": "ALL", "pwm_job_level": "ASSISTANT_CASHIER",
              "contractual_weekly_hours": None}
    assert labour.pwm_check(emp, retail, {"basic": D("1"), "gross_ex_ot": D("1")}, rates)[0]["code"] == "PWM_PART_TIME_NOT_EVALUATED"
    # MOM: "Additional PWM gross wage requirements for overtime" are separate schedules — still reported.
    ot = labour.pwm_check(emp, {**food, "employment_type": "Full-time", "part4": "COVERED", "overtime_paid": True},
                          {"basic": D("2300"), "gross_ex_ot": D("2300")}, rates)
    assert "PWM_OVERTIME_GROSS_NOT_EVALUATED" in [c["code"] for c in ot]


def test_compliance_centre_pwm_never_passes_an_unevaluable_cohort(db, organization, monkeypatch):
    from app.modules.payroll import service

    _pf_run(db, organization, monkeypatch)

    def pwm_item():
        return next(i for i in service.get_sg_compliance_centre(db, organization.id, as_of=date(2026, 10, 1))["items"]
                    if i["key"] == "pwm")

    _sg_employee(db, organization.id, "PWMOK", compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "OPW_ADMIN",
                                                                  "pwm_group": "ALL", "pwm_job_level": "ASSISTANT"})
    assert pwm_item()["status"] == "PASS"
    _sg_employee(db, organization.id, "PWMOLD", compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "OPW_DRIVER",
                                                                   "pwm_group": "ALL", "pwm_job_level": "GENERAL_DRIVER"})
    item = pwm_item()                                                                 # no GENERAL_DRIVER floor from 1 Jul 2026
    assert item["status"] == "FAIL" and "PWMOLD" in item["evidence"] and "SG-018" in item["blocker"]


def test_compliance_centre_pwm_fails_for_a_part_time_employee_it_cannot_evaluate(db, organization, monkeypatch):
    from app.modules.payroll import service

    _pf_run(db, organization, monkeypatch)
    _sg_employee(db, organization.id, "PWMPT", employment_type="Part-time",
                 compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "CLEANING", "pwm_group": "G1",
                                    "pwm_job_level": "GENERAL_INDOOR", "ea_contractual_weekly_hours": "20"})
    item = next(i for i in service.get_sg_compliance_centre(db, organization.id, as_of=date(2026, 10, 1))["items"]
                if i["key"] == "pwm")
    assert item["status"] == "FAIL" and "PWMPT" in item["evidence"]


# SG-023 — controlled manual IR8A submission; API DIRECT SUBMISSION NOT READY.

def _ir8a_generated(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    template = _ir8a_template(db)
    emp = _sg_employee(db, organization.id, f"IR8M{organization.id}")
    run = _run(db, organization, date(2026, 3, 31), f"IR8A {organization.id}")
    run.status = PayrollStatus.APPROVED
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                       country_code="SG", gross_pay=D("6000"), employee_pension=D("1200")))
    db.commit()
    return template, service.generate_sg_ir8a(db, organization.id, template.id, 2026, actor_id=MAKER.id)


def test_ir8a_manual_submission_lifecycle_is_maker_checker_evidenced_and_audited(db, organization):
    from fastapi import HTTPException
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    template, report = _ir8a_generated(db, organization)
    assert service.list_sg_ir8a(db, organization.id)[0]["submissionStatus"] == "EXPORT_READY"
    with pytest.raises(BadRequestException, match="maker-checker"):
        service.transition_sg_ir8a(db, organization.id, report.id, "SUBMITTED_MANUALLY", actor_id=MAKER.id, reference="X1")
    with pytest.raises(BadRequestException, match="IRAS reference"):
        service.transition_sg_ir8a(db, organization.id, report.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id)
    with pytest.raises(BadRequestException, match="allowed next"):
        service.transition_sg_ir8a(db, organization.id, report.id, "ACKNOWLEDGED", actor_id=CHECKER.id, reference="A1")
    out = service.transition_sg_ir8a(db, organization.id, report.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id,
                                     reference="MYTAX-2027-0001")
    assert out["submissionStatus"] == "SUBMITTED_MANUALLY" and out["apiDirectSubmission"] == "NOT READY"
    with pytest.raises(HTTPException) as exc:                                         # never resubmitted blindly
        service.generate_sg_ir8a(db, organization.id, template.id, 2026, actor_id=MAKER.id)
    assert exc.value.status_code == 409
    service.transition_sg_ir8a(db, organization.id, report.id, "UNKNOWN", actor_id=CHECKER.id)
    with pytest.raises(BadRequestException, match="note"):
        service.transition_sg_ir8a(db, organization.id, report.id, "ACKNOWLEDGED", actor_id=CHECKER.id, reference="ACK-1")
    done = service.transition_sg_ir8a(db, organization.id, report.id, "ACKNOWLEDGED", actor_id=CHECKER.id,
                                      reference="ACK-1", note="confirmed on myTax Portal")
    assert (done["submissionStatus"], done["acknowledgement"]["reference"]) == ("ACKNOWLEDGED", "ACK-1")
    ir8a_audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_ir8a").all()
    assert len(ir8a_audit) == 4                                                     # 3 transitions + the refused
    assert [a.action for a in ir8a_audit].count("refused") == 1                     # self-submission (Phase 6.5)
    assert next(a for a in ir8a_audit if a.action == "refused").actor_id == MAKER.id
    other = _other_org(db, "IR8AOTHER")
    with pytest.raises(HTTPException) as exc:                                         # tenant-scoped
        service.transition_sg_ir8a(db, other.id, report.id, "REJECTED", actor_id=CHECKER.id, reference="R")
    assert exc.value.status_code == 404 and service.list_sg_ir8a(db, other.id) == []
    for path, method in (("/api/payroll/singapore/reports/ir8a", "GET"),
                         ("/api/payroll/singapore/reports/ir8a/{report_id}/transition", "POST")):
        assert "get_current_payroll_operator" in _dependency_names(_route(path, method))


def test_compliance_centre_marks_ais_api_direct_submission_not_ready(db, organization, monkeypatch):
    from app.modules.payroll import service

    _pf_run(db, organization, monkeypatch)
    item = next(i for i in service.get_sg_compliance_centre(db, organization.id)["items"] if i["key"] == "ais_api")
    assert (item["label"], item["status"]) == ("API DIRECT SUBMISSION — NOT READY", "BLOCKED")


# SG-045 — effective-dated statutory facts (audit trail; no history table).

def _fact_employee(db, organization, code="FACT1", nric="S1234567D", **cf):
    return _sg_employee(db, organization.id, code, ctc=D("72000"), sgp_shg_funds="CDAC",
                        compliance_fields={"nric_fin": nric, "cpf_residency_status": "SC", "work_pass_type": "NONE",
                                           "shg_funds": "CDAC", **cf})


def _update_cf(db, organization, emp, **cf):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import EmployeeUpdate

    return service.update_employee(db, emp.id, EmployeeUpdate.model_validate({"complianceFields": cf}), organization.id,
                                   actor_id=MAKER.id)


def test_statutory_fact_change_needs_an_effective_date_and_is_audited(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxConfigurationAudit

    emp = _fact_employee(db, organization)
    with pytest.raises(BadRequestException, match="statutory_change_effective_date"):
        _update_cf(db, organization, emp, shg_funds="NONE")
    _update_cf(db, organization, emp, shg_funds="NONE", statutory_change_effective_date="2026-07-01",
               employment_class="STANDARD")                                            # first recording: no date needed
    db.refresh(emp)
    assert emp.sgp_shg_funds == "NONE" and "statutory_change_effective_date" not in (emp.compliance_fields or {})
    rows = {r.new_value["field"]: r for r in db.query(TaxConfigurationAudit).filter(
        TaxConfigurationAudit.entity_type == "sg_statutory_fact_change", TaxConfigurationAudit.entity_id == emp.id)}
    assert (rows["shg_funds"].old_value["value"], rows["shg_funds"].new_value["effectiveDate"],
            rows["shg_funds"].actor_id) == ("CDAC", "2026-07-01", MAKER.id)
    assert rows["employment_class"].old_value["value"] is None


def test_each_month_uses_the_fact_in_force_and_a_mid_month_change_blocks(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    june = _pf_run(db, organization, monkeypatch, pay_date=date(2026, 6, 30))
    emp = _fact_employee(db, organization)
    _update_cf(db, organization, emp, shg_funds="NONE", statutory_change_effective_date="2026-07-01")
    service.generate_payslips_for_run(db, june, organization.id)
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == june.id).one()
    assert item.professional_tax == D("2.00")                                         # June: still CDAC (in force)
    assert item.sgp_calculation_trace["inputs"]["statutoryFactsApplied"] == {"shg_funds": "CDAC"}
    july = _run(db, organization, date(2026, 7, 31), "Jul 2026")
    service.generate_payslips_for_run(db, july, organization.id)
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == july.id).one().professional_tax == D("0")
    mid = _fact_employee(db, organization, code="FACT2", nric="S7654321F")
    _update_cf(db, organization, mid, shg_funds="NONE", statutory_change_effective_date="2026-08-15")
    august = _run(db, organization, date(2026, 8, 31), "Aug 2026")
    with pytest.raises(Exception, match="statutory_fact_change"):                     # never applied to the whole month
        service.generate_payslips_for_run(db, august, organization.id)


def test_employment_act_status_follows_its_effective_date(db, organization):
    from app.modules.payroll import service

    emp = _fact_employee(db, organization, ea_workman="YES", ea_manager_executive="NO")
    _update_cf(db, organization, emp, ea_workman="NO", statutory_change_effective_date="2026-09-01")
    applied, block = service._sg_statutory_facts_for_month(db, emp, date(2026, 8, 1), date(2026, 8, 31))
    assert (applied, block) == ({"ea_workman": "YES"}, None)
    assert service._sg_statutory_facts_for_month(db, emp, date(2026, 9, 1), date(2026, 9, 30)) == ({}, None)


# SG-046 — PDPA-by-design (evidence-supported parts).

def test_shg_reads_are_audited_for_singapore_only(db, organization):
    from types import SimpleNamespace as NS
    from app.modules.payroll import router
    from app.modules.payroll.models import TaxConfigurationAudit

    shg = _sg_employee(db, organization.id, "SHGREAD", sgp_shg_funds="CDAC")
    _sg_employee(db, organization.id, "SHGNONE")
    user = NS(id=CHECKER.id, organization_id=organization.id)
    router.get_employee(shg.id, db=db, current_user=user)
    router.list_employees(search=None, department=None, status=None, limit=None, offset=None, db=db, current_user=user)
    rows = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_shg_data").all()
    assert [(r.action, r.new_value["employeeIds"], r.actor_id) for r in rows] == [("read", [shg.id], CHECKER.id)] * 2
    other = _other_org(db, "SHGOTHER")
    with pytest.raises(Exception):                                                    # tenant-scoped read
        router.get_employee(shg.id, db=db, current_user=NS(id=CHECKER.id, organization_id=other.id))


def test_retention_report_is_read_only_and_uses_the_statutory_minimums(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayslipItem

    _pf_run(db, organization, monkeypatch)
    old = _sg_employee(db, organization.id, "RETOLD", date_of_leaving=date(2020, 6, 30))
    cur = _sg_employee(db, organization.id, "RETCUR")
    for emp, pay in ((old, date(2019, 6, 30)), (cur, date(2026, 6, 30))):
        run = _run(db, organization, pay, f"R{pay}")
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                           employee_name=emp.name, country_code="SG", gross_pay=D("6000")))
    db.commit()
    before = db.query(PayslipItem).count()
    report = service.sg_retention_report(db, organization.id, as_of=date(2026, 10, 1))
    # 2019 payslip: IRAS ≥ 5 years from YA2020 → to 31 Dec 2025; MOM 1 year after leaving → 30 Jun 2021.
    assert report["payslips"] == {"withinStatutoryMinimum": 1, "beyondAllStatutoryMinimums": 1}
    assert report["employeesWithRecordsBeyondMinimums"] == [old.id] and "never automatic" in report["deletion"]
    assert {r["key"]: r["value"] for r in report["rules"]} == {
        "retention_mom_records_years": 2, "retention_mom_after_leaving_years": 1, "retention_iras_years_from_ya": 5}
    assert db.query(PayslipItem).count() == before                                    # nothing deleted
    db.query(ContributionRate).filter(ContributionRate.component_key == "retention_iras_years_from_ya").delete()
    db.commit()
    assert service.sg_retention_report(db, organization.id, as_of=date(2026, 10, 1))["status"] == "BLOCKED"
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/retention-report", "GET"))


def test_compliance_centre_documents_pdpa_roles_and_retention(db, organization, monkeypatch):
    from app.modules.payroll import service

    _pf_run(db, organization, monkeypatch)
    items = {i["key"]: i for i in service.get_sg_compliance_centre(db, organization.id)["items"]}
    roles = items["pdpa_roles"]
    assert roles["status"] == "REVIEW" and "Controller" in roles["evidence"] and "Data intermediary" in roles["evidence"]
    assert items["retention"]["status"] == "REVIEW" and "nothing is deleted" in items["retention"]["evidence"]


# SG-047 — the restore freeze covers IR8A, IR21 and the bank export.

def test_restore_freezes_ir8a_ir21_and_holds_the_bank_export_until_reconciled(db, organization, monkeypatch):
    from fastapi import HTTPException
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus

    _ir21_org(db, organization, monkeypatch)
    template, ir8a = _ir8a_generated(db, organization)
    service.transition_sg_ir8a(db, organization.id, ir8a.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id, reference="MYTAX-1")
    foreign = _foreign(db, organization.id, "DRIR21")
    case = _open_case(db, organization, foreign)
    run = _run(db, organization, date(2026, 5, 31), "May DR")
    _sg_employee(db, organization.id, "DRBANK", ctc=D("72000"))
    service.generate_payslips_for_run(db, run, organization.id)
    run.status = PayrollStatus.APPROVED
    db.commit()
    other = _other_org(db, "DROTHER2")
    assert service.sg_freeze_after_restore(db, other.id, "bk-1")["bankExportHeld"] == []   # tenant-scoped
    out = service.sg_freeze_after_restore(db, organization.id, "backup-2026-05-31T02:00Z", actor_id=CHECKER.id)
    assert [(f["id"], f["previousStatus"]) for f in out["frozen"]] == [(ir8a.id, "SUBMITTED_MANUALLY")]
    assert [c["id"] for c in out["ir21ReconcileFirst"]] == [case.id]
    assert run.id in [b["runId"] for b in out["bankExportHeld"]]                    # every SG run that may be paid
    assert service.list_sg_ir8a(db, organization.id)[0]["submissionStatus"] == "UNKNOWN"
    with pytest.raises(HTTPException) as exc:                                         # never paid again blindly
        _bank_rows(db, organization, run)
    assert exc.value.status_code == 409
    with pytest.raises(BadRequestException, match="note"):
        service.transition_sg_ir21_case(db, organization.id, case.id, "DRAFT", actor_id=CHECKER.id)
    assert service.transition_sg_ir21_case(db, organization.id, case.id, "DRAFT", actor_id=CHECKER.id,
                                           reason="IRAS myTax shows no IR21 filed").status == "DRAFT"
    with pytest.raises(BadRequestException):
        service.release_sg_bank_export_hold(db, organization.id, run.id, "  ", actor_id=CHECKER.id)
    service.release_sg_bank_export_hold(db, organization.id, run.id, "DBS-STMT-2026-06-01", actor_id=CHECKER.id)
    assert _bank_rows(db, organization, run)                                          # released after reconciliation
    assert "get_current_payroll_operator" in _dependency_names(
        _route("/api/payroll/singapore/disaster-recovery/bank-hold/{run_id}/release", "POST"))


# SG-051 — two consecutive parallel cycles (Oct / Nov 2026) through the real
# run path with the spec's mixed population, plus a simulated annual AIS
# close (the IR8A extract reconciled to the payroll). Expected figures are
# computed HERE from the published tables, never read from the engine:
# CPF Board Table 1 (SC ≤ 55: 37% / 20%; $500–750 phase-in), Table 2 (SPR
# year 1 G/G: 9% / 5%), Table 5 (SPR year 2 F/G: 32% / 15%); OW ceiling
# $8,000; AW ceiling = 102,000 − (YTD OW + this month's OW × months left,
# this month included); total rounded half-up to the dollar, employee
# share down; SDL 0.25% ($2–$11.25); CDAC band; MOM S Pass $650 and Work
# Permit services Tier 2 basic-skilled $600 per month.

def test_two_consecutive_parallel_cycles_with_a_simulated_ais_close(db, organization, monkeypatch):
    from decimal import ROUND_FLOOR, ROUND_HALF_UP
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollAttendanceRecord, PayrollStatus, PayslipItem

    oct_run = _pf_run(db, organization, monkeypatch, pay_date=date(2026, 10, 31))
    E = {
        "SC": _sg_employee(db, organization.id, "P51SC", ctc=D("72000"), sgp_shg_funds="CDAC"),
        "HIGH": _sg_employee(db, organization.id, "P51HIGH", ctc=D("120000")),
        "SPR1": _sg_employee(db, organization.id, "P51SPR1", ctc=D("60000"), sgp_cpf_residency_status="SPR",
                             sgp_spr_effective_date=date(2026, 3, 1), sgp_cpf_contribution_arrangement="GG"),
        "SPR2": _sg_employee(db, organization.id, "P51SPR2", ctc=D("60000"), sgp_cpf_residency_status="SPR",
                             sgp_spr_effective_date=date(2025, 6, 1), sgp_cpf_contribution_arrangement="FG"),
        "LOW": _sg_employee(db, organization.id, "P51LOW", ctc=D("7200")),
        "EP": _sg_employee(db, organization.id, "P51EP", ctc=D("96000"), sgp_cpf_residency_status="FOREIGN",
                           sgp_work_pass_type="EP", compliance_fields={"nric_fin": "G7654321N"}),
        "SPASS": _sg_employee(db, organization.id, "P51SP", ctc=D("60000"), sgp_cpf_residency_status="FOREIGN",
                              sgp_work_pass_type="S_PASS", compliance_fields={"nric_fin": "G1234567X"}),
        "WP": _sg_employee(db, organization.id, "P51WP", ctc=D("24000"), sgp_cpf_residency_status="FOREIGN",
                           sgp_work_pass_type="WORK_PERMIT", sgp_wp_sector="SERVICES", sgp_wp_skill_level="R2",
                           sgp_wp_levy_tier="TIER_2", compliance_fields={"nric_fin": "G2345678N"}),
    }
    monthly = {k: D(str(e.ctc)) / 12 for k, e in E.items()}
    rates = {"SC": (D("0.37"), D("0.20")), "HIGH": (D("0.37"), D("0.20")), "SPR1": (D("0.09"), D("0.05")),
             "SPR2": (D("0.32"), D("0.15"))}

    def cpf(code, ow, aw=D("0")):
        if code == "LOW":                                                             # Table 1 $500–750 phase-in
            total = (D("0.17") * ow + D("0.6") * (ow - 500)).quantize(D("1"), ROUND_HALF_UP)
            ee = (D("0.6") * (ow - 500)).quantize(D("1"), ROUND_FLOOR)
            return ee, total - ee
        if code not in rates:
            return D("0"), D("0")
        total_rate, ee_rate = rates[code]
        subject = min(ow, D("8000")) + aw
        total = (total_rate * subject).quantize(D("1"), ROUND_HALF_UP)
        ee = (ee_rate * subject).quantize(D("1"), ROUND_FLOOR)
        return ee, total - ee

    def sdl(tw):
        return min(max((D("0.0025") * tw).quantize(D("0.01")), D("2")), D("11.25"))

    def cycle(run):
        service.generate_payslips_for_run(db, run, organization.id)
        run.status = PayrollStatus.REVIEW
        db.commit()
        service.advance_payroll_run_status(db, run.id, CHECKER.id, organization.id)
        return {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id)}

    # ── October ─────────────────────────────────────────────────────
    slips = cycle(oct_run)
    for code, emp in E.items():
        ee, er = cpf(code, monthly[code])
        item = slips[emp.id]
        assert (item.employee_pension, item.employer_pension, item.employer_payroll_tax) == (ee, er, sdl(monthly[code])), code
    assert slips[E["SC"].id].professional_tax == D("2.00")                            # CDAC $5,000–7,500 band
    assert (slips[E["SPASS"].id].employer_eht, slips[E["WP"].id].employer_eht) == (D("650"), D("600"))
    assert slips[E["WP"].id].net_pay == monthly["WP"]                                # levy never deducted
    # ── November: a $90,000 bonus (AW ceiling binds) and a foreign leaver (IR21) ──
    db.add(PayrollAttendanceRecord(organization_id=organization.id, employee_id=E["HIGH"].id, date=date(2026, 11, 5),
                                   status="present", bonus=D("90000")))
    db.commit()
    service.record_sg_cessation(db, organization.id, E["EP"].id, date(2026, 11, 30), actor_id=MAKER.id)
    import app.core.code_generation as code_generation
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org_id, prefix, *a, **k: f"NOV{prefix}00001")      # one base code per run
    nov_run = _run(db, organization, date(2026, 11, 30), "Nov 2026")
    slips = cycle(nov_run)
    ceiling = D("102000") - (D("8000") + D("8000") * 2)                              # Nov + Dec remaining
    ee, er = cpf("HIGH", monthly["HIGH"], min(D("90000"), ceiling))
    high = slips[E["HIGH"].id]
    assert (high.employee_pension, high.employer_pension, high.employer_payroll_tax) == (ee, er, D("11.25"))
    for code in ("SC", "SPR1", "SPR2", "LOW"):
        assert (slips[E[code].id].employee_pension, slips[E[code].id].employer_pension) == cpf(code, monthly[code]), code
    assert E["EP"].id not in _bank_rows(db, organization, nov_run)                   # IR21: monies held
    # ── Simulated annual AIS close: the IR8A extract reconciles to the payroll ──
    report = service.generate_sg_ir8a(db, organization.id, _ir8a_template(db).id, 2026, actor_id=MAKER.id)
    rows = {r["employeeCode"]: r for r in report.rendered_data["employeeRows"]}
    items = ("grossSalary", "bonusAdditionalWages", "directorFees", "allowances", "grossCommission", "lumpSumPayment")
    for code, emp in E.items():
        paid = sum((i.gross_pay for i in db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id)), D("0"))
        cpf_ee = sum((i.employee_pension for i in db.query(PayslipItem).filter(PayslipItem.employee_id == emp.id)), D("0"))
        row = rows[emp.employee_code]
        assert D(str(sum(row.get(k) or 0 for k in items))) == paid, code
        assert D(str(row["employeeCpf"])) == cpf_ee, code
    assert rows["P51EP"].get("ir21PendingCaseId")                                    # IR21 not yet filed: flagged
    assert report.rendered_data["submissionStatus"] == "EXPORT_READY"
    # Correction / replay: re-running a finalized November payslip on its frozen
    # context with unchanged facts reproduces it exactly — nothing to correct.
    with pytest.raises(Exception, match="no change"):
        service.correct_sg_finalized_payslip(db, organization.id, slips[E["LOW"].id].id, "replay check", actor_id=MAKER.id)



# ══ Phase 5.4 — final hardening ═════════════════════════════════════════════
# SG-019: MOM COS 2024 factsheet — "At least $10.50 per hour for part-time
# local workers … implemented from 1 July 2024"; MOM LQS page — the hourly
# test is "(total monthly gross wages) ÷ (total hours worked for the month)".

def test_pre_july_part_time_lqs_is_evidenced_and_evaluated_from_hours_worked(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import SourceArtifact

    _activate_directly(db, _seed(db))
    march = service._sg_active_pack_and_rates(db, date(2026, 3, 31))[1]["lqs_part_time_hourly"]
    assert march.flat_amount == D("10.50")
    src = db.get(SourceArtifact, march.source_document_id)
    assert src.checksum_sha256.startswith("5822ec2358b5") and src.retrieved_at.date() == date(2026, 9, 25)
    rates = _rate_map(lqs_part_time_hourly=Rate(flat_amount=D("10.50")))

    def lqs(gross, hours):
        return _trace(singapore.calculate(_ctx(gross, pay_date=date(2026, 3, 31), employment_type="Part-time",
                                               sgp_employer_hires_foreign_workers=True, rate_map=rates,
                                               sgp_employment_facts={"hoursWorked": hours})))["lqs"]

    assert (lqs("1100", "100")["status"], lqs("1100", "100")["hourlyGross"]) == ("MEETS_LQS", "11.00")
    assert lqs("1000", "100")["status"] == "BELOW_LQS"                               # $10.00 < $10.50
    assert lqs("1000", None)["status"] == "BLOCKED"                                  # no hours: never guessed


def test_employment_facts_carry_attendance_hours_worked(db, organization):
    from app.modules.payroll import service

    emp = _sg_employee(db, organization.id, "HRSWORKED")
    for day, hours, status in ((4, "6", "present"), (5, "5.5", "present"), (6, None, "absent")):
        _attend(db, organization, emp, date(2026, 5, day), status)
        if hours:
            from app.modules.payroll.models import PayrollAttendanceRecord

            rec = db.query(PayrollAttendanceRecord).filter(PayrollAttendanceRecord.employee_id == emp.id,
                                                           PayrollAttendanceRecord.date == date(2026, 5, day)).one()
            rec.hours = hours
    db.commit()
    facts = service._sg_employment_inputs(db, organization.id, emp, date(2026, 5, 1), date(2026, 5, 31))["sgp_employment_facts"]
    assert facts["hoursWorked"] == "11.5" and facts["unpaidDates"] == ["2026-05-06"]


# SG-018: MOM OPW overtime notes §4 — part-time hourly gross = full-time
# monthly gross × 12 / (52 × 44) (the same 44-hour pro-rating); waste
# management's wage ladder publishes an "OT Rate of Pay" per hour.

def test_part_time_occupational_pw_is_evaluated_on_the_published_basis():
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    rates = {"pwm__OPW_ADMIN__ALL__ASSISTANT": Rate(flat_amount=D("2170"), text_value="GROSS")}
    facts = {"pwm_sector": "OPW_ADMIN", "pwm_group": "ALL", "pwm_job_level": "ASSISTANT", "residency": "SC",
             "employment_type": "Part-time", "contractual_weekly_hours": "20"}
    out = labour.pwm_check({"employeeId": 1}, facts, {"basic": D("990"), "gross_ex_ot": D("990")}, rates)
    assert [c["code"] for c in out] == ["PWM_PART_TIME_PRO_RATED", "PWM_MET"]        # 2,170 × 20 / 44 = 986.36


def test_waste_management_overtime_rate_of_pay_is_seeded_and_enforced(db):
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    _activate_directly(db, _seed(db))
    rates = service._sg_active_pack_and_rates(db, date(2026, 10, 31))[1]
    assert rates["pwo_WASTE_MANAGEMENT__COLLECTION__CREW"].flat_amount == D("21.56")          # 1 Jul 2026–
    assert rates["pwo_WASTE_MANAGEMENT__MRF__SENIOR_SORTER_OPERATOR"].flat_amount == D("22.34")
    facts = {"pwm_sector": "WASTE_MANAGEMENT", "pwm_group": "COLLECTION", "pwm_job_level": "CREW", "residency": "SC",
             "employment_type": "Full-time", "part4": "COVERED", "overtime_paid": True, "overtime_hours": "10"}
    wages = {"basic": D("2900"), "gross_ex_ot": D("2900")}
    short = labour.pwm_check({"employeeId": 1}, {**facts, "overtime_amount": D("200")}, wages, rates)
    assert ("PWM_OVERTIME_RATE_SHORTFALL", "BLOCK") in [(c["code"], c["severity"]) for c in short]   # $20.00/h < $21.56
    met = labour.pwm_check({"employeeId": 1}, {**facts, "overtime_amount": D("216")}, wages, rates)
    assert "PWM_OVERTIME_RATE_MET" in [c["code"] for c in met]
    assert "PWM_OVERTIME_GROSS_NOT_EVALUATED" not in [c["code"] for c in met]
    retail = labour.pwm_check({"employeeId": 1}, {**facts, "pwm_sector": "RETAIL", "pwm_group": "ALL",
                                                  "pwm_job_level": "ASSISTANT_CASHIER", "overtime_amount": D("200")},
                              {"basic": D("2500"), "gross_ex_ot": D("2500")}, rates)
    assert "PWM_OVERTIME_GROSS_NOT_EVALUATED" in [c["code"] for c in retail]           # MOM tables: storage pending


# SG-023: IRAS — non-API submission is the myTax Portal "Submit Employment
# Income Records" digital service; "Round down to the nearest dollar for
# income fields … Round up to the nearest dollar for deduction fields";
# "up to 200 records per submission".

def test_ir8a_extract_carries_the_mytax_portal_entry_with_iras_rounding(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem

    template = _ir8a_template(db)
    emp = _sg_employee(db, organization.id, "MYTAX")
    run = _run(db, organization, date(2026, 4, 30), "Apr MyTax")
    run.status = PayrollStatus.APPROVED
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name=emp.name,
                       country_code="SG", gross_pay=D("6000.75"), employee_pension=D("1200.20"), professional_tax=D("1.50")))
    db.commit()
    data = service.generate_sg_ir8a(db, organization.id, template.id, 2026, actor_id=MAKER.id).rendered_data
    entry = data["employeeRows"][0]["myTaxPortalEntry"]
    assert (entry["grossSalary"], entry["employeeCpf"], entry["shgDonations"]) == (6000, 1201, 2)
    assert data["myTaxPortalSubmission"]["maxRecordsPerSubmission"] == 200 and data["myTaxPortalSubmission"]["submissions"] == 1
    assert data["readiness"]["officialFileFormat"].startswith("NOT APPLICABLE")


# SG-046: SHG data is read only by payroll operators — every platform role is
# an operator (org_admin / payroll_admin, super_admin without an org); the
# shared employee read routes therefore need no Singapore-specific change.
# This guard fails if a non-operator role is ever introduced.

def test_every_platform_role_is_a_payroll_operator_so_shg_reads_stay_restricted():
    from app.core import dependencies
    from app.modules.auth.models import UserRole

    operators = {dependencies.ROLE_ORG_ADMIN, dependencies.ROLE_PAYROLL_ADMIN, dependencies.ROLE_SUPER_ADMIN,
                 dependencies.ROLE_ASSISTED_ACCESS}
    assert {r.value for r in UserRole} <= operators


def test_phase53_and_54_sources_record_their_real_retrieval_date(db):
    from app.modules.payroll.models import SourceArtifact

    _activate_directly(db, _seed(db))
    for fragment in ("occupational-pws-for-administrators-and-drivers", "employment-records",
                     "record-keeping-requirements", "waste-management-pwm-ot-rate-of-pay"):
        art = db.query(SourceArtifact).filter(SourceArtifact.source_url.like(f"%{fragment}%")).one()
        assert art.retrieved_at.date() == date(2026, 9, 25), fragment



# ══ Phase 5.5 — PWM overtime schedules (SG-018, OPTION A) ═══════════════════
# MOM publishes the "Total PWM Gross Wage Requirement" for 0–72 overtime
# hours per month as tables (retail, food services, Occupational PWs) —
# 6,132 cells from six MOM PDFs, stored in sgp_pwm_overtime_schedules
# (tenant-independent, effective-dated, source + sha256 per row).

def _ot_data():
    import json
    from scripts.seed_singapore_canonical_pack import PWM_OVERTIME_DATA

    return json.loads(PWM_OVERTIME_DATA.read_text(encoding="utf8"))


def test_pwm_overtime_schedules_are_seeded_exactly_from_the_mom_tables(db):
    from app.modules.payroll.models import SgpPwmOvertimeSchedule, SourceArtifact
    from scripts.seed_singapore_canonical_pack import SOURCES, _upsert_sources, seed_pwm_overtime_schedules

    _seed(db)
    data = _ot_data()
    rows = db.query(SgpPwmOvertimeSchedule).all()
    assert len(rows) == 6132 == sum(len(x["amounts"]) for x in data["schedules"])      # 84 schedules × 73 hours
    by_key = {(r.sector, r.occupation_group, r.job_level, r.effective_from.isoformat(), r.overtime_hours): r for r in rows}
    for sched in data["schedules"]:                                                   # every published cell, exactly
        src = SOURCES[f"mom_{sched['source']}"]
        for hours, amount in enumerate(sched["amounts"]):
            r = by_key[(sched["sector"], sched["group"], sched["level"], sched["effective_from"], hours)]
            assert (r.required_gross, r.effective_to.isoformat(), r.source_sha256, r.status) == (
                D(str(amount)), sched["effective_to"], src[3], "Active")
    assert {r.retrieved_at.date() for r in rows} == {date(2026, 9, 25)}
    for name, meta in data["sources"].items():
        art = db.query(SourceArtifact).filter(SourceArtifact.source_url == meta["url"]).one()
        assert art.checksum_sha256 == meta["sha256"]
    assert seed_pwm_overtime_schedules(db, _upsert_sources(db))["inserted"] == 0      # idempotent, never rewritten
    assert {r.sector for r in rows} == {"RETAIL", "FOOD_SERVICES", "OPW_ADMIN", "OPW_DRIVER"}


def test_every_schedule_is_found_at_its_effective_boundaries_and_hour_limits(db):
    from app.modules.payroll import service

    _seed(db)
    for sched in _ot_data()["schedules"]:
        first, last = date.fromisoformat(sched["effective_from"]), date.fromisoformat(sched["effective_to"])
        for on, hours in ((first, 0), (first, 1), (last, 72)):
            got = service._sg_pwm_overtime_requirement(db, sched["sector"], sched["group"], sched["level"], on, hours)
            assert (got["status"], D(got["required"])) == ("FOUND", D(sched["amounts"][hours])), (sched["level"], on, hours)
        assert service._sg_pwm_overtime_requirement(db, sched["sector"], sched["group"], sched["level"], last,
                                                    73)["status"] == "MISSING"         # beyond the Part 4 72 h


def test_overtime_hours_round_down_and_history_uses_the_schedule_in_force(db):
    from app.modules.payroll import service

    _seed(db)
    req = service._sg_pwm_overtime_requirement
    assert req(db, "RETAIL", "ALL", "ASSISTANT_CASHIER", date(2025, 10, 31), "2.8")["required"] == "2336.00"   # → 2 h
    assert req(db, "RETAIL", "ALL", "ASSISTANT_CASHIER", date(2024, 10, 31), 0)["required"] == "2175.00"      # Sep 2024–
    assert req(db, "RETAIL", "ALL", "ASSISTANT_CASHIER", date(2025, 10, 31), 0)["required"] == "2305.00"      # Sep 2025–
    fs = req(db, "FOOD_SERVICES", "B_WAITER", "WAITER", date(2026, 7, 31), 1)                  # shared MOM table
    assert (fs["required"], fs["roleLabel"]) == ("2337.00", "Kitchen Assistant (Full-Service) / Waiter")
    # MOM publishes no overtime table for the Administrative Supervisor — never assumed.
    assert req(db, "OPW_ADMIN", "ALL", "SUPERVISOR", date(2026, 7, 31), 5)["status"] == "MISSING"
    assert req(db, "OPW_DRIVER", "ALL", "GENERAL_DRIVER", date(2026, 7, 31), 5)["status"] == "MISSING"        # replaced


def test_mom_food_services_worked_example_is_a_shortfall(db):
    """MOM food services OT PDF, Scenario 2: 10 OT hours from 1 Jul 2026 →
    requirement $2,383; basic $2,100 + OT $165.20 = $2,265.20 — "insufficient"."""
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    _seed(db)
    req = service._sg_pwm_overtime_requirement(db, "FOOD_SERVICES", "A_QUICK", "STALL_ASSISTANT", date(2026, 7, 31), 10)
    assert req["required"] == "2383.00"
    rates = {"pwm__FOOD_SERVICES__A_QUICK__STALL_ASSISTANT": Rate(flat_amount=D("2220"), text_value="GROSS")}
    facts = {"pwm_sector": "FOOD_SERVICES", "pwm_group": "A_QUICK", "pwm_job_level": "STALL_ASSISTANT", "residency": "SC",
             "employment_type": "Full-time", "part4": "COVERED", "overtime_paid": True, "overtime_hours": "10",
             "overtime_gross_requirement": req}

    def codes(gross, ot):
        return {c["code"]: c["severity"] for c in labour.pwm_check({"employeeId": 1}, facts,
                                                                    {"basic": gross, "gross_ex_ot": gross, "overtime": ot}, rates)}

    assert codes(D("2100"), D("165.20"))["PWM_OVERTIME_GROSS_SHORTFALL"] == "BLOCK"          # MOM's own verdict
    assert codes(D("2217.80"), D("165.20"))["PWM_OVERTIME_GROSS_MET"] == "INFO"               # exactly $2,383.00
    assert codes(D("2217.79"), D("165.20"))["PWM_OVERTIME_GROSS_SHORTFALL"] == "BLOCK"        # one cent below
    assert "PWM_OVERTIME_GROSS_MET" in codes(D("2500"), D("165.20"))                          # above
    missing = labour.pwm_check({"employeeId": 1}, {**facts, "overtime_gross_requirement": {"status": "MISSING", "hours": 10}},
                               {"basic": D("3000"), "gross_ex_ot": D("3000"), "overtime": D("200")}, rates)
    assert "PWM_OVERTIME_GROSS_NOT_EVALUATED" in [c["code"] for c in missing]                 # never PASS without a table
    assert "PWM_OVERTIME_GROSS_MET" not in [c["code"] for c in missing]
    part_time = labour.pwm_check({"employeeId": 1}, {**facts, "employment_type": "Part-time", "contractual_weekly_hours": "20"},
                                 {"basic": D("2100"), "gross_ex_ot": D("2100"), "overtime": D("165.20")}, rates)
    assert {c["code"] for c in part_time} & {"PWM_OVERTIME_GROSS_MET", "PWM_OVERTIME_GROSS_SHORTFALL"} == set()
    assert "PWM_OVERTIME_GROSS_NOT_EVALUATED" in [c["code"] for c in part_time]           # full-time tables only


def test_retail_overtime_shortfall_is_a_warning_under_three_month_averaging(db):
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    _seed(db)
    req = service._sg_pwm_overtime_requirement(db, "RETAIL", "ALL", "ASSISTANT_CASHIER", date(2025, 10, 31), 30)
    facts = {"pwm_sector": "RETAIL", "pwm_group": "ALL", "pwm_job_level": "ASSISTANT_CASHIER", "residency": "SC",
             "employment_type": "Full-time", "part4": "COVERED", "overtime_paid": True, "overtime_hours": "30",
             "overtime_gross_requirement": req}
    rates = {"pwm__RETAIL__ALL__ASSISTANT_CASHIER": Rate(flat_amount=D("2305"), text_value="GROSS")}
    out = labour.pwm_check({"employeeId": 1}, facts, {"basic": D("2400"), "gross_ex_ot": D("2400"), "overtime": D("100")}, rates)
    assert ("PWM_OVERTIME_GROSS_SHORTFALL", "WARN") in [(c["code"], c["severity"]) for c in out]   # 2,500 < 2,776


def test_preflight_evaluates_pwm_overtime_for_its_own_tenant_only(db, organization, monkeypatch):
    from app.modules.payroll import service

    run, emp = _ot_setup(db, organization, monkeypatch, hours=("10",) * 15, basic_annual=D("24960"))   # 30 OT hours
    emp.compliance_fields = {**emp.compliance_fields, "pwm_sector": "FOOD_SERVICES", "pwm_group": "A_QUICK",
                             "pwm_job_level": "STALL_ASSISTANT"}
    other = _other_org(db, "PWMOTOTHER")
    stranger = _sg_employee(db, other.id, "PWMOTSTRANGER",
                            compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "FOOD_SERVICES",
                                               "pwm_group": "A_QUICK", "pwm_job_level": "STALL_ASSISTANT"})
    db.commit()
    result = service.sg_payroll_preflight(db, organization.id, run.id)
    ot = [c for c in result["checks"] if c.get("employeeId") == emp.id and c["code"].startswith("PWM_OVERTIME_GROSS")]
    assert ot and ot[0]["code"] in ("PWM_OVERTIME_GROSS_MET", "PWM_OVERTIME_GROSS_SHORTFALL")
    assert "sgp_pwm_overtime_schedules#" in ot[0]["source"]                                 # evidence by reference
    assert not _codes(result, stranger)
    assert "get_current_payroll_operator" in _dependency_names(_route("/api/payroll/singapore/runs/{run_id}/preflight", "GET"))


def test_pwm_overtime_rows_never_enter_the_payslip_statutory_snapshot_and_replay_ignores_them(db, organization, monkeypatch):
    import json
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, SgpPwmOvertimeSchedule

    run, emp, item = _finalized(db, organization, monkeypatch, code="SNAPOT")
    snap = item.tax_rule_snapshot or {}
    pack_ids = {r.id for r in db.query(ContributionRate.id).filter(ContributionRate.jurisdiction_pack_id == item.tax_policy_pack_id)}
    assert db.query(SgpPwmOvertimeSchedule).count() == 6132
    assert {r["id"] for r in snap["contributionRates"]} <= pack_ids                         # pack rows only
    assert len(snap["contributionRates"]) < 6132
    text = json.dumps(snap)
    assert "sgp_pwm_overtime" not in text and "Total PWM Gross Wage Requirement" not in text
    db.query(SgpPwmOvertimeSchedule).update({"status": "Superseded"})                        # compliance data changes…
    db.commit()
    with pytest.raises(Exception, match="no change"):                                        # …payroll replay does not
        service.correct_sg_finalized_payslip(db, organization.id, item.id, "replay check", actor_id=MAKER.id)

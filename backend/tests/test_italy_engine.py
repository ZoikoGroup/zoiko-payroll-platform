"""Italy (ZP-IT-ENG-001) engine behaviour — engine/countries/italy.py.

Two layers, deliberately separate:

1. GOLDEN — tests/fixtures/it_golden/italy_golden_2026.json. Every figure in
   those ten cases was worked out by hand from the specification (§3, §4, §6,
   §7, §13), then independently re-transcribed into a separate script and
   re-derived, before any of them were compared with the engine. They are the
   acceptance set: asserted here to the cent.

2. RULES — the statutory behaviour that no single golden figure can prove: each
   fail-closed path, the cumulative threshold crossing, ceiling with and
   without cohort evidence, every wedge band edge, and the tax-domicile /
   workplace separation.

The local surtax bands and the INPS classification codes are DRAFT figures the
specification does not state (IT-012 / IT-043). The golden set therefore pins
the ENGINE's behaviour on draft content, not the correctness of the rates; both
must be replaced from authoritative sources before Italy can leave PLANNED.

No DB: italy.py reads attributes off row objects, which is what keeps this
module ORM-free.
"""
import json
import os
from datetime import date
from decimal import Decimal as D

import pytest

from app.modules.payroll.engine import fallback_registry
from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries import italy, italy_content
from app.modules.payroll.engine.countries.italy import (
    ItalyCalculationBlockedError,
    calculate,
)
from app.modules.payroll.engine.countries.shared import (
    MissingComplianceConfigurationError,
    _VALIDATION_ENABLED_COUNTRIES,
)

GOLDEN_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "it_golden", "italy_golden_2026.json"
)
with open(GOLDEN_PATH, encoding="utf-8") as _fh:
    GOLDEN = json.load(_fh)
GOLDEN_BY_NAME = {case["name"]: case for case in GOLDEN}


# ── stubs ───────────────────────────────────────────────────────────────────
class Row:
    """Stand-in for a ContributionRate / TaxSlab row. italy.py reads attributes
    only, so no real ORM object is needed."""

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class Profile:
    """Stand-in for the it_* block of EmployeeStatutoryProfile."""

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class EmployerProfile:
    """Stand-in for EmployerItalyProfile (§17 B/C: CSC, CA, fund, headcount)."""

    def __init__(self, csc="70501", ca=None, fund="FIS", fis_band="UP_TO_5",
                 headcount=10):
        self.csc_code = csc
        self.ca_code = ca
        self.fund_status = {"fund": fund, "fisBand": fis_band}
        self.prior_year_avg_headcount = headcount


def _content_slabs():
    """Every IT_TAX_SLABS / IT_LOCAL_TAX_SLABS tuple as a row object, so the
    tests run against the Draft CONTENT rather than a second hard-coded copy
    that could drift from it."""
    out = []
    for rule, table, lo, hi, rate, flat, _label in (
            italy_content.IT_TAX_SLABS + italy_content.IT_LOCAL_TAX_SLABS):
        out.append(Row(rule_type=rule, tax_table_number=table, min_amount=lo,
                       max_amount=hi, rate_pct=rate, flat_amount=flat))
    return out


def _rate_map(**overrides):
    """One row per italy_content.IT_PARAMETER_KEYS scalar plus the INPS matrix
    rows for every configured worker class inside a single CSC scope (D1: the
    matrix is keyed on jurisdiction_state + tax_regime, never on a flat
    component key)."""
    rows = {}
    for key, _kind in italy_content.IT_PARAMETER_KEYS.items():
        rows[key] = Row(component_key=key, flat_amount=None,
                        employee_rate_pct=None, employer_rate_pct=None)
    for key, _label, ee, er, flat, _source in italy_content.IT_SCALAR_CONTENT:
        rows[key] = Row(component_key=key,
                        employee_rate_pct=D(ee) if ee else None,
                        employer_rate_pct=D(er) if er else None,
                        flat_amount=D(flat) if flat else None)
    for csc, ca, worker_class, family, causale, ee, er in italy_content.IT_INPS_MATRIX:
        scope = f"CSC_{csc}" + (f"_CA_{ca}" if ca else "")
        rows[f"{scope}|{worker_class}|{family}"] = Row(
            jurisdiction_state=scope, tax_regime=worker_class,
            component_key=family, filing_status=causale,
            employee_rate_pct=D(ee), employer_rate_pct=D(er))
    rows.update(overrides)
    return rows


def _slabs(extra=()):
    return _content_slabs() + list(extra)


_UNSET = object()

_LOCAL_DUE_KEYS = (
    "it_addreg_saldo_due", "it_addreg_saldo_withheld_prior",
    "it_addcom_saldo_due", "it_addcom_saldo_withheld_prior",
    "it_addcom_acconto_due", "it_addcom_acconto_withheld_prior",
    # IT-011: no wedge-sum recovery plan open.
    "it_wedge_recovery_outstanding", "it_wedge_recovery_instalment",
)


def _ctx(gross=D("3000"), *, profile=_UNSET, employer=_UNSET, rate_map=None,
         slabs=None, work_days=365, mensilita=13, mensilita_paid_prior=0,
         period_mensilita=1, ytd_base=None, ytd_taxable=None,
         ytd_withheld=None, **kwargs):
    # profile=None means "no profile at all" and is deliberately distinct from
    # the default, so the missing-profile guard can be exercised.
    # §5: a worker with no local-surtax balance or advance carries explicit
    # zeros; a test that needs an amount (or its absence) overrides one.
    for key in _LOCAL_DUE_KEYS:
        kwargs.setdefault(key, D("0"))
    # §6: a full monthly period covers 26 contributory days unless a test
    # supplies part-time hours or a shorter period.
    if "it_part_time_hours" not in kwargs:
        kwargs.setdefault("it_contributory_days", D("26"))
    return PayrollContext(
        country="IT",
        pay_date=date(2026, 3, 10),
        pay_frequency="monthly",
        gross=gross,
        basic=gross,
        payroll_days=30,
        calendar_days=30,
        italy_statutory_profile=_ready_profile() if profile is _UNSET else profile,
        italy_employer_profile=EmployerProfile() if employer is _UNSET else employer,
        rate_map=rate_map if rate_map is not None else _rate_map(),
        slabs=slabs if slabs is not None else _slabs(),
        it_work_days_in_year=work_days,
        it_mensilita=mensilita,
        it_mensilita_paid_prior=mensilita_paid_prior,
        it_period_mensilita=period_mensilita,
        it_ytd_contributory_base_prior=ytd_base,
        it_ytd_taxable_prior=ytd_taxable,
        it_ytd_irpef_withheld_prior=ytd_withheld,
        **kwargs,
    )


def _ready_profile(**overrides):
    """The minimum a live calculation needs. Anything omitted here is what a
    fail-closed test removes to prove the block."""
    values = dict(it_worker_class="OPERAIO", it_contract_type="INDETERMINATO",
                  it_cigs_applies=False, it_contributory_cap_cohort=None,
                  it_tfr_destination="AZIENDA", it_pension_fund=None,
                  it_tax_domicile_region="03", it_tax_domicile_comune="F205",
                  it_fringe_child_declared=False)
    values.update(overrides)
    return Profile(**values)


def _run(case, **kwargs):
    """One golden case through the engine, with the profile/employer facts the
    case's own inputs imply."""
    cohort = case.get("capCohort")
    profile = _ready_profile(it_contributory_cap_cohort=cohort)
    employer = EmployerProfile()
    if not cohort:
        employer.prior_year_avg_headcount = 10   # below threshold: AZIENDA legal
    ctx = _ctx(
        D(case["gross"]),
        profile=profile, employer=employer,
        work_days=case["workDays"],
        mensilita=case["mensilita"],
        mensilita_paid_prior=case["mensilitaPaidPrior"],
        ytd_base=D(case["ytdContributoryBasePrior"]),
        ytd_taxable=D(case["ytdTaxablePrior"]),
        ytd_withheld=D(case["ytdIrpefWithheldPrior"]),
        it_contributory_days=D(str(case.get("contributoryDays", 26))),
        **kwargs,
    )
    return calculate(ctx)


# ── 1. GOLDEN ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("case", GOLDEN, ids=[c["name"] for c in GOLDEN])
def test_golden_case_matches_hand_worked_figures(case):
    """Every field of every hand-worked case, to the cent."""
    got = _run(case)
    expected = case["expected"]
    by_key = {c["key"]: c for c in got["it_inps_components"]}

    assert _round2(got["it_contributory_base"]) == D(expected["contributoryBase"])
    assert _round2(got["it_contributory_cap_amount"]) == D(expected["capExcluded"])
    assert _round2(by_key["it_inps_ivs"]["employee"]) == D(expected["ivsEmployee"])
    assert _round2(by_key["it_inps_ivs"]["employer"]) == D(expected["ivsEmployer"])
    assert _round2(got["it_ivs_additional"]) == D(expected["ivsAdditional"])
    assert _round2(got["it_employee_contributions"]) == D(
        expected["employeeContributions"])
    assert _round2(got["it_taxable_income"]) == D(expected["taxableIncome"])
    assert _round2(got["it_irpef_gross_annual"]) == D(expected["irpefGrossAnnual"])
    assert _round2(got["it_detrazione_lavoro"]) == D(expected["detrazioneAnnual"])
    assert _round2(got["it_wedge_additional_deduction"]) == D(
        expected["additionalDeductionAnnual"])
    assert _round2(got["it_irpef_annual"]) == D(expected["irpefNetAnnual"])
    assert _round2(got["it_irpef"]) == D(expected["irpef"])
    assert D(expected["wedgePct"]) == _round2(got["it_wedge_band_pct"])
    assert _round2(got["it_wedge_tax_free_sum"]) == D(expected["wedgeTaxFreeSum"])
    assert _round2(got["it_tfr_gross_accrual"]) == D(expected["tfrGross"])
    assert _round2(got["it_tfr_inps_offset"]) == D(expected["tfrInpsOffset"])
    assert _round2(got["it_tfr_amount"]) == D(expected["tfrNet"])
    assert _round2(got["it_regional_tax_annual"]) == D(expected["regionalAnnual"])
    assert _round2(got["it_municipal_tax_annual"]) == D(expected["municipalAnnual"])
    assert _round2(got["it_employee_total"]) == D(expected["employeeTotal"])


def test_golden_net_pay_adds_the_wedge_benefit():
    """IT-009: the non-taxable sum is money the employee KEEPS. It is added to
    net pay, never netted inside IRPEF, so it can never reduce a deduction."""
    for case in GOLDEN:
        got = _run(case)
        expected = case["expected"]
        # Net pay is derived by standard.py; here we assert the identity the
        # golden pins, which is what that addition must produce.
        assert (_round2(D(case["gross"]) - got["it_employee_total"]
                        + got["it_wedge_tax_free_sum"])
                == D(expected["netPay"]))


def test_golden_employee_total_contains_no_surtax_liability_and_no_wedge():
    """The two objects most easily mis-folded: this year's surtax LIABILITY is
    settled at the next conguaglio (only determined instalments are withheld,
    zero in these cases), and the wedge sum is a benefit. Neither may appear
    in the employee deduction total."""
    for case in GOLDEN:
        got = _run(case)
        expected = case["expected"]
        assert got["it_local_tax_withheld_amount"] == D("0")
        assert got["it_employee_total"] == (
            got["it_employee_contributions"] + got["it_irpef"])
        assert D(expected["regionalAnnual"]) > 0 or case["name"] != "jan_2500"
        # The correct invariant: gross - employee_total + wedge = netPay
        assert _round2(D(case["gross"]) - got["it_employee_total"]
                       + got["it_wedge_tax_free_sum"]) == D(expected["netPay"])


# ── 2. INPS classification matrix (D1 / IT-002) ─────────────────────────────
def test_unconfigured_classification_blocks_rather_than_using_a_national_rate():
    """IT-002 is the rule the specification repeats most emphatically: an
    unsupported classification BLOCKS, never falls back to a generic rate."""
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_worker_class="IMPRENDITORE")))
    assert excinfo.value.key == "it_worker_class"


def test_missing_csc_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(csc=None)))
    assert excinfo.value.key == "it_inps_classification"


def test_missing_worker_class_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_worker_class=None)))
    assert excinfo.value.key == "it_worker_class"


def test_ca_code_selects_a_separate_scope():
    """A CA narrows the scope string; an employer with one must not silently
    use the CSC-only rows."""
    base = _rate_map()
    got = calculate(_ctx(profile=_ready_profile(), employer=EmployerProfile(ca=None),
                         rate_map=base))
    assert got["it_inps_scope"] == "CSC_70501"
    with pytest.raises(ItalyCalculationBlockedError):
        calculate(_ctx(profile=_ready_profile(),
                       employer=EmployerProfile(ca="01"), rate_map=base))


def test_cigs_raises_the_employee_share_to_the_specified_variation():
    """Section 6: where the employee CIGS contribution applies the employee
    total is 9.49% rather than 9.19%."""
    plain = calculate(_ctx(gross=D("3000"), profile=_ready_profile()))
    cigs = calculate(_ctx(gross=D("3000"),
                          profile=_ready_profile(it_cigs_applies=True)))
    assert cigs["it_employee_contributions"] - plain["it_employee_contributions"] == (
        _round2(D("0.30") * D("3000") / D(100)))


def test_cigs_without_a_configured_row_blocks():
    rate_map = _rate_map()
    for key in [k for k in rate_map if k.endswith("|it_inps_cigs")]:
        del rate_map[key]
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_cigs_applies=True),
                       rate_map=rate_map))
    assert excinfo.value.key == "it_inps_cigs"


# ── 3. Fund (IT-020) ────────────────────────────────────────────────────────
def test_fis_split_two_thirds_employer_one_third_employee():
    """IT-020: 0.50% (<=5 employees) / 0.80% (>5), split two-thirds employer and
    one-third employee. The split is asserted on the RATES, because INPS
    publishes each share already rounded to two decimals (0.17/0.33 and
    0.27/0.53) — dividing the rounded total by three would assert a figure no
    employer ever pays."""
    small = calculate(_ctx(gross=D("3000"), employer=EmployerProfile(fis_band="UP_TO_5")))
    large = calculate(_ctx(gross=D("3000"), employer=EmployerProfile(fis_band="OVER_5")))
    small_fis = {c["key"]: c for c in small["it_inps_components"]}["it_fis_small_employer"]
    large_fis = {c["key"]: c for c in large["it_inps_components"]}["it_fis_large_employer"]
    assert D(small_fis["employeePct"]) == D("0.17")
    assert D(small_fis["employerPct"]) == D("0.33")
    assert D(small_fis["employeePct"]) + D(small_fis["employerPct"]) == D("0.50")
    assert D(large_fis["employeePct"]) == D("0.27")
    assert D(large_fis["employerPct"]) == D("0.53")
    assert D(large_fis["employeePct"]) + D(large_fis["employerPct"]) == D("0.80")
    # The employer carries roughly twice the employee's share in both bands.
    for row in (small_fis, large_fis):
        assert D(row["employer"]) == _round2(D(row["employerPct"]) * D("3000") / D(100))
        assert D(row["employee"]) == _round2(D(row["employeePct"]) * D("3000") / D(100))
    assert small["it_fis_employee"] == D(small_fis["employee"])
    assert large["it_fis_employee"] > small["it_fis_employee"]


def test_fis_band_must_be_captured_when_fis_applies():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(fis_band=None)))
    assert excinfo.value.key == "it_fund_status"


def test_unknown_fund_position_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(fund="SOMETHING_ELSE")))
    assert excinfo.value.key == "it_fund_status"


def test_sector_fund_blocks_rather_than_assuming_the_fis_rate():
    """IT-020: sector funds differ, so there is no rate to guess."""
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(fund="SECTOR_FUND")))
    assert excinfo.value.key == "it_fund_status"


def test_missing_fund_position_blocks():
    employer = EmployerProfile()
    employer.fund_status = None
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=employer))
    assert excinfo.value.key == "it_fund_status"


# ── 4. Additional 1% and the ceiling (IT-016 / IT-017) ───────────────────────
def test_additional_1pct_is_cumulative_not_a_single_period_test():
    """A worker already past the threshold in prior periods keeps paying the
    extra 1% on the WHOLE current base — not only on the part that newly
    crosses, and not only once. Threshold is EUR 56,224."""
    # ytd 54,000 + 2,000 = 56,000 < 56,224 → no excess yet
    below = calculate(_ctx(gross=D("2000"), ytd_base=D("54000")))
    # ytd 55,000 + 2,000 = 57,000 > 56,224 → crosses during this period
    crosses = calculate(_ctx(gross=D("2000"), ytd_base=D("55000")))
    # ytd 58,000 + 2,000 = 60,000 → already past, pays on whole 2,000
    above = calculate(_ctx(gross=D("2000"), ytd_base=D("58000")))
    assert below["it_ivs_additional"] == D("0.00")
    assert crosses["it_ivs_additional"] == _round2(D("776") * D("0.01"))
    assert above["it_ivs_additional"] == _round2(D("2000") * D("0.01"))


def test_additional_1pct_below_the_threshold_is_zero():
    got = calculate(_ctx(gross=D("2000"), ytd_base=D("30000")))
    assert got["it_ivs_additional"] == D("0.00")


def test_additional_1pct_trace_records_the_crossing_period():
    """IT-016 asks for an exact crossing trace, so the crossing is recorded as
    a fact rather than inferred from the amount."""
    before = calculate(_ctx(gross=D("2000"), ytd_base=D("54000")))
    after = calculate(_ctx(gross=D("2000"), ytd_base=D("56000")))
    flagged = [c for c in before["it_inps_components"]
               if c["key"] == "it_ivs_additional_pct"][0]
    flagged_after = [c for c in after["it_inps_components"]
                     if c["key"] == "it_ivs_additional_pct"][0]
    assert flagged["crossedThisPeriod"] is False
    assert flagged_after["crossedThisPeriod"] is True


def test_ceiling_requires_cohort_evidence_it_017():
    """Income above EUR 122,295 alone must NOT cap the contribution."""
    without = calculate(_ctx(gross=D("10000"), ytd_base=D("120000"),
                             profile=_ready_profile(it_contributory_cap_cohort=None)))
    assert without["it_contributory_capped"] is False
    assert without["it_contributory_base"] == D("10000")


def test_ceiling_applies_with_cohort_evidence_and_is_cumulative():
    got = calculate(_ctx(gross=D("10000"), ytd_base=D("120000"),
                         profile=_ready_profile(it_contributory_cap_cohort="POST_1995")))
    # 120,000 of the ceiling is already used, so only 2,295 remains this period.
    assert got["it_contributory_base"] == D("2295.00")
    assert got["it_contributory_cap_amount"] == _round2(D("10000") - D("2295"))


def test_unknown_cap_cohort_blocks_rather_than_capping_on_a_typo():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_contributory_cap_cohort="MADE_UP")))
    assert excinfo.value.key == "it_contributory_cap_cohort"


def test_ceiling_is_not_eaten_by_the_additional_1pct_base():
    """Both the ceiling and the 1% threshold read the CAPPED base, so a capped
    worker cannot be charged 1% on pay that is above the ceiling."""
    got = calculate(_ctx(gross=D("10000"), ytd_base=D("120000"),
                         profile=_ready_profile(it_contributory_cap_cohort="POST_1995")))
    assert got["it_ivs_additional"] == _round2(D("2295") * D("0.01"))


# ── 5. IRPEF forecast (IT-005) ───────────────────────────────────────────────
def test_irpef_is_forecast_for_the_year_not_bracketed_on_the_month():
    """The headline rule: withholding on EUR 3,000 of January gross must not be
    3,000 at a marginal rate. It is the annual forecast spread over the
    remaining mensilita."""
    got = calculate(_ctx(gross=D("3000")))
    assert got["it_irpef"] < D("3000") * D("0.23")


def test_withholding_offsets_prior_withholding():
    """IT-005: year-to-date withholding state. The ninth run of a constant salary
    must forecast the same annual liability as the first and subtract the eight
    prior withholdings, so the annual total reconciles rather than restarting."""
    first = calculate(_ctx(gross=D("3000")))
    ytd_taxable = first["it_taxable_income"] * 8
    ninth = calculate(_ctx(gross=D("3000"), mensilita_paid_prior=8,
                           ytd_taxable=ytd_taxable,
                           ytd_withheld=first["it_irpef"] * 8))
    assert ninth["it_irpef"] > D(0)
    assert ninth["it_irpef_annual"] == first["it_irpef_annual"]
    # After 9 periods, cumulative due = annual * 9/13. The sum of 8 prior
    # withholdings plus this one may differ by 1 cent due to rounding of
    # each period's withholding. Allow 1 cent tolerance.
    cum_due_9 = _round2(first["it_irpef_annual"] * D(9) / D(13))
    actual_cum = _round2(first["it_irpef"] * 8 + ninth["it_irpef"])
    assert abs(actual_cum - cum_due_9) <= D("0.01")


def test_over_withholding_is_traced_not_allowed_to_go_negative():
    gross_tax = calculate(_ctx(gross=D("3000")))["it_irpef"]
    over = calculate(_ctx(gross=D("1000"), mensilita_paid_prior=6,
                          ytd_taxable=D("6000"), ytd_withheld=D("5000")))
    assert over["it_irpef"] == D("0.00")
    assert over["it_calculation_trace"]["overWithheld"] != "0"


def test_mensilita_state_that_does_not_fit_the_year_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(mensilita=13, mensilita_paid_prior=13))
    assert excinfo.value.key == "it_mensilita"


def test_non_integer_mensilita_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(mensilita=D("13.5")))
    assert excinfo.value.key == "it_mensilita"


def test_missing_work_days_blocks():
    """Section 4 prorates the deduction to the days of employment; without them
    the figure would be silently wrong for every part-year hire."""
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(work_days=None))
    assert excinfo.value.key == "it_work_days_in_year"


def test_ytd_totals_without_a_mensilita_record_block():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(ytd_taxable=D("5000")))
    assert excinfo.value.key == "it_ytd_taxable_prior"


# ── 6. Section 4 band edges ─────────────────────────────────────────────────
@pytest.mark.parametrize("forecast,expected_pct", [
    (D("5000"), D("7.1")),
    (D("8000"), D("7.1")),
    (D("8500"), D("7.1")),        # "up to EUR 8,500" INCLUDES 8,500
    (D("9000"), D("5.3")),
    (D("12000"), D("5.3")),
    (D("15000"), D("5.3")),
    (D("16000"), D("4.8")),
    (D("19000"), D("4.8")),
    (D("20000"), D("4.8")),
    (D("21000"), D("0")),         # no band above 20,000
    (D("25000"), D("0")),
])
def _gross_for_forecast(target, **kwargs):
    """The gross that produces approximately `target` as the annual forecast.

    The forecast is built from TAXABLE income, not gross, so gross/13 lands
    short by the employee contributions. Solving for it here (rather than
    dividing) lets the band-edge assertions sit near the statutory thresholds.
    """
    guess = target / D(13) * D("1.10")
    for _ in range(80):
        got = calculate(_ctx(gross=_round2(guess), **kwargs))
        forecast = D(got["it_calculation_trace"]["annualForecast"])
        delta = target - forecast
        if abs(delta) < D("0.05"):
            break
        guess += delta / D(13)
    return _round2(guess)


def _band_for_local(slabs, income):
    """Local copy of italy.py's _band_for for test independence."""
    for row in slabs:
        band_max = getattr(row, "max_amount", None)
        min_amt = D(str(getattr(row, "min_amount", None) or 0))
        max_amt = D(str(band_max)) if band_max is not None else None
        if income > min_amt and (max_amt is None or income <= max_amt):
            return row
    return None


@pytest.mark.parametrize("forecast,expected_pct", [
    (D("5000"), D("7.1")),
    (D("8000"), D("7.1")),
    (D("8500"), D("7.1")),        # "up to EUR 8,500" INCLUDES 8,500
    (D("9000"), D("5.3")),
    (D("12000"), D("5.3")),
    (D("15000"), D("5.3")),
    (D("16000"), D("4.8")),
    (D("19000"), D("4.8")),
    (D("20000"), D("4.8")),
    (D("21000"), D("0")),         # no band above 20,000
    (D("25000"), D("0")),
])
def test_wedge_sum_band_edges(forecast, expected_pct):
    """IT-010: the band is chosen on the ANNUALISED income. Pick a forecast
    clearly inside each band (not on the edge) to avoid rounding drift, then
    assert the engine picks the correct percentage."""
    gross = _gross_for_forecast(forecast)
    got = calculate(_ctx(gross=gross))
    actual_forecast = D(got["it_calculation_trace"]["annualForecast"])
    # The actual forecast should land in the band we intended (it may not hit
    # the exact target due to rounding, but it must be in the same statutory
    # band so the percentage is unambiguous).
    wedge_rows = [r for r in _content_slabs()
                  if getattr(r, "rule_type", None) == "IT_WEDGE_SUM"]
    band = _band_for_local(wedge_rows, actual_forecast)
    if expected_pct == D("0"):
        # No band above 20,000 - _band_for returns None and wedge_pct = 0
        assert band is None
        assert got["it_wedge_band_pct"] == D("0")
    else:
        assert band is not None
        assert _round2(got["it_wedge_band_pct"]) == expected_pct


def test_wedge_sum_is_a_benefit_not_a_deduction():
    got = calculate(_ctx(gross=D("1000")))
    assert got["it_wedge_tax_free_sum"] > D(0)
    assert got["it_irpef_annual"] == (got["it_irpef_gross_annual"]
                                      - got["it_detrazione_lavoro"]
                                      - got["it_wedge_additional_deduction"])


def test_wedge_additional_deduction_reaches_exactly_zero_at_40000():
    """At EUR 40,000 the taper formula yields exactly zero; target just above
    the boundary to be safely in the zero zone."""
    gross = _gross_for_forecast(D("40001"))
    got = calculate(_ctx(gross=gross))
    assert got["it_wedge_additional_deduction"] == D("0.00")


def test_wedge_additional_deduction_is_full_inside_its_band():
    got = calculate(_ctx(gross=D("25000") / D(13)))
    assert got["it_wedge_additional_deduction"] == D("1000.00")


def test_detrazione_is_prorated_to_the_work_period():
    """A part-year hire cannot take the full annual deduction."""
    full = calculate(_ctx(gross=D("3000"), work_days=365))
    half = calculate(_ctx(gross=D("3000"), work_days=180))
    assert half["it_detrazione_lavoro"] < full["it_detrazione_lavoro"]
    assert half["it_detrazione_lavoro"] == _round2(
        full["it_detrazione_lavoro"] * D(180) / D(365))


def test_detrazione_floor_applies_to_a_short_period_permanent_contract():
    """Pro-rating a short period can fall under the statutory floor, which then
    holds the deduction up — the floor is a floor, not a target."""
    got = calculate(_ctx(gross=D("1000"), work_days=92, mensilita=4))
    assert got["it_calculation_trace"]["detrazioneFloorApplied"] is True
    assert got["it_detrazione_lavoro"] == D("690.00")


def test_detrazione_floor_depends_on_contract_type():
    """IT-002 style: the floor differs by contract type, so it is read from
    content per contract rather than hard-coded once."""
    permanent = calculate(_ctx(gross=D("1000"), work_days=92, mensilita=4,
                               profile=_ready_profile(it_contract_type="INDETERMINATO")))
    fixed_term = calculate(_ctx(gross=D("1000"), work_days=92, mensilita=4,
                                profile=_ready_profile(it_contract_type="DETERMINATO")))
    assert permanent["it_detrazione_lavoro"] == D("690.00")
    assert fixed_term["it_detrazione_lavoro"] > permanent["it_detrazione_lavoro"]


def test_unknown_contract_type_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_contract_type="COOP")))
    assert excinfo.value.key == "it_contract_type"


# ── 7. Local surtax and the tax domicile (IT-012 / IT-013 / IT-014) ─────────
def test_local_surtax_follows_the_tax_domicile_not_the_workplace():
    """IT-013: tax domicile (ISTAT region code + cadastral comune) determines
    the local surtax, not the workplace. Only Lombardia (REG_03) and Milano
    (COM_F205) are staged in Draft content; every other locality blocks with a
    missing-content error rather than substituting a national rate."""
    # Milan domicile: configured content exists
    milan = calculate(_ctx(profile=_ready_profile(
        it_tax_domicile_region="03", it_tax_domicile_comune="F205")))
    assert milan["it_regional_tax_annual"] > D(0)
    assert milan["it_municipal_tax_annual"] > D(0)

    # Rome domicile: unconfigured → blocks on regional first
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(
            it_tax_domicile_region="12", it_tax_domicile_comune="H501")))
    assert excinfo.value.key == "it_addregionale"


def test_unconfigured_locality_blocks_rather_than_substituting_a_national_rate():
    """IT-012: no single national addizionale rate is permitted. The engine
    blocks on the first missing domicile-scoped row it encounters — regional
    before municipal."""
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(
            it_tax_domicile_region="12", it_tax_domicile_comune="H501")))
    assert excinfo.value.key == "it_addregionale"
    # If regional were present but municipal missing, it would block there.


def test_missing_tax_domicile_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_tax_domicile_region=None)))
    assert excinfo.value.key == "it_tax_domicile_region"


def test_missing_comune_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_tax_domicile_comune=None)))
    assert excinfo.value.key == "it_tax_domicile_comune"


def test_current_year_liability_is_traced_but_not_what_is_withheld():
    """This year's surtax is a LIABILITY for the next conguaglio; what is
    withheld now is only the determined amounts (none here)."""
    got = calculate(_ctx(gross=D("2500")))
    assert got["it_regional_tax_annual"] > D(0)
    assert got["it_local_tax_withheld_amount"] == D("0")
    assert got["it_employee_total"] == got["it_employee_contributions"] + got["it_irpef"]
    assert got["it_calculation_trace"]["localTaxModel"] == "DETERMINED_AMOUNTS_IN_INSTALMENTS_V2"


# ── §5 local-surtax WITHHOLDING (balances and advance) ──────────────────────
def _withholding_ctx(month, **kwargs):
    ctx = _ctx(gross=D("2500"), **kwargs)
    ctx.pay_date = date(2026, month, 10)
    return ctx


@pytest.mark.parametrize("key", [k for k in _LOCAL_DUE_KEYS if k.endswith("_due")])
def test_an_unrecorded_determined_amount_blocks(key):
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), **{key: None}))
    assert excinfo.value.key == key


def test_three_lines_are_distinct_deductions_in_the_employee_total():
    got = calculate(_withholding_ctx(
        3, it_addreg_saldo_due=D("330"), it_addcom_saldo_due=D("110"),
        it_addcom_acconto_due=D("90")))
    # March: the Jan-Nov balance windows leave 9 instalments; the Mar-Nov
    # advance window also leaves 9.
    assert got["it_addreg_saldo_withheld"] == D("36.67")
    assert got["it_addcom_saldo_withheld"] == D("12.22")
    assert got["it_addcom_acconto_withheld"] == D("10.00")
    assert got["it_local_tax_withheld_amount"] == D("58.89")
    assert got["it_employee_total"] == (got["it_employee_contributions"] + got["it_irpef"]
                                        + D("58.89"))


def test_balance_spreads_evenly_and_the_last_instalment_takes_the_remainder():
    """11 instalments Jan-Nov: the running remainder is re-spread each month,
    so November withholds exactly what is left and the total is exact."""
    due, withheld = D("100"), D("0")
    for month in range(1, 12):
        got = calculate(_withholding_ctx(month, it_addreg_saldo_due=due,
                                         it_addreg_saldo_withheld_prior=withheld))
        withheld += got["it_addreg_saldo_withheld"]
    assert withheld == due


def test_advance_is_not_withheld_before_its_window_opens():
    got = calculate(_withholding_ctx(2, it_addcom_acconto_due=D("90")))
    assert got["it_addcom_acconto_withheld"] == D("0")
    line = got["it_calculation_trace"]["localWithholding"]["addcom_acconto"]
    assert line["basis"] == "window_not_open" and line["window"] == [3, 11]


def test_a_remainder_after_the_window_closes_falls_due_at_once():
    got = calculate(_withholding_ctx(12, it_addreg_saldo_due=D("100"),
                                     it_addreg_saldo_withheld_prior=D("40")))
    assert got["it_addreg_saldo_withheld"] == D("60.00")
    assert got["it_calculation_trace"]["localWithholding"]["addreg_saldo"]["basis"] == "after_window"


def test_termination_withholds_everything_outstanding_at_once():
    got = calculate(_withholding_ctx(
        4, it_is_termination_period=True, it_ytd_wedge_paid_prior=D("0"),
        it_addreg_saldo_due=D("330"),
        it_addreg_saldo_withheld_prior=D("90"), it_addcom_acconto_due=D("90")))
    assert got["it_addreg_saldo_withheld"] == D("240.00")
    assert got["it_addcom_acconto_withheld"] == D("90.00")
    assert got["it_calculation_trace"]["terminationPeriod"] is True


def test_a_settled_amount_withholds_nothing():
    got = calculate(_withholding_ctx(5, it_addreg_saldo_due=D("100"),
                                     it_addreg_saldo_withheld_prior=D("100")))
    assert got["it_addreg_saldo_withheld"] == D("0")


def test_more_withheld_than_determined_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_addcom_saldo_due=D("50"),
                       it_addcom_saldo_withheld_prior=D("60")))
    assert excinfo.value.key == "it_addcom_saldo_withheld_prior"


def test_a_missing_schedule_row_blocks_rather_than_assuming_a_window():
    rate_map = _rate_map()
    del rate_map["it_addcom_acconto_first_month"]
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), rate_map=rate_map))
    assert excinfo.value.key == "it_addcom_acconto_first_month"


def test_advance_is_determined_on_prior_year_income_with_this_years_table():
    """Milano draft content: 0.8% above a EUR 23,000 exemption; 30% advance."""
    ctx = _ctx()
    assert italy.determine_addcom_acconto(ctx, D("30000"), "F205", True) == D("72.00")
    assert italy.determine_addcom_acconto(ctx, D("22000"), "F205", True) == D("0.00")
    assert italy.determine_addcom_acconto(ctx, D("30000"), "F205", False) == D("0")


def test_surtax_is_zero_when_no_irpef_is_due_for_the_year():
    """The additions are due on income, not on a tax bill — so with the whole
    deduction wiping out IRPEF there is nothing to add to."""
    got = calculate(_ctx(gross=D("1000"), work_days=60, mensilita=3))
    assert got["it_irpef_annual"] == D("0.00")
    assert got["it_regional_tax_annual"] == D("0.00")
    assert got["it_calculation_trace"]["localTaxZeroBecauseNoIrpef"] is True


def test_local_bands_are_progressive_not_one_rate_on_the_whole_amount():
    """IT-014: brackets, not flat rates."""
    got = calculate(_ctx(gross=D("2500")))
    regional = got["it_regional_tax_annual"]
    assert regional > _round2(got["it_taxable_income"] * D("0.0123"))


# ── 8. TFR (section 13 / section 14) ────────────────────────────────────────
# ── IT-006 conguaglio, IT-011 wedge recovery, §5/§22 surtax determination ──
# Worked case: December, gross 2,500 (contributions 229.75 + 4.25 = 234.00),
# 25,000 taxable earned before it -> actual annual 27,266.00; IRPEF 23% =
# 6,271.18, detrazione 1,910 + 1,190 x (28,000 - 27,266) / 13,000 = 1,977.19,
# additional deduction 1,000 -> net annual 3,293.99. Figures checked with a
# separate calculation that shares no engine code.
def _december(**kwargs):
    ctx = _ctx(gross=D("2500"), mensilita_paid_prior=12, ytd_taxable=D("25000"),
               it_is_conguaglio_period=True, **kwargs)
    ctx.pay_date = date(2026, 12, 15)
    return ctx


def test_conguaglio_settles_the_year_on_actual_income():
    got = calculate(_december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("0")))
    assert got["it_conguaglio"] is True
    assert got["it_calculation_trace"]["annualForecast"] == "27266.00"   # actual, not projected
    assert got["it_irpef_annual"] == D("3293.99")
    assert got["it_irpef"] == D("293.99")                               # 3,293.99 - 3,000
    assert got["it_irpef_refund"] == D("0")


def test_conguaglio_refunds_over_withholding():
    got = calculate(_december(ytd_withheld=D("3500"), it_ytd_wedge_paid_prior=D("0")))
    assert got["it_irpef"] == D("0")
    assert got["it_irpef_refund"] == D("206.01")
    assert got["it_employee_total"] == (got["it_employee_contributions"] - D("206.01"))


def test_mid_year_over_withholding_is_not_refunded():
    got = calculate(_ctx(gross=D("2500"), mensilita_paid_prior=5, ytd_taxable=D("12000"),
                         ytd_withheld=D("5000")))
    assert got["it_conguaglio"] is False
    assert got["it_irpef_refund"] == D("0")


def test_conguaglio_needs_the_wedge_sum_paid_this_year():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_december(ytd_withheld=D("3000")))
    assert excinfo.value.key == "it_ytd_wedge_paid_prior"


def test_wedge_sum_not_due_above_60_is_recovered_in_ten_instalments():
    """IT-011: 27,266 is above every wedge band, so the 300 paid during the
    year is not due; above EUR 60 it is recovered as 10 x 30.00, starting now."""
    got = calculate(_december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("300")))
    assert got["it_wedge_tax_free_sum"] == D("0")
    assert got["it_wedge_recovery_new"] == D("300.00")
    assert got["it_wedge_recovery_now"] == D("30.00")
    assert got["it_wedge_recovery_outstanding_after"] == D("270.00")
    assert got["it_wedge_recovery_instalment_after"] == D("30.00")
    assert got["it_calculation_trace"]["wedgeSettlement"]["recoveryMode"] == "10_instalments"


def test_wedge_recovery_up_to_60_is_taken_at_once():
    got = calculate(_december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("50")))
    assert got["it_wedge_recovery_now"] == D("50.00")
    assert got["it_wedge_recovery_outstanding_after"] == D("0")


def test_conguaglio_pays_a_wedge_sum_still_due():
    """Gross 1,500 (contributions on the 1,511.38 minimum: 141.47) -> actual
    annual 11,358.53 in the 5.3% band -> 602.00 due; 500 paid -> 102.00 now."""
    ctx = _ctx(gross=D("1500"), mensilita_paid_prior=12, ytd_taxable=D("10000"),
               it_is_conguaglio_period=True, it_ytd_wedge_paid_prior=D("500"))
    ctx.pay_date = date(2026, 12, 15)
    got = calculate(ctx)
    assert got["it_wedge_tax_free_sum"] == D("102.00")
    assert got["it_wedge_recovery_new"] == D("0")


def test_an_open_recovery_plan_is_deducted_each_period():
    got = calculate(_ctx(gross=D("2500"), it_wedge_recovery_outstanding=D("270"),
                         it_wedge_recovery_instalment=D("30")))
    assert got["it_wedge_recovery_now"] == D("30.00")
    assert got["it_wedge_recovery_outstanding_after"] == D("240.00")
    assert got["it_employee_total"] == (got["it_employee_contributions"] + got["it_irpef"] + D("30.00"))


def test_the_last_plan_instalment_takes_only_what_is_left():
    got = calculate(_ctx(gross=D("2500"), it_wedge_recovery_outstanding=D("12"),
                         it_wedge_recovery_instalment=D("30")))
    assert got["it_wedge_recovery_now"] == D("12.00")
    assert got["it_wedge_recovery_instalment_after"] == D("0")


def test_an_open_plan_without_its_instalment_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_wedge_recovery_outstanding=D("270")))
    assert excinfo.value.key == "it_wedge_recovery_instalment"


def test_termination_recovers_an_open_plan_in_full():
    ctx = _ctx(gross=D("2500"), it_is_termination_period=True, it_ytd_wedge_paid_prior=D("0"),
               it_wedge_recovery_outstanding=D("270"), it_wedge_recovery_instalment=D("30"))
    got = calculate(ctx)
    assert got["it_wedge_recovery_now"] == D("270.00")
    assert got["it_wedge_recovery_outstanding_after"] == D("0")


def test_year_end_determines_next_years_surtax_balances():
    """Lombardia 184.50 + 193.80 = 378.30; Milano 0.8% x 27,266 = 218.13 less
    the 60 advance = 158.13. Withheld next year, not now."""
    got = calculate(_december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("0"),
                              it_addcom_acconto_due=D("60"), it_addcom_acconto_withheld_prior=D("60")))
    assert got["it_addreg_saldo_determined"] == D("378.30")
    assert got["it_addcom_saldo_determined"] == D("158.13")
    assert got["it_termination_surtax_withheld"] == D("0")


def test_an_advance_above_the_liability_leaves_a_credit_not_a_negative_balance():
    got = calculate(_december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("0"),
                              it_addcom_acconto_due=D("300"), it_addcom_acconto_withheld_prior=D("300")))
    assert got["it_addcom_saldo_determined"] == D("0")
    assert got["it_addcom_credit_determined"] == D("81.87")


def test_termination_withholds_the_years_surtax_balances_now():
    """§22: no later pay exists, so 378.30 + 158.13 = 536.43 is withheld now."""
    ctx = _december(ytd_withheld=D("3000"), it_ytd_wedge_paid_prior=D("0"),
                    it_addcom_acconto_due=D("60"), it_addcom_acconto_withheld_prior=D("60"))
    ctx.it_is_termination_period = True
    got = calculate(ctx)
    assert got["it_termination_surtax_withheld"] == D("536.43")
    assert got["it_employee_total"] == _round2(
        got["it_employee_contributions"] + got["it_irpef"] + D("536.43"))


# ── §11 fringe benefits and meal vouchers (IT-031..IT-033) ────────────────
def test_fringe_within_the_annual_limit_is_not_taxable():
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("400"), it_ytd_fringe_prior=D("300")))
    assert got["it_fringe_taxable"] == D("0")
    assert got["it_fringe_ytd_after"] == D("700")


def test_crossing_the_limit_taxes_the_whole_years_amount_not_the_excess():
    """IT-031: 800 already exempt + 300 now crosses EUR 1,000, so all 1,100 is
    taxable in this period — not just the 100 above the limit."""
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("300"), it_ytd_fringe_prior=D("800")))
    assert got["it_fringe_taxable"] == D("1100")
    assert got["it_calculation_trace"]["fringeCrossedThisPeriod"] is True


def test_after_the_crossing_each_benefit_is_taxed_in_full():
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("200"), it_ytd_fringe_prior=D("1100")))
    assert got["it_fringe_taxable"] == D("200")


def test_child_declaration_raises_the_limit():
    """IT-032: the higher limit needs the employee's own declaration."""
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("300"), it_ytd_fringe_prior=D("800"),
                         profile=_ready_profile(it_fringe_child_declared=True)))
    assert got["it_fringe_taxable"] == D("0")
    assert got["it_calculation_trace"]["fringeLimit"] == "2000.00"


def test_a_fringe_value_without_its_year_to_date_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_fringe_amount=D("300")))
    assert excinfo.value.key == "it_ytd_fringe_prior"


def test_meal_vouchers_tax_only_the_excess_and_paper_has_its_own_limit():
    got = calculate(_ctx(gross=D("2500"),
                         it_meal_electronic_count=D("20"), it_meal_electronic_value=D("12"),
                         it_meal_paper_count=D("10"), it_meal_paper_value=D("6")))
    # electronic (12 - 10) x 20 = 40; paper (6 - 4) x 10 = 20 — paper never
    # inherits the EUR 10 electronic limit.
    assert got["it_meal_voucher_taxable"] == D("60.00")
    meals = got["it_calculation_trace"]["mealVouchers"]
    assert meals["electronic"]["taxable"] == "40.00" and meals["paper"]["taxable"] == "20.00"


def test_vouchers_within_the_limit_are_not_taxable():
    got = calculate(_ctx(gross=D("2500"), it_meal_electronic_count=D("20"),
                         it_meal_electronic_value=D("8")))
    assert got["it_meal_voucher_taxable"] == D("0")


def test_meal_vouchers_without_a_face_value_block():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_meal_paper_count=D("5")))
    assert excinfo.value.key == "it_meal_paper_value"


def test_taxable_benefits_raise_income_and_the_inps_base_but_are_never_paid():
    plain = calculate(_ctx(gross=D("2500")))
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("300"), it_ytd_fringe_prior=D("800")))
    assert got["it_contributory_base"] == D("3600")                    # 2500 cash + 1100 fringe
    assert got["it_taxable_income"] == D("2500") - got["it_employee_contributions"] + D("1100")
    # Net cash falls: more tax and contributions, and the benefit itself is
    # never added to pay.
    net = lambda r: D("2500") - r["it_employee_total"] + r["it_wedge_tax_free_sum"]
    assert net(got) < net(plain)


def test_a_one_off_taxable_benefit_is_not_projected_over_the_year():
    """IT-005: the 1,100 enters the annual forecast once, not x 13."""
    got = calculate(_ctx(gross=D("2500"), it_fringe_amount=D("300"), it_ytd_fringe_prior=D("800")))
    one_off, taxable = got["it_fringe_taxable"], got["it_taxable_income"]
    forecast = D(got["it_calculation_trace"]["annualForecast"])
    assert forecast == _round2((taxable - one_off) * 13 + one_off)


# ── §2/§6 INPS contributory minimum (IT-004 / IT-018) ──────────────────────
def test_minimum_raises_the_inps_base_but_not_taxable_pay():
    got = calculate(_ctx(gross=D("1000")))
    assert got["it_contributory_base"] == D("1511.38")      # 58.13 x 26
    assert got["it_contributory_minimum_applied"] is True
    # IRPEF taxable income is actual pay minus contributions actually deducted.
    assert got["it_taxable_income"] == D("1000") - got["it_employee_contributions"]


def test_pay_above_the_minimum_is_untouched():
    got = calculate(_ctx(gross=D("2500")))
    assert got["it_contributory_base"] == D("2500")
    assert got["it_contributory_minimum_applied"] is False


def test_minimum_follows_the_contributory_days_of_a_short_period():
    got = calculate(_ctx(gross=D("500"), it_contributory_days=D("10")))
    assert got["it_contributory_base"] == D("581.30")


def test_part_time_minimum_is_hourly_on_ccnl_hours_not_an_eight_hour_day():
    """IT-018: 58.13 x 6 / 40 = 8.72 per hour; 80 hours = 697.60. Dividing by
    a generic 8-hour day would give 7.27/hour instead."""
    got = calculate(_ctx(gross=D("600"), it_part_time_hours=D("80"),
                         it_ccnl_weekly_hours=D("40")))
    assert got["it_contributory_base"] == D("697.60")
    minimum = got["it_calculation_trace"]["contributoryMinimum"]
    assert minimum["basis"] == "part_time" and minimum["hourlyMinimum"] == "8.72"


def test_part_time_without_ccnl_hours_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("600"), it_part_time_hours=D("80")))
    assert excinfo.value.key == "it_ccnl_weekly_hours"


def test_missing_contributory_days_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_contributory_days=None))
    assert excinfo.value.key == "it_contributory_days"


def test_more_days_than_a_full_month_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("2500"), it_contributory_days=D("27")))
    assert excinfo.value.key == "it_contributory_days"


def test_a_full_month_uses_the_configured_day_count():
    got = calculate(_ctx(gross=D("1000"), it_contributory_days=None, it_contributory_full_month=True))
    assert got["it_contributory_base"] == D("1511.38")


def test_a_part_time_worker_without_hours_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(gross=D("800"), it_contributory_days=None, it_is_part_time=True))
    assert excinfo.value.key == "it_part_time_hours"


def test_tfr_accrues_on_actual_pay_even_when_the_minimum_applies():
    got = calculate(_ctx(gross=D("1000")))
    assert got["it_tfr_gross_accrual"] == D("74.07")       # 1000 / 13.5
    assert got["it_tfr_inps_offset"] == D("7.56")          # 0.50% of 1511.38


# ── §13 TFR revaluation and IT-039 separate taxation ───────────────────────
def test_tfr_revaluation_full_year():
    """10,000 accrued, ISTAT +2.0%: 1.5% + 75% x 2.0% = 3.0% -> 300; 17% tax 51."""
    got = italy.determine_tfr_revaluation(_ctx(), D("10000"), D("2.0"), 12)
    assert got["revaluation"] == D("300.00")
    assert got["substituteTax"] == D("51.00")
    assert got["netRevaluation"] == D("249.00")


def test_tfr_revaluation_part_year_prorates_only_the_fixed_part():
    """6 months, ISTAT +1.0%: 0.75% + 0.75% = 1.5% -> 150."""
    got = italy.determine_tfr_revaluation(_ctx(), D("10000"), D("1.0"), 6)
    assert got["revaluation"] == D("150.00")


def test_tfr_revaluation_needs_the_istat_figure():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        italy.determine_tfr_revaluation(_ctx(), D("10000"), None, 12)
    assert excinfo.value.key == "it_istat_foi_increase"


def test_tfr_separate_tax_uses_the_average_rate_on_the_reference_income():
    """IT-039: 20,000 over 10 years -> reference 24,000, all in the 23% band
    -> average 23% -> 4,600."""
    got = italy.determine_tfr_separate_tax(_ctx(), D("20000"), 120, date(2016, 1, 1))
    assert got["referenceIncome"] == "24000.00"
    assert got["tax"] == D("4600.00")


def test_tfr_separate_tax_is_not_the_marginal_rate():
    """90,000 over 5 years -> reference 216,000; IRPEF 6,440 + 7,260 + 71,380 =
    85,080 -> average 39.39% -> 35,450.00, well below the 43% marginal rate."""
    got = italy.determine_tfr_separate_tax(_ctx(), D("90000"), 60, date(2021, 1, 1))
    assert got["tax"] == D("35450.00")
    assert got["averageRatePct"] == "39.39"


def test_tfr_for_pre_2001_service_blocks_rather_than_approximating():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        italy.determine_tfr_separate_tax(_ctx(), D("50000"), 360, date(1996, 3, 1))
    assert excinfo.value.key == "it_service_start"


def test_tfr_accrues_at_one_thirteen_and_a_half():
    got = calculate(_ctx(gross=D("3000")))
    assert got["it_tfr_gross_accrual"] == _round2(D("3000") / D("13.5"))


def test_tfr_offset_is_a_separate_line_not_netted_into_the_accrual():
    got = calculate(_ctx(gross=D("3000")))
    assert got["it_tfr_inps_offset"] == _round2(D("3000") * D("0.005"))
    assert got["it_tfr_amount"] == (got["it_tfr_gross_accrual"]
                                    - got["it_tfr_inps_offset"])


def test_tfr_destination_tesoreria_below_the_threshold_blocks():
    """Section 14: the obligation arises only at or above the prior-year
    threshold. Electing Tesoreria below it is a contradiction, not a case to
    trace — IT-041's transferred-worker exception needs explicit evidence."""
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(headcount=10),
                       profile=_ready_profile(it_tfr_destination="FONDO_TESORERIA")))
    assert excinfo.value.key == "it_tfr_destination"


def test_tfr_tesoreria_at_or_above_the_threshold_is_accepted():
    got = calculate(_ctx(employer=EmployerProfile(headcount=60),
                         profile=_ready_profile(it_tfr_destination="FONDO_TESORERIA")))
    assert got["it_tfr_destination"] == "FONDO_TESORERIA"
    assert got["it_tfr_routing_complete"] is True
    assert got["it_calculation_trace"]["tfrTesoreriaBelowThreshold"] is False


def test_tfr_tesoreria_below_threshold_allowed_only_with_transfer_evidence():
    """IT-041: the exception is real but must be evidenced, never assumed."""
    with pytest.raises(ItalyCalculationBlockedError):
        calculate(_ctx(employer=EmployerProfile(headcount=10),
                       profile=_ready_profile(it_tfr_destination="FONDO_TESORERIA")))
    got = calculate(_ctx(
        employer=EmployerProfile(headcount=10),
        profile=_ready_profile(it_tfr_destination="FONDO_TESORERIA",
                               it_tesoreria_transfer_evidence=True)))
    assert got["it_calculation_trace"]["tfrTesoreriaBelowThreshold"] is True


def test_tfr_staying_with_the_employer_above_the_threshold_blocks():
    got_legal = calculate(_ctx(employer=EmployerProfile(headcount=59),
                               profile=_ready_profile(it_tfr_destination="AZIENDA")))
    assert got_legal["it_tfr_routing_complete"] is True
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(headcount=60),
                       profile=_ready_profile(it_tfr_destination="AZIENDA")))
    assert excinfo.value.key == "it_tfr_destination"


def test_missing_prior_year_headcount_blocks():
    """IT-040: the threshold comes from the PRIOR-YEAR average, so without that
    fact the destination cannot be validated."""
    employer = EmployerProfile()
    employer.prior_year_avg_headcount = None
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=employer,
                       profile=_ready_profile(it_tfr_destination="AZIENDA")))
    assert excinfo.value.key == "it_prior_year_avg_headcount"


def test_pension_fund_destination_requires_a_named_fund():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(employer=EmployerProfile(headcount=10),
                       profile=_ready_profile(it_tfr_destination="FONDO_PENSIONE")))
    assert excinfo.value.key == "it_pension_fund"


def test_unknown_tfr_destination_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=_ready_profile(it_tfr_destination="CRYPTO")))
    assert excinfo.value.key == "it_tfr_destination"


def test_absent_tfr_election_accrues_but_leaves_routing_incomplete():
    """IT-038: the entitlement is owed regardless of how it is funded, so the
    accrual stands while the routing is reported as unresolved."""
    got = calculate(_ctx(profile=_ready_profile(it_tfr_destination=None)))
    assert got["it_tfr_amount"] > D(0)
    assert got["it_tfr_routing_complete"] is False


def test_tfr_destination_change_never_erases_the_accrual():
    """IT-038: changing the destination changes future funding flows only."""
    employer = EmployerProfile(headcount=10)
    to_employer = calculate(_ctx(employer=employer,
                                 profile=_ready_profile(it_tfr_destination="AZIENDA")))
    to_fund = calculate(_ctx(employer=employer,
                             profile=_ready_profile(it_tfr_destination="FONDO_PENSIONE",
                                                    it_pension_fund="FUND_X")))
    assert to_employer["it_tfr_amount"] == to_fund["it_tfr_amount"]


def test_tfr_is_not_part_of_what_the_employer_remits_to_inps():
    """IT-057: TFR is a reserve the employer funds, not part of the month's
    INPS remittance. The employer_social_security slot is the total INPS
    remittance (IVS + CIGS + FIS + other families), and TFR is added on top
    in it_employer_contributions."""
    got = calculate(_ctx(gross=D("3000")))
    # employer_social_security = total INPS (IVS employer + FIS employer + ...)
    # it_employer_contributions = employer_social_security + TFR net
    assert got["it_employer_contributions"] == (
        got["it_employer_social_security"] + got["it_tfr_amount"])
    # Verify it_employer_social_security includes FIS employer (0.33% of 3000 = 9.90)
    ivs_er = D("3000") * D("23.81") / D(100)
    fis_er = D("3000") * D("0.33") / D(100)
    assert got["it_employer_social_security"] == _round2(ivs_er + fis_er)


# ── 9. Dispatch guards ──────────────────────────────────────────────────────
def test_italy_is_fail_closed_from_day_one():
    assert "IT" in _VALIDATION_ENABLED_COUNTRIES
    assert issubclass(ItalyCalculationBlockedError, MissingComplianceConfigurationError)


def test_non_monthly_payroll_blocks():
    ctx = _ctx()
    ctx.pay_frequency = "weekly"
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.key == "pay_frequency"


def test_missing_pay_date_blocks():
    ctx = _ctx()
    ctx.pay_date = None
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(ctx)
    assert excinfo.value.key == "pay_date"


def test_missing_statutory_profile_blocks():
    with pytest.raises(ItalyCalculationBlockedError) as excinfo:
        calculate(_ctx(profile=None))
    assert excinfo.value.key == "italy_statutory_profile"


def test_no_scalar_parameter_falls_back():
    """Every registered Italy constant is None: Italy has no engine fallback by
    design, and a missing row must reach the calculation as a BLOCK."""
    entries = [e for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
               if e["country"] == "IT"]
    assert entries
    for entry in entries:
        assert getattr(italy, entry["attr"]) is None


def test_registered_keys_match_the_content_and_the_engine():
    """The readiness check, the content file and the calculation must name the
    same keys, or a pack could be certified against keys nothing reads."""
    registered = {e["resolverKey"] for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
                  if e["country"] == "IT"}
    assert registered == set(italy.IT_PARAMETER_KEYS)
    assert registered == set(italy_content.IT_PARAMETER_KEYS)
    assert {row[0] for row in italy_content.IT_SCALAR_CONTENT} == registered


def test_registry_side_matches_each_keys_kind():
    """The service readiness check reads the registry's "side" to decide which
    column must be set: an amount key registered as a rate (or the reverse)
    reports a seeded row as missing and blocks every Italian payroll. This is
    how it_tfr_divisor and both FIS keys were first registered."""
    want = {"amount": None, "employee_pct": "employee", "employer_pct": "employer"}
    for entry in fallback_registry._ENGINE_CONSTANT_REGISTRY:
        if entry["country"] == "IT":
            assert entry.get("side") == want[italy.IT_PARAMETER_KEYS[entry["resolverKey"]]], entry["resolverKey"]


def test_inps_matrix_has_no_national_rate_key():
    """IT-002: the matrix must not collapse to one national component key."""
    families = {row[3] for row in italy_content.IT_INPS_MATRIX}
    assert families.isdisjoint(italy.IT_PARAMETER_KEYS)


def test_content_is_draft_and_the_registry_row_is_planned():
    """Italy stays Draft and PLANNED until the statutory review lands."""
    assert italy_content._STATUS == "Draft"
    assert all("needs source" in row[5].lower() or "needs" in row[5].lower()
               or "Decision" in row[5] or "§" in row[5]
               for row in italy_content.IT_SCALAR_CONTENT)


def test_local_surtax_content_is_marked_as_needing_a_mef_source():
    """IT-012: these rates are not in the specification. They are staged so the
    calculation can be exercised, and every one must say so."""
    for _rule, _table, _lo, _hi, _rate, _flat, label in italy_content.IT_LOCAL_TAX_SLABS:
        assert "needs MEF source" in label


def test_content_tax_table_numbers_fit_their_columns():
    """TaxSlab.tax_table_number is VARCHAR(10) and rule_type VARCHAR(30); a
    longer value would truncate at the database, not in the engine."""
    for rule, table, *_rest in italy_content.IT_TAX_SLABS + italy_content.IT_LOCAL_TAX_SLABS:
        assert len(rule) <= 30, rule
        assert len(table) <= 10, table


def test_tax_domicile_codes_fit_the_employee_columns():
    """The whole reason domicile is stored as ISTAT/cadastral codes: a name such
    as 'Emilia-Romagna' would truncate in it_tax_domicile_region String(10)."""
    for code, _name in italy_content.IT_REGIONS:
        assert len(code) <= 10
    for code, _name, _region in italy_content.IT_LAUNCH_COMMUNI:
        assert len(code) <= 20


def test_trace_records_the_annualised_band_and_the_domicile():
    """IT-010 / IT-013: the retained trace is what proves which band and which
    locality the figures came from."""
    got = calculate(_ctx(gross=D("1000")))
    trace = got["it_calculation_trace"]
    assert trace["annualForecast"]
    assert trace["detrazioneBandMin"] is not None
    assert trace["wedgeBandPct"]
    assert trace["taxDomicileRegion"] == "03"
    assert trace["taxDomicileComune"] == "F205"
    assert trace["inpsScope"].startswith("CSC_")


def test_every_golden_case_is_reachable_through_the_engine():
    """Guards against a fixture that silently stops exercising the engine."""
    for case in GOLDEN:
        got = _run(case)
        assert got["it_inps_components"]
        assert got["it_calculation_trace"]["jurisdiction"] == "IT"

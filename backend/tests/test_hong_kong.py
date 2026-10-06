"""
tests/test_hong_kong.py
-----------------------
Hong Kong (ZP-HK-ENG-001 v1.0) — the pure statutory layer, against the
official IRD / MPFA / Labour Department sources recorded by
scripts/seed_hong_kong_canonical_pack.py. Every statutory value used here is
read from the SEEDED PACK ROWS (never restated as a literal rate), so a test
proves the pack as well as the engine.

Covers: country registration, the no-PAYE architecture lock, MPF coverage /
exemptions / 60-day rule / contribution holiday / thresholds / non-monthly,
SMW incl. the 1 May 2026 crossover and the hours-record trigger, the
continuous-contract 4-18 → 468 rule, the 12-month average wage with excluded
periods, holiday / annual leave / sickness / maternity / paternity pay, SP/LSP
with the 1 May 2025 transition, the informational Salaries Tax (IRD worked
examples), IRD deadlines + IR56B duplicate suppression, the IR56G state
machine, golden vectors A–L.

All identifiers are synthetic. app.* is imported lazily (collection-order
DB-binding hazard, see conftest.py).
"""

import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "hk_golden"


@pytest.fixture()
def packs(db):
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    p25, p26 = seed_hong_kong_all(db)
    for p in (p25, p26):
        p.status = "Active"
    db.commit()
    return p25, p26


def _inputs(db, on):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    rates, slabs, pack = resolve_tax_configuration(db, "HK", payroll_date=on)
    return {r.component_key: r for r in rates}, slabs, pack


def _calc(db, gross="20000", pay=date(2026, 6, 30), ps=None, pe=None, freq="Monthly", facts=None, hours=None,
          dob=date(1990, 1, 1), **kw):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import rule_segments
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import ContributionRate

    ps = ps or pay.replace(day=1)
    pe = pe or pay
    rate_map, slabs, pack = _inputs(db, pay)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    f = {"profileId": 1, "dateOfJoining": "2024-01-01", **(facts or {})}
    ctx = PayrollContext(gross=D(gross), basic=kw.pop("basic", D(gross)), country="HK", rate_map=rate_map, slabs=slabs,
                         pay_date=pay, period_start=ps, period_end=pe, pay_frequency=freq, date_of_birth=dob,
                         hk_worker_facts=f, hk_hours=hours or {}, hk_rule_segments=rule_segments(rows, ps, pe), **kw)
    return calculate_payroll(ctx, "standard")


# ── 1. Country registration / architecture lock ─────────────────────────

def test_hk_registered_in_the_shared_strategy_and_every_country_registry():
    from app.core.jurisdiction import (CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES,
                                       get_jurisdiction_code)
    from app.modules.payroll.employee_validation import _STRATEGIES
    from app.modules.payroll.engine.countries import hong_kong
    from app.modules.payroll.engine.countries.shared import _VALIDATION_ENABLED_COUNTRIES
    from app.modules.payroll.engine.standard import _COUNTRY_CALC
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES
    from app.modules.payroll.service import _CANONICAL_PACK_ONLY_COUNTRIES, _normalize_country

    assert _COUNTRY_CALC["HK"] is hong_kong.calculate
    assert JURISDICTION_TAX_SCHEMAS["HK"]["currency"] == "HKD" and CODE_TO_COUNTRY_NAME["HK"] == "Hong Kong"
    assert get_jurisdiction_code("Hong Kong") == get_jurisdiction_code("hong kong sar") == "HK"
    assert _normalize_country("Hong Kong") == "HK"          # previously truncated to "HO"
    assert "Hong Kong" not in REGISTRATION_COUNTRIES          # live payroll gated (§16)
    assert "HK" in _VALIDATION_ENABLED_COUNTRIES and "HK" in _CANONICAL_PACK_ONLY_COUNTRIES
    assert "HK" in _REGISTRY_ROW_REQUIRED_COUNTRIES and "HK" in _STRATEGIES


def test_no_separate_hk_runtime_the_calculator_is_one_module_in_the_shared_dispatch():
    from app.modules.payroll.engine import enterprise, standard

    assert enterprise.EnterpriseStrategy.__mro__[1] is standard.StandardStrategy
    src = (Path(__file__).parents[1] / "app/modules/payroll/engine/countries/hong_kong.py").read_text(encoding="utf8")
    assert "tds=" not in src and "\"tds\"" not in src          # never a withholding slot
    for forbidden in ("Session", "db.query", "date.today", "datetime.now"):
        assert forbidden not in src                           # HK-020: pure calculator


@pytest.mark.parametrize("gross", ["6500", "20000", "45000", "250000"])
def test_architecture_lock_normal_payroll_never_withholds_salaries_tax(db, packs, gross):
    r = _calc(db, gross)
    assert r.tds == 0 and r.federal_income_tax == 0 and r.state_income_tax == 0
    assert r.hk_calculation_trace["salariesTax"]["withholding"] == "NONE"
    assert r.net_pay == D(gross) - r.employee_pension


def test_hk_blocks_without_a_statutory_profile_version(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match="statutory profile"):
        _calc(db, facts={"profileId": None})


# ── MPF (golden cases A–F + coverage) ──────────────────────────────────

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.stem)
def test_golden_vectors_embedded_rows(path):
    from app.modules.payroll.hmrc_golden_harness import run_golden_case

    run_golden_case(json.loads(path.read_text(encoding="utf8")))


def test_golden_vectors_reproduce_from_each_packs_own_rows(db, packs):
    from app.modules.payroll import hong_kong_service

    total = 0
    for pack in packs:
        check = hong_kong_service.pack_golden_check(db, pack)
        assert check["failures"] == [], check
        total += check["casesInWindow"]
    assert total == len(list(GOLDEN.glob("*.json"))) >= 11


def test_case_a_b_c_threshold_branches_from_pack_rows(db, packs):
    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    lo, hi = rate_map["mpf_min_relevant_income_monthly"].flat_amount, rate_map["mpf_max_relevant_income_monthly"].flat_amount
    assert (lo, hi) == (D("7100"), D("30000"))
    for gross, branch, ee, er in (("6500", "BELOW_MINIMUM", "0", "325"), ("7100", "WITHIN_LEVELS", "355", "355"),
                                  ("30000", "WITHIN_LEVELS", "1500", "1500"), ("30000.01", "ABOVE_MAXIMUM", "1500", "1500"),
                                  ("45000", "ABOVE_MAXIMUM", "1500", "1500")):
        r = _calc(db, gross)
        assert r.hk_calculation_trace["mpf"]["currentPeriod"]["branch"] == branch
        assert (r.employee_pension, r.employer_pension) == (D(ee), D(er)), gross


def test_mpf_employer_still_pays_5_percent_below_minimum_and_employee_nil(db, packs):
    r = _calc(db, "7099.99")
    assert (r.employee_pension, r.employer_pension) == (D("0"), D("355.00"))


def test_non_monthly_daily_levels_times_days(db, packs):
    r = _calc(db, "1500", pay=date(2026, 6, 14), ps=date(2026, 6, 1), pe=date(2026, 6, 14), freq="Fortnightly")
    cp = r.hk_calculation_trace["mpf"]["currentPeriod"]
    assert (D(cp["minLevel"]), D(cp["maxLevel"])) == (D("3920"), D("14000"))       # 280×14, 1,000×14
    assert cp["branch"] == "BELOW_MINIMUM" and r.employee_pension == 0 and r.employer_pension == D("75.00")


def test_60_day_rule_first_contribution_day_and_holiday_boundary(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import mpf

    start = date(2026, 1, 16)
    assert mpf.sixty_day_date(start, 60) == date(2026, 3, 16)
    assert mpf.holiday_end(start, 30) == date(2026, 2, 14)
    assert mpf.first_contribution_day(date(2026, 3, 16), 10) == date(2026, 4, 10)
    # A wage period beginning after day 30 contributes; one containing day 30 is holiday.
    assert mpf.employee_holiday_applies(date(2026, 2, 1), date(2026, 2, 28), start, 30) is True
    assert mpf.employee_holiday_applies(date(2026, 3, 1), date(2026, 3, 31), start, 30) is False
    # Joiner on the 1st: holiday = 1–30 Jan, so the whole of February contributes.
    assert mpf.employee_holiday_applies(date(2026, 2, 1), date(2026, 2, 28), date(2026, 1, 1), 30) is False


def test_case_e_catch_up_is_never_booked_twice(db, packs):
    facts = {"dateOfJoining": "2026-01-16", "priorPeriods": [
        {"payslipId": 1, "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "relevantIncome": "20000",
         "coverageStatus": "PENDING_60_DAY", "caughtUp": True},
        {"payslipId": 2, "periodStart": "2026-02-01", "periodEnd": "2026-02-28", "relevantIncome": "20000",
         "coverageStatus": "PENDING_60_DAY", "caughtUp": True}]}
    r = _calc(db, pay=date(2026, 4, 30), facts=facts)
    assert r.hk_calculation_trace["mpf"]["catchUp"] == [] and r.employer_pension == D("1000.00")


def test_case_f_leaver_before_60_days_records_employment_duration_evidence(db, packs):
    r = _calc(db, pay=date(2026, 2, 28), facts={"dateOfJoining": "2026-01-16", "terminationDate": "2026-02-28"})
    cov = r.hk_calculation_trace["mpf"]["coverage"]
    assert cov["status"] == "NOT_COVERED_LEFT_BEFORE_60_DAYS" and cov["employmentDays"] == 44


@pytest.mark.parametrize("facts,match", [
    ({"employmentRelationship": "DOMESTIC"}, "domestic"),
    ({"employmentRelationship": "CASUAL_INDUSTRY"}, "Industry Scheme"),
    ({"employmentRelationship": "CONTRACTOR_REVIEW"}, "contractor"),
    ({"mpfExemptionCode": "INDUSTRY_SCHEME_SPECIAL"}, "Industry Scheme"),
    ({"mpfExemptionCode": "EXEMPT_ORSO"}, "evidence"),
    ({"mpfExemptionCode": "EXEMPT_STATUTORY_SCHEME"}, "evidence"),
    ({"mpfExemptionCode": "EXEMPT_AGE"}, "EXEMPT_AGE is recorded"),
])
def test_mpf_exemptions_fail_closed_without_facts_or_out_of_scope(db, packs, facts, match):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match=match):
        _calc(db, facts=facts)


def test_mpf_inbound_13_month_rule(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    base = {"mpfExemptionCode": "EXEMPT_INBOUND", "mpfExemptionEvidenceRef": "VISA-1", "enteredForEmployment": True,
            "arrivalDate": "2026-01-10"}
    ok = _calc(db, facts={**base, "permissionToStayUntil": "2027-01-31"})
    assert ok.hk_calculation_trace["mpf"]["coverage"]["status"] == "EXEMPT" and ok.employer_pension == 0
    with pytest.raises(HongKongCalculationBlockedError, match="13 months"):
        _calc(db, facts={**base, "permissionToStayUntil": "2027-06-30"})
    overseas = _calc(db, facts={"mpfExemptionCode": "EXEMPT_INBOUND", "mpfExemptionEvidenceRef": "SCHEME-1",
                                "overseasSchemeMember": True})
    assert overseas.employer_pension == 0


def test_mpf_coverage_never_inferred_from_part_time_status(db, packs):
    r = _calc(db, "8000", employment_type="Part-time")
    assert r.hk_calculation_trace["mpf"]["coverage"]["status"] == "COVERED" and r.employee_pension == D("400.00")


def test_age_boundary_inside_period_blocks(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match="turns 65"):
        _calc(db, dob=date(1961, 6, 15))
    with pytest.raises(HongKongCalculationBlockedError, match="turns 18"):
        _calc(db, dob=date(2008, 6, 15))


def test_missing_date_of_birth_blocks(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match="date of birth"):
        _calc(db, dob=None)


def test_missing_statutory_row_blocks_never_defaults(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError
    from app.modules.payroll.models import ContributionRate

    db.query(ContributionRate).filter(ContributionRate.component_key == "mpf_max_relevant_income_monthly").delete()
    db.commit()
    with pytest.raises(HongKongCalculationBlockedError, match="mpf_max_relevant_income_monthly"):
        _calc(db)


def test_unclassified_earning_component_blocks_mpf(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError
    from app.modules.payroll.models import TaxSlab

    db.query(TaxSlab).filter(TaxSlab.rule_type == "HK_EARNING_CLASS", TaxSlab.filing_status == "overtime",
                             TaxSlab.tax_regime == "MPF_RI").delete()
    db.commit()
    with pytest.raises(HongKongCalculationBlockedError, match="overtime"):
        _calc(db, "20000", basic=D("18000"), overtime=D("2000"))


def test_one_earning_classified_per_obligation(db, packs):
    """HK-006: additional compensation counts for MPF, is REVIEW for EO wages / SMW, and is reported to the IRD."""
    r = _calc(db, "25000", basic=D("20000"), additional_compensation=D("5000"))
    cls = r.hk_calculation_trace["classification"]
    assert D(cls["MPF_RI"]["included"]) == D("25000") and D(cls["EO_WAGES"]["review"]) == D("5000")
    assert D(cls["SMW_WAGES"]["review"]) == D("5000")
    assert r.hk_calculation_trace["ird"]["reportable"]["UNMAPPED_REQUIRES_CLASSIFICATION"] == "5000.00"


# ── Minimum wage (golden case G) ────────────────────────────────────────

def test_case_g_wage_period_crossing_1_may_2026_splits_rates(db, packs):
    days = {(date(2026, 4, 16) + timedelta(days=i)).isoformat(): "8" for i in range(30)}
    r = _calc(db, "10000", pay=date(2026, 5, 15), ps=date(2026, 4, 16), pe=date(2026, 5, 15),
              hours={"days": days, "complete": True})
    smw = r.hk_calculation_trace["minimumWage"]
    rates = {s["rate"]: D(s["hours"]) for s in smw["segments"]}
    assert rates == {"42.10": D("120"), "43.10": D("120")}
    assert D(smw["minimumDue"]) == D("120") * D("42.10") + D("120") * D("43.10") == D("10224.00")
    assert smw["status"] == "BREACH" and D(smw["topUpRequired"]) == D("224.00")
    assert r.net_pay == D("10000") - r.employee_pension          # never silently topped up


def test_smw_historical_rate_resolves_from_the_2025_pack(db, packs):
    days = {(date(2025, 4, 1) + timedelta(days=i)).isoformat(): "8" for i in range(30)}
    r = _calc(db, "12000", pay=date(2025, 4, 30), ps=date(2025, 4, 1), pe=date(2025, 4, 30),
              hours={"days": days, "complete": True})
    smw = r.hk_calculation_trace["minimumWage"]
    assert [s["rate"] for s in smw["segments"]] == ["40.00"] and D(smw["minimumDue"]) == D("9600.00")


def test_17600_is_a_record_keeping_trigger_not_a_monthly_minimum_wage(db, packs):
    r = _calc(db, "15000")
    smw = r.hk_calculation_trace["minimumWage"]
    assert smw["hoursRecord"]["required"] is True and D(smw["hoursRecord"]["monthlyCap"]) == D("17600")
    assert smw["status"] == "HOURS_NOT_RECORDED"                   # never a "BREACH" for being under 17,600
    assert _calc(db, "18000").hk_calculation_trace["minimumWage"]["hoursRecord"]["required"] is False
    april = _calc(db, "17300", pay=date(2025, 6, 30))
    assert D(april.hk_calculation_trace["minimumWage"]["hoursRecord"]["monthlyCap"]) == D("17200")


def test_smw_compliant_with_countable_wages(db, packs):
    days = {(date(2026, 6, 1) + timedelta(days=i)).isoformat(): "8" for i in range(30)}
    r = _calc(db, "15000", hours={"days": days, "complete": True})
    assert r.hk_calculation_trace["minimumWage"]["status"] == "COMPLIANT"


# ── Continuous contract (golden case H) ─────────────────────────────────

def _cc(db, start, as_of, weekly_hours, contractual=None):
    from app.modules.payroll.engine.jurisdictions.hong_kong import continuous_contract as cc

    rate_map, _s, _p = _inputs(db, as_of)
    params = cc.parameters(rate_map)
    days = {}
    for ws, hours in weekly_hours:
        days[ws.isoformat()] = str(hours)           # all of a week's hours on its first day
    return cc.resolve(start, as_of, days, params, contractual)


def test_case_h_468_rule_one_week_below_17_but_4_weeks_total_70(db, packs):
    weeks = [(date(2026, 2, 1), 18), (date(2026, 2, 8), 18), (date(2026, 2, 15), 18), (date(2026, 2, 22), 16)]
    out = _cc(db, date(2026, 2, 1), date(2026, 2, 28), weeks)
    assert out["status"] == "CONTINUOUS"
    last = out["weeks"][-1]
    assert (last["rule"], last["result"], last["fourWeekHours"]) == ("4_WEEK_17_68", "MET", "70")


def test_468_rule_is_unavailable_in_the_first_weeks_of_a_new_employment(db, packs):
    """LD Education Tool Note 1: the employee must have been employed by the
    employer throughout the four-week period, so a short week inside the first
    three weeks of a NEW employment cannot be rescued by a 68-hour total — and
    the trace must say that, not blame an incomplete window."""
    weeks = [(date(2026, 2, 1), 30), (date(2026, 2, 8), 30), (date(2026, 2, 15), 16), (date(2026, 2, 22), 16)]
    out = _cc(db, date(2026, 2, 1), date(2026, 2, 28), weeks)
    third = out["weeks"][2]
    assert out["rules"]["newEmploymentWeeksWithout468Rule"] == 3
    assert third["result"] == "NOT_MET"
    assert third["fourWeekHours"] == "468 rule unavailable — week 3 of the new employment"
    # The very next week has a full four-week period, so the alternative applies
    # and the same 16 hours are rescued by the 92-hour total.
    fourth = out["weeks"][3]
    assert (fourth["result"], fourth["fourWeekHours"]) == ("MET", "92")


def test_468_fails_when_4_week_total_below_68(db, packs):
    weeks = [(date(2026, 2, 1), 17), (date(2026, 2, 8), 17), (date(2026, 2, 15), 17), (date(2026, 2, 22), 16)]
    out = _cc(db, date(2026, 2, 1), date(2026, 2, 28), weeks)
    assert out["weeks"][-1]["result"] == "NOT_MET" and out["status"] == "NOT_CONTINUOUS"


def test_pre_18_january_2026_weeks_use_the_legacy_418_rule(db, packs):
    weeks = [(date(2025, 11, 2), 17), (date(2025, 11, 9), 17), (date(2025, 11, 16), 17), (date(2025, 11, 23), 17)]
    out = _cc(db, date(2025, 11, 2), date(2025, 11, 29), weeks)
    assert all(w["rule"] == "4_18" for w in out["weeks"]) and out["status"] == "NOT_CONTINUOUS"
    after = [(date(2026, 1, 18), 17), (date(2026, 1, 25), 17), (date(2026, 2, 1), 17), (date(2026, 2, 8), 17)]
    out = _cc(db, date(2026, 1, 18), date(2026, 2, 14), after)
    assert all(w["rule"] == "4_WEEK_17_68" for w in out["weeks"]) and out["status"] == "CONTINUOUS"


def test_continuity_replay_with_missing_hours_is_undetermined_never_assumed(db, packs):
    out = _cc(db, date(2026, 2, 1), date(2026, 2, 28), [(date(2026, 2, 1), 20)])
    assert out["status"] == "UNDETERMINED"


def test_contractual_hours_evidence_is_flagged(db, packs):
    out = _cc(db, date(2026, 2, 1), date(2026, 2, 28), [], contractual=D("40"))
    assert out["status"] == "CONTINUOUS" and {w["evidence"] for w in out["weeks"]} == {"CONTRACTUAL"}


# ── Average wage (golden case L) + entitlements ─────────────────────────

def _slip(pid, y, m, wages, ot="0"):
    import calendar

    return {"payslipId": pid, "periodStart": date(y, m, 1).isoformat(),
            "periodEnd": date(y, m, calendar.monthrange(y, m)[1]).isoformat(), "eoWages": wages, "overtime": ot,
            "revision": f"r{pid}"}


def test_average_wage_lookback_is_the_12_calendar_months_before_the_reference_month(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import average_wage

    months = int(_inputs(db, date(2026, 4, 1))[0]["eo_average_wage_months"].flat_amount)
    # LD Appendix 1 Example 1: Tuen Ng 22 Jun 2023 → 1 Jun 2022 – 31 May 2023.
    assert average_wage.lookback_window(date(2023, 6, 22), date(2020, 1, 1), months) == (date(2022, 6, 1), date(2023, 5, 31), False)
    assert average_wage.lookback_window(date(2008, 4, 4), date(2007, 7, 5), months) == (date(2007, 7, 5), date(2008, 3, 31), True)


def test_ld_appendix1_example3_annual_leave_pay(db, packs):
    """LD Appendix 1 Example 3: monthly-rated HK$15,000, no disregarded periods → ADW 180,000/365 = 493.15; 7 days."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import average_wage, entitlements

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    slips = [_slip(i, 2022 + (7 + i) // 12, (7 + i) % 12 + 1, "15000") for i in range(12)]
    out = average_wage.calculate(date(2023, 8, 10), date(2020, 1, 1), slips, [], "ANNUAL_LEAVE", rate_map=rm)
    assert (out["lookbackStart"], out["lookbackEnd"], out["includedDays"]) == ("2022-08-01", "2023-07-31", 365)
    assert D(out["averageDailyWage"]).quantize(D("0.01")) == D("493.15")
    assert round(D(entitlements.annual_leave_pay(out, D(7))["amount"])) == 3452   # LD rounds ADW to 493 → 3,451
    assert out["statutoryFactors"]["daysPerYear"] == "365.00"
    assert out["statutoryFactors"]["refs"]["eo_average_wage_days_per_year"]["sourceDocumentId"]


def test_case_l_average_wage_excludes_maternity_period_and_pay(db, packs):
    """Case L — LD Appendix 1 Example 3 formula: (total − 14-week maternity pay) ÷ (365 − 98)."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import average_wage

    rm, _sl, _p = _inputs(db, date(2026, 4, 1))
    slips = [_slip(i, 2022 + (11 + i) // 12, (11 + i) % 12 + 1, "15000") for i in range(12)]
    maternity = [{"from": "2023-08-09", "to": "2023-11-14", "reason": "MATERNITY_LEAVE_FOUR_FIFTHS_PAY",
                  "amountPaid": "38465.75"}]
    out = average_wage.calculate(date(2023, 12, 6), date(2020, 1, 1), slips, maternity, "ANNUAL_LEAVE", rate_map=rm)
    assert out["excludedDays"] == 98 and out["includedDays"] == 365 - 98
    expected = (D("180000") - D("38465.75")) / D(267)
    assert D(out["averageDailyWage"]) == expected.quantize(D("0.0001"))
    assert out["excludedPeriods"][0]["reason"] == "MATERNITY_LEAVE_FOUR_FIFTHS_PAY"


def test_average_wage_blocks_on_missing_history_and_unreasoned_exclusions(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import average_wage
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    rm, _sl, _p = _inputs(db, date(2026, 4, 1))
    slips = [_slip(i, 2025, i + 1, "15000") for i in range(11)]            # December missing
    with pytest.raises(HongKongCalculationBlockedError, match="does not cover"):
        average_wage.calculate(date(2026, 1, 10), date(2020, 1, 1), slips, [], "SICKNESS", rate_map=rm)
    slips.append(_slip(12, 2025, 12, "15000"))
    with pytest.raises(HongKongCalculationBlockedError, match="statutory reason"):
        average_wage.calculate(date(2026, 1, 10), date(2020, 1, 1), slips,
                               [{"from": "2025-03-01", "to": "2025-03-02"}], "SICKNESS", rate_map=rm)
    # Without the pack rows there is no average wage at all (fail closed).
    with pytest.raises(HongKongCalculationBlockedError, match="eo_average_wage_days_per_year"):
        average_wage.calculate(date(2026, 1, 10), date(2020, 1, 1), slips, [], "SICKNESS",
                               rate_map={k: v for k, v in rm.items() if k != "eo_average_wage_days_per_year"})


def test_average_wage_overtime_20_percent_rule(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import average_wage

    rm, _sl, _p = _inputs(db, date(2026, 4, 1))
    low = [_slip(i, 2025, i + 1, "15500", ot="500") for i in range(12)]     # OT 500 < 20% of 15,000
    out = average_wage.calculate(date(2026, 1, 10), date(2020, 1, 1), low, [], "SICKNESS", rate_map=rm)
    assert out["overtime"]["overtimeInclusionTestMet"] is False and D(out["wagesUsed"]) == D("180000")
    assert out["statutoryFactors"]["overtimeInclusionTestShare"] == "0.20"
    high = [_slip(i, 2025, i + 1, "18000", ot="3000") for i in range(12)]   # OT 3,000 ≥ 20% of 15,000
    out = average_wage.calculate(date(2026, 1, 10), date(2020, 1, 1), high, [], "SICKNESS", rate_map=rm)
    assert out["overtime"]["overtimeInclusionTestMet"] is True and D(out["wagesUsed"]) == D("216000")


def _cc_result(since):
    return {"status": "CONTINUOUS", "continuousSince": since}


def test_sickness_allowance_ld_example_2_and_conditions(db, packs):
    """LD Appendix 1 Example 2: ADW 493.15 × 4/5 × 4 days ≈ 1,578."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    avg = {"averageDailyWage": str(D("180000") / D("365"))}
    out = entitlements.sickness_allowance(rate_map, _cc_result("2024-01-01"), avg, 4, 4, True, D("20"))
    assert out["status"] == "ENTITLED" and round(D(out["amount"])) == 1578
    short = entitlements.sickness_allowance(rate_map, _cc_result("2024-01-01"), avg, 3, 3, True, D("20"))
    assert short["status"] == "NOT_ENTITLED" and "less than 4" in short["failedConditions"][0]
    preg = entitlements.sickness_allowance(rate_map, _cc_result("2024-01-01"), avg, 1, 1, True, D("20"), True)
    assert preg["status"] == "ENTITLED"


def test_paid_sickness_day_accrual_2_then_4_capped_at_120(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    assert entitlements.paid_sickness_days_accrued(rate_map, date(2026, 1, 1), date(2026, 7, 1))["accrued"] == "12"
    assert entitlements.paid_sickness_days_accrued(rate_map, date(2025, 1, 1), date(2026, 3, 1))["accrued"] == "32"
    assert entitlements.paid_sickness_days_accrued(rate_map, date(2020, 1, 1), date(2026, 6, 1))["accrued"] == "120"


def test_maternity_leave_pay_14_weeks_with_80000_cap_on_weeks_11_to_14(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    avg = {"averageDailyWage": "5000"}                              # 4/5 = 4,000/day
    out = entitlements.maternity_leave_pay(rate_map, _cc_result("2024-01-01"), avg, date(2026, 6, 1), True)
    assert D(out["weeks1to10"]) == D("280000.00") and D(out["weeks11to14Uncapped"]) == D("112000.00")
    assert D(out["weeks11to14"]) == D("80000") and D(out["amount"]) == D("360000.00")
    ineligible = entitlements.maternity_leave_pay(rate_map, _cc_result("2026-03-01"), avg, date(2026, 6, 1), True)
    assert ineligible["status"] == "NOT_ENTITLED"


def test_paternity_leave_pay_5_days_40_weeks(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    out = entitlements.paternity_leave_pay(rate_map, _cc_result("2025-01-01"), {"averageDailyWage": "500"},
                                           date(2026, 6, 1), 5, True)
    assert out["status"] == "ENTITLED" and D(out["amount"]) == D("2000.00")
    with pytest.raises(HongKongCalculationBlockedError):
        entitlements.paternity_leave_pay(rate_map, _cc_result("2025-01-01"), {"averageDailyWage": "500"},
                                         date(2026, 6, 1), 6, True)


def test_statutory_holidays_2026_are_15_with_easter_monday(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    _r, slabs, _p = _inputs(db, date(2026, 6, 30))
    days = entitlements.statutory_holidays(slabs, 2026)
    assert len(days) == 15 and (days[5]["date"], days[5]["name"]) == ("2026-04-06", "Easter Monday")
    _r, slabs25, _p = _inputs(db, date(2025, 6, 30))
    assert len(entitlements.statutory_holidays(slabs25, 2025)) == 14


def test_holiday_pay_needs_3_months_continuous_contract(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    rate_map, _s, _p = _inputs(db, date(2026, 6, 30))
    avg = {"averageDailyWage": "600"}
    assert entitlements.holiday_pay(rate_map, _cc_result("2026-05-01"), avg, date(2026, 6, 19))["status"] == "NOT_ENTITLED"
    assert entitlements.holiday_pay(rate_map, _cc_result("2026-03-19"), avg, date(2026, 6, 19))["amount"] == "600.00"


def test_annual_leave_scale_7_to_14_days(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import entitlements

    _r, slabs, _p = _inputs(db, date(2026, 6, 30))
    assert [entitlements.annual_leave_days(slabs, y)[0] for y in range(1, 12)] == [7, 7, 8, 9, 10, 11, 12, 13, 14, 14, 14]


# ── Termination (golden case K) ─────────────────────────────────────────

def _term(db, **kw):
    from app.modules.payroll.engine.jurisdictions.hong_kong import termination

    rate_map, _s, _p = _inputs(db, date(2027, 3, 31))    # params are the same in every seeded window
    base = dict(start=date(2015, 5, 1), termination=date(2027, 3, 31), reason="REDUNDANCY", pay_basis="MONTHLY",
                cc_status="CONTINUOUS", params=termination.parameters(rate_map), post_wage=D("30000"),
                pre_wage=D("24000"))
    base.update(kw)
    return termination.calculate(**base)


def test_case_k_pre_and_post_transition_split_and_mandatory_mpf_offset_only_hits_pre(db, packs):
    out = _term(db, offsets=[{"type": "EMPLOYER_MANDATORY_MPF", "amount": "999999"}])
    pre, post = out["portions"]["preTransition"], out["portions"]["postTransition"]
    assert D(pre["base"]) == D(post["base"]) == D("15000.00")          # 2/3 × wage capped at 2/3 × 22,500
    assert pre["frozen"] is True and pre["serviceDays"] == (date(2025, 5, 1) - date(2015, 5, 1)).days
    assert D(post["amount"]) == (D("15000") * D(post["serviceDays"]) / D(365)).quantize(D("0.01"))
    assert D(pre["amount"]) == (D("15000") * D(pre["serviceDays"]) / D(365)).quantize(D("0.01"))
    # Mandatory-MPF accrued benefits offset ONLY the pre-transition portion:
    assert D(out["offsets"][0]["applied"]) == D(pre["amount"])
    assert D(out["netStatutoryPayment"]) == D(post["amount"])


def test_390000_cap_excess_deducted_from_post_transition_portion(db, packs):
    out = _term(db, start=date(2000, 5, 1), termination=date(2027, 3, 31), post_wage=D("30000"), pre_wage=D("30000"))
    pre = (D("15000") * D((date(2025, 5, 1) - date(2000, 5, 1)).days) / D(365)).quantize(D("0.01"))
    assert D(out["portions"]["preTransition"]["amount"]) == pre            # pre portion untouched
    assert D(out["grossEntitlement"]) == D("390000")
    assert D(out["portions"]["postTransition"]["amountAfterCap"]) == D("390000") - pre   # excess came off post


def test_pre_transition_portion_alone_above_the_cap_is_capped(db, packs):
    out = _term(db, start=date(1990, 5, 1), termination=date(2027, 3, 31), pre_wage=D("30000"))
    assert D(out["grossEntitlement"]) == D("390000")
    assert D(out["portions"]["preTransition"]["amountAfterCap"]) == D("390000")
    assert D(out["portions"]["postTransition"]["amountAfterCap"]) == 0


def test_voluntary_mpf_and_gratuity_may_offset_post_transition(db, packs):
    out = _term(db, offsets=[{"type": "EMPLOYER_VOLUNTARY_MPF", "amount": "10000"}])
    assert D(out["offsets"][0]["appliedTo"]["postTransition"]) == D("10000.00")


def test_straddling_employment_requires_frozen_pre_transition_wage(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match="HK-017"):
        _term(db, pre_wage=None)


def test_post_transition_employee_has_single_portion_and_no_mandatory_offset(db, packs):
    out = _term(db, start=date(2025, 6, 1), termination=date(2027, 7, 31),
                offsets=[{"type": "EMPLOYER_MANDATORY_MPF", "amount": "50000"}], pre_wage=None)
    assert "preTransition" not in out["portions"] and D(out["totalOffsets"]) == 0


@pytest.mark.parametrize("reason,start,expected", [
    ("REDUNDANCY", date(2025, 6, 1), "NONE"),         # < 24 months
    ("REDUNDANCY", date(2024, 6, 1), "SP"),
    ("DISMISSAL", date(2023, 1, 1), "NONE"),          # < 5 years
    ("DISMISSAL", date(2020, 1, 1), "LSP"),
    ("SUMMARY_DISMISSAL", date(2010, 1, 1), "NONE"),
    ("RESIGNATION", date(2010, 1, 1), "NONE"),
])
def test_sp_lsp_eligibility(db, packs, reason, start, expected):
    out = _term(db, reason=reason, start=start, termination=date(2026, 12, 31))
    assert out["paymentType"] == expected


def test_termination_before_transition_is_out_of_scope(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    with pytest.raises(HongKongCalculationBlockedError, match="pre-abolition"):
        _term(db, termination=date(2025, 4, 30))


# ── Salaries Tax — informational only (IRD 2026-27 Budget examples) ─────

def test_salaries_tax_ird_example_1_2026_27_and_2025_26_with_reduction(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm26, sl26, _p = _inputs(db, date(2026, 4, 1))
    out = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm26, slabs=sl26, income=D("380000"),
                                allowances={"basic": 1})
    assert (D(out["netChargeableIncome"]), D(out["estimatedTax"])) == (D("235000"), D("21950"))
    assert out["label"] == "INFORMATIONAL_NOT_WITHHELD"
    rm25, sl25, _p = _inputs(db, date(2025, 4, 1))
    out = salaries_tax.estimate(year_of_assessment="2025/26", rate_map=rm25, slabs=sl25, income=D("380000"),
                                allowances={"basic": 1})
    assert (D(out["taxBeforeReduction"]), D(out["taxReduction"]), D(out["estimatedTax"])) == (D("24160"), D("3000"), D("21160"))


def test_salaries_tax_ird_example_2_single_parent_2026_27(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    out = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("500000"),
                                deductions=D("60000"), allowances={"basic": 1, "single_parent": 1, "child": 1})
    assert (D(out["netChargeableIncome"]), D(out["estimatedTax"])) == (D("10000"), D("200"))


def test_salaries_tax_standard_rate_two_tier_applies_when_lower(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    out = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("6000000"),
                                allowances={"basic": 1})
    assert out["basisApplied"] == "STANDARD_RATE"
    assert D(out["estimatedTax"]) == D("5000000") * D("0.15") + D("1000000") * D("0.16")


def test_2026_27_allowances_are_the_ird_pam61e_values(db, packs):
    rm, _sl, _p = _inputs(db, date(2026, 4, 1))
    expected = {"basic": "145000", "married": "290000", "single_parent": "145000", "child": "140000",
                "child_additional": "140000", "dependent_parent_60": "55000", "dependent_parent_55": "27500",
                "dependent_parent_60_additional": "55000", "dependent_parent_55_additional": "27500",
                "personal_disability": "75000", "disabled_dependant": "75000", "dependent_sibling": "37500"}
    assert {k: rm[f"hk_allowance_{k}"].flat_amount for k in expected} == {k: D(v) for k, v in expected.items()}


def test_deduction_ceilings_are_the_ird_pam61e_values_per_year(db, packs):
    """PAM 61(e) §3. Elderly residential care is the only ceiling that moved
    for 2026/27 (Allowance (Amendment) Bill 2026, HK$100,000 → HK$110,000)."""
    rm25, _sl, _p = _inputs(db, date(2025, 4, 1))
    rm26, _sl, _p = _inputs(db, date(2026, 4, 1))
    flat = {"hk_deduction_mandatory_contributions": "18000", "hk_deduction_self_education": "100000",
            "hk_deduction_home_loan_interest": "100000", "hk_deduction_elderly_residential_care": "100000",
            "hk_deduction_domestic_rents": "100000", "hk_deduction_mpf_voluntary": "60000",
            "hk_deduction_assisted_reproductive": "100000", "hk_deduction_qvhi_premium": "8000"}
    for key, value in flat.items():
        assert rm25[key].flat_amount == D(value), key
    for key, value in flat.items():
        expected = "110000" if key == "hk_deduction_elderly_residential_care" else value
        assert rm26[key].flat_amount == D(expected), key
    # Fractions, the ContributionRate convention (0.35 = 35%).
    assert rm25["hk_deduction_approved_donation_pct"].employee_rate_pct == D("0.35")
    assert rm26["hk_deduction_approved_donation_pct"].employee_rate_pct == D("0.35")


def test_deduction_claims_are_capped_to_the_statutory_ceiling_and_disclosed(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    # A claim above the HK$18,000 MPF mandatory-contribution ceiling is capped,
    # never carried at the claimed figure.
    out = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("600000"),
                                deduction_claims={"mandatory_contributions": D("25000")})
    line = out["deductionClaims"][0]
    assert (D(line["claimed"]), D(line["ceiling"]), D(line["allowed"]), line["capped"]) == (
        D("25000"), D("18000"), D("18000"), True)
    assert D(out["deductions"]) == D("18000")


def test_approved_donation_deduction_is_35_percent_of_remaining_income(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    out = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("400000"),
                                deductions=D("10000"), deduction_claims={"approved_donation": D("999999")})
    line = out["deductionClaims"][0]
    # 35% of (income 400,000 − allowable expenses 10,000) = 136,500 (PAM 61(e)).
    assert (line["basis"], D(line["allowed"]), line["capped"]) == ("SHARE_OF_INCOME_LESS_ALLOWABLE_EXPENSES", D("136500"), True)


def test_approved_donation_base_excludes_concessionary_deductions_regardless_of_claim_order(db, packs):
    """PAM 61(e): approved donations ≤ (Income − Allowable Expenses −
    Depreciation Allowances) × 35% — the concessionary deductions (here home-loan
    interest) are NOT taken off the base. Corrected 2026-10-01 by independent
    vector ST-22; the previous version of this test asserted a post-HLI base."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    claims = {"approved_donation": D("999999"), "home_loan_interest": D("100000")}
    first = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("400000"),
                                  deduction_claims=claims)
    second = salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("400000"),
                                   deduction_claims={k: claims[k] for k in reversed(list(claims))})
    donation = [c for c in first["deductionClaims"] if c["deduction"] == "approved_donation"][0]
    # Base 400,000 (no allowable expenses) → 35% = 140,000; HLI 100,000 on top.
    assert (D(donation["base"]), D(donation["allowed"])) == (D("400000"), D("140000"))
    assert first["estimatedTax"] == second["estimatedTax"]
    assert D(first["deductions"]) == D("240000")


def test_a_deduction_ceiling_missing_from_the_pack_blocks_instead_of_defaulting(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    rm, sl, _p = _inputs(db, date(2026, 4, 1))
    without = {k: v for k, v in rm.items() if k != "hk_deduction_home_loan_interest"}
    with pytest.raises(HongKongCalculationBlockedError, match="hk_deduction_home_loan_interest"):
        salaries_tax.estimate(year_of_assessment="2026/27", rate_map=without, slabs=sl, income=D("600000"),
                              deduction_claims={"home_loan_interest": D("50000")})
    with pytest.raises(HongKongCalculationBlockedError, match="unknown deduction"):
        salaries_tax.estimate(year_of_assessment="2026/27", rate_map=rm, slabs=sl, income=D("600000"),
                              deduction_claims={"invented": D("1")})


def test_every_seeded_deduction_ceiling_row_is_reachable_from_the_deduction_table(db, packs):
    """One statutory fact, one row: a ceiling nobody can claim (or a second row
    for the same ceiling) is a configuration defect, not a spare row."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    expected_rows = (set(salaries_tax.DEDUCTION_KEYS.values()) | set(salaries_tax.DEDUCTION_PERCENT_KEYS.values())
                     | {key for _d, key in salaries_tax.ADDITIONAL_CEILING_ELECTIONS.values()})
    for pay_date, ya in ((date(2025, 4, 1), "2025/26"), (date(2026, 4, 1), "2026/27")):
        rate_map, _slabs, _pack = _inputs(db, pay_date)
        seeded = {k for k in rate_map if k.startswith("hk_deduction_")}
        assert seeded == expected_rows, (ya, sorted(seeded ^ expected_rows))
    # The MPF mandatory-contribution ceiling is not duplicated in the MPF block.
    rm, _slabs, _pack = _inputs(db, date(2026, 4, 1))
    assert "mpf_tax_deduction_cap" not in rm
    assert rm["hk_deduction_mandatory_contributions"].flat_amount == D("18000")


# ── IRD rules (§7) ──────────────────────────────────────────────────────

def test_ird_year_of_assessment_ends_31_march_not_calendar_year():
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment

    assert year_of_assessment(date(2026, 3, 31)) == "2025/26" and year_of_assessment(date(2026, 4, 1)) == "2026/27"


def test_ird_event_deadlines(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import resolve_timing

    rm, _sl, _p = _inputs(db, date(2026, 7, 15))
    t = resolve_timing(rm)
    assert ird.due_date("IR56E", t, event_date=date(2026, 7, 15)) == date(2026, 10, 15)
    assert ird.due_date("IR56F", t, event_date=date(2026, 7, 15)) == date(2026, 6, 15)
    assert ird.due_date("IR56G", t, event_date=date(2026, 7, 15)) == date(2026, 6, 15)
    assert ird.due_date("IR56B", t, ya="2025/26") == date(2026, 5, 1)
    assert ird.due_date("BIR56A", t, ya="2026/27") == date(2027, 5, 1)


def test_ird_deadline_without_the_pack_timing_is_blocked(db, packs):
    """D-4: a due date may never fall back to a literal — no pack timing, no
    deadline (fail closed, never a silent statutory default)."""
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError, resolve_timing

    with pytest.raises(HongKongCalculationBlockedError, match="ird_ir56e_months"):
        ird.due_date("IR56E", {}, event_date=date(2026, 7, 15))
    rm, _sl, _p = _inputs(db, date(2026, 7, 15))
    partial = {k: v for k, v in resolve_timing(rm).items() if k != "ird_ir56e_months"}
    with pytest.raises(HongKongCalculationBlockedError, match="ird_ir56e_months"):
        ird.due_date("IR56E", partial, event_date=date(2026, 7, 15))


def test_case_j_ir56b_suppressed_after_filed_ir56f_for_the_same_income():
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird

    prior = [{"id": 7, "formType": "IR56F", "status": "FILED", "incomePeriodStart": "2025-04-01", "incomePeriodEnd": "2025-12-31"}]
    out = ird.ir56b_suppression("2025/26", (date(2025, 4, 1), date(2025, 12, 31)), prior)
    assert out["action"] == "SUPPRESS" and "twice" in out["message"]
    partial = ird.ir56b_suppression("2025/26", (date(2025, 4, 1), date(2026, 3, 31)), prior)
    assert partial["action"] == "RESOLVE"
    unfiled = ird.ir56b_suppression("2025/26", (date(2025, 4, 1), date(2025, 12, 31)), [{**prior[0], "status": "PREPARED"}])
    assert unfiled["action"] == "FILE"


def test_ir56g_not_required_for_frequent_travellers_or_short_absence(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import resolve_timing

    t = resolve_timing(_inputs(db, date(2026, 8, 1))[0])
    assert ird.tax_clearance_required(t, date(2026, 8, 1), frequent_travel=True)["required"] is False
    assert ird.tax_clearance_required(t, date(2026, 8, 1), return_date=date(2026, 8, 20))["required"] is False
    assert ird.tax_clearance_required(t, date(2026, 8, 1))["fileBy"] == "2026-07-01"
    assert ird.tax_clearance_required(t, date(2026, 8, 1), return_date=date(2026, 9, 5),
                                      likely_chargeable=False)["required"] is False


# ── IR56G state machine (golden case I) ─────────────────────────────────

def test_case_i_ir56g_states_and_release_rules(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import tax_clearance as tc
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import resolve_timing

    t = resolve_timing(_inputs(db, date(2026, 7, 31))[0])

    assert tc.STATES == ("INACTIVE", "DEPARTURE_IDENTIFIED", "IR56G_DUE", "IR56G_FILED_HOLD_ACTIVE",
                         "LETTER_OF_RELEASE_RECEIVED", "DEPARTURE_CANCELLED_OR_CHANGED", "CASE_CLOSED")
    # Identified 35 days ahead → deadline created, still DEPARTURE_IDENTIFIED.
    assert tc.initial_state(date(2026, 6, 26), date(2026, 7, 31), t) == "DEPARTURE_IDENTIFIED"
    assert tc.filing_deadline(date(2026, 7, 31), t) == date(2026, 6, 30)
    assert tc.initial_state(date(2026, 7, 5), date(2026, 7, 31), t) == "IR56G_DUE"
    assert tc.statutory_hold_expiry(date(2026, 6, 28), t) == date(2026, 7, 28)
    assert not tc.can_transition("IR56G_FILED_HOLD_ACTIVE", "CASE_CLOSED")      # never silently cleared
    filed = date(2026, 6, 28)
    r = tc.release_refusal
    assert "evidence" in r("IR56G_FILED_HOLD_ACTIVE", "LETTER_OF_RELEASE", "LOR-1", None, filed, filed, 1, 2)
    assert "four-eyes" in r("IR56G_FILED_HOLD_ACTIVE", "LETTER_OF_RELEASE", "LOR-1", "doc", filed, filed, 1, 1)
    assert "runs to 2026-07-28" in r("IR56G_FILED_HOLD_ACTIVE", "STATUTORY_PERIOD_ELAPSED", None, "doc", filed,
                                     date(2026, 7, 20), 1, 2, timing=t)
    assert r("IR56G_FILED_HOLD_ACTIVE", "STATUTORY_PERIOD_ELAPSED", None, "doc", filed, date(2026, 7, 28), 1, 2,
             timing=t) is None
    assert r("IR56G_FILED_HOLD_ACTIVE", "LETTER_OF_RELEASE", "LOR-1", "doc", filed, filed, 1, 2) is None
    assert "no active hold" in r("DEPARTURE_IDENTIFIED", "LETTER_OF_RELEASE", "L", "doc", filed, filed, 1, 2)


# ── Provenance / effective dating of the seeded packs ───────────────────

def test_every_seeded_row_has_a_source_artifact_and_the_packs_are_draft(db):
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    packs = seed_hong_kong_all(db)
    db.commit()
    assert {p.status for p in packs} == {"Draft"}
    for model in (ContributionRate, TaxSlab):
        assert db.query(model).filter(model.jurisdiction_country == "HK", model.source_document_id.is_(None)).count() == 0
    arts = db.query(SourceArtifact).all()
    assert all(a.checksum_sha256 for a in arts if "UNVERIFIED" not in a.title)
    assert [a.title for a in arts if not a.checksum_sha256] == [
        "[UNVERIFIED — G1] Employment Ordinance Cap. 57 s.2 definition of 'week' (continuous contract)"]


def test_no_seeded_hk_row_is_orphaned_by_the_code():
    """A seeded row that no rule module reads is either a spelling mistake or a
    statutory value nothing enforces — both are defects. This walks the seed
    tables and requires every component key to appear in the application."""
    from pathlib import Path

    import scripts.seed_hong_kong_canonical_pack as seed_mod
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    backend = Path(seed_mod.__file__).resolve().parents[1]          # scripts/ -> backend
    application = "".join(p.read_text(encoding="utf-8") for p in sorted((backend / "app").rglob("*.py")))
    for table in (seed_mod.COMMON_RATES, seed_mod.EO_CONVENTIONS):
        for key, _label, _source, _value in table:
            assert key in application, f"{key} is seeded but nothing reads it"
    deduction_keys = set(seed_mod.DEDUCTION_CEILINGS) | set(seed_mod.DEDUCTION_PERCENT_KEYS)
    expected = set(salaries_tax.DEDUCTION_KEYS.values()) | set(salaries_tax.DEDUCTION_PERCENT_KEYS.values())
    assert deduction_keys == expected


def test_seed_is_idempotent_and_refuses_non_draft(db):
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_hong_kong_canonical_pack import YA_2026, seed_hong_kong, seed_hong_kong_all

    p25, p26 = seed_hong_kong_all(db)
    db.commit()
    ids = sorted(i for (i,) in db.query(ContributionRate.id).filter(ContributionRate.jurisdiction_pack_id == p26.id))
    seed_hong_kong_all(db)
    db.commit()
    assert sorted(i for (i,) in db.query(ContributionRate.id).filter(ContributionRate.jurisdiction_pack_id == p26.id)) == ids
    p26.status = "Approved"
    db.commit()
    with pytest.raises(SystemExit):
        seed_hong_kong(db, YA_2026)


def test_packs_are_year_of_assessment_windows_and_resolve_by_payroll_date(db, packs):
    p25, p26 = packs
    assert (p25.effective_from, p25.effective_to) == (date(2025, 4, 1), date(2026, 3, 31))
    assert (p26.effective_from, p26.effective_to) == (date(2026, 4, 1), date(2027, 3, 31))
    assert _inputs(db, date(2026, 3, 31))[2].id == p25.id and _inputs(db, date(2026, 4, 1))[2].id == p26.id
    # Row-level dating inside ONE pack: April 2026 still resolves HK$42.10.
    rm_apr = _inputs(db, date(2026, 4, 30))[0]
    rm_may = _inputs(db, date(2026, 5, 1))[0]
    assert (rm_apr["smw_hourly_rate"].flat_amount, rm_may["smw_hourly_rate"].flat_amount) == (D("42.10"), D("43.10"))


def test_hkid_check_digit_validation():
    from app.modules.payroll.employee_validation import HKEmployeeValidation, hkid_check_digit_valid

    assert hkid_check_digit_valid("A123456(3)") and hkid_check_digit_valid("A1234563")
    assert not hkid_check_digit_valid("A123456(4)")
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        HKEmployeeValidation.validate({"hkid": "A123456(4)"})
    assert "hkid" in HKEmployeeValidation.SENSITIVE_FIELDS


# ── Preflight / run readiness (§14) ──────────────────────────────────────

def _emp(code="HK-001"):
    return {"id": 1, "code": code, "identity": {"hkid": "A123456(3)", "passport_number": None}}


def test_preflight_pack_checks_are_empty_for_the_seeded_packs_and_fail_closed_when_incomplete(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    rate_map, _slabs, _pack = _inputs(db, date(2026, 6, 30))
    assert pf.pack_checks(rate_map) == []
    # MPF parameters are the authority, not a hand-kept key list.
    without = {k: v for k, v in rate_map.items() if k != "mpf_employer_rate"}
    codes = [c["code"] for c in pf.pack_checks(without)]
    assert codes == ["HK_PACK_INCOMPLETE:MPF"]
    assert all(c["severity"] == pf.BLOCK for c in pf.pack_checks(without))
    # Reporting timing and the wage-payment deadline fail closed the same way.
    assert [c["code"] for c in pf.pack_checks(
        {k: v for k, v in rate_map.items() if k != "eo_wage_payment_days"})] == [
        "HK_PACK_INCOMPLETE:wage payment timing"]
    assert [c["code"] for c in pf.pack_checks(
        {k: v for k, v in rate_map.items() if k != "ird_ir56g_hold_months"})] == [
        "HK_IRD_TIMING_INCOMPLETE"]


def test_wage_payment_timing_uses_the_pack_row_and_the_termination_rule(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    rate_map, _slabs, _pack = _inputs(db, date(2026, 6, 30))
    pe = date(2026, 5, 31)
    on_time = pf.wage_payment_timing(date(2026, 6, 7), pe, rate_map)
    assert (on_time["daysAllowed"], on_time["latestPaymentDate"], on_time["onTime"]) == (7, "2026-06-07", True)
    late = pf.wage_payment_timing(date(2026, 6, 8), pe, rate_map)
    assert (late["latestPaymentDate"], late["daysUsed"], late["onTime"]) == ("2026-06-07", 8, False)
    leaving = pf.wage_payment_timing(date(2026, 6, 30), pe, rate_map, date(2026, 6, 30))
    assert leaving["terminationTriggered"] and leaving["terminationImmediateDue"]
    # The source is the pack row, so the disclosure names the artifact.
    assert on_time["source"]["componentKey"] == "eo_wage_payment_days"
    assert on_time["source"]["sourceDocumentId"]


def test_wage_payment_late_blocks_and_a_leaver_requires_immediate_payment(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    rate_map, _slabs, _pack = _inputs(db, date(2026, 6, 30))
    late = pf.wage_payment_checks(_emp(), date(2026, 6, 9), date(2026, 5, 31), rate_map)
    assert [c["code"] for c in late] == ["EO_WAGE_PAYMENT_LATE"] and late[0]["severity"] == pf.BLOCK
    assert "2026-06-07" in late[0]["message"]
    ok = pf.wage_payment_checks(_emp(), date(2026, 6, 5), date(2026, 5, 31), rate_map)
    assert [c["code"] for c in ok] == ["EO_WAGE_PAYMENT_TIMING"] and ok[0]["severity"] == pf.INFO
    leaver = pf.wage_payment_checks(_emp(), date(2026, 6, 5), date(2026, 5, 31), rate_map, date(2026, 6, 4))
    assert [c["code"] for c in leaver] == ["EO_TERMINATION_WAGES_DUE_IMMEDIATELY"]
    assert leaver[0]["severity"] == pf.BLOCK


def test_preflight_missing_hkid_blocks_but_a_passport_is_enough():
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    assert [c["code"] for c in pf.identity_checks(
        {"id": 9, "code": "HK-009", "identity": {"hkid": None, "passport_number": None}})] == ["HK_IDENTITY_MISSING"]
    assert pf.identity_checks({"id": 9, "code": "HK-009", "identity": {"hkid": None, "passport_number": "X1"}}) == []
    assert pf.identity_checks(_emp()) == []


def test_preflight_continuous_contract_is_never_assumed():
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    undetermined = pf.continuous_contract_checks(_emp(), {"status": "UNDETERMINED"})
    assert undetermined[0]["code"] == "EO_CC_UNDETERMINED" and undetermined[0]["severity"] == pf.BLOCK
    not_continuous = pf.continuous_contract_checks(_emp(), {"status": "NOT_CONTINUOUS", "asOf": "2026-06-30"})
    assert not_continuous[0]["code"] == "EO_NOT_A_CONTINUOUS_CONTRACT" and not_continuous[0]["severity"] == pf.INFO
    ok = pf.continuous_contract_checks(
        _emp(), {"status": "CONTINUOUS", "continuousSince": "2024-01-01", "weeksOfContinuity": 130, "asOf": "2026-06-30"})
    assert ok[0]["code"] == "EO_CONTINUOUS_CONTRACT" and "2024-01-01" in ok[0]["message"]
    # Not assessed at all is a WARN that tells the operator what to record.
    none = pf.continuous_contract_checks(_emp(), None)
    assert none[0]["code"] == "EO_CC_NOT_ASSESSED" and none[0]["severity"] == pf.WARN


def test_preflight_reports_the_engines_own_minimum_wage_and_mpf_assessment(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    trace = _calc(db, gross="8000", pay=date(2026, 6, 30), hours={"2026-06-01": D("200")}).hk_calculation_trace
    smw_checks = pf.minimum_wage_checks(_emp(), trace["minimumWage"])
    assert "SMW_HOURS_RECORD" in {c["code"] for c in smw_checks}
    # A covered month with no exception says nothing about MPF (parity with SG).
    assert pf.mpf_checks(_emp(), trace["mpf"]) == []
    # Below the minimum level the employer still contributes and the operator is told.
    low = _calc(db, gross="6000", pay=date(2026, 6, 30), hours={"2026-06-01": D("200")}).hk_calculation_trace
    codes = {c["code"] for c in pf.mpf_checks(_emp(), low["mpf"])}
    assert "MPF_BELOW_MINIMUM" in codes
    assert all(c["employeeId"] == 1 for c in pf.mpf_checks(_emp(), low["mpf"]))


def test_preflight_reports_the_60_day_rule_and_a_catch_up(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    facts = {"dateOfJoining": date(2026, 6, 1).isoformat(), "dateOfBirth": "1990-01-01"}
    pending = _calc(db, gross="9000", pay=date(2026, 6, 30), facts=facts,
                    hours={"2026-06-01": D("200")}).hk_calculation_trace
    codes = {c["code"] for c in pf.mpf_checks(_emp(), pending["mpf"])}
    assert "MPF_60_DAY_NOT_MET" in codes
    mature = _calc(db, gross="9000", pay=date(2026, 6, 30),
                   facts={"dateOfJoining": "2024-01-01", "dateOfBirth": "1990-01-01"},
                   hours={"2026-06-01": D("200")}).hk_calculation_trace
    catch_up = {**mature["mpf"], "catchUp": [{"payslipId": 1, "employee": "100.00", "employer": "100.00"}]}
    assert {c["code"] for c in pf.mpf_checks(_emp(), catch_up)} == {"MPF_CATCH_UP"}


def test_preflight_smw_breach_blocks_with_the_top_up_amount(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    breach = pf.minimum_wage_checks(_emp(), {
        "status": "BREACH", "countableWages": "100.00", "hours": "20", "minimumDue": "862.00",
        "topUpRequired": "762.00", "hoursRecord": {"required": False}})
    assert [c["code"] for c in breach] == ["SMW_BREACH"] and breach[0]["severity"] == pf.BLOCK
    assert "762.00" in breach[0]["message"]


def test_preflight_ird_hold_and_overdue_case():
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    holding = pf.ird_checks(_emp(), {"id": 4, "state": "IR56G_FILED_HOLD_ACTIVE"})
    assert holding[0]["code"] == "IR56G_HOLD_ACTIVE" and holding[0]["severity"] == pf.WARN
    assert "HELD_FOR_IR56G" in holding[0]["message"]
    blocking = pf.ird_checks(_emp(), {"id": 4, "state": "IR56G_DUE", "filing_deadline": "2026-06-02"})
    assert blocking[0]["code"] == "IR56G_NOT_YET_FILED" and blocking[0]["severity"] == pf.BLOCK
    overdue = pf.ird_checks(_emp(), None, [
        {"id": 7, "form_type": "HK_IR56G", "status": "DUE", "dueDate": "2026-05-01"}], date(2026, 6, 30))
    assert overdue[0]["code"] == "IRD_OVERDUE:HK_IR56G" and overdue[0]["severity"] == pf.WARN
    filed = pf.ird_checks(_emp(), None, [
        {"id": 7, "form_type": "HK_IR56G", "status": "FILED", "dueDate": "2026-05-01"}], date(2026, 6, 30))
    assert filed == []


def test_preflight_hold_states_come_from_the_rule_modules_not_a_local_list():
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird, preflight as pf, tax_clearance

    assert set(pf._HOLDING_STATES) == set(tax_clearance.HOLDING_STATES)
    assert set(pf._FINAL_PAY_BLOCKING_STATES) == set(tax_clearance.FINAL_PAY_BLOCKING_STATES)
    assert set(pf._OPEN_IRD_STATUSES) == {"DUE", "PREPARED", "VALIDATED", "AMENDED"}
    assert not set(pf._OPEN_IRD_STATUSES) & set(ird.FILED_STATES)


def test_preflight_summarize_status(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong import preflight as pf

    assert pf.summarize([])["status"] == "CLEAR"
    assert pf.summarize([pf.check("A", pf.WARN, "m")])["status"] == "REVIEW"
    blocked = pf.summarize([pf.check("A", pf.WARN, "m"), pf.check("B", pf.BLOCK, "m")])
    assert blocked["status"] == "BLOCKED" and blocked["counts"] == {pf.BLOCK: 1, pf.WARN: 1, pf.INFO: 0}

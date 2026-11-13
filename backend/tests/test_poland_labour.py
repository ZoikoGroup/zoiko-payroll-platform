"""Poland labour-law controls (ZP-PL-ENG-001 Phase 5; spec §8, PL-015 / PL-016,
QA matrix "Minimum wage" and "Overtime/leave")."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError, calculate
from app.modules.payroll.engine.jurisdictions.poland import leave
from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack
from tests._pl_engine_helpers import PAY_DATE, build_pack, ctx, profile

TEST_PREMIUM_MAP = "DAILY=50,WEEKLY=100,NIGHT=100,SUNDAY_HOLIDAY=100,COMP_TIME_FAILED=50"   # TEST fixture
ALL_BUT_MIN_WAGE = ("PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE", "FP_FS", "FGSP", "FEP",
                    "PPK")


def _pl(context):
    return calculate(context)["pl_result"]


def _blocks(context, prefix):
    with pytest.raises(PLCalculationBlockedError) as raised:
        calculate(context)
    assert raised.value.key.startswith(prefix), raised.value.key


def _codes(pl):
    return [e["code"] for e in pl["exceptions"]]


def _signed_classes(component):
    return {(o, component): "INCLUDED" for o in ALL_BUT_MIN_WAGE}


# ── minimum wage (PL-015) ──────────────────────────────────────────────────
def test_full_time_at_or_above_the_minimum_passes():
    pl = _pl(ctx(gross="4806"))
    assert pl["trace"]["labour"]["minimumWage"]["status"] == "PASS" and "MIN_WAGE_BREACH" not in _codes(pl)


def test_full_time_below_the_minimum_is_an_exception_that_stops_approval():
    pl = _pl(ctx(gross="4805.99"))
    assert pl["trace"]["labour"]["minimumWage"]["status"] == "BREACH"
    assert "MIN_WAGE_BREACH" in _codes(pl)


@pytest.mark.parametrize("gross, status", [("2403", "PASS"), ("2402.99", "BREACH")])
def test_part_time_is_prorated(gross, status):
    pl = _pl(ctx(gross=gross, profile_overrides={"fte_numerator": 1, "fte_denominator": 2}))
    assert pl["trace"]["labour"]["minimumWage"]["minimumWage"] == "2403.00"
    assert pl["trace"]["labour"]["minimumWage"]["status"] == status


def test_excluded_components_cannot_mask_a_deficient_base_wage():
    # 4,000 salary + 1,500 seniority allowance = 5,500 gross, but the
    # minimum-wage base is the 4,000 (seniority is EXCLUDED there, PL-015).
    pl = _pl(ctx(gross="5500", components={"SALARY": Decimal("4000"), "SENIORITY_ALLOWANCE": Decimal("1500")},
                 pack=build_pack(classes=_signed_classes("SENIORITY_ALLOWANCE"))))
    assert pl["trace"]["bases"]["MIN_WAGE"]["base"] == "4000.00"
    assert "MIN_WAGE_BREACH" in _codes(pl)


def test_unpaid_absence_is_flagged_not_guessed():
    pl = _pl(ctx(gross="3000", unpaid_leave_days=5))
    assert pl["trace"]["labour"]["minimumWage"]["status"] == "NOT_EVALUATED"
    assert _codes(pl) == ["MIN_WAGE_NOT_EVALUATED"]


@pytest.mark.parametrize("overrides", [{"fte_numerator": None, "fte_denominator": None},
                                       {"fte_numerator": 3, "fte_denominator": 2},
                                       {"fte_numerator": 0, "fte_denominator": 1}])
def test_missing_or_invalid_fte_blocks(overrides):
    _blocks(ctx(profile_overrides=overrides), "PL_FACT_MISSING:fte")


def test_the_minimum_wage_comes_from_the_pack():
    pl = _pl(ctx(gross="5000", pack=build_pack({"pl_min_wage_monthly": "5100"})))
    assert pl["trace"]["labour"]["minimumWage"]["minimumWage"] == "5100.00" and "MIN_WAGE_BREACH" in _codes(pl)


# ── overtime (PL-016) ──────────────────────────────────────────────────────
def _ot(components, events, premium_map=TEST_PREMIUM_MAP, **extra):
    classes = {**_signed_classes("OVERTIME_50"), **_signed_classes("OVERTIME_100")}
    gross = sum(components.values(), Decimal("0"))
    return ctx(gross=gross, components=components, pl_overtime_events=events,
               pack=build_pack({"pl_overtime_premium_map": premium_map}, classes=classes), **extra)


def test_overtime_without_its_events_blocks():
    _blocks(_ot({"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("1500")}, None), "PL_OVERTIME_EVENTS_MISSING")


def test_overtime_matches_normal_pay_plus_premium_per_event():
    events = [{"kind": "DAILY", "event_ref": "D-2026-03-10", "hours": "10", "hourly_rate": "50"},
              {"kind": "SUNDAY_HOLIDAY", "event_ref": "S-2026-03-15", "hours": "8", "hourly_rate": "50"}]
    pl = _pl(_ot({"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("750"), "OVERTIME_100": Decimal("800")}, events))
    overtime = pl["trace"]["labour"]["overtime"]
    assert overtime["status"] == "MATCHED"
    assert overtime["expected"] == {"OVERTIME_50": "750.00", "OVERTIME_100": "800.00"}
    assert [e["eventRef"] for e in overtime["events"]] == ["D-2026-03-10", "S-2026-03-15"]   # the triggering event


def test_the_same_legal_excess_never_earns_two_premiums():
    events = [{"kind": "DAILY", "event_ref": "X1", "hours": "10", "hourly_rate": "50"},
              {"kind": "WEEKLY", "event_ref": "X1", "hours": "10", "hourly_rate": "50"}]
    _blocks(_ot({"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("750"), "OVERTIME_100": Decimal("1000")}, events),
            "PL_OVERTIME_DOUBLE_PREMIUM:X1")


@pytest.mark.parametrize("events, components, code", [
    ([{"kind": "DAILY", "event_ref": "A", "hours": "10", "hourly_rate": "50"}],
     {"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("700")}, "PL_OVERTIME_MISMATCH:OVERTIME_50"),
    ([{"kind": "LUNCH", "event_ref": "A", "hours": "10", "hourly_rate": "50"}],
     {"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("750")}, "PL_OVERTIME_EVENT_INVALID:LUNCH"),
    ([{"kind": "DAILY", "event_ref": "", "hours": "10", "hourly_rate": "50"}],
     {"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("750")}, "PL_OVERTIME_EVENT_INVALID:DAILY"),
])
def test_invalid_overtime_blocks(events, components, code):
    _blocks(_ot(components, events), code)


def test_unsigned_or_invalid_premium_map_blocks():
    events = [{"kind": "DAILY", "event_ref": "A", "hours": "10", "hourly_rate": "50"}]
    components = {"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("750")}
    _blocks(_ot(components, events, premium_map="PENDING_G1"), "PL_POLICY_PENDING:pl_overtime_premium_map")
    _blocks(_ot(components, events, premium_map="DAILY=75"), "PL_POLICY_PENDING:pl_overtime_premium_map")


def test_night_supplement_blocks_until_a_rule_is_signed():
    _blocks(ctx(gross="8500", components={"SALARY": Decimal("8000"), "NIGHT_SUPPLEMENT": Decimal("500")},
                pack=build_pack(classes=_signed_classes("NIGHT_SUPPLEMENT"))),
            "PL_POLICY_PENDING:pl_night_supplement_basis")


# ── pay timing (spec §8) ───────────────────────────────────────────────────
@pytest.mark.parametrize("pay_date, status", [(date(2026, 4, 10), "OK"), (date(2026, 4, 11), "LATE")])
def test_monthly_pay_deadline(pay_date, status):
    pl = _pl(ctx(pay_date=pay_date, period_end=date(2026, 3, 31),
                 registration_overrides={"accident_rate_to": date(2027, 3, 31)}))
    assert pl["trace"]["labour"]["payTiming"]["status"] == status
    assert ("PAY_DATE_LATE" in _codes(pl)) is (status == "LATE")


def test_pay_timing_without_a_period_end_is_not_evaluated():
    assert _pl(ctx())["trace"]["labour"]["payTiming"]["status"] == "NOT_EVALUATED"


# ── annual leave entitlement (spec §8) ─────────────────────────────────────
def _pack(overrides=None):
    rate_map, slabs = build_pack(overrides)
    return PlPack(rate_map, slabs, 1, PAY_DATE)


@pytest.mark.parametrize("months, tier, days", [(0, "BASE", "20"), (119, "BASE", "20"), (120, "SENIOR", "26")])
def test_leave_tier_by_service_credit(months, tier, days):
    out = leave.annual_entitlement(_pack(), profile(service_credit_months=months))
    assert (out["tier"], out["days"]) == (tier, days)


def test_part_time_leave_needs_a_signed_rounding_rule():
    with pytest.raises(PLCalculationBlockedError, match="pl_leave_part_time_rounding"):
        leave.annual_entitlement(_pack(), profile(fte_numerator=3, fte_denominator=4))
    up = leave.annual_entitlement(_pack({"pl_leave_part_time_rounding": "ROUND_UP_FULL_DAY"}),
                                  profile(fte_numerator=3, fte_denominator=4, service_credit_months=130))
    assert (up["exactDays"], up["days"]) == ("19.5", "20")                       # 26 x 3/4
    exact = leave.annual_entitlement(_pack({"pl_leave_part_time_rounding": "EXACT"}),
                                     profile(fte_numerator=3, fte_denominator=4, service_credit_months=130))
    assert exact["days"] == "19.5"


def test_leave_needs_service_credit():
    with pytest.raises(PLCalculationBlockedError, match="service_credit_months"):
        leave.annual_entitlement(_pack(), profile(service_credit_months=None))


def test_golden_results_are_unchanged_by_the_labour_checks():
    pl = _pl(ctx())
    assert pl["pl_net"] == "5608.91" and pl["exceptions"] == []

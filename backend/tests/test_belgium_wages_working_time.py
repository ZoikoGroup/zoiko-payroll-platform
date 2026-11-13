"""Belgium (ZP-BE-ENG-001) Block B1: wages and working time (spec §4 / §7,
§16 wage and working-time rows).

SYNTHETIC TEST ONLY content (tests/_be_engine_helpers.py): fake scale amounts
(900 / 1200), fallback 1000, limits 12 h / 50 h, premiums 10 % / 20 %. The sector
minimum comes first; the interprofessional fallback only when no sector minimum
applies; any breach is an exception and pay is never topped up."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests._be_engine_helpers import PAY, TEST_HOLIDAY, build_pack, context, rate, records


def _calc(ctx):
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(ctx, "standard")


def _blocked(ctx):
    from app.modules.payroll.engine.countries.belgium import BECalculationBlockedError

    with pytest.raises(BECalculationBlockedError) as raised:
        _calc(ctx)
    return raised.value.key


def _codes(result):
    return {e["code"] for e in result["exceptions"]}


SCALES = [{"functionClass": "B", "seniorityFromMonths": 0, "monthlyMinimum": "900", "fullTimeWeeklyHours": "38"},
          {"functionClass": "B", "seniorityFromMonths": 12, "monthlyMinimum": "1200", "fullTimeWeeklyHours": "38"},
          {"functionClass": "B", "seniorityFromMonths": 12, "scheduleRegime": "AVERAGE", "monthlyMinimum": "950",
           "fullTimeWeeklyHours": "38"}]


def _agreement(modules):
    return {30: dict(records()["be_agreements"][30], modules=modules)}


def _line(**over):
    return [dict(records()["be_classifications"][0], **over)]


# ── sector minimum first (BE-020 / BE-021) ──────────────────────────────────
def test_the_sector_minimum_is_checked_first_and_a_breach_is_an_exception_never_a_top_up():
    r = _calc(context(be_agreements=_agreement({"wage_scales": SCALES})))       # seniority 24 -> the 12-month row
    b = r.be_result
    assert b["be_wage_floor"] == {"source": "SECTOR", "required": "1200", "paid": "1000"}
    assert "BE_MINIMUM_WAGE_BREACH" in _codes(b)
    assert r.net_pay == Decimal("852.00") and r.gross == Decimal("1000")       # never topped up


def test_the_seniority_band_and_the_regime_specific_row_are_chosen():
    junior = _calc(context(be_agreements=_agreement({"wage_scales": SCALES}),
                           be_classifications=_line(seniority_months=6))).be_result
    assert junior["be_wage_floor"]["required"] == "900" and "BE_MINIMUM_WAGE_BREACH" not in _codes(junior)
    average = dict(records()["be_schedules"][0], regime="AVERAGE")
    regime = _calc(context(be_agreements=_agreement({"wage_scales": SCALES}), be_schedules=[average])).be_result
    assert regime["be_wage_floor"]["required"] == "950"


def test_a_part_time_schedule_is_pro_rata():
    part = dict(records()["be_schedules"][0], weekly_hours="19")
    b = _calc(context(be_agreements=_agreement({"wage_scales": SCALES}), be_schedules=[part])).be_result
    assert Decimal(b["be_wage_floor"]["required"]) == Decimal("600")            # 1200 x 19 / 38
    assert "BE_MINIMUM_WAGE_BREACH" not in _codes(b)


def test_no_scale_for_the_function_class_is_an_exception_not_a_fallback():
    b = _calc(context(be_agreements=_agreement({"wage_scales": SCALES}),
                      be_classifications=_line(function_class="Z"))).be_result
    assert b["be_wage_floor"]["source"] == "SECTOR" and "BE_SCALE_ROW_MISSING" in _codes(b)


def test_the_interprofessional_minimum_only_when_no_sector_minimum_applies():
    b = _calc(context()).be_result                                     # the agreement carries no wage_scales
    assert b["be_wage_floor"]["source"] == "RMMMG"
    assert Decimal(b["be_wage_floor"]["required"]) == Decimal("760")   # 1000 x 38 / 50 (fake fallback and limit)
    assert "no wage scale" in b["trace"]["wages"]["floor"]["reason"]
    low = _calc(context(gross="700")).be_result
    assert "BE_MINIMUM_WAGE_BREACH" in _codes(low)


def test_no_fallback_when_a_committee_applies_but_no_agreement_is_linked():
    b = _calc(context(be_classifications=_line(collective_agreement_id=None))).be_result
    assert b["be_wage_floor"] == {"source": "NONE", "required": None, "paid": "1000"}
    assert "BE_SECTOR_AGREEMENT_MISSING:MAIN" in _codes(b)


def test_the_fallback_needs_the_age_condition():
    unknown = _calc(context(be_date_of_birth=None)).be_result
    assert "BE_SECTOR_MINIMUM_UNVERIFIED" in _codes(unknown)
    young = _calc(context(be_date_of_birth="2020-01-01")).be_result               # below the fake minimum age 10
    assert "BE_SECTOR_MINIMUM_UNVERIFIED" in _codes(young)


def test_hourly_paid_workers_need_the_hours_paid():
    pack = build_pack(rates_over={"be_supported_pay_bases": rate("be_supported_pay_bases", text="SALARIED,HOURLY")})
    hourly = dict(records()["be_profile"], pay_basis="HOURLY")
    scales = [{"functionClass": "B", "seniorityFromMonths": 0, "hourlyMinimum": "9"}]
    no_hours = _calc(context(pack=pack, be_profile=hourly, be_agreements=_agreement({"wage_scales": scales}))).be_result
    assert "BE_SECTOR_MINIMUM_UNVERIFIED" in _codes(no_hours)
    ok = _calc(context(pack=pack, be_profile=hourly, be_agreements=_agreement({"wage_scales": scales}),
                       be_hours_paid=Decimal("100"))).be_result
    assert ok["be_wage_floor"]["required"] == "900" and "BE_MINIMUM_WAGE_BREACH" not in _codes(ok)


def test_the_floor_reads_the_sector_min_wage_base_not_gross():
    from tests._be_engine_helpers import CLASSES

    assert "SECTOR_MIN_WAGE" not in CLASSES["OVERTIME_PREMIUM"]
    b = _calc(context(gross="1100", components={"SALARY": "1000", "OVERTIME_PREMIUM": "100"},
                      be_working_time={"days": [{"date": "2026-03-02", "hours": "8"}]})).be_result
    assert b["be_wage_floor"]["paid"] == "1000"


# ── index-centime limitation and wage norm ──────────────────────────────────
def test_index_centime_limitation_and_wage_norm_warning_only():
    capped = _calc(context(be_indexation={"increase": "25", "increasePct": "20"})).be_result
    assert "BE_INDEXATION_ABOVE_LIMIT" in _codes(capped)                  # fake formula caps the increase at 10
    assert {w["code"] for w in capped["warnings"]} == {"BE_WAGE_NORM_WARNING"}
    assert "BE_WAGE_NORM_WARNING" not in _codes(capped)                    # a warning, never an exception
    within = _calc(context(be_indexation={"increase": "5", "increasePct": "1"})).be_result
    assert "BE_INDEXATION_ABOVE_LIMIT" not in _codes(within) and within["warnings"] == []
    pending = build_pack(rates_over={"be_wage_index_centime_threshold": dict(
        build_pack()[0]["be_wage_index_centime_threshold"], label="x [PENDING G1]")})
    assert _blocked(context(pack=pending, be_indexation={"increase": "5"})) == \
        "BE_CONTENT_PENDING:be_wage_index_centime_threshold"
    assert _calc(context(pack=pending)).be_result["trace"]["wages"]["indexation"] == {"applied": False}


# ── working time (BE-022 / BE-023) ──────────────────────────────────────────
WEEK = [f"2026-03-{d:02d}" for d in range(2, 7)]                                  # Monday 2 .. Friday 6 March


def _days(hours, dates=WEEK):
    return {"days": [{"date": d, "hours": str(hours)} for d in dates]}


def test_overtime_above_the_governing_effective_schedule_is_a_ledger_fact():
    b = _calc(context(be_working_time=_days(9))).be_result                     # 45 h in a 38 h week
    assert b["be_working_time"] == {"overtimeHours": "7", "compensatoryRestEarned": "7"}
    assert b["accumulatorDeltas"]["OVERTIME_HOURS"] == "7"
    assert b["accumulatorDeltas"]["COMPENSATORY_REST_HOURS"] == "7"            # fake formula: rest = overtime
    taken = _calc(context(be_working_time={**_days(9), "restTakenHours": "3"})).be_result
    assert taken["accumulatorDeltas"]["COMPENSATORY_REST_HOURS"] == "4"
    assert "BE_OVERTIME_PREMIUM_UNVERIFIED" in _codes(b)                      # no hourly rate known


def test_the_average_regime_measures_over_the_period():
    two_weeks = {"days": [{"date": d, "hours": "9"} for d in WEEK]
                 + [{"date": f"2026-03-{d:02d}", "hours": "6.2"} for d in range(9, 14)]}
    effective = _calc(context(be_working_time=two_weeks)).be_result
    average = dict(records()["be_schedules"][0], regime="AVERAGE")
    averaged = _calc(context(be_working_time=two_weeks, be_schedules=[average])).be_result
    assert effective["be_working_time"]["overtimeHours"] == "7"                # week 1 only
    assert averaged["be_working_time"]["overtimeHours"] == "0"                # 76 h over 2 weeks of 38 h


def test_sunday_public_holiday_and_substitute_days_use_the_holiday_premium():
    days = _days(8)["days"] + [{"date": "2026-03-08", "hours": "6"}]          # 40 + Sunday 6 = 46 h
    b = _calc(context(be_working_time={"days": days}, be_hourly_rate=Decimal("10"),
                      gross="1100", components={"SALARY": "1000", "OVERTIME_PREMIUM": "100"})).be_result
    wt = b["trace"]["workingTime"]
    assert (wt["overtimeWeekday"], wt["overtimeSundayHoliday"]) == ("2", "6")
    assert wt["premiums"] == {"source": "CONTENT", "weekday": "10.00", "sundayHoliday": "20.00"}
    holiday_week = [f"2026-04-{d:02d}" for d in range(6, 11)]                    # Monday 6 April = TEST holiday
    h = _calc(context(be_working_time=_days(9, holiday_week))).be_result["trace"]["workingTime"]
    assert h["overtimeSundayHoliday"] == "7" and TEST_HOLIDAY in h["holidayDates"]
    sub = _calc(context(be_working_time={**_days(9), "substituteDays": ["2026-03-04"]})).be_result
    assert sub["trace"]["workingTime"]["overtimeSundayHoliday"] == "7"         # the substitute day counts


def test_a_sector_override_replaces_the_content_premiums():
    modules = {"overtime": {"weekdayPct": "15", "sundayHolidayPct": "30"}}
    b = _calc(context(be_working_time=_days(9), be_agreements=_agreement(modules))).be_result
    assert b["trace"]["workingTime"]["premiums"] == {"source": "SECTOR", "weekday": "15", "sundayHoliday": "30"}


def test_the_premium_is_verified_when_the_hourly_rate_is_known():
    base = dict(be_working_time=_days(9), be_hourly_rate=Decimal("10"), gross="1100")
    short = _calc(context(**base, components={"SALARY": "1095", "OVERTIME_PREMIUM": "5"})).be_result
    assert "BE_OVERTIME_PREMIUM_SHORT" in _codes(short)                        # due 7 h x 10 x 10 % = 7
    paid = _calc(context(**base, components={"SALARY": "1093", "OVERTIME_PREMIUM": "7"})).be_result
    assert not {"BE_OVERTIME_PREMIUM_SHORT", "BE_OVERTIME_PREMIUM_UNVERIFIED"} & _codes(paid)


def test_paid_overtime_without_facts_blocks_and_limits_are_exceptions():
    assert _blocked(context(gross="1100", components={"SALARY": "1000", "OVERTIME_PREMIUM": "100"})) == \
        "BE_OVERTIME_FACTS_MISSING:OVERTIME_PREMIUM"
    long_day = _calc(context(be_working_time=_days(13))).be_result             # above the fake 12 h daily limit
    assert "BE_WORKING_TIME_LIMIT" in _codes(long_day)
    assert _calc(context()).be_result["trace"]["workingTime"] == {"facts": False}


# ── service: holidays hook, substitute days (D15), facts from attendance ────
@pytest.fixture
def world(db, monkeypatch):
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Hours BV", code="BEHOURS", admins=2, country="BE")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Test Worker", country_code="BE",
                               employment_type="Full-time", pay_frequency="Monthly", date_of_birth=date(1990, 1, 1))
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def test_the_holidays_hook_returns_signed_rows_only(world, monkeypatch):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    assert jurisdiction_hooks.call("BE", "pack_holidays", world.db, 2026) == []               # no active pack
    rate_map, slabs = build_pack()
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: BePack(rate_map, slabs, org, on))
    assert jurisdiction_hooks.call("BE", "pack_holidays", world.db, 2026) == [
        {"date": TEST_HOLIDAY, "name": "TEST ONLY holiday"}]
    assert jurisdiction_hooks.call("BE", "pack_holidays", world.db, 2027) == []               # none signed
    pending = build_pack(rates_over={"be_public_holidays": rate("be_public_holidays", text="SLAB_ROWS",
                                                                label="x [PENDING G1]")})
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: BePack(*pending, org, on))
    assert jurisdiction_hooks.call("BE", "pack_holidays", world.db, 2026) == []


def test_substitute_days_are_recorded_audited_and_used_as_working_time_facts(world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollAttendanceRecord, PayrollHoliday, TaxConfigurationAudit

    w = world
    with pytest.raises(BadRequestException, match="reason"):
        be.record_be_substitute_day(w.db, w.org, {"date": "2026-03-04", "replacesHoliday": "2026-03-01"}, w.a)
    out = be.record_be_substitute_day(w.db, w.org, {"date": "2026-03-04", "replacesHoliday": "2026-03-01",
                                                    "reason": "holiday on a Sunday"}, w.a)
    w.db.commit()
    row = w.db.get(PayrollHoliday, out["id"])
    assert (row.country, row.category) == ("BE", "Substitute")
    audit = w.db.query(TaxConfigurationAudit).filter_by(entity_type="be_substitute_day", entity_id=row.id).one()
    assert audit.reason == "holiday on a Sunday"
    with pytest.raises(BadRequestException, match="already"):
        be.record_be_substitute_day(w.db, w.org, {"date": "2026-03-04", "replacesHoliday": "2026-03-01",
                                                  "reason": "again"}, w.a)
    for day, hours in (("2026-03-02", "9"), ("2026-03-03", "9"), ("2026-03-04", "8.5")):
        w.db.add(PayrollAttendanceRecord(organization_id=w.org, employee_id=w.employee.id, date=date.fromisoformat(day),
                                         status="present", hours=hours))
    w.db.commit()
    facts = be._be_working_time_inputs(w.db, w.org, w.employee, (date(2026, 3, 1), date(2026, 3, 31)))
    assert facts["be_working_time"]["substituteDays"] == ["2026-03-04"]
    assert [d["hours"] for d in facts["be_working_time"]["days"]] == ["9", "9", "8.5"]
    assert facts["be_hours_paid"] == Decimal("26.5")
    assert be._be_working_time_inputs(w.db, w.org, w.employee, None) == {"be_working_time": None,
                                                                        "be_hours_paid": None}
    assert be.be_substitute_days(w.db, w.org, 2026) == [{"id": row.id, "date": "2026-03-04",
                                                        "name": "Substitute for 2026-03-01"}]


# ── Super Admin: sector wage scales on a DRAFT agreement (D3) ───────────────
def test_wage_scales_are_written_to_draft_agreements_only_and_audited(db):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import be_super_admin
    from app.modules.payroll.models import CollectiveAgreement, TaxConfigurationAudit

    agreement = CollectiveAgreement(organization_id=None, jurisdiction_country="BE", agreement_code="BE-PC-200-1.0",
                                    name="TEST ONLY committee", agreement_type="SECTOR", status="Draft")
    db.add(agreement)
    db.commit()
    payload = {"reason": "TEST ONLY scales", "wageScales": SCALES,
               "overtime": {"weekdayPct": "15", "sundayHolidayPct": "30"}}
    out = be_super_admin.set_agreement_wage_modules(db, agreement.id, payload, 1)
    db.commit()
    assert out["modules"]["wage_scales"][1]["monthlyMinimum"] == "1200"
    assert out["modules"]["overtime"] == {"weekdayPct": "15", "sundayHolidayPct": "30"}
    assert db.query(TaxConfigurationAudit).filter_by(entity_type="be_agreement_modules").count() == 1
    json.dumps(db.get(CollectiveAgreement, agreement.id).modules)
    for bad, message in (({"wageScales": []}, "non-empty"),
                         ({"wageScales": [{"functionClass": "B"}]}, "monthlyMinimum or an hourlyMinimum"),
                         ({"wageScales": [{"functionClass": "B", "monthlyMinimum": "900"}]}, "fullTimeWeeklyHours"),
                         ({"wageScales": [{"functionClass": "B", "hourlyMinimum": "-1"}]}, "above zero"),
                         ({"wageScales": [{"functionClass": "B", "hourlyMinimum": "9", "scheduleRegime": "FLEX"}]},
                          "scheduleRegime"),
                         ({"wageScales": SCALES[:1] * 2}, "same function class"),
                         ({"wageScales": SCALES, "overtime": {"weekdayPct": "15"}}, "both premiums"),
                         ({"wageScales": SCALES, "reason": ""}, "reason")):
        with pytest.raises(BadRequestException, match=message):
            be_super_admin.set_agreement_wage_modules(db, agreement.id, {"reason": "x", **bad}, 1)
    agreement.status = "Active"
    db.commit()
    with pytest.raises(BadRequestException, match="new version"):
        be_super_admin.set_agreement_wage_modules(db, agreement.id, payload, 1)
    other = CollectiveAgreement(organization_id=None, jurisdiction_country="SE", agreement_code="SE-X-1",
                                name="x", agreement_type="SECTOR", status="Draft")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundException):
        be_super_admin.set_agreement_wage_modules(db, other.id, payload, 1)

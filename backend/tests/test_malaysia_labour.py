"""Malaysia labour by territory (ZP-MY-ENG-001 Phase 6): the territory comes
only from the approved work assignment (MY-001 / MY-003), a transfer inside a
period needs the signed split rule, overtime is verified against approved
events with the territory's signed divisor and multipliers (MY-017), public
holidays come from signed federal + state rows, and leave entitlements from
the territory's signed tiers. LABOUR is its own obligation (MY-008). Values
are TEST rows (tests/_my_engine_helpers.py) — never certifying."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import malaysia
from app.modules.payroll.engine.countries.malaysia import MYCalculationBlockedError
from tests._my_engine_helpers import assignment, build_pack, ctx, profile

# Overtime counted in EPF / SOCSO / EIS / PCB normal and kept out of the
# overtime-rate base: TEST treatments standing in for the signed ones.
OT_TREATMENTS = {("EPF", "OVERTIME"): "INCLUDED", ("SOCSO", "OVERTIME"): "INCLUDED",
                 ("EIS", "OVERTIME"): "INCLUDED", ("PCB_NORMAL", "OVERTIME"): "INCLUDED",
                 ("PCB_ADDITIONAL", "OVERTIME"): "EXCLUDED", ("OT_RATE_BASE", "OVERTIME"): "EXCLUDED"}
BASIC = Decimal("2600")                       # 2600 / 26 / 8 = 12.50 an hour


def _event(ref, day_type, on, hours, daily="8"):
    return {"event_ref": ref, "day_type": day_type, "date": on.isoformat(), "hours": hours,
            "normal_daily_hours": daily}


def _ot_ctx(overtime, events, pack=None, profile_=None, basic=BASIC, **extra):
    pack = pack or build_pack(treatments=OT_TREATMENTS)
    return ctx(gross=basic + Decimal(overtime), pack=pack, profile_=profile_ or profile(rest_day="SUN"),
               components={"BASIC_SALARY": basic, "OVERTIME": Decimal(overtime)}, my_overtime_events=events,
               **extra)


def _blocked(context) -> MYCalculationBlockedError:
    with pytest.raises(MYCalculationBlockedError) as raised:
        malaysia.calculate(context)
    return raised.value


@pytest.fixture
def with_pcb(monkeypatch):
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb

    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("0.00"), "trace": {"stub": True}})


# ── territory (MY-001 / MY-003) ────────────────────────────────────────────
def test_no_assignment_blocks_labour_only(with_pcb):
    error = _blocked(ctx(my_assignment=None))
    assert set(error.blocked) == {"LABOUR"} and error.blocked["LABOUR"]["code"] == "MY_TERRITORY_UNRESOLVED"
    assert error.partial["obligations"]["EPF"]["employee"] == "550.00"            # national work is still done
    assert error.partial["minimumWage"]["reasons"] == ["labour territory not resolved"]


def test_a_holiday_state_outside_the_territory_is_a_conflict(with_pcb):
    error = _blocked(ctx(assignment_=assignment("SARAWAK", "SGR")))
    assert error.blocked["LABOUR"]["code"] == "MY_TERRITORY_CONFLICT"


def test_a_transfer_inside_the_period_needs_the_signed_split_rule(with_pcb):
    moved = [SimpleNamespace(labour_territory="PENINSULAR_LABUAN", holiday_state="SGR", status="ACTIVE",
                             effective_from=date(2026, 1, 1), effective_to=date(2026, 3, 15), id=1),
             SimpleNamespace(labour_territory="SABAH", holiday_state="SBH", status="ACTIVE",
                             effective_from=date(2026, 3, 16), effective_to=None, id=2)]
    error = _blocked(ctx(assignment_=moved[1], my_assignments=moved))
    assert error.blocked["LABOUR"]["code"] == "MY_TERRITORY_TRANSFER"
    signed = build_pack(overrides={"my_transfer_split_rule": {"text_value": "TERRITORY_AT_PERIOD_END"}})
    r = malaysia.calculate(ctx(pack=signed, assignment_=moved[1], my_assignments=moved))["my_result"]
    place = r["trace"]["labour"]["territory"]
    assert place["territory"] == "SABAH" and place["rule"] == "TERRITORY_AT_PERIOD_END"
    assert place["territoriesInPeriod"] == ["PENINSULAR_LABUAN", "SABAH"]
    earlier = malaysia.calculate(ctx(assignment_=moved[0], my_assignments=moved[:1]))["my_result"]
    assert earlier["trace"]["labour"]["territory"]["rule"] == "SINGLE_TERRITORY"


# ── overtime (MY-017) ──────────────────────────────────────────────────────
def test_overtime_matches_its_events_with_the_signed_rate_and_multipliers(with_pcb):
    events = [_event("T-1", "WORKDAY", date(2026, 3, 10), "4"), _event("T-2", "REST_DAY", date(2026, 3, 29), "2")]
    r = malaysia.calculate(_ot_ctx("125.00", events))["my_result"]
    overtime = r["trace"]["labour"]["overtime"]
    assert overtime["status"] == "MATCHED" and overtime["expected"] == "125.00"
    assert [(e["hourlyRate"], e["multiplier"], e["amount"]) for e in overtime["events"]] == \
        [("12.50", "1.5", "75.00"), ("12.50", "2", "50.00")]
    assert r["trace"]["minimumWage"]["basic"] == "2600.00"                         # overtime never props it up


def test_a_public_holiday_event_must_be_a_signed_holiday_of_the_state(with_pcb):
    ok = malaysia.calculate(_ot_ctx("37.50", [_event("H-1", "PUBLIC_HOLIDAY", date(2026, 5, 1), "1")]))
    assert ok["my_result"]["trace"]["labour"]["overtime"]["events"][0]["multiplier"] == "3"
    sabah_only = _blocked(_ot_ctx("37.50", [_event("H-2", "PUBLIC_HOLIDAY", date(2026, 5, 30), "1")]))
    assert sabah_only.blocked["LABOUR"]["code"] == "MY_OVERTIME_EVENT_INVALID:H-2"
    sabah = malaysia.calculate(_ot_ctx("37.50", [_event("H-3", "PUBLIC_HOLIDAY", date(2026, 5, 30), "1")],
                                       assignment_=assignment("SABAH", "SBH")))
    assert sabah["my_result"]["trace"]["labour"]["territory"]["territory"] == "SABAH"


@pytest.mark.parametrize("overtime, events, code", [
    ("125.00", [], "MY_OVERTIME_EVENTS_MISSING"),
    ("120.00", [_event("T-1", "WORKDAY", date(2026, 3, 10), "4"), _event("T-2", "REST_DAY", date(2026, 3, 29), "2")],
     "MY_OVERTIME_MISMATCH"),
    ("150.00", [_event("T-1", "WORKDAY", date(2026, 3, 10), "4"), _event("T-1", "WORKDAY", date(2026, 3, 11), "4")],
     "MY_OVERTIME_DOUBLE_EVENT:T-1"),
    ("50.00", [_event("T-3", "REST_DAY", date(2026, 3, 30), "2")], "MY_OVERTIME_EVENT_INVALID:T-3"),
    ("37.50", [_event("T-4", "PUBLIC_HOLIDAY", date(2026, 3, 10), "1")], "MY_OVERTIME_EVENT_INVALID:T-4"),
    ("75.00", [_event("T-5", "NIGHT", date(2026, 3, 10), "4")], "MY_OVERTIME_EVENT_INVALID:T-5"),
    ("75.00", [_event("T-6", "WORKDAY", date(2026, 3, 10), "4", daily="0")], "MY_OVERTIME_EVENT_INVALID:T-6"),
])
def test_overtime_without_valid_events_blocks_labour(overtime, events, code):
    error = _blocked(_ot_ctx(overtime, events))
    assert error.blocked["LABOUR"]["code"] == code and "EPF" in error.partial["obligations"]


def test_eligibility_by_wage_and_manual_work(with_pcb):
    events = [_event("T-1", "WORKDAY", date(2026, 3, 10), "4")]
    above = malaysia.calculate(_ot_ctx("999.00", events, basic=Decimal("5200")))["my_result"]
    assert above["trace"]["labour"]["overtime"]["status"] == "CONTRACTUAL"           # traced, not verified
    manual = _ot_ctx("150.00", events, basic=Decimal("5200"), profile_=profile(manual_worker=True))   # 25.00/h
    assert malaysia.calculate(manual)["my_result"]["trace"]["labour"]["overtime"]["status"] == "MATCHED"
    error = _blocked(_ot_ctx("75.00", events, profile_=profile(manual_worker=None)))
    assert error.blocked["LABOUR"]["code"] == "MY_FACT_MISSING:manual_worker"


def test_unsigned_divisor_or_multiplier_blocks_and_territories_differ(with_pcb):
    events = [_event("T-1", "WORKDAY", date(2026, 3, 10), "4")]
    pending = build_pack(treatments=OT_TREATMENTS,
                         overrides={"my_ot_rate_divisor_rule__PEN": {"text_value": "PENDING_G1"}})
    assert _blocked(_ot_ctx("75.00", events, pack=pending)).blocked["LABOUR"]["code"] == \
        "MY_POLICY_PENDING:my_ot_rate_divisor_rule__PEN"
    unsigned = build_pack(treatments=OT_TREATMENTS, unsigned=("my_ot_multiplier_workday__PEN",))
    assert _blocked(_ot_ctx("75.00", events, pack=unsigned)).blocked["LABOUR"]["code"] == \
        "MY_PACK_UNSIGNED:my_ot_multiplier_workday__PEN"
    sabah_pack = build_pack(treatments=OT_TREATMENTS, overrides={"my_ot_multiplier_workday__SBH": {"flat_amount": "2"}})
    sabah = malaysia.calculate(_ot_ctx("100.00", events, pack=sabah_pack, assignment_=assignment("SABAH", "SBH")))
    assert sabah["my_result"]["trace"]["labour"]["overtime"]["events"][0]["amount"] == "100.00"


# ── holidays and leave ─────────────────────────────────────────────────────
def _pack(**kw):
    from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack

    rate_map, slabs = build_pack(**kw)
    return MyPack(rate_map, slabs, 1, date(2026, 3, 31))


def test_holiday_calendars_are_national_plus_state():
    from app.modules.payroll.engine.jurisdictions.malaysia import holidays

    assert sorted(holidays.calendar(_pack(), "SGR", 2026)) == [date(2026, 5, 1), date(2026, 12, 11)]
    assert sorted(holidays.calendar(_pack(), "SBH", 2026)) == [date(2026, 5, 1), date(2026, 5, 30)]
    assert holidays.calendar(_pack(), "SGR", 2027) == {}
    _rate_map, slabs = build_pack()
    assert [h["date"] for h in holidays.national_rows(slabs, 2026)] == ["2026-05-01"]
    for row in slabs:
        if row["rule_type"] == "MY_PUBLIC_HOLIDAY":
            row["rate_label"] += " [PENDING G1]"
    assert holidays.national_rows(slabs, 2026) == []                              # unsigned is never seeded
    with pytest.raises(MYCalculationBlockedError, match="MY_PACK_UNSIGNED"):
        from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack

        holidays.calendar(MyPack({}, slabs, 1, date(2026, 3, 31)), "SGR", 2026)
    with pytest.raises(MYCalculationBlockedError, match="MY_TABLE_EMPTY"):
        holidays.calendar(_pack(holidays=()), "SGR", 2026)


def test_leave_entitlements_by_territory_and_service():
    from app.modules.payroll.engine.jurisdictions.malaysia import leave

    worker = profile(service_start=date(2023, 1, 15))
    out = leave.entitlements(_pack(), "PENINSULAR_LABUAN", worker, date(2026, 3, 31))
    assert (out["serviceYears"], out["annualDays"], out["sickDays"]) == (3, "12", "18")
    assert (out["hospitalisationDays"], out["maternityDays"], out["paternityDays"]) == ("60", "98", "7")
    assert leave.entitlements(_pack(), "SARAWAK", worker, date(2028, 1, 15))["annualDays"] == "16"
    with pytest.raises(MYCalculationBlockedError, match="MY_FACT_MISSING:service_start"):
        leave.entitlements(_pack(), "SABAH", profile(service_start=None), date(2026, 3, 31))
    pending = _pack(overrides={"my_sick_leave_tiers__SBH": {"text_value": "PENDING_G1"}})
    with pytest.raises(MYCalculationBlockedError, match="MY_POLICY_PENDING:my_sick_leave_tiers__SBH"):
        leave.entitlements(pending, "SABAH", worker, date(2026, 3, 31))


@pytest.mark.parametrize("text, ok", [("0:8,2:12,5:16", True), ("0:8.5", True), ("2:12", False),
                                      ("0:8,0:9", False), ("0:8,5:16,2:12", False), ("0:8.25", False),
                                      ("zero:8", False), ("", False)])
def test_leave_tier_format(text, ok):
    from app.modules.payroll.engine.jurisdictions.malaysia.leave import parse_tiers
    from app.modules.payroll.my_super_admin import _leave_tiers_problem

    assert (_leave_tiers_problem(text) is None) is ok
    if ok:
        assert parse_tiers(text)[0][0] == 0


def test_signing_vocabulary_covers_the_territorial_labour_policies():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.my_super_admin import check_rate_value

    check_rate_value("my_ot_rate_divisor_rule__SWK", "text_value", "MONTHLY_BASE_DIV_DAYS_DIV_DAILY_HOURS")
    check_rate_value("my_annual_leave_tiers__SBH", "text_value", "0:8,2:12,5:16")
    check_rate_value("my_transfer_split_rule", "text_value", "TERRITORY_AT_PERIOD_END")
    check_rate_value("my_ot_rate_days_divisor__PEN", "flat_amount", Decimal("26"))
    with pytest.raises(BadRequestException, match="YEARS:DAYS"):
        check_rate_value("my_annual_leave_tiers__SBH", "text_value", "eight days")

"""Belgium (ZP-BE-ENG-001) Block B2: holiday pay and absence (§16 holiday and
sickness / leave scenarios).

SYNTHETIC TEST ONLY content (tests/_be_engine_helpers.py): double holiday 10 %,
fund debit 10 %, guaranteed 10 days at 10 %, contract condition 5 months,
relapse window 3 weeks, manual bands 10 % / 5 %, birth leave 20 days of which 3
employer. Holiday and absence pay are VERIFIED, never topped up."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests._be_engine_helpers import PAY, context, records

JAN = date(2026, 1, 31)


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


def _double(paid, **holiday):
    return context(gross=str(1000 + paid), components={"SALARY": "1000", "HOLIDAY_PAY_DOUBLE": str(paid)},
                   be_exceptional_reference=Decimal("10000"), be_holiday={"monthsWorked": 12, **holiday})


# ── holiday pay: white-collar employer strategy (BE-025) ────────────────────
def test_white_collar_double_holiday_pay_is_verified_against_the_holiday_base():
    ok = _calc(_double(100)).be_result
    assert ok["be_holiday"] == {"strategy": "WHITE_COLLAR_EMPLOYER", "due": {"HOLIDAY_PAY_DOUBLE": "100.00"}}
    assert "BE_HOLIDAY_PAY_SHORT" not in _codes(ok)
    assert ok["accumulatorDeltas"]["HOLIDAY_DOUBLE_PAID"] == "100"
    short = _calc(_double(50)).be_result
    assert "BE_HOLIDAY_PAY_SHORT" in _codes(short)


def test_service_year_is_separate_from_the_taking_year_and_pro_rata():
    b = _calc(_double(50, monthsWorked=6)).be_result
    assert b["be_holiday"]["due"]["HOLIDAY_PAY_DOUBLE"] == "50.00"
    assert (b["trace"]["holiday"]["serviceYear"], b["trace"]["holiday"]["takingYear"]) == (2025, 2026)


def test_a_prior_employer_certificate_and_the_additional_holiday_advance_offset_the_double_pay():
    certificate = {"id": 1, "direction": "IN", "status": "APPROVED", "service_year": 2025, "double_pay_amount": "30"}
    with_prior = _calc(_ctx_with(_double(70), be_holiday_certificates=[certificate])).be_result
    assert with_prior["be_holiday"]["due"]["HOLIDAY_PAY_DOUBLE"] == "70.00"
    advanced = _calc(_double(80, advanceOutstanding="20")).be_result
    assert advanced["be_holiday"]["due"]["HOLIDAY_PAY_DOUBLE"] == "80.00"
    assert advanced["accumulatorDeltas"]["ADDITIONAL_HOLIDAY_ADVANCE"] == "-20"           # BE-026 offset consumed


def _ctx_with(ctx, **over):
    for key, value in over.items():
        setattr(ctx, key, value)
    return ctx


def test_additional_holidays_are_advanced_for_a_later_offset():
    b = _calc(context(be_holiday={"additionalDays": "2"})).be_result
    assert b["be_holiday"]["due"] == {"ADDITIONAL_HOLIDAY": "20.00"}
    assert b["accumulatorDeltas"]["ADDITIONAL_HOLIDAY_ADVANCE"] == "20.00"


def test_departure_holiday_pay_is_due_on_exit():
    b = _calc(context(be_holiday={"departure": {"monthsWorked": "6"}})).be_result
    assert b["be_holiday"]["due"]["DEPARTURE_HOLIDAY_PAY"] == "60.00"
    assert "BE_HOLIDAY_PAY_SHORT" in _codes(b)
    paid = _calc(context(gross="1060", components={"SALARY": "1000", "DEPARTURE_HOLIDAY_PAY": "60"},
                         be_exceptional_reference=Decimal("10000"),
                         be_holiday={"departure": {"monthsWorked": "6"}})).be_result
    assert "BE_HOLIDAY_PAY_SHORT" not in _codes(paid)


def test_the_wage_floor_is_never_the_holiday_base():
    """BE-028: a sector minimum of 1200 (breached) does not change the 1000 holiday base."""
    scales = [{"functionClass": "B", "seniorityFromMonths": 0, "monthlyMinimum": "1200", "fullTimeWeeklyHours": "38"}]
    ctx = _double(100)
    ctx.be_agreements = {30: dict(records()["be_agreements"][30], modules={"wage_scales": scales})}
    b = _calc(ctx).be_result
    assert "BE_MINIMUM_WAGE_BREACH" in _codes(b)
    assert b["be_holiday"]["due"]["HOLIDAY_PAY_DOUBLE"] == "100.00"
    assert b["trace"]["holiday"]["double"]["reference"] == "1000"


# ── holiday pay: manual-worker fund strategy (BE-025) ───────────────────────
def _manual(**over):
    return context(be_profile=dict(records()["be_profile"], worker_category="MANUAL"), **over)


def test_a_manual_worker_gets_no_employer_holiday_pay_and_the_fund_is_reconciled():
    paid = _calc(_ctx_with(_double(100), be_profile=dict(records()["be_profile"], worker_category="MANUAL"))).be_result
    assert paid["be_holiday"]["strategy"] == "MANUAL_FUND" and "BE_HOLIDAY_PAID_BY_FUND" in _codes(paid)
    fund = _calc(_manual(be_holiday={"reconcileFund": True, "priorYearBase": "1000", "fundDeclared": "90"})).be_result
    assert fund["obligationDeltas"]["HOLIDAY_FUND_ANNUAL_DEBIT"] == "100.00"
    assert "BE_HOLIDAY_FUND_MISMATCH" in _codes(fund)
    assert fund["be_holiday"]["due"] == {}


def test_a_category_change_inside_the_service_year_is_an_explicit_transition():
    history = [dict(records()["be_profile"], id=1, worker_category="EMPLOYEE", status="SUPERSEDED",
                    effective_from="2025-01-01", effective_to="2025-06-30"),
               dict(records()["be_profile"], id=2, worker_category="MANUAL", status="ACTIVE",
                    effective_from="2025-07-01", effective_to=None)]
    b = _calc(context(be_profile_history=history)).be_result
    assert "BE_HOLIDAY_CATEGORY_TRANSITION" in _codes(b)


# ── absence episodes (BE-029 .. BE-032) ─────────────────────────────────────
def _episode(eid, start, end, kind="SICKNESS", category="EMPLOYEE", **over):
    return {"id": eid, "kind": kind, "start_date": start, "end_date": end, "worker_category_at_start": category,
            "status": "ACTIVE", "different_cause": None, **over}


def test_white_collar_guaranteed_salary_days_and_external_days():
    ctx = context(gross="1050", components={"SALARY": "1000", "GUARANTEED_SALARY": "50"}, be_daily_rate=Decimal("50"),
                  be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20")])
    b = _calc(ctx).be_result
    assert (b["be_absence"]["employerDays"], b["be_absence"]["externalDays"]) == ("10", "9")
    assert b["be_absence"]["employerDue"] == "50.00" and b["accumulatorDeltas"]["GUARANTEED_SALARY_DAYS"] == "10"
    assert "BE_ABSENCE_PAY_SHORT" not in _codes(b)
    short = _calc(context(be_daily_rate=Decimal("50"), be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20")]))
    assert "BE_ABSENCE_PAY_SHORT" in _codes(short.be_result)
    unverified = _calc(context(be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20")])).be_result
    assert "BE_ABSENCE_PAY_UNVERIFIED" in _codes(unverified)


def test_a_short_fixed_term_white_collar_and_a_manual_worker_use_the_day_bands():
    short_contract = [dict(records()["be_classifications"][0], contract_type="FIXED_TERM",
                           contract_start_date="2026-01-01", contract_end_date="2026-03-31")]
    for ctx in (context(be_classifications=short_contract,
                        be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20")]),
                _manual(be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20", category="MANUAL")])):
        (episode,) = _calc(ctx).be_result["be_absence"]["episodes"]
        assert [(band["fromDay"], band["toDay"], band["pct"]) for band in episode["bands"]] == \
            [(1, 7, "10.00"), (8, 19, "5.00")]


def test_a_relapse_across_31_december_2025_and_1_january_2026_continues_the_count():
    """BE-030: the incapacity that ended 31 Dec 2025 is in the lookback; the new
    one starts 10 Jan 2026, inside the window, so the guaranteed days already
    used are not granted again."""
    first = _episode(1, "2025-12-01", "2025-12-31")
    relapse = _episode(2, "2026-01-10", "2026-01-25")
    b = _calc(context(pay_date=JAN, be_absence_episodes=[first, relapse])).be_result
    (episode,) = b["be_absence"]["episodes"]
    assert episode["relapseOf"] == 1 and episode["employerDays"] == "0"
    late = _episode(2, "2026-01-25", "2026-01-31")                       # outside the 3-week window
    fresh = _calc(context(pay_date=JAN, be_absence_episodes=[first, late])).be_result["be_absence"]["episodes"][0]
    assert fresh["relapseOf"] is None and fresh["employerDays"] == "7"


def test_a_declared_different_cause_starts_a_new_period_with_an_exception():
    first = _episode(1, "2025-12-01", "2025-12-31")
    other = _episode(2, "2026-01-10", "2026-01-25", different_cause=True)
    b = _calc(context(pay_date=JAN, be_absence_episodes=[first, other])).be_result
    assert b["be_absence"]["episodes"][0]["relapseOf"] is None and b["be_absence"]["employerDays"] == "10"
    assert "BE_ABSENCE_DIFFERENT_CAUSE" in _codes(b)


def test_rules_are_read_by_the_incapacity_start_date():
    """An episode that started before the pack window needs the rule in force
    THEN — the 2026 rows do not apply, so it blocks (fail closed)."""
    old = _episode(1, "2025-11-01", "2026-03-31")
    assert _blocked(context(be_absence_episodes=[old])) == "BE_ROW_MISSING:be_abs_relapse_window_weeks"


def test_maternity_suspends_the_salary_and_a_cba_top_up_is_an_overlay():
    plain = _calc(context(be_absence_episodes=[_episode(1, "2026-03-01", "2026-03-31", kind="MATERNITY")]))
    (episode,) = plain.be_result["be_absence"]["episodes"]
    assert episode["salarySuspended"] is True and episode["employerDays"] == "0"
    assert plain.be_result["be_absence"]["externalDays"] == "31"
    ctx = context(be_daily_rate=Decimal("10"), be_absence_episodes=[_episode(1, "2026-03-01", "2026-03-31",
                                                                            kind="MATERNITY")])
    ctx.be_agreements = {30: dict(records()["be_agreements"][30], modules={"topups": {"MATERNITY": "10"}})}
    topped = _calc(ctx).be_result
    # 31 days x 10 x 10 % = 31 (no absence rounding key exists, and rounding only comes from signed rows)
    assert topped["be_absence"]["employerDue"] == "31" and "BE_ABSENCE_PAY_SHORT" in _codes(topped)


def test_birth_leave_splits_employer_and_external_days():
    b = _calc(context(be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-06", kind="BIRTH_LEAVE")])).be_result
    assert (b["be_absence"]["employerDays"], b["be_absence"]["externalDays"]) == ("3", "2")


def test_external_benefits_never_reach_net_pay():
    with_absence = _calc(context(be_absence_episodes=[_episode(1, "2026-03-02", "2026-03-20")]))
    without = _calc(context())
    assert with_absence.net_pay == without.net_pay == Decimal("852.00")
    assert "external" not in json.dumps(with_absence.be_result["accumulatorDeltas"]).lower()


# ── service: episodes and certificates (four-eyes) ──────────────────────────
@pytest.fixture
def world(db):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Leave BV", code="BELEAVE", admins=2, country="BE")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Test Worker", country_code="BE")
    db.add(employee)
    db.commit()
    w = SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)
    row = be.record_be_worker_profile(db, w.org, employee.id, {"effective_from": "2025-01-01",
                                                               "worker_category": "EMPLOYEE"}, w.a, "hire")
    db.commit()
    be.approve_be_worker_profile(db, w.org, row.id, w.b)
    db.commit()
    return w


def test_episodes_record_dates_only_with_four_eyes_and_cancellation(world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be

    w = world
    with pytest.raises(BadRequestException, match="unknown field"):
        be.record_be_absence_episode(w.db, w.org, w.employee.id, {"kind": "SICKNESS", "start_date": "2026-03-02",
                                                                  "diagnosis": "x"}, w.a, "sick")
    row = be.record_be_absence_episode(w.db, w.org, w.employee.id, {"kind": "sickness", "start_date": "2026-03-02",
                                                                    "end_date": "2026-03-10",
                                                                    "certificate_ref": "TEST-REF"}, w.a, "sick")
    w.db.commit()
    assert (row.kind, row.worker_category_at_start, row.status) == ("SICKNESS", "EMPLOYEE", "DRAFT")
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        be.approve_be_absence_episode(w.db, w.org, row.id, w.a)
    w.db.rollback()
    assert be.approve_be_absence_episode(w.db, w.org, row.id, w.b).status == "ACTIVE"
    relapse = be.record_be_absence_episode(w.db, w.org, w.employee.id, {
        "kind": "SICKNESS", "start_date": "2026-03-20", "cause_link_id": row.id}, w.a, "relapse")
    assert relapse.cause_link_id == row.id
    with pytest.raises(BadRequestException, match="earlier episode"):
        be.record_be_absence_episode(w.db, w.org, w.employee.id, {"kind": "SICKNESS", "start_date": "2026-03-01",
                                                                  "cause_link_id": row.id}, w.a, "x")
    for bad, message in (({"kind": "FLU"}, "kind"), ({"end_date": "2026-03-01"}, "end_date"),
                         ({"different_cause": "maybe"}, "different_cause"),
                         ({"start_date": "2024-01-01"}, "worker profile")):
        with pytest.raises(BadRequestException, match=message):
            be.record_be_absence_episode(w.db, w.org, w.employee.id, {"kind": "SICKNESS",
                                                                      "start_date": "2026-03-02", **bad}, w.a, "x")
    cancelled = be.cancel_be_absence_episode(w.db, w.org, row.id, w.a, "entered twice")
    assert (cancelled.status, cancelled.cancelled_reason) == ("CANCELLED", "entered twice")


def test_holiday_certificates_are_immutable_after_approval(world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be

    w = world
    with pytest.raises(BadRequestException, match="prior employer"):
        be.record_be_holiday_certificate(w.db, w.org, w.employee.id, {"direction": "IN", "service_year": 2025},
                                         w.a, "hire")
    cert = be.record_be_holiday_certificate(w.db, w.org, w.employee.id, {
        "direction": "in", "service_year": "2025", "double_pay_amount": "30",
        "prior_employer_ref": "TEST ONLY prior employer"}, w.a, "hire")
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        be.approve_be_holiday_certificate(w.db, w.org, cert.id, w.a)
    w.db.rollback()
    be.approve_be_holiday_certificate(w.db, w.org, cert.id, w.b)
    with pytest.raises(BadRequestException, match="immutable"):
        be.approve_be_holiday_certificate(w.db, w.org, cert.id, w.b)
    correction = be.record_be_holiday_certificate(w.db, w.org, w.employee.id, {
        "direction": "IN", "service_year": 2025, "double_pay_amount": "35",
        "prior_employer_ref": "TEST ONLY prior employer", "supersedes_id": cert.id}, w.a, "corrected certificate")
    w.db.commit()
    be.approve_be_holiday_certificate(w.db, w.org, correction.id, w.b)
    assert (cert.status, correction.status, str(cert.double_pay_amount)) == ("SUPERSEDED", "APPROVED", "30.00")
    with pytest.raises(BadRequestException, match="negative"):
        be.record_be_holiday_certificate(w.db, w.org, w.employee.id, {"direction": "OUT", "service_year": 2025,
                                                                      "simple_pay_amount": "-1"}, w.a, "x")


def test_calc_inputs_carry_the_service_year_facts_from_the_ledger(world):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollBeAccumulatorEntry

    w = world
    entries = [PayrollBeAccumulatorEntry(organization_id=w.org, employee_id=w.employee.id, year=2025,
                                         accumulator="HOLIDAY_PAY_BASE", pay_date=date(2025, month, 28),
                                         amount=Decimal("1000"), entry_kind="RUN", payslip_item_id=900 + month)
               for month in (10, 11, 12)]
    entries.append(PayrollBeAccumulatorEntry(organization_id=w.org, employee_id=w.employee.id, year=2025,
                                             accumulator="ADDITIONAL_HOLIDAY_ADVANCE", pay_date=date(2025, 12, 28),
                                             amount=Decimal("20"), entry_kind="RUN", payslip_item_id=950))
    w.db.add_all(entries)
    w.db.commit()
    facts = be._be_holiday_absence_inputs(w.db, w.org, w.employee, PAY)
    assert facts["be_holiday"] == {"serviceYear": 2025, "priorYearBase": "3000.00", "advanceOutstanding": "20.00",
                                   "monthsWorked": 3}
    assert facts["be_profile_history"][0]["worker_category"] == "EMPLOYEE"

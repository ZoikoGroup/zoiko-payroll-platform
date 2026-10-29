"""Mexico Phase 11c — the dates on which approved overtime was worked, and the
CFDI HorasExtra node built from them (S4 pp. 48, 51–53). Recording stays
four-eyes; without the dates a receipt with overtime (019) stays refused.
SYNTHETIC data; SAT codes read from the pinned set."""

import copy
from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_mexico_cfdi_builder import GOLDEN, SET, _parse, _refusal


def _R():
    from app.modules.payroll import mexico_run_service

    return mexico_run_service


def _world(db, monkeypatch, code):
    from tests import _mx_run_helpers as rh

    return rh.world(db, monkeypatch, code=code)


def test_overtime_dates_are_recorded_validated_and_approved_four_eyes(db, monkeypatch):
    from app.core.exceptions import BadRequestException, ForbiddenException

    w = _world(db, monkeypatch, "MXOT1")
    R, emp, week = _R(), w.employee.id, date(2026, 6, 1)
    base = {"week_start": week, "ordinary_hours": "40", "overtime_hours": "6", "sundays_worked": 0,
            "rest_days_worked": 0, "evidence_document_id": 1}
    for dates, message in (([date(2026, 6, 8)], "inside the recorded week"),
                           ([date(2026, 6, 2), date(2026, 6, 2)], "must not repeat")):
        with pytest.raises(BadRequestException, match=message):
            R.record_hours(db, w.org.id, emp, {**base, "overtime_dates": dates}, w.users[0].id)
    with pytest.raises(BadRequestException, match="only with overtime hours"):
        R.record_hours(db, w.org.id, emp, {**base, "overtime_hours": "0", "overtime_dates": [week]}, w.users[0].id)
    row = R.record_hours(db, w.org.id, emp, {**base, "overtime_dates": [date(2026, 6, 3), date(2026, 6, 2)]},
                         w.users[0].id)
    assert row["overtimeDates"] == ["2026-06-02", "2026-06-03"] and row["status"] == "DRAFT"
    with pytest.raises(ForbiddenException):
        R.approve_hours(db, w.org.id, row["id"], w.users[0].id)                 # the recorder cannot approve
    assert R.approve_hours(db, w.org.id, row["id"], w.users[1].id)["status"] == "APPROVED"
    assert R.list_hours(db, w.org.id, emp)[0]["overtimeDates"] == ["2026-06-02", "2026-06-03"]
    plain = R.record_hours(db, w.org.id, emp, {**base, "week_start": date(2026, 6, 8)}, w.users[0].id)
    assert plain["overtimeDates"] == []                                          # still optional


def test_the_engine_carries_the_dates_into_each_overtime_week():
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    class Content:                                                              # SYNTHETIC tier content
        values = {"mx_overtime_double_weekly_max_hours": D("9"), "mx_overtime_double_multiplier": D("2"),
                  "mx_overtime_triple_multiplier": D("3")}

        def has(self, key):
            return key in self.values

        def amount(self, key):
            return self.values[key]

    out = labor.hour_lines(Content(), {"weeks": [{"overtime_hours": D("6"), "overtime_dates": ["2026-06-02"]},
                                                 {"overtime_hours": D("11"), "overtime_dates": []}],
                                       "hourly_rate": D("50"), "overtime_code": "OT"}, {}, D("400"))
    w1, w2 = out["overtime"]
    assert (w1["dates"], w1["first_tier_hours"], w1["second_tier_hours"], w1["first_tier_amount"]) == \
        (["2026-06-02"], D("6"), D("0"), D("600"))
    assert (w2["dates"], w2["second_tier_hours"]) == ([], D("2"))


def _result(weeks):
    return {"labor": {"overtime": weeks}}


def test_horas_extra_is_built_from_the_dates_only_when_it_can_be_exact():
    from app.modules.payroll import mexico_cfdi_input as I
    from app.modules.payroll import mexico_cfdi_schema as S

    on = date(2026, 6, 15)
    double = next(e[0] for e in S.catalogs(SET)["c_TipoHoras"]["entries"] if e[1] == "Dobles")
    ok = I._overtime_detail(SET, _result([
        {"dates": ["2026-06-02", "2026-06-03"], "first_tier_hours": "5.4", "second_tier_hours": "0",
         "first_tier_amount": "540.00"},
        {"dates": ["2026-06-09"], "first_tier_hours": "2", "second_tier_hours": "0", "first_tier_amount": "200.00"}]),
        on)
    assert ok == {"overtime": [{"days": 3, "type": double, "hours": 7, "amount": D("740.00")}]}   # 7.4 h -> 7 (S4 p. 52)
    missing = I._overtime_detail(SET, _result([{"dates": [], "first_tier_hours": "2", "second_tier_hours": "0"}]), on)
    assert "not recorded" in missing["overtimeRefusal"]
    triple = I._overtime_detail(SET, _result([{"dates": ["2026-06-02"], "first_tier_hours": "9",
                                               "second_tier_hours": "2"}]), on)
    assert "triple-rate" in triple["overtimeRefusal"]


def _with_overtime(detail):
    doc = copy.deepcopy(GOLDEN)
    line = {"satCode": "019", "key": "OT1", "concept": "Horas extra", "taxed": "740.00", "exempt": "0", **detail}
    doc["perceptions"] = doc["perceptions"] + [line]
    return doc


def test_the_builder_emits_horas_extra_and_keeps_019_refused_without_the_dates():
    from app.modules.payroll import mexico_cfdi_schema as S

    double = next(e[0] for e in S.catalogs(SET)["c_TipoHoras"]["entries"] if e[1] == "Dobles")
    root = _parse(__import__("app.modules.payroll.mexico_cfdi_xml", fromlist=["x"]).build(
        _with_overtime({"overtime": [{"days": 3, "type": double, "hours": 7, "amount": D("740.00")}]})))
    from lxml import etree

    (node,) = [e for e in root.iter() if etree.QName(e).localname == "HorasExtra"]
    assert (node.get("Dias"), node.get("TipoHoras"), node.get("HorasExtra"), node.get("ImportePagado")) == \
        ("3", double, "7", "740.00")
    assert etree.QName(node.getparent()).localname == "Percepcion" and node.getparent().get("TipoPercepcion") == "019"
    exc = _refusal(_with_overtime({}))
    assert any("HorasExtra" in t and "dates" in t for r, t in exc.reasons if r == "R-DETAIL-NODE")
    exc = _refusal(_with_overtime({"overtimeRefusal": "a week has triple-rate hours"}))
    assert any("triple-rate" in t for _, t in exc.reasons)

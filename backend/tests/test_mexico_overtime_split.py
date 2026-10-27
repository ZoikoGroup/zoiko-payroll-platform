"""Completion W6-1 (gap register A11): triple-rate overtime on the CFDI. The
employer records, per date, the hours paid at the double and at the triple
rate (LFT Art. 68 prices the hours beyond the weekly maximum at triple but does
not say which days they fell on); the HorasExtra nodes count the days of each
type (S4 p. 51) and must agree with the calculation's weekly tiers.
SYNTHETIC data; SAT codes read from the pinned set."""

import copy
from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_mexico_cfdi_builder import GOLDEN, SET, _parse
from tests.test_mexico_overtime_dates import _R, _result, _world


def _codes():
    from app.modules.payroll import mexico_cfdi_schema as S

    entries = S.catalogs(SET)["c_TipoHoras"]["entries"]
    return (next(e[0] for e in entries if e[1] == "Dobles"), next(e[0] for e in entries if e[1] == "Triples"))


def test_hours_per_date_are_validated_and_stored(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    w = _world(db, monkeypatch, "MXOS1")
    R, emp, week = _R(), w.employee.id, date(2026, 6, 1)
    base = {"week_start": week, "ordinary_hours": "40", "overtime_hours": "11", "sundays_worked": 0,
            "rest_days_worked": 0, "evidence_document_id": 1}
    split = [{"date": date(2026, 6, 3), "double": "6", "triple": "2"}, {"date": date(2026, 6, 2), "double": "3",
                                                                        "triple": "0"}]
    for data, message in (
            ({"overtime_by_date": split, "overtime_dates": [date(2026, 6, 2)]}, "not both"),
            ({"overtime_by_date": [{**split[0], "double": "5"}, split[1]]}, "add up to the week's overtime hours"),
            ({"overtime_by_date": [{**split[0], "double": "0", "triple": "0"}, split[1]]}, "not both zero"),
            ({"overtime_by_date": [{**split[0], "triple": "-1"}, split[1]]}, "zero or more"),
            ({"overtime_by_date": [{**split[0], "date": date(2026, 6, 8)}, split[1]]}, "inside the recorded week"),
            ({"overtime_by_date": [split[0], {**split[1], "date": date(2026, 6, 3)}]}, "must not repeat")):
        with pytest.raises(BadRequestException, match=message):
            R.record_hours(db, w.org.id, emp, {**base, **data}, w.users[0].id)
    row = R.record_hours(db, w.org.id, emp, {**base, "overtime_by_date": split}, w.users[0].id)
    assert row["overtimeDates"] == [{"date": "2026-06-02", "double": "3", "triple": "0"},
                                    {"date": "2026-06-03", "double": "6", "triple": "2"}]


def test_the_engine_carries_the_split_into_its_weekly_tiers():
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    class Content:                                                              # SYNTHETIC tier content
        values = {"mx_overtime_double_weekly_max_hours": D("9"), "mx_overtime_double_multiplier": D("2"),
                  "mx_overtime_triple_multiplier": D("3")}

        def has(self, key):
            return key in self.values

        def amount(self, key):
            return self.values[key]

    split = [{"date": "2026-06-02", "double": "3", "triple": "0"}, {"date": "2026-06-03", "double": "6", "triple": "2"}]
    (week,) = labor.hour_lines(Content(), {"weeks": [{"overtime_hours": D("11"), "overtime_dates": split}],
                                           "hourly_rate": D("50"), "overtime_code": "OT"}, {}, D("400"))["overtime"]
    assert (week["first_tier_hours"], week["second_tier_hours"], week["dates"]) == (D("9"), D("2"), split)
    assert (week["first_tier_amount"], week["amount"]) == (D("900"), D("1200"))      # 9 x 50 x 2; + 2 x 50 x 3


def test_horas_extra_has_a_double_and_a_triple_node_with_their_own_days():
    from app.modules.payroll import mexico_cfdi_input as I

    double, triple = _codes()
    on = date(2026, 6, 15)
    weeks = [{"week": 1, "dates": [{"date": "2026-06-02", "double": "3", "triple": "0"},
                                   {"date": "2026-06-03", "double": "6", "triple": "2"}],
              "first_tier_hours": "9", "second_tier_hours": "2", "first_tier_amount": "900.00", "amount": "1200.00"},
             {"week": 2, "dates": ["2026-06-09"], "first_tier_hours": "2", "second_tier_hours": "0",
              "first_tier_amount": "200.00", "amount": "200.00"}]                 # a dates-only week (Phase 11c)
    assert I._overtime_detail(SET, _result(weeks), on) == {"overtime": [
        {"days": 3, "type": double, "hours": 11, "amount": D("1100.00")},
        {"days": 1, "type": triple, "hours": 2, "amount": D("300.00")}]}
    mismatch = copy.deepcopy(weeks)
    mismatch[0]["dates"][1]["triple"] = "1"
    mismatch[0]["dates"][1]["double"] = "7"
    refusal = I._overtime_detail(SET, _result(mismatch), on)["overtimeRefusal"]
    assert "do not match the calculation's weekly tiers" in refusal
    dates_only = I._overtime_detail(SET, _result([{**weeks[0], "dates": ["2026-06-02", "2026-06-03"]}]), on)
    assert "record the double and triple hours per date" in dates_only["overtimeRefusal"]


def test_the_receipt_with_both_nodes_is_valid_against_the_xsd():
    from lxml import etree

    from app.modules.payroll import mexico_cfdi_xml as X

    double, triple = _codes()
    doc = copy.deepcopy(GOLDEN)
    doc["perceptions"] = doc["perceptions"] + [{
        "satCode": "019", "key": "OT1", "concept": "Horas extra", "taxed": "1400.00", "exempt": "0",
        "overtime": [{"days": 3, "type": double, "hours": 11, "amount": D("1100.00")},
                     {"days": 1, "type": triple, "hours": 2, "amount": D("300.00")}]}]
    nodes = [e for e in _parse(X.build(doc)).iter() if etree.QName(e).localname == "HorasExtra"]
    assert [(n.get("TipoHoras"), n.get("Dias"), n.get("HorasExtra"), n.get("ImportePagado")) for n in nodes] == \
        [(double, "3", "11", "1100.00"), (triple, "1", "2", "300.00")]

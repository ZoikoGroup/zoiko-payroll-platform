"""Completion W6-2 (gap register C11, DECISIONS_PENDING D-21): the 830
Chihuahua c_CodigoPostal rows labelled "Tiempo del Centro en Frontera" give
winter -6 / summer -7, which is not one hour ahead. Each reading the G1 owner
may choose is built behind TIMEZONE_INCONSISTENT_ROW_READING; undecided, the
place of issue stays refused. Read from the pinned SAT set."""

from datetime import datetime, timezone

import pytest

from tests.test_mexico_cfdi_builder import SET

TZ = "Referencias del Huso Horario/"


def _I():
    from app.modules.payroll import mexico_cfdi_input

    return mexico_cfdi_input


def _chh_border():
    from app.modules.payroll import mexico_cfdi_schema as S

    rows = {e[0]: e[4] for e in S.catalogs(SET)["c_CodigoPostal"]["entries"]}
    return next(code for code, a in rows.items() if a.get(TZ + "Mes_Inicio_Horario_Verano")
                and a[TZ + "Diferencia_Horaria_Verano"] != a[TZ + "Diferencia_Horaria_Invierno"] + 1)


def test_undecided_the_place_of_issue_is_refused_naming_d21():
    from app.modules.payroll.engine.countries.mexico import MXBlock

    assert _I().TIMEZONE_INCONSISTENT_ROW_READING is None
    with pytest.raises(MXBlock) as exc:
        _I().local_issue_time(SET, _chh_border(), datetime(2026, 7, 1, 12, tzinfo=timezone.utc))
    assert exc.value.key == "MX_CFDI_TIMEZONE_RULE_INVALID" and "D-21" in exc.value.reason


@pytest.mark.parametrize("reading,july,january", [
    ("SAME_LABEL", datetime(2026, 7, 1, 7), datetime(2026, 1, 15, 6)),     # COA / NLE / TAM rows: -6 / -5
    ("SWAPPED", datetime(2026, 7, 1, 6), datetime(2026, 1, 15, 5)),        # -7 winter / -6 summer
])
def test_each_reading_gives_a_consistent_local_time(monkeypatch, reading, july, january):
    I = _I()
    monkeypatch.setattr(I, "TIMEZONE_INCONSISTENT_ROW_READING", reading)
    code = _chh_border()
    assert I.local_issue_time(SET, code, datetime(2026, 7, 1, 12, tzinfo=timezone.utc)) == july
    assert I.local_issue_time(SET, code, datetime(2026, 1, 15, 12, tzinfo=timezone.utc)) == january


def test_an_unknown_reading_is_refused(monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    I = _I()
    monkeypatch.setattr(I, "TIMEZONE_INCONSISTENT_ROW_READING", "GUESS")
    with pytest.raises(MXBlock) as exc:
        I.local_issue_time(SET, _chh_border(), datetime(2026, 7, 1, 12, tzinfo=timezone.utc))
    assert exc.value.key == "MX_RULE_UNRECOGNISED"


def test_consistent_rows_are_unaffected_by_the_switch(monkeypatch):
    I = _I()
    before = I.local_issue_time(SET, "21000", datetime(2026, 7, 1, 12, tzinfo=timezone.utc))      # BCN, own DST rule
    monkeypatch.setattr(I, "TIMEZONE_INCONSISTENT_ROW_READING", "SWAPPED")
    assert I.local_issue_time(SET, "21000", datetime(2026, 7, 1, 12, tzinfo=timezone.utc)) == before

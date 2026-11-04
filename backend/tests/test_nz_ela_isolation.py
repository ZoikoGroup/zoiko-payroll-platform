"""Employment Leave Act 2026 isolation harness (ZP-NZ-ENG-001 Phase 6,
AC-NZ-08): the NZ-ELA-2028 pack is never selected for a payday before
6 August 2028 — even if someone forced it Active — and cannot be activated
early. The Holidays Act engine keeps reading the 2026-27 rows until then."""
from datetime import date

import pytest

from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.models import JurisdictionPack

ELA_ID = content.NZ_ELA_2028[0]


@pytest.fixture()
def packs(db):
    nzs.seed_nz_pack(db)
    rows = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "NZ").all()
    for pack in rows:                                       # the worst case: both forced Active
        pack.status = "Active"
    db.commit()
    return {p.pack_id: p for p in rows}


def _months(first: date, last: date):
    on = first
    while on <= last:
        yield on
        on = date(on.year + (on.month == 12), on.month % 12 + 1, 1)


def test_ela_pack_never_resolves_before_2028_08_06(db, packs):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    resolved = []
    for on in list(_months(date(2026, 4, 1), date(2028, 8, 1))) + [date(2028, 8, 5)]:
        try:
            _rates, _slabs, pack = resolve_tax_configuration(db, "NZ", payroll_date=on)
        except Exception:
            continue                                         # no pack in force is fine; ELA must not appear
        assert pack is None or pack.pack_id != ELA_ID, on
        resolved.append(getattr(pack, "pack_id", None))
    assert "NZ-PAYROLL-2026-27" in resolved                  # the harness really resolves packs


def test_calc_inputs_never_select_ela(db, packs):
    for on in (date(2026, 4, 1), date(2027, 3, 31), date(2027, 4, 1), date(2028, 8, 5)):
        _rate_map, _slabs, pack = nzs._nz_pack_in_force(db, on)
        assert pack is None or pack.pack_id != ELA_ID, on


def test_ela_pack_activation_refused(db, packs):
    ela = packs[ELA_ID]
    for today in (date(2026, 11, 4), date(2028, 8, 5)):
        refusal = nzs.nz_pack_activation_refusal(db, ela, today=today)
        assert refusal and "2028-08-06" in refusal
    assert "no signed content" in nzs.nz_pack_activation_refusal(db, ela, today=date(2028, 8, 6))


def test_holidays_act_rules_still_used_on_2028_08_05():
    """No Holidays Act content row ends before the ELA date: the leave rules
    in force on 5 August 2028 are still the Holidays Act ones."""
    holiday_keys = [row for row in content.NZ_SCALAR_CONTENT if row[0].startswith("nz_hol_")]
    assert holiday_keys
    assert all(row[9] is None or row[9] >= date(2028, 8, 5) for row in holiday_keys)
    assert all(row[8] is None or row[8] < content.ELA_EARLIEST_EFFECTIVE for row in holiday_keys)

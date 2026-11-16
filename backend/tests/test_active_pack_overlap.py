"""
tests/test_active_pack_overlap.py
---------------------------------
P3c (2026-11-16): the "no two overlapping Active tax packs" check on
activation. The read-only production audit of 2026-11-14 found two Active,
in-force US Maine packs; the earlier check missed an Active pack with no
Effective From, treated "" and NULL state / regime as different, and ignored
locality.
"""

from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import JurisdictionPack

MAKER, CHECKER = 101, 202


def _pack(db, pack_id, status="Draft", *, state=None, locality=None, regime=None,
          start=date(2026, 1, 1), end=None):
    row = JurisdictionPack(
        pack_id=pack_id, version="1.0", jurisdiction_country="IN", jurisdiction_state=state,
        jurisdiction_locality=locality, tax_regime=regime, pack_type="tax", status=status,
        effective_from=start, effective_to=end, updated_by_id=MAKER, approved_by_id=CHECKER,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _activate(db, row):
    return service.set_jurisdiction_pack_status(db, row.id, "Active", actor_id=CHECKER)


def test_active_pack_without_effective_from_blocks_an_overlapping_one(db):
    _pack(db, "OPEN-START", "Active", start=None)
    with pytest.raises(BadRequestException, match="already Active"):
        _activate(db, _pack(db, "NEW"))


def test_blank_and_null_state_are_the_same_scope(db):
    _pack(db, "BLANK-STATE", "Active", state="")
    with pytest.raises(BadRequestException, match="already Active"):
        _activate(db, _pack(db, "NULL-STATE", state=None))


def test_blank_and_null_regime_are_the_same_scope(db):
    _pack(db, "BLANK-REGIME", "Active", regime="")
    with pytest.raises(BadRequestException, match="already Active"):
        _activate(db, _pack(db, "NULL-REGIME"))


def test_a_city_pack_does_not_clash_with_its_states_pack(db):
    _pack(db, "STATE", "Active", state="Karnataka")
    assert _activate(db, _pack(db, "CITY", state="Karnataka", locality="Bengaluru")).status == "Active"


def test_two_packs_for_the_same_city_still_clash(db):
    _pack(db, "CITY-1", "Active", state="Karnataka", locality="Bengaluru")
    with pytest.raises(BadRequestException, match="already Active"):
        _activate(db, _pack(db, "CITY-2", state="Karnataka", locality="Bengaluru"))


def test_back_to_back_periods_can_both_be_active(db):
    _pack(db, "H1", "Active", end=date(2026, 6, 30))
    assert _activate(db, _pack(db, "H2", start=date(2026, 7, 1))).status == "Active"

"""
tests/test_compliance_pack_health.py
------------------------------------
P3a (2026-11-16): read-only pack health check for the Super Admin
Compliance page - the same checks as the production audit of 2026-11-14.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

TODAY = date.today()


def _pack(db, pack_id, country="IN", status="Active", *, state=None, start=None, end=None, **kw):
    row = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=country, jurisdiction_state=state,
                           pack_type="tax", status=status, effective_from=start, effective_to=end, **kw)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _slab(pack, min_amount="0", rate="10", label="10%"):
    return TaxSlab(organization_id=None, jurisdiction_country=pack.jurisdiction_country, jurisdiction_pack_id=pack.id,
                   min_amount=Decimal(min_amount), rate_pct=Decimal(rate), rate_label=label, tax_formula="")


def _rate(pack, key, label=None):
    return ContributionRate(organization_id=None, jurisdiction_country=pack.jurisdiction_country,
                            jurisdiction_pack_id=pack.id, component_key=key, label=label or key,
                            employee_share="1%", employer_share="1%", total="2%")


def test_active_pack_in_force_is_reported_with_its_contents(db):
    _pack(db, "OLD", start=TODAY - timedelta(days=400), end=TODAY - timedelta(days=1))
    current = _pack(db, "CUR", start=TODAY - timedelta(days=10), approved_by_id=7)
    db.add_all([_slab(current), _slab(current, "1000", "20", "PENDING sign-off"), _rate(current, "pf")])
    db.commit()

    (row,) = service.get_compliance_pack_health(db)["countries"]
    active = row["activePack"]
    assert (active["id"], active["inForceToday"], active["approved"]) == (current.id, True, True)
    assert (active["rates"], active["slabs"], active["pendingSignOff"]) == (1, 2, 1)
    assert row["statusCounts"] == {"Active": 2}


def test_overlapping_active_packs_are_listed_but_back_to_back_periods_are_not(db):
    _pack(db, "H1", start=date(2026, 1, 1), end=date(2026, 6, 30))
    _pack(db, "H2", start=date(2026, 7, 1), end=date(2026, 12, 31))
    a = _pack(db, "ME-A", country="US", state="ME", start=date(2026, 1, 1))
    b = _pack(db, "ME-B", country="US", state="ME", start=None)  # no start date: open-ended
    overlaps = service.get_compliance_pack_health(db)["issues"]["overlappingActive"]
    assert [(o["country"], o["state"], [p["id"] for p in o["packs"]]) for o in overlaps] == [("US", "ME", [a.id, b.id])]


def test_exact_copy_rows_are_counted_per_pack(db):
    pack = _pack(db, "UK-P", country="UK")
    db.add_all([_slab(pack), _slab(pack), _slab(pack), _slab(pack, "500"),  # 2 extra copies, 1 distinct
                _rate(pack, "ni"), _rate(pack, "ni"), _rate(pack, "ni", label="NI (other)")])  # 1 extra copy
    db.commit()
    (dup,) = service.get_compliance_pack_health(db)["issues"]["duplicateRows"]
    assert (dup["id"], dup["extraSlabRows"], dup["extraRateRows"]) == (pack.id, 2, 1)


def test_country_with_packs_but_no_active_country_pack_is_flagged(db):
    _pack(db, "JM-1", country="JM", status="Approved")
    _pack(db, "IN-KA", country="IN", state="Karnataka")  # state pack only
    _pack(db, "UK-1", country="UK")
    assert service.get_compliance_pack_health(db)["issues"]["noActivePack"] == ["IN", "JM"]


def test_health_check_changes_nothing(db):
    pack = _pack(db, "SAFE")
    db.add_all([_slab(pack), _slab(pack)])
    db.commit()
    service.get_compliance_pack_health(db)
    assert db.query(TaxSlab).count() == 2 and db.query(JurisdictionPack).one().status == "Active"

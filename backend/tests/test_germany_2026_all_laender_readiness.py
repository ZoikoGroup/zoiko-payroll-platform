"""
tests/test_germany_2026_all_laender_readiness.py
---------------------------------------------------
Proves the Germany 2026 "all 16 Länder" jurisdiction configuration (see
scripts/seed_germany_2026_all_jurisdictions.py) is correct, idempotent,
and correctly isolated/centralized — against an isolated in-memory
SQLite database, never the shared dev Postgres.

Reuses the real script module (GERMAN_LAENDER, _land_pack_id,
_resolve_federal_pack, _seed_one_land) rather than re-implementing its
logic here, so these tests exercise the actual production code path.
`scripts._actor_authorization`'s Super-Admin-role check is script-level
only (enforced in main(), not inside _seed_one_land/service.py), so tests
pass plain SimpleNamespace(id=...) stand-ins for maker/checker — exactly
like every other test in this module passes bare actor_id integers to
service.py's maker-checker functions.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.engine import tax_resolver
from app.modules.payroll.models import JurisdictionPack
from app.modules.payroll.schemas import JurisdictionPackUpsert

from scripts import seed_germany_2026_all_jurisdictions as land_seed

MAKER = SimpleNamespace(id=101)
CHECKER = SimpleNamespace(id=202)


def _make_federal_pack(db, pack_id="DE-PAYROLL-CY2026-V1"):
    pack = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId=pack_id, jurisdictionCountry="DE", jurisdictionState=None, packType="tax",
            version="1.0", status="Draft", effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31),
            taxYear="2026", currency="EUR",
        ), actor_id=MAKER.id,
    )
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER.id)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)


def _seed_all_laender(db, federal_pack):
    return [
        land_seed._seed_one_land(db, service, JurisdictionPackUpsert, code, name, federal_pack, MAKER, CHECKER)
        for code, name in land_seed.GERMAN_LAENDER
    ]


# ══════════════════════════════════════════════════════════════════════════
# A/B/C. Federal configuration exists; exactly 16 Länder; each has a valid
# Active pack.
# ══════════════════════════════════════════════════════════════════════════

def test_exactly_16_laender_defined(db):
    assert len(land_seed.GERMAN_LAENDER) == 16
    assert len({code for code, _ in land_seed.GERMAN_LAENDER}) == 16  # no duplicate codes
    assert len({name for _, name in land_seed.GERMAN_LAENDER}) == 16  # no duplicate names


def test_federal_and_all_16_laender_packs_active(db):
    federal = _make_federal_pack(db)
    results = _seed_all_laender(db, federal)

    assert federal.status == "Active"
    assert federal.jurisdiction_state is None

    assert len(results) == 16
    for r in results:
        assert r["status"] == "Active", f"{r['land_name']} did not activate"
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == r["id"]).first()
        assert pack.jurisdiction_country == "DE"
        assert pack.jurisdiction_state == r["land_code"]
        assert pack.parent_pack_id == federal.id
        assert pack.pack_type == "tax"


# ══════════════════════════════════════════════════════════════════════════
# G. No duplicate ACTIVE jurisdiction configuration for the same Land +
# overlapping effective dates (same guard proven for country-level DE in
# test_germany_compliance_pack_framework.py, exercised here per-Land).
# ══════════════════════════════════════════════════════════════════════════

def test_overlapping_active_land_packs_rejected(db):
    federal = _make_federal_pack(db)
    _seed_all_laender(db, federal)

    # A second, overlapping v1.1 pack for the SAME Land must not be
    # allowed to go Active alongside the existing v1.0.
    dup = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId=land_seed._land_pack_id("DE-BW"), jurisdictionCountry="DE", jurisdictionState="DE-BW",
            packType="tax", version="1.1", status="Draft",
            effectiveFrom=date(2026, 6, 1), effectiveTo=date(2026, 12, 31), taxYear="2026", currency="EUR",
        ), actor_id=MAKER.id,
    )
    service.set_jurisdiction_pack_approver(db, dup.id, actor_id=CHECKER.id)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, dup.id, "Active", actor_id=CHECKER.id)


def test_no_duplicate_active_pack_per_land(db):
    federal = _make_federal_pack(db)
    _seed_all_laender(db, federal)
    for code, _ in land_seed.GERMAN_LAENDER:
        active_count = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.jurisdiction_country == "DE",
                JurisdictionPack.jurisdiction_state == code,
                JurisdictionPack.status == "Active",
            )
            .count()
        )
        assert active_count == 1, f"{code} has {active_count} Active packs, expected exactly 1"


# ══════════════════════════════════════════════════════════════════════════
# H. Seeding is idempotent — running it twice creates no duplicate rows.
# ══════════════════════════════════════════════════════════════════════════

def test_seeding_all_laender_twice_is_idempotent(db):
    federal = _make_federal_pack(db)
    first = _seed_all_laender(db, federal)
    second = _seed_all_laender(db, federal)

    assert [r["id"] for r in first] == [r["id"] for r in second]
    for code, _ in land_seed.GERMAN_LAENDER:
        count = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == "DE", JurisdictionPack.jurisdiction_state == code)
            .count()
        )
        assert count == 1, f"{code} has {count} pack rows after seeding twice, expected exactly 1"


# ══════════════════════════════════════════════════════════════════════════
# I. Draft -> Approved -> Active lifecycle works for a Land pack exactly
# like it does for the federal pack (same maker-checker gate).
# ══════════════════════════════════════════════════════════════════════════

def test_land_pack_lifecycle_requires_distinct_approver(db):
    federal = _make_federal_pack(db)
    pack = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId=land_seed._land_pack_id("DE-BY"), jurisdictionCountry="DE", jurisdictionState="DE-BY",
            packType="tax", version="1.0", status="Draft",
            effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31), taxYear="2026", currency="EUR",
        ), actor_id=MAKER.id,
    )
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=MAKER.id)  # self-approval

    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER.id)
    activated = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER.id)
    assert activated.status == "Active"


# ══════════════════════════════════════════════════════════════════════════
# J/K. Effective-date selection for 2026, and the resolution chain:
# employee -> Land -> jurisdiction pack -> federal rules (never Land-
# specific slabs, since Germany's federal tax/social-insurance law is
# uniform — Phase 5's centralization requirement).
# ══════════════════════════════════════════════════════════════════════════

def test_land_pack_resolves_through_to_federal_rules(db):
    federal = _make_federal_pack(db)
    _seed_all_laender(db, federal)

    for code, name in land_seed.GERMAN_LAENDER:
        resolved = tax_resolver.find_active_tax_pack(db, "DE", state=code, as_of=date(2026, 6, 1))
        assert resolved is not None, f"{name} did not resolve to any pack"
        assert resolved.id == federal.id, (
            f"{name} resolved to pack {resolved.pack_id!r} instead of the federal pack — "
            "a Land pack must never shadow federal tax/social-insurance rules."
        )


def test_land_pack_outside_2026_effective_window_does_not_resolve(db):
    federal = _make_federal_pack(db)
    _seed_all_laender(db, federal)

    resolved_2025 = tax_resolver.find_active_tax_pack(db, "DE", state="DE-BW", as_of=date(2025, 6, 1))
    assert resolved_2025 is None, "no Germany 2026 pack should resolve for a 2025 payroll date"

    resolved_2026 = tax_resolver.find_active_tax_pack(db, "DE", state="DE-BW", as_of=date(2026, 6, 1))
    assert resolved_2026 is not None and resolved_2026.id == federal.id


# ══════════════════════════════════════════════════════════════════════════
# L. One Land cannot accidentally resolve another Land's configuration.
# ══════════════════════════════════════════════════════════════════════════

def test_land_packs_are_mutually_isolated(db):
    federal = _make_federal_pack(db)
    results = _seed_all_laender(db, federal)

    ids_by_code = {r["land_code"]: r["id"] for r in results}
    assert len(set(ids_by_code.values())) == 16, "every Land must have its own distinct pack id"

    # Querying one Land's pack must never return a different Land's row.
    for code, pack_id in ids_by_code.items():
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_id).first()
        assert pack.jurisdiction_state == code
        other_codes = [c for c in ids_by_code if c != code]
        assert pack.jurisdiction_state not in other_codes


def test_land_church_tax_rate_lookup_does_not_cross_lands(db):
    """CHURCH_TAX_LAND_RATES (the actual per-Land value that varies) must
    give Bavaria/Baden-Württemberg's 8% and never leak into a 9% Land, and
    vice versa — the real isolation the payroll engine depends on,
    independent of (and unaffected by) the JurisdictionPack governance
    rows this file otherwise tests."""
    from app.modules.payroll.engine.jurisdictions.germany.pap.core import CHURCH_TAX_LAND_RATES

    assert CHURCH_TAX_LAND_RATES["DE-BW"] == CHURCH_TAX_LAND_RATES["DE-BY"] == 8
    nine_percent_lands = [c for c in CHURCH_TAX_LAND_RATES if c not in ("DE-BW", "DE-BY")]
    assert len(nine_percent_lands) == 14
    for code in nine_percent_lands:
        assert CHURCH_TAX_LAND_RATES[code] == 9, f"{code} expected 9%, got {CHURCH_TAX_LAND_RATES[code]}"


# ══════════════════════════════════════════════════════════════════════════
# M. Existing non-Germany payroll configurations remain unaffected.
# ══════════════════════════════════════════════════════════════════════════

def test_non_germany_packs_unaffected_by_land_seeding(db):
    other = service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId="IN-PAYROLL-2026-V1", jurisdictionCountry="IN", jurisdictionState=None, packType="tax",
            version="1.0", status="Draft", effectiveFrom=date(2026, 1, 1), taxYear="2026", currency="INR",
        ), actor_id=MAKER.id,
    )
    service.set_jurisdiction_pack_approver(db, other.id, actor_id=CHECKER.id)
    other = service.set_jurisdiction_pack_status(db, other.id, "Active", actor_id=CHECKER.id)

    federal = _make_federal_pack(db)
    _seed_all_laender(db, federal)

    db.refresh(other)
    assert other.status == "Active"
    assert other.jurisdiction_country == "IN"

    resolved_in = tax_resolver.find_active_tax_pack(db, "IN", state=None, as_of=date(2026, 6, 1))
    assert resolved_in is not None and resolved_in.id == other.id

    # A Land-scoped DE lookup must never resolve to India's pack.
    resolved_de = tax_resolver.find_active_tax_pack(db, "DE", state="DE-BY", as_of=date(2026, 6, 1))
    assert resolved_de.jurisdiction_country == "DE"

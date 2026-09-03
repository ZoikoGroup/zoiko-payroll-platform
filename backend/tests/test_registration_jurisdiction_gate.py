"""
tests/test_registration_jurisdiction_gate.py
----------------------------------------------
Coverage for the Production-Grade Refactor: Remove Hardcoded Payroll
Fallbacks, Enforce Active Compliance Packs.

Four areas:
  1. Organization registration is rejected for a jurisdiction with no
     valid Active canonical tax pack, and accepted when one exists.
  2. An inverted effective-date range (effective_to before effective_from)
     is rejected on save/activate — the exact defect class that silently
     made a real pack unresolvable this session.
  3. check_jurisdiction_readiness (the read-only audit tool) correctly
     reports missing keys vs. a fully-configured jurisdiction.
  4. The dormant fail-fast enforcement wrapper (_assert_jurisdiction_ready)
     stays a true no-op while _VALIDATION_ENABLED_COUNTRIES is empty, and
     actually raises once a country is (synthetically, here) opted in —
     without affecting any other country.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import register_enterprise
from app.modules.auth.models import User
from app.modules.organizations.models import Organization
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
from app.modules.payroll.schemas import JurisdictionPackUpsert


def _register_data(country, email="new-admin@example.com", **overrides):
    fields = dict(
        organization="Test Co", name="Ada Admin", email=email, password="a-strong-password-1",
        country=country,
    )
    fields.update(overrides)
    return RegisterRequest(**fields)


# ── Registration gate ────────────────────────────────────────────────────

def test_registration_rejects_country_with_no_active_pack(db):
    with pytest.raises(BadRequestException):
        register_enterprise(db, _register_data("Australia"))
    assert db.query(Organization).count() == 0
    assert db.query(User).count() == 0


def test_registration_rejects_unrecognized_country(db):
    with pytest.raises(BadRequestException):
        register_enterprise(db, _register_data("Nonexistria"))
    assert db.query(Organization).count() == 0


def test_registration_accepts_country_with_active_pack(db):
    pack = JurisdictionPack(
        pack_id="IN-TEST", jurisdiction_country="IN", pack_type="tax", version="1.0", status="Active",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
        component_key="pf", label="PF", employee_share="—", employer_share="—", total="—",
        employee_rate_pct=Decimal("12.00"),
    ))
    db.commit()

    result = register_enterprise(db, _register_data("IN"))
    assert result is not None
    assert db.query(Organization).filter(Organization.country == "IN").count() == 1


def test_registration_gate_applies_identically_to_super_admin_org_creation(db):
    # organizations/router.py's create_organization is a FastAPI route
    # function (not importable/callable standalone the way register_enterprise
    # is), so this test proves the underlying gate function it calls behaves
    # identically for a not-ready jurisdiction — the same function is reused,
    # not duplicated, at both call sites (see auth/service.py and
    # organizations/router.py, both calling
    # get_jurisdiction_onboarding_block_reason).
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason
    assert get_jurisdiction_onboarding_block_reason(db, "Canada") is not None


# ── Inverted effective-date range ────────────────────────────────────────

def test_upsert_jurisdiction_pack_rejects_inverted_date_range(db):
    data = JurisdictionPackUpsert(
        packId="BAD-DATES", jurisdictionCountry="DE", packType="tax", version="1.0",
        status="Draft", effectiveFrom=date(2026, 4, 1), effectiveTo=date(2026, 3, 31),
    )
    with pytest.raises(BadRequestException):
        service.upsert_jurisdiction_pack(db, data)


def test_set_jurisdiction_pack_status_rejects_inverted_date_on_activate(db):
    # Constructed directly via the ORM (bypassing upsert's own guard) to
    # simulate a pack that was saved before that guard existed — exactly
    # the real state India's live pack was found in this session.
    pack = JurisdictionPack(
        pack_id="BAD-DATES-2", jurisdiction_country="DE", pack_type="tax", version="1.0",
        status="Draft", effective_from=date(2026, 4, 1), effective_to=date(2026, 3, 31),
        approved_by_id=1, updated_by_id=2,
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=1)


# ── Phase 22 duplicate/overlap guard: date-range overlap, not tax_year ────
# equality — a real gap found live this session: Canada's CA-2026-H1
# (Jan-Jun) and CA-2026-H2 (Jul-Dec) share the same tax_year "2026" but
# have non-overlapping effective dates, and _find_active_tax_pack's own
# resolver is designed to pick between multiple Active packs by date
# range — so both legitimately need to be Active at once.

def test_non_overlapping_same_year_packs_can_both_go_active(db):
    h1 = JurisdictionPack(
        pack_id="CA-2026-H1-T", jurisdiction_country="CA", pack_type="tax", version="1.0",
        status="Draft", tax_year="2026", tax_regime="Standard",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
        approved_by_id=1, updated_by_id=2,
    )
    h2 = JurisdictionPack(
        pack_id="CA-2026-H2-T", jurisdiction_country="CA", pack_type="tax", version="1.0",
        status="Draft", tax_year="2026", tax_regime="Standard",
        effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31),
        approved_by_id=1, updated_by_id=2,
    )
    db.add_all([h1, h2])
    db.commit()
    db.refresh(h1)
    db.refresh(h2)
    service.set_jurisdiction_pack_status(db, h1.id, "Active", actor_id=1)
    # Must NOT raise — this is the exact case that was wrongly blocked.
    service.set_jurisdiction_pack_status(db, h2.id, "Active", actor_id=1)
    db.refresh(h1)
    db.refresh(h2)
    assert h1.status == "Active"
    assert h2.status == "Active"


def test_overlapping_date_packs_still_rejected(db):
    a = JurisdictionPack(
        pack_id="CA-2026-A-T", jurisdiction_country="CA", pack_type="tax", version="1.0",
        status="Draft", tax_year="2026", tax_regime="Standard",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
        approved_by_id=1, updated_by_id=2,
    )
    b = JurisdictionPack(
        pack_id="CA-2026-B-T", jurisdiction_country="CA", pack_type="tax", version="1.0",
        status="Draft", tax_year="2026", tax_regime="Standard",
        effective_from=date(2026, 6, 1), effective_to=date(2026, 12, 31),
        approved_by_id=1, updated_by_id=2,
    )
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)
    service.set_jurisdiction_pack_status(db, a.id, "Active", actor_id=1)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, b.id, "Active", actor_id=1)


# ── check_jurisdiction_readiness ─────────────────────────────────────────

def test_readiness_reports_missing_keys_when_unconfigured(db, organization):
    readiness = service.check_jurisdiction_readiness(db, organization.id, "IN")
    assert readiness["ready"] is False
    assert readiness["missingKeys"] or readiness["missingSlabs"]


def test_readiness_ready_when_fully_configured(db, organization):
    pack = JurisdictionPack(
        pack_id="IN-READY", jurisdiction_country="IN", pack_type="tax", version="1.0", status="Active",
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)

    from app.modules.payroll.engine.fallback_registry import get_required_parameter_keys
    for req in get_required_parameter_keys("IN"):
        kwargs = dict(
            organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
            component_key=req["key"], label=req["label"], employee_share="—", employer_share="—", total="—",
        )
        if req["side"] == "employer":
            kwargs["employer_rate_pct"] = Decimal("1.00")
        elif req["side"] == "employee":
            kwargs["employee_rate_pct"] = Decimal("1.00")
        else:
            kwargs["flat_amount"] = Decimal("100.00")
        db.add(ContributionRate(**kwargs))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"),
        rate_label="10%", tax_formula="flat",
    ))
    db.commit()

    readiness = service.check_jurisdiction_readiness(db, organization.id, "IN")
    assert readiness["ready"] is True
    assert readiness["missingKeys"] == []


# ── Dormant enforcement wrapper ──────────────────────────────────────────

def test_assert_jurisdiction_ready_is_noop_while_validation_disabled(db, organization):
    # Nothing configured at all, and IN is NOT in _VALIDATION_ENABLED_COUNTRIES
    # (the real, current, empty state) — must not raise.
    service._assert_jurisdiction_ready({}, [], "IN", organization.id)


def test_assert_jurisdiction_ready_raises_when_country_opted_in_and_not_ready(db, organization):
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._VALIDATION_ENABLED_COUNTRIES.add("ZZ")
    try:
        with pytest.raises(shared_module.MissingComplianceConfigurationError):
            service._assert_jurisdiction_ready({}, [], "ZZ", organization.id)
    finally:
        shared_module._VALIDATION_ENABLED_COUNTRIES.discard("ZZ")


def test_assert_jurisdiction_ready_unaffected_for_a_different_country(db, organization):
    # Opting ZZ in must not affect IN's own (still dormant) behavior.
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._VALIDATION_ENABLED_COUNTRIES.add("ZZ")
    try:
        service._assert_jurisdiction_ready({}, [], "IN", organization.id)
    finally:
        shared_module._VALIDATION_ENABLED_COUNTRIES.discard("ZZ")

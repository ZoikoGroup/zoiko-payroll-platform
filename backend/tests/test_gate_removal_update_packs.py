"""Gate removal P5: scripts/gate_removal_update_packs.py brings already-seeded packs in line.

A "legacy" pack is simulated the way the remote database holds it (seeded before P4): every label carries
"[PENDING G1]" and the values approved on 2026-11-25 are still empty / PENDING_G1. The script strips the
markers, fills only the empty rows from a fresh seed of the current catalogue, never overwrites a value
someone set, and leaves Active / Approved packs alone unless asked. SYNTHETIC data only.
"""
import pytest

from scripts import gate_removal_update_packs as upd

MARK = upd.MARK


@pytest.fixture(scope="module")
def reference():
    return upd.reference_rows(("PL", "BE"))


def _legacy_pack(db, seed, country):
    """Seed the current catalogue, then put it back into its pre-P4 shape."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    seed(db)
    db.flush()
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == country).one()
    for row in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id):
        row.label = f"{row.label} {MARK}"[:100]
        if upd.has_value(row):
            for column in upd.VALUE_COLS:
                setattr(row, column, None)
            row.text_value = upd.PENDING if row.component_key.endswith("_rule") else None
    for slab in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        slab.rate_label = f"{slab.rate_label} {MARK}"[:150]
    db.commit()
    return pack


def _rates(db, pack):
    from app.modules.payroll.models import ContributionRate

    return {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}


def test_dry_run_reports_and_writes_nothing(db, reference):
    from app.modules.payroll import poland_service

    pack = _legacy_pack(db, poland_service.seed_poland_pack, "PL")
    report = upd.plan_and_apply(db, reference, ("PL",), include_approved=False, apply=False)
    db.rollback()
    entry = report["packs"][0]
    assert entry["labelsStripped"] > 0 and len(entry["filled"]) >= 60
    assert all(MARK in r.label for r in _rates(db, pack).values())                 # nothing written
    assert _rates(db, pack)["pl_rounding_pit"].text_value in (None, upd.PENDING)


def test_apply_strips_markers_fills_empty_rows_and_never_overwrites(db, reference):
    from app.modules.payroll import poland_service
    from app.modules.payroll.models import TaxConfigurationAudit, TaxSlab

    pack = _legacy_pack(db, poland_service.seed_poland_pack, "PL")
    edited = _rates(db, pack)["pl_rounding_zus"]
    edited.text_value = "GROSZ_DOWN"                                     # an admin's own choice
    db.commit()

    report = upd.plan_and_apply(db, reference, ("PL",), include_approved=False, apply=True)
    db.commit()
    rates = _rates(db, pack)
    assert not any(MARK in r.label for r in rates.values())
    assert not any(MARK in (s.rate_label or "") for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id))
    assert rates["pl_rounding_pit"].text_value == "FULL_PLN_HALF_UP"            # filled from the catalogue
    assert str(rates["pl_costs_standard_annual_cap"].flat_amount).startswith("3000")
    assert rates["pl_rounding_zus"].text_value == "GROSZ_DOWN"                  # never overwritten
    assert "pl_rounding_zus" in report["packs"][0]["kept"]
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                   TaxConfigurationAudit.entity_id == pack.id).all()
    assert any("Gate removal P5" in (a.reason or "") for a in audit)

    again = upd.plan_and_apply(db, reference, ("PL",), include_approved=False, apply=True)    # idempotent
    assert again["packs"][0]["labelsStripped"] == 0 and again["packs"][0]["filled"] == []


def test_belgium_spec_values_are_filled_with_their_dates(db, reference):
    from app.modules.payroll import belgium_service

    pack = _legacy_pack(db, belgium_service.seed_belgium_pack, "BE")
    upd.plan_and_apply(db, reference, ("BE",), include_approved=False, apply=True)
    db.commit()
    rates = _rates(db, pack)
    assert str(rates["be_onss_employee_rate"].employee_rate_pct).startswith("13.07")
    assert str(rates["be_wage_rmmmg"].flat_amount).startswith("2233.61")
    assert rates["be_wage_rmmmg"].effective_from.isoformat() == "2026-07-01"
    assert rates["be_wht_annex3_regular_scale"].text_value in (None, "")        # no value in the spec: left empty


@pytest.mark.parametrize("status,include,touched", [("Active", True, False), ("Approved", False, False),
                                                    ("Approved", True, True)])
def test_pack_status_controls_what_is_touched(db, reference, status, include, touched):
    from app.modules.payroll import poland_service

    pack = _legacy_pack(db, poland_service.seed_poland_pack, "PL")
    pack.status = status
    db.commit()
    report = upd.plan_and_apply(db, reference, ("PL",), include_approved=include, apply=True)
    db.commit()
    assert bool(report["packs"]) is touched and bool(report["skipped"]) is not touched
    assert (MARK in _rates(db, pack)["pl_rounding_pit"].label) is not touched


def test_apply_refuses_a_remote_database(monkeypatch):
    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql://u:p@db.example-remote.net/zoiko")
    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    with pytest.raises(SystemExit):
        upd.main(["--apply"])

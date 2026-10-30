"""Mexico statutory configuration versions (Hong Kong parity): every version of
every Mexico pack with its state, one version's rows with sources (read-only),
a row-level compare, and "new version" — a Draft copy of the CHOSEN version
(the rollback path), never of whichever version is latest. The real Draft packs
seeded by the deployment script; SYNTHETIC edits only where a test says so."""

from decimal import Decimal

import pytest

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, _http


@pytest.fixture()
def seeded(db):
    from app.modules.payroll.models import JurisdictionPack
    from scripts.seed_mexico_canonical_packs import seed_mexico

    seed_mexico(db)
    db.commit()
    return (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "MX",
                                              JurisdictionPack.jurisdiction_state.is_(None)).one())


def _V():
    from app.modules.payroll import mexico_config_versions

    return mexico_config_versions


def test_versions_list_every_pack_with_its_state_and_rows(db, seeded):
    out = _V().mx_config_versions(db)
    national = out["packs"][0]
    assert national["state"] is None and national["packId"] == seeded.pack_id
    (v,) = national["versions"]
    assert v["status"] == "Draft" and v["versionState"] in ("DRAFT", "FUTURE_DRAFT") and v["rows"] > 0
    assert v["rowsWithSource"] == v["rows"]                              # every seeded row cites its source
    assert "never edited in the product" in out["rule"]
    assert any(g["state"] == "CDMX" for g in out["packs"])               # the state ISN pack too


def test_one_versions_rows_are_read_only_with_values_and_sources(db, seeded):
    out = _V().mx_config_pack_rows(db, seeded.id)
    assert out["editable"] is False and out["rates"] and out["slabs"]
    assert all(r["source"] and r["source"].get("sha256") for r in out["rates"] + out["slabs"])


def test_a_new_version_copies_the_chosen_version_exactly_not_the_latest(db, seeded):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    v2 = _V().mx_config_new_version(db, seeded.id, "1.1", "SYNTHETIC: re-prove after a source re-download", SA_A.id)
    assert v2["status"] == "Draft" and v2["copiedFrom"]["id"] == seeded.id and v2["rows"] > 0
    assert _V().mx_config_compare(db, seeded.id, v2["id"])["identical"] is True
    # A later code release changes one value in v1.1 (stands in for a re-seed).
    row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == v2["id"])
           .order_by(ContributionRate.id).first())
    row.flat_amount = (row.flat_amount or Decimal("0")) + Decimal("1")
    db.commit()
    diff = _V().mx_config_compare(db, seeded.id, v2["id"])
    assert diff["identical"] is False and [c["key"] for c in diff["changed"]] == [row.component_key]
    # Rollback: a copy of v1.0 (not of the latest, v1.1) restores v1.0 exactly.
    v3 = _V().mx_config_new_version(db, seeded.id, "1.2", "SYNTHETIC: roll back to v1.0", SA_A.id)
    assert _V().mx_config_compare(db, seeded.id, v3["id"])["identical"] is True
    assert _V().mx_config_compare(db, v2["id"], v3["id"])["identical"] is False
    pack = db.get(JurisdictionPack, v3["id"])
    assert (pack.status, pack.approved_by_id, pack.previous_version_id) == ("Draft", None, seeded.id)
    assert pack.source_document_id == seeded.source_document_id and pack.effective_from == seeded.effective_from
    assert "roll back to v1.0" in pack.change_summary


def test_a_new_version_is_audited_and_refused_without_a_reason_or_twice(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxConfigurationAudit as A

    with pytest.raises(BadRequestException, match="reason"):
        _V().mx_config_new_version(db, seeded.id, "1.1", "  ", SA_A.id)
    with pytest.raises(BadRequestException, match="version number"):
        _V().mx_config_new_version(db, seeded.id, "", "x", SA_A.id)
    v2 = _V().mx_config_new_version(db, seeded.id, "1.1", "SYNTHETIC", SA_A.id)
    with pytest.raises(BadRequestException, match="already exists"):
        _V().mx_config_new_version(db, seeded.id, "1.1", "SYNTHETIC", SA_A.id)
    audit = db.query(A).filter(A.entity_type == "jurisdiction_pack", A.action == "new_version",
                               A.entity_id == v2["id"]).one()
    assert audit.actor_id == SA_A.id and audit.reason == "SYNTHETIC"


def test_compare_refuses_different_scopes_and_other_countries(db, seeded):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll.models import JurisdictionPack

    cdmx = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "MX",
                                             JurisdictionPack.jurisdiction_state == "CDMX").first()
    with pytest.raises(BadRequestException, match="same scope"):
        _V().mx_config_compare(db, seeded.id, cdmx.id)
    other = JurisdictionPack(pack_id="IN-CV-TEST", jurisdiction_country="IN", version="1.0", pack_type="tax",
                             status="Draft", tax_year="2026", currency="INR")
    db.add(other)
    db.commit()
    for call in (lambda: _V().mx_config_pack_rows(db, other.id), lambda: _V().mx_config_compare(db, seeded.id, other.id),
                 lambda: _V().mx_config_new_version(db, other.id, "2", "x", SA_A.id)):
        with pytest.raises(NotFoundException):
            call()


def test_the_routes_are_super_admin_only(db, seeded):
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/configuration/versions").status_code == 200
        assert c.get(f"{BASE}/configuration/packs/{seeded.id}").status_code == 200
        made = c.post(f"{BASE}/configuration/packs/{seeded.id}/new-version",
                      json={"version": "1.1", "reason": "SYNTHETIC"})
        assert made.status_code == 200 and made.json()["status"] == "Draft"
        cmp = c.get(f"{BASE}/configuration/compare?from={seeded.id}&to={made.json()['id']}")
        assert cmp.status_code == 200 and cmp.json()["identical"] is True
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/configuration/versions").status_code in (401, 403)
        assert c.post(f"{BASE}/configuration/packs/{seeded.id}/new-version",
                      json={"version": "1.2", "reason": "x"}).status_code in (401, 403)

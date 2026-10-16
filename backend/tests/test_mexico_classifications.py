"""Mexico (ZP-MX-ENG-001) earning classifications (MX-005 / MX-006) and CFDI
schema releases (MX-015) — versioning, four-eyes, partial unique indexes,
enum constraints, historical lookup. In-memory SQLite; SYNTHETIC codes."""

from datetime import date

import pytest

MAKER, CHECKER = 11, 12


def _svc():
    from app.modules.payroll import mexico_service

    return mexico_service


def _data(**over):
    base = {"organization_id": None, "earning_code": "SUELDO", "label": "SYNTHETIC salary",
            "effective_from": date(2026, 1, 1), "isr_treatment": "TAXABLE", "isr_exempt_rule_key": None,
            "sbc_treatment": "FIXED", "sbc_exclusion_condition": None, "infonavit_included": True,
            "isn_default_included": True, "isn_state_overrides": None, "ptu_wage_base_included": True,
            "cfdi_node_type": "PERCEPCION", "cfdi_concept_code": None}
    base.update(over)
    return base


def _approved_catalog(db, code="001"):
    svc = _svc()
    rel = svc.create_release(db, {"cfdi_version": "4.0", "complement_version": "1.2"}, MAKER)
    svc.add_catalog_entry(db, rel["id"], {"catalog_name": "c_TipoPercepcion", "code": code,
                                          "description": "SYNTHETIC"}, MAKER)
    svc.transition_release(db, rel["id"], "submit", MAKER)
    svc.transition_release(db, rel["id"], "approve", CHECKER)
    return rel


def test_a_new_classification_is_draft_and_never_live(db, organization):
    svc = _svc()
    row = svc.create_classification(db, _data(organization_id=organization.id), MAKER)
    assert (row["status"], row["version"], row["approvedById"]) == ("DRAFT", 1, None)
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 6, 1)) is None


def test_the_creator_cannot_approve_and_a_second_super_admin_can(db, organization):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    row = svc.create_classification(db, _data(organization_id=organization.id), MAKER)
    with pytest.raises(BadRequestException, match="different Super Admin"):
        svc.approve_classification(db, row["id"], MAKER)
    approved = svc.approve_classification(db, row["id"], CHECKER)
    assert (approved["status"], approved["approvedById"]) == ("ACTIVE", CHECKER)
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 6, 1)).id == row["id"]


def test_a_canonical_row_needs_an_approved_catalog_code(db):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    row = svc.create_classification(db, _data(cfdi_concept_code="001"), MAKER)
    with pytest.raises(BadRequestException, match="S28"):
        svc.approve_classification(db, row["id"], CHECKER)
    _approved_catalog(db, "001")
    assert svc.approve_classification(db, row["id"], CHECKER)["status"] == "ACTIVE"


def test_a_newer_version_supersedes_and_history_keeps_the_old_one(db, organization):
    svc = _svc()
    v1 = svc.create_classification(db, _data(organization_id=organization.id), MAKER)
    svc.approve_classification(db, v1["id"], CHECKER)
    v2 = svc.create_classification(db, _data(organization_id=organization.id, effective_from=date(2026, 7, 1),
                                             sbc_treatment="VARIABLE"), MAKER)
    assert v2["version"] == 2
    svc.approve_classification(db, v2["id"], CHECKER)
    rows = {r["id"]: r for r in svc.list_classifications(db, organization.id)}
    assert rows[v1["id"]]["status"] == "SUPERSEDED" and rows[v1["id"]]["effectiveTo"] == "2026-06-30"
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 3, 1)).sbc_treatment == "FIXED"
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 9, 1)).sbc_treatment == "VARIABLE"


def test_versions_must_be_approved_in_date_order(db, organization):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    later = svc.create_classification(db, _data(organization_id=organization.id, effective_from=date(2026, 7, 1)), MAKER)
    earlier = svc.create_classification(db, _data(organization_id=organization.id), MAKER)
    svc.approve_classification(db, later["id"], CHECKER)
    with pytest.raises(BadRequestException, match="date order"):
        svc.approve_classification(db, earlier["id"], CHECKER)


def test_an_org_row_overrides_the_platform_catalogue(db, organization):
    svc = _svc()
    _approved_catalog(db, "001")
    canonical = svc.create_classification(db, _data(cfdi_concept_code="001"), MAKER)
    svc.approve_classification(db, canonical["id"], CHECKER)
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 3, 1)).id == canonical["id"]
    own = svc.create_classification(db, _data(organization_id=organization.id, isr_treatment="PARTIAL",
                                              isr_exempt_rule_key="SYNTHETIC_RULE"), MAKER)
    svc.approve_classification(db, own["id"], CHECKER)
    assert svc.classification_in_force(db, organization.id, "SUELDO", date(2026, 3, 1)).id == own["id"]


@pytest.mark.parametrize("over, message", [
    ({"isr_treatment": "TAX"}, "isr_treatment"),
    ({"sbc_treatment": "NONE"}, "sbc_treatment"),
    ({"cfdi_node_type": "OTHER"}, "cfdi_node_type"),
    ({"isr_treatment": "EXEMPT"}, "exemption rule"),
    ({"sbc_treatment": "EXCLUDED"}, "documentary condition"),
    ({"infonavit_included": None}, "decided explicitly"),
    ({"isn_state_overrides": {"XX": True}}, "unknown federal entity"),
])
def test_every_axis_is_validated(db, over, message):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match=message):
        _svc().create_classification(db, _data(**over), MAKER)


def test_archive_rules(db, organization):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    v1 = svc.create_classification(db, _data(organization_id=organization.id), MAKER)
    svc.approve_classification(db, v1["id"], CHECKER)
    v2 = svc.create_classification(db, _data(organization_id=organization.id, effective_from=date(2026, 7, 1)), MAKER)
    svc.approve_classification(db, v2["id"], CHECKER)
    with pytest.raises(BadRequestException, match="retained evidence"):
        svc.archive_classification(db, v1["id"], CHECKER, "x")            # SUPERSEDED is evidence
    assert svc.archive_classification(db, v2["id"], CHECKER, "withdrawn")["status"] == "ARCHIVED"


# ── database-level guarantees (partial unique indexes, check constraints) ──

def _orm_row(**over):
    from app.modules.payroll.models import PayrollMxEarningClassification

    values = dict(organization_id=None, earning_code="SUELDO", label="x", version=1, effective_from=date(2026, 1, 1),
                  isr_treatment="TAXABLE", sbc_treatment="FIXED", infonavit_included=True, isn_default_included=True,
                  ptu_wage_base_included=True, cfdi_node_type="PERCEPCION", status="DRAFT", sha256="0" * 64)
    values.update(over)
    return PayrollMxEarningClassification(**values)


def test_a_duplicate_canonical_row_is_refused_by_the_database(db):
    from sqlalchemy.exc import IntegrityError

    db.add(_orm_row())
    db.commit()
    db.add(_orm_row(version=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_duplicate_org_row_is_refused_but_scopes_are_independent(db, organization):
    from sqlalchemy.exc import IntegrityError

    db.add_all([_orm_row(), _orm_row(organization_id=organization.id)])   # canonical + org, same code/date: fine
    db.commit()
    db.add(_orm_row(organization_id=organization.id, version=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("over", [{"isr_treatment": "X"}, {"sbc_treatment": "X"}, {"cfdi_node_type": "X"},
                                  {"status": "LIVE"}, {"effective_to": date(2025, 1, 1)}])
def test_check_constraints_refuse_invalid_rows(db, over):
    from sqlalchemy.exc import IntegrityError

    db.add(_orm_row(**over))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_service_refuses_a_duplicate_before_the_database_does(db):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    svc.create_classification(db, _data(), MAKER)
    with pytest.raises(BadRequestException, match="already has a version"):
        svc.create_classification(db, _data(), MAKER)


# ── CFDI schema releases ────────────────────────────────────────────────────

def test_release_lifecycle_four_eyes_and_frozen_entries(db):
    from app.core.exceptions import BadRequestException

    svc = _svc()
    rel = svc.create_release(db, {"cfdi_version": "4.0", "complement_version": "1.2"}, MAKER)
    assert rel["status"] == "Draft"
    svc.add_catalog_entry(db, rel["id"], {"catalog_name": "c_TipoDeduccion", "code": "002",
                                          "description": "SYNTHETIC"}, MAKER)
    svc.transition_release(db, rel["id"], "submit", MAKER)
    with pytest.raises(BadRequestException, match="frozen"):
        svc.add_catalog_entry(db, rel["id"], {"catalog_name": "c", "code": "9", "description": "x"}, MAKER)
    with pytest.raises(BadRequestException, match="different Super Admin"):
        svc.transition_release(db, rel["id"], "approve", MAKER)
    assert svc.transition_release(db, rel["id"], "approve", CHECKER)["status"] == "Approved"
    with pytest.raises(BadRequestException, match="Phase 7 PAC validation"):
        svc.transition_release(db, rel["id"], "activate", CHECKER)
    assert svc.list_releases(db)[0]["status"] == "Approved"
    assert [e["code"] for e in svc.list_catalog_entries(db, rel["id"])] == ["002"]

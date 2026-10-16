"""Mexico Phase 3 — legal employer profile (panels A and B): versioning,
RFC immutability, persona moral / física formats, per-org uniqueness,
several RFCs per organisation (MX-002). SYNTHETIC identifiers."""

from datetime import date

import pytest

from tests._mx_employer_helpers import employer_payload, make_org, new_employer, to_service


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


@pytest.mark.parametrize("rfc,kind", [("ABC010101AB1", "MORAL"), ("ÑA&010101XY9", "MORAL"),
                                      ("ABCD000229AB1", "FISICA"), ("ABCD991231ZZ9", "FISICA")])
def test_valid_rfc_formats(rfc, kind):
    assert _svc().validate_rfc(f"  {rfc.lower()} ", kind) == rfc.upper()


@pytest.mark.parametrize("rfc,kind,msg", [
    ("ABCD010101AB1", "MORAL", "MORAL RFC is 12"),         # 13 chars given a moral
    ("ABC010101AB1", "FISICA", "FISICA RFC is 13"),         # 12 chars given a física
    ("ABC011301AB1", "MORAL", "real date"),                 # month 13
    ("ABC010230AB1", "MORAL", "real date"),                 # 30 February
    ("AB1010101AB1", "MORAL", "12"),
    ("ABC010101AB1", "OTHER", "taxpayerType"),
])
def test_invalid_rfc_is_refused_with_a_field_message(rfc, kind, msg):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match=msg):
        _svc().validate_rfc(rfc, kind)


def test_registro_patronal_format_only():
    from app.core.exceptions import BadRequestException

    assert _svc().validate_registro_patronal("y1234567101") == "Y1234567101"
    for bad in ("Y123456710", "Y12345671012", "Y123456710-"):
        with pytest.raises(BadRequestException, match="11 letters or digits"):
            _svc().validate_registro_patronal(bad)


def test_create_version_closes_the_previous_and_keeps_the_rfc(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    v1 = new_employer(db, t.org.id)
    v2 = _svc().create_employer_version(db, t.org.id, v1["id"], to_service(employer_payload(
        effectiveFrom="2026-07-01", legalName="Empresa Sintética v2")), 701)
    assert (v2["version"], v2["previousVersionId"]) == (2, v1["id"])
    chain = _svc().list_employers(db, t.org.id)[0]["versions"]
    assert chain[0]["effectiveTo"] == "2026-06-30" and chain[1]["effectiveTo"] is None
    with pytest.raises(BadRequestException, match="RFC cannot change"):
        _svc().create_employer_version(db, t.org.id, v2["id"], to_service(employer_payload(
            effectiveFrom="2026-09-01", rfc="XYZ010101AB1")), 701)
    with pytest.raises(BadRequestException, match="must start after"):
        _svc().create_employer_version(db, t.org.id, v1["id"], to_service(employer_payload(
            effectiveFrom="2026-07-01")), 701)
    root = _svc().employer_root(db, t.org.id, v2["id"])
    assert root.id == v1["id"]                                   # children hang off the root
    assert _svc().version_in_force(db, root.id, date(2026, 6, 30)).version == 1
    assert _svc().version_in_force(db, root.id, date(2026, 7, 1)).version == 2


def test_several_rfcs_per_org_and_uniqueness_is_per_org_only(db):
    from app.core.exceptions import BadRequestException

    a, b = make_org(db), make_org(db, name="Other", code="OTHER")
    new_employer(db, a.org.id)
    new_employer(db, a.org.id, rfc="XYZ010101AB1")             # a second legal employer in one tenant
    with pytest.raises(BadRequestException, match="already has a legal employer with that RFC"):
        new_employer(db, a.org.id)
    new_employer(db, b.org.id)                                   # another tenant may record the same RFC
    assert len(_svc().list_employers(db, a.org.id)) == 2


def test_open_row_partial_index_refuses_a_second_open_version(db):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    t = make_org(db)
    v1 = new_employer(db, t.org.id)
    row = db.get(P, v1["id"])
    db.add(P(organization_id=t.org.id, version=9, effective_from=date(2026, 5, 1), taxpayer_type="MORAL",
             rfc=row.rfc, legal_name="dup", fiscal_regime_code="601", fiscal_postal_code="06600",
             place_of_issue_postal_code="06600", withholding_obligation_active=True, stamp_test_status="NOT_TESTED"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_audit_rows_mask_the_rfc(db):
    import json

    from app.modules.payroll.models import TaxConfigurationAudit

    t = make_org(db)
    new_employer(db, t.org.id)
    blob = json.dumps([a.new_value for a in db.query(TaxConfigurationAudit).all()], default=str)
    assert "ABC010101AB1" not in blob and "AB1" in blob


def test_stamp_test_fields_cannot_be_set_by_the_client():
    from pydantic import ValidationError

    from app.modules.payroll.mexico_schemas import MXEmployerCreate

    with pytest.raises(ValidationError):
        MXEmployerCreate(**employer_payload(stampTestStatus="PASSED"))

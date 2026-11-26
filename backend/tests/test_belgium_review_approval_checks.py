"""Belgium: a Belgian pack cannot move to QA, In Review or Approved while any
catalogue key is missing (structural; status list, Approve action and create /
edit alike). Since the gate removal, owner decision 2026-11-25, a complete catalogue may be approved with rows
still empty: a row without a value blocks only the calculation that needs it,
as in Spain. Stricter only, never retroactive.
SYNTHETIC data only: no Belgian figure is used (rows are decided NOT_SUPPORTED)."""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import belgium_service as bes
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit, TaxSlab
from app.modules.payroll.schemas import JurisdictionPackUpsert
from tests.test_belgium_super_admin import _c, _verified_source, seeded  # noqa: F401  (pytest fixture)

MAKER, CHECKER, ACTIVATOR = 801, 802, 803


def _empty_pack(db, pack_id="BE-PAYROLL-2027", status="Draft"):
    pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country="BE", pack_type="tax", status=status,
                            effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31), tax_year="2027",
                            created_by_id=MAKER, updated_by_id=MAKER)
    db.add(pack)
    db.commit()
    return pack


def _refused(db, pack):
    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id, TaxConfigurationAudit.action == "refused")
            .all())


def _decide_every_row(db, pack):
    """Every catalogue row decided (NOT_SUPPORTED: not empty, no figure), sourced and
    signed; every earning classification signed. Written directly: SYNTHETIC."""
    c = _c()
    src = _verified_source(db)
    for row in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id):
        row.label, row.text_value, row.source_document_id = row.label.replace(c.PENDING_MARK, "").strip(), \
            c.NOT_SUPPORTED, src.id
    for slab in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        slab.rate_label = (slab.rate_label or "").replace(c.PENDING_MARK, "").strip()
    db.commit()


@pytest.mark.parametrize("status", ["QA", "In Review", "Approved"])
def test_an_empty_pack_cannot_move_to_a_review_status(db, status):
    pack = _empty_pack(db)
    with pytest.raises(BadRequestException) as refused:
        service.set_jurisdiction_pack_status(db, pack.id, status, actor_id=CHECKER)
    assert refused.value.message == bes.BE_NO_CATALOGUE
    assert ".py" not in refused.value.message
    db.rollback()
    assert db.get(JurisdictionPack, pack.id).status == "Draft"


def test_an_empty_pack_cannot_be_approved(db):
    pack = _empty_pack(db)
    with pytest.raises(BadRequestException) as refused:
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    assert refused.value.message == bes.BE_NO_CATALOGUE
    db.rollback()
    pack = db.get(JurisdictionPack, pack.id)
    assert pack.status == "Draft" and pack.approved_by_id is None


def test_a_partial_catalogue_is_refused_with_the_count(db, seeded):
    key = next(iter(_c().KEYS))
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == seeded.id,
                                      ContributionRate.component_key == key).delete()
    db.commit()
    with pytest.raises(BadRequestException, match=f"missing 1 of {len(_c().KEYS)} Belgian statutory rows"):
        service.set_jurisdiction_pack_status(db, seeded.id, "QA", actor_id=CHECKER)


def test_a_complete_catalogue_may_go_to_review_and_be_approved_with_empty_rows(db, seeded):
    """gate removal, owner decision 2026-11-25: no row needs to be valued, sourced or signed before approval."""
    assert service.set_jurisdiction_pack_status(db, seeded.id, "In Review", actor_id=MAKER).status == "In Review"
    assert service.set_jurisdiction_pack_status(db, seeded.id, "QA", actor_id=MAKER).status == "QA"
    assert bes.be_approval_content_refusal(db, seeded) is None
    approved = service.set_jurisdiction_pack_approver(db, seeded.id, actor_id=CHECKER)
    assert approved.approved_by_id == CHECKER


def test_a_fully_valued_sourced_and_signed_pack_can_be_approved(db, seeded):
    _decide_every_row(db, seeded)
    assert bes.be_approval_content_refusal(db, seeded) is None
    approved = service.set_jurisdiction_pack_approver(db, seeded.id, actor_id=CHECKER)
    assert approved.status == "Approved" and approved.approved_by_id == CHECKER


def test_the_status_list_never_approves(db, seeded):
    """Approved is reached only through the Approve action (platform rule, every country)."""
    service.set_jurisdiction_pack_status(db, seeded.id, "In Review", actor_id=MAKER)
    with pytest.raises(BadRequestException, match="use the Approve button"):
        service.set_jurisdiction_pack_status(db, seeded.id, "Approved", actor_id=MAKER)


def test_create_or_edit_into_a_review_status_is_refused_without_a_catalogue(db):
    def upsert(status, pack_id="BE-PAYROLL-2030"):
        return service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
            packId=pack_id, jurisdictionCountry="BE", packType="tax", version="1.0", status=status,
            effectiveFrom=date(2030, 1, 1), effectiveTo=date(2030, 12, 31), taxYear="2030", currency="EUR",
        ), actor_id=MAKER)

    with pytest.raises(BadRequestException, match="no Belgian statutory rows yet"):
        upsert("QA")                                                  # create
    db.rollback()
    pack = upsert("Draft")
    with pytest.raises(BadRequestException, match="no Belgian statutory rows yet"):
        upsert("In Review")                                           # edit
    db.rollback()
    assert db.get(JurisdictionPack, pack.id).status == "Draft"


def test_existing_statuses_are_not_changed_retroactively(db):
    pack = _empty_pack(db, status="Approved")                         # e.g. the live BE-PAYROLL-2027
    bes.be_approval_content_refusal(db, pack)
    db.expire_all()
    assert db.get(JurisdictionPack, pack.id).status == "Approved"
    # and the documented way back is still open
    assert service.set_jurisdiction_pack_status(db, pack.id, "Draft", actor_id=CHECKER).status == "Draft"


def test_other_countries_are_unaffected(db):
    pack = JurisdictionPack(pack_id="PL-SYNTH-EMPTY", version="1.0", jurisdiction_country="PL", pack_type="tax",
                            status="Draft", effective_from=date(2030, 1, 1), effective_to=date(2030, 12, 31),
                            tax_year="2030", created_by_id=MAKER, updated_by_id=MAKER)
    db.add(pack)
    db.commit()
    assert service.set_jurisdiction_pack_status(db, pack.id, "QA", actor_id=MAKER).status == "QA"

"""Every country (2026-11-25): a tax pack becomes Approved only through the
Approve action (set_jurisdiction_pack_approver: recorded approver, self-approval
/ four-eyes and the country's own approval checks). The status list
(PUT /compliance/policies/{id}/status) and plain create / edit used to set
"Approved" with no approver and none of those checks. Stricter only: the
Approve action and every other transition are unchanged. SYNTHETIC data only."""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import JurisdictionPack, TaxConfigurationAudit
from app.modules.payroll.schemas import JurisdictionPackUpsert

MAKER, CHECKER = 701, 702
# A graph country with refusal audit (SG), and two countries outside every opt-in list.
COUNTRIES = ("SG", "CA", "PR")


def _upsert(db, country, status="Draft", actor_id=MAKER, **extra):
    return service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=f"{country}-SYNTH-APPROVAL", jurisdictionCountry=country, packType="tax", version="1.0", status=status,
        effectiveFrom=date(2030, 1, 1), effectiveTo=date(2030, 12, 31), taxYear="2030", currency="XXX", **extra,
    ), actor_id=actor_id)


@pytest.mark.parametrize("country", COUNTRIES)
def test_status_list_refuses_approved_without_a_recorded_approver(db, country):
    pack = _upsert(db, country)
    with pytest.raises(BadRequestException, match="use the Approve button"):
        service.set_jurisdiction_pack_status(db, pack.id, "Approved", actor_id=CHECKER)
    db.rollback()
    pack = db.get(JurisdictionPack, pack.id)
    assert pack.status == "Draft" and pack.approved_by_id is None


def test_the_refusal_is_audited_for_an_opted_in_country(db):
    pack = _upsert(db, "SG")
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Approved", actor_id=CHECKER)
    refused = (db.query(TaxConfigurationAudit)
               .filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id, TaxConfigurationAudit.action == "refused")
               .all())
    assert refused and refused[-1].new_value["attempted"] == "Approved"


@pytest.mark.parametrize("country", COUNTRIES)
def test_the_approve_action_still_moves_a_draft_to_approved(db, country):
    pack = _upsert(db, country)
    approved = service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    assert approved.status == "Approved" and approved.approved_by_id == CHECKER        # unchanged behaviour


@pytest.mark.parametrize("country", COUNTRIES)
def test_in_review_then_approve_then_approved_still_works(db, country):
    pack = _upsert(db, country)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=MAKER)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    assert db.get(JurisdictionPack, pack.id).status == "In Review"                     # Approve keeps In Review
    assert service.set_jurisdiction_pack_status(db, pack.id, "Approved", actor_id=MAKER).status == "Approved"


@pytest.mark.parametrize("country", COUNTRIES)
def test_create_or_edit_cannot_set_approved(db, country):
    with pytest.raises(BadRequestException, match="use the Approve button"):
        _upsert(db, country, status="Approved")                                         # create
    db.rollback()
    pack = _upsert(db, country)
    with pytest.raises(BadRequestException, match="use the Approve button"):
        _upsert(db, country, status="Approved")                                         # edit Draft -> Approved
    db.rollback()
    assert db.get(JurisdictionPack, pack.id).status == "Draft"


@pytest.mark.parametrize("country", COUNTRIES)
def test_editing_an_approved_pack_keeping_its_status_is_still_allowed(db, country):
    pack = _upsert(db, country)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    edited = _upsert(db, country, status="Approved", actor_id=CHECKER, changeSummary="SYNTHETIC edit")
    # Allowed; and, as before, an edit clears the approval and returns the pack to Draft.
    assert edited.status == "Draft" and edited.approved_by_id is None

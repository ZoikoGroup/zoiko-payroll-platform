"""Germany is opted into the two stricter approval rules (owner decision 2026-11-25):

* the approver may not approve their own edit (_SELF_APPROVAL_REFUSED_COUNTRIES:
  refused at Approve; also: an Active pack's approval cannot be replaced);
* the approver may not activate (_APPROVER_NOT_ACTIVATOR_COUNTRIES).

Stricter only: a distinct maker, approver and activator still activate a German
pack as before. Onboarding and the other activation checks are unchanged.
SYNTHETIC data only."""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import ReportTemplate
from app.modules.payroll.schemas import JurisdictionPackUpsert

MAKER, CHECKER, ACTIVATOR = 101, 202, 303


def _draft(db, pack_id="DE-PAYROLL-FOUR-EYES", actor_id=MAKER):
    return service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=pack_id, jurisdictionCountry="DE", packType="tax", version="2026", status="Draft",
        effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31), taxYear="2026", currency="EUR",
    ), actor_id=actor_id)


def test_germany_is_in_both_lists():
    assert "DE" in service._SELF_APPROVAL_REFUSED_COUNTRIES
    assert "DE" in service._APPROVER_NOT_ACTIVATOR_COUNTRIES


def test_the_last_editor_cannot_approve(db):
    pack = _draft(db)
    with pytest.raises(BadRequestException, match="last edited or submitted this pack cannot approve"):
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=MAKER)
    db.refresh(pack)
    assert pack.approved_by_id is None


def test_the_approver_cannot_activate(db):
    pack = _draft(db)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    with pytest.raises(BadRequestException, match="approved this pack cannot also activate it"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=CHECKER)
    db.refresh(pack)
    assert pack.status != "Active"


def test_distinct_maker_approver_and_activator_still_activate(db):
    pack = _draft(db)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    active = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=ACTIVATOR)
    assert active.status == "Active" and active.approved_by_id == CHECKER


def test_an_active_packs_approval_cannot_be_replaced(db):
    pack = _draft(db)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER)
    service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=ACTIVATOR)
    with pytest.raises(BadRequestException, match="approval is release evidence"):
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=404)
    db.refresh(pack)
    assert pack.approved_by_id == CHECKER


def test_german_report_templates_follow_the_same_approver_rule():
    row = ReportTemplate(template_key="DE-SYNTH", version="1", jurisdiction_country="DE", approved_by_id=CHECKER,
                         content_editor_id=MAKER)
    assert "the approver may not activate" in service.report_template_four_eyes_refusal(row, "Active", CHECKER)
    assert service.report_template_four_eyes_refusal(row, "Active", ACTIVATOR) is None


def test_other_countries_are_unchanged():
    # A country outside both lists keeps "the checker approves and activates".
    for country in ("CA", "PR", "BS", "BB"):
        assert country not in service._SELF_APPROVAL_REFUSED_COUNTRIES
        assert country not in service._APPROVER_NOT_ACTIVATOR_COUNTRIES


def test_seed_scripts_require_a_distinct_activator(monkeypatch):
    import sys

    from scripts import _actor_authorization as auth
    from scripts import seed_germany_2026_all_jurisdictions as land_seed
    from scripts import seed_germany_compliance_pack_2026 as pack_seed

    for module, extra in ((pack_seed, []), (land_seed, ["--federal-pack-id", "1"])):
        monkeypatch.setattr(sys, "argv", ["x", "--maker-id", "1", "--checker-id", "2", *extra])
        with pytest.raises(SystemExit):                       # --activator-id is required
            module._parse_args()
        monkeypatch.setattr(sys, "argv", ["x", "--maker-id", "1", "--checker-id", "2", "--activator-id", "3", *extra])
        assert module._parse_args().activator_id == 3
    for same in (MAKER, CHECKER):
        with pytest.raises(auth.ActorAuthorizationError) as refused:
            auth.resolve_and_authorize_activator(None, same, MAKER, CHECKER)
        assert "must differ from the maker" in refused.value.message

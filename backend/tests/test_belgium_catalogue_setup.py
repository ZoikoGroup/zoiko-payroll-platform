"""'Set up Belgian catalogue' (2026-11-25): writes the standard catalogue into a
Draft Belgian pack that lacks it, with the SAME rows as the seed
(be_write_catalogue_rows: every value empty, [PENDING G1], spec-proposed text in
the label only). Nothing copied, no value invented; Draft only, reason
required, audited, create-only. SYNTHETIC data only."""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as bes
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit, TaxSlab
from tests.test_belgium_super_admin import _c, seeded  # noqa: F401  (pytest fixture)

ADMIN, CHECKER = 901, 902
REASON = "SYNTHETIC catalogue set-up"
VALUE_FIELDS = ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value")


def _pack(db, pack_id="BE-PAYROLL-2027", status="Draft", country="BE"):
    pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=country, pack_type="tax",
                            status=status, effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31),
                            tax_year="2027", created_by_id=ADMIN, updated_by_id=ADMIN)
    db.add(pack)
    db.commit()
    return pack


def _rows(db, pack):
    rates = {r.component_key: r for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id)}
    classes = [s for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id)
               if s.rule_type == _c().EARNING_CLASS_RULE]
    return rates, classes


def _setup(db, pack, reason=REASON):
    out = bes.be_set_up_catalogue(db, pack.id, ADMIN, reason)
    db.commit()
    return out


def test_sets_up_every_catalogue_row_with_the_approved_values_and_no_marker(db):
    """gate removal, owner decision 2026-11-25: the same rows as the seed - approved spec values filled
    (belgium_content.VALUES), every other row empty, no "[PENDING G1]" marker."""
    c = _c()
    pack = _pack(db)
    out = _setup(db, pack)
    rates, classes = _rows(db, pack)
    assert out["rows"] == len(c.KEYS) == len(rates)
    assert out["earningClasses"] == len(c.OBLIGATIONS) * len(c.COMPONENTS) == len(classes)
    for key, row in rates.items():
        filled = any(getattr(row, f) is not None for f in VALUE_FIELDS)
        assert filled is (key in c.VALUES), key                                    # only approved values
        assert c.PENDING_MARK not in row.label
    assert all(c.PENDING_MARK not in s.rate_label and s.assessment_basis == "REVIEW" for s in classes)
    assert bes.be_catalogue_refusal(db, pack) is None


def test_writes_exactly_what_the_seed_writes(db, seeded):
    other = _pack(db)
    _setup(db, other)
    seed_rates, seed_classes = _rows(db, seeded)
    new_rates, new_classes = _rows(db, other)
    fields = ("label", "employee_share", "employer_share", "total", *VALUE_FIELDS, "source_document_id", "sort_order")
    assert {k: tuple(getattr(r, f) for f in fields) for k, r in new_rates.items()} == \
        {k: tuple(getattr(r, f) for f in fields) for k, r in seed_rates.items()}           # spec-proposed text kept
    slab_fields = ("tax_regime", "filing_status", "assessment_basis", "rate_label", "min_amount", "rate_pct")
    assert sorted(tuple(getattr(s, f) for f in slab_fields) for s in new_classes) == \
        sorted(tuple(getattr(s, f) for f in slab_fields) for s in seed_classes)


def test_is_audited_with_who_and_reason(db):
    pack = _pack(db)
    _setup(db, pack)
    audit = (db.query(TaxConfigurationAudit)
             .filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id,
                     TaxConfigurationAudit.action == "catalogue_setup").one())
    assert audit.actor_id == ADMIN and audit.reason == REASON and audit.created_at is not None
    assert audit.new_value["catalogueRowsAdded"] == len(_c().KEYS)


@pytest.mark.parametrize("status", ["In Review", "QA", "Approved", "Active", "Retired"])
def test_refused_outside_draft(db, status):
    pack = _pack(db, status=status)
    with pytest.raises(BadRequestException, match="Draft pack only"):
        bes.be_set_up_catalogue(db, pack.id, ADMIN, REASON)


def test_refused_without_reason_for_a_complete_catalogue_and_for_another_country(db, seeded):
    with pytest.raises(BadRequestException, match="reason is required"):
        bes.be_set_up_catalogue(db, _pack(db).id, ADMIN, "  ")
    with pytest.raises(BadRequestException, match="already holds the full Belgian catalogue"):
        bes.be_set_up_catalogue(db, seeded.id, ADMIN, REASON)
    with pytest.raises(NotFoundException):
        bes.be_set_up_catalogue(db, _pack(db, "PL-SYNTH", country="PL").id, ADMIN, REASON)


def test_create_only_a_row_already_held_is_never_touched(db):
    pack = _pack(db)
    key = next(iter(_c().KEYS))
    kept = ContributionRate(jurisdiction_country="BE", jurisdiction_pack_id=pack.id, component_key=key,
                            label="SYNTHETIC kept row", employee_share="—", employer_share="—", total="—",
                            text_value="SYNTHETIC")
    db.add(kept)
    db.commit()
    out = _setup(db, pack)
    assert out["rows"] == len(_c().KEYS) - 1
    db.refresh(kept)
    assert (kept.label, kept.text_value) == ("SYNTHETIC kept row", "SYNTHETIC")


def test_after_set_up_the_pack_may_go_to_review_and_be_approved(db):
    """gate removal, owner decision 2026-11-25: a complete catalogue may be approved with rows still empty."""
    pack = _pack(db)
    _setup(db, pack)
    assert service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=ADMIN).status == "In Review"
    assert service.set_jurisdiction_pack_approver(db, pack.id, actor_id=CHECKER).approved_by_id == CHECKER

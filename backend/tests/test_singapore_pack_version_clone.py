"""
tests/test_singapore_pack_version_clone.py
------------------------------------------
Singapore final closure (2026-09-29), found by the real-organization
validation on PostgreSQL: creating a NEW pack version (upsert_jurisdiction_pack
-> _clone_pack_rates, the documented correction path) dropped
effective_from / effective_to, source_document_id and TaxSlab.assessment_basis.
For Singapore that made every CPF band "unknown CPF formula type None" (all
payroll under the new version BLOCKED), made effective-dated rows open-ended
(both LQS windows in force at once) and lost every row's source. The clone
now copies every value column. The fix is in a shared function, so a
non-Singapore pack is covered too.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal as D

from tests.test_singapore_phase57_reports import _employee, _generate_payslips, _stub_codes

A, B, C = 101, 202, 303
_SKIP = {"id", "jurisdiction_pack_id", "created_at", "updated_at"}


def _rows(db, model, pack_id):
    cols = [c.name for c in model.__table__.columns if c.name not in _SKIP]
    return sorted((tuple(str(getattr(r, c)) for c in cols) for r in
                   db.query(model).filter(model.jurisdiction_pack_id == pack_id, model.organization_id.is_(None))))


def _new_version(db, pack, version):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    return service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=pack.pack_id, jurisdictionCountry=pack.jurisdiction_country, packType="tax", version=version,
        status="Draft", effectiveFrom=pack.effective_from, effectiveTo=pack.effective_to), actor_id=A)


def test_a_new_singapore_pack_version_copies_every_row_value(db):
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    clone = _new_version(db, pack, "1.3")
    for model in (ContributionRate, TaxSlab):
        assert _rows(db, model, clone.id) == _rows(db, model, pack.id), model.__tablename__
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == clone.id, TaxSlab.rule_type == "CPF_RATE_BAND").all()
    assert slabs and all(s.assessment_basis for s in slabs)                              # FULL / PHASE_IN kept
    lqs = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == clone.id,
                                            ContributionRate.component_key == "lqs_full_time_monthly").all()
    assert len(lqs) >= 2 and all(r.effective_from or r.effective_to for r in lqs)        # windows stay windows
    unsourced = {r.component_key for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == clone.id,
                                                                           ContributionRate.source_document_id.is_(None))}
    assert unsourced == {"ais_submission_mode"}          # the product's AIS-mode setting (owner decision D1), not a statutory value


def test_payroll_under_the_new_version_calculates_exactly_as_under_the_old(db, organization, monkeypatch):
    """CPF golden F1 (citizen, age 40, OW 6,000: 1,200 / 1,020) under the cloned, Active v1.3."""
    import json
    from pathlib import Path

    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails, PayslipItem
    from scripts.seed_singapore_canonical_pack import seed_singapore

    _stub_codes(monkeypatch)
    pack = seed_singapore(db)
    pack.status = "Superseded"                                          # the prior version, replaced
    db.commit()
    clone = _new_version(db, pack, "1.3")
    clone.status = "Active"
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", active_pack_id=clone.id,
                                    name="Clone Co", tax_identifiers={"uen": "201912345K"}))
    db.commit()
    emp = _employee(db, organization.id, "F1", ctc=D("72000"))
    run = _generate_payslips(db, organization, date(2026, 8, 31), "Aug 2026 clone")
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    f1 = json.loads(Path("tests/fixtures/sg_golden/f1_citizen_le55_ow_6000.json").read_text(encoding="utf8"))["expected"]
    assert (item.employee_pension, item.employer_pension) == (D(f1["employee_pension"]), D(f1["employer_pension"]))
    assert item.tax_policy_pack_id == clone.id


def test_a_non_singapore_pack_version_is_cloned_faithfully_too(db):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    src = SourceArtifact(agency="IRS", title="Pub 15-T", source_url="https://example.invalid/15t")
    db.add(src)
    db.commit()
    pack = JurisdictionPack(pack_id="US-CLONE", jurisdiction_country="US", pack_type="tax", version="1.0", status="Active",
                            effective_from=date(2026, 1, 1))
    db.add(pack)
    db.commit()
    db.add_all([
        ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="US", component_key="futa", label="FUTA",
                         employee_share="0", employer_share="0.6%", total="0.6%", employer_rate_pct=D("0.006"), effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
                         source_document_id=src.id),
        TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="US", min_amount=D("0"), max_amount=D("1000"),
                rate_pct=D("10"), rate_label="US-BRACKET-10", tax_formula="10% of the bracket", rule_type="BRACKET", assessment_basis="ANNUAL",
                effective_from=date(2026, 1, 1),
                source_document_id=src.id),
    ])
    db.commit()
    clone = _new_version(db, pack, "1.1")
    for model in (ContributionRate, TaxSlab):
        assert _rows(db, model, clone.id) == _rows(db, model, pack.id), model.__tablename__

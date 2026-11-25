"""A new Belgian pack version copies its base version's rows UNSIGNED.

service._clone_pack_rates copies every column, the label included, and a
Belgian row's signed state is the absence of the "[PENDING G1]" label marker
— so a signed row used to arrive already signed in the new Draft. Now every
copied Belgian row (rates and slabs) carries the marker again and goes through
the governed signing; values, sources and dates are kept; the base version is
untouched; other countries are unaffected. SYNTHETIC data only."""
from datetime import date

from tests.test_belgium_super_admin import _c, _verified_source, seeded  # noqa: F401  (pytest fixture)


def _rows(db, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None)).all()
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None)).all()
    return rates, slabs


def _sign_directly(db, row, label_attr="label"):
    """Simulate a row signed in the console (marker removed, a value set)."""
    mark = _c().PENDING_MARK
    setattr(row, label_attr, getattr(row, label_attr).replace(mark, "").strip())
    db.commit()


def _new_version(db, base):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    return service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId=base.pack_id, version="1.1", jurisdictionCountry="BE", packType="tax", status="Draft",
        effectiveFrom=base.effective_from, effectiveTo=base.effective_to, taxYear=base.tax_year), actor_id=701)


def test_copied_rows_arrive_unsigned_with_their_values(db, seeded):
    from app.modules.payroll.models import TaxConfigurationAudit

    mark = _c().PENDING_MARK
    src = _verified_source(db)
    rates, _slabs = _rows(db, seeded)
    signed = rates[0]
    signed.text_value, signed.source_document_id = "SYNTHETIC", src.id
    _sign_directly(db, signed)
    assert mark not in signed.label

    new = _new_version(db, seeded)
    new_rates, _ = _rows(db, new)
    assert len(new_rates) == len(rates)
    assert all(mark in r.label for r in new_rates)                         # every copied row: unsigned
    copy = next(r for r in new_rates if r.component_key == signed.component_key)
    assert copy.text_value == "SYNTHETIC" and copy.source_document_id == src.id   # values / sources kept
    db.refresh(signed)
    assert mark not in signed.label                                        # the base version is untouched
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                    TaxConfigurationAudit.entity_id == new.id,
                                                    TaxConfigurationAudit.action == "update").one())
    assert audit.actor_id == 701 and audit.new_value["unsignedRows"] >= 1 and "signs them again" in audit.reason
    assert new.status == "Draft"                                           # nothing activated


def test_copied_slab_rows_arrive_unsigned(db, seeded):
    from app.modules.payroll.models import TaxSlab

    mark = _c().PENDING_MARK
    row = TaxSlab(jurisdiction_pack_id=seeded.id, organization_id=None, jurisdiction_country="BE",
                  rule_type="SYNTHETIC_BAND", rate_label="Synthetic band", min_amount=0, rate_pct=0, tax_formula="SYNTHETIC")
    db.add(row)
    db.commit()
    new = _new_version(db, seeded)
    _rates, slabs = _rows(db, new)
    copy = next(s for s in slabs if s.rule_type == "SYNTHETIC_BAND")
    assert copy.rate_label == f"Synthetic band {mark}"


def test_the_marker_survives_a_full_length_label():
    from app.modules.payroll import belgium_service as be

    mark = _c().PENDING_MARK
    out = be._with_pending_mark("x" * 100, 100)
    assert out.endswith(mark) and len(out) <= 100
    assert be._with_pending_mark(f"already {mark}", 100) == f"already {mark}"


def test_other_countries_keep_their_labels(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    first = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId="DE-NV-TEST", version="1.0", jurisdictionCountry="DE", packType="tax", status="Draft",
        effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31), taxYear="2026"))
    db.add(ContributionRate(organization_id=None, jurisdiction_country="DE", jurisdiction_pack_id=first.id,
                            component_key="syn", label="Synthetic", employee_share="—", employer_share="—", total="—"))
    db.commit()
    second = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        packId="DE-NV-TEST", version="1.1", jurisdictionCountry="DE", packType="tax", status="Draft",
        effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 12, 31), taxYear="2026"))
    copied = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == second.id).one()
    assert copied.label == "Synthetic"

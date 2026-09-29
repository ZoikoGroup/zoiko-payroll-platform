"""
tests/test_singapore_seed_idempotency.py
----------------------------------------
Singapore final completion programme (2026-09-29): re-running the canonical
seed must change NOTHING when the Draft pack already holds the canonical
values.

Found by the PostgreSQL seed rehearsal's row-version (xmin) fingerprints:
_upsert_pack bulk-deleted every canonical rate / slab row of the Draft
pack and the seed re-inserted them, so each re-run replaced 596 rates and
336 slabs with identical copies under new ids. Counts matched, so the
earlier count-only check could not see it. Now only rows whose values
differ are replaced.

app.* imports are lazy (tests/_db_safety.py).
"""

from decimal import Decimal


def _rows(db, pack_id):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    return {model.__tablename__: sorted(i for (i,) in db.query(model.id).filter(model.jurisdiction_pack_id == pack_id,
                                                                              model.organization_id.is_(None)))
            for model in (ContributionRate, TaxSlab)}


def _seed_audit(db, pack_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack", TaxConfigurationAudit.entity_id == pack_id)
            .order_by(TaxConfigurationAudit.id.desc()).first())


def test_a_second_seed_run_keeps_every_row_untouched(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore, seed_singapore_2027

    packs = [seed_singapore(db), seed_singapore_2027(db)]
    db.commit()
    before = {p.id: _rows(db, p.id) for p in packs}
    assert all(r["payroll_contribution_rates"] and r["payroll_tax_slabs"] for r in before.values())
    again = [seed_singapore(db), seed_singapore_2027(db)]
    db.commit()
    assert [p.id for p in again] == [p.id for p in packs]
    for p in packs:
        assert _rows(db, p.id) == before[p.id], p.version                 # same ids: nothing deleted or re-inserted
        assert _seed_audit(db, p.id).new_value["rowChanges"] == {
            "payroll_contribution_rates": {"inserted": 0, "deleted": 0},
            "payroll_tax_slabs": {"inserted": 0, "deleted": 0}}


def test_a_re_seed_restores_an_edited_draft_row_and_replaces_only_that_row(db):
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    before = _rows(db, pack.id)
    edited = (db.query(ContributionRate)
              .filter(ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.component_key == "sdl_max_monthly")
              .one())
    canonical = edited.flat_amount
    edited.flat_amount = Decimal("99.00")                               # a Draft edit that is not the canonical value
    db.commit()
    seed_singapore(db)
    db.commit()
    after = _rows(db, pack.id)
    assert edited.id not in after["payroll_contribution_rates"]           # the non-canonical row was replaced
    assert len(set(before["payroll_contribution_rates"]) - set(after["payroll_contribution_rates"])) == 1
    assert after["payroll_tax_slabs"] == before["payroll_tax_slabs"]      # nothing else moved
    restored = (db.query(ContributionRate)
                .filter(ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.component_key == "sdl_max_monthly")
                .one())
    assert restored.flat_amount == canonical == Decimal("11.25")
    assert _seed_audit(db, pack.id).new_value["rowChanges"]["payroll_contribution_rates"] == {"inserted": 1, "deleted": 1}

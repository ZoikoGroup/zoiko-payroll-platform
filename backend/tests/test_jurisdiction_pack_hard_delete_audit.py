"""Deleting a never-used jurisdiction pack still works with append-only audit rows (G5 F-6).

Regression found by the 2026-10-14 HK gap audit (defect D-E): the F-6 triggers made
hard_delete_jurisdiction_pack fail as soon as the pack had configuration-audit rows.
App modules are imported lazily (collection-order hazard)."""
import pytest


def _pack_with_audit(db):
    from app.modules.payroll.models import JurisdictionPack, TaxConfigurationAudit

    pack = JurisdictionPack(pack_id="ZZ-TEST", jurisdiction_country="HK", pack_type="tax", version="9.9", status="Draft")
    db.add(pack)
    db.commit()
    db.add(TaxConfigurationAudit(action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                                 jurisdiction_pack_id=pack.id))
    db.commit()
    return pack


def test_hard_delete_of_an_unused_pack_purges_its_audit_rows_inside_the_purge_scope(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack, TaxConfigurationAudit

    pack = _pack_with_audit(db)
    pack_id = pack.id
    service.hard_delete_jurisdiction_pack(db, pack_id)
    assert db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_id).first() is None
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.jurisdiction_pack_id == pack_id).count() == 0


def test_outside_the_purge_scope_the_same_delete_is_refused(db):
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.modules.payroll.models import TaxConfigurationAudit

    pack = _pack_with_audit(db)
    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id).delete()
        db.flush()
    db.rollback()

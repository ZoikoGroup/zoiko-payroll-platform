"""Belgium (ZP-BE-ENG-001): the governed Draft seed fits the real column widths.

Production defect 2026-11-18: Super Admin > Belgium > "Create the Draft pack" returned 500 — the seed writes the
earning-class obligation WITHHOLDING_EXCEPTIONAL (23 characters) into payroll_tax_slabs.tax_regime, which was
VARCHAR(20); PostgreSQL refused it, SQLite (every other test) silently accepted it. Fixed by c3e8a1d5f7b2
(tax_regime -> VARCHAR(40)).

  * everywhere (SQLite): every string the seed writes fits its column's DECLARED length — the whole class of defect,
    not only this column;
  * on a DISPOSABLE PostgreSQL (ZP_TEST_POSTGRES_URL, CI privacy-isolation job): from the production shape
    (tax_regime VARCHAR(20)) the migration widens the column, the real seed_draft then completes, a second seed is
    refused, and the downgrade refuses to truncate while Belgian rows hold a longer value.

Imports of app.* are lazy (collection-order DB-binding hazard)."""
import os

import pytest
import sqlalchemy as sa

from tests.test_belgium_super_admin import seeded  # noqa: F401  (pytest fixture)

PG_URL = os.environ.get("ZP_TEST_POSTGRES_URL")
REVISION = "c3e8a1d5f7b2"


def _string_overflows(db, model, pack_id_column, pack_id):
    """[(column, length, value)] for every string value of this pack's rows longer than its declared VARCHAR."""
    limited = [c for c in model.__table__.columns if isinstance(c.type, sa.String) and c.type.length]
    out = []
    for row in db.query(model).filter(getattr(model, pack_id_column) == pack_id):
        for col in limited:
            value = getattr(row, col.key)
            if isinstance(value, str) and len(value) > col.type.length:
                out.append((f"{model.__tablename__}.{col.name}", col.type.length, value))
    return out


def test_every_string_the_seed_writes_fits_its_declared_column(db, seeded):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    overflows = (_string_overflows(db, ContributionRate, "jurisdiction_pack_id", seeded.id)
                 + _string_overflows(db, TaxSlab, "jurisdiction_pack_id", seeded.id)
                 + _string_overflows(db, JurisdictionPack, "id", seeded.id))
    limited = [c for c in SourceArtifact.__table__.columns if isinstance(c.type, sa.String) and c.type.length]
    for src in db.query(SourceArtifact):
        for col in limited:
            value = getattr(src, col.key)
            if isinstance(value, str) and len(value) > col.type.length:
                overflows.append((f"{SourceArtifact.__tablename__}.{col.name}", col.type.length, value))
    assert overflows == [], overflows                    # PostgreSQL would refuse every one of these


def test_tax_regime_is_wide_enough_for_every_belgian_obligation():
    from app.modules.payroll.engine.countries import belgium_content as c
    from app.modules.payroll.models import TaxSlab

    width = TaxSlab.__table__.c.tax_regime.type.length
    assert max(len(o) for o in c.OBLIGATIONS) <= width, (width, max(c.OBLIGATIONS, key=len))


def test_the_widening_revision_is_the_single_head_on_the_report_field_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = ScriptDirectory.from_config(Config(os.path.join(here, "alembic.ini")))
    # UAE ad01fc67ce44 and the report-template content editor d7a3f1c9e5b2 both grow from this
    # revision; merge b5f3e8a1c6d9 joins them; Spain 86f1ec062709 and e4b7c2a9d1f3 (certification runs
    # tied to a pack) grow from it, joined by merge c8d2f6a4e1b9, the single head.
    assert script.get_heads() == ["c8d2f6a4e1b9"]
    assert script.get_revision("ad01fc67ce44").down_revision == REVISION
    assert script.get_revision("d7a3f1c9e5b2").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == "a4c7e1f9b3d8"


def _load_revision():
    import importlib.util

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "alembic", "versions", f"{REVISION}_widen_tax_slabs_tax_regime_40.py")
    spec = importlib.util.spec_from_file_location(f"rev_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not PG_URL, reason="ZP_TEST_POSTGRES_URL not set (disposable Postgres only)")
def test_postgres_seed_draft_from_the_production_column_shape():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.modules.payroll import be_super_admin
    from app.modules.payroll.engine.countries import belgium_content as c
    from app.modules.payroll.models import JurisdictionPack, TaxSlab
    from app.core.exceptions import BadRequestException
    from tests.test_belgium_migrations import pg_reset_public_schema

    engine = sa.create_engine(PG_URL, connect_args={"sslmode": "disable"} if "sslmode" not in PG_URL else {})
    revision = _load_revision()

    def step(name):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(revision, name)()

    def width():
        with engine.connect() as conn:
            return conn.execute(sa.text(
                "SELECT character_maximum_length FROM information_schema.columns WHERE table_schema = "
                "current_schema() AND table_name = 'payroll_tax_slabs' AND column_name = 'tax_regime'")).scalar()

    try:
        pg_reset_public_schema(engine)
        Base.metadata.create_all(engine)
        with engine.begin() as conn:                                         # the production shape before the fix
            conn.execute(sa.text("ALTER TABLE payroll_tax_slabs ALTER COLUMN tax_regime TYPE varchar(20)"))
        Session = sessionmaker(bind=engine, autoflush=False)

        db = Session()
        try:                                                                 # the production 500, reproduced
            with pytest.raises(sa.exc.DataError):
                be_super_admin.seed_draft(db, {"reason": "TEST ONLY: before the fix"}, None)
            db.rollback()
            assert db.query(JurisdictionPack).filter_by(jurisdiction_country="BE").count() == 0   # nothing kept
        finally:
            db.close()

        step("upgrade")
        assert width() == 40
        step("upgrade")                                                      # idempotent replay
        assert width() == 40

        db = Session()
        try:
            result = be_super_admin.seed_draft(db, {"reason": "TEST ONLY: after the fix"}, None)
            db.commit()
            pack = db.query(JurisdictionPack).filter_by(jurisdiction_country="BE").one()
            assert (pack.pack_id, pack.status) == ("BE-PAYROLL-2026", "Draft")
            assert result["availability"] == "PLANNED"
            classes = db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id, rule_type=c.EARNING_CLASS_RULE)
            assert classes.count() == len(c.OBLIGATIONS) * len(c.COMPONENTS)
            assert {s.tax_regime for s in classes} == set(c.OBLIGATIONS)
            assert not any(c.PENDING_MARK in (s.rate_label or "") for s in classes)      # no legacy marker
            with pytest.raises(BadRequestException):                         # create-only
                be_super_admin.seed_draft(db, {"reason": "TEST ONLY: second seed"}, None)
            db.rollback()
        finally:
            db.close()

        with pytest.raises(RuntimeError, match="never truncates"):          # Belgian rows hold 23 characters
            step("downgrade")
        assert width() == 40
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM payroll_tax_slabs WHERE char_length(tax_regime) > 20"))
        step("downgrade")
        assert width() == 20
        step("upgrade")
        assert width() == 40
    finally:
        engine.dispose()

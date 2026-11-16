"""Belgium (ZP-BE-ENG-001) Block I5: scripts/belgium_post_deploy_setup.py — idempotent, refuses, dry-run.

Synthetic, test SQLite only. The setup creates the PLANNED registry row, the Draft BE-PAYROLL-2026 pack (when no
Belgian pack exists) and the S1-S24 sources; it never signs, activates, assigns, changes a setting, creates the
DEMO pack, changes an existing row, or touches another country."""
import pytest


def _setup():
    import importlib

    return importlib.import_module("scripts.belgium_post_deploy_setup")


def _counts(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    return {"registry": db.query(JurisdictionServiceRegistry).count(), "packs": db.query(JurisdictionPack).count(),
            "sources": db.query(SourceArtifact).count(), "rates": db.query(ContributionRate).count(),
            "slabs": db.query(TaxSlab).count()}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("APP_ENV", raising=False)


def test_refusals(db, monkeypatch, env):
    from app.config import settings

    s = _setup()
    lines = []
    for kwargs, message in (({"environment": ""}, "--environment"),
                            ({"environment": "production"}, "does not match"),
                            ({"environment": "staging"}, "--confirm")):
        with pytest.raises(s.Refused, match=message):
            s.run(db, echo=lines.append, **kwargs)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    with pytest.raises(s.Refused, match="BE_DEMO_PACKS_ENABLED"):
        s.run(db, "production", confirm=True, echo=lines.append)
    assert _counts(db)["packs"] == 0 and _counts(db)["registry"] == 0                        # nothing written


def test_dry_run_plans_and_writes_nothing(db, env):
    s = _setup()
    before, lines = _counts(db), []
    out = s.run(db, "staging", dry_run=True, echo=lines.append)
    assert _counts(db) == before
    assert any("PLAN registry: create BE row PLANNED" in ln for ln in lines)
    assert any("PLAN pack: seed Draft BE-PAYROLL-2026" in ln for ln in lines)
    assert any("PLAN sources: register 24 of 24" in ln for ln in lines)
    assert not out["done"] and any(line.startswith("PASS 3.2") for line in lines)


def test_setup_is_create_only_idempotent_and_never_signs_activates_or_assigns(db, env, monkeypatch):
    from app.config import settings
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import (CompanyComplianceDetails, ContributionRate, JurisdictionPack,
                                            SourceArtifact, TaxSlab)
    from tests._mx_employer_helpers import make_org

    other = JurisdictionPack(pack_id="IN-TEST-2026", version="1.0", jurisdiction_country="IN", pack_type="tax",
                             status="Active")
    db.add(other)
    t = make_org(db, name="Other BV", code="BEPDS", country="BE")
    db.commit()
    settings_before = {k: getattr(settings, k) for k in dir(settings) if k.startswith("BE_")}
    s = _setup()
    lines = []
    first = s.run(db, "staging", confirm=True, echo=lines.append)
    assert dict((n, ok) for n, ok, _d in first["checks"])["3.1 alembic at the head"] is False   # no alembic_version here
    checks = {name: ok for name, ok, _d in first["checks"]}
    assert checks["3.2 Belgian tables"] and checks["3.5 Belgium not available"] and checks["3.6 no Belgian pack Active"]
    assert checks["3.7 no Belgian data rows"]

    reg = db.query(JurisdictionServiceRegistry).filter_by(country="BE").one()
    assert reg.availability == "PLANNED"
    pack = db.query(JurisdictionPack).filter_by(jurisdiction_country="BE").one()
    assert (pack.pack_id, pack.status) == (content.BE_2026[0], "Draft")
    rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id).all()
    slabs = db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).all()
    assert rates and all(content.PENDING_MARK in (r.label or "") for r in rates)               # nothing signed
    assert all(content.PENDING_MARK in (s_.rate_label or "") for s_ in slabs)
    forms = {f"ZP-BE-ENG-001 {code}" for code, *_ in content.SOURCE_REFERENCES}
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.in_(forms)).count() == len(forms) == 24
    assert not db.query(JurisdictionPack).filter(JurisdictionPack.pack_id.like("BE-DEMO%")).count()  # no DEMO pack
    assert db.query(CompanyComplianceDetails).filter_by(active_pack_id=pack.id).count() == 0        # not assigned
    assert db.get(JurisdictionPack, other.id).status == "Active"                                    # other country
    assert {k: getattr(settings, k) for k in dir(settings) if k.startswith("BE_")} == settings_before

    # idempotent: a second run changes nothing and says so
    reg.availability = "COMING_SOON"                                       # an existing row is never changed
    db.commit()
    before = _counts(db)
    lines2 = []
    s.run(db, "staging", confirm=True, echo=lines2.append)
    assert _counts(db) == before
    assert db.query(JurisdictionServiceRegistry).filter_by(country="BE").one().availability == "COMING_SOON"
    assert any("not seeded" in ln for ln in lines2) and any("all 24 registered" in ln for ln in lines2)
    assert any(ln.startswith("FAIL 3.5") for ln in lines2)                  # verification reports it honestly
    assert t.org.id                                                         # org untouched (no assignment)


def test_a_non_draft_pack_is_never_reseeded(db, env):
    from app.modules.payroll.models import JurisdictionPack

    db.add(JurisdictionPack(pack_id="BE-PAYROLL-2026", version="1.0", jurisdiction_country="BE", pack_type="tax",
                            status="Archived"))
    db.commit()
    s = _setup()
    lines = []
    s.run(db, "staging", confirm=True, echo=lines.append)
    assert db.query(JurisdictionPack).filter_by(jurisdiction_country="BE").count() == 1
    assert db.query(JurisdictionPack).filter_by(jurisdiction_country="BE").one().status == "Archived"
    assert any("not seeded" in ln for ln in lines)

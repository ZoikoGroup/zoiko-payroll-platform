"""Seeding the Malaysia pack (SQLite only; nothing here touches a real
database): the hardened seed script (dry run / --verify / --apply, the local
database guard plus the app-target check, masked target, exit codes) and the
seed blockers that protect console / workbook signing work."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.payroll import malaysia_service as mys
from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit, TaxSlab
from scripts import seed_malaysia_canonical_packs as script

LOCAL = "sqlite:///./my_seed_test.sqlite3"
REMOTE = "postgresql://payroll_user:s3cret-pw@db.example-remote.net:5432/zoiko_prod"


@pytest.fixture()
def run(db, monkeypatch, capsys):
    """Run the script's main() against the test database (never the app's
    configured engine): SessionLocal is bound to the test connection."""
    import app.database as database

    factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(database, "initialize_database", lambda: None)
    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def go(*argv, url=LOCAL):
        monkeypatch.setenv("PAYROLL_DATABASE_URL", url)
        try:
            code = script.main(list(argv))
        except SystemExit as exc:
            code = exc.code
        db.expire_all()
        return code, capsys.readouterr()

    return go


def _packs(db):
    return {p.pack_id: p for p in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "MY")}


def test_dry_run_writes_nothing(db, run):
    code, out = run()
    assert code == 0 and "dry run — nothing written" in out.out and "Existing packs: none." in out.out
    assert "MY_EPF_SCHEDULE" in out.out                                      # tables that stay empty are named
    assert _packs(db) == {}


def test_apply_seeds_a_draft_pack_and_registry_and_is_repeatable(db, run):
    code, _out = run("--apply")
    packs = _packs(db)
    assert code == 0 and set(packs) == {content.MY_2026[0]} and packs[content.MY_2026[0]].status == "Draft"
    summary = mys.my_seed_summary(db)
    main = summary["packs"][0]
    assert main["rates"] == summary["content"]["rates"] and main["slabs"] == summary["content"]["slabs"]
    assert main["pending"] == main["rates"] + main["slabs"]                 # every row PENDING G1
    assert main["activationRefusal"] and summary["registry"] == "PLANNED" and summary["blockers"] == []
    code, _ = run("--apply")                                                 # untouched Draft: safe re-run
    assert code == 0 and mys.my_seed_summary(db)["packs"] == summary["packs"]


def test_verify_is_read_only(db, run):
    run("--apply")
    before = db.query(TaxConfigurationAudit).count()
    code, out = run("--verify")
    assert code == 0 and "verify — nothing written" in out.out and "pending G1" in out.out
    assert db.query(TaxConfigurationAudit).count() == before


def test_apply_refuses_a_remote_database_without_the_override(db, run):
    code, out = run("--apply", url=REMOTE)
    assert code == 2 and "REFUSING" in out.err and _packs(db) == {}
    assert "s3cret-pw" not in out.out + out.err


def test_apply_refuses_when_only_an_ignored_database_url_looks_local(db, run, monkeypatch):
    """The app binds to PAYROLL_DATABASE_URL (environment, else settings); a
    local DATABASE_URL must never make a remote app target look safe."""
    from app.config import settings

    monkeypatch.setattr(settings, "PAYROLL_DATABASE_URL", REMOTE)
    monkeypatch.setenv("DATABASE_URL", LOCAL)

    def go():
        monkeypatch.delenv("PAYROLL_DATABASE_URL", raising=False)
        try:
            return script.main(["--apply"])
        except SystemExit as exc:
            return exc.code

    assert go() == 2 and _packs(db) == {}
    assert script.app_database_url() == REMOTE


def test_target_is_masked_and_never_shows_the_password(db, run):
    _code, out = run(url=REMOTE)
    assert "postgresql host=db.*** database=zoiko_prod" in out.out
    assert "s3cret-pw" not in out.out and "example-remote" not in out.out
    assert script.describe_target(LOCAL) == "sqlite (my_seed_test.sqlite3)"


def _seeded(db, run):
    run("--apply")
    return _packs(db)[content.MY_2026[0]]


def test_a_signed_row_blocks_a_re_seed(db, run):
    pack = _seeded(db, run)
    row = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id, component_key="my_min_wage_monthly",
                                               organization_id=None).one()
    row.label = row.label.replace(mys.PENDING_G1_SUFFIX, "")
    db.commit()
    assert "already being signed" in mys.my_seed_blockers(db)[0]
    code, out = run("--apply")
    assert code == 2 and "refused — nothing written" in out.out
    assert run()[0] == 2                                                     # the dry run says it would refuse
    db.refresh(row)
    assert not row.label.endswith("[PENDING G1]")                            # the signed work survived


def test_a_loaded_schedule_or_holiday_row_blocks_a_re_seed(db, run):
    pack = _seeded(db, run)
    db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="MY",
                   rule_type=content.MY_PUBLIC_HOLIDAY_RULE, min_amount=0, rate_pct=0,
                   rate_label="TEST holiday" + mys.PENDING_G1_SUFFIX, tax_formula=""))
    db.commit()
    assert "1 schedule/holiday/table row(s)" in mys.my_seed_blockers(db)[0]
    assert run("--apply")[0] == 2


def test_a_console_editor_blocks_a_re_seed(db, run):
    pack = _seeded(db, run)
    db.add(TaxConfigurationAudit(actor_id=7, action="update", entity_type="my_statutory_rate", entity_id=1,
                                 jurisdiction_pack_id=pack.id, reason="TEST edit"))
    db.commit()
    assert "1 editor(s)" in mys.my_seed_blockers(db)[0]


def test_a_pack_that_left_draft_is_never_rewritten(db, run):
    pack = _seeded(db, run)
    pack.status = "Active"
    db.commit()
    assert "is Active, not Draft" in mys.my_seed_blockers(db)[0]
    assert run("--apply")[0] == 2

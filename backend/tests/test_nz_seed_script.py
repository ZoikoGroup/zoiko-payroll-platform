"""Seeding the New Zealand pack (SQLite only; nothing here touches a real
database): the hardened seed script (dry run / --verify / --apply, the local
database guard, masked target), the seed blockers that protect console work,
the Super Admin "seed draft" action, and the local demo pack."""
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_super_admin as console
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.models import JurisdictionPack, SourceArtifact, TaxConfigurationAudit
from scripts import nz_local_demo_pack as demo
from scripts import seed_nz_canonical_packs as script

LOCAL = "sqlite:///./nz_seed_test.sqlite3"
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
    return {p.pack_id: p for p in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "NZ")}


def test_dry_run_writes_nothing(db, run):
    code, out = run()
    assert code == 0 and "dry run — nothing written" in out.out and "Existing packs: none." in out.out
    assert _packs(db) == {}


def test_apply_seeds_draft_packs_and_registry_and_is_repeatable(db, run):
    code, out = run("--apply")
    packs = _packs(db)
    assert code == 0 and set(packs) == {content.NZ_2026_27[0], content.NZ_ELA_2028[0]}
    assert {p.status for p in packs.values()} == {"Draft"}
    summary = nzs.nz_seed_summary(db)
    main = next(p for p in summary["packs"] if p["packId"] == content.NZ_2026_27[0])
    assert main["rates"] == summary["content"]["rates"] and main["slabs"] == summary["content"]["slabs"]
    assert main["pending"] == main["rates"] + main["slabs"]                 # every row PENDING G1
    assert "PENDING G1" in main["activationRefusal"] and summary["registry"] == "PLANNED"
    assert summary["blockers"] == []
    code, _ = run("--apply")                                                 # unchanged re-run
    assert code == 0 and nzs.nz_seed_summary(db)["packs"] == summary["packs"]


def test_verify_is_read_only_and_reports_the_activation_refusal(db, run):
    run("--apply")
    before = db.query(TaxConfigurationAudit).count()
    code, out = run("--verify")
    assert code == 0 and "verify — nothing written" in out.out and "PENDING G1" in out.out
    assert db.query(TaxConfigurationAudit).count() == before


def test_apply_refuses_a_remote_database_without_the_override(db, run):
    code, out = run("--apply", url=REMOTE)
    assert code == 2 and "REFUSING" in out.err and _packs(db) == {}
    assert "s3cret-pw" not in out.out + out.err


def test_target_is_masked_and_never_shows_the_password(db, run):
    _code, out = run(url=REMOTE)
    assert "postgresql host=db.*** database=zoiko_prod" in out.out
    assert "s3cret-pw" not in out.out and "example-remote" not in out.out
    assert script.describe_target(LOCAL) == "sqlite (nz_seed_test.sqlite3)"


def test_console_work_blocks_a_re_seed(db, run):
    run("--apply")
    pack = _packs(db)[content.NZ_2026_27[0]]
    from app.modules.auth.models import User, UserRole

    users = []
    for email in ("nz-seed-a@zoikotest.example.com", "nz-seed-b@zoikotest.example.com"):
        user = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S", last_name="A",
                    is_active=True)
        db.add(user)
        db.commit()
        users.append(user.id)
    source = SourceArtifact(agency="Inland Revenue", title="TEST source", retrieved_at=datetime(2026, 11, 1),
                            checksum_sha256="c" * 64, file_path="nz/test.pdf", created_by_id=users[0],
                            reviewer_id=users[1])
    db.add(source)
    db.commit()
    console.add_table_row(db, pack.id, "NZ_PUBLIC_HOLIDAY", {"reason": "TEST", "sourceDocumentId": source.id,
                                                              "date": "2026-12-25", "name": "TEST Christmas"},
                          users[0])
    db.commit()
    assert "already being signed" in nzs.nz_seed_blockers(db)[0]
    code, out = run("--apply")
    assert code == 2 and "refused — nothing written" in out.out
    assert run()[0] == 2                                                     # the dry run says it would refuse
    pack.status = "Active"
    db.commit()
    assert "is Active, not Draft" in nzs.nz_seed_blockers(db)[0]


# ── Super Admin "seed draft" ────────────────────────────────────────────────
def test_console_seed_draft_needs_a_reason_and_only_runs_once(db):
    with pytest.raises(BadRequestException, match="reason"):
        console.seed_draft(db, {"reason": " "}, 7)
    summary = console.seed_draft(db, {"reason": "Start New Zealand signing"}, 7)
    db.commit()
    assert {p["packId"] for p in summary["packs"]} == {content.NZ_2026_27[0], content.NZ_ELA_2028[0]}
    assert summary["registry"] == "PLANNED"
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                    TaxConfigurationAudit.actor_id == 7).one())
    assert "Start New Zealand signing" in audit.reason and audit.action == "create"
    with pytest.raises(BadRequestException, match="already seeded"):
        console.seed_draft(db, {"reason": "again"}, 7)


def test_seed_draft_route_is_super_admin_only():
    from app.modules.super_admin import router as sa

    route = next(r for r in sa.router.routes if getattr(r, "path", "").endswith("/compliance/new-zealand/seed-draft"))
    deps = {d.call.__name__ for d in route.dependant.dependencies}
    assert route.methods == {"POST"} and "get_current_super_admin" in deps


# ── local demo pack ─────────────────────────────────────────────────────────
def test_demo_refuses_every_remote_database_even_with_the_override(monkeypatch):
    monkeypatch.setenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", "I_UNDERSTAND")
    with pytest.raises(SystemExit) as exc:
        demo.refuse_unless_local(REMOTE)
    assert exc.value.code == 2
    demo.refuse_unless_local(LOCAL)                                          # local: allowed


def test_demo_builds_an_active_pack_through_the_governed_path(db):
    pack = demo.build_demo_pack(db)
    assert pack.status == "Active" and pack.change_summary == demo.DEMO_NOTE
    assert nzs.nz_pack_activation_refusal(db, pack) is None
    assert demo.build_demo_pack(db).id == pack.id                            # re-run: already Active
    editors = nzs._nz_statutory_editors(db, pack)
    assert pack.approved_by_id not in editors and len(editors) == 1          # maker signed; checker approved


"""
scripts/nz_local_demo_pack.py
-----------------------------
LOCAL DEMO ONLY: an Active New Zealand pack on a local database, so the NZ
screens can be clicked through end to end.

It seeds the Draft NZ-PAYROLL-2026-27 pack (if missing), signs every row and
fills every authority table through the governed Super Admin console with the
TEST values the test suite uses (tests/_nz_engine_helpers.py), then approves
and activates it with three inactive local demo Super Admins (maker, checker,
activator) — the same governance path a real pack takes.

TEST values are NOT statutory content. This script refuses every non-local
database ALWAYS — the ZOIKO_ALLOW_NONLOCAL_DB_WRITES override is deliberately
not honoured here. A real pack is signed by Super Admins in the console.

It does not turn New Zealand on: set NZ_TENANT_ONBOARDING_ENABLED=true in your
own local environment to use the organisation screens.

Usage:
    PAYROLL_DATABASE_URL=sqlite:///./nz_demo.sqlite3 python -m scripts.nz_local_demo_pack
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import _configured_database_url, is_local_database  # noqa: E402

NAME = "nz_local_demo_pack"
DEMO_USERS = ("zzz.nz-demo-maker@zoiko.internal", "zzz.nz-demo-checker@zoiko.internal",
              "zzz.nz-demo-activator@zoiko.internal")
DEMO_NOTE = "LOCAL DEMO — signed with TEST values from the test suite; not statutory content"


def refuse_unless_local(url: str) -> None:
    if is_local_database(url):
        return
    print(f"[{NAME}] REFUSING — this demo only ever runs on a local SQLite or loopback database "
          "(no override exists). A real New Zealand pack is signed in the Super Admin console.", file=sys.stderr)
    raise SystemExit(2)


def _demo_user(db, email: str) -> int:
    from app.modules.auth.models import User, UserRole

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        # Inactive, with no usable password: these ids only sign the demo pack.
        user = User(email=email, hashed_password="!", role=UserRole.SUPER_ADMIN, first_name="NZ demo",
                    last_name=email.split("@")[0][-9:], is_active=False)
        db.add(user)
        db.flush()
    return user.id


def build_demo_pack(db) -> "JurisdictionPack":  # noqa: F821
    from app.modules.payroll import new_zealand_service as nzs
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.models import JurisdictionPack, SourceArtifact
    from tests._nz_engine_helpers import sign_with_test_values

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == content.NZ_2026_27[0], JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status == "Active":
        return pack
    blockers = nzs.nz_seed_blockers(db)
    if blockers:
        raise SystemExit(f"[{NAME}] refused: {'; '.join(blockers)}. Use a fresh local database for the demo.")
    pack = nzs.seed_nz_pack(db)
    nzs.ensure_nz_service_registry_row(db)
    db.commit()
    maker, checker, activator = (_demo_user(db, email) for email in DEMO_USERS)
    source = SourceArtifact(agency="Inland Revenue", title=f"TEST source — {DEMO_NOTE}", retrieved_at=datetime.utcnow(),
                            checksum_sha256="0" * 64, file_path="local-demo/nz-test-source.pdf",
                            created_by_id=maker, reviewer_id=checker)
    db.add(source)
    db.commit()
    sign_with_test_values(db, pack, source.id, maker, reason=DEMO_NOTE)
    pack.change_summary = DEMO_NOTE
    db.commit()
    service.set_jurisdiction_pack_approver(db, pack.id, checker)
    service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=activator)
    db.commit()
    db.refresh(pack)
    return pack


def main() -> int:
    url = _configured_database_url()
    refuse_unless_local(url)
    from app.database import SessionLocal, initialize_database

    initialize_database()
    db = SessionLocal()
    try:
        pack = build_demo_pack(db)
        print(f"[{NAME}] {pack.pack_id} v{pack.version} (id={pack.id}) is {pack.status} — {DEMO_NOTE}.")
        print(f"[{NAME}] Next: set NZ_TENANT_ONBOARDING_ENABLED=true in your local environment to use the "
              "New Zealand organisation screens.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

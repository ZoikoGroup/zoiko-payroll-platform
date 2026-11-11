"""Rotate Japan My Number ciphertexts to the newest JP_MY_NUMBER_KEYRING version.

ZP-JP-ENG-001 Phase 9 (release gate G6). Every ACTIVE vault row not yet under
the newest key version is decrypted with its owner binding and re-encrypted
under the newest version; the duplicate fingerprint (its own, non-rotating
key) must still match. Prints counts and row ids only — never a number.

Default is a DRY RUN that writes nothing. ``--apply`` writes. The
local-database guard refuses any non-local database unless
``--confirm-remote`` is also given — for the documented production rotation
(docs/japan/RUNBOOK_GO_LIVE.md), run by the approved operator only.

Usage:
    python -m scripts.rotate_jp_my_number_keys            # dry run, local DB
    python -m scripts.rotate_jp_my_number_keys --apply    # write, local DB
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the re-encrypted rows (default: dry run)")
    parser.add_argument("--confirm-remote", action="store_true",
                        help="allow a non-local database (documented production rotation only)")
    args = parser.parse_args(argv)
    if not args.confirm_remote:
        assert_local_database("rotate_jp_my_number_keys")

    from app.database import SessionLocal
    from app.modules.payroll import japan_service

    db = SessionLocal()
    try:
        out = japan_service.rotate_my_number_keys(db, dry_run=not args.apply)
        if args.apply and not out["failed"]:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(out, indent=2))
        return 1 if out["failed"] else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

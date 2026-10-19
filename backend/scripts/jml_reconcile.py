"""
scripts/jml_reconcile.py
------------------------
ZP-PRIV E05 joiner / mover / leaver. Reads HR / IdP events and, for staff
exit, role change, incident revocation or grant expiry: deactivates the
account, revokes refresh sessions (access tokens die on the per-request DB
check), ends live support grants, and prints a reconciliation (ids only).

Input JSON: [{"email": "...", "event": "leaver|mover|incident|grant_expiry", "new_role": "..."}]

    python -m scripts.jml_reconcile events.json              # dry run
    python -m scripts.jml_reconcile events.json --apply      # make the changes
    python -m scripts.jml_reconcile --sample --output ../docs/privacy/evidence_pack/EP-02/jml_reconciliation_sample.json

Idempotent: an already-deactivated user produces no new deactivation.
Proof status: awaiting HR / IdP owner (HP-05) to connect the real feed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._privacy_script_db import live_session, synthetic_session, write_json  # noqa: E402


def _sample(db) -> list:
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    users = []
    for email, role in (("leaver@staff.example", UserRole.SUPPORT_OPERATOR),
                        ("mover@staff.example", UserRole.PLATFORM_SECURITY),
                        ("incident@staff.example", UserRole.SUPER_ADMIN)):
        u = User(email=email, hashed_password=hash_password("Sample-Only-Password-1!"), role=role,
                 first_name="Sample", last_name="Staff", is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.commit()
    return [{"user_id": users[0].id, "event": "leaver"},
            {"user_id": users[1].id, "event": "mover", "new_role": "support_operator"},
            {"user_id": users[2].id, "event": "incident"},
            {"email": "unknown@staff.example", "event": "leaver"}]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Joiner / mover / leaver reconciliation.")
    parser.add_argument("events", nargs="?", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sample", action="store_true", help="run on synthetic staff in a throwaway database")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    from app.modules.security.ops import jml_reconcile

    if args.sample:
        db = synthetic_session()
        try:
            hr = _sample(db)
            dry = jml_reconcile(db, hr, apply=False)
            applied = jml_reconcile(db, hr, apply=True)
            rerun = jml_reconcile(db, hr, apply=True)
        finally:
            db.close()
        write_json(args.output, {"dryRun": dry, "applied": applied, "rerun": rerun,
                                 "note": "synthetic sample; awaiting HR / IdP owner (HP-05)"})
        return 0
    if args.events is None:
        parser.error("events file required (or --sample)")
    hr_events = json.loads(args.events.read_text(encoding="utf-8"))
    db = live_session()
    try:
        write_json(args.output, jml_reconcile(db, hr_events, apply=args.apply))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

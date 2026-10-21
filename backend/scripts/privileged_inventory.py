"""
scripts/privileged_inventory.py
-------------------------------
ZP-PRIV E04: export the privileged access inventory (privileged humans,
machine accounts, active and emergency grants, last login, MFA status) -
the same data as GET /api/super-admin/privileged-inventory. Read-only.
Tenant-plane accounts are listed without their email.

    python -m scripts.privileged_inventory [--output PATH] [--synthetic]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._privacy_script_db import live_session, synthetic_session, write_json  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export the privileged access inventory.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--synthetic", action="store_true", help="empty throwaway database (format check)")
    args = parser.parse_args(argv)
    from app.modules.security.inventory import build_inventory

    db = synthetic_session() if args.synthetic else live_session()
    try:
        write_json(args.output, build_inventory(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

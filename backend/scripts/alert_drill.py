"""
scripts/alert_drill.py
----------------------
ZP-PRIV E03: fire every security alert rule and record the delivery
receipts. Idempotent (each run uses its own drill tag).

    python -m scripts.alert_drill                       # synthetic DB, real detection path
    python -m scripts.alert_drill --live                # deployment: labelled drill alerts only
    python -m scripts.alert_drill --output ../docs/privacy/evidence_pack/EP-05/alert_drill.json

Exits 1 when any rule did not fire or was not delivered.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._privacy_script_db import live_session, synthetic_session, write_json  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fire every alert rule and record delivery receipts.")
    parser.add_argument("--live", action="store_true", help="use the configured database (labelled drill alerts)")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    from app.modules.security.ops import run_alert_drill

    db = live_session() if args.live else synthetic_session()
    try:
        result = run_alert_drill(db, live=args.live)
    finally:
        db.close()
    write_json(args.output, result)
    for r in result["rules"]:
        print(f"{'FIRED' if r['fired'] else 'MISSING':8} {r['rule']:<30} {r['deliveryReceipt'] or '-'}")
    return 0 if result["allFired"] and result["allDelivered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

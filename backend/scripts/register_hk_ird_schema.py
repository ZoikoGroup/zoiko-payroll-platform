"""
scripts/register_hk_ird_schema.py
---------------------------------
Register an OFFICIAL IRD electronic schema file (supplied by the IRD) for a
Hong Kong form and year of assessment — G2 readiness. See
app/modules/payroll/hong_kong_service.py. Refuses non-local databases
(scripts/_local_db_guard); a production registration needs the owner's
explicit ZOIKO_ALLOW_NONLOCAL_DB_WRITES override.

Usage (from backend/):
  python -m scripts.register_hk_ird_schema --form IR56B --ya 2025/26 --file path/to/ir56b.xsd [--url https://...]
  python -m scripts.register_hk_ird_schema --readiness --ya 2025/26
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._local_db_guard import assert_local_database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--form")
    parser.add_argument("--ya", required=True)
    parser.add_argument("--file")
    parser.add_argument("--url")
    parser.add_argument("--readiness", action="store_true")
    args = parser.parse_args()
    from app.database import SessionLocal
    from app.modules.payroll import hong_kong_service

    db = SessionLocal()
    try:
        if args.readiness:
            for row in hong_kong_service.readiness(db, args.ya):
                print(row)
            return
        assert_local_database("register_hk_ird_schema")
        art = hong_kong_service.register_schema(db, args.form, args.ya, args.file, source_url=args.url)
        print({"artifactId": art.id, "form": args.form, "ya": args.ya, "sha256": art.checksum_sha256})
    finally:
        db.close()


if __name__ == "__main__":
    main()

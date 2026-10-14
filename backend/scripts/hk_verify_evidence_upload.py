"""
Hong Kong evidence upload check — READ-ONLY.

    python -m scripts.hk_verify_evidence_upload docs/hk-evidence/UPLOAD_KIT/manifest.csv [--out report.json]

For every manifest row (file, tag, title, issuer, sha256), looks up the current
(not superseded) Source Evidence artifacts with that tag and reports:

  MATCH            an artifact with this title and the manifest SHA-256 exists
  DIGEST_MISMATCH  an artifact with this title exists but its stored SHA-256 differs
  NOT_UPLOADED     the artifact is registered but has no file yet
  MISSING          nothing with this tag and title

It also reports the review state (reviewer recorded, and whether it is a
different person from the registrant) so nobody mistakes "uploaded" for
"accepted". SELECT statements only; the session is switched to read-only before
any query, so PostgreSQL refuses writes. Exit code 0 only when every row is MATCH.
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import engine

QUERY = text(
    "SELECT id, title, agency, checksum_sha256, file_path IS NOT NULL AS has_file, created_by_id, reviewer_id "
    "FROM payroll_source_artifacts WHERE form_number = :tag AND superseded_by_id IS NULL ORDER BY id"
)


def check(manifest_path: str) -> dict:
    rows = list(csv.DictReader(open(manifest_path, encoding="utf-8")))
    results = []
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET SESSION default_transaction_read_only = on"))
            conn.commit()
            conn.execute(text("SET TRANSACTION READ ONLY"))
        for r in rows:
            found = [dict(x._mapping) for x in conn.execute(QUERY, {"tag": r["tag"]})]
            same_title = [f for f in found if (f["title"] or "").strip() == r["title"].strip()]
            if not same_title:
                status, art = "MISSING", None
            else:
                art = next((f for f in same_title if (f["checksum_sha256"] or "") == r["sha256"]), same_title[-1])
                status = ("MATCH" if art["checksum_sha256"] == r["sha256"] else
                          "NOT_UPLOADED" if not art["has_file"] else "DIGEST_MISMATCH")
            results.append({
                "file": r["file"], "tag": r["tag"], "title": r["title"], "expectedSha256": r["sha256"], "status": status,
                "artifactId": art["id"] if art else None,
                "storedSha256": art["checksum_sha256"] if art else None,
                "reviewed": bool(art and art["reviewer_id"]),
                "independentReview": bool(art and art["reviewer_id"] and art["reviewer_id"] != art["created_by_id"]),
            })
        conn.rollback()
    report = {"checkedAt": datetime.now(timezone.utc).isoformat(), "database": {"host": engine.url.host, "name": engine.url.database},
              "manifest": manifest_path, "manifestSha256": hashlib.sha256(open(manifest_path, "rb").read()).hexdigest(),
              "counts": {s: sum(1 for x in results if x["status"] == s) for s in ("MATCH", "DIGEST_MISMATCH", "NOT_UPLOADED", "MISSING")},
              "results": results}
    report["reportSha256"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only check of uploaded HK evidence against the manifest")
    ap.add_argument("manifest")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    report = check(args.manifest)
    body = json.dumps(report, indent=1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(body)
    print(json.dumps(report["counts"]), "reportSha256=" + report["reportSha256"])
    for x in report["results"]:
        if x["status"] != "MATCH":
            print(f"  {x['status']:16} {x['tag']:28} {x['file']}")
    return 0 if report["counts"]["MATCH"] == len(report["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())

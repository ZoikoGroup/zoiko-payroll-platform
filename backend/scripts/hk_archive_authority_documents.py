"""
Hong Kong G1 / G2 evidence: archive official authority documents with their SHA-256.

    python -m scripts.hk_archive_authority_documents --manifest docs/hk-evidence/G2/authority_documents.csv \
        --archive <archive-dir> [--fetch]

The manifest CSV has columns: doc_id, authority, title, url, local_file.
For each row:

* with ``local_file`` set, the file a person downloaded from the official
  site is hashed and copied into the archive;
* with ``--fetch`` and no ``local_file``, the document is downloaded from
  ``url`` (recording the HTTP status, content type and UTC time) and
  archived. Only https URLs on the official authority domains are fetched.

The archived copy is named ``<sha256>__<original name>``. The register
(``register.csv`` plus ``register.json`` in the archive directory) records
doc_id, authority, title, url, retrieved_at, bytes and sha256, together with the
register's own SHA-256. Use the register to fill the ``source_document_sha256``
column of the G1 worksheet, and upload the archived file to Source Evidence.

Nothing is sent anywhere, and no database is touched. A row whose file is
missing, or whose fetch fails, is reported as MISSING. It is never skipped
silently and never given a placeholder hash.
"""

import argparse
import csv
import hashlib
import json
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

OFFICIAL_DOMAINS = ("ird.gov.hk", "mpfa.org.hk", "empf.org.hk", "labour.gov.hk", "info.gov.hk", "pcpd.org.hk",
                    "elegislation.gov.hk", "gov.hk")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _official(url: str) -> bool:
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _fetch(url: str) -> tuple:
    req = urllib.request.Request(url, headers={"User-Agent": "Zoiko-Payroll-evidence-archiver/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:     # noqa: S310 — https + official domains only
        return resp.read(), resp.status, resp.headers.get("Content-Type", "")


def archive(manifest: Path, archive_dir: Path, fetch: bool) -> dict:
    archive_dir.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    out = []
    for r in rows:
        entry = {k: (r.get(k) or "").strip() for k in ("doc_id", "authority", "title", "url", "local_file")}
        entry.update({"status": "MISSING", "sha256": "", "bytes": 0, "retrieved_at": "", "archived_as": "", "note": ""})
        try:
            if entry["local_file"]:
                src = (manifest.parent / entry["local_file"]).resolve() if not Path(entry["local_file"]).is_absolute() \
                    else Path(entry["local_file"])
                data, name = src.read_bytes(), src.name
                entry["note"] = "hashed from a file downloaded by a person"
            elif fetch:
                if not _official(entry["url"]):
                    raise ValueError("not an https URL on an official Hong Kong authority domain")
                data, status, ctype = _fetch(entry["url"])
                name = Path(urlparse(entry["url"]).path).name or f"{entry['doc_id']}.bin"
                entry["note"] = f"fetched: HTTP {status}, {ctype}"
            else:
                raise FileNotFoundError("no local_file and --fetch not given")
            if not data:
                raise ValueError("empty document")
            digest = _sha256(data)
            target = archive_dir / f"{digest}__{name}"
            if not target.exists():
                target.write_bytes(data)
            entry.update({"status": "ARCHIVED", "sha256": digest, "bytes": len(data), "archived_as": target.name,
                          "retrieved_at": datetime.now(timezone.utc).isoformat()})
        except Exception as exc:                             # reported, never hidden
            entry["note"] = f"MISSING — {type(exc).__name__}: {exc}"
        out.append(entry)
    fields = ["doc_id", "authority", "title", "url", "status", "sha256", "bytes", "retrieved_at", "archived_as", "note"]
    with (archive_dir / "register.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    register = {"generatedAt": datetime.now(timezone.utc).isoformat(), "manifest": str(manifest),
                "manifestSha256": _sha256(manifest.read_bytes()), "documents": out,
                "archived": sum(1 for e in out if e["status"] == "ARCHIVED"),
                "missing": sum(1 for e in out if e["status"] != "ARCHIVED")}
    register["registerSha256"] = _sha256(json.dumps(register, sort_keys=True).encode())
    (archive_dir / "register.json").write_text(json.dumps(register, indent=1), encoding="utf-8")
    return register


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Archive Hong Kong authority documents with SHA-256")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--archive", required=True, type=Path)
    ap.add_argument("--fetch", action="store_true", help="download rows without local_file from their official URL")
    args = ap.parse_args(argv)
    reg = archive(args.manifest, args.archive, args.fetch)
    print(f"archived {reg['archived']}, missing {reg['missing']}, registerSha256={reg['registerSha256']}")
    for e in reg["documents"]:
        print(f"  {e['status']:8} {e['doc_id']:14} {e['sha256'][:16] or '-':16} {e['note']}")
    return 0 if reg["missing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

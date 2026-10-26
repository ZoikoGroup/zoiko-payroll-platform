"""
modules/payroll/mexico_sources.py
---------------------------------
The Mexico source manifest (docs/mexico/sources/SOURCES_MANIFEST.csv) as the
seed and the activation gate read it (Phase 11d, gap register A9).

* Status rule (2026-10-26): a source saved as an ``ARCHIVE_COPY_VERIFIED``
  Internet Archive capture may back rows in a **Draft** pack only. Activation
  and G1 need ``VERIFIED`` — the file downloaded directly from its official URL.
* Keyed by file as well as by code: a code can have several saved files (S28,
  S30). A content row cites either the bare code — valid only while that code
  has exactly one usable file — or ``CODE/file``.
* A ``VERIFIED`` row counts only with a matching ``MATCH`` entry (same code,
  file, URL and SHA-256) in VERIFICATION_LOG.csv beside the manifest. Only
  ``scripts/verify_mexico_sources.py verify`` writes one, after a fresh direct
  download from the official URL hashes to the saved copy. A row marked
  VERIFIED by hand, with no entry, is not usable anywhere.

The manifest ships with the repository (production runs from the git
checkout, as ``security/assurance.py`` reads docs/privacy). If it cannot be
read, nothing is treated as verified.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = REPO_ROOT / "docs" / "mexico" / "sources" / "SOURCES_MANIFEST.csv"

VERIFIED = "VERIFIED"
ARCHIVE_COPY_VERIFIED = "ARCHIVE_COPY_VERIFIED"
DRAFT_STATUSES = (VERIFIED, ARCHIVE_COPY_VERIFIED)     # may back a row in a Draft pack
ACTIVATION_STATUSES = (VERIFIED,)                     # may back a row in a pack being activated
LOG_NAME = "VERIFICATION_LOG.csv"
LOG_COLUMNS = ("code", "file", "url", "final_url", "downloaded_at", "downloader", "response_bytes", "sha256",
               "result")


def read_rows(path: Optional[Path] = None) -> list:
    path = Path(path or MANIFEST_PATH)
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def log_path(manifest_path: Optional[Path] = None) -> Path:
    return Path(manifest_path or MANIFEST_PATH).parent / LOG_NAME


def read_log(manifest_path: Optional[Path] = None) -> list:
    """The verification log beside the manifest ([] if missing)."""
    return read_rows(log_path(manifest_path))


def logged(row: dict, log_rows: Iterable[dict]) -> bool:
    """Has this manifest row a successful direct-download verification?"""
    return any(e.get("result") == "MATCH" and e.get("code") == row.get("code") and e.get("file") == row.get("file")
               and e.get("url") == row.get("url") and e.get("sha256") == row.get("sha256") for e in log_rows)


def effective_status(row: dict, log_rows: Iterable[dict]) -> str:
    status = (row.get("status") or "").strip()
    if status == VERIFIED and not logged(row, log_rows):
        return "VERIFIED_WITHOUT_LOG"                 # never usable
    return status


def cite_key(row: dict) -> str:
    return f"{row['code']}/{row['file']}"


def usable(rows: Iterable[dict], statuses: tuple = DRAFT_STATUSES, log_rows: Iterable[dict] = ()) -> dict:
    """{cite: row}: every usable file under ``CODE/file``, plus the bare
    ``CODE`` when that code has exactly one usable file. A VERIFIED row
    without a log entry in ``log_rows`` is skipped."""
    out, by_code = {}, {}
    log_rows = list(log_rows)
    for row in rows:
        if effective_status(row, log_rows) not in statuses:
            continue
        out[cite_key(row)] = row
        by_code.setdefault(row["code"], []).append(row)
    for code, files in by_code.items():
        if len(files) == 1:
            out[code] = files[0]
    return out


def missing_reason(manifest: dict, cite: str) -> str:
    """Why ``cite`` is not usable (for the seed's refusal)."""
    if "/" not in cite and any(k.startswith(cite + "/") for k in manifest):
        files = sorted(k for k in manifest if k.startswith(cite + "/"))
        return f"{cite} has {len(files)} saved files — cite one of them ({', '.join(files)})"
    return f"SOURCES_MANIFEST.csv has no usable file for {cite}"


def verified_artifact(rows: Iterable[dict], url: Optional[str], sha256: Optional[str],
                      log_rows: Iterable[dict] = ()) -> bool:
    """Is an artifact (URL + SHA-256) backed by a manifest row that is
    VERIFIED and has a matching verification-log entry?"""
    log_rows = list(log_rows)
    return any(effective_status(r, log_rows) in ACTIVATION_STATUSES and r.get("sha256") == sha256
               and (r.get("url") or "") == (url or "") for r in rows)

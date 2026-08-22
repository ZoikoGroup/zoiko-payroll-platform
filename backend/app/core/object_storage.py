"""
core/object_storage.py
----------------------
Storage abstraction for uploaded files (compliance documents, org logos).

Cloud Run's filesystem is ephemeral — writes to local disk are lost whenever
an instance recycles. In production these uploads MUST go to Cloud Storage;
locally (dev/tests) the plain-disk backend keeps the previous behavior.

Selection:
  - PAYROLL_STORAGE_BACKEND = "gcs" | "local" | "auto" (default "auto")
  - "auto" uses GCS when PAYROLL_GCS_BUCKET is set, otherwise local disk.

References stored in the DB:
  - GCS:      gs://<bucket>/<key>
  - Local:    absolute filesystem path (unchanged from the old behavior)

GCS auth uses Application Default Credentials (the Cloud Run service
account, which needs roles/storage.objectAdmin on the uploads bucket — see
GCP_DEPLOYMENT.md §9.4). Locally, `gcloud auth application-default login`.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("zoiko_payroll.object_storage")

_GCS_PREFIX = "gs://"


def _backend() -> str:
    configured = os.environ.get("PAYROLL_STORAGE_BACKEND", "auto").strip().lower()
    if configured in {"gcs", "local"}:
        return configured
    return "gcs" if os.environ.get("PAYROLL_GCS_BUCKET") else "local"


def using_gcs() -> bool:
    return _backend() == "gcs"


def is_gcs_ref(ref: Optional[str]) -> bool:
    return bool(ref) and ref.startswith(_GCS_PREFIX)


def _parse_gcs_ref(ref: str) -> tuple[str, str]:
    without_scheme = ref[len(_GCS_PREFIX):]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid GCS reference: {ref!r}")
    return bucket, key


_bucket_client_cache: dict[str, object] = {}


def _get_bucket(bucket_name: Optional[str] = None):
    from google.cloud import storage as gcs_storage

    name = bucket_name or os.environ.get("PAYROLL_GCS_BUCKET")
    if not name:
        raise RuntimeError(
            "PAYROLL_GCS_BUCKET is not set but the GCS storage backend is active."
        )
    if name not in _bucket_client_cache:
        client = gcs_storage.Client()
        _bucket_client_cache[name] = client.bucket(name)
    return _bucket_client_cache[name]


def save_upload(*, subdir: str, filename: str, data: bytes) -> str:
    """Persist upload bytes; returns the reference to store on the DB row."""
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise ValueError("Upload filename must not be empty.")

    if using_gcs():
        prefix = os.environ.get("PAYROLL_GCS_UPLOAD_PREFIX", "").strip("/")
        key = "/".join(p for p in (prefix, subdir.strip("/"), safe_name) if p)
        blob = _get_bucket().blob(key)
        blob.upload_from_string(data)
        logger.info("Uploaded %s bytes to gs://%s/%s", len(data), _bucket_name(), key)
        return f"{_GCS_PREFIX}{_bucket_name()}/{key}"

    base_dir = os.environ.get(
        "UPLOAD_BASE_DIR", "/tmp/uploads"
    )
    directory = os.path.join(base_dir, subdir)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, safe_name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def read_bytes(ref: str) -> bytes:
    """Read back an upload by DB-stored reference (gs:// URI or local path)."""
    if is_gcs_ref(ref):
        bucket, key = _parse_gcs_ref(ref)
        return _get_bucket(bucket).blob(key).download_as_bytes()
    with open(ref, "rb") as fh:
        return fh.read()


def exists(ref: str) -> bool:
    if is_gcs_ref(ref):
        bucket, key = _parse_gcs_ref(ref)
        return _get_bucket(bucket).blob(key).exists()
    return os.path.isfile(ref)


def delete_ref(ref: str) -> None:
    """Best-effort delete; missing objects are ignored so DB cleanup never
    fails because a file was already removed."""
    if not ref:
        return
    try:
        if is_gcs_ref(ref):
            bucket, key = _parse_gcs_ref(ref)
            _get_bucket(bucket).blob(key).delete()
        elif os.path.isfile(ref):
            os.remove(ref)
    except FileNotFoundError:
        pass
    except Exception as exc:
        # GCS missing-object surfaces as NotFound (404) or, on delete with a
        # generation precondition, PreconditionFailed — treat both as "already gone".
        if getattr(exc, "code", None) in (404, 412):
            return
        if type(exc).__name__ in {"NotFound", "PreconditionFailed"}:
            return
        raise


def _bucket_name() -> str:
    return os.environ.get("PAYROLL_GCS_BUCKET", "")

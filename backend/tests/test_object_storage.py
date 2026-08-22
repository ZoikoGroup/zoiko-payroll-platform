"""
tests/test_object_storage.py
----------------------------
Coverage for app/core/object_storage.py — the local-disk backend (dev/test
default) plus reference parsing. GCS itself is not exercised here; that path
is a thin wrapper over google-cloud-storage and needs live credentials.
"""

import os
import uuid

import pytest

from app.core import object_storage


@pytest.fixture(autouse=True)
def _local_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("PAYROLL_GCS_BUCKET", raising=False)
    monkeypatch.setenv("PAYROLL_STORAGE_BACKEND", "local")
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path / "uploads"))
    yield


def test_auto_backend_falls_back_to_local_without_bucket():
    assert object_storage._backend() == "local"
    assert object_storage.using_gcs() is False


def test_bucket_env_switches_backend_to_gcs(monkeypatch):
    monkeypatch.setenv("PAYROLL_GCS_BUCKET", "zoiko-uploads")
    monkeypatch.setenv("PAYROLL_STORAGE_BACKEND", "auto")
    assert object_storage.using_gcs() is True


def test_save_read_delete_roundtrip_local():
    ref = object_storage.save_upload(
        subdir="payroll_compliance_documents",
        filename=f"{uuid.uuid4().hex}.txt",
        data="jurisdiction: India\nEPF 12%\n".encode("utf-8"),
    )
    assert not object_storage.is_gcs_ref(ref)
    assert object_storage.exists(ref)
    assert b"jurisdiction: India" in object_storage.read_bytes(ref)

    object_storage.delete_ref(ref)
    assert not object_storage.exists(ref)


def test_delete_missing_ref_is_noop(tmp_path):
    missing = str(tmp_path / "nope.bin")
    object_storage.delete_ref(missing)  # must not raise
    object_storage.delete_ref("")        # empty ref also fine


def test_gcs_ref_parsing_rejects_malformed():
    with pytest.raises(ValueError):
        object_storage._parse_gcs_ref("gs://bucket-only-no-key")
    assert object_storage.is_gcs_ref("gs://b/k") is True
    assert object_storage.is_gcs_ref("/tmp/uploads/x") is False
    assert object_storage.is_gcs_ref(None) is False


def test_save_upload_sanitizes_path_traversal_filename(tmp_path):
    ref = object_storage.save_upload(subdir="logos", filename="../../etc/passwd", data=b"x")
    # basename() strips directory components — the stored name must be flat.
    assert os.path.basename(ref) == "passwd"
    assert os.path.dirname(ref).startswith(str(tmp_path / "uploads"))

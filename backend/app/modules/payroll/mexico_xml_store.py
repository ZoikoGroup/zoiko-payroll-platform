"""
payroll/mexico_xml_store.py
---------------------------
Mexico final mile X5 (gap C15): the durable store contract for CFDI XML (the
signed and the stamped document). Write-once, hash-checked on write and read,
with a retention field.

  * put(key, data, retention_until) stores once. The same bytes again under the
    same key are an idempotent no-op; DIFFERENT bytes under an existing key are
    refused (MX_CFDI_XML_WRITE_ONCE) — a stamped CFDI is never overwritten.
  * get(ref) returns the bytes only if their SHA-256 still equals the hash
    recorded at write (MX_CFDI_XML_INTEGRITY otherwise).
  * retention_until is None while the retention period is undecided (C15 and
    legal). delete() refuses while it is None or not yet reached.

Production has NO store here: ``_STORE`` is None and active_store() refuses with
MX_CFDI_STORAGE_NOT_DURABLE — the same code the CFDI generation path already
uses (mexico_cfdi_service via app/core/object_storage). The only implementation
is the local-filesystem store in tests/. The GCS implementation and the
retention period wait for C15 and legal: docs/mexico/CFDI_XML_STORAGE_CONTRACT.md.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.modules.payroll.engine.countries.mexico import MXRefuse

# org/<id>/run/<id>/<name>.xml — no traversal, no identifier in the key (MX-061).
_KEY = re.compile(r"^org/\d+/run/\d+/[A-Za-z0-9._-]{1,120}\.xml$")


@dataclass(frozen=True)
class StoredXml:
    ref: str                                    # opaque, implementation-specific
    key: str
    sha256: str
    size: int
    retention_until: Optional[date]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY.match(key) or ".." in key:
        raise MXRefuse("MX_CFDI_XML_KEY_INVALID", "an XML key is org/<id>/run/<id>/<name>.xml")
    return key


class StampedXmlStore(ABC):
    """The contract every durable XML store meets (tests/test_mexico_xml_store.py
    runs it against any implementation)."""

    @abstractmethod
    def put(self, key: str, data: bytes, retention_until: Optional[date]) -> StoredXml: ...

    @abstractmethod
    def get(self, ref: str) -> bytes: ...

    @abstractmethod
    def head(self, ref: str) -> Optional[StoredXml]: ...

    @abstractmethod
    def delete(self, ref: str, on: date) -> None: ...

    # Shared rules, so an implementation only moves bytes.
    @staticmethod
    def write_once(existing: Optional[StoredXml], data: bytes) -> Optional[StoredXml]:
        """The existing record for an idempotent re-put, None to write, or a refusal."""
        if existing is None:
            return None
        if existing.sha256 == sha256(data):
            return existing
        raise MXRefuse("MX_CFDI_XML_WRITE_ONCE", "different XML under an existing key — a CFDI is never overwritten")

    @staticmethod
    def verified(meta: StoredXml, data: bytes) -> bytes:
        if sha256(data) != meta.sha256 or len(data) != meta.size:
            raise MXRefuse("MX_CFDI_XML_INTEGRITY", "the stored XML no longer matches the hash recorded at write")
        return data

    @staticmethod
    def deletable(meta: StoredXml, on: date) -> None:
        if meta.retention_until is None:
            raise MXRefuse("MX_CFDI_XML_RETENTION_UNDECIDED",
                           "the CFDI XML retention period is not decided (gap C15 / legal) — nothing is deleted")
        if on < meta.retention_until:
            raise MXRefuse("MX_CFDI_XML_RETAINED", f"retained until {meta.retention_until.isoformat()}")


_STORE: Optional[StampedXmlStore] = None         # production: none (C15 open)


def active_store() -> StampedXmlStore:
    if _STORE is None:
        raise MXRefuse("MX_CFDI_STORAGE_NOT_DURABLE",
                       "no durable CFDI XML store is configured (gap C15: GCS and the retention period)")
    return _STORE

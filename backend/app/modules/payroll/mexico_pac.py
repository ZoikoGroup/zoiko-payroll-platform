"""
modules/payroll/mexico_pac.py
-----------------------------
Provider-agnostic PAC (Proveedor Autorizado de Certificación) interface for
Mexican CFDI stamping (ZP-MX-ENG-001 Phase 7 §5.1). Deliberately THIN: four
calls with typed, provider-neutral results, so the provider chosen later
(Phase 7 D10, open) is one new class here — never a rewrite of the lifecycle.

Production has NO adapter: `_ADAPTERS` is empty in app/, so every PAC call is
refused with MX_PAC_NOT_CONFIGURED. The only implementation is a test-only
mock in tests/ (registered by monkeypatch). Transport failures and timeouts
are always UNKNOWN, never REJECTED (MX-062).

"Definitively not found" (§4.2) needs two provider-specific settings with NO
default — `min_wait_seconds` and `min_not_found_queries` (> 1). While a
provider has none, a document never becomes definitively not found, and any
retry from UNKNOWN needs explicit operator confirmation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from app.modules.payroll.engine.countries.mexico import MXRefuse

# Outcomes (provider-neutral)
ACCEPTED, REJECTED, UNKNOWN = "ACCEPTED", "REJECTED", "UNKNOWN"
FOUND, NOT_FOUND = "FOUND", "NOT_FOUND"
PENDING, CANCELLED, STILL_ACTIVE = "PENDING", "CANCELLED", "STILL_ACTIVE"


@dataclass(frozen=True)
class CredentialHandle:
    """An opaque pointer to managed secrets (MX-035): the adapter never sees
    key material from the database. Phase 7 has no real secret."""
    credential_ref_id: Optional[int]
    kind: str
    fingerprint_sha256: Optional[str] = None


@dataclass(frozen=True)
class DocumentRef:
    document_id: int
    issuer_rfc: Optional[str]
    folio: str
    series: Optional[str]
    payload_hash: Optional[str]


@dataclass(frozen=True)
class StampResult:
    outcome: str                       # ACCEPTED / REJECTED / UNKNOWN
    uuid: Optional[str] = None
    stamped_at: Optional[datetime] = None
    sat_certificate_number: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None      # redacted, never XML
    raw_response_hash: Optional[str] = None
    # Completion W4-3b: the PAC's stamped CFDI (the signed XML with its
    # TimbreFiscalDigital complement). Stored next to the signed XML; the printed
    # receipt is rendered only from it (RMF 2.7.1.7 needs the SAT seal / serial).
    stamped_xml: Optional[bytes] = None


@dataclass(frozen=True)
class StatusResult:
    outcome: str                       # FOUND / NOT_FOUND / UNKNOWN
    uuid: Optional[str] = None
    stamped_at: Optional[datetime] = None
    sat_certificate_number: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class CancelResult:
    outcome: str                       # ACCEPTED / PENDING / REJECTED / UNKNOWN
    code: Optional[str] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class CancelStatusResult:
    outcome: str                       # CANCELLED / PENDING / STILL_ACTIVE / UNKNOWN
    code: Optional[str] = None
    message: Optional[str] = None


class PacAdapter(ABC):
    provider: str = ""

    @abstractmethod
    def stamp(self, signed_payload: bytes, idempotency_key: str, credential: CredentialHandle) -> StampResult: ...

    @abstractmethod
    def query_status(self, document: DocumentRef, idempotency_key: str, credential: CredentialHandle) -> StatusResult: ...

    @abstractmethod
    def cancel(self, uuid: str, reason_code: str, replacement_uuid: Optional[str], idempotency_key: str,
               credential: CredentialHandle) -> CancelResult: ...

    @abstractmethod
    def query_cancel_status(self, uuid: str, credential: CredentialHandle) -> CancelStatusResult: ...


@dataclass(frozen=True)
class ProviderRetryConfig:
    """Thresholds for 'definitively not found' — provider-specific, no default."""
    min_wait_seconds: int
    min_not_found_queries: int


# (provider, environment) -> adapter factory. EMPTY in production (Phase 7 D10).
_ADAPTERS: Dict[tuple, object] = {}
# provider -> ProviderRetryConfig. EMPTY until a provider is chosen.
_PROVIDER_RETRY_CONFIG: Dict[str, ProviderRetryConfig] = {}


def get_adapter(provider: Optional[str], environment: Optional[str]) -> PacAdapter:
    factory = _ADAPTERS.get(((provider or "").upper(), (environment or "").upper()))
    if factory is None:
        raise MXRefuse("MX_PAC_NOT_CONFIGURED",
                      f"no PAC adapter is configured for provider {provider or '(none)'} / {environment or '(none)'} — "
                      "the PAC provider is not chosen yet (Phase 7 D10)")
    return factory()


def retry_config(provider: Optional[str]) -> Optional[ProviderRetryConfig]:
    cfg = _PROVIDER_RETRY_CONFIG.get((provider or "").upper())
    if cfg is None or cfg.min_wait_seconds is None or cfg.min_not_found_queries is None:
        return None
    if cfg.min_not_found_queries < 2 or cfg.min_wait_seconds <= 0:
        return None                     # one query or no wait is never "definitive"
    return cfg

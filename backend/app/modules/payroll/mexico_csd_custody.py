"""
payroll/mexico_csd_custody.py
-----------------------------
Mexico final mile X5 (gap C3): the CSD custody seam. The employer's CSD private
key never leaves its custody provider (MX-035): the signer asks the provider
for the certificate's PUBLIC facts (fingerprint, validity, status) and for a
signature over bytes it supplies — never for the key.

  * CsdCustodyProvider — the interface. A provider is chosen by the scheme of the
    credential's secret_ref (``gcp-sm://…``). The Secret Manager implementation
    waits for the security lead's decision (C3); its contract is
    docs/mexico/CSD_CUSTODY_CONTRACT.md.
  * CustodySigner — a CfdiSigner that checks custody (the provider's fingerprint
    matches the credential reference, the certificate is in force and ACTIVE)
    before it asks for a signature, and hands the signature to a *sealer* (the
    cadena original + sello step, Eng work after C3). It is NOT installed:
    mexico_cfdi_builder.active_signer() is still GcpSmSigner, which refuses.
  * csd_expiry_alerts — every ACTIVE CSD reference that is expired or within the
    warning window, for the Super Admin (public certificate metadata only).

Production registers no provider: ``_PROVIDERS`` is empty, so a lookup refuses
with MX_CSD_PROVIDER_NOT_CONFIGURED.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.modules.payroll.engine.countries.mexico import MXBlock, MXRefuse
from app.modules.payroll.mexico_cfdi_builder import CfdiSigner

ACTIVE, REVOKED, NOT_FOUND = "ACTIVE", "REVOKED", "NOT_FOUND"


@dataclass(frozen=True)
class CsdFacts:
    """What a provider may reveal about a CSD: public facts only."""
    fingerprint_sha256: str
    certificate_serial: Optional[str]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    status: str                                   # ACTIVE / REVOKED / NOT_FOUND


@dataclass(frozen=True)
class CsdSignature:
    signature: bytes                              # over the bytes the signer supplied
    certificate_der: bytes                        # the PUBLIC certificate (for the CFDI's Certificado)
    certificate_serial: Optional[str]


class CsdCustodyProvider(ABC):
    """A custody provider holds the private key; nothing here returns it."""
    scheme: str = ""

    @abstractmethod
    def describe(self, secret_ref: str) -> CsdFacts: ...

    @abstractmethod
    def sign(self, secret_ref: str, data: bytes) -> CsdSignature: ...


# secret_ref scheme -> provider factory. EMPTY in production (C3 is open).
_PROVIDERS: Dict[str, Callable[[], CsdCustodyProvider]] = {}


def provider_for(secret_ref: Optional[str]) -> CsdCustodyProvider:
    scheme = (secret_ref or "").split("://", 1)[0].lower() if "://" in (secret_ref or "") else ""
    factory = _PROVIDERS.get(scheme)
    if factory is None:
        raise MXRefuse("MX_CSD_PROVIDER_NOT_CONFIGURED",
                       f"no CSD custody provider is configured for {scheme or '(no scheme)'}:// — the custody "
                       "decision is open (gap C3)")
    return factory()


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def custody_refusal(facts: CsdFacts, expected_fingerprint: Optional[str], at: datetime) -> Optional[MXRefuse]:
    """Why the CSD must not sign at `at` (None = it may)."""
    if facts.status != ACTIVE:
        return MXRefuse("MX_CSD_NOT_ACTIVE", f"the CSD in custody is {facts.status}")
    if not expected_fingerprint or facts.fingerprint_sha256 != expected_fingerprint:
        return MXRefuse("MX_CSD_FINGERPRINT_MISMATCH",
                       "the CSD in custody is not the certificate recorded for this employer")
    start, end = _aware(facts.valid_from), _aware(facts.valid_to)
    if end is None or (start is not None and at < start) or at > end:
        return MXRefuse("MX_CSD_EXPIRED", "the CSD is not in force at signing time")
    return None


class CustodySigner(CfdiSigner):
    """Signs through a custody provider. `credential` is the employer's
    PayrollMxCredentialRef (kind CSD); `sealer(payload, sign, signature_facts)`
    builds the sealed CFDI from the payload and a signing callable."""

    def __init__(self, sealer: Optional[Callable] = None, now: Callable[[], datetime] = None):
        self.sealer = sealer
        self.now = now or (lambda: datetime.now(timezone.utc))

    def blocked(self) -> Optional[MXBlock]:
        if self.sealer is None:
            return MXBlock("MX_CSD_SEALER_NOT_BUILT",
                           "the cadena original + sello step is not built yet (after gap C3)")
        return None

    def sign(self, payload: bytes, credential) -> Tuple[bytes, Optional[str]]:
        blocked = self.blocked()
        if blocked is not None:
            raise blocked
        if credential is None or getattr(credential, "kind", None) != "CSD" or credential.status != "ACTIVE":
            raise MXRefuse("MX_CSD_NOT_ACTIVE", "the employer has no ACTIVE CSD credential reference")
        provider = provider_for(credential.secret_ref)
        refusal = custody_refusal(provider.describe(credential.secret_ref), credential.fingerprint_sha256, self.now())
        if refusal is not None:
            raise refusal
        last = {}

        def sign_bytes(data: bytes) -> CsdSignature:
            last["sig"] = provider.sign(credential.secret_ref, data)
            return last["sig"]

        sealed = self.sealer(payload, sign_bytes)
        sig = last.get("sig")
        return sealed, sig.certificate_serial if sig else None


def csd_expiry_alerts(db: Session, on: date, organization_id: Optional[int] = None) -> list:
    """ACTIVE CSD references that are expired, or expire within
    MX_CREDENTIAL_EXPIRY_WARNING_DAYS, on `on`. Public metadata only: the
    secret reference and the RFC are never returned."""
    from app.config import settings
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollMxCredentialRef as C

    at = datetime.combine(on, time.min, tzinfo=timezone.utc)
    window = timedelta(days=settings.MX_CREDENTIAL_EXPIRY_WARNING_DAYS)
    q = db.query(C).filter(C.kind == "CSD", C.status == "ACTIVE")
    if organization_id is not None:
        q = q.filter(C.organization_id == organization_id)
    names = {}
    out = []
    for c in q.order_by(C.valid_to, C.id):
        end = _aware(c.valid_to)
        if end is None:
            level, note = "MISSING", "no certificate uploaded — validity unknown"
        elif end < at:
            level, note = "EXPIRED", f"expired {end.date().isoformat()}"
        elif end - at <= window:
            level, note = "EXPIRING", f"expires {end.date().isoformat()} ({(end - at).days} days)"
        else:
            continue
        if c.organization_id not in names:
            org = db.get(Organization, c.organization_id)
            names[c.organization_id] = getattr(org, "organization_name", None)
        out.append({"credentialId": c.id, "organizationId": c.organization_id,
                    "organization": names[c.organization_id], "employerProfileId": c.employer_profile_id,
                    "level": level, "validTo": end.isoformat() if end else None,
                    "fingerprint": f"{c.fingerprint_sha256[:12]}…" if c.fingerprint_sha256 else None,
                    "certificateSerial": c.certificate_serial, "note": note})
    return out

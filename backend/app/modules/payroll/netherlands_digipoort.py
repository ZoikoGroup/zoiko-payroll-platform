"""
payroll/netherlands_digipoort.py
---------------------------------
Digipoort / SBR transport adapter for NL loonaangifte.

Interface with two modes:
  - VALIDATION_SERVICE / SANDBOX: open for development/testing
  - LIVE (DIGIPOORT / SBR): LOCKED until gate G3 (PKIoverheid cert + test access)

After timeout -> UNKNOWN status, reconciled before retry (NL-052).
Transport acknowledgement, statutory acceptance, and payment are three
separate states (NL-038).
"""
from __future__ import annotations

import hashlib
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.payroll.models import (
    PayrollNlDigipoortSubmission,
    PayrollNlEmployerProfile,
    PayrollNlLoonaangifteReturn,
)
from app.core.exceptions import BadRequestException


class DigipoortChannel(str, Enum):
    DIGIPOORT = "DIGIPOORT"
    SBR = "SBR"
    VALIDATION_SERVICE = "VALIDATION_SERVICE"


class TransportStatus(str, Enum):
    PREPARED = "PREPARED"
    SENT = "SENT"
    ACK = "ACK"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class DigipoortError(BadRequestException):
    pass


class LiveTransportLockedError(DigipoortError):
    pass


class TimeoutError(DigipoortError):
    pass


class CertificateError(DigipoortError):
    pass


# Default timeout for transport (configurable via env)
DEFAULT_TRANSPORT_TIMEOUT_SECONDS = int(os.getenv("NL_DIGIPOORT_TIMEOUT_SECONDS", "300"))


@dataclass
class TransportResult:
    success: bool
    transport_status: TransportStatus
    digipoort_reference: Optional[str] = None
    ack_payload: Optional[str] = None
    error_codes: Optional[list] = None
    error_message: Optional[str] = None


class DigipoortTransport(ABC):
    """Abstract transport interface."""

    @abstractmethod
    def send(self, payload_xml: str, cert_fingerprint: str, idempotency_key: str) -> TransportResult:
        pass

    @abstractmethod
    def poll_acknowledgement(self, digipoort_reference: str) -> TransportResult:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass


class ValidationServiceTransport(DigipoortTransport):
    """Belastingdienst validation-service / sandbox endpoint.
    No PKI cert required; open for testing.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv(
            "NL_VALIDATION_SERVICE_URL",
            "https://api.sandbox.belastingdienst.nl/validatie/loonaangifte"
        )
        self.enabled = True

    def send(self, payload_xml: str, cert_fingerprint: str, idempotency_key: str) -> TransportResult:
        # In a real implementation, this would POST to the validation service
        # For now, simulate synchronous validation
        if not self.enabled:
            return TransportResult(success=False, transport_status=TransportStatus.REJECTED,
                                   error_message="Validation service disabled")

        # Simulate: check well-formed XML, schema validation
        is_valid = payload_xml.startswith("<?xml") and "<Loonaangifte" in payload_xml

        if is_valid:
            return TransportResult(
                success=True,
                transport_status=TransportStatus.ACK,
                digipoort_reference=f"VAL-{idempotency_key[:16]}",
                ack_payload='<Ack><Status>VALID</Status></Ack>'
            )
        else:
            return TransportResult(
                success=False,
                transport_status=TransportStatus.REJECTED,
                error_codes=[{"code": "SCHEMA_INVALID", "message": "Payload failed schema validation"}]
            )

    def poll_acknowledgement(self, digipoort_reference: str) -> TransportResult:
        # Validation service is synchronous
        return TransportResult(success=True, transport_status=TransportStatus.ACK,
                               digipoort_reference=digipoort_reference)

    def health_check(self) -> bool:
        return self.enabled


class SandboxTransport(DigipoortTransport):
    """Digipoort sandbox/test environment.
    Requires PKIoverheid test certificate.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv(
            "NL_DIGIPOORT_SANDBOX_URL",
            "https://digipoort.sandbox.belastingdienst.nl"
        )
        self.enabled = os.getenv("NL_DIGIPOORT_SANDBOX_ENABLED", "false").lower() == "true"

    def send(self, payload_xml: str, cert_fingerprint: str, idempotency_key: str) -> TransportResult:
        if not self.enabled:
            return TransportResult(success=False, transport_status=TransportStatus.REJECTED,
                                   error_message="Sandbox transport not enabled")

        # Real implementation would sign with PKI cert and POST to Digipoort
        # Placeholder
        return TransportResult(
            success=True,
            transport_status=TransportStatus.SENT,
            digipoort_reference=f"SND-{idempotency_key[:16]}"
        )

    def poll_acknowledgement(self, digipoort_reference: str) -> TransportResult:
        # Poll Digipoort for ACK
        return TransportResult(
            success=True,
            transport_status=TransportStatus.ACK,
            digipoort_reference=digipoort_reference,
            ack_payload='<Ack><Status>ACCEPTED</Status></Ack>'
        )

    def health_check(self) -> bool:
        return self.enabled


class LiveTransport(DigipoortTransport):
    """Production Digipoort / SBR transport.
    LOCKED until gate G3 is signed (PKIoverheid cert + test access granted).
    """

    def __init__(self):
        self.enabled = False  # LOCKED until G3
        self.base_url = os.getenv("NL_DIGIPOORT_LIVE_URL", "https://digipoort.belastingdienst.nl")

    def unlock(self, cert_path: str, cert_password: str, test_evidence_id: int) -> None:
        """Unlock live transport after G3 sign-off.
        Requires PKIoverheid certificate path + password, and test evidence artifact ID.
        """
        if not os.path.exists(cert_path):
            raise CertificateError(f"Certificate not found: {cert_path}")
        self.cert_path = cert_path
        self.cert_password = cert_password
        self.test_evidence_id = test_evidence_id
        self.enabled = True

    def send(self, payload_xml: str, cert_fingerprint: str, idempotency_key: str) -> TransportResult:
        if not self.enabled:
            raise LiveTransportLockedError(
                "Live Digipoort transport is locked until gate G3 is signed. "
                "PKIoverheid certificate and successful test submission required."
            )

        # Real implementation: sign with PKI cert, POST to Digipoort endpoint
        # Placeholder
        return TransportResult(
            success=True,
            transport_status=TransportStatus.SENT,
            digipoort_reference=f"LIVE-{idempotency_key[:16]}"
        )

    def poll_acknowledgement(self, digipoort_reference: str) -> TransportResult:
        if not self.enabled:
            raise LiveTransportLockedError("Live transport not unlocked")

        # Poll for acknowledgement
        return TransportResult(
            success=True,
            transport_status=TransportStatus.ACK,
            digipoort_reference=digipoort_reference,
            ack_payload='<Ack><Status>ACCEPTED</Status></Ack>'
        )

    def health_check(self) -> bool:
        return self.enabled


# Global transport instances (configured at startup)
_validation_transport = ValidationServiceTransport()
_sandbox_transport = SandboxTransport()
_live_transport = LiveTransport()


def get_transport(channel: DigipoortChannel) -> DigipoortTransport:
    if channel == DigipoortChannel.VALIDATION_SERVICE:
        return _validation_transport
    if channel == DigipoortChannel.SBR:
        return _sandbox_transport  # SBR uses sandbox until live
    if channel == DigipoortChannel.DIGIPOORT:
        return _live_transport
    raise DigipoortError(f"unknown channel {channel}")


def submit_return(
    db: Session,
    return_id: int,
    channel: DigipoortChannel = DigipoortChannel.VALIDATION_SERVICE,
    timeout_seconds: int = DEFAULT_TRANSPORT_TIMEOUT_SECONDS,
) -> PayrollNlDigipoortSubmission:
    """Submit a loonaangifte return via Digipoort.
    Creates submission record, sends payload, polls for ACK with timeout.
    """
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise BadRequestException(f"Return {return_id} not found")

    if not ret.payload_xml or not ret.payload_sha256:
        raise BadRequestException("Return has no XML payload — build it first")

    # Get employer profile for cert fingerprint
    employer = db.query(PayrollNlEmployerProfile).filter(
        PayrollNlEmployerProfile.id == ret.employer_profile_id).one_or_none()
    cert_fp = employer.pki_cert_fingerprint if employer else "unknown"

    # Next attempt number
    last_attempt = db.query(func.max(PayrollNlDigipoortSubmission.attempt_no)).filter(
        PayrollNlDigipoortSubmission.return_id == return_id).scalar() or 0
    attempt_no = last_attempt + 1

    transport = get_transport(channel)

    idempotency_key = f"digipoort-{return_id}-{attempt_no}-{datetime.utcnow().isoformat()}"
    idempotency_key = hashlib.sha256(idempotency_key.encode()).hexdigest()[:100]

    # Create submission record
    sub = PayrollNlDigipoortSubmission(
        return_id=return_id,
        attempt_no=attempt_no,
        channel=channel.value,
        cert_fingerprint=cert_fp,
        payload_sha256=ret.payload_sha256,
        transport_status=TransportStatus.PREPARED.value,
        idempotency_key=idempotency_key,
    )
    db.add(sub)
    db.flush()

    # Send
    try:
        result = transport.send(ret.payload_xml, cert_fp, idempotency_key)
    except Exception as e:
        sub.transport_status = TransportStatus.REJECTED.value
        sub.error_codes = [{"code": "TRANSPORT_ERROR", "message": str(e)}]
        db.flush()
        raise

    sub.sent_at = datetime.utcnow()
    sub.transport_status = result.transport_status.value
    sub.digipoort_reference = result.digipoort_reference
    sub.ack_payload = result.ack_payload
    sub.error_codes = result.error_codes
    db.flush()

    # Poll for ACK if sent
    if result.transport_status == TransportStatus.SENT:
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                ack_result = transport.poll_acknowledgement(result.digipoort_reference)
            except Exception as e:
                sub.transport_status = TransportStatus.REJECTED.value
                sub.error_codes = [{"code": "POLL_ERROR", "message": str(e)}]
                db.flush()
                raise

            if ack_result.transport_status in (TransportStatus.ACK, TransportStatus.REJECTED):
                sub.transport_status = ack_result.transport_status.value
                sub.ack_payload = ack_result.ack_payload
                sub.error_codes = ack_result.error_codes
                db.flush()
                break
            time.sleep(5)  # poll interval
        else:
            # Timeout
            sub.transport_status = TransportStatus.UNKNOWN.value
            sub.error_codes = [{"code": "TIMEOUT", "message": f"No ACK within {timeout_seconds}s"}]
            db.flush()
            raise TimeoutError(f"Digipoort ACK timeout after {timeout_seconds}s")

    return sub


def reconcile_unknown_submissions(db: Session, max_age_hours: int = 24) -> int:
    """Find UNKNOWN submissions older than max_age_hours and attempt reconciliation.
    Called by scheduled job before any retry (NL-052).
    """
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    unknown = db.query(PayrollNlDigipoortSubmission).filter(
        PayrollNlDigipoortSubmission.transport_status == TransportStatus.UNKNOWN.value,
        PayrollNlDigipoortSubmission.sent_at < cutoff).all()

    reconciled = 0
    for sub in unknown:
        ret = db.query(PayrollNlLoonaangifteReturn).filter(
            PayrollNlLoonaangifteReturn.id == sub.return_id).one_or_none()
        if not ret:
            continue

        transport = get_transport(DigipoortChannel(sub.channel))
        try:
            result = transport.poll_acknowledgement(sub.digipoort_reference)
        except Exception:
            continue

        if result.transport_status in (TransportStatus.ACK, TransportStatus.REJECTED):
            sub.transport_status = result.transport_status.value
            sub.ack_payload = result.ack_payload
            sub.error_codes = result.error_codes
            sub.reconciled_at = datetime.utcnow()
            db.flush()
            reconciled += 1

    return reconciled


def retry_submission(db: Session, submission_id: int, channel: Optional[DigipoortChannel] = None) -> PayrollNlDigipoortSubmission:
    """Retry a failed/unknown submission (after reconciliation)."""
    sub = db.query(PayrollNlDigipoortSubmission).filter(
        PayrollNlDigipoortSubmission.id == submission_id).one_or_none()
    if not sub:
        raise BadRequestException(f"Submission {submission_id} not found")

    if sub.transport_status not in (TransportStatus.REJECTED.value, TransportStatus.UNKNOWN.value):
        raise DigipoortError(f"Cannot retry submission with status {sub.transport_status}")

    # Reconcile first if UNKNOWN
    if sub.transport_status == TransportStatus.UNKNOWN.value:
        reconcile_unknown_submissions(db, max_age_hours=0)

    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == sub.return_id).one_or_none()
    if not ret:
        raise BadRequestException("Return missing")

    use_channel = channel or DigipoortChannel(sub.channel)
    return submit_return(db, ret.id, use_channel)


def unlock_live_transport(cert_path: str, cert_password: str, test_evidence_id: int) -> None:
    """Unlock live Digipoort transport after G3 sign-off.
    Called by admin UI after evidence is reviewed and gate G3 signed.
    """
    _live_transport.unlock(cert_path, cert_password, test_evidence_id)


def get_transport_status(channel: DigipoortChannel) -> Dict[str, Any]:
    transport = get_transport(channel)
    return {
        "channel": channel.value,
        "enabled": transport.enabled,
        "healthy": transport.health_check() if transport.enabled else False,
    }


def configure_sandbox(base_url: str, enabled: bool = True) -> None:
    _sandbox_transport.base_url = base_url
    _sandbox_transport.enabled = enabled


def configure_validation_service(base_url: str, enabled: bool = True) -> None:
    _validation_transport.base_url = base_url
    _validation_transport.enabled = enabled
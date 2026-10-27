"""TEST-ONLY fake PAC that passes the conformance kit (Mexico final mile X5).
Never imported by app/ and never registered in mexico_pac._ADAPTERS: the kit
calls it directly. Built on the Phase 7 mock (tests/_mx_mock_pac.py) plus the
one behaviour the mock lacks — an expired CSD is a definitive rejection.
SYNTHETIC: no real PAC, no real CSD, no real SAT data."""

from contextlib import contextmanager

from app.modules.payroll import mexico_pac as P
from tests._mx_mock_pac import MockPac
from tests._mx_pac_conformance import Driver

SYN_XML = (b'<?xml version="1.0" encoding="UTF-8"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
           b'Version="4.0" Folio="%s" Sello="SYNTHETIC"/>')


class FakeConformantPac(MockPac):
    provider = "FAKE"

    def __init__(self, expired_fingerprints=(), **script):
        super().__init__(**script)
        self.expired = set(expired_fingerprints)

    def stamp(self, signed_payload, idempotency_key, credential):
        if credential.fingerprint_sha256 in self.expired:
            self.calls.append(("stamp", idempotency_key, "expired"))
            return P.StampResult(outcome=P.REJECTED, code="SYN-CSD-EXPIRED", message="synthetic: CSD expired")
        if b"INVALID" in signed_payload:
            self.calls.append(("stamp", idempotency_key, "invalid"))
            return P.StampResult(outcome=P.REJECTED, code="SYN-SCHEMA", message="synthetic: schema error")
        return super().stamp(signed_payload, idempotency_key, credential)


class FakeDriver(Driver):
    max_cancel_polls = 3

    def __init__(self, adapter=None):
        self.credential = P.CredentialHandle(1, "CSD", "f" * 64)
        self.expired_credential = P.CredentialHandle(2, "CSD", "e" * 64)
        self.adapter = adapter or FakeConformantPac(expired_fingerprints={"e" * 64},
                                                    cancel_status=["pending", "cancelled"])

    def payload(self, tag):
        return SYN_XML % tag.encode()

    def invalid_payload(self):
        return b"<INVALID/>"

    @contextmanager
    def timeout(self, after_stamp):
        self.adapter.script.setdefault("stamp", []).insert(0, "timeout_after_stamp" if after_stamp else "timeout")
        yield

    def cancel_reason(self, with_replacement):
        return "SYN-01" if with_replacement else "SYN-02"

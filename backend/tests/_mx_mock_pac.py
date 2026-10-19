"""TEST-ONLY mock PAC (Phase 7 §5.1). Never imported by app/; registered by
monkeypatch into mexico_pac._ADAPTERS. Behaves like a deduplicating PAC: the
same idempotency key always yields the same UUID, and `stamps_by_key` counts
how many CFDI were actually stamped per key (the "no second stamp" proof).

Script per call type, consumed in order (default when empty in brackets):
  stamp:  "accept" | "reject" | "timeout" (nothing stamped) |
          "timeout_after_stamp" (stamped, answer lost)            [accept]
  status: "auto" (FOUND if stamped else NOT_FOUND) | "not_found" |
          "unknown" | "timeout"                                    [auto]
  cancel: "accept" | "pending" | "reject" | "timeout"              [accept]
  cancel_status: "cancelled" | "pending" | "still_active" | "unknown"   [cancelled]
"""

import hashlib
from datetime import datetime, timezone

from app.modules.payroll import mexico_pac as P


class PacTimeout(Exception):
    pass


class MockPac(P.PacAdapter):
    provider = "MOCK"

    def __init__(self, **script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []                 # (call, key, payload_hash)
        self.uuid_by_key = {}
        self.stamps_by_key = {}

    def _next(self, kind, default):
        seq = self.script.get(kind) or []
        return seq.pop(0) if seq else default

    def _do_stamp(self, key):
        if key not in self.uuid_by_key:
            self.uuid_by_key[key] = f"SYN-{hashlib.sha256(key.encode()).hexdigest()[:8].upper()}-UUID"
            self.stamps_by_key[key] = self.stamps_by_key.get(key, 0) + 1
        return self.uuid_by_key[key]

    def stamp(self, signed_payload, idempotency_key, credential):
        self.calls.append(("stamp", idempotency_key, hashlib.sha256(signed_payload).hexdigest()))
        how = self._next("stamp", "accept")
        if how == "timeout":
            raise PacTimeout("synthetic timeout")
        if how == "timeout_after_stamp":
            self._do_stamp(idempotency_key)
            raise PacTimeout("synthetic timeout after the PAC stamped")
        if how == "reject":
            return P.StampResult(outcome=P.REJECTED, code="SYN-REJECT", message="synthetic rejection")
        uuid = self._do_stamp(idempotency_key)
        return P.StampResult(outcome=P.ACCEPTED, uuid=uuid, stamped_at=datetime.now(timezone.utc),
                             sat_certificate_number="SYN-SAT-CERT", code="SYN-OK")

    def query_status(self, document, idempotency_key, credential):
        self.calls.append(("status", idempotency_key, document.payload_hash))
        how = self._next("status", "auto")
        if how == "timeout":
            raise PacTimeout("synthetic status timeout")
        if how == "unknown":
            return P.StatusResult(outcome=P.UNKNOWN)
        if how == "not_found" or idempotency_key not in self.uuid_by_key:
            return P.StatusResult(outcome=P.NOT_FOUND)
        return P.StatusResult(outcome=P.FOUND, uuid=self.uuid_by_key[idempotency_key],
                              stamped_at=datetime.now(timezone.utc), sat_certificate_number="SYN-SAT-CERT")

    def cancel(self, uuid, reason_code, replacement_uuid, idempotency_key, credential):
        self.calls.append(("cancel", idempotency_key, f"{uuid}|{reason_code}|{replacement_uuid}"))
        how = self._next("cancel", "accept")
        if how == "timeout":
            raise PacTimeout("synthetic cancel timeout")
        return P.CancelResult(outcome={"accept": P.ACCEPTED, "pending": P.PENDING, "reject": P.REJECTED}[how])

    def query_cancel_status(self, uuid, credential):
        self.calls.append(("cancel_status", uuid, None))
        how = self._next("cancel_status", "cancelled")
        return P.CancelStatusResult(outcome={"cancelled": P.CANCELLED, "pending": P.PENDING,
                                             "still_active": P.STILL_ACTIVE, "unknown": P.UNKNOWN}[how])


def install(monkeypatch, mock: MockPac, environment="SANDBOX"):
    monkeypatch.setitem(P._ADAPTERS, ("MOCK", environment), lambda: mock)
    return mock

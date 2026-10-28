"""PAC conformance kit (Mexico final mile X5, gap C1). TEST-ONLY.

Any PacAdapter (mexico_pac.py) must pass every check here before it is
registered in mexico_pac._ADAPTERS. The kit knows nothing about a provider: a
*driver* supplies the adapter, credentials and payloads, and knows how to
provoke each scenario in that provider's sandbox. The kit checks the
provider-neutral contract the CFDI lifecycle relies on (MEXICO_PHASE_7_PLAN.md
§4–§5, MX-015–MX-018, MX-043, MX-062):

  stamp_accepted            ACCEPTED with a UUID, stamp time, SAT certificate
                            number and the stamped XML carrying that UUID
  stamp_rejected            a definitive rejection: REJECTED with a code, no UUID
  timeout_unknown_status    a transport failure is UNKNOWN (never REJECTED), and
                            query_status with the same idempotency key then finds
                            the CFDI the PAC stamped; a retry returns the SAME UUID
  timeout_before_stamp      UNKNOWN, then query_status answers NOT_FOUND (never FOUND)
  duplicate_idempotency     the same key twice gives one UUID (no second CFDI)
  cancel_without_replacement / cancel_with_replacement
                            ACCEPTED or PENDING, never a silent success on a bad call
  cancel_status_polling     only CANCELLED / PENDING / STILL_ACTIVE / UNKNOWN, and
                            CANCELLED within the driver's poll budget
  csd_expired               an expired CSD is a definitive REJECTED, not UNKNOWN
  no_raw_xml_in_messages    no result message carries XML

A transport exception from the adapter is normalised to UNKNOWN exactly as the
lifecycle does (mexico_cfdi_service._process_*). A scenario the driver cannot
provoke is reported NOT_RUN — the provider's sandbox must allow it before the
adapter is accepted (PAC_SELECTION_CHECKLIST.md §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.modules.payroll import mexico_pac as P

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT_RUN"
CANCEL_OUTCOMES = {P.ACCEPTED, P.PENDING}
CANCEL_STATUS_OUTCOMES = {P.CANCELLED, P.PENDING, P.STILL_ACTIVE, P.UNKNOWN}


class Unsupported(Exception):
    """Raised by a driver for a scenario its sandbox cannot provoke."""


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


@dataclass
class Report:
    provider: str
    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.status == PASS for r in self.results)

    def by_status(self, status) -> List[str]:
        return [r.name for r in self.results if r.status == status]


class Driver:
    """What an adapter's author implements for the kit (a sandbox harness).

    adapter                 the PacAdapter under test
    credential              a valid CSD CredentialHandle in the sandbox
    expired_credential      a CredentialHandle whose CSD has expired
    payload(tag)            a signed CFDI payload the sandbox accepts (distinct per tag)
    invalid_payload()       a signed payload the sandbox must reject definitively
    timeout(after_stamp)    a context manager: the NEXT adapter call fails in transport
                            — after the PAC stamped (answer lost) or before it did
    cancel_reason(with_replacement)  a cancellation reason code for each case
    document_ref(payload, key)       the DocumentRef the lifecycle would send
    max_cancel_polls        how many query_cancel_status calls may precede CANCELLED
    """
    max_cancel_polls = 10

    def payload(self, tag: str) -> bytes: raise NotImplementedError
    def invalid_payload(self) -> bytes: raise NotImplementedError
    def timeout(self, after_stamp: bool): raise Unsupported("timeout")
    def cancel_reason(self, with_replacement: bool) -> str: raise NotImplementedError

    def document_ref(self, payload: bytes, key: str) -> P.DocumentRef:
        import hashlib

        return P.DocumentRef(document_id=0, issuer_rfc=None, folio=key, series=None,
                             payload_hash=hashlib.sha256(payload).hexdigest())


def _safe(call: Callable, kind) -> object:
    """The lifecycle's own mapping: any exception is UNKNOWN (MX-062)."""
    try:
        return call()
    except Exception as exc:                                       # noqa: BLE001 — that is the contract
        return kind(outcome=P.UNKNOWN, code="TRANSPORT", message=type(exc).__name__)


def _stamp(d, payload, key, credential=None):
    return _safe(lambda: d.adapter.stamp(payload, key, credential or d.credential), P.StampResult)


def _status(d, payload, key):
    return _safe(lambda: d.adapter.query_status(d.document_ref(payload, key), key, d.credential), P.StatusResult)


def _accepted(d, payload, key):
    r = _stamp(d, payload, key)
    assert r.outcome == P.ACCEPTED and r.uuid, f"setup stamp was {r.outcome} {r.code}"
    return r


def check_stamp_accepted(d):
    payload = d.payload("accepted")
    r = _stamp(d, payload, "KIT-ACCEPT-1")
    assert r.outcome == P.ACCEPTED, f"outcome {r.outcome} {r.code}"
    assert r.uuid and r.stamped_at and r.sat_certificate_number, "uuid, stamped_at and SAT certificate are required"
    assert r.stamped_xml and r.uuid.encode() in r.stamped_xml, "the stamped XML must carry the UUID (TFD)"


def check_stamp_rejected(d):
    r = _stamp(d, d.invalid_payload(), "KIT-REJECT-1")
    assert r.outcome == P.REJECTED, f"a definitive rejection must be REJECTED, got {r.outcome}"
    assert r.code and not r.uuid, "a rejection carries a code and no UUID"


def check_timeout_unknown_status(d):
    payload, key = d.payload("timeout-after"), "KIT-TIMEOUT-AFTER-1"
    with d.timeout(after_stamp=True):
        r = _stamp(d, payload, key)
    assert r.outcome == P.UNKNOWN, f"a transport failure must be UNKNOWN, never {r.outcome}"
    s = _status(d, payload, key)
    assert s.outcome == P.FOUND and s.uuid, f"query_status must find the stamped CFDI, got {s.outcome}"
    again = _stamp(d, payload, key)
    assert again.outcome == P.ACCEPTED and again.uuid == s.uuid, "a retry with the same key must return the same UUID"


def check_timeout_before_stamp(d):
    payload, key = d.payload("timeout-before"), "KIT-TIMEOUT-BEFORE-1"
    with d.timeout(after_stamp=False):
        r = _stamp(d, payload, key)
    assert r.outcome == P.UNKNOWN, f"a transport failure must be UNKNOWN, never {r.outcome}"
    s = _status(d, payload, key)
    assert s.outcome == P.NOT_FOUND, f"nothing was stamped: query_status must be NOT_FOUND, got {s.outcome}"


def check_duplicate_idempotency(d):
    payload, key = d.payload("duplicate"), "KIT-DUP-1"
    first, second = _accepted(d, payload, key), _stamp(d, payload, key)
    assert second.outcome == P.ACCEPTED and second.uuid == first.uuid, \
        f"the same idempotency key must not produce a second CFDI ({first.uuid} vs {second.uuid})"
    s = _status(d, payload, key)
    assert s.outcome == P.FOUND and s.uuid == first.uuid


def _cancel(d, uuid, reason, replacement, key):
    return _safe(lambda: d.adapter.cancel(uuid, reason, replacement, key, d.credential), P.CancelResult)


def check_cancel_without_replacement(d):
    orig = _accepted(d, d.payload("cancel-plain"), "KIT-CANCEL-1")
    r = _cancel(d, orig.uuid, d.cancel_reason(with_replacement=False), None, "KIT-CANCEL-1-C")
    assert r.outcome in CANCEL_OUTCOMES, f"cancel must be ACCEPTED or PENDING, got {r.outcome}"


def check_cancel_with_replacement(d):
    orig = _accepted(d, d.payload("cancel-orig"), "KIT-CANCEL-2")
    repl = _accepted(d, d.payload("cancel-repl"), "KIT-CANCEL-2-R")
    r = _cancel(d, orig.uuid, d.cancel_reason(with_replacement=True), repl.uuid, "KIT-CANCEL-2-C")
    assert r.outcome in CANCEL_OUTCOMES, f"cancel must be ACCEPTED or PENDING, got {r.outcome}"


def check_cancel_status_polling(d):
    orig = _accepted(d, d.payload("cancel-poll"), "KIT-CANCEL-3")
    r = _cancel(d, orig.uuid, d.cancel_reason(with_replacement=False), None, "KIT-CANCEL-3-C")
    assert r.outcome in CANCEL_OUTCOMES, f"cancel was {r.outcome}"
    seen = []
    for _ in range(d.max_cancel_polls):
        s = _safe(lambda: d.adapter.query_cancel_status(orig.uuid, d.credential), P.CancelStatusResult)
        assert s.outcome in CANCEL_STATUS_OUTCOMES, f"unexpected cancel status {s.outcome}"
        seen.append(s.outcome)
        if s.outcome == P.CANCELLED:
            return
    raise AssertionError(f"not CANCELLED within {d.max_cancel_polls} polls: {seen}")


def check_csd_expired(d):
    r = _stamp(d, d.payload("expired"), "KIT-EXPIRED-1", credential=d.expired_credential)
    assert r.outcome == P.REJECTED and r.code, f"an expired CSD must be a definitive REJECTED, got {r.outcome}"


def check_no_raw_xml_in_messages(d):
    for r in (_stamp(d, d.invalid_payload(), "KIT-MSG-1"), _status(d, d.payload("msg"), "KIT-MSG-UNSENT")):
        assert "<" not in (r.message or ""), "a result message must never carry XML"


CHECKS = [
    ("stamp_accepted", check_stamp_accepted),
    ("stamp_rejected", check_stamp_rejected),
    ("timeout_unknown_status", check_timeout_unknown_status),
    ("timeout_before_stamp", check_timeout_before_stamp),
    ("duplicate_idempotency", check_duplicate_idempotency),
    ("cancel_without_replacement", check_cancel_without_replacement),
    ("cancel_with_replacement", check_cancel_with_replacement),
    ("cancel_status_polling", check_cancel_status_polling),
    ("csd_expired", check_csd_expired),
    ("no_raw_xml_in_messages", check_no_raw_xml_in_messages),
]


def run(driver_factory: Callable[[], Driver], only: Optional[List[str]] = None) -> Report:
    """Run every check, each on a fresh driver (so one scenario cannot leak into another)."""
    probe = driver_factory()
    report = Report(provider=getattr(probe.adapter, "provider", "") or type(probe.adapter).__name__)
    for name, fn in CHECKS:
        if only and name not in only:
            continue
        try:
            fn(driver_factory())
            report.results.append(CheckResult(name, PASS))
        except Unsupported as exc:
            report.results.append(CheckResult(name, NOT_RUN, f"the sandbox cannot provoke: {exc}"))
        except AssertionError as exc:
            report.results.append(CheckResult(name, FAIL, str(exc)))
    return report

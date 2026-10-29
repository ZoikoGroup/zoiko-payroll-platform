"""Mexico final mile X5 (gap C1): the PAC conformance kit. A fake adapter
passes every check; adapters with the faults the kit exists to catch fail the
right check; a scenario a sandbox cannot provoke is NOT_RUN, never PASS; and
nothing of this reaches app/ (the production registry stays empty). SYNTHETIC."""

from pathlib import Path

from app.modules.payroll import mexico_pac as P
from tests import _mx_pac_conformance as kit
from tests._mx_fake_pac import FakeConformantPac, FakeDriver

APP = Path(__file__).resolve().parents[1] / "app"


def test_the_fake_adapter_passes_every_check():
    report = kit.run(FakeDriver)
    assert [r.name for r in report.results] == [n for n, _ in kit.CHECKS]
    assert report.passed, [(r.name, r.detail) for r in report.results if r.status != kit.PASS]


class _TimeoutIsRejected(FakeConformantPac):
    def stamp(self, signed_payload, idempotency_key, credential):
        try:
            return super().stamp(signed_payload, idempotency_key, credential)
        except Exception:
            return P.StampResult(outcome=P.REJECTED, code="TIMEOUT")              # the MX-062 fault


class _NewUuidEachTime(FakeConformantPac):
    def _do_stamp(self, key):
        self.uuid_by_key[key] = f"SYN-{len(self.calls)}-UUID"                      # a second CFDI per retry
        return self.uuid_by_key[key]


class _IgnoresExpiry(FakeConformantPac):
    def __init__(self, **script):
        super().__init__(expired_fingerprints=(), **script)


class _NeverCancels(FakeConformantPac):
    def query_cancel_status(self, uuid, credential):
        return P.CancelStatusResult(outcome=P.PENDING)


def _failed(adapter_cls):
    report = kit.run(lambda: FakeDriver(adapter_cls(**({} if adapter_cls is _IgnoresExpiry else
                                                       {"expired_fingerprints": {"e" * 64}}))))
    return set(report.by_status(kit.FAIL)), report


def test_the_kit_catches_a_timeout_reported_as_rejected():
    failed, _ = _failed(_TimeoutIsRejected)
    assert {"timeout_unknown_status", "timeout_before_stamp"} <= failed


def test_the_kit_catches_a_second_cfdi_for_the_same_key():
    failed, _ = _failed(_NewUuidEachTime)
    assert {"duplicate_idempotency", "timeout_unknown_status"} <= failed


def test_the_kit_catches_an_expired_csd_that_is_stamped():
    failed, _ = _failed(_IgnoresExpiry)
    assert failed == {"csd_expired"}


def test_the_kit_catches_a_cancellation_that_never_settles():
    failed, report = _failed(_NeverCancels)
    assert failed == {"cancel_status_polling"}
    assert "not CANCELLED within 3 polls" in next(r.detail for r in report.results if r.name == "cancel_status_polling")


def test_a_scenario_the_sandbox_cannot_provoke_is_not_run_never_pass():
    class _NoTimeouts(FakeDriver):
        def timeout(self, after_stamp):
            raise kit.Unsupported("transport timeout")

    report = kit.run(_NoTimeouts)
    assert set(report.by_status(kit.NOT_RUN)) == {"timeout_unknown_status", "timeout_before_stamp"}
    assert not report.passed


def test_nothing_of_the_kit_or_the_fake_reaches_app():
    assert P._ADAPTERS == {} and P._PROVIDER_RETRY_CONFIG == {}
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "_mx_fake_pac" not in text and "_mx_pac_conformance" not in text and "FakeConformantPac" not in text, path

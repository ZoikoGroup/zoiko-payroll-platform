"""Client address resolution (trusted proxies only) and the startup guards.

* extract_client_ip must not let a caller choose its own address with a
  forwarding header: headers count only when the socket peer is a trusted
  proxy (settings.TRUSTED_PROXY_CIDRS), and X-Forwarded-For is read right to
  left so a client-prepended entry is ignored. The address feeds audit rows,
  machine-client new-network alerts (ZP-PRIV D06) and session fingerprints.
* The ZP-PRIV D09 non-production data guard must actually execute at
  startup: `@asynccontextmanager` belongs on `lifespan`, not on the guard
  (on the guard, calling it only built a context manager and enforced nothing).
"""
import inspect
from types import SimpleNamespace

import pytest

from app.core import correlation


def _request(peer, **headers):
    return SimpleNamespace(client=SimpleNamespace(host=peer),
                           headers={k.replace("_", "-"): v for k, v in headers.items()})


@pytest.fixture
def trust(monkeypatch):
    from app.config import settings

    def _set(value):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", value)
    _set("")
    return _set


def test_without_trusted_proxies_headers_are_ignored(trust):
    req = _request("203.0.113.9", cf_connecting_ip="1.2.3.4", x_real_ip="5.6.7.8",
                   x_forwarded_for="9.9.9.9")
    assert correlation.extract_client_ip(req) == "203.0.113.9"


def test_untrusted_peer_cannot_spoof_even_when_proxies_are_configured(trust):
    trust("10.0.0.0/8")
    req = _request("203.0.113.9", x_forwarded_for="1.2.3.4", cf_connecting_ip="1.2.3.4")
    assert correlation.extract_client_ip(req) == "203.0.113.9"


def test_trusted_proxy_header_is_used(trust):
    trust("10.0.0.0/8")
    assert correlation.extract_client_ip(_request("10.1.2.3", cf_connecting_ip="198.51.100.7")) == "198.51.100.7"
    assert correlation.extract_client_ip(_request("10.1.2.3", x_real_ip="198.51.100.8")) == "198.51.100.8"


def test_forwarded_for_is_read_right_to_left_skipping_trusted_hops(trust):
    trust("10.0.0.0/8, 192.168.0.0/16")
    # The client prepended a fake 1.1.1.1; the real client is the last untrusted hop.
    req = _request("10.0.0.5", x_forwarded_for="1.1.1.1, 198.51.100.20, 192.168.1.4")
    assert correlation.extract_client_ip(req) == "198.51.100.20"


def test_garbage_headers_fall_back_to_the_peer(trust):
    trust("10.0.0.0/8")
    req = _request("10.0.0.5", cf_connecting_ip="not-an-ip", x_forwarded_for="also, bad")
    assert correlation.extract_client_ip(req) == "10.0.0.5"


def test_ipv6_and_invalid_cidr_entries(trust):
    trust("2001:db8::/32, nonsense")
    assert correlation.extract_client_ip(_request("2001:db8::1", x_real_ip="2001:db9::5")) == "2001:db9::5"
    assert correlation.extract_client_ip(_request("2001:dead::1", x_real_ip="2001:db9::5")) == "2001:dead::1"


def test_non_ip_peer_and_missing_request(trust):
    assert correlation.extract_client_ip(_request("testclient", x_forwarded_for="1.2.3.4")) == "testclient"
    assert correlation.extract_client_ip(None) is None


def test_trusted_proxies_default_to_none():
    from app.config import Settings

    assert Settings.model_fields["TRUSTED_PROXY_CIDRS"].default == ""


# ── startup guards ──────────────────────────────────────────────────────────

def test_lifespan_is_the_context_manager_and_the_guard_is_a_plain_call():
    from app import main

    assert not inspect.isasyncgenfunction(main._enforce_nonprod_data_guard)
    assert inspect.isfunction(main._enforce_nonprod_data_guard)
    assert not hasattr(main._enforce_nonprod_data_guard, "__wrapped__")       # not an asynccontextmanager
    assert hasattr(main.lifespan, "__wrapped__") and inspect.isasyncgenfunction(main.lifespan.__wrapped__)


def test_the_nonprod_guard_really_enforces(monkeypatch):
    from app import main
    from app.core import nonprod_guard

    calls = []
    monkeypatch.setattr(nonprod_guard, "enforce", lambda db: calls.append(db) or "ok")
    monkeypatch.setattr("app.database.SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    main._enforce_nonprod_data_guard()
    assert len(calls) == 1

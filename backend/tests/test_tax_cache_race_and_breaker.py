"""
tests/test_tax_cache_race_and_breaker.py
----------------------------------------
Two cache failure modes not covered by test_tax_config_cache.py:

1. The stale-write race. A payroll run reads rows, a canonical write then
   commits and bumps the version token, and the run stores what it read.
   If the store keys the entry under the token current AT STORE TIME, the
   pre-write rows land under the post-write token and are served as fresh
   until the TTL expires. The token must be the one captured before the
   read.

2. An unreachable Redis. Every command carries a socket timeout, so without
   a circuit breaker each resolution pays that timeout several times over,
   per employee. After one connection failure the cache must be skipped
   outright until the cooldown elapses.
"""
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core import cache as cache_module
from app.modules.payroll.models import ContributionRate
from app.modules.payroll.engine import tax_resolver
from app.modules.payroll.engine.tax_cache import invalidate_tax_config_cache
from tests.test_tax_config_cache import (  # noqa: F401 — fake_redis is a fixture
    FakeRedis,
    _count_queries,
    _make_pack,
    _make_rate,
    _seed_version,
    fake_redis,
)


@pytest.fixture(autouse=True)
def _closed_breaker():
    """A breaker tripped by one test must never leak into the next."""
    cache_module.reset_circuit_breaker()
    yield
    cache_module.reset_circuit_breaker()


class TestStaleWriteRace:
    def test_rows_read_before_a_concurrent_write_are_not_served_after_it(self, db, fake_redis, monkeypatch):
        pack = _make_pack(db)
        rate = _make_rate(db, pack)
        _seed_version(fake_redis, 5)
        as_of = dt.date(2026, 6, 1)

        real_resolve = tax_resolver._resolve_uncached

        def resolve_then_concurrent_write(*args, **kwargs):
            result = real_resolve(*args, **kwargs)
            # A Super Admin edit lands, from its own session, after this run
            # read the old rows: it commits, then bumps the token (the real
            # write path's order). This run's already-loaded rows stay at the
            # old value, exactly as they would in a separate request.
            other = Session(bind=db.get_bind())
            try:
                other.get(ContributionRate, rate.id).employee_rate_pct = Decimal("10.0000")
                other.commit()
            finally:
                other.close()
            invalidate_tax_config_cache()
            return result

        monkeypatch.setattr(tax_resolver, "_resolve_uncached", resolve_then_concurrent_write)
        first = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert first[0][0].employee_rate_pct == Decimal("12.0000")  # the pre-write read

        monkeypatch.setattr(tax_resolver, "_resolve_uncached", real_resolve)
        db.expire_all()
        second = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        assert second[0][0].employee_rate_pct == Decimal("10.0000"), (
            "a pre-write read was cached under the post-write token and served as current"
        )

    def test_a_resolution_reads_the_version_token_once(self, db, fake_redis, monkeypatch):
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)
        calls = {"n": 0}
        real_get_version = cache_module.cache_get_version

        def counting_get_version(namespace):
            calls["n"] += 1
            return real_get_version(namespace)

        from app.modules.payroll.engine import tax_cache
        monkeypatch.setattr(tax_cache, "cache_get_version", counting_get_version)

        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)  # miss + store
        assert calls["n"] == 1
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)  # hit
        assert calls["n"] == 2


class UnreachableRedis(FakeRedis):
    """Every command fails the way a dead host does, and is counted."""

    def __init__(self):
        super().__init__()
        self.attempts = 0

    def _maybe_fail(self, cmd):
        self.attempts += 1
        raise ConnectionError(f"simulated connection refused on {cmd}")


@pytest.fixture()
def dead_redis(monkeypatch):
    client = UnreachableRedis()
    monkeypatch.setattr(cache_module.settings, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(cache_module, "_redis_client", client)
    return client


class TestCircuitBreaker:
    def test_one_connection_failure_stops_further_attempts(self, db, dead_redis):
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)

        first = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        attempts_after_first = dead_redis.attempts
        assert attempts_after_first == 1, "the first failure should trip the breaker immediately"

        for _ in range(20):  # a payroll run's worth of resolutions
            result = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
            assert result[0][0].employee_rate_pct == first[0][0].employee_rate_pct

        assert dead_redis.attempts == attempts_after_first, "Redis was retried while the breaker was open"

    def test_resolution_is_still_correct_while_the_breaker_is_open(self, db, dead_redis):
        _make_rate(db, _make_pack(db))
        rates, slabs, pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 6, 1))
        assert pack is not None
        assert rates[0].employee_rate_pct == Decimal("12.0000")

    def test_redis_is_probed_again_after_the_cooldown(self, db, dead_redis, monkeypatch):
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert dead_redis.attempts == 1

        monkeypatch.setattr(cache_module, "_breaker_open_until", 0.0)  # cooldown elapsed
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert dead_redis.attempts == 2

    def test_a_command_error_does_not_trip_the_breaker(self, db, fake_redis):
        """Redis answered, so it is reachable — only connection loss trips it."""
        _make_rate(db, _make_pack(db))
        fake_redis.fail_on = {"GET"}  # raises RuntimeError, not a connection error

        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 6, 1))

        assert not cache_module._breaker_is_open()
        assert cache_module.get_redis_client() is fake_redis

    def test_open_breaker_skips_the_version_read_on_invalidation_without_raising(self, db, dead_redis):
        cache_module.cache_get(" any ")  # trips it
        assert cache_module._breaker_is_open()
        attempts = dead_redis.attempts
        assert invalidate_tax_config_cache() == 1
        assert dead_redis.attempts == attempts

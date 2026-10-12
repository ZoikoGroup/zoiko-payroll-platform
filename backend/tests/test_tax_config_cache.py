"""
tests/test_tax_config_cache.py
-------------------------------
Correctness tests for the Redis tax-configuration cache
(engine/tax_cache.py), wired into tax_resolver.resolve_tax_configuration.

The bar here is deliberately higher than "it returns something". This cache
sits directly in front of statutory net-pay arithmetic, so every test
below is written against one of three failure modes that would produce a
WRONG number rather than a slow request:

  1. A column silently dropped in serialization (payroll reads a field
     that comes back None).
  2. A stale entry served after the underlying data changed.
  3. Two different questions sharing one cache entry (date/state/regime
     collisions) — i.e. historical payroll not reproducing.

The whole module is exercised against a hand-written in-memory fake Redis
rather than fakeredis, which is not a project dependency. The fake
implements only the four commands the cache layer actually calls (GET,
SETEX, INCR, plus SCAN/UNLINK for completeness), so a test failure points
at cache logic rather than at a third-party emulator.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core import cache as cache_module
from app.modules.payroll.engine import tax_resolver
from app.modules.payroll.engine.tax_cache import (
    TAX_CACHE_VERSION_KEY,
    invalidate_tax_config_cache,
)


class FakeRedis:
    """Minimal synchronous stand-in for redis.Redis.

    Deliberately not a general emulator: it stores strings, counts INCR,
    and can be told to raise on any command so cache-failure fallback is
    testable.
    """

    def __init__(self):
        self.store = {}
        self.fail_on = set()
        self.get_calls = 0
        self.set_calls = 0

    def _maybe_fail(self, cmd):
        if cmd in self.fail_on:
            raise RuntimeError(f"simulated Redis {cmd} failure")

    def get(self, key):
        self._maybe_fail("GET")
        self.get_calls += 1
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self._maybe_fail("SETEX")
        self.set_calls += 1
        self.store[key] = value
        return True

    def incr(self, key):
        """Counters live in the SAME keyspace as stored values.

        Real Redis has one keyspace, so a value written by INCR is visible
        to a subsequent GET. Splitting them across two dicts here made
        INCR and GET disagree in a way the real server never would, which
        is precisely the failure mode cache_get_version's docstring warns
        about — so the fake must not be the thing that hides it.
        """
        self._maybe_fail("INCR")
        # Real Redis INCR treats an absent key as 0 and returns 1, rather
        # than erroring on None.
        current = self.store.get(key)
        self.store[key] = str((0 if current is None else int(current)) + 1)
        return int(self.store[key])

    def delete(self, *keys):
        self._maybe_fail("DELETE")
        for k in keys:
            self.store.pop(k, None)
        return len(keys)

    def unlink(self, *keys):
        return self.delete(*keys)

    def scan_iter(self, match="*", count=None):
        import fnmatch

        self._maybe_fail("SCAN")
        for k in list(self.store):
            if fnmatch.fnmatch(k, match):
                yield k


@pytest.fixture()
def fake_redis(monkeypatch):
    """Install a FakeRedis as the process-wide cache client.

    get_redis_client() memoizes its first successful construction and
    returns early on `if not settings.REDIS_URL`, so a test has to satisfy
    BOTH conditions to get its fake in — patching the module global alone
    would silently leave the cache disabled and every "cache is used"
    assertion below would pass for the wrong reason (it would just be
    reading the DB each time and comparing equal results).
    """
    client = FakeRedis()
    # URL is set for realism/documentation, but get_redis_client() returns
    # the memoized client before consulting it, so the fake does not
    # actually depend on the `redis` package being importable.
    monkeypatch.setattr(cache_module.settings, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(cache_module, "_redis_client", client)
    return client


def _seed_version(client, value: int) -> None:
    """Pin the version token so INCR-from-absent is not what a test measures.

    The real INCR starts a missing counter at 1, which makes "did this
    write bump the version?" assertions read as 1 -> 1 and look like a
    failed invalidation. Seeding an explicit base keeps the arithmetic in
    each test about the bump, not about counter bootstrapping.
    """
    client.store[TAX_CACHE_VERSION_KEY] = str(value)


@pytest.fixture()
def no_cache(monkeypatch):
    """Force the cache fully off (the shipped default when REDIS_URL="")."""
    monkeypatch.setattr(cache_module.settings, "REDIS_URL", "")
    monkeypatch.setattr(cache_module, "_redis_client", None)
    return None


def _make_pack(db, **overrides):
    from app.modules.payroll.models import JurisdictionPack

    fields = dict(
        pack_id="IN-PAYROLL-2026-V1",
        jurisdiction_country="IN",
        pack_type="tax",
        version="1.0",
        status="Active",
        effective_from=dt.date(2026, 4, 1),
    )
    fields.update(overrides)
    pack = JurisdictionPack(**fields)
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _make_rate(db, pack, **overrides):
    from app.modules.payroll.models import ContributionRate

    fields = dict(
        organization_id=None,
        jurisdiction_pack_id=pack.id,
        component_key="pf",
        label="Provident Fund",
        employee_share="12.00%",
        employer_share="12.00%",
        total="24.00%",
        employee_rate_pct=Decimal("12.0000"),
        employer_rate_pct=Decimal("12.0000"),
        jurisdiction_country="IN",
        sort_order=1,
    )
    fields.update(overrides)
    row = ContributionRate(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_slab(db, pack, **overrides):
    from app.modules.payroll.models import TaxSlab

    fields = dict(
        organization_id=None,
        jurisdiction_pack_id=pack.id,
        min_amount=Decimal("0.00"),
        max_amount=Decimal("250000.00"),
        rate_pct=Decimal("5.0000"),
        rate_label="5%",
        tax_formula="Nil",
        jurisdiction_country="IN",
        rule_type="MARGINAL_RATE",
        sort_order=1,
    )
    fields.update(overrides)
    row = TaxSlab(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _count_queries(db):
    """Attach a statement counter, and return a function that reads it live.

    Listens on the engine reached via the session's bind (a Session has no
    `.engine`), and returns a closure rather than a dict so a test reads
    the count at the moment it asserts instead of at an earlier moment.
    """
    counter = {"n": 0}
    engine = db.get_bind()

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _on_execute)

    def stop():
        event.remove(engine, "before_cursor_execute", _on_execute)

    return counter, stop


# ── Serialization fidelity ───────────────────────────────────────────────

class TestRowRoundTrip:
    def test_every_mapped_column_survives_the_round_trip(self, db):
        """A dropped column is the quietest way to break payroll.

        The engine reads these rows by attribute across many country
        modules. This asserts the reflective encoder picked up EVERY
        column the mapper declares, rather than trusting a curated list.
        """
        from app.modules.payroll.engine.tax_cache import _decode_row, _encode_row
        from app.modules.payroll.models import ContributionRate
        from sqlalchemy import inspect

        rate = _make_rate(db, _make_pack(db))

        payload = _encode_row(rate)
        mapped = {c.key for c in inspect(rate).mapper.column_attrs}
        assert set(payload) == mapped, (
            f"encoder missed columns: {sorted(mapped - set(payload))}"
        )

        restored = _decode_row(ContributionRate, payload)
        for key_name in mapped:
            original = getattr(rate, key_name)
            got = getattr(restored, key_name, "<missing>")
            if isinstance(original, Decimal):
                assert got == original, f"{key_name}: {original!r} != {got!r}"
            elif isinstance(original, dt.datetime):
                assert got == original
            else:
                assert got == original, f"{key_name}: {original!r} != {got!r}"

    def test_decimal_precision_is_not_lost_to_float_json(self, db):
        """Decimal must not round-trip through a binary float.

        json.dumps(Decimal("0.1")) emits 0.1, and float("0.1") is not
        Decimal("0.1"). On a rate that would show up as a net-pay
        difference of a fraction of a unit; the fix is str() on write and
        Decimal() on read.
        """
        from app.modules.payroll.engine.tax_cache import _decode_row, _encode_row
        from app.modules.payroll.models import ContributionRate

        rate = _make_rate(db, _make_pack(db), employee_rate_pct=Decimal("12.1234"))
        restored = _decode_row(ContributionRate, _encode_row(rate))
        assert restored.employee_rate_pct == Decimal("12.1234")
        assert isinstance(restored.employee_rate_pct, Decimal)

    def test_string_columns_stay_strings(self, db):
        """Coercion must be driven by column type, not by JSON shape.

        A tax_regime of "New" must not come back as a Decimal or a
        date just because some other column on the same row is numeric.
        """
        from app.modules.payroll.engine.tax_cache import _decode_row, _encode_row
        from app.modules.payroll.models import TaxSlab

        slab = _make_slab(db, _make_pack(db), tax_regime="New")
        restored = _decode_row(TaxSlab, _encode_row(slab))
        assert restored.tax_regime == "New"
        assert isinstance(restored.tax_regime, str)

    def test_dates_round_trip_as_dates(self, db):
        from app.modules.payroll.engine.tax_cache import _decode_row, _encode_row
        from app.modules.payroll.models import JurisdictionPack

        pack = _make_pack(db, effective_to=dt.date(2027, 3, 31))
        restored = _decode_row(JurisdictionPack, _encode_row(pack))
        assert restored.effective_from == dt.date(2026, 4, 1)
        assert restored.effective_to == dt.date(2027, 3, 31)
        assert isinstance(restored.effective_to, dt.date)

    def test_rehydrated_rows_are_transient_not_session_bound(self, db):
        """Cached rows must carry no Session.

        A rehydrated row that looked attached could be mutated in place by
        a caller and that mutation would leak into the shared cache for
        every subsequent payroll. Transient instances make that a loud
        error instead.
        """
        from app.modules.payroll.engine.tax_cache import _decode_row, _encode_row
        from app.modules.payroll.models import ContributionRate
        from sqlalchemy import inspect as sa_inspect

        rate = _make_rate(db, _make_pack(db))
        restored = _decode_row(ContributionRate, _encode_row(rate))
        state = sa_inspect(restored)
        assert state.transient is True
        assert state.session is None
        # Still a real instance of the mapped class, so downstream
        # isinstance checks and attribute access behave normally.
        assert isinstance(restored, ContributionRate)

    def test_unknown_keys_in_a_payload_are_ignored(self, db):
        """A payload from a different build must not crash the payroll run."""
        from app.modules.payroll.engine.tax_cache import _decode_row
        from app.modules.payroll.models import ContributionRate

        restored = _decode_row(ContributionRate, {"component_key": "pf", "column_from_the_future": "x"})
        assert restored.component_key == "pf"

    def test_undecodable_numeric_falls_back_to_none_not_a_wrong_number(self, db):
        """A value that will not coerce is dropped, never half-converted.

        A wrong Decimal reaching a payslip is materially worse than a None
        that the caller's own validation can surface.
        """
        from app.modules.payroll.engine.tax_cache import _decode_row
        from app.modules.payroll.models import ContributionRate

        restored = _decode_row(ContributionRate, {"component_key": "pf", "employee_rate_pct": "not-a-number"})
        assert restored.employee_rate_pct is None
        assert restored.component_key == "pf"


# ── Cache hit / miss behaviour ───────────────────────────────────────────

class TestResolutionCaching:
    def test_disabled_by_default_always_reads_the_database(self, db, no_cache):
        """With no REDIS_URL the resolver must behave exactly as before.

        This is the guarantee that makes the whole feature safe to land:
        the default deployment cannot be affected by a cache bug at all.
        """
        _make_rate(db, _make_pack(db))
        rates, _slabs, pack = tax_resolver.resolve_tax_configuration(
            db, "IN", payroll_date=dt.date(2026, 6, 1)
        )
        assert pack is not None
        assert len(rates) == 1
        assert rates[0].employee_rate_pct == Decimal("12.0000")

    def test_second_resolution_is_served_from_cache_without_queries(self, db, fake_redis):
        """The whole point: repeat resolution must not re-query."""
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)

        first = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert first[2] is not None

        counter, stop = _count_queries(db)
        try:
            second = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        finally:
            stop()

        assert counter["n"] == 0, "cached resolution still issued SQL"
        assert len(second[0]) == 1
        assert second[0][0].employee_rate_pct == Decimal("12.0000")

    def test_cached_result_matches_uncached_result_exactly(self, db, fake_redis):
        """Parity is the real contract, and it must be asserted field by field.

        Comparing just row counts would pass while a rate came back as
        the wrong value — the failure that actually reaches an employee.
        """
        pack = _make_pack(db)
        _make_rate(db, pack, employee_rate_pct=Decimal("12.3456"))
        _make_slab(db, pack, min_amount=Decimal("0.00"), rate_pct=Decimal("5.0000"))
        as_of = dt.date(2026, 6, 1)

        live_rates, live_slabs, live_pack = tax_resolver._resolve_uncached(
            db, "IN", state=None, tax_regime=None, as_of=as_of
        )
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)  # populate
        cached_rates, cached_slabs, cached_pack = tax_resolver.resolve_tax_configuration(
            db, "IN", payroll_date=as_of
        )

        assert cached_pack.id == live_pack.id
        assert cached_pack.pack_id == live_pack.pack_id
        assert cached_pack.status == live_pack.status
        assert len(cached_rates) == len(live_rates)
        assert len(cached_slabs) == len(live_slabs)
        for got, want in zip(cached_rates, live_rates):
            assert got.component_key == want.component_key
            assert got.employee_rate_pct == want.employee_rate_pct
            assert got.employer_rate_pct == want.employer_rate_pct
            assert got.tax_regime == want.tax_regime
            assert got.jurisdiction_pack_id == want.jurisdiction_pack_id
        for got, want in zip(cached_slabs, live_slabs):
            assert got.min_amount == want.min_amount
            assert got.max_amount == want.max_amount
            assert got.rate_pct == want.rate_pct
            assert got.rule_type == want.rule_type

    def test_a_miss_falls_through_to_the_database_and_populates(self, db, fake_redis):
        _make_rate(db, _make_pack(db))
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 6, 1))
        assert fake_redis.set_calls == 1

    def test_missing_configuration_is_cached_as_a_negative_result(self, db, fake_redis):
        """"No pack configured" is a real answer and worth caching.

        Without this, every payroll for an unconfigured jurisdiction
        re-runs the pack lookup forever. The `found` flag is what keeps
        that distinct from a cache miss.
        """
        as_of = dt.date(2026, 6, 1)
        rates, slabs, pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert (rates, slabs, pack) == ([], [], None)

        counter, stop = _count_queries(db)
        try:
            again = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        finally:
            stop()
        assert counter["n"] == 0, "negative result was not cached"
        assert again == ([], [], None)

    def test_corrupt_entry_degrades_to_a_miss_not_a_short_list(self, db, fake_redis):
        """A damaged entry must never look like a legitimately small result.

        Returning a partial rate set here is the worst available outcome:
        the caller cannot distinguish it from a jurisdiction that really
        has one rate, and would compute a wrong net pay with no signal.
        """
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        # Corrupt every stored entry into a value that decodes to nothing usable.
        for k in list(fake_redis.store):
            if k.startswith("zoiko:taxcfg|"):
                fake_redis.store[k] = '{"found": true, "rates": "not-a-list", "slabs": []}'

        rates, _slabs, pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert pack is not None
        assert len(rates) == 1, "corrupt cache entry produced a short rate list instead of a refetch"


# ── Key construction: the collision hazards ──────────────────────────────

class TestCacheKeyIsolation:
    def test_different_payroll_dates_do_not_share_an_entry(self, db, fake_redis):
        """Historical reproducibility.

        Pack selection and row-level effective dating both depend on the
        exact date. If two dates shared a key, a period run before a rate
        change could be answered with the post-change rate, and a re-run
        of an old payroll would no longer reproduce its original number.
        """
        pack = _make_pack(db)
        _make_rate(db, pack, component_key="pf", employee_rate_pct=Decimal("10.0000"), sort_order=1)

        june = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 6, 1))
        june_rates = {r.employee_rate_pct for r in june[0]}
        assert june_rates == {Decimal("10.0000")}

        # A second rate that only comes into effect on 1 July.
        _make_rate(
            db, pack, component_key="pf", employee_rate_pct=Decimal("15.0000"),
            effective_from=dt.date(2026, 7, 1), sort_order=2,
        )
        # An explicit write invalidates, so this reflects live rows.
        august = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 8, 1))
        august_rates = {r.employee_rate_pct for r in august[0]}
        assert Decimal("15.0000") in august_rates, "a rate effective from 1 July was missing for an August payroll"

        # The June answer must be unchanged by the July row: a historical
        # payroll re-run has to reproduce its original number, which means
        # the June entry must not have been overwritten by the August read.
        june_again = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=dt.date(2026, 6, 1))
        assert {r.employee_rate_pct for r in june_again[0]} == {Decimal("10.0000")}, (
            "a payroll for June saw a rate that only takes effect in July"
        )

    def test_different_states_do_not_share_an_entry(self, db, fake_redis):
        _make_slab(db, _make_pack(db, pack_id="US-2026", jurisdiction_country="US", jurisdiction_state="CA",
                                  effective_from=dt.date(2026, 1, 1)))
        ca = tax_resolver.resolve_tax_configuration(db, "US", state="CA", payroll_date=dt.date(2026, 6, 1))
        assert ca[2] is not None and ca[2].jurisdiction_state == "CA"

        # A different state is a genuinely different question.
        ny = tax_resolver.resolve_tax_configuration(db, "US", state="NY", payroll_date=dt.date(2026, 6, 1))
        assert ny[2] is None

    def test_different_regimes_do_not_share_an_entry(self, db, fake_redis):
        pack = _make_pack(db)
        _make_slab(db, pack, tax_regime="New", min_amount=Decimal("0.00"), rate_pct=Decimal("5.0000"))
        _make_slab(db, pack, tax_regime="Old", min_amount=Decimal("0.00"), rate_pct=Decimal("30.0000"))

        new = tax_resolver.resolve_tax_configuration(db, "IN", tax_regime="New", payroll_date=dt.date(2026, 6, 1))
        old = tax_resolver.resolve_tax_configuration(db, "IN", tax_regime="Old", payroll_date=dt.date(2026, 6, 1))
        new_rates = {r.rate_pct for r in new[1]}
        old_rates = {r.rate_pct for r in old[1]}
        assert Decimal("5.0000") in new_rates
        assert Decimal("30.0000") in old_rates

    def test_country_and_state_cannot_be_confused_by_the_separator(self):
        """A naive join would make ("IN","New") collide with ("IN-New",None)."""
        from app.modules.payroll.engine.tax_cache import _cache_key

        a = _cache_key("IN", "New", None, dt.date(2026, 6, 1))
        b = _cache_key("IN-New", None, None, dt.date(2026, 6, 1))
        assert a != b

    def test_key_includes_the_version_token(self, db, fake_redis):
        from app.modules.payroll.engine.tax_cache import _cache_key

        before = _cache_key("IN", None, None, dt.date(2026, 6, 1))
        invalidate_tax_config_cache()
        after = _cache_key("IN", None, None, dt.date(2026, 6, 1))
        assert before != after


# ── Invalidation ─────────────────────────────────────────────────────────

class TestInvalidation:
    def test_upserting_a_canonical_rate_invalidates(self, db, fake_redis):
        from app.modules.payroll import service

        pack = _make_pack(db, status="Draft")
        _make_rate(db, pack)
        as_of = dt.date(2026, 6, 1)

        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        version_before = int(fake_redis.store.get(TAX_CACHE_VERSION_KEY, 1))

        service.upsert_canonical_contribution_rate(db, service.CanonicalContributionRateUpsert(
            jurisdictionPackId=pack.id, jurisdictionCountry="IN", componentKey="esi",
            label="ESI", employeeSharePct=Decimal("0.75"), employerSharePct=Decimal("3.25"),
            sortOrder=2,
        ))

        assert int(fake_redis.store[TAX_CACHE_VERSION_KEY]) > version_before

    def test_activating_a_pack_invalidates(self, db, fake_redis):
        """A status flip alone changes what resolves.

        _find_active_tax_pack filters status == "Active", so a just-
        activated pack must not keep serving the cached "no pack
        configured" answer.
        """
        from app.modules.payroll import service

        pack = _make_pack(db, status="Draft")
        _make_rate(db, pack)
        as_of = dt.date(2026, 6, 1)
        assert tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)[2] is None

        pack.status = "Active"
        db.commit()
        service.set_jurisdiction_pack_status(db, pack.id, "Active", bypass_approver_check=True)

        rates, _slabs, resolved = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert resolved is not None, "activating a pack did not invalidate the cached negative result"
        assert len(rates) == 1

    def test_deleting_a_canonical_rate_invalidates(self, db, fake_redis):
        from app.modules.payroll import service

        pack = _make_pack(db, status="Draft")
        rate = _make_rate(db, pack)
        as_of = dt.date(2026, 6, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        service.delete_canonical_contribution_rate(db, rate.id)

        rates, _slabs, _pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert rates == []

    def test_bump_is_a_noop_against_an_unreachable_redis(self, db, fake_redis):
        """An outage during invalidation must not raise into the write path.

        The data is already committed at this point; raising here would
        turn a successful tax-config write into a 500 and leave the caller
        thinking the edit failed when it actually landed.
        """
        from app.modules.payroll import service

        pack = _make_pack(db, status="Draft")
        rate = _make_rate(db, pack)
        fake_redis.fail_on.add("INCR")
        service.delete_canonical_contribution_rate(db, rate.id)  # must not raise
        assert service.list_canonical_contribution_rates(db) == []

    def test_first_bump_on_a_fresh_cache_actually_changes_the_token(self, db, fake_redis):
        """A bump from an ABSENT counter must still invalidate.

        INCR on a missing key yields 1, and cache_get_version also reports
        1 for a missing key — so a naive single INCR produces the same
        token the pre-bump read used, and the first write after a cold
        start would leave every existing entry readable for its full TTL.
        This is the single easiest invalidation bug to ship, because the
        second and later bumps all behave correctly.
        """
        from app.core.cache import cache_get_version
        from app.modules.payroll.engine.tax_cache import _cache_key

        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)

        before = _cache_key("IN", None, None, as_of)
        invalidate_tax_config_cache()  # very first bump, counter absent
        after = _cache_key("IN", None, None, as_of)
        assert before != after, "first bump on a cold cache did not change the token"
        assert cache_get_version(TAX_CACHE_VERSION_KEY) > 1

    def test_data_written_before_a_cold_start_bump_is_not_served(self, db, fake_redis):
        """The user-visible consequence of the bug above.

        Populates a cache, then bumps as the very first write to an
        otherwise-empty version key, and asserts the new data is visible.
        """
        from app.modules.payroll.engine.tax_cache import _cache_key

        pack = _make_pack(db)
        _make_rate(db, pack, employee_rate_pct=Decimal("10.0000"), sort_order=1)
        as_of = dt.date(2026, 6, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        # Model a cold counter with entries already written under token 1.
        fake_redis.store[TAX_CACHE_VERSION_KEY] = "1"
        stale_key = _cache_key("IN", None, None, as_of)
        for k in list(fake_redis.store):
            if k.startswith("zoiko:taxcfg|"):
                fake_redis.store[stale_key] = fake_redis.store.pop(k)

        _make_rate(
            db, pack, component_key="pf", employee_rate_pct=Decimal("20.0000"), sort_order=2
        )
        invalidate_tax_config_cache()

        rates, _slabs, _pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        seen = {r.employee_rate_pct for r in rates}
        assert seen == {Decimal("10.0000"), Decimal("20.0000")}, (
            f"expected both live rates after the write; a stale or empty set means "
            f"the cold-start bump failed to invalidate. Got: {seen}"
        )

    def test_an_entry_written_under_an_old_token_is_never_returned(self, db, fake_redis):
        """Defence against a lost race between read and write."""
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)
        _seed_version(fake_redis, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        # Simulate an entry that outlived its token (e.g. a writer that
        # read version N, then a bump landed before it wrote).
        for k in list(fake_redis.store):
            if k.startswith("zoiko:taxcfg|"):
                fake_redis.store[k] = (
                    '{"found": true, "version": 1, "pack": {"id": 999}, '
                    '"rates": [], "slabs": []}'
                )
        invalidate_tax_config_cache()

        rates, _slabs, pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert pack.id != 999, "an entry from a superseded version token was served"
        assert len(rates) == 1

    def test_invalidation_with_no_redis_is_a_silent_no_op(self, db, no_cache):
        from app.modules.payroll import service

        pack = _make_pack(db, status="Draft")
        rate = _make_rate(db, pack)
        # Must not raise or otherwise disturb the write path when caching
        # is switched off.
        service.delete_canonical_contribution_rate(db, rate.id)
        assert service.list_canonical_contribution_rates(db) == []


# ── Graceful degradation ─────────────────────────────────────────────────

class TestFailureModes:
    @pytest.mark.parametrize("failing", ["GET", "SETEX", "INCR"])
    def test_redis_errors_never_break_payroll(self, db, fake_redis, failing):
        """A cache outage must degrade to the database, never to an error.

        This is the property that lets the cache be safe to enable at all:
        the worst a Redis outage can do is remove a speedup.
        """
        _make_rate(db, _make_pack(db))
        as_of = dt.date(2026, 6, 1)
        tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)

        fake_redis.fail_on.add(failing)
        rates, _slabs, pack = tax_resolver.resolve_tax_configuration(db, "IN", payroll_date=as_of)
        assert pack is not None
        assert len(rates) == 1
        assert rates[0].employee_rate_pct == Decimal("12.0000")

    def test_redis_silently_returning_none_client_is_a_miss(self, db, fake_redis, monkeypatch):
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: None)
        _make_rate(db, _make_pack(db))
        rates, _slabs, pack = tax_resolver.resolve_tax_configuration(
            db, "IN", payroll_date=dt.date(2026, 6, 1)
        )
        assert pack is not None and len(rates) == 1

    def test_version_fallback_never_regresses_to_zero(self, db, fake_redis):
        """A read fallback of 0 would let a token-1 entry be found again.

        cache_get_version pins its unreachable-Redis fallback to 1 for
        exactly this reason; the counter is what proves the two sides
        agree.
        """
        fake_redis.fail_on.add("GET")
        assert cache_module.cache_get_version(TAX_CACHE_VERSION_KEY) == 1
        fake_redis.fail_on.discard("GET")
        invalidate_tax_config_cache()
        assert cache_module.cache_get_version(TAX_CACHE_VERSION_KEY) == 2

    def test_non_integer_version_token_is_treated_as_missing(self, db, fake_redis):
        fake_redis.store[TAX_CACHE_VERSION_KEY] = "garbage"
        assert cache_module.cache_get_version(TAX_CACHE_VERSION_KEY) == 1

    def test_invalidation_is_a_single_incr_not_a_keyspace_scan(self, db, fake_redis):
        """O(1) invalidation, so it stays cheap as the keyspace grows."""
        _make_rate(db, _make_pack(db))
        for month in range(1, 13):
            tax_resolver.resolve_tax_configuration(
                db, "IN", payroll_date=dt.date(2026, month, 1)
            )
        assert len([k for k in fake_redis.store if k.startswith("zoiko:taxcfg|")]) == 12

        fake_redis.fail_on.add("SCAN")
        invalidate_tax_config_cache()  # would raise if it scanned
        assert int(fake_redis.store[TAX_CACHE_VERSION_KEY]) == 2

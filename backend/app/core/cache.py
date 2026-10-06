"""
app/core/cache.py
------------------
Redis-backed cache layer for the Zoiko Payroll Platform.

Synchronous get/set interface with JSON serialization, TTL support, and
graceful degradation when Redis is unavailable.

The interface is synchronous on purpose: the platform's data access layer
(``app.database.SessionLocal``) is synchronous SQLAlchemy, and Celery workers
are synchronous processes. An async client would force ``await`` at every
call site and gain nothing.

Usage:
    from app.core.cache import cache_get, cache_set

    # Set a value with TTL
    cache_set("my_key", {"data": "value"}, ttl=3600)

    # Get a value
    value = cache_get("my_key")

The cache degrades to a no-op when Redis is unconfigured or unreachable, so
a cache outage can never take the payroll calculation path down with it.
"""
import json
import logging
import threading
import time
from typing import Any, List, Optional

try:
    import redis  # type: ignore
    from redis.exceptions import ConnectionError as RedisConnectionError  # type: ignore
    from redis.exceptions import RedisError  # type: ignore
    from redis.exceptions import TimeoutError as RedisTimeoutError  # type: ignore
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    redis = None
    RedisError = Exception  # type: ignore
    RedisConnectionError = ConnectionError  # type: ignore
    RedisTimeoutError = TimeoutError  # type: ignore
    REDIS_AVAILABLE = False

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[Any] = None

# ── Circuit breaker ──────────────────────────────────────────────────────
# Every command carries a 2s socket timeout. Without a breaker, an
# unreachable Redis costs that timeout on EVERY call — and one tax
# resolution makes several calls, once per employee — so a 500-employee
# payroll run would stall for many minutes instead of simply falling back
# to the database. After one connection-level failure the cache is skipped
# entirely for _BREAKER_COOLDOWN_SECONDS, then one call is allowed through
# to probe whether Redis is back.
#
# Only connection/timeout failures trip it. A command-level error (bad
# value, wrong type) means Redis is up and answering, so skipping it would
# only hide the real problem.
_BREAKER_COOLDOWN_SECONDS = 30.0
_breaker_open_until = 0.0
_breaker_lock = threading.Lock()
_CONNECTION_ERRORS = (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError, OSError)


def _breaker_is_open() -> bool:
    return time.monotonic() < _breaker_open_until


def _record_failure(exc: BaseException) -> None:
    """Open the breaker if `exc` means Redis is unreachable."""
    global _breaker_open_until
    if not isinstance(exc, _CONNECTION_ERRORS):
        return
    with _breaker_lock:
        already_open = _breaker_is_open()
        _breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SECONDS
    if not already_open:
        logger.warning(
            f"Redis unreachable ({exc}); cache bypassed for "
            f"{_BREAKER_COOLDOWN_SECONDS:.0f}s, reading from the database."
        )


def reset_circuit_breaker() -> None:
    """Close the breaker immediately. For tests and teardown."""
    global _breaker_open_until
    with _breaker_lock:
        _breaker_open_until = 0.0


def get_redis_client() -> Optional[Any]:
    """Return a lazily-created synchronous Redis client, or None.

    None means "no cache": Redis is not configured, not installed, or could
    not be constructed. Callers must treat None as a miss, never as an error.

    An already-present client is returned before the import/config checks.
    This function is the only thing that ever assigns `_redis_client` from a
    real driver, so the global is None whenever redis is genuinely
    unavailable — checking it first therefore cannot accidentally enable a
    cache that was meant to be off. It does mean an injected client (tests
    substitute a fake rather than depending on the real driver being
    installed) is honoured, which is what makes this layer unit-testable in
    an environment where `pip install redis` has not been run.
    """
    global _redis_client

    if _breaker_is_open():
        return None

    if _redis_client is not None:
        return _redis_client

    if not REDIS_AVAILABLE or redis is None:
        return None

    if not settings.REDIS_URL:
        return None

    try:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        return _redis_client
    except Exception as e:  # pragma: no cover - construction rarely fails
        logger.warning(f"Failed to initialize Redis client: {e}. Cache disabled.")
        _redis_client = None
        return None


def reset_redis_client() -> None:
    """Reset the cached Redis client singleton, closing it if open.

    Useful in tests and teardown to force re-initialization on next call.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            close_fn = getattr(_redis_client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
        _redis_client = None
    reset_circuit_breaker()


def cache_get(key: str) -> Optional[Any]:
    """Get a value from cache. Returns None on miss or any cache problem."""
    client = get_redis_client()
    if client is None:
        return None

    try:
        value = client.get(key)
    except RedisError as e:
        _record_failure(e)
        logger.warning(f"Redis GET error for key '{key}': {e}")
        return None
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Unexpected Redis GET error for key '{key}': {e}")
        return None

    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Cache value for key '{key}' is not valid JSON: {e}")
        return None


def cache_set(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Set a value in cache with TTL. Returns False if not cached."""
    client = get_redis_client()
    if client is None:
        return False

    if ttl is None:
        ttl = getattr(settings, "REDIS_TTL_SECONDS", 3600)
    if ttl is None or ttl <= 0:
        ttl = 3600

    try:
        serialized = json.dumps(value, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"Value for key '{key}' is not JSON-serializable: {e}")
        return False

    try:
        client.setex(key, ttl, serialized)
        return True
    except RedisError as e:
        _record_failure(e)
        logger.warning(f"Redis SET error for key '{key}': {e}")
        return False
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Unexpected Redis SET error for key '{key}': {e}")
        return False


def cache_delete(key: str) -> bool:
    """Delete a key. Returns True if the delete was issued."""
    client = get_redis_client()
    if client is None:
        return False

    try:
        client.delete(key)
        return True
    except RedisError as e:
        _record_failure(e)
        logger.warning(f"Redis DELETE error for key '{key}': {e}")
        return False
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Unexpected Redis DELETE error for key '{key}': {e}")
        return False


def cache_get_version(namespace: str) -> int:
    """Read the current version token for a cache namespace.

    Versioned namespacing is how the tax cache gets O(1) invalidation
    without a keyspace scan: every cached key embeds this token, so
    bumping the token on a write orphans every existing entry at once
    (they simply stop being looked up and expire on their own TTL).

    Returns 1 when Redis is unavailable or the token has never been set.
    A constant fallback is safe here specifically because it is only ever
    *bumped* on write: an unreachable Redis means no entry was ever
    written either, so a read that falls through to the DB is already the
    correct behavior. The subtle failure to avoid would be a read
    returning 0 while writes bumped to 1 and 2 — that would let a stale
    entry written under token 1 be found again. Pinning the fallback to 1
    rather than 0 makes that impossible.
    """
    client = get_redis_client()
    if client is None:
        return 1
    try:
        raw = client.get(namespace)
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Redis GET error for version key '{namespace}': {e}")
        return 1
    if raw is None:
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning(f"Version key '{namespace}' is not an integer: {raw!r}")
        return 1


def cache_bump_version(namespace: str) -> int:
    """Atomically increment and return the version token for a namespace.

    Called on every write that could change what a cached read would
    resolve to. Uses INCR rather than GET-then-SET so two concurrent
    writers cannot both read N and both write N+1 (which would leave one
    writer's invalidation silently lost, letting a stale entry live out
    its full TTL against data that has since changed).
    """
    client = get_redis_client()
    if client is None:
        return 1
    try:
        new_value = int(client.incr(namespace))
        if new_value == 1:
            # INCR on an absent key yields 1 — which is exactly the value
            # cache_get_version reports for an absent key. Bumping once on
            # a fresh Redis would therefore produce the SAME token the
            # pre-bump read used, and every entry written before that first
            # bump would stay readable for its full TTL. Incrementing past
            # it guarantees any bump actually changes the token, which is
            # the entire point of the scheme.
            new_value = int(client.incr(namespace))
        return new_value
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Redis INCR error for version key '{namespace}': {e}")
        return 1


def cache_delete_pattern(pattern: str) -> int:
    """Delete every key matching a glob pattern. Returns the number deleted."""
    client = get_redis_client()
    if client is None:
        return 0

    deleted = 0
    try:
        # Unlink where available so a large keyspace does not block the server.
        unlink = getattr(client, "unlink", None)
        batch: List[str] = []
        for key in client.scan_iter(match=pattern, count=500):
            batch.append(key)
            if len(batch) >= 500:
                if callable(unlink):
                    unlink(*batch)
                else:  # pragma: no cover - Redis < 4.0
                    client.delete(*batch)
                deleted += len(batch)
                batch = []
        if batch:
            if callable(unlink):
                unlink(*batch)
            else:  # pragma: no cover - Redis < 4.0
                client.delete(*batch)
            deleted += len(batch)
    except RedisError as e:
        _record_failure(e)
        logger.warning(f"Redis SCAN/UNLINK error for pattern '{pattern}': {e}")
    except Exception as e:
        _record_failure(e)
        logger.warning(f"Unexpected Redis SCAN error for pattern '{pattern}': {e}")

    return deleted


# Alias for backwards compatibility
cache_clear_pattern = cache_delete_pattern


# ── Convenience functions for canonical pack caching ─────────────────────

CANONICAL_RATES_KEY_PREFIX = "canonical_rates"
CANONICAL_SLABS_KEY_PREFIX = "canonical_slabs"
CANONICAL_PACK_KEY_PREFIX = "canonical_pack"


def _canonical_rates_key(country: str, pack_id: str) -> str:
    return f"{CANONICAL_RATES_KEY_PREFIX}:{country}:{pack_id}"


def _canonical_slabs_key(country: str, pack_id: str) -> str:
    return f"{CANONICAL_SLABS_KEY_PREFIX}:{country}:{pack_id}"


def _canonical_pack_key(country: str, pack_id: str) -> str:
    return f"{CANONICAL_PACK_KEY_PREFIX}:{country}:{pack_id}"


def get_canonical_rates(country: str, pack_id: str) -> Optional[list]:
    """Get cached canonical contribution rates for a country/pack."""
    key = _canonical_rates_key(country, pack_id)
    return cache_get(key)


def set_canonical_rates(country: str, pack_id: str, rates: list, ttl: int = 3600) -> bool:
    """Cache canonical contribution rates for a country/pack."""
    key = _canonical_rates_key(country, pack_id)
    return cache_set(key, rates, ttl)


def get_canonical_slabs(country: str, pack_id: str) -> Optional[list]:
    """Get cached canonical tax slabs for a country/pack."""
    key = _canonical_slabs_key(country, pack_id)
    return cache_get(key)


def set_canonical_slabs(country: str, pack_id: str, slabs: list, ttl: int = 3600) -> bool:
    """Cache canonical tax slabs for a country/pack."""
    key = _canonical_slabs_key(country, pack_id)
    return cache_set(key, slabs, ttl)


def get_canonical_pack(country: str, pack_id: str) -> Optional[dict]:
    """Get cached canonical pack metadata (synchronous)."""
    key = _canonical_pack_key(country, pack_id)
    return cache_get(key)


def set_canonical_pack(country: str, pack_id: str, pack_data: dict, ttl: int = 3600) -> bool:
    """Cache canonical pack metadata."""
    key = _canonical_pack_key(country, pack_id)
    return cache_set(key, pack_data, ttl)


def invalidate_canonical_cache(country: str, pack_id: str) -> int:
    """Invalidate all cached data for a canonical pack (synchronous)."""
    count = 0
    if cache_delete(_canonical_rates_key(country, pack_id)):
        count += 1
    if cache_delete(_canonical_slabs_key(country, pack_id)):
        count += 1
    if cache_delete(_canonical_pack_key(country, pack_id)):
        count += 1
    return count


def invalidate_all_canonical_cache(country: str) -> int:
    """Invalidate all canonical cache for a country (synchronous)."""
    return (
        cache_delete_pattern(f"{CANONICAL_RATES_KEY_PREFIX}:{country}:*")
        + cache_delete_pattern(f"{CANONICAL_SLABS_KEY_PREFIX}:{country}:*")
        + cache_delete_pattern(f"{CANONICAL_PACK_KEY_PREFIX}:{country}:*")
    )
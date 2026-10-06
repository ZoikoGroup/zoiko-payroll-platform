"""
modules/payroll/engine/tax_cache
--------------------------------
Serialization layer for caching the CANONICAL tax configuration
(``tax_resolver.resolve_tax_configuration``'s result) in Redis.

Why this needs its own module rather than a decorator on the resolver: the
resolver returns live ORM objects attached to the request's Session, and
its result is statutory data that feeds net-pay arithmetic directly. Two
properties are therefore non-negotiable, and both are easy to get subtly
wrong:

1. EVERY column must survive the round trip, not a hand-picked subset.
   The engine reads these rows by many different attribute names across a
   dozen country modules (``r.employee_rate_pct``, ``s.min_amount``,
   ``r.tax_regime``, ``s.rule_type``, ``r.filing_status``, ...). A
   hand-maintained field list is a landmine: the day someone adds a column
   the engine starts reading, the cache silently returns ``None`` for it
   and the payroll number is quietly wrong with no error anywhere. So this
   module enumerates columns reflectively from SQLAlchemy's own mapper
   metadata, meaning a new model column is cached correctly the moment it
   exists rather than the day someone remembers to update a list.

2. Numeric/date types must not be mangled. ``employee_rate_pct`` is
   ``Numeric(7,4)`` and ``min_amount`` is ``Numeric(14,2)``; both are
   ``Decimal`` on the Python side. ``json.dumps`` renders a Decimal as a
   float, which is a lossy binary-float round trip — ``Decimal("0.1")``
   does not survive it. Every value is therefore encoded to its exact
   string form and decoded back through ``Decimal``/``date``, so a cached
   rate is bit-identical to the value the database returned.

Rows are rehydrated as *transient* instances of their real mapped class
(not dicts, not stand-in objects) so downstream ``isinstance`` checks,
attribute access, and the ``_normalize_regime_label``/component-key logic
all behave exactly as they do on a freshly-queried row. They are read-only
by contract: the canonical path never writes these rows, and a transient
instance carries no Session, so a stray write would raise loudly instead of
silently mutating cached shared state.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.cache import cache_bump_version, cache_get, cache_get_version, cache_set

logger = logging.getLogger(__name__)

# Namespace for the version token. Bumping this orphans every cached
# resolution in one O(1) operation; see cache_bump_version's docstring for
# why a counter beats deleting keys by pattern here.
TAX_CACHE_VERSION_KEY = "zoiko:taxcfg:version"

# Deliberately short. Tax configuration changes on the order of once a tax
# year, and a write bumps the version token that orphans the entry
# immediately — so this TTL is only a backstop against a missed
# invalidation, not the primary mechanism. Keeping it modest bounds the
# blast radius of any single missed bump to minutes rather than the
# default 3600s, which is appropriate for a number that becomes someone's
# net pay.
TAX_CACHE_TTL_SECONDS = 900


def _encode_value(value: Any) -> Any:
    """Convert a column value to something JSON round-trips exactly."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        # str(), not float() — see the module docstring's precision note.
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return {"__type__": type(value).__name__, "value": value.isoformat()}
    # Anything else (JSON columns holding dicts/lists, etc.) is passed
    # through to json.dumps untouched rather than being str()'d, which
    # would turn a structured value into an opaque string on read-back.
    return value


def _decode_value(payload: Any) -> Any:
    """Inverse of _encode_value, restoring the exact Python type."""
    if isinstance(payload, dict) and payload.get("__type__") in {"datetime", "date", "time"}:
        raw = payload["value"]
        try:
            if payload["__type__"] == "datetime":
                return dt.datetime.fromisoformat(raw)
            if payload["__type__"] == "date":
                return dt.date.fromisoformat(raw)
            return dt.time.fromisoformat(raw)
        except (KeyError, TypeError, ValueError) as e:
            # A malformed entry must degrade to "no cache", never to a
            # wrong value. Signalling with the raw payload lets the caller
            # discard the entry.
            logger.warning(f"Undecodable temporal cache value {raw!r}: {e}")
            raise
    if isinstance(payload, str):
        # Encoded Decimals arrive as strings. The caller's schema is known
        # at rehydration time, so the coercion is applied by
        # _decode_row using the column's declared type rather than guessing
        # here — a plain string column must stay a str.
        return payload
    return payload


def _column_types(model_cls) -> Dict[str, Any]:
    """Map every mapped attribute name to its SQLAlchemy type.

    Reads types off each ColumnProperty's underlying Column rather than
    off the property itself (a ColumnProperty has no `.type`) so that
    naming a column differently from its attribute — `label = Column("lbl", ...)` —
    still resolves to the right type.
    """
    types: Dict[str, Any] = {}
    for prop in inspect(model_cls).mapper.column_attrs:
        columns = getattr(prop, "columns", None)
        if columns:
            types[prop.key] = columns[0].type
    return types


def _encode_row(row) -> Dict[str, Any]:
    """Snapshot every mapped column of one ORM row."""
    mapper = inspect(row).mapper
    return {c.key: _encode_value(getattr(row, c.key, None)) for c in mapper.column_attrs}


def _decode_row(model_cls, payload: Dict[str, Any]):
    """Rebuild a transient instance of `model_cls` from _encode_row output.

    Coercion is driven by the column's declared SQLAlchemy type, so a
    Numeric column comes back as Decimal and a String column as str
    regardless of how the value was encoded. Falls back to the raw value
    when a key is unknown rather than raising, so a payload written by an
    older/newer build degrades to a partially-populated row instead of
    failing the whole payroll run.
    """
    obj = model_cls()
    types = _column_types(model_cls)
    for key, value in (payload or {}).items():
        col_type = types.get(key)
        if col_type is None:
            continue
        if value is None:
            decoded = None
        else:
            python_type = getattr(col_type, "python_type", None)
            try:
                if python_type is Decimal:
                    decoded = Decimal(str(value))
                elif python_type is dt.datetime:
                    decoded = _decode_value(value)
                    if not isinstance(decoded, dt.datetime):
                        decoded = dt.datetime.fromisoformat(str(value))
                elif python_type is dt.date:
                    decoded = _decode_value(value)
                    if isinstance(decoded, dt.datetime):
                        decoded = decoded.date()
                    elif not isinstance(decoded, dt.date):
                        decoded = dt.date.fromisoformat(str(value))
                else:
                    decoded = value
            except (TypeError, ValueError, ArithmeticError) as e:
                # A value that will not coerce is dropped rather than
                # stored half-converted; a wrong Decimal in a payslip is
                # worse than a None that a caller's own validation catches.
                logger.warning(f"Could not decode column '{key}' for {model_cls.__name__}: {e}")
                decoded = None
        setattr(obj, key, decoded)
    return obj


def current_tax_cache_version() -> int:
    """Read the version token once, BEFORE the resolution it will key.

    The caller must capture this before reading the database and pass the
    same value to both load_cached_tax_config and store_cached_tax_config.
    Reading it at store time instead opens a race: a payroll run reads the
    old rows, a Super Admin write commits and bumps the token, and the run
    then stores those old rows under the NEW token, where every later read
    finds them for the full TTL. Keyed under the pre-read token, an entry
    built from data that a concurrent write has since replaced is orphaned
    by that write's bump like any other.
    """
    return cache_get_version(TAX_CACHE_VERSION_KEY)


def _cache_key(
    country: str, state: Optional[str], tax_regime: Optional[str], as_of,
    version: Optional[int] = None,
) -> str:
    """Build the versioned cache key for one resolution.

    `as_of` is part of the key and is never collapsed or rounded. Pack
    selection and row-level effective dating both depend on the exact
    date, so a key without it would let a pack version that was only in
    force for part of a tax year answer a query for a date it never
    covered — a historical payroll would then recompute to a different
    number than the one originally generated for it. Isolating each date
    costs cache efficiency (one entry per distinct date) but that is the
    correct trade: historical reproducibility is a hard requirement, and
    the finite set of real payroll dates keeps the keyspace small.
    """
    date_part = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    if version is None:
        version = current_tax_cache_version()
    parts = [
        "zoiko:taxcfg",
        str(version),
        str(country or "").upper(),
        str(state or ""),
        str(tax_regime or ""),
        str(date_part),
    ]
    # "|" cannot appear in a country/state/regime value, so it is a safe
    # separator: without it, ("IN", "New") and ("IN-New", None) would
    # otherwise produce the identical key.
    return "|".join(parts)


def invalidate_tax_config_cache() -> int:
    """Invalidate every cached tax resolution. Call on any canonical write.

    Bumps the shared version token rather than deleting keys, so this is a
    single O(1) INCR no matter how many resolutions are cached, and it
    cannot miss an entry the way a hand-listed delete can.
    """
    return cache_bump_version(TAX_CACHE_VERSION_KEY)


def load_cached_tax_config(
    country: str, state: Optional[str], tax_regime: Optional[str], as_of,
    rate_model, slab_model, pack_model,
    version: Optional[int] = None,
) -> Optional[Tuple[List, List, Any]]:
    """Return (rates, slabs, pack) from cache, or None on any miss.

    A cached "no configuration" result (empty lists, pack=None) is
    distinguished from a miss by the presence of the ``"found"`` key, so
    a jurisdiction genuinely without a pack is cached as a negative result
    instead of re-querying the DB on every single payroll for that
    country. The version token is re-read here rather than trusted from
    the key, so an entry written under an older token is never returned
    even if it lingers in Redis until its TTL.

    Pass the `version` from current_tax_cache_version() so the token is
    read once per resolution rather than once here and again for the key.
    """
    if version is None:
        version = current_tax_cache_version()
    key = _cache_key(country, state, tax_regime, as_of, version=version)
    payload = cache_get(key)
    if not isinstance(payload, dict) or "found" not in payload:
        return None

    if str(payload.get("version")) != str(version):
        # Stale token (a bump landed between write and read, or the key
        # was hand-written). Treat as a miss rather than trusting it.
        return None

    try:
        if not payload["found"]:
            return [], [], None
        pack_payload = payload.get("pack")
        pack = _decode_row(pack_model, pack_payload) if pack_payload else None
        rates = [_decode_row(rate_model, r) for r in payload.get("rates", [])]
        slabs = [_decode_row(slab_model, s) for s in payload.get("slabs", [])]
    except Exception as e:
        # Any decode failure invalidates the whole entry. Returning a
        # partial set would be the worst outcome here: the caller cannot
        # tell a short list from a genuinely jurisdiction-limited one, and
        # would calculate a wrong number with no signal.
        logger.warning(f"Discarding unreadable tax cache entry for key '{key}': {e}")
        return None

    return rates, slabs, pack


def store_cached_tax_config(
    country: str, state: Optional[str], tax_regime: Optional[str], as_of,
    rates: List, slabs: List, pack,
    rate_model, slab_model, pack_model,
    version: Optional[int] = None,
) -> bool:
    """Persist one resolution. Returns False if it could not be cached.

    `version` must be the token captured BEFORE the rows were read — see
    current_tax_cache_version for the race this closes. Omitting it reads
    the token now, which is only safe when nothing can have changed
    between the read and this call (tests seeding a known state).
    """
    if version is None:
        version = current_tax_cache_version()
    key = _cache_key(country, state, tax_regime, as_of, version=version)
    payload: Dict[str, Any] = {
        "found": pack is not None,
        "version": version,
    }
    try:
        if pack is not None:
            payload["pack"] = _encode_row(pack)
            payload["rates"] = [_encode_row(r) for r in rates]
            payload["slabs"] = [_encode_row(s) for s in slabs]
    except Exception as e:
        logger.warning(f"Could not encode tax config for cache key '{key}': {e}")
        return False
    return cache_set(key, payload, ttl=TAX_CACHE_TTL_SECONDS)


def clear_tax_config_cache_state() -> None:
    """Reset the in-process Redis client singleton.

    Test-only helper: tests that swap REDIS_URL (or inject a fake client)
    need the memoized client rebuilt, since get_redis_client() caches its
    first successful construction for the process lifetime.
    """
    from app.core import cache as _cache_module

    _cache_module._redis_client = None
    _cache_module.reset_circuit_breaker()

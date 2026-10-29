"""
core/correlation.py
-------------------
One correlation id per request, carried everywhere (ZP-PRIV E01): logs, PDP
decision traces, audit and security-event rows, Celery tasks, emails and
notifications.

* The HTTP middleware (main.py) accepts a well-formed ``X-Correlation-ID``
  from the caller or generates one, stores it on ``request.state`` and in a
  context variable, and echoes it on the response.
* ``current()`` returns the id wherever code runs inside that request
  (including FastAPI's thread pool, which copies the context).
* Background work does not inherit a request context: callers pass the id
  explicitly (``task_headers()`` / ``bind(...)``) - Celery tasks receive it as
  a task header and re-bind it before running (core/celery_app.py).
* ``CorrelationLogFilter`` adds ``record.correlation_id`` to every log line.
"""

from __future__ import annotations

import contextvars
import ipaddress
import logging
import re
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

HEADER = "X-Correlation-ID"
_VALID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("zp_correlation_id", default=None)
# The calling client's address for this request (machine-client network checks).
client_ip: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("zp_client_ip", default=None)


def _trusted_proxy_networks() -> tuple:
    from app.config import settings

    networks = []
    for raw in (getattr(settings, "TRUSTED_PROXY_CIDRS", "") or "").split(","):
        raw = raw.strip()
        if raw:
            try:
                networks.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                logging.getLogger(__name__).warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry %r", raw)
    return tuple(networks)


def _parse_ip(value) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def _is_trusted(ip: Optional[str], networks: tuple) -> bool:
    if ip is None:
        return False
    address = ipaddress.ip_address(ip)
    return any(address in net for net in networks if net.version == address.version)


def extract_client_ip(request) -> Optional[str]:
    """The client address the request came from (audit rows, machine-client
    network alerts, session fingerprints).

    Forwarding headers are client-controlled, so they are honoured ONLY when
    the socket peer is a trusted proxy (settings.TRUSTED_PROXY_CIDRS; empty =
    trust none, i.e. the peer address). Behind a trusted proxy:
    CF-Connecting-IP / X-Real-IP are set by that proxy; X-Forwarded-For is
    walked right to left, skipping trusted hops, so an entry the client
    prepended itself is never taken as its address."""
    if request is None:
        return None
    client = getattr(request, "client", None)
    peer = _parse_ip(getattr(client, "host", None))
    networks = _trusted_proxy_networks()
    if peer is None or not _is_trusted(peer, networks):
        return peer if peer is not None else getattr(client, "host", None)
    headers = getattr(request, "headers", None) or {}
    for name in ("cf-connecting-ip", "x-real-ip"):
        ip = _parse_ip(headers.get(name) or "")
        if ip is not None:
            return ip
    hops = [h for h in (_parse_ip(part) for part in (headers.get("x-forwarded-for") or "").split(",")) if h]
    for hop in reversed(hops):
        if not _is_trusted(hop, networks):
            return hop
    return peer


def new_id() -> str:
    return uuid.uuid4().hex


def accept(candidate: Optional[str]) -> str:
    """A caller-supplied id only if it is well-formed; otherwise a new one
    (never trust arbitrary header content into logs and audit rows)."""
    if candidate and _VALID.match(candidate):
        return candidate
    return new_id()


def current() -> Optional[str]:
    return _current.get()


def set_current(value: Optional[str]):
    return _current.set(value)


@contextmanager
def bind(value: Optional[str]) -> Iterator[str]:
    """Run a block (a task, a sweep) under an explicit correlation id."""
    cid = value or new_id()
    token = _current.set(cid)
    try:
        yield cid
    finally:
        _current.reset(token)


def task_headers() -> dict:
    """Headers to pass when enqueueing a Celery task from a request."""
    return {"correlation_id": current() or new_id()}


class CorrelationLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = current() or "-"
        return True

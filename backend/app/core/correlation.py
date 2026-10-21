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

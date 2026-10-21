"""
core/redaction.py
-----------------
Central scrubbing of secrets and worker personal data from logs and Sentry
(ZP-PRIV D03/D04).

Two layers, applied everywhere a log line or error report can leave:

* key-based: any value stored under a sensitive key (passwords, tokens,
  salary/pay fields, bank and tax identifiers, dates of birth, addresses,
  emails, phone numbers) is replaced by ``[REDACTED]`` - in dicts, ``extra``
  attributes, Sentry request bodies, contexts and breadcrumbs;
* value-based: free text is scanned for JWTs / bearer tokens, IBANs, long
  account-like digit runs, national / tax identifier shapes and email
  addresses, which are masked.

``RedactingLogFilter`` is installed on every root handler at import of the
app (main.py) and runs before formatting, so it also covers exception text
and ``%``-style args. ``sentry_before_send`` / ``sentry_before_breadcrumb``
are passed to sentry_sdk.init.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|authorization|cookie|api[_-]?key|otp|mfa|recovery|"
    r"bank|iban|account[_-]?(no|num|number)|routing|ifsc|swift|bic|sort[_-]?code|"
    r"\bpan\b|pan_?number|uan|nino|\bni[_-]?number|ssn|sin\b|bsn|tfn|tax[_-]?(code|id|number)|national[_-]?id|"
    r"hkid|nric|iqama|aadhaar|passport|"
    r"salary|ctc|\bbasic\b|hra|wage|gross|net[_-]?pay|\bnet\b|earning|deduction|bonus|"
    r"date[_-]?of[_-]?birth|\bdob\b|birth|address|postcode|zip|email|phone|mobile)",
    re.IGNORECASE,
)
_VALUE_PATTERNS = (
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[JWT]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "[IBAN]"),
    (re.compile(r"\b[A-Z]{2}\d{6}[A-D]\b"), "[NINO]"),           # UK NI number
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),             # India PAN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),              # US SSN
    (re.compile(r"\b[A-Z]\d{6}\(?[0-9A]\)?"), "[HKID]"),           # HK identity card
    (re.compile(r"\b\d{9,}\b"), "[NUMBER]"),                     # account / BSN / long ids
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
)


def scrub_text(text: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY.search(key))


def scrub(value: Any, depth: int = 0) -> Any:
    """Recursively scrub a structure (dict / list / str)."""
    if depth > 12:
        return REDACTED
    if isinstance(value, dict):
        return {k: (REDACTED if is_sensitive_key(k) else scrub(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub(v, depth + 1) for v in value)
    if isinstance(value, str):
        return scrub_text(value)
    return value


# Leaving the platform (the Assist model provider, ZP-PRIV D07): person
# identities are masked too, not just secrets and pay values.
_IDENTITY_KEY = re.compile(
    r"(^|_)(name|full_?name|first_?name|last_?name|display_?name|employee_?name|employee_?code|"
    r"worker|initials)($|_)|^(name|fullName|firstName|lastName|displayName|employeeName|employeeCode)$",
    re.IGNORECASE,
)
PERSON = "[PERSON]"


def scrub_for_egress(value: Any, depth: int = 0) -> Any:
    """``scrub`` plus person identities, for data sent to an external processor."""
    if depth > 12:
        return REDACTED
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if is_sensitive_key(k):
                out[k] = REDACTED
            elif isinstance(k, str) and _IDENTITY_KEY.search(k) and isinstance(v, (str, int)) and v != "":
                out[k] = PERSON
            else:
                out[k] = scrub_for_egress(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_for_egress(v, depth + 1) for v in value)
    if isinstance(value, str):
        return scrub_text(value)
    return value


_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "correlation_id"}


class RedactingLogFilter(logging.Filter):
    """Scrub a record in place before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Scrub the template and each argument in place, keeping the args
            # shape: some formatters (uvicorn's access log) unpack record.args.
            if isinstance(record.args, tuple) and record.args:
                record.msg = scrub_text(record.msg) if isinstance(record.msg, str) else record.msg
                record.args = tuple(scrub_text(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict) and record.args:
                record.args = {k: (REDACTED if is_sensitive_key(k) else scrub(v)) for k, v in record.args.items()}
            else:
                record.msg = scrub_text(record.getMessage())
                record.args = ()
            if record.exc_info and record.exc_info[1] is not None:
                record.exc_text = scrub_text(logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
            for key, value in list(vars(record).items()):
                if key in _STANDARD_ATTRS:
                    continue
                setattr(record, key, REDACTED if is_sensitive_key(key) else scrub(value))
        except Exception:  # noqa: BLE001 - never lose the log line itself
            record.msg = "[log message withheld: redaction failed]"
            record.args = ()
        return True


def install_log_filters() -> None:
    """Attach the redaction + correlation filters to every root handler."""
    from app.core.correlation import CorrelationLogFilter

    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.task"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingLogFilter) for f in handler.filters):
                handler.addFilter(CorrelationLogFilter())
                handler.addFilter(RedactingLogFilter())


def sentry_before_send(event: dict, hint: dict | None = None) -> dict:
    """Sentry hook: scrub request bodies, headers, cookies, extra, contexts,
    exception messages and breadcrumbs."""
    request = event.get("request") or {}
    for part in ("data", "cookies", "query_string", "env"):
        if part in request:
            request[part] = scrub(request[part]) if part != "cookies" else REDACTED
    if "headers" in request:
        request["headers"] = {k: (REDACTED if is_sensitive_key(k) else scrub_text(v))
                              for k, v in (request["headers"] or {}).items()}
    for part in ("extra", "contexts", "tags"):
        if part in event:
            event[part] = scrub(event[part])
    if "user" in event:
        event["user"] = {"id": (event["user"] or {}).get("id")}
    for exc in (event.get("exception") or {}).get("values", []) or []:
        exc["value"] = scrub_text(exc.get("value"))
        for frame in (exc.get("stacktrace") or {}).get("frames", []) or []:
            if "vars" in frame:
                frame["vars"] = scrub(frame["vars"])
    if "logentry" in event:
        event["logentry"] = scrub(event["logentry"])
    if "message" in event:
        event["message"] = scrub_text(event["message"])
    crumbs = event.get("breadcrumbs") or {}
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for crumb in values or []:
        sentry_before_breadcrumb(crumb)
    return event


def sentry_before_breadcrumb(crumb: dict, hint: dict | None = None) -> dict:
    if "message" in crumb:
        crumb["message"] = scrub_text(crumb["message"])
    if "data" in crumb:
        crumb["data"] = scrub(crumb["data"])
    return crumb

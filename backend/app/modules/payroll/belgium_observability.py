"""Belgium (ZP-BE-ENG-001) Block I3: structured operational events.

The platform has no metrics library, so Belgian operations are observable through ONE structured log line per
event on the ``zoiko.belgium`` logger (the request correlation id is added by core/correlation.py's filter).
A log pipeline counts them by ``event`` and ``code``, e.g.:

  be.calculation.blocked    one employee's calculation refused (code = the block code)
  be.run.approval_refused   a run refused at approval (code = BE_RUN_BLOCKED; count; one line per code)
  be.filing.state           a filing reached a state (form, state)
  be.filing.refused         a filing action refused (code)
  be.payslip.pdf_refused    a Belgian payslip PDF refused (code)
  be.identifier.reveal      a NISS / BIS reveal step (state = REQUESTED / APPROVED / USED / REFUSED)

Privacy: only the fields in ``ALLOWED`` are accepted — codes, internal ids, form / state names and counts. A NISS,
a name, an IBAN or an amount can never be logged: any other field raises, and every value is checked (ids are
integers, text fields are code-shaped). Logging never breaks payroll: a malformed event is dropped with a
warning naming only the offending field.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from typing import Optional

logger = logging.getLogger("zoiko.belgium")

EVENTS = ("be.calculation.blocked", "be.run.approval_refused", "be.filing.state", "be.filing.refused",
          "be.payslip.pdf_refused", "be.identifier.reveal")
_IDS = ("organization_id", "run_id", "employee_id", "filing_id", "vault_id", "payslip_id")
_TEXT = {"code": re.compile(r"^BE_[A-Z0-9_]{2,60}(:[a-z0-9_.\-]{1,60})?$"),
         "form": re.compile(r"^[A-Z0-9_]{2,20}$"), "state": re.compile(r"^[A-Z_]{2,30}$")}
ALLOWED = frozenset(("event", "count", *_IDS, *_TEXT))

_run_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("zp_be_run_id", default=None)


def be_bind_run(run_id) -> None:
    """Remember the run being calculated, so engine-level events carry its id."""
    try:
        _run_id.set(int(run_id) if run_id is not None else None)
    except (TypeError, ValueError):
        _run_id.set(None)


def be_current_run() -> Optional[int]:
    return _run_id.get()


def be_event_fields(event: str, **fields) -> dict:
    """The validated record (raises ValueError naming the offending field only)."""
    if event not in EVENTS:
        raise ValueError("event")
    out = {"event": event}
    for name, value in fields.items():
        if name not in ALLOWED:
            raise ValueError(name)
        if value is None:
            continue
        if name in _IDS or name == "count":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(name)
        elif not isinstance(value, str) or not _TEXT[name].match(value):
            raise ValueError(name)
        out[name] = value
    if "run_id" not in out and _run_id.get() is not None and event == "be.calculation.blocked":
        out["run_id"] = _run_id.get()
    return out


def be_log_event(event: str, **fields) -> None:
    try:
        record = be_event_fields(event, **fields)
    except ValueError as bad:
        logger.warning("be.event dropped: field %s not allowed / not code-shaped", bad)
        return
    logger.info("be.event %s", json.dumps(record, sort_keys=True), extra={"be_event": record})


_FILING_LISTENER = []


def be_register_filing_events() -> None:
    """Every PayrollBeFiling status change -> one be.filing.state event (form + state + ids), wherever it is made."""
    if _FILING_LISTENER:
        return
    from sqlalchemy import event

    from app.modules.payroll.models import PayrollBeFiling

    def _on_status(target, value, oldvalue, _initiator):
        if value != oldvalue and isinstance(value, str):
            be_log_event("be.filing.state", state=value, form=getattr(target, "form_code", None),
                         filing_id=getattr(target, "id", None), organization_id=getattr(target, "organization_id", None))

    event.listen(PayrollBeFiling.status, "set", _on_status)
    _FILING_LISTENER.append(_on_status)

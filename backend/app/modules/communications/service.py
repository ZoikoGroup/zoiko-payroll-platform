"""
modules/communications/service.py
---------------------------------
The single dispatch path for every outbound email on the platform.

    dispatch_email(...)  — audit-first, idempotent, retrying send. Runs NOW,
                           in the caller's thread.
    queue_email(...)     — same arguments; schedules dispatch_email on the
                           current request's FastAPI BackgroundTasks so the
                           HTTP response never waits on SMTP. Falls back to
                           dispatch_email inline when there is no request
                           (scripts, schedulers, direct service calls/tests).

Contract (generalised from auth's _dispatch_email_guarded, §04):
  1. INSERT a communication_events row (outcome="pending") carrying the
     idempotency_key BEFORE any SMTP call. The UNIQUE constraint is the
     double-send guard: a duplicate key records its own skipped_duplicate
     row and never reaches SMTP.
  2. Call the send function. Transient SMTP failures (connection refused /
     reset, timeouts, 4xx replies) are retried in-process with a short
     backoff; permanent ones (5xx, auth failure, bad recipient) are not.
  3. UPDATE the row's outcome / provider_response / attempt_count from the
     real result.

Known, accepted limits (deliberate scope — see the task notes):
  - BackgroundTasks is in-process: a worker restart between response and
    send loses the send. The row stays outcome="pending", which is the
    queryable signal for that case. A broker-backed durable queue is
    separate work.
  - Retry happens inside the one background task; there is no scheduled
    re-drive or dead-letter UI. Failed rows (outcome="failed",
    attempt_count, provider_response) are the manual re-drive input.
  - If the audit INSERT itself errors for a reason other than a duplicate
    (e.g. database unavailable), the send still goes out (fail-open, logged
    at error level): a notification outage is worse than a missing audit
    row, and idempotency is only lost for that one degraded send.
"""

import hashlib
import inspect
import json
import logging
import smtplib
import socket
import ssl
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.communications.models import CommunicationEvent

logger = logging.getLogger("zoiko_payroll.communications")

# Same material-version segment auth's keys have always carried (auth
# TOKEN_MATERIAL_VERSION) — one key format platform-wide, not two.
KEY_MATERIAL_VERSION = "v2"
MAX_KEY_LENGTH = 255

# Events that can legitimately recur on the same object (suspend → reactivate
# → suspend, repeated edits, toggles) are keyed on object + change hash + this
# window, so duplicate/concurrent requests collapse while a genuine repeat of
# the same change later still sends.
REPEATABLE_WINDOW_MINUTES = 10

MAX_ATTEMPTS = 3
# Sleep before attempt 2 and attempt 3 respectively.
RETRY_BACKOFF_SECONDS = (2, 5)

OUTCOME_PENDING = "pending"
OUTCOME_SENT = "sent"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED_DUPLICATE = "skipped_duplicate"

# Patched in tests so retry backoff doesn't actually sleep.
_sleep = time.sleep


# ── Idempotency keys ────────────────────────────────────────────────────────

def _fingerprint(change: Any) -> str:
    payload = json.dumps(change, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def idempotency_key(
    organization_id,
    event_type: str,
    email: str,
    template_id: Optional[str],
    related_object_id: Any = None,
    *,
    change: Any = None,
    window_minutes: Optional[int] = None,
    now: Optional[datetime] = None,
) -> str:
    """§04 key: tenant | event | recipient | template | material version —
    byte-identical to auth's historical _idempotency_key for the first five
    segments — optionally extended with:
      obj:<related_object_id>  what the event is about (run, employee, ...)
      chg:<hash>               fingerprint of the change payload
      win:<bucket>             time bucket, for repeatable events
    """
    parts = [
        str(organization_id or "platform"),
        event_type,
        (email or "").lower(),
        template_id or "-",
        KEY_MATERIAL_VERSION,
    ]
    if related_object_id is not None:
        parts.append(f"obj:{related_object_id}")
    if change is not None:
        parts.append(f"chg:{_fingerprint(change)}")
    if window_minutes:
        moment = now or datetime.utcnow()
        parts.append(f"win:{int(moment.timestamp() // (window_minutes * 60))}")
    key = "|".join(parts)
    if len(key) > MAX_KEY_LENGTH:
        key = f"{key[:200]}#{hashlib.sha256(key.encode('utf-8')).hexdigest()[:40]}"
    return key


def repeatable_idempotency_key(
    organization_id,
    event_type: str,
    email: str,
    template_id: Optional[str],
    related_object_id: Any,
    change: Any,
    now: Optional[datetime] = None,
) -> str:
    """Key for events that may legitimately recur on the same object: object
    + change fingerprint + REPEATABLE_WINDOW_MINUTES bucket."""
    return idempotency_key(
        organization_id, event_type, email, template_id, related_object_id,
        change=change, window_minutes=REPEATABLE_WINDOW_MINUTES, now=now,
    )


# ── Failure classification ──────────────────────────────────────────────────

def is_transient_send_error(exc: BaseException) -> bool:
    """True for failures worth retrying, based on what email_service's
    smtplib.SMTP / SMTP_SSL usage can actually raise. Order matters:
    smtplib.SMTPException and ssl.SSLError are both OSError subclasses, so
    they must be classified before the generic network-error branch."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return False  # wrong credentials on the configured account — retrying won't help
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _msg in (exc.recipients or {}).values()]
        return bool(codes) and all(400 <= int(code) < 500 for code in codes)
    if isinstance(exc, smtplib.SMTPResponseException):
        # Covers SMTPSenderRefused / SMTPDataError / SMTPConnectError /
        # SMTPHeloError: 4xx is a temporary condition, 5xx is permanent.
        return 400 <= int(exc.smtp_code) < 500
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return True
    if isinstance(exc, smtplib.SMTPException):
        return False  # SMTPNotSupportedError and other protocol/config errors
    if isinstance(exc, ssl.SSLError):
        return False  # TLS misconfiguration / certificate failure
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, socket.gaierror)):
        return True
    if isinstance(exc, OSError):
        return True  # remaining socket-level errors (network unreachable, ...)
    return False  # coding/template errors — never retried


# ── Audit rows ──────────────────────────────────────────────────────────────

_DUPLICATE = object()


def _claim_row(session: Session, **fields):
    """INSERT the pending row — the dedup gate. Returns the new row id,
    _DUPLICATE when the key already exists, or None when the audit table
    could not be written at all (fail-open; logged)."""
    key = fields["idempotency_key"]
    try:
        if session.query(CommunicationEvent.id).filter(CommunicationEvent.idempotency_key == key).first():
            return _DUPLICATE
        row = CommunicationEvent(outcome=OUTCOME_PENDING, attempt_count=0, **fields)
        session.add(row)
        session.flush()
        row_id = row.id
        session.commit()
        return row_id
    except IntegrityError:
        # A concurrent request won the race for this key.
        session.rollback()
        return _DUPLICATE
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception(
            "[communications] audit INSERT failed for event=%s key=%s; sending without an audit row",
            fields.get("event_type"), key,
        )
        return None


def _record_duplicate(session: Session, **fields) -> None:
    """Persist a suppressed attempt as its own row. The original keeps its
    key; the duplicate gets a suffixed one so it never collides."""
    fields = dict(fields)
    fields["idempotency_key"] = f"{fields['idempotency_key'][:230]}#dup:{uuid.uuid4().hex[:8]}"
    try:
        session.add(CommunicationEvent(outcome=OUTCOME_SKIPPED_DUPLICATE, attempt_count=0, **fields))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("[communications] could not record skipped_duplicate for event=%s", fields.get("event_type"))


def _finalize_row(session: Session, row_id: int, outcome: str, provider_response: Optional[str], attempts: int) -> None:
    try:
        session.query(CommunicationEvent).filter(CommunicationEvent.id == row_id).update(
            {"outcome": outcome, "provider_response": provider_response, "attempt_count": attempts},
            synchronize_session=False,
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("[communications] failed to persist outcome=%s for communication_event id=%s", outcome, row_id)


def _accepts_db(fn: Callable) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "db" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def record_skipped_duplicate(
    db: Optional[Session],
    *,
    module: str,
    event_type: str,
    template_id: Optional[str],
    recipient_email: str,
    idempotency_key: str,
    recipient_user_id=None,
    organization_id=None,
    actor_user_id=None,
) -> None:
    """Record a duplicate that a caller-side gate (e.g. auth_email_events)
    already suppressed, so communication_events shows it too."""
    own_session = db is None
    if own_session:
        from app.database import SessionLocal
        db = SessionLocal()
    try:
        _record_duplicate(
            db, module=module, event_type=event_type, template_id=template_id,
            recipient_email=recipient_email, idempotency_key=idempotency_key,
            recipient_user_id=recipient_user_id, organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
    finally:
        if own_session:
            db.close()


def snapshot(obj, *fields: str):
    """Plain-value copy of an ORM object's fields, safe to hand to a send
    that runs after the request session is closed."""
    from types import SimpleNamespace

    if obj is None:
        return None
    return SimpleNamespace(**{f: getattr(obj, f, None) for f in fields})


# ── Dispatch ────────────────────────────────────────────────────────────────

def dispatch_email(
    module: str,
    event_type: str,
    template_id: Optional[str],
    recipient_email: str,
    idempotency_key: str,
    send_fn: Callable[..., bool],
    *send_fn_args,
    organization_id=None,
    actor_user_id=None,
    recipient_user_id=None,
    send_kwargs: Optional[dict] = None,
    db: Optional[Session] = None,
) -> bool:
    """Audit-first, idempotent, retrying send. Returns True only when the
    email was actually sent; False for a duplicate (skipped) or a failure.

    `db` is used for the audit rows and injected as send_fn's `db=` kwarg
    (when send_fn takes one); when omitted a private session is opened."""
    if not recipient_email:
        return False
    from app.services import email_service

    own_session = db is None
    if own_session:
        from app.database import SessionLocal
        db = SessionLocal()
    audit_fields = dict(
        module=module,
        event_type=event_type,
        template_id=template_id,
        recipient_email=recipient_email,
        recipient_user_id=recipient_user_id,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )
    try:
        row_id = _claim_row(db, **audit_fields)
        if row_id is _DUPLICATE:
            _record_duplicate(db, **audit_fields)
            logger.info(
                "[communications] module=%s event=%s template_id=%s recipient=%s outcome=skipped_duplicate",
                module, event_type, template_id, recipient_email,
            )
            return False

        kwargs = dict(send_kwargs or {})
        if _accepts_db(send_fn):
            kwargs["db"] = db

        attempts = 0
        provider_response = None
        while True:
            attempts += 1
            try:
                with email_service.propagate_delivery_errors():
                    ok = bool(send_fn(*send_fn_args, **kwargs))
            except Exception as exc:  # noqa: BLE001
                provider_response = f"{type(exc).__name__}: {exc}"
                if is_transient_send_error(exc) and attempts < MAX_ATTEMPTS:
                    delay = RETRY_BACKOFF_SECONDS[min(attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                    logger.warning(
                        "[communications] transient failure module=%s event=%s recipient=%s attempt=%d: %s; retrying in %ss",
                        module, event_type, recipient_email, attempts, provider_response, delay,
                    )
                    _sleep(delay)
                    continue
                outcome = OUTCOME_FAILED
                break
            if ok:
                outcome, provider_response = OUTCOME_SENT, None
            else:
                outcome = OUTCOME_FAILED
                provider_response = provider_response or "send function reported failure (returned False)"
            break

        if row_id is not None:
            _finalize_row(db, row_id, outcome, provider_response, attempts)
        log = logger.info if outcome == OUTCOME_SENT else logger.error
        log(
            "[communications] module=%s event=%s template_id=%s recipient=%s outcome=%s attempts=%d%s",
            module, event_type, template_id, recipient_email, outcome, attempts,
            f" error={provider_response}" if provider_response else "",
        )
        return outcome == OUTCOME_SENT
    finally:
        if own_session:
            db.close()


# ── Off-request scheduling (BackgroundTasks) ────────────────────────────────

_request_background_tasks: ContextVar[Optional[BackgroundTasks]] = ContextVar(
    "communications_request_background_tasks", default=None,
)


async def bind_request_background_tasks(background_tasks: BackgroundTasks):
    """App-wide FastAPI dependency (main.py): exposes the current request's
    BackgroundTasks to queue_email, so a send deep inside a service function
    is deferred until after the response without threading the object
    through every service signature. Must be `async` so the ContextVar is
    set in the request task's own context, which the threadpool that runs
    sync endpoints copies."""
    token = _request_background_tasks.set(background_tasks)
    try:
        yield
    finally:
        try:
            _request_background_tasks.reset(token)
        except ValueError:
            _request_background_tasks.set(None)


@contextmanager
def dispatch_inline():
    """Force queue_email to dispatch inline for the enclosed block. For code
    that is itself already running as a background task (e.g. payroll's
    run-notification pass), where re-queueing would only add latency."""
    token = _request_background_tasks.set(None)
    try:
        yield
    finally:
        _request_background_tasks.reset(token)


def _dispatch_in_background(bind, args: tuple, kwargs: dict) -> None:
    """BackgroundTasks entry point. Runs after the response is sent, when the
    request's session is already closed — so it opens its own session on the
    same engine."""
    token = _request_background_tasks.set(None)  # never re-queue from inside a background task
    if bind is not None:
        session = Session(bind=bind)
    else:
        from app.database import SessionLocal
        session = SessionLocal()
    try:
        dispatch_email(*args, db=session, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("[communications] background dispatch crashed for event=%s", args[1] if len(args) > 1 else "?")
    finally:
        session.close()
        _request_background_tasks.reset(token)


def queue_email(
    module: str,
    event_type: str,
    template_id: Optional[str],
    recipient_email: str,
    idempotency_key: str,
    send_fn: Callable[..., bool],
    *send_fn_args,
    organization_id=None,
    actor_user_id=None,
    recipient_user_id=None,
    send_kwargs: Optional[dict] = None,
    db: Optional[Session] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Optional[bool]:
    """Schedule dispatch_email off the request/response cycle. Returns None
    when queued (the outcome lands in communication_events), or
    dispatch_email's bool when run inline because there is no request.

    Every argument must be a plain value (str/int/list of tuples ...), never
    a live ORM object: the request session is closed before the task runs."""
    if not recipient_email:
        return False
    tasks = background_tasks if background_tasks is not None else _request_background_tasks.get()
    args = (module, event_type, template_id, recipient_email, idempotency_key, send_fn, *send_fn_args)
    kwargs = dict(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        recipient_user_id=recipient_user_id,
        send_kwargs=send_kwargs,
    )
    if tasks is None:
        return dispatch_email(*args, db=db, **kwargs)
    bind = None
    if db is not None:
        try:
            bind = db.get_bind()
        except Exception:  # noqa: BLE001
            bind = None
    tasks.add_task(_dispatch_in_background, bind, args, kwargs)
    return None

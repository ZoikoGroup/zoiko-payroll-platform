"""
payroll/netherlands_http.py
----------------------------
Write-request plumbing for Netherlands (NL) routes only.

Every NL write carries two headers (same pattern as CH):

* Idempotency-Key (required) — a retry with the same key and the same request
  replays the stored response and writes nothing; the same key with a
  different request is refused (409). Keys are scoped per organization
  ("org:<id>") or to the platform catalog ("platform").
* X-Correlation-ID (optional) — echoed back, generated when absent, and
  written into the audit entry so one request can be traced end to end.

`nl_write` runs the service call, records the idempotency entry and commits
both in ONE transaction: a crash can never leave a write without its record
(a retry would then write twice) or a record without its write.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ZoikoException
from app.modules.payroll.models import PayrollNlIdempotencyRecord

MAX_KEY_LENGTH = 100
MAX_CORRELATION_LENGTH = 64


@dataclass(frozen=True)
class NlWriteContext:
    idempotency_key: str
    correlation_id: str


def nl_write_headers(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
) -> NlWriteContext:
    """FastAPI dependency for every NL write route."""
    key = (idempotency_key or "").strip()
    if not key:
        raise BadRequestException("the Idempotency-Key header is required for this write")
    if len(key) > MAX_KEY_LENGTH:
        raise BadRequestException(f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters")
    cid = (correlation_id or "").strip() or uuid.uuid4().hex
    if len(cid) > MAX_CORRELATION_LENGTH:
        raise BadRequestException(f"X-Correlation-ID must be at most {MAX_CORRELATION_LENGTH} characters")
    return NlWriteContext(idempotency_key=key, correlation_id=cid)


def scope_key(organization_id: Optional[int]) -> str:
    return f"org:{organization_id}" if organization_id is not None else "platform"


class IdempotencyConflict(ZoikoException):
    def __init__(self, message: str):
        super().__init__(status_code=409, error_code="IDEMPOTENCY_KEY_REUSED", message=message)


def _request_sha(operation: str, request: dict) -> str:
    body = json.dumps({"operation": operation, "request": jsonable_encoder(request)}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _find(db: Session, scope: str, key: str) -> Optional[PayrollNlIdempotencyRecord]:
    return (db.query(PayrollNlIdempotencyRecord)
            .filter(PayrollNlIdempotencyRecord.idempotency_key == key).first())


def _respond(body, ctx: NlWriteContext, replayed: bool) -> JSONResponse:
    return JSONResponse(content=body, headers={
        "Idempotency-Key": ctx.idempotency_key,
        "X-Correlation-ID": ctx.correlation_id,
        "Idempotent-Replayed": "true" if replayed else "false",
    })


def _replay_or_conflict(record: PayrollNlIdempotencyRecord, sha: str, ctx: NlWriteContext) -> JSONResponse:
    if record.request_hash != sha:
        raise IdempotencyConflict(f"Idempotency-Key {ctx.idempotency_key!r} was already used for a different "
                                  f"request (hash mismatch); use a new key")
    return _respond(record.response_body, ctx, replayed=True)


def nl_write(
    db: Session,
    ctx: NlWriteContext,
    *,
    organization_id: Optional[int],
    operation: str,
    actor_id: Optional[int],
    request: dict,
    perform: Callable[[], dict],
) -> JSONResponse:
    """Run `perform` once per (scope, Idempotency-Key). `operation` names the
    route AND its target (e.g. "employer_profile.create:42") so one key can
    never be replayed against a different resource."""
    scope = scope_key(organization_id)
    sha = _request_sha(operation, request)

    existing = _find(db, scope, ctx.idempotency_key)
    if existing:
        return _replay_or_conflict(existing, sha, ctx)

    # Execute the service call
    response = perform()

    # Record idempotency entry
    record = PayrollNlIdempotencyRecord(
        idempotency_key=ctx.idempotency_key,
        request_hash=sha,
        response_status=200,
        response_body=response,
        created_by=actor_id,
    )
    db.add(record)
    db.flush()

    return _respond(response, ctx, replayed=False)
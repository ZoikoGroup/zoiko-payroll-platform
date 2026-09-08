"""
core/exceptions.py
------------------
Custom error classes and handlers for the entire application.

Why custom exceptions?
  FastAPI by default returns technical errors. We want clean, consistent
  JSON error responses that the frontend can easily understand.

Standard error response format we use everywhere:
  {
    "success": false,
    "error": "NOT_FOUND",
    "message": "Employee with id 5 not found"
  }
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def _cors_headers(request: Request) -> dict:
    """Return CORS headers that mirror the ForceCORSMiddleware logic."""
    origin = request.headers.get("origin", "")
    return {
        "Access-Control-Allow-Origin": origin if origin else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Expose-Headers": "*",
    }


# ── Custom Exception Classes ──────────────────────────────────────────────────

class ZoikoException(HTTPException):
    """Base exception for all Zoiko errors. All custom errors inherit from this."""
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(status_code=status_code, detail=message)
        self.error_code = error_code
        self.message = message


class NotFoundException(ZoikoException):
    """Use when a requested resource doesn't exist (404)."""
    def __init__(self, resource: str, identifier=None):
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} with id '{identifier}' not found"
        super().__init__(status_code=404, error_code="NOT_FOUND", message=msg)


class AlreadyExistsException(ZoikoException):
    """Use when trying to create something that already exists (409)."""
    def __init__(self, resource: str, field: str = None):
        msg = f"{resource} already exists"
        if field:
            msg = f"{resource} with this {field} already exists"
        super().__init__(status_code=409, error_code="ALREADY_EXISTS", message=msg)


class UnauthorizedException(ZoikoException):
    """Use when user is not logged in or token is invalid (401)."""
    def __init__(self, message: str = "Authentication required. Please log in."):
        super().__init__(status_code=401, error_code="UNAUTHORIZED", message=message)


class ForbiddenException(ZoikoException):
    """Use when user is logged in but doesn't have permission (403)."""
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(status_code=403, error_code="FORBIDDEN", message=message)


class BadRequestException(ZoikoException):
    """Use when the request data is invalid or makes no logical sense (400)."""
    def __init__(self, message: str):
        super().__init__(status_code=400, error_code="BAD_REQUEST", message=message)


class GermanyCalculationBlockedException(ZoikoException):
    """Use when a Germany payroll calculation cannot safely produce a
    compliant result (400) — e.g. no PUBLISHED BMF PAP asset, no effective
    EmployeeStatutoryProfile, no resolvable Health Fund / Contribution
    Ceiling / PV Configuration for the payroll date. `error_code` is one
    of engine.germany_pap.core's GermanyCalculationError subclass
    codes (e.g. "GERMANY_PAP_NOT_AVAILABLE"), not the generic
    "BAD_REQUEST", so API/UI consumers can distinguish the specific
    statutory blocker. `trace` is the (already-redacted)
    GermanyCalculationTrace.to_dict() showing exactly what DID resolve
    before the block — real diagnostic value, not just a bare failure."""
    def __init__(self, error_code: str, message: str, trace: dict | None = None):
        super().__init__(status_code=400, error_code=error_code, message=message)
        self.trace = trace or {}


class GermanyPapGateBlockedException(ZoikoException):
    """Phase 8G-1 — raised when an activation attempt against a
    GermanyPapRelease fails the compound production-release gate (see
    engine.germany_pap.production_gate). `failed_gates` lists exactly
    which named dimensions were not satisfied, surfaced via the same
    `trace` mechanism GermanyCalculationBlockedException already uses
    (zoiko_exception_handler serializes any `trace` attribute) — no new
    response-serialization path was added for this."""
    def __init__(self, failed_gates: list):
        super().__init__(
            status_code=400,
            error_code="GERMANY_PAP_PRODUCTION_GATE_BLOCKED",
            message="This PAP release does not satisfy every required production gate.",
        )
        self.trace = {"failedGates": list(failed_gates)}


# ── Global Exception Handlers ─────────────────────────────────────────────────
# These are registered in main.py so every error returns our clean JSON format.

async def zoiko_exception_handler(request: Request, exc: ZoikoException):
    """Handles all our custom ZoikoException errors."""
    content = {
        "success": False,
        "error": exc.error_code,
        "message": exc.message,
        "detail": exc.message,
    }
    trace = getattr(exc, "trace", None)
    if trace:
        content["trace"] = trace
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=_cors_headers(request),
    )


async def generic_exception_handler(request: Request, exc: Exception):
    """Catches any unexpected server error and returns a clean message."""
    import logging
    logging.getLogger("zoiko").error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "INTERNAL_SERVER_ERROR",
            "message": "Something went wrong on the server. Please try again later.",
        },
        headers=_cors_headers(request),
    )


async def database_schema_error_handler(request: Request, exc: Exception):
    """Registered for sqlalchemy.exc.ProgrammingError specifically —
    FastAPI dispatches to the most specific matching handler class, so
    this runs INSTEAD OF generic_exception_handler only for this one
    exception type, never masking any other exception.

    Narrowly inspects the underlying DBAPI error (`exc.orig`): only when
    it is genuinely psycopg.errors.UndefinedTable/UndefinedColumn — i.e.
    the database this environment is connected to is missing a
    table/column a migration already in the repository would create — do
    we return the clean, distinguishable 503 SCHEMA_UNAVAILABLE contract
    (found during the Super Admin stabilization audit: several Germany
    registry endpoints were surfacing this as a bare, unhandled 500).
    Every other ProgrammingError (a genuine SQL/query defect) still logs
    and returns the normal 500 — this handler never widens into a
    broad `except Exception` and never swallows a real bug."""
    import logging

    from psycopg.errors import UndefinedTable, UndefinedColumn

    orig = getattr(exc, "orig", None)
    if not isinstance(orig, (UndefinedTable, UndefinedColumn)):
        return await generic_exception_handler(request, exc)

    logging.getLogger("zoiko").error(
        "Schema unavailable on %s %s: %s", request.method, request.url.path, orig,
    )
    friendly_message = (
        "This feature requires a database migration that has not been applied to this "
        "environment yet. Please contact an administrator to run the pending deployment."
    )
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": "SCHEMA_UNAVAILABLE",
            # `detail` intentionally mirrors `message` (matching every other
            # handler here) rather than the raw DB error text — the frontend's
            # api.js picks `detail` first when present, and raw table/column
            # names are a server-side diagnostic (already logged above), not
            # something to surface to an authenticated client.
            "message": friendly_message,
            "detail": friendly_message,
        },
        headers=_cors_headers(request),
    )

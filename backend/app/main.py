"""
main.py
-------
Entry point of the standalone Zoiko Payroll Platform backend.

Serves ONLY this platform's own API under /api and its own auth surface.
Nothing from the old ZoikoOne codebase is imported at runtime.

Router mounting:
  - /api/auth            → auth + user management
  - /api/organizations   → org profile (own org) + super-admin org CRUD
  - /api/payroll/...     → the extracted Payroll module (its own prefix /payroll)
  - /api/employee        → employee self-service (ESS)
  - /api/super-admin     → platform admin
  - /api/assist          → Zoiko Payroll Assist (its own prefix /assist)
"""

import logging
import re
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import ProgrammingError

from app.config import settings
from app.core.exceptions import (
    ZoikoException,
    zoiko_exception_handler,
    generic_exception_handler,
    database_schema_error_handler,
)
from app.core.rate_limiter import limiter
from app.database import initialize_database
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

logger = logging.getLogger("zoiko_payroll")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(message)s")

# ZP-PRIV D03/D04: every log line carries the request's correlation id and is
# scrubbed of secrets and worker personal data before any handler sees it.
from app.core.redaction import install_log_filters  # noqa: E402

install_log_filters()

# ── Error tracking (Sentry) ──────────────────────────────────────────────
# Inert until SENTRY_DSN is set (empty by default -- see config.py). No
# behavior change for any environment that hasn't opted in.
if settings.SENTRY_DSN:
    import sentry_sdk

    from app.core.redaction import sentry_before_breadcrumb, sentry_before_send

    sentry_sdk.init(dsn=settings.SENTRY_DSN, send_default_pii=False, max_request_body_size="never",
                    include_local_variables=False,
                    before_send=sentry_before_send, before_breadcrumb=sentry_before_breadcrumb)

# ── Access-log redaction for security tokens in query strings ───────────────

_ACCESS_LOG_REDACT_RE = re.compile(r"(?i)([?&](?:token|code)=)[^&\s\"']+")


class _RedactSensitiveQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _ACCESS_LOG_REDACT_RE.sub(r"\1[REDACTED]", record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


@asynccontextmanager
def _enforce_nonprod_data_guard() -> None:
    """ZP-PRIV D09: production stamps its data origin; a named non-production
    environment refuses to start on production-origin data that was not
    de-identified (core/nonprod_guard.py)."""
    from app.core import nonprod_guard
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = nonprod_guard.enforce(db)
        logger.info("[startup] non-production data guard: %s", result)
    finally:
        db.close()


async def lifespan(app: FastAPI):
    initialize_database()
    install_log_filters()  # uvicorn's own handlers exist by now
    from app.database import check_row_level_security

    check_row_level_security()
    _enforce_nonprod_data_guard()
    from app.modules.assisted_access.models import ensure_tables
    from app.modules.assist.scheduler import start_assist_scheduler, stop_assist_scheduler
    from app.modules.auth.scheduler import start_token_cleanup_scheduler, stop_token_cleanup_scheduler
    from app.modules.billing.scheduler import (
        start_trial_scheduler, stop_trial_scheduler,
        start_dunning_scheduler, stop_dunning_scheduler,
        start_bwm_aggregation_scheduler, stop_bwm_aggregation_scheduler,
    )
    from app.modules.support_access.scheduler import (
        retire_legacy_assisted_access, start_support_access_scheduler, stop_support_access_scheduler,
    )

    start_assist_scheduler(run_now=True)
    start_trial_scheduler(run_now=True)
    start_dunning_scheduler(run_now=True)
    start_bwm_aggregation_scheduler(run_now=True)
    start_token_cleanup_scheduler(run_now=True)
    ensure_tables()
    # ZP-PRIV Part D supersedes Assisted Access: close any legacy session
    # still open (its tokens are refused regardless), then run the JIT
    # Support Access minute sweep.
    retire_legacy_assisted_access()
    start_support_access_scheduler(run_now=True)

    from app.modules.billing.router import _missing_checkout_config
    missing_checkout_config = _missing_checkout_config()
    if missing_checkout_config:
        logger.warning(
            "[startup] Checkout is not fully configured — missing: %s. "
            "POST /billing/checkout will fail until these are set.",
            ", ".join(missing_checkout_config),
        )

    logger.info("Zoiko Payroll Platform backend is ready.")
    yield
    stop_token_cleanup_scheduler()
    stop_assist_scheduler()
    stop_trial_scheduler()
    stop_dunning_scheduler()
    stop_bwm_aggregation_scheduler()
    stop_support_access_scheduler()


from app.modules.communications.service import bind_request_background_tasks  # noqa: E402

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    # Every route gets the request's BackgroundTasks bound for
    # communications.queue_email, so outbound email is sent after the
    # response instead of blocking it on SMTP.
    dependencies=[Depends(bind_request_background_tasks)],
)

async def _missing_compliance_configuration_handler(request: Request, exc: MissingComplianceConfigurationError):
    """Converts the payroll engine's plain (framework-free by design)
    MissingComplianceConfigurationError into the same clean JSON error
    shape every other Zoiko error uses — kept here rather than in
    core/exceptions.py so that module doesn't have to import a
    payroll-specific engine class."""
    from app.core.exceptions import _cors_headers
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": "MISSING_COMPLIANCE_CONFIGURATION",
            "message": str(exc),
            "detail": str(exc),
        },
        headers=_cors_headers(request),
    )


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(ZoikoException, zoiko_exception_handler)
app.add_exception_handler(ProgrammingError, database_schema_error_handler)
app.add_exception_handler(MissingComplianceConfigurationError, _missing_compliance_configuration_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── CORS ─────────────────────────────────────────────────────────────────────

_cors_origins = [
    o.strip()
    for o in settings.PAYROLL_CORS_ORIGINS.split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────

from app.modules.auth.router import router as auth_router
from app.modules.auth.router import user_router as auth_user_router
from app.modules.organizations.router import router as organizations_router
from app.modules.organizations.router import jurisdiction_router
from app.modules.super_admin.router import router as super_admin_router
from app.modules.super_admin.command_center_router import router as super_admin_command_center_router
from app.modules.payroll.router import payroll_router
from app.modules.payroll.netherlands_router import router as netherlands_router
from app.modules.payroll.mexico_router import router as mexico_router
from app.modules.payroll.forms.router import public_forms_router
from app.modules.assist.router import assist_router
from app.modules.assist.public_router import assist_public_router
from app.modules.billing.router import router as billing_router
from app.modules.billing.admin_router import router as billing_admin_router
from app.modules.assisted_access.router import sa_router as assisted_access_sa_router
from app.modules.assisted_access.router import org_router as assisted_access_org_router

app.include_router(auth_router, prefix="/api")
app.include_router(auth_user_router, prefix="/api")
app.include_router(organizations_router, prefix="/api")
app.include_router(jurisdiction_router, prefix="/api")
app.include_router(super_admin_router, prefix="/api")
app.include_router(netherlands_router, prefix="/api")
app.include_router(mexico_router, prefix="/api")
app.include_router(super_admin_command_center_router, prefix="/api")
app.include_router(payroll_router, prefix="/api")
app.include_router(public_forms_router, prefix="/api/payroll")
app.include_router(assist_router, prefix="/api")
app.include_router(assist_public_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(billing_admin_router, prefix="/api")
app.include_router(assisted_access_sa_router, prefix="/api")
app.include_router(assisted_access_org_router, prefix="/api")

# ZP-PRIV Part D: JIT Support Access (supersedes Assisted Access).
from app.modules.support_access.router import operator_router as support_access_operator_router  # noqa: E402
from app.modules.support_access.router import tenant_router as support_access_tenant_router  # noqa: E402

app.include_router(support_access_operator_router, prefix="/api")
app.include_router(support_access_tenant_router, prefix="/api")

# ZP-PRIV C.3: pay groups, user scope, employee placement (org admins).
from app.modules.organizations.scope_router import router as organization_scope_router  # noqa: E402

app.include_router(organization_scope_router, prefix="/api")

# ZP-PRIV D/E/F: security events, alerts, inventory, machine clients.
from app.modules.security.router import platform_router as security_platform_router  # noqa: E402
from app.modules.security.router import tenant_router as security_tenant_router  # noqa: E402

app.include_router(security_platform_router, prefix="/api")
app.include_router(security_tenant_router, prefix="/api")


@app.middleware("http")
async def export_size_middleware(request: Request, call_next):
    """ZP-PRIV E03: record the size of every completed export (rows for JSON
    lists, bytes otherwise) as a security event - feeds the large-export
    alert. Metadata only; the body itself is never stored."""
    response = await call_next(request)
    policy = getattr(request.state, "authz_policy", None)
    if policy is None or policy.action != "export" or response.status_code >= 400:
        return response
    size = int(response.headers.get("content-length") or 0)
    from app.modules.security import events as security_events

    principal = getattr(request.state, "authz_principal", None)
    security_events.emit(
        getattr(request.state, "authz_db"), "EXPORT_COMPLETED", result="allow",
        actor_user_id=getattr(principal, "user_id", None), actor_role=getattr(principal, "role", None),
        organization_id=getattr(principal, "organization_id", None), target_type=f"route:{policy.data_class}",
        target_id=f"{request.method} {policy.path}|0:{size}", action="export", request=request)
    return response


@app.middleware("http")
async def no_store_middleware(request: Request, call_next):
    """ZP-PRIV T09: nothing a credentialed request returns may be kept by a
    browser, proxy or CDN cache and replayed to someone else later."""
    response = await call_next(request)
    policy = getattr(request.state, "authz_policy", None)
    credentialed = "authorization" in request.headers or "cookie" in request.headers
    if credentialed or (policy is not None and policy.data_class != "public"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        vary = response.headers.get("Vary")
        response.headers["Vary"] = f"{vary}, Authorization" if vary and "Authorization" not in vary else (vary or "Authorization")
    return response


@app.middleware("http")
async def support_access_projection_middleware(request: Request, call_next):
    """Field-class projection of worker records for temporary support users
    (ZP-PRIV B04); a no-op for every other principal."""
    from app.modules.support_access.projection import project_support_response

    response = await call_next(request)
    return await project_support_response(request, response)

# ── Correlation id (ZP-PRIV E01) ────────────────────────────────────────────
# Registered first = innermost: it wraps the application itself, so every
# handler, the PDP, audit rows, security events and log lines see the id (the
# middlewares registered after it read request.state.correlation_id), and the
# response echoes it.

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    from app.core import correlation

    cid = correlation.accept(request.headers.get(correlation.HEADER))
    request.state.correlation_id = cid
    token = correlation.set_current(cid)
    ip_token = correlation.client_ip.set(request.client.host if request.client else None)
    try:
        response = await call_next(request)
    finally:
        correlation._current.reset(token)
        correlation.client_ip.reset(ip_token)
    response.headers[correlation.HEADER] = cid
    return response


# ── Assisted Access audit middleware ────────────────────────────────────────
# Single chokepoint: every request that ran under a SafeGuard assisted-access
# token is appended to assisted_access_audit_events. Best-effort by design —
# an audit write failure must never break the request it describes.

@app.middleware("http")
async def assisted_access_audit_middleware(request: Request, call_next):
    from app.modules.assisted_access.audit import record_request_if_assisted

    response = await call_next(request)
    record_request_if_assisted(request, response.status_code)
    return response


# Registered last = outermost. When the client disconnects before a response
# exists (a health probe or browser tab giving up), Starlette's
# BaseHTTPMiddleware raises "No response returned." That is not an
# application error: answer 499 quietly instead of logging a traceback.
@app.middleware("http")
async def client_disconnect_middleware(request: Request, call_next):
    from starlette.responses import Response

    try:
        return await call_next(request)
    except RuntimeError as exc:
        if str(exc) == "No response returned." and await request.is_disconnected():
            return Response(status_code=499)
        raise

# ── Root health ──────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def health_root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    from app.database import check_connection

    return {"status": "ok", "database": "connected" if check_connection() else "unavailable"}


@app.get("/health/celery", tags=["Health"])
@app.get("/api/health/celery", tags=["Health"])
def health_celery():
    from app.config import settings
    from app.core.celery_app import celery_app
    from app.core.cache import get_redis_client

    if not settings.REDIS_URL:
        return {
            "status": "unconfigured",
            "message": "Celery disabled; running in synchronous mode",
            "broker": "unconfigured",
            "workers": [],
            "worker_count": 0,
        }

    # Test broker connectivity
    broker_status = "offline"
    try:
        r = get_redis_client()
        if r is not None and r.ping():
            broker_status = "connected"
    except Exception as exc:
        logger.warning("Redis ping failed during celery health check: %s", exc)
        broker_status = "offline"

    # Inspect active workers with 1.0s timeout
    active_workers = []
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        pings = insp.ping() or {}
        active_workers = list(pings.keys())
    except Exception as exc:
        logger.warning("Celery worker inspect failed: %s", exc)

    worker_count = len(active_workers)
    if broker_status == "connected" and worker_count > 0:
        overall_status = "healthy"
    elif broker_status == "connected":
        overall_status = "degraded"
    else:
        overall_status = "offline"

    return {
        "status": overall_status,
        "broker": broker_status,
        "workers": active_workers,
        "worker_count": worker_count,
    }


# ── Privacy PDP: default-deny route policy install ──────────────────────────
# Must run AFTER every include_router (and the health routes above) so the
# PDP dependency lands in front of every existing route's own gates. Routes
# with no registry entry get a deny-all policy (fail closed).
from app.core.authz.policy import install_route_policies  # noqa: E402

install_route_policies(app)

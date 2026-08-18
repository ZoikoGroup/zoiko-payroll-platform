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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.core.exceptions import (
    ZoikoException,
    zoiko_exception_handler,
    generic_exception_handler,
)
from app.core.rate_limiter import limiter
from app.database import initialize_database

logger = logging.getLogger("zoiko_payroll")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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
async def lifespan(app: FastAPI):
    initialize_database()
    from app.modules.assist.scheduler import start_assist_scheduler, stop_assist_scheduler

    start_assist_scheduler()
    logger.info("Zoiko Payroll Platform backend is ready.")
    yield
    stop_assist_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(ZoikoException, zoiko_exception_handler)
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
from app.modules.payroll.router import payroll_router
from app.modules.payroll.forms.router import public_forms_router
from app.modules.assist.router import assist_router
from app.modules.payroll.hierarchy.router import hierarchy_super_admin_router, hierarchy_org_router

app.include_router(auth_router, prefix="/api")
app.include_router(auth_user_router, prefix="/api")
app.include_router(organizations_router, prefix="/api")
app.include_router(jurisdiction_router, prefix="/api")
app.include_router(super_admin_router, prefix="/api")
app.include_router(payroll_router, prefix="/api")
app.include_router(public_forms_router, prefix="/api/payroll")
app.include_router(assist_router, prefix="/api")
# New, additive API surface for the generic jurisdiction/tax hierarchy
# engine (Phase 4) — old /super-admin/compliance/* and
# /payroll/compliance/* endpoints above are untouched and keep serving
# the old JurisdictionPack/ContributionRate/TaxSlab data.
app.include_router(hierarchy_super_admin_router, prefix="/api")
app.include_router(hierarchy_org_router, prefix="/api")

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

"""
modules/assist/scheduler.py
----------------------------
Background sweep for Zoiko Payroll Assist.

Runs the same KB-expiry and session-retention sweeps already exposed as
manual admin endpoints (POST /assist/admin/knowledge/expiry-run,
POST /assist/admin/retention/run), on a timer instead of requiring an
admin to click a button. Each run is scoped per-organization, using a
fresh DB session per organization so one org's failure can't affect
another's, and mirrors the manual endpoints exactly rather than
duplicating their logic.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.modules.assist import service

logger = logging.getLogger("zoiko_payroll.assist.scheduler")

_scheduler: BackgroundScheduler | None = None

# Last-run tracking consumed by GET /super-admin/platform/service-health —
# an in-memory dict, not persisted, so it reflects only this process's runs.
last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


def _sweep_all_organizations() -> None:
    from app.modules.organizations.models import Organization

    last_run_status["last_run_at"] = datetime.utcnow()
    had_error = False

    db = SessionLocal()
    try:
        org_ids = [row[0] for row in db.query(Organization.id).all()]
    finally:
        db.close()

    for org_id in org_ids:
        db = SessionLocal()
        try:
            expiry_result = service.run_kb_expiry_sweep(db, org_id)
            if expiry_result.get("expired"):
                logger.info("[assist-sweep] org=%s expired %s KB item(s)", org_id, expiry_result["expired"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("[assist-sweep] KB expiry sweep failed for org=%s", org_id)
            had_error = True
            last_run_status["last_error"] = str(exc)
        finally:
            db.close()

        db = SessionLocal()
        try:
            # No authenticated user for a scheduled run — _audit already
            # treats a None user as a system-attributed event (user_id=None).
            retention_result = service.run_retention_cleanup(db, org_id, None)
            if retention_result.get("archived"):
                logger.info("[assist-sweep] org=%s archived %s session(s)", org_id, retention_result["archived"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("[assist-sweep] Retention cleanup failed for org=%s", org_id)
            had_error = True
            last_run_status["last_error"] = str(exc)
        finally:
            db.close()

    if not had_error:
        last_run_status["last_success_at"] = datetime.utcnow()
        last_run_status["last_error"] = None


def start_assist_scheduler() -> BackgroundScheduler | None:
    """Start the background sweep on app startup. No-op if disabled via
    ASSIST_SWEEP_ENABLED or already running (safe to call more than once)."""
    global _scheduler
    if not settings.ASSIST_SWEEP_ENABLED:
        logger.info("[assist-sweep] Disabled via ASSIST_SWEEP_ENABLED=false; not starting.")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _sweep_all_organizations,
        "interval",
        hours=settings.ASSIST_SWEEP_INTERVAL_HOURS,
        id="assist_sweep",
        # Default IntervalTrigger behavior: first run is one interval from
        # now, not immediately on every app boot/restart.
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("[assist-sweep] Started, running every %s hour(s).", settings.ASSIST_SWEEP_INTERVAL_HOURS)
    return _scheduler


def stop_assist_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

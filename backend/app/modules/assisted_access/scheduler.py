"""
modules/assisted_access/scheduler.py
------------------------------------
Background expiry sweep for Assisted Access sessions — identical pattern to
modules/billing/scheduler.py and modules/assist/scheduler.py: a single
BackgroundScheduler job guarded by ASSISTED_ACCESS_SWEEP_ENABLED, running
assisted_service.run_expiry_sweep (idempotent, non-duplicating). The hard
cap (expires_at) is enforced structurally: even if nobody ends a session
manually, the sweep ends whatever is past its expiry.

Last-run status is tracked in-memory for GET /super-admin/platform/
service-health, mirroring trial_expiry_sweep / assist_sweep.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.modules.assisted_access.service import run_expiry_sweep

logger = logging.getLogger("zoiko_payroll.assisted_access.scheduler")

_scheduler: BackgroundScheduler | None = None

last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


def _run_sweep() -> None:
    db = SessionLocal()
    last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = run_expiry_sweep(db)
        if result["ended"]:
            logger.info("[assisted-access-sweep] ended=%s", len(result["ended"]))
        last_run_status["last_success_at"] = datetime.utcnow()
        last_run_status["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("[assisted-access-sweep] Sweep run failed")
        last_run_status["last_error"] = str(exc)
    finally:
        db.close()


def start_assisted_access_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    """Start on app startup. No-op if disabled or already running. `run_now`
    executes one sweep immediately before scheduling (used once at startup so
    service-health shows a real last-run rather than 'unknown' for one full
    interval)."""
    global _scheduler
    if not settings.ASSISTED_ACCESS_SWEEP_ENABLED:
        logger.info("[assisted-access-sweep] Disabled via ASSISTED_ACCESS_SWEEP_ENABLED=false; not starting.")
        return None
    if _scheduler is not None:
        return _scheduler

    if run_now:
        logger.info("[assisted-access-sweep] Running initial sweep at startup.")
        _run_sweep()

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_sweep,
        "interval",
        minutes=settings.ASSISTED_ACCESS_SWEEP_INTERVAL_MINUTES,
        id="assisted_access_sweep",
        # First run is one interval from now — never immediately on boot.
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        "[assisted-access-sweep] Started, running every %s minute(s).",
        settings.ASSISTED_ACCESS_SWEEP_INTERVAL_MINUTES,
    )
    return _scheduler


def stop_assisted_access_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
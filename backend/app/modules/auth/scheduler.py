"""
modules/auth/scheduler.py
--------------------------
Background sweep for the revoked_tokens table (platform infrastructure
fix plan, Tier 3). Mirrors modules/billing/scheduler.py exactly: one
idempotent, non-duplicating job guarded by TOKEN_CLEANUP_SWEEP_ENABLED.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.modules.auth.service import run_revoked_token_cleanup_sweep

logger = logging.getLogger("zoiko_payroll.auth.scheduler")

_scheduler: BackgroundScheduler | None = None

last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


def _run_sweep() -> None:
    db = SessionLocal()
    last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = run_revoked_token_cleanup_sweep(db)
        if result["deleted"]:
            logger.info("[token-cleanup] deleted=%s expired revocation rows", result["deleted"])
        last_run_status["last_success_at"] = datetime.utcnow()
        last_run_status["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("[token-cleanup] Sweep run failed")
        last_run_status["last_error"] = str(exc)
    finally:
        db.close()


def start_token_cleanup_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    """Start the background revoked-token cleanup sweep on app startup.
    No-op if disabled via TOKEN_CLEANUP_SWEEP_ENABLED or already running
    (safe to call more than once). `run_now` executes one sweep immediately
    before scheduling (used once at startup so service-health shows a real
    last-run rather than 'unknown' for one full interval)."""
    global _scheduler
    if not settings.TOKEN_CLEANUP_SWEEP_ENABLED:
        logger.info("[token-cleanup] Disabled via TOKEN_CLEANUP_SWEEP_ENABLED=false; not starting.")
        return None
    if _scheduler is not None:
        return _scheduler

    if run_now:
        logger.info("[token-cleanup] Running initial sweep at startup.")
        _run_sweep()

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_sweep,
        "interval",
        hours=settings.TOKEN_CLEANUP_SWEEP_INTERVAL_HOURS,
        id="revoked_token_cleanup_sweep",
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("[token-cleanup] Started, running every %s hour(s).", settings.TOKEN_CLEANUP_SWEEP_INTERVAL_HOURS)
    return _scheduler


def stop_token_cleanup_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

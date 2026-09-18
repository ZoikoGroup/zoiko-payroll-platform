"""
modules/billing/scheduler.py
------------------------------
Background sweep for the trial lifecycle (Prompt 5).

Runs the same expiry sweep already exposed as a manual admin endpoint
(POST /super-admin/billing/trial-expiry-run) on a timer, mirroring
modules/assist/scheduler.py exactly: idempotent, non-duplicating, one job
guarded by TRIAL_SWEEP_ENABLED. run_trial_expiry_sweep itself iterates all
TRIALING subscriptions in one session and commits per-org transitions, so a
single org's failure can't corrupt another's row — each transition already
sits in its own transaction.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.modules.billing.trial_lifecycle import run_trial_expiry_sweep
from app.modules.billing.dunning import run_dunning_sweep

logger = logging.getLogger("zoiko_payroll.billing.scheduler")

_scheduler: BackgroundScheduler | None = None
_dunning_scheduler: BackgroundScheduler | None = None

dunning_last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}

# Last-run tracking consumed by GET /super-admin/platform/service-health —
# an in-memory dict, not persisted, so it reflects only this process's runs.
last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


def _run_sweep() -> None:
    db = SessionLocal()
    last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = run_trial_expiry_sweep(db)
        if result["scanned"]:
            logger.info(
                "[trial-sweep] scanned=%s grace_started=%s closed=%s",
                result["scanned"],
                len(result["grace_started"]),
                len(result["closed"]),
            )
        last_run_status["last_success_at"] = datetime.utcnow()
        last_run_status["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("[trial-sweep] Sweep run failed")
        last_run_status["last_error"] = str(exc)
    finally:
        db.close()


def start_trial_scheduler() -> BackgroundScheduler | None:
    """Start the background trial sweep on app startup. No-op if disabled
    via TRIAL_SWEEP_ENABLED or already running (safe to call more than once)."""
    global _scheduler
    if not settings.TRIAL_SWEEP_ENABLED:
        logger.info("[trial-sweep] Disabled via TRIAL_SWEEP_ENABLED=false; not starting.")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_sweep,
        "interval",
        hours=settings.TRIAL_SWEEP_INTERVAL_HOURS,
        id="trial_expiry_sweep",
        # Default IntervalTrigger behavior: first run is one interval from
        # now, not immediately on every app boot/restart.
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("[trial-sweep] Started, running every %s hour(s).", settings.TRIAL_SWEEP_INTERVAL_HOURS)
    return _scheduler


def stop_trial_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _run_dunning_sweep() -> None:
    db = SessionLocal()
    dunning_last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = run_dunning_sweep(db)
        if result["scanned"]:
            logger.info("[dunning-sweep] scanned=%s advanced=%s", len(result["scanned"]), len(result["advanced"]))
        dunning_last_run_status["last_success_at"] = datetime.utcnow()
        dunning_last_run_status["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("[dunning-sweep] Sweep run failed")
        dunning_last_run_status["last_error"] = str(exc)
    finally:
        db.close()


def start_dunning_scheduler() -> BackgroundScheduler | None:
    """Start the background dunning sweep on app startup. No-op if disabled
    via DUNNING_SWEEP_ENABLED or already running (safe to call more than once)."""
    global _dunning_scheduler
    if not settings.DUNNING_SWEEP_ENABLED:
        logger.info("[dunning-sweep] Disabled via DUNNING_SWEEP_ENABLED=false; not starting.")
        return None
    if _dunning_scheduler is not None:
        return _dunning_scheduler

    _dunning_scheduler = BackgroundScheduler(timezone="UTC")
    _dunning_scheduler.add_job(
        _run_dunning_sweep,
        "interval",
        hours=settings.DUNNING_SWEEP_INTERVAL_HOURS,
        id="dunning_sweep",
        coalesce=True,
        max_instances=1,
    )
    _dunning_scheduler.start()
    logger.info("[dunning-sweep] Started, running every %s hour(s).", settings.DUNNING_SWEEP_INTERVAL_HOURS)
    return _dunning_scheduler


def stop_dunning_scheduler() -> None:
    global _dunning_scheduler
    if _dunning_scheduler is not None:
        _dunning_scheduler.shutdown(wait=False)
        _dunning_scheduler = None
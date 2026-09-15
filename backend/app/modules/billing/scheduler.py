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

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.modules.billing.trial_lifecycle import run_trial_expiry_sweep

logger = logging.getLogger("zoiko_payroll.billing.scheduler")

_scheduler: BackgroundScheduler | None = None


def _run_sweep() -> None:
    db = SessionLocal()
    try:
        result = run_trial_expiry_sweep(db)
        if result["scanned"]:
            logger.info(
                "[trial-sweep] scanned=%s grace_started=%s closed=%s",
                result["scanned"],
                len(result["grace_started"]),
                len(result["closed"]),
            )
    except Exception:  # noqa: BLE001
        logger.exception("[trial-sweep] Sweep run failed")
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
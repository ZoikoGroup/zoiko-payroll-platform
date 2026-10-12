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

BWM aggregation (Prompt 4, §4) populates billing_worker_month_records — a
Compute-only path (never calls a gateway) whose rows feed
bwm_invoice_mismatches on the Exceptions & Reconciliation page and future
metered invoicing. Previously had no callers; wiring this scheduler closes
that gap.
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
_bwm_aggregation_scheduler: BackgroundScheduler | None = None

dunning_last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}

# Last-run tracking consumed by GET /super-admin/platform/service-health —
# an in-memory dict, not persisted, so it reflects only this process's runs.
last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}

# BWM aggregation tracker, same semantics as last_run_status/dunning_last_run_status.
bwm_last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


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


def start_trial_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    """Start the background trial sweep on app startup. No-op if disabled
    via TRIAL_SWEEP_ENABLED or already running (safe to call more than once).
    `run_now` executes one sweep immediately before scheduling (used once at
    startup so service-health shows a real last-run rather than 'unknown'
    for one full interval)."""
    global _scheduler
    if not settings.TRIAL_SWEEP_ENABLED:
        logger.info("[trial-sweep] Disabled via TRIAL_SWEEP_ENABLED=false; not starting.")
        return None
    if _scheduler is not None:
        return _scheduler

    if run_now:
        logger.info("[trial-sweep] Running initial sweep at startup.")
        _run_sweep()

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


def start_dunning_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    """Start the background dunning sweep on app startup. No-op if disabled
    via DUNNING_SWEEP_ENABLED or already running (safe to call more than once).
    `run_now` executes one sweep immediately before scheduling (used once at
    startup so service-health shows a real last-run rather than 'unknown'
    for one full interval)."""
    global _dunning_scheduler
    if not settings.DUNNING_SWEEP_ENABLED:
        logger.info("[dunning-sweep] Disabled via DUNNING_SWEEP_ENABLED=false; not starting.")
        return None
    if _dunning_scheduler is not None:
        return _dunning_scheduler

    if run_now:
        logger.info("[dunning-sweep] Running initial sweep at startup.")
        _run_dunning_sweep()

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


def _run_bwm_aggregation(billing_month=None) -> dict:
    """Run the monthly BWM aggregation for every org with employees.
    Idempotent — aggregate_billing_month upserts per (org, employee, month)
    against the UniqueConstraint, so re-running a month updates in place."""
    from app.modules.billing import bwm as bwm_service

    db = SessionLocal()
    bwm_last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = bwm_service.aggregate_all_billing_months(db, billing_month=billing_month)
        logger.info(
            "[bwm-aggregation] month=%s orgs=%s",
            result["billing_month"],
            result["organizations_processed"],
        )
        bwm_last_run_status["last_success_at"] = datetime.utcnow()
        bwm_last_run_status["last_error"] = None
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("[bwm-aggregation] Aggregation run failed")
        bwm_last_run_status["last_error"] = str(exc)
        return {"billing_month": billing_month, "organizations_processed": 0, "organizations": [], "error": str(exc)}
    finally:
        db.close()


def _bwm_sweep_job() -> None:
    _run_bwm_aggregation()


def start_bwm_aggregation_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    """Start the background BWM aggregation on app startup. No-op if
    disabled via BWM_AGGREGATION_ENABLED or already running (safe to call
    more than once). `run_now` executes one aggregation immediately before
    scheduling (used once at startup so billing_worker_month_records is
    populated right away rather than one interval later)."""
    global _bwm_aggregation_scheduler
    if not settings.BWM_AGGREGATION_ENABLED:
        logger.info("[bwm-aggregation] Disabled via BWM_AGGREGATION_ENABLED=false; not starting.")
        return None
    if _bwm_aggregation_scheduler is not None:
        return _bwm_aggregation_scheduler

    if run_now:
        logger.info("[bwm-aggregation] Running initial aggregation at startup.")
        _run_bwm_aggregation()

    _bwm_aggregation_scheduler = BackgroundScheduler(timezone="UTC")
    _bwm_aggregation_scheduler.add_job(
        _bwm_sweep_job,
        "interval",
        hours=settings.BWM_AGGREGATION_INTERVAL_HOURS,
        id="bwm_aggregation",
        coalesce=True,
        max_instances=1,
    )
    _bwm_aggregation_scheduler.start()
    logger.info(
        "[bwm-aggregation] Started, running every %s hour(s).",
        settings.BWM_AGGREGATION_INTERVAL_HOURS,
    )
    return _bwm_aggregation_scheduler


def stop_bwm_aggregation_scheduler() -> None:
    global _bwm_aggregation_scheduler
    if _bwm_aggregation_scheduler is not None:
        _bwm_aggregation_scheduler.shutdown(wait=False)
        _bwm_aggregation_scheduler = None
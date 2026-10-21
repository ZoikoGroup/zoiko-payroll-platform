"""
modules/support_access/scheduler.py
-----------------------------------
The JIT Support Access minute job (ZP-PRIV D.3): ends overdue grants,
deactivates any temporary account past its window and escalates overdue
break-glass reviews. Expiry does not DEPEND on this job - login, refresh,
the per-request auth check and the PDP all refuse an expired grant on their
own - the sweep only makes the stored state catch up.

At startup it also retires every legacy assisted-access session still open
(Part D supersedes that flow; its tables are kept for history).

Same pattern as the other schedulers (assisted_access/scheduler.py).
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger("zoiko_payroll.support_access.scheduler")

_scheduler: BackgroundScheduler | None = None

last_run_status: dict = {"last_run_at": None, "last_success_at": None, "last_error": None}


def _run_sweep() -> None:
    from app.modules.support_access.service import run_sweep

    db = SessionLocal()
    last_run_status["last_run_at"] = datetime.utcnow()
    try:
        result = run_sweep(db)
        if result["ended"] or result["deactivated_users"] or result["escalated_reviews"]:
            logger.info("[support-access-sweep] %s", result)
        last_run_status["last_success_at"] = datetime.utcnow()
        last_run_status["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("[support-access-sweep] Sweep run failed")
        last_run_status["last_error"] = str(exc)
    finally:
        db.close()


def retire_legacy_assisted_access() -> None:
    from app.modules.support_access.service import retire_legacy_assisted_sessions

    db = SessionLocal()
    try:
        ended = retire_legacy_assisted_sessions(db)
        if ended:
            logger.warning("[support-access] retired %s legacy assisted-access session(s)", ended)
    except Exception:  # noqa: BLE001 - the assisted path rejects these tokens anyway
        logger.exception("[support-access] legacy assisted-access retirement failed")
    finally:
        db.close()


def start_support_access_scheduler(run_now: bool = False) -> BackgroundScheduler | None:
    global _scheduler
    if not settings.SUPPORT_ACCESS_SWEEP_ENABLED or _scheduler is not None:
        return _scheduler
    if run_now:
        _run_sweep()
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_run_sweep, "interval", seconds=settings.SUPPORT_ACCESS_SWEEP_INTERVAL_SECONDS,
                       id="support_access_sweep", max_instances=1, coalesce=True)
    _scheduler.start()
    return _scheduler


def stop_support_access_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

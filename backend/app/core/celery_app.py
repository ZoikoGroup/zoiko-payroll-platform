"""
app/core/celery_app.py
-----------------------
Celery application configuration for Zoiko Payroll Platform.

Provides asynchronous task processing for long-running operations:
- Payroll runs (parallel per-employee processing)
- Bulk employee import/export
- Attendance bulk upload/processing
- Revenue/ROS submissions
- Report generation
- Email/notifications
"""
import os
from celery import Celery
from celery.schedules import crontab
from app.config import settings

# Create Celery instance
celery_app = Celery(
    "zoiko_payroll",
    broker=settings.REDIS_URL or "redis://localhost:6379/0",
    backend=settings.REDIS_URL or "redis://localhost:6379/1",
    include=[
        "app.tasks.payroll_tasks",
        "app.tasks.attendance_tasks",
        "app.tasks.employee_tasks",
        "app.tasks.report_tasks",
        "app.tasks.email_tasks",
        "app.tasks.billing_tasks",
        "app.tasks.auth_tasks",
        "app.tasks.assist_tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    
    # Worker configuration
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # Result backend
    result_expires=3600,
    result_compression="gzip",
    
    # Task routing
    task_routes={
        "app.tasks.payroll_tasks.*": {"queue": "payroll"},
        "app.tasks.attendance_tasks.*": {"queue": "attendance"},
        "app.tasks.employee_tasks.*": {"queue": "employees"},
        "app.tasks.report_tasks.*": {"queue": "reports"},
        "app.tasks.email_tasks.*": {"queue": "emails"},
        "app.tasks.billing_tasks.*": {"queue": "billing"},
        "app.tasks.auth_tasks.*": {"queue": "maintenance"},
        "app.tasks.assist_tasks.*": {"queue": "assist"},
    },
    
    # Queue configuration
    task_default_queue="default",
    task_create_missing_queues=True,
    
    # Beat schedule (periodic tasks)
    # Only tasks with a real implementation belong here. The trial-expiry
    # and Assist KB-expiry tasks are still NotImplementedError stubs — beat
    # would fail them every day — and those sweeps already run in-process
    # via the schedulers started in main.py's lifespan. Add them back only
    # once the task bodies exist AND the in-process scheduler is retired,
    # or the sweep runs twice.
    beat_schedule={
        # Daily token cleanup at 03:00 UTC
        "token-cleanup": {
            "task": "app.tasks.auth_tasks.revoked_token_cleanup_task",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "maintenance"},
        },
        # Weekly token cleanup at 05:00 UTC on Sunday
        "weekly-token-cleanup": {
            "task": "app.tasks.auth_tasks.weekly_revoked_token_cleanup_task",
            "schedule": crontab(hour=5, minute=0, day_of_week=0),
            "options": {"queue": "maintenance"},
        },
    },
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)
# NOTE: retry/backoff policy is set per task via @shared_task(autoretry_for=...).
# It is deliberately NOT set globally: a blanket auto-retry would silently
# replay non-idempotent work (payment capture, Revenue submission) after an
# error that the task never actually got far enough to attempt.

# Make this the process-wide default app, not just the current one.
# Every task is declared with @shared_task, which resolves its app through
# Celery's "current app" — and that is THREAD-LOCAL. Celery() only marks
# itself current in the thread that constructed it, so in any other thread
# (FastAPI runs sync endpoints on a threadpool) a shared task resolved to
# Celery's unconfigured fallback app and .delay() tried AMQP on localhost
# instead of REDIS_URL. set_default() makes every thread see this app.
celery_app.set_default()

# Auto-discover tasks
celery_app.autodiscover_tasks([
    "app.tasks.payroll_tasks",
    "app.tasks.attendance_tasks",
    "app.tasks.employee_tasks",
    "app.tasks.report_tasks",
    "app.tasks.email_tasks",
    "app.tasks.billing_tasks",
    "app.tasks.auth_tasks",
    "app.tasks.assist_tasks",
])


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery connectivity."""
    print(f"Request: {self.request!r}")


if __name__ == "__main__":
    celery_app.start()
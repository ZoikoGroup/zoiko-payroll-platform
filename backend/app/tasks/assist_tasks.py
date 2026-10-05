"""
app/tasks/assist_tasks.py
--------------------------
Celery tasks for Zoiko Payroll Assist.

Handles KB expiry sweep, retention cleanup, and conversation management.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.assist import service as assist_service

logger = get_task_logger(__name__)


def get_db() -> Session:
    """Get a new database session for the task."""
    return SessionLocal()


@shared_task(
    bind=True,
    queue="assist",
)
def kb_expiry_sweep_task(self) -> Dict[str, Any]:
    raise NotImplementedError(
        "kb_expiry_sweep_task is not implemented: this task has no KB retention sweep; no expiry policy is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def retention_cleanup_task(self) -> Dict[str, Any]:
    raise NotImplementedError(
        "retention_cleanup_task is not implemented: this task has no retention job; no retention window is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def archive_old_conversations_task(self, older_than_days: int = 365) -> Dict:
    raise NotImplementedError(
        "archive_old_conversations_task is not implemented: this task has no conversation archival. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def cleanup_orphaned_sessions_task(self) -> Dict:
    raise NotImplementedError(
        "cleanup_orphaned_sessions_task is not implemented: this task has no orphaned-session cleanup. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def rebuild_search_index_task(self, kb_id: Optional[int] = None) -> Dict:
    raise NotImplementedError(
        "rebuild_search_index_task is not implemented: this task has no search indexer; no index is built by this task. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def process_feedback_task(self, feedback_id: int) -> Dict:
    raise NotImplementedError(
        "process_feedback_task is not implemented: this task has no feedback processing. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def train_model_task(self, model_name: str, training_data: List[Dict]) -> Dict:
    raise NotImplementedError(
        "train_model_task is not implemented: this task has no training pipeline; it reported 'started' without starting anything. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def sync_knowledge_base_task(self, kb_id: int) -> Dict:
    raise NotImplementedError(
        "sync_knowledge_base_task is not implemented: this task has no KB sync; no external source is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="assist",
)
def generate_assist_analytics_task(self, start_date: str, end_date: str) -> Dict:
    raise NotImplementedError(
        "generate_assist_analytics_task is not implemented: this task has no analytics report; the returned URL would 404. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )

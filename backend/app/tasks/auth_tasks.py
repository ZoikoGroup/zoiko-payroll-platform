"""
app/tasks/auth_tasks.py
-------------------------
Celery tasks for authentication and token management.

Handles token cleanup, revoked token cleanup, and security-related tasks.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.auth.models import RevokedToken, SecurityActionToken

logger = get_task_logger(__name__)


def get_db() -> Session:
    """Get a new database session for the task."""
    return SessionLocal()


@shared_task(
    bind=True,
    queue="maintenance",
)
def revoked_token_cleanup_task(self) -> Dict[str, Any]:
    """
    Daily cleanup of expired revoked tokens.
    
    Deletes revoked_token rows where expires_at has passed.
    
    Returns:
        Dict with cleanup results
    """
    db = SessionLocal()
    try:
        from app.modules.auth.models import RevokedToken
        from datetime import datetime
        
        deleted = db.query(RevokedToken).filter(
            RevokedToken.expires_at < datetime.utcnow()
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.info(f"Revoked token cleanup: deleted {deleted} expired tokens")
        
        return {
            "status": "completed",
            "deleted_count": deleted,
            "cleaned_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error(f"Revoked token cleanup failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="maintenance",
)
def weekly_revoked_token_cleanup_task(self) -> Dict[str, Any]:
    """
    Weekly archival cleanup of revoked tokens.

    Retains expired rows for 30 days past expiry before deleting them, so a
    token that turns out to need investigating is still auditable. Note
    RevokedToken carries no user_id, so nothing here identifies orphaned rows.
    """
    db = SessionLocal()
    try:
        from app.modules.auth.models import RevokedToken
        from datetime import datetime, timedelta
        
        # Delete tokens expired more than 30 days ago
        cutoff = datetime.utcnow() - timedelta(days=30)
        deleted = db.query(RevokedToken).filter(
            RevokedToken.expires_at < cutoff
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.info(f"Weekly revoked token cleanup: deleted {deleted} old tokens")
        
        return {
            "status": "completed",
            "deleted_count": deleted,
            "cleaned_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error(f"Weekly revoked token cleanup failed: {exc}")
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="maintenance",
)
def cleanup_expired_security_action_tokens_task(self) -> Dict:
    """
    Clean up expired security action tokens.
    """
    db = SessionLocal()
    try:
        from app.modules.auth.models import SecurityActionToken
        from datetime import datetime
        
        deleted = db.query(SecurityActionToken).filter(
            SecurityActionToken.expires_at < datetime.utcnow()
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return {
            "status": "completed",
            "deleted_count": deleted,
        }
    finally:
        pass


@shared_task(
    bind=True,
    queue="maintenance",
)
def cleanup_expired_password_reset_tokens_task(self) -> Dict:
    raise NotImplementedError(
        "cleanup_expired_password_reset_tokens_task is not implemented: this task has no reset-token cleanup; it reported 0 deleted without querying anything. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="maintenance",
)
def cleanup_expired_email_verification_tokens_task(self) -> Dict:
    raise NotImplementedError(
        "cleanup_expired_email_verification_tokens_task is not implemented: this task has no verification-token cleanup. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="maintenance",
)
def audit_log_cleanup_task(self) -> Dict:
    raise NotImplementedError(
        "audit_log_cleanup_task is not implemented: this task has no audit archival; no cold-storage target is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )

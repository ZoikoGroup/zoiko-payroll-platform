"""
modules/payroll/mail/tasks.py
--------------------------------
Scheduled entry point for polling every organization's configured
leave-request mailbox. Mirrors billing/tasks/recurring_billing.py's shape —
opens its own DB session since APScheduler jobs don't get FastAPI's
request-scoped Depends(get_db).

Does nothing (returns immediately, orgsPolled=0) until at least one
organization has IMAP enabled with real settings entered through
PUT /api/payroll/mail/settings — no credential is read from any file here.
"""

import logging

from app.database import SessionLocal
from app.modules.payroll.mail.service import poll_all_mailboxes

logger = logging.getLogger("zoiko")


def run_poll_mailbox_job():
    db = SessionLocal()
    try:
        result = poll_all_mailboxes(db)
        if result.get("orgsPolled"):
            logger.info(f"[payroll-mail] Poll cycle complete: {result}")
        return result
    except Exception as exc:
        logger.error(f"[payroll-mail] Poll cycle failed: {exc}")
        return {"error": str(exc)}
    finally:
        db.close()

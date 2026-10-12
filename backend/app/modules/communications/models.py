"""
modules/communications/models.py
--------------------------------
CommunicationEvent: the platform-wide record of truth for every outbound
email, generalised from auth's AuthEmailEvent (same shape, plus a `module`
column and an `attempt_count`).
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class CommunicationEvent(Base):
    """Persisted audit + double-send guard for every outbound email.

    The row is INSERTed (outcome="pending") BEFORE any SMTP call; the UNIQUE
    idempotency_key is the structural guard. A duplicate request hits the
    constraint, records its own outcome="skipped_duplicate" row (suffixed
    key), and never reaches SMTP. After the send, the original row's
    outcome / provider_response / attempt_count are updated from the real
    result (see communications/service.py dispatch_email).

    organization_id / recipient_user_id / actor_user_id are deliberately plain
    indexed integers, not foreign keys: an audit record must outlive the
    tenant or user it describes (the organization-deleted notice is sent
    *after* the organization row is gone, and a CASCADE would erase the
    evidence that any notice was ever sent).
    """

    __tablename__ = "communication_events"

    id = Column(Integer, primary_key=True, index=True)
    # Owning module: auth / organizations / billing / payroll / super_admin / assist.
    module = Column(String(32), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    # Catalog template ID (e.g. "IAM-007"). NULL where the catalog ID is not
    # known — never guessed.
    template_id = Column(String(40), nullable=True)
    recipient_email = Column(String(200), nullable=False, index=True)
    recipient_user_id = Column(Integer, nullable=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    actor_user_id = Column(Integer, nullable=True, index=True)
    # tenant | event | recipient | template | material version [| obj | chg | win]
    # — see service.idempotency_key. Nullable only for the migration window;
    # every call site sets it.
    idempotency_key = Column(String(255), unique=True, index=True, nullable=True)
    # pending (transient, in-flight) / sent / failed / skipped_duplicate.
    outcome = Column(String(24), nullable=False, default="pending")
    # SMTP provider detail on failure (e.g. "SMTPRecipientsRefused: ...").
    provider_response = Column(Text, nullable=True)
    # Real number of delivery attempts (retries on transient failures count).
    attempt_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return (
            f"<CommunicationEvent id={self.id} module={self.module} event_type={self.event_type} "
            f"outcome={self.outcome} attempts={self.attempt_count}>"
        )

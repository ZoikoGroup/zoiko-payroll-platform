"""
modules/security/alerts.py
--------------------------
Security alerting (ZP-PRIV E03). Thresholds are decision 8 (recorded
2026-10-19 by venu@zoikogroup.com) and exported to docs/privacy/alert_rules.json.

Every security event is observed here; a rule that fires creates or bumps an
alert_events row. Alerts are deduplicated per (rule, dedupe key, 15-minute
window) so a burst never becomes a storm, and they NEVER carry personal data:
summaries hold ids, codes and counts only. Delivery: the Super Admin Alerts
page (always) plus email to SECURITY_ALERT_EMAILS (when configured); no
secondary channel exists (decision 10), an optional webhook hook is left
unconfigured.

The clock is injectable (``set_clock``) so time-based tests are exact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.security.models import AlertEvent, AlertRule, SecurityEvent

logger = logging.getLogger("zoiko_payroll.security.alerts")

DEDUPE_WINDOW_SECONDS = 900
BUSINESS_HOURS_UTC = (7, 20)  # grants outside 07:00-20:00 UTC are "unscheduled"


@dataclass(frozen=True)
class RuleSpec:
    key: str
    description: str
    window_seconds: int
    threshold: int
    severity: str
    channel: str = "email+console"


RULES = (
    RuleSpec("cross_tenant_access", "Any attempt to read another tenant's object, or a platform role reaching "
             "worker data", 900, 1, "high"),
    RuleSpec("employee_enumeration", "One principal touching 25 or more distinct employee records in 10 minutes",
             600, 25, "high"),
    RuleSpec("large_export", "An export of 1,000 or more rows or 10 MB or more", 900, 1, "medium"),
    RuleSpec("unscheduled_elevation", "Support access granted outside 07:00-20:00 UTC, or any break-glass access",
             900, 1, "high"),
    RuleSpec("mfa_failures", "Five or more failed MFA or step-up attempts by one user in 15 minutes", 900, 5, "high"),
    RuleSpec("overdue_break_glass_review", "A break-glass post-incident review passed its 24-hour due time",
             900, 1, "high"),
    RuleSpec("failed_audit_write", "A security or audit record could not be written", 900, 1, "high"),
    RuleSpec("machine_client_new_network", "A machine client was used from a network it never used before",
             900, 1, "medium"),
)
RULES_BY_KEY = {r.key: r for r in RULES}
LARGE_EXPORT_ROWS = 1000
LARGE_EXPORT_BYTES = 10 * 1024 * 1024

_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731


def set_clock(fn: Optional[Callable[[], datetime]]) -> None:
    global _clock
    _clock = fn or (lambda: datetime.now(timezone.utc))


def now() -> datetime:
    return _clock()


def export_rules(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dedupe_window_seconds": DEDUPE_WINDOW_SECONDS,
                                "business_hours_utc": list(BUSINESS_HOURS_UTC),
                                "large_export": {"rows": LARGE_EXPORT_ROWS, "bytes": LARGE_EXPORT_BYTES},
                                "rules": [asdict(r) for r in RULES]}, indent=2), encoding="utf-8")


def ensure_rules(db: Session) -> None:
    existing = {r.key for r in db.query(AlertRule.key).all()}
    for spec in RULES:
        if spec.key not in existing:
            db.add(AlertRule(key=spec.key, description=spec.description, window_seconds=spec.window_seconds,
                             threshold=spec.threshold, severity=spec.severity, channel=spec.channel, enabled=True))
    db.commit()


def _rule(db: Session, key: str) -> RuleSpec:
    row = db.query(AlertRule).filter(AlertRule.key == key).first()
    spec = RULES_BY_KEY[key]
    if row is None:
        return spec
    if not row.enabled:
        return RuleSpec(spec.key, spec.description, row.window_seconds, 10 ** 9, row.severity, row.channel)
    return RuleSpec(spec.key, row.description, row.window_seconds, row.threshold, row.severity, row.channel)


def _window_start(at: datetime) -> datetime:
    epoch = int(at.timestamp())
    return datetime.fromtimestamp(epoch - epoch % DEDUPE_WINDOW_SECONDS, tz=timezone.utc)


def raise_alert(bind_or_db, rule_key: str, *, dedupe_key: str, summary: str,
                organization_id: Optional[int] = None, is_drill: bool = False) -> Optional[AlertEvent]:
    """Create (or bump, inside the dedupe window) one alert and deliver it."""
    bind = bind_or_db.get_bind() if hasattr(bind_or_db, "get_bind") else bind_or_db
    db = Session(bind=bind)
    try:
        spec = RULES_BY_KEY[rule_key]
        at = now()
        start = _window_start(at)
        row = (db.query(AlertEvent)
               .filter(AlertEvent.rule_key == rule_key, AlertEvent.dedupe_key == dedupe_key[:200],
                       AlertEvent.window_start == start).first())
        if row is not None:
            row.count += 1
            row.last_seen = at
            db.commit()
            return row
        row = AlertEvent(rule_key=rule_key, dedupe_key=dedupe_key[:200], window_start=start,
                         severity=spec.severity, summary=summary[:400], organization_id=organization_id,
                         first_seen=at, last_seen=at, count=1, status="open", is_drill=is_drill)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # a concurrent writer created it first: bump that one
            db.rollback()
            row = (db.query(AlertEvent).filter(AlertEvent.rule_key == rule_key,
                                               AlertEvent.dedupe_key == dedupe_key[:200],
                                               AlertEvent.window_start == start).first())
            if row is not None:
                row.count += 1
                row.last_seen = at
                db.commit()
            return row
        _deliver(db, row)
        return row
    finally:
        db.close()


def _deliver(db: Session, row: AlertEvent) -> None:
    from app.config import settings

    receipts = ["console"]
    recipients = [e.strip() for e in (getattr(settings, "SECURITY_ALERT_EMAILS", "") or "").split(",") if e.strip()]
    if recipients:
        from app.services.email_service import send_security_alert_email

        sent = 0
        for to in recipients:
            try:
                sent += 1 if send_security_alert_email(to, row.rule_key, row.severity, row.summary, db=db) else 0
            except Exception:  # noqa: BLE001
                logger.exception("[alerts] email delivery failed rule=%s", row.rule_key)
        receipts.append(f"email:{sent}/{len(recipients)}")
    row.delivered_at = now()
    row.delivery_receipt = ";".join(receipts)
    db.commit()
    logger.warning("[alerts] %s %s (%s) %s", row.severity.upper(), row.rule_key, row.delivery_receipt, row.summary)


def _count_since(db: Session, since: datetime, **filters) -> int:
    q = db.query(func.count(SecurityEvent.id)).filter(SecurityEvent.occurred_at >= since)
    for col, val in filters.items():
        column = getattr(SecurityEvent, col)
        q = q.filter(column.in_(val) if isinstance(val, (list, tuple, set)) else column == val)
    return q.scalar() or 0


def observe(bind, event: SecurityEvent) -> None:
    """Evaluate every rule this event can trigger."""
    db = Session(bind=bind)
    try:
        at = now()
        actor = event.actor_user_id
        et, reason = event.event_type, event.reason_code

        if et == "PDP_DENY" and (reason == "ACCESS_DENIED_OUT_OF_SCOPE"
                                 or (event.actor_role in ("super_admin", "support_operator", "platform_security")
                                     and (event.target_type or "").endswith(":worker"))):
            raise_alert(bind, "cross_tenant_access", dedupe_key=f"actor:{actor}",
                        summary=f"User #{actor} ({event.actor_role}) was refused {event.target_id} "
                                f"[{reason}] (event #{event.id})",
                        organization_id=event.organization_id)

        if (event.target_type or "").startswith("employee") and actor:
            spec = _rule(db, "employee_enumeration")
            since = at - timedelta(seconds=spec.window_seconds)
            distinct = (db.query(func.count(func.distinct(SecurityEvent.target_id)))
                        .filter(SecurityEvent.actor_user_id == actor, SecurityEvent.occurred_at >= since,
                                SecurityEvent.target_type.like("employee%")).scalar() or 0)
            if distinct >= spec.threshold:
                raise_alert(bind, "employee_enumeration", dedupe_key=f"actor:{actor}",
                            summary=f"User #{actor} touched {distinct} distinct employee records in "
                                    f"{spec.window_seconds // 60} minutes", organization_id=event.organization_id)

        if et == "EXPORT_COMPLETED":
            try:
                rows, size = (int(x) for x in (event.target_id or "0:0").split("|")[-1].split(":"))
            except ValueError:
                rows, size = 0, 0
            if rows >= LARGE_EXPORT_ROWS or size >= LARGE_EXPORT_BYTES:
                raise_alert(bind, "large_export", dedupe_key=f"actor:{actor}",
                            summary=f"User #{actor} exported {rows} rows / {size} bytes (event #{event.id})",
                            organization_id=event.organization_id)

        if et in ("SUPPORT_GRANTED", "SUPPORT_BREAK_GLASS_OPENED"):
            hour = at.astimezone(timezone.utc).hour
            outside = not (BUSINESS_HOURS_UTC[0] <= hour < BUSINESS_HOURS_UTC[1])
            if et == "SUPPORT_BREAK_GLASS_OPENED" or outside or not event.ticket_reference:
                raise_alert(bind, "unscheduled_elevation", dedupe_key=f"grant:{event.grant_id}",
                            summary=f"Grant #{event.grant_id} activated ({et}, {hour:02d}:00 UTC, "
                                    f"ticket {'present' if event.ticket_reference else 'missing'})",
                            organization_id=event.organization_id)

        if et in ("MFA_FAILED", "MFA_STEP_UP_FAILED") and actor:
            spec = _rule(db, "mfa_failures")
            since = at - timedelta(seconds=spec.window_seconds)
            n = _count_since(db, since, actor_user_id=actor, event_type=["MFA_FAILED", "MFA_STEP_UP_FAILED"])
            if n >= spec.threshold:
                raise_alert(bind, "mfa_failures", dedupe_key=f"actor:{actor}",
                            summary=f"User #{actor} failed MFA {n} times in {spec.window_seconds // 60} minutes")

        if et == "SUPPORT_BREAK_GLASS_REVIEW_OVERDUE":
            raise_alert(bind, "overdue_break_glass_review", dedupe_key=f"grant:{event.grant_id}",
                        summary=f"Break-glass grant #{event.grant_id} review is overdue",
                        organization_id=event.organization_id)

        if et == "MACHINE_CLIENT_NEW_NETWORK":
            raise_alert(bind, "machine_client_new_network", dedupe_key=f"client:{event.target_id}",
                        summary=f"Machine client {event.target_id} used from a new network",
                        organization_id=event.organization_id)
    finally:
        db.close()

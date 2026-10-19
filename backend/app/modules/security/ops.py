"""
modules/security/ops.py
-----------------------
Operational routines behind the ZP-PRIV scripts (kept here so they are
tested like any other code):

* ``run_alert_drill``      - fire every alert rule and collect delivery
                             receipts (E03; scripts/alert_drill.py)
* ``jml_reconcile``        - joiner / mover / leaver: deactivate, revoke
                             sessions, end grants, and report (E05;
                             scripts/jml_reconcile.py)

Both are idempotent and write only ids, rule keys and codes - never names
or emails - into their output.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session


def _z(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── Alert drill (E03) ───────────────────────────────────────────────────────

def _signal(db: Session, key: str, tag: str) -> None:
    """Drive the real detection path for one rule with synthetic ids."""
    from app.modules.security import alerts, events

    actor = 990000 + abs(hash(tag)) % 9999
    if key == "cross_tenant_access":
        events.emit(db, "PDP_DENY", result="deny", actor_user_id=actor, actor_role="super_admin",
                    target_type="employee:worker", target_id=f"drill:{tag}", reason_code="ROLE_NOT_PERMITTED")
    elif key == "employee_enumeration":
        for i in range(25):
            events.emit(db, "PRIVILEGED_READ", result="allow", actor_user_id=actor, actor_role="support_temp",
                        target_type="employee:worker", target_id=f"employee:drill-{tag}-{i}")
    elif key == "large_export":
        events.emit(db, "EXPORT_COMPLETED", result="allow", actor_user_id=actor, target_type="route:worker",
                    target_id=f"GET /drill/{tag}|0:20000000")
    elif key == "unscheduled_elevation":
        events.emit(db, "SUPPORT_BREAK_GLASS_OPENED", result="allow", actor_user_id=actor,
                    ticket_reference=f"DRILL-{tag}")
    elif key == "mfa_failures":
        for _ in range(5):
            events.emit(db, "MFA_FAILED", result="deny", actor_user_id=actor)
    elif key == "overdue_break_glass_review":
        events.emit(db, "SUPPORT_BREAK_GLASS_REVIEW_OVERDUE", result="allow", actor_user_id=actor)
    elif key == "machine_client_new_network":
        events.emit(db, "MACHINE_CLIENT_NEW_NETWORK", result="allow", target_id=f"client:drill-{tag}")
    else:
        alerts.raise_alert(db, key, dedupe_key=f"drill:{tag}", summary=f"DRILL: {key}", is_drill=True)


def run_alert_drill(db: Session, *, live: bool = False, tag: Optional[str] = None) -> dict:
    """Fire every rule. Synthetic mode drives the real detection path on a
    disposable database; ``live`` mode (a real deployment) only raises
    labelled drill alerts, so no fake security events enter the real log."""
    from app.modules.security import alerts
    from app.modules.security.models import AlertEvent

    alerts.ensure_rules(db)
    tag = tag or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = alerts.now() - timedelta(seconds=1)
    results = []
    for spec in alerts.RULES:
        if live:
            alerts.raise_alert(db, spec.key, dedupe_key=f"drill:{tag}", is_drill=True,
                               summary=f"DRILL: scheduled alert drill for {spec.key}")
        else:
            _signal(db, spec.key, tag)
        db.expire_all()
        row = (db.query(AlertEvent).filter(AlertEvent.rule_key == spec.key, AlertEvent.last_seen >= started)
               .order_by(AlertEvent.id.desc()).first())
        results.append({"rule": spec.key, "severity": spec.severity, "fired": row is not None,
                        "alertId": row.id if row else None, "count": row.count if row else 0,
                        "deliveryReceipt": row.delivery_receipt if row else None,
                        "deliveredAt": _z(row.delivered_at) if row else None})
    return {"tag": tag, "mode": "live" if live else "synthetic", "ranAt": _z(datetime.now(timezone.utc)),
            "rules": results, "allFired": all(r["fired"] for r in results),
            "allDelivered": all(r["deliveryReceipt"] for r in results)}


# ── Joiner / mover / leaver (E05) ───────────────────────────────────────────

LEAVER, MOVER, INCIDENT, GRANT_EXPIRY = "leaver", "mover", "incident", "grant_expiry"
EVENT_TYPES = (LEAVER, MOVER, INCIDENT, GRANT_EXPIRY)


def jml_reconcile(db: Session, hr_events: Iterable[dict], *, apply: bool = False) -> dict:
    """``hr_events``: [{"email"|"user_id", "event": leaver|mover|incident|grant_expiry,
    "new_role"?: str}]. Dry run unless ``apply``. Re-running is a no-op for
    users already handled."""
    from app.modules.auth.models import User, UserRole
    from app.modules.auth.service import revoke_user_sessions
    from app.modules.security import events as security_events
    from app.modules.support_access import models as SM
    from app.modules.support_access import service as support

    rows: List[dict] = []
    for item in hr_events:
        kind = str(item.get("event") or "").lower()
        q = db.query(User)
        user = (q.filter(User.id == int(item["user_id"])).first() if item.get("user_id")
                else q.filter(User.email == str(item.get("email") or "").strip().lower()).first())
        row = {"userId": user.id if user else None, "event": kind, "actions": [], "status": "ok"}
        if kind not in EVENT_TYPES:
            row["status"] = "rejected: unknown event"
            rows.append(row)
            continue
        if user is None:
            row["status"] = "no matching account"
            rows.append(row)
            continue
        live = (db.query(SM.SupportAccessGrant)
                .filter(SM.SupportAccessGrant.requested_by_user_id == user.id,
                        SM.SupportAccessGrant.status.in_(SM.LIVE_STATUSES)).all())
        if kind in (LEAVER, INCIDENT):
            if user.is_active:
                row["actions"].append("deactivate")
            row["actions"].append("revoke_sessions")
        if kind == MOVER:
            new_role = str(item.get("new_role") or "").lower()
            if new_role and new_role != getattr(user.role, "value", user.role):
                if new_role not in {r.value for r in UserRole}:
                    row["status"] = "rejected: unknown role"
                    rows.append(row)
                    continue
                row["actions"] += [f"role:{new_role}", "revoke_sessions"]
        if live:
            row["actions"].append(f"end_grants:{len(live)}")
        if apply and row["actions"]:
            if "deactivate" in row["actions"]:
                user.is_active = False
            for action in row["actions"]:
                if action.startswith("role:"):
                    user.role = UserRole(action.split(":", 1)[1])
            db.commit()
            for grant in live:
                support._end(db, grant, SM.REVOKED, support.EV_REVOKED, actor=None,
                             reason=f"Joiner/mover/leaver: {kind}")
            if "revoke_sessions" in row["actions"]:
                revoke_user_sessions(db, user.id, f"jml_{kind}")
            security_events.emit(db, "JML_APPLIED", result="allow", actor_user_id=None,
                                 target_type="user", target_id=f"user:{user.id}", action=kind,
                                 reason_code=",".join(a.split(":")[0] for a in row["actions"]).upper()[:120])
        rows.append(row)
    return {"applied": apply, "ranAt": _z(datetime.now(timezone.utc)), "results": rows,
            "summary": {"events": len(rows), "withActions": sum(1 for r in rows if r["actions"]),
                        "unmatched": sum(1 for r in rows if r["status"] != "ok")}}

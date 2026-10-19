"""
modules/security/machine_clients.py
-----------------------------------
Tenant-pinned machine clients (API keys) and signed outbound webhooks
(ZP-PRIV D06).

Credential: ``zpmc_<client_key>.<secret>``. Only an HMAC-SHA256 of the secret
(keyed by the app secret) is stored; the secret is shown once at creation or
rotation. Every client is pinned to one organization, carries least-privilege
scopes from SCOPES (no wildcard), must expire (max 365 days), and rotation or
revocation takes effect immediately.

A machine principal goes through the same PDP as people: it may only call the
routes its scopes map to, read-only, inside its own organization, with field
projection (scopes say which field classes); a request that names any other
tenant is refused and audited. Use from a network the client never used
before raises an alert.

Outbound webhooks are signed (``Zoiko-Signature: t=<unix>,v1=<hmac>`` over
``t.event_id.body``), carry ``Zoiko-Event-Id`` for idempotency, are refused
outside a 5-minute tolerance or on a replayed event id, and are tenant-pinned:
a payload for another organization is never delivered to an endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core import secretbox
from app.core.exceptions import BadRequestException, NotFoundException, UnauthorizedException

PREFIX = "zpmc_"
MAX_LIFETIME_DAYS = 365
WEBHOOK_TOLERANCE_SECONDS = 300

# scope -> (routes it opens, field classes it may read). Read-only by design.
SCOPES: Dict[str, Tuple[FrozenSet[Tuple[str, str]], FrozenSet[str]]] = {
    "employees:read": (frozenset({("GET", "/api/payroll/employees"), ("GET", "/api/payroll/employees/{employee_id}")}),
                       frozenset({"identifier", "contact"})),
    "payroll_runs:read": (frozenset({("GET", "/api/payroll/runs"), ("GET", "/api/payroll/runs/{run_id}")}),
                          frozenset()),
    "reports:read": (frozenset({("GET", "/api/payroll/generated-reports")}), frozenset({"identifier"})),
}
WEBHOOK_EVENTS = frozenset({"payroll_run.approved", "payroll_run.paid", "employee.created", "employee.updated"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_secret(secret: str) -> str:
    return hmac.new(settings.PAYROLL_SECRET_KEY.encode(), secret.encode(), hashlib.sha256).hexdigest()


def validate_scopes(scopes: Iterable[str]) -> List[str]:
    scopes = sorted(set(scopes or []))
    if not scopes:
        raise BadRequestException("Choose at least one scope.")
    unknown = [s for s in scopes if s not in SCOPES]
    if unknown or any("*" in s for s in scopes):
        raise BadRequestException(f"Unknown scope(s) {unknown}. Allowed: {sorted(SCOPES)} (no wildcards).")
    return scopes


@dataclass
class MachinePrincipal:
    """What get_current_user returns for a machine credential. No user row:
    ``id`` is None, so nothing can be attributed to a person by mistake."""
    client_id: int
    organization_id: int
    scopes: FrozenSet[str]
    name: str
    role: str = "machine_client"
    id: Optional[int] = None
    email: Optional[str] = None
    is_active: bool = True
    is_temporary: bool = False
    support_grant_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    extra: dict = field(default_factory=dict)

    def allowed_routes(self) -> FrozenSet[Tuple[str, str]]:
        out = set()
        for s in self.scopes:
            out |= SCOPES[s][0]
        return frozenset(out)

    def field_classes(self) -> FrozenSet[str]:
        out = set()
        for s in self.scopes:
            out |= SCOPES[s][1]
        return frozenset(out)


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def create_client(db: Session, owner, *, name: str, scopes: Iterable[str], expires_in_days: int) -> dict:
    from app.modules.security.models import MachineClient

    name = (name or "").strip()
    if not name:
        raise BadRequestException("A name is required.")
    if not 1 <= int(expires_in_days) <= MAX_LIFETIME_DAYS:
        raise BadRequestException(f"Expiry must be between 1 and {MAX_LIFETIME_DAYS} days.")
    secret = _new_secret()
    client = MachineClient(organization_id=owner.organization_id, name=name, owner_user_id=owner.id,
                           client_key=secrets.token_hex(8), scopes=validate_scopes(scopes),
                           secret_hash=_hash_secret(secret), created_at=_now(),
                           expires_at=_now() + timedelta(days=int(expires_in_days)), known_networks=[])
    db.add(client)
    db.commit()
    db.refresh(client)
    return {"client": client, "credential": f"{PREFIX}{client.client_key}.{secret}"}


def _own(db: Session, owner, client_id: int):
    from app.modules.security.models import MachineClient

    row = db.query(MachineClient).filter(MachineClient.id == client_id).first()
    if row is None or row.organization_id != owner.organization_id:
        raise NotFoundException("API client")
    return row


def rotate_client(db: Session, owner, client_id: int) -> dict:
    row = _own(db, owner, client_id)
    if row.revoked_at is not None:
        raise BadRequestException("A revoked client cannot be rotated.")
    secret = _new_secret()
    row.secret_hash = _hash_secret(secret)
    row.rotated_at = _now()
    db.commit()
    return {"client": row, "credential": f"{PREFIX}{row.client_key}.{secret}"}


def revoke_client(db: Session, owner, client_id: int):
    row = _own(db, owner, client_id)
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()
    return row


def _network(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


def resolve(db: Session, credential: str, ip: Optional[str] = None) -> MachinePrincipal:
    """Validate a machine credential (constant-time) and return its principal."""
    from app.modules.security import events as security_events
    from app.modules.security.models import MachineClient

    try:
        key, secret = credential[len(PREFIX):].split(".", 1)
    except ValueError:
        raise UnauthorizedException("Invalid API credential.")
    row = db.query(MachineClient).filter(MachineClient.client_key == key).first()
    if row is None or not hmac.compare_digest(row.secret_hash, _hash_secret(secret)):
        raise UnauthorizedException("Invalid API credential.")
    if row.revoked_at is not None:
        raise UnauthorizedException("This API credential has been revoked.")
    if _aware(row.expires_at) <= _now():
        raise UnauthorizedException("This API credential has expired.")
    net = _network(ip)
    known = list(row.known_networks or [])
    if net and net not in known:
        if known:  # the first network is the baseline; a later new one alerts
            security_events.emit(db, "MACHINE_CLIENT_NEW_NETWORK", result="allow", actor_role="machine_client",
                                 organization_id=row.organization_id, target_type="machine_client",
                                 target_id=f"client:{row.id}")
        known.append(net)
        row.known_networks = known[-20:]
    row.last_used_at = _now()
    row.last_used_ip = ip
    db.commit()
    return MachinePrincipal(client_id=row.id, organization_id=row.organization_id, scopes=frozenset(row.scopes),
                            name=row.name, owner_user_id=row.owner_user_id)


# ── Outbound webhooks ───────────────────────────────────────────────────────

def create_webhook(db: Session, owner, *, url: str, events: Iterable[str]) -> dict:
    from app.modules.security.models import WebhookEndpoint

    url = (url or "").strip()
    if not url.startswith("https://"):
        raise BadRequestException("Webhook URLs must use https://")
    events = sorted(set(events or []))
    if not events or any(e not in WEBHOOK_EVENTS for e in events):
        raise BadRequestException(f"Events must be chosen from {sorted(WEBHOOK_EVENTS)}.")
    secret = "whsec_" + secrets.token_urlsafe(32)
    row = WebhookEndpoint(organization_id=owner.organization_id, url=url, events=events,
                          signing_secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
                          signing_secret_encrypted=secretbox.encrypt(secret, "webhook-signing"),
                          created_by_user_id=owner.id, status="active")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"endpoint": row, "signingSecret": secret}


def sign(secret: str, event_id: str, body: bytes, timestamp: Optional[int] = None) -> str:
    ts = int(timestamp if timestamp is not None else _now().timestamp())
    mac = hmac.new(secret.encode(), f"{ts}.{event_id}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, header: str, event_id: str, body: bytes, *, seen_event_ids: set,
           now: Optional[datetime] = None) -> bool:
    """Receiver-side check (also used by tests): signature, tolerance, replay."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    current = (now or _now()).timestamp()
    if abs(current - ts) > WEBHOOK_TOLERANCE_SECONDS or event_id in seen_event_ids:
        return False
    expected = sign(secret, event_id, body, ts).split("v1=", 1)[1]
    if not hmac.compare_digest(expected, parts.get("v1", "")):
        return False
    seen_event_ids.add(event_id)
    return True


def build_delivery(db: Session, endpoint, event_type: str, payload: dict) -> dict:
    """Prepare (and record) one signed delivery. Tenant-pinned: refuses a
    payload that belongs to another organization. Returns url, headers, body
    for the transport (core/outbound.py decides whether it may be sent)."""
    from app.modules.security.models import WebhookDelivery

    if payload.get("organizationId") != endpoint.organization_id:
        raise BadRequestException("Webhook payload organization does not match the endpoint (tenant-pinned).")
    if event_type not in (endpoint.events or []) or endpoint.status != "active":
        raise BadRequestException("This endpoint is not subscribed to that event.")
    event_id = secrets.token_hex(16)
    body = json.dumps({"id": event_id, "type": event_type, "data": payload}, sort_keys=True).encode()
    secret = secretbox.decrypt(endpoint.signing_secret_encrypted, "webhook-signing")
    db.add(WebhookDelivery(endpoint_id=endpoint.id, organization_id=endpoint.organization_id, event_id=event_id,
                           event_type=event_type, status="prepared"))
    db.commit()
    return {"url": endpoint.url, "body": body,
            "headers": {"Content-Type": "application/json", "Zoiko-Event-Id": event_id,
                        "Zoiko-Signature": sign(secret, event_id, body)}}
